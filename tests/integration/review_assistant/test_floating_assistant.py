"""Floating assistant backend: case-insensitive entity resolution, inline completion forms without extra model calls,
context-hash / cross-run validation, deterministic draft QA, run summary, attention and UI state."""
import json

import pytest

from tcp_planner.review.assistant.core import entity_resolution as ER
from .conftest import call, login
from .test_phase4_versions import conv
from .test_phase8_interpretation import intent, model, msg, op  # noqa: F401  (fixture re-export)


# ---------------------------------------------------------------- resolver (unit)
@pytest.mark.parametrize("ref,expected,method", [
    ("S1", "S1", "EXACT"), ("s1", "S1", "CASE_INSENSITIVE"), ("s2", "S2", "CASE_INSENSITIVE"),
    ("  s1 ", "S1", "CASE_INSENSITIVE"), ("S 1", "S1", "ID_FORMAT_NORMALIZED"), ("s  2", "S2", "ID_FORMAT_NORMALIZED"),
    ("ｓ１", "S1", "CASE_INSENSITIVE"),  # full-width characters: Unicode NFKC
])
def test_resolver_case_insensitive(ref, expected, method):
    r = ER.resolve(ref, ["W1", "S1", "S2"])
    assert r["resolved_entity_id"] == expected and r["resolution_method"] == method and r["original_reference"] == ref


def test_resolver_no_punctuation_folding_and_collisions():
    assert ER.resolve("CONE1", ["CONE-1"])["resolution_method"] == "NOT_FOUND"     # punctuation never removed
    r = ER.resolve("ab1", ["Ab1", "AB1"])
    assert r["resolution_method"] == "AMBIGUOUS" and r["candidates"] == ["AB1", "Ab1"] and r["resolved_entity_id"] is None
    assert ER.resolve("AB1", ["Ab1", "AB1"])["resolution_method"] == "EXACT"       # exact match first
    assert ER.resolve("S3", ["S1", "S2"])["resolution_method"] == "NOT_FOUND"


# ---------------------------------------------------------------- NL: "Move s1 100ft" -> S1, form for direction, no 2nd call
def test_move_lowercase_id_resolves_and_form_completes_without_model_call(aenv, runs, model):
    from tcp_planner.review.assistant.text_model import provider as MP
    from tcp_planner.review.assistant.services.container import container
    t, cid = conv(runs, "supported")
    model["response"] = intent([op("MOVE_DEVICE", "s1", distance=100, unit="FT")], needs_clarification=True,
                               missing_information=["direction"])
    st, _, r = msg(t, cid, "Move s1 100ft")
    assert st == 200 and len(MP.CALLS) == 1
    row = r["operations"][0]
    assert row["resolution"]["resolved_entity_id"] == "S1" and row["resolution"]["resolution_method"] == "CASE_INSENSITIVE"
    assert "does not exist" not in (row["clarification"] or {}).get("message", "")
    f = row["form"]
    assert f["title"] == "Complete movement request" and f["known"] == {"object_id": "S1", "distance": 100, "unit": "FT"}
    assert [x["name"] for x in f["fields"]] == ["direction", "preserve_lateral_offset"] and f["ai_calls_on_submit"] == 0
    # incomplete / invalid values are rejected deterministically
    assert call("POST", f"conversations/{cid}/forms/submit", {"interpretation_id": r["interpretation_id"], "op_index": 0,
                                                              "values": {}}, token=t)[2]["error_code"] == "FORM_INCOMPLETE"
    assert call("POST", f"conversations/{cid}/forms/submit", {"interpretation_id": r["interpretation_id"], "op_index": 0,
                "values": {"direction": "SIDEWAYS"}}, token=t)[2]["error_code"] == "FORM_INVALID"
    st, _, res = call("POST", f"conversations/{cid}/forms/submit", {"interpretation_id": r["interpretation_id"], "op_index": 0,
                      "values": {"direction": "UPSTREAM", "preserve_lateral_offset": True}}, token=t)
    assert st == 200 and res["model_call"] is False and len(MP.CALLS) == 1          # still exactly one model call
    m = res["evaluation"]["movement"]
    assert m["object_id"] == "S1" and m["actual_along_alignment_ft"] == 100.0 and m["reference"]["original_reference"] == "S1"
    v = call("GET", f"conversations/{cid}", token=t)[2]
    res_msg = next(x for x in v["messages"] if x["message_id"] == res["message_id"])
    assert res_msg["kind"] in ("DETERMINISTIC_RESULT", "CONFLICT_RESULT") and res_msg["body"]["object_id"] == "S1"
    # stage with the evaluated payload -> canonical id in the change set
    st, _, sr = call("POST", f"conversations/{cid}/placements", {**res_msg["body"]["stage_payload"], "reason": "sight line"}, token=t)
    assert st == 200 and [x["key"] for x in sr["staged"]] == ["ADJUST:S1"] and len(MP.CALLS) == 1
    evs = container().audit.read(cid)
    interp = next(e for e in evs if e["event_type"] == "INTERPRETATION")
    assert interp["entity_resolutions"][0] == {"original_reference": "s1", "normalized_reference": "S1",
                                              "resolved_entity_id": "S1", "resolution_method": "CASE_INSENSITIVE"}
    assert not any("Move s1 100ft" in json.dumps(e) for e in evs)                  # full text only in the conversation


