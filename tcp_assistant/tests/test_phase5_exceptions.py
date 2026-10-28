import json, os

import pytest

from .conftest import call, login
from .test_phase4_versions import inproc_launch, conv, review, stage_fact, confirm, out  # noqa: F401


def exc(t, cid, **p):
    return call("POST", f"conversations/{cid}/exceptions", p, token=t)


def test_rule_conflict_exception_end_to_end(aenv, runs, inproc_launch, monkeypatch):
    monkeypatch.setenv("TCP_RENDER_SHEET", "1")  # existing test conftests disable sheet rendering globally
    t, cid = conv(runs, "driveway_at_sign")
    st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id="GEO-DRIVEWAY-INTERSECTION-CONFLICT",
                   reason="driveway is a closed field access; sign position field-verified", confirm_exception=True)
    assert st == 200, r
    ex = r["exception"]
    assert ex["approval_mode"] == "SELF_CONFIRMED_POC" and ex["independent_approval"] is False
    assert ex["requested_by"] == ex["confirmed_by"] == "sme.1" and ex["rule_status"] == "CONFLICT"
    assert ex["scope"] == "THIS_PLAN_VERSION_ONLY" and ex["object_ids"] == ["S1"]
    p = r["preview"]
    assert p["plan_outcome"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    geo = next(x for x in p["rules"] if x["check_id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT")
    assert geo["proposed"] == "FAIL" and geo["rule_status_proposed"] == "CONFLICT"          # never turned into PASS
    d = next(x for x in p["dispositions"]["dispositions"] if x["check_id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT")
    assert d["disposition"] == "ACCEPTED_WITH_SME_OVERRIDE" and d["validator_result"] == "FAIL"
    rv = review(t, cid)
    assert rv["review"]["exceptions"][0]["exception_id"] == ex["exception_id"]
    st, _, res = confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")
    assert st == 200, res
    child = res["resume_attempt"]["run_id"]
    v = call("GET", f"conversations/{cid}", token=t)[2]
    pv = call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]
    assert pv["current_status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION" and pv["active_exceptions"] == [ex["exception_id"]]
    plan = out(aenv, child, "plan.json"); val = out(aenv, child, "validation_results.json")
    assert plan["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION" and "ENGINEERING EXCEPTION" in plan["disclaimer"]
    assert plan["sme_dispositions"]["active_exceptions"][0]["exception_id"] == ex["exception_id"]
    assert val["geometry_validation"]["status"] == "FAIL"                                   # validator output unchanged
    assert next(c for c in val["geometry_validation"]["checks"] if c["id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT")["status"] == "FAIL"
    from tcp_planner.storage import run_store as store
    st_ = store.build_state(child)
    assert st_["decision"] == "DRAFT_WITH_ENGINEERING_EXCEPTION" and st_["draft_generated"] and st_["exit_code"] == 5
    assert os.path.exists(aenv / "runs" / child / "output" / "tcp_sheet.png")
    assert os.path.exists(aenv / "runs" / child / "output" / "debug_plan.png")
    from tcp_planner.sheets.sme_exception_text import exception_lines
    assert any("SELF-CONFIRMED" in x for x in exception_lines(plan))
    # exceptions are this-version-only: not carried into the next proposal
    assert call("GET", f"conversations/{cid}/preview", token=t)[2]["preview"]["plan_outcome"]["status"] == "BLOCKED"


def test_exception_requires_reason_confirmation_role_and_policy(aenv, runs, tmp_path, monkeypatch):
    t, cid = conv(runs, "driveway_at_sign")
    st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id="GEO-DRIVEWAY-INTERSECTION-CONFLICT", reason="x")
    assert st == 400 and r["error_code"] == "EXCEPTION_NOT_CONFIRMED"
    st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id="GEO-DRIVEWAY-INTERSECTION-CONFLICT", confirm_exception=True)
    assert st == 400 and r["error_code"] == "REASON_REQUIRED"
    st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id="VAL-SPACING", reason="x", confirm_exception=True)
    assert st == 409 and r["error_code"] == "EXCEPTION_NOT_APPLICABLE"                      # does not fail
    aud = login("aud.1")
    st, _, r = exc(aud, cid, type="RULE_CONFLICT", check_id="GEO-DRIVEWAY-INTERSECTION-CONFLICT", reason="x", confirm_exception=True)
    assert st == 403
    # master switch off -> exceptions unavailable; normal corrections still allowed
    from tcp_planner.review import action_policy as P
    doc = json.load(open(P.POLICY_PATH, encoding="utf-8")); doc["sme_exceptions_enabled"] = False
    doc["content_sha256"] = P.policy_hash(doc); pth = tmp_path / "pol.json"; pth.write_text(json.dumps(doc))
    monkeypatch.setenv("TCP_SME_ACTION_POLICY", str(pth))
    st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id="GEO-DRIVEWAY-INTERSECTION-CONFLICT", reason="x", confirm_exception=True)
    assert st == 403 and r["error_code"] == "POLICY_DENIED"
    assert stage_fact(t, cid, "road.lane_count", "CONFIRM")["preview"]["plan_outcome"]["status"] == "BLOCKED"


def test_ta_exception_when_ta1_not_applicable(aenv, runs, inproc_launch):
    t, cid = conv(runs, "sidewalk")
    p = call("GET", f"conversations/{cid}/preview", token=t)[2]["preview"]
    assert p["ta"]["proposed"]["message"] == ("Current TA is no longer applicable. "
                                              "No alternative TA is available in the current approved rule pack.")
    assert p["ta"]["approved_candidates_found"] == []
    st, _, r = exc(t, cid, type="TA_NOT_APPLICABLE", reason="pedestrian detour handled separately", confirm_exception=True)
    assert st == 200, r
    assert r["exception"]["reason_codes"] == ["PEDESTRIAN_ROUTE_IMPACT"] and r["exception"]["candidate_tas"] == []
    # the TA exception covers TA applicability only; the remaining rule conflicts still block
    p = r["preview"]
    assert p["plan_outcome"]["status"] == "BLOCKED"
    remaining = [d["check_id"] for d in p["dispositions"]["dispositions"] if d["disposition"] == "BLOCKED"]
    assert remaining and "VAL-ELIGIBILITY" not in remaining
    for chk in remaining:
        st, _, r = exc(t, cid, type="RULE_CONFLICT", check_id=chk, reason="pedestrian route handled by separate plan",
                       confirm_exception=True)
        assert st == 200, r
    assert r["preview"]["plan_outcome"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    rv = review(t, cid)
    st, _, res = confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")
    child = res["resume_attempt"]["run_id"]
    call("GET", f"conversations/{cid}", token=t)
    plan, elig = out(aenv, child, "plan.json"), out(aenv, child, "eligibility_result.json")
    assert elig["decision"] == "UNSUPPORTED_POC"
    assert plan["template"]["id"] == "TA-1" and plan["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    val = out(aenv, child, "validation_results.json")
    assert next(c for c in val["rule_validation"]["checks"] if c["id"] == "VAL-ELIGIBILITY")["status"] == "FAIL"
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    assert len(plan["sme_dispositions"]["active_exceptions"]) == 1 + len(remaining)


def test_ta_exception_refused_for_unverified_geometry(aenv, runs):
    t, cid = conv(runs, "four_lane")
    st, _, r = exc(t, cid, type="TA_NOT_APPLICABLE", reason="x", confirm_exception=True)
    assert st == 409 and r["error_code"] == "ESSENTIAL_FACT_UNRESOLVED" and "CENTERLINE_UNRESOLVED" in r["message"]


def test_ta_exception_never_bypasses_unresolved_facts(aenv, runs):
    t, cid = conv(runs, "missing_road_type")
    st, _, r = exc(t, cid, type="TA_NOT_APPLICABLE", reason="x", confirm_exception=True)
    assert st == 409 and r["error_code"] in ("ESSENTIAL_FACT_UNRESOLVED", "EXCEPTION_NOT_APPLICABLE")


def test_pipeline_disposition_rejects_unauthorized_exception():
    from tcp_planner.conflicts import sme_disposition as SD
    from tcp_planner.review.action_policy import load_policy
    val = {"rule_validation": {"checks": []}, "geometry_validation": {"checks": [
        {"id": "GEO-DRIVEWAY-INTERSECTION-CONFLICT", "status": "FAIL", "detail": {"conflicts": [{"object": "S2"}]}},
        {"id": "GEO-IMAGE-EXTENT", "status": "FAIL", "detail": {"objects": ["S1"]}}]}}
    ex = {"exception_id": "e1", "type": "RULE_CONFLICT", "action": "override_rule_conflict", "check_id": "GEO-DRIVEWAY-INTERSECTION-CONFLICT",
          "object_ids": ["S2"], "reason": "r", "approval_mode": "SELF_CONFIRMED_POC", "confirmed_by": "x", "confirmed_by_roles": ["AUDITOR"]}
    ex2 = dict(ex, exception_id="e2", check_id="GEO-IMAGE-EXTENT", object_ids=["S1"], confirmed_by_roles=["SME_REVIEWER"])
    d = SD.evaluate(val, {"exceptions": [ex, ex2], "_policy": load_policy()}, {"decision": "SUPPORTED_AUTO"})
    rows = {r["check_id"]: r for r in d["dispositions"]}
    assert rows["GEO-DRIVEWAY-INTERSECTION-CONFLICT"]["disposition"] == "BLOCKED"        # role not authorized
    assert rows["GEO-IMAGE-EXTENT"]["disposition"] == "BLOCKED" and "OUTSIDE_EVIDENCE_COVERAGE" in rows["GEO-IMAGE-EXTENT"]["reason"]
    assert not d["all_accepted"] and d["plan_status"] is None


def test_final_review_offers_exception_resolution_and_unblocks(aenv, runs):
    """A blocked final review lists each conflict with a deterministic 'request exception' resolution."""
    t, cid = conv(runs, "supported")
    st, _, r = call("POST", f"conversations/{cid}/placements", {"object_id": "S1", "direction": "UPSTREAM", "distance": 10,
                                                                "unit": "FT", "reason": "sight line"}, token=t)
    assert st == 200, r
    rv = review(t, cid)["review"]
    res = [x for b in rv["blocking"] for x in b.get("resolutions", [])]
    assert {x["check_id"] for x in res} == {"VAL-SPACING", "GEO-STATION"} and all(x["can_request_exception"] for x in res)
    assert rv["eligibility"]["proposed"]["decision"] == "SUPPORTED_AUTO"
    for x in res:
        assert exc(t, cid, type="RULE_CONFLICT", check_id=x["check_id"], reason="field adjustment", confirm_exception=True)[0] == 200
    rv = review(t, cid)["review"]
    assert rv["blocking"] == [] and rv["modes"]["CONFIRM_AND_REGENERATE"]["available"]