def test_button_path_resolves_case_insensitively(aenv, runs):
    t, cid = conv(runs, "supported")
    st, _, r = call("POST", f"conversations/{cid}/placements/evaluate", {"object_id": "s2", "direction": "UPSTREAM",
                                                                         "distance": 10, "unit": "FT"}, token=t)
    assert st == 200 and r["evaluation"]["movement"]["object_id"] == "S2"
    assert r["evaluation"]["movement"]["reference"]["resolution_method"] == "CASE_INSENSITIVE"


def test_unknown_object_form_offers_create_and_never_auto_maps(aenv, runs, model):
    from tcp_planner.review.assistant.text_model import provider as MP
    t, cid = conv(runs, "supported")
    model["response"] = intent([op("MOVE_DEVICE", "s3", direction="UPSTREAM", distance=50, unit="FT")])
    r = msg(t, cid, "Move s3 50 ft upstream")[2]
    row = r["operations"][0]
    assert row["status"] == "NEEDS_CLARIFICATION" and row["structured"] is None
    opts = [o["value"] for o in row["form"]["fields"][0]["options"]]
    assert opts == ["S1", "S2", "__CREATE__:S3"]
    res = call("POST", f"conversations/{cid}/forms/submit", {"interpretation_id": r["interpretation_id"], "op_index": 0,
                                                             "values": {"object_id": "__CREATE__:S3"}}, token=t)[2]
    assert res == {"open_object_form": "S3", "model_call": False} and len(MP.CALLS) == 1


def test_relative_and_fact_forms(aenv, runs, model):
    from tcp_planner.review.assistant.text_model import provider as MP
    t, cid = conv(runs, "missing_road_type")
    model["response"] = intent([op("SET_SITE_FACT", "road.road_type", value_text="the county kind")])
    r = msg(t, cid, "set the road type")[2]
    f = r["operations"][0]["form"]
    assert f["target"] == "decisions" and f["fields"][0]["name"] == "value"
    res = call("POST", f"conversations/{cid}/forms/submit", {"interpretation_id": r["interpretation_id"], "op_index": 0,
                                                             "values": {"value": "RURAL", "reason": "county records"}}, token=t)[2]
    assert res["staged"] == "FACT:road.road_type" and len(MP.CALLS) == 1
    v = call("GET", f"conversations/{cid}", token=t)[2]
    assert v["staged"][0]["value"] == "RURAL" and v["staged"][0]["message_id"] == r["message"]["message_id"]


# ---------------------------------------------------------------- context hash / cross-run / stale
def test_context_validation(aenv, runs):
    t, cid = conv(runs, "missing_road_type")
    ctx = call("GET", f"conversations/{cid}/context", token=t)[2]["context"]
    assert set(ctx) >= {"run_id", "conversation_id", "site_evidence_version", "plan_version", "context_hash"}
    body = {"type": "FACT", "field": "road.road_type", "action": "CORRECT", "value": "RURAL", "reason": "x"}
    st, _, r = call("POST", f"conversations/{cid}/decisions", {**body, "context": {**ctx, "run_id": runs["supported"]}}, token=t)
    assert st == 409 and r["error_code"] == "CROSS_RUN_REJECTED"
    st, _, r = call("POST", f"conversations/{cid}/decisions", {**body, "context": {**ctx, "plan_version": "tcp-plan-x-v9"}}, token=t)
    assert st == 409 and r["error_code"] == "STALE_CONTEXT"
    st, _, r = call("POST", f"conversations/{cid}/decisions", {**body, "context": {**ctx, "conversation_id": "conv-other"}}, token=t)
    assert st == 409 and r["error_code"] == "CONVERSATION_MISMATCH"
    st, _, r = call("POST", f"conversations/{cid}/decisions", {**body, "context": ctx}, token=t)
    assert st == 200
    # after a confirmation the site-evidence version moves: the old context becomes stale
    rv = call("GET", f"conversations/{cid}/review", token=t)[2]
    call("POST", f"conversations/{cid}/confirm", {"review_sha256": rv["review_sha256"], "mode": "SAVE_SITE_FACTS_ONLY", "context": ctx}, token=t)
    st, _, r = call("POST", f"conversations/{cid}/decisions", {**body, "context": ctx}, token=t)
    assert st == 409 and r["error_code"] == "STALE_CONTEXT"


# ---------------------------------------------------------------- deterministic draft QA
def test_draft_qa_is_deterministic(aenv, runs, model):
    from tcp_planner.review.assistant.text_model import provider as MP
    t, cid = conv(runs, "driveway_at_sign")
    for qid in ("WHY_BLOCKING", "WHAT_RERUNS", "AZURE_CALLED", "ARTIFACTS_REUSED", "VALIDATOR_RESULT", "VERSION_DIFF", "TA_STATUS"):
        st, _, r = call("POST", f"conversations/{cid}/ask", {"question_id": qid}, token=t)
        assert st == 200 and r["model_call"] is False and r["answer"], qid
    assert "GEO-DRIVEWAY-INTERSECTION-CONFLICT" in call("POST", f"conversations/{cid}/ask", {"question_id": "VALIDATOR_RESULT"}, token=t)[2]["answer"]
    assert call("POST", f"conversations/{cid}/ask", {"question_id": "AZURE_CALLED"}, token=t)[2]["answer"].startswith("No.")
    for text in ("Will Azure Maps be called?", "What step will rerun?", "What artifacts are reused?"):
        r = msg(t, cid, text)[2]
        assert r["status"] == "ANSWERED" and r["model_call"] is False
    assert len(MP.CALLS) == 0
    assert call("POST", f"conversations/{cid}/ask", {"question_id": "TELL_ME_A_JOKE"}, token=t)[0] == 400


# ---------------------------------------------------------------- launcher summary / attention / ui state
def test_run_summary_does_not_create_conversation(aenv, runs):
    from tcp_planner.review.assistant.services.container import container
    t = login()
    s = call("GET", f"runs/{runs['driveway_at_sign']}/assistant-summary", token=t)[2]
    assert s["eligible"] and s["latest_conversation_id"] is None and container().store.list("conversations") == []
    assert s["attention"]["counts"]["BLOCKING"] >= 1 and s["attention"]["blocking_ids"]
    s2 = call("GET", f"runs/{runs['supported']}/assistant-summary", token=t)[2]
    assert s2["attention"]["counts"]["BLOCKING"] == 0


def test_attention_ui_state_and_run_scoped_conversations(aenv, runs):
    t, cid = conv(runs, "supported")
    a = call("GET", f"conversations/{cid}/attention", token=t)[2]
    assert a["attention"]["counts"]["BLOCKING"] == 0 and a["ui_state"]["acknowledged_blocking"] == []
    call("POST", f"conversations/{cid}/placements", {"object_id": "S1", "direction": "UPSTREAM", "distance": 10, "unit": "FT",
                                                     "reason": "x"}, token=t)
    a = call("GET", f"conversations/{cid}/attention", token=t)[2]["attention"]
    kinds = {i["kind"] for i in a["items"] if i["category"] == "BLOCKING"}
    assert "EXCEPTION_DECISION" in kinds                                  # spacing conflict needs a decision
    st, _, u = call("POST", f"conversations/{cid}/ui-state", {"acknowledged_blocking": a["blocking_ids"]}, token=t)
    assert call("GET", f"conversations/{cid}/attention", token=t)[2]["ui_state"]["acknowledged_blocking"] == a["blocking_ids"]
    assert [c["conversation_id"] for c in call("GET", "conversations", token=t, ) [2]["conversations"]] == [cid]
    from tcp_planner.review.assistant import routes as api
    st, _, lst = api.dispatch("GET", ["conversations"], {"run_id": [runs["four_lane"]]}, None, {"X-TCP-Session": t})
    assert lst["conversations"] == []                                     # another run's conversation is never applied


def test_accepted_exceptions_are_not_blocking_after_regeneration(aenv, runs, monkeypatch):
    """A regenerated DRAFT_WITH_ENGINEERING_EXCEPTION must not show its accepted conflicts as new blocking items."""
    from tcp_planner.review.assistant.services import pipeline_controller
    from tests.integration.web_api import inproc
    monkeypatch.setattr(pipeline_controller, "LAUNCHER", lambda rid, rdir: inproc.run(rdir))
    t, cid = conv(runs, "supported")
    mv = {"object_id": "S1", "direction": "UPSTREAM", "distance": 10, "unit": "FT"}
    assert call("POST", f"conversations/{cid}/placements/evaluate", mv, token=t)[0] == 200
    call("POST", f"conversations/{cid}/placements", {**mv, "reason": "x"}, token=t)
    for chk in ("VAL-SPACING", "GEO-STATION"):
        call("POST", f"conversations/{cid}/exceptions", {"type": "RULE_CONFLICT", "check_id": chk, "reason": "field adj",
                                                         "confirm_exception": True}, token=t)
    rv = call("GET", f"conversations/{cid}/review", token=t)[2]
    assert call("POST", f"conversations/{cid}/confirm", {"review_sha256": rv["review_sha256"], "mode": "CONFIRM_AND_REGENERATE"}, token=t)[0] == 200
    v = call("GET", f"conversations/{cid}", token=t)[2]
    assert v["plan"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    rc = {f["subject"]: f for f in v["findings"] if f["category"] == "RULE_CHECK"}
    assert rc["VAL-SPACING"]["state"] == "SME_EXCEPTION" and rc["VAL-SPACING"]["rule_status"] == "CONFLICT"
    att = call("GET", f"conversations/{cid}/attention", token=t)[2]["attention"]
    assert att["counts"]["BLOCKING"] == 0 and att["counts"]["WARNING"] >= 2
    kinds = [m["kind"] for m in v["messages"]]
    for k in ("CONFLICT_RESULT", "FINAL_REVIEW", "CONFIRMATION", "VERSION_RESULT", "PIPELINE_STATUS"):
        assert k in kinds, k


def test_delete_session_archives_without_erasing(aenv, runs):
    from tcp_planner.review.assistant.services.container import container
    t, cid = conv(runs, "supported")
    call("POST", f"conversations/{cid}/placements", {"object_id": "S1", "direction": "UPSTREAM", "distance": 10, "unit": "FT", "reason": "x"}, token=t)
    t2, cid2 = conv(runs, "supported")
    aud = login("aud.1")
    assert call("POST", f"conversations/{cid}/archive", {}, token=aud)[0] == 403              # auditors cannot delete
    st, _, r = call("POST", f"conversations/{cid}/archive", {"reason": "duplicate"}, token=t)
    assert st == 200 and r["archived"]["staged_discarded"] == 1
    lst = call("GET", f"runs/{runs['supported']}/assistant-summary", token=t)[2]
    assert [c["conversation_id"] for c in lst["conversations"]] == [cid2] and lst["latest_conversation_id"] == cid2
    st, _, r = call("POST", f"conversations/{cid}/decisions", {"type": "FACT", "field": "road.lane_count", "action": "CONFIRM"}, token=t)
    assert st == 409 and r["error_code"] == "SESSION_ARCHIVED"                                 # no writes afterwards
    assert container().store.get("conversations", cid)                                         # record kept
    assert any(e["event_type"] == "SESSION_ARCHIVED" for e in container().audit.read(cid))
    assert call("GET", f"conversations/{cid}", token=t)[0] == 200                             # still readable for audit
    assert call("POST", f"conversations/{cid}/archive", {}, token=t)[0] == 409
