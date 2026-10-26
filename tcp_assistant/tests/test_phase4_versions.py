import json, os

import pytest

from .conftest import call, login, tree_hash


@pytest.fixture
def inproc_launch(monkeypatch):
    from tcp_assistant.services import pipeline_controller
    from tcp_ui.tests import inproc
    launched = []

    def launch(rid, rdir):
        launched.append(rid); inproc.run(rdir)
    monkeypatch.setattr(pipeline_controller, "LAUNCHER", launch)
    return launched


def conv(runs, sc):
    t = login()
    st, _, v = call("POST", "conversations", {"run_id": runs[sc]}, token=t)
    assert st == 201, v
    return t, v["conversation"]["conversation_id"]


def review(t, cid):
    st, _, r = call("GET", f"conversations/{cid}/review", token=t)
    assert st == 200, r
    return r


def stage_fact(t, cid, field, action, value=None, reason="field verification"):
    p = {"type": "FACT", "field": field, "action": action, "reason": reason}
    if value is not None: p["value"] = value
    st, _, r = call("POST", f"conversations/{cid}/decisions", p, token=t)
    assert st == 200, r
    return r


def confirm(t, cid, r, mode, token=None):
    return call("POST", f"conversations/{cid}/confirm", {"review_sha256": r["review_sha256"], "mode": mode}, token=token or t)


def out(aenv, rid, name):
    p = aenv / "runs" / rid / "output" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def events(rdir):
    with open(os.path.join(rdir, "ui", "events.jsonl"), encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def test_confirm_and_regenerate_end_to_end(aenv, runs, inproc_launch):
    parent = runs["missing_road_type"]
    before = tree_hash(aenv / "runs" / parent)
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL", "county road records")
    r = review(t, cid); rv = r["review"]
    assert rv["modes"]["CONFIRM_AND_REGENERATE"]["available"] and rv["blocking"] == []
    assert rv["expected_calls"]["azure_maps"] == 0 and rv["expected_calls"]["foundry_vision"] == 0
    assert rv["resume"]["recommended_stage"] == "fusion" and rv["resume"]["strict_replay"]
    assert not any(c["allowed"] for c in rv["resume"]["allowed_choices"] if c["stage"] != "fusion")
    assert rv["versions"]["proposed_status"] == "PROPOSED_REVISION"
    st, _, res = confirm(t, cid, r, "CONFIRM_AND_REGENERATE")
    assert st == 200, res
    assert res["resume_attempt"]["strict_replay"] and len(inproc_launch) == 1
    child = res["resume_attempt"]["run_id"]
    v = call("GET", f"conversations/{cid}", token=t)[2]          # view finalizes the attempt
    pv = call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]
    assert pv["current_status"] == "DRAFT_COMPLIANT" and pv["status"] == "PROPOSED_REVISION"
    assert v["head_run_id"] == child
    plan, machine, site = out(aenv, child, "plan.json"), out(aenv, child, "machine_site_model.json"), out(aenv, child, "site_model.json")
    assert plan["status"] == "DRAFT_COMPLIANT" and plan["revision"]["plan_version_id"] == res["plan_version_id"]
    assert machine["road"]["road_type"]["status"] == "UNRESOLVED"
    assert site["road"]["road_type"]["source"] == "SME_CORRECTED" and site["road"]["road_type"]["machine"]["status"] == "UNRESOLVED"
    assert tree_hash(aenv / "runs" / parent) == before
    evs = [e for e in events(aenv / "runs" / child) if e.get("event") == "evidence"]
    assert not any(e.get("action") in ("strict_replay_blocked", "saved") for e in evs)
    assert {e["kind"] for e in evs if e.get("action") == "reused"} >= {"map", "osm", "ai"}
    calls_path = aenv / "runs" / child / "ui" / "calls.json"
    assert not calls_path.exists() or json.loads(calls_path.read_text()) == []
    titles = [m["body"].get("title") or "" for m in v["messages"] if m["kind"] == "SUMMARY"]
    assert any("Regenerated draft" in x for x in titles)
    lin = v["lineage"]
    assert [p["status"] for p in lin["plan_versions"]] == ["DRAFT_COMPLIANT"]
    assert [s["kind"] for s in lin["site_evidence_versions"]] == ["MACHINE_BASELINE", "SME_DECISIONS"]


def test_stale_review_rejected(aenv, runs):
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL")
    r = review(t, cid)
    stage_fact(t, cid, "road.lane_count", "CONFIRM")
    st, _, res = confirm(t, cid, r, "SAVE_PROPOSED_REVISION")
    assert st == 409 and res["error_code"] == "STALE_REVIEW"
    st, _, res = call("POST", f"conversations/{cid}/confirm", {"review_sha256": "0" * 64, "mode": "SAVE_PROPOSED_REVISION"}, token=t)
    assert st == 409


def test_save_site_facts_only_and_blocked_modes(aenv, runs):
    t, cid = conv(runs, "four_lane")
    stage_fact(t, cid, "road.lane_count", "CORRECT", 2)
    r = review(t, cid)
    assert not r["review"]["modes"]["CONFIRM_AND_REGENERATE"]["available"]
    st, _, res = confirm(t, cid, r, "CONFIRM_AND_REGENERATE")
    assert st == 409 and res["error_code"] == "CONFIRMATION_BLOCKED"
    st, _, res = confirm(t, cid, r, "SAVE_SITE_FACTS_ONLY")
    assert st == 200 and res["plan_version_id"] is None and res["site_evidence_version"].endswith("-v2")
    v = call("GET", f"conversations/{cid}", token=t)[2]
    assert v["site_evidence_only"] and v["staged"] == []
    assert v["applied_decisions"]["facts"][0]["field"] == "road.lane_count"
    lc = next(f for f in v["findings"] if f["subject"] == "road.lane_count")
    assert lc["state"] == "SME_CONFIRMED" and lc["value"] == 2


def test_save_proposed_revision_then_regenerate_and_roles(aenv, runs, inproc_launch):
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "URBAN_LOW_SPEED")
    r = review(t, cid)
    aud = login("aud.1")
    assert confirm(t, cid, r, "SAVE_PROPOSED_REVISION", token=aud)[0] == 403
    st, _, res = confirm(t, cid, r, "SAVE_PROPOSED_REVISION")
    assert st == 200 and inproc_launch == []
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "PROPOSED_REVISION"
    st, _, rr = call("POST", f"plan-versions/{res['plan_version_id']}/regenerate", {"conversation_id": cid}, token=t)
    assert st == 200 and len(inproc_launch) == 1
    call("GET", f"conversations/{cid}", token=t)
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "DRAFT_COMPLIANT"


def test_failed_regeneration_keeps_parent_and_allows_retry(aenv, runs, monkeypatch):
    from tcp_assistant.services import pipeline_controller

    def boom(rid, rdir): raise RuntimeError("cannot start")
    monkeypatch.setattr(pipeline_controller, "LAUNCHER", boom)
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL")
    r = review(t, cid)
    st, _, res = confirm(t, cid, r, "CONFIRM_AND_REGENERATE")
    assert st == 200 and res["resume_error"]["error_code"] == "RESUME_LAUNCH_FAILED"
    pv = call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]
    assert pv["current_status"] == "DRAFT_GENERATION_FAILED" and len(pv["resume_attempts"]) == 1
    assert call("GET", f"conversations/{cid}", token=t)[2]["head_run_id"] == runs["missing_road_type"]


def test_audit_failure_blocks_commit(aenv, runs, monkeypatch):
    from tcp_assistant.services.container import container
    from tcp_assistant.core.errors import AssistantError
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL")
    r = review(t, cid)
    audit = container().audit; real = audit.write

    def failing(event_type, *a, **k):
        if event_type == "INTENT_TO_COMMIT": raise AssistantError("AUDIT_WRITE_FAILED", "x", 500)
        return real(event_type, *a, **k)
    monkeypatch.setattr(audit, "write", failing)
    st, _, res = confirm(t, cid, r, "SAVE_PROPOSED_REVISION")
    assert st == 500 and res["error_code"] == "AUDIT_WRITE_FAILED"
    assert container().store.list("versions") == [] and container().store.list("changesets") == []


def test_version_write_failure_fails_closed(aenv, runs, monkeypatch):
    from tcp_assistant.services import versions as V
    from tcp_assistant.core.errors import AssistantError
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL")
    r = review(t, cid)

    def boom(*a, **k): raise AssistantError("VERSION_CONFLICT", "concurrent", 409)
    monkeypatch.setattr(V, "move_head", boom)
    st, _, res = confirm(t, cid, r, "SAVE_PROPOSED_REVISION")
    assert st == 409 and res["error_code"] == "VERSION_CONFLICT"
    from tcp_assistant.services.container import container
    assert any(e["event_type"] == "COMMIT_FAILED" for e in container().audit.read())


def test_pipeline_rejects_revision_when_disabled_or_tampered(aenv, runs, monkeypatch):
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL")
    r = review(t, cid)
    st, _, res = confirm(t, cid, r, "SAVE_PROPOSED_REVISION")
    from tcp_assistant.services.container import container
    from tcp_ui import relations
    from tcp_ui.tests import inproc
    store = container().store
    with open(store.blob_path("versions", res["plan_version_id"], "sme_revision.json"), encoding="utf-8") as f: rev = json.load(f)
    bad = dict(rev, decisions={"facts": [], "features": [], "sidewalks": []})
    rid, rdir = relations.create_resume_run(runs["missing_road_type"], "fusion", sme_revision=bad, strict_replay=True)
    assert inproc.run(rdir) == 2
    assert "SME_REVISION_HASH_MISMATCH" in open(os.path.join(rdir, "output", "run_report.txt"), encoding="utf-8").read()
    monkeypatch.setenv("TCP_SME_ASSISTANT_ENABLED", "false")
    rid, rdir = relations.create_resume_run(runs["missing_road_type"], "fusion", sme_revision=rev, strict_replay=True)
    assert inproc.run(rdir) == 2
    assert "SME_ASSISTANT_DISABLED" in open(os.path.join(rdir, "output", "run_report.txt"), encoding="utf-8").read()


def test_strict_replay_fails_closed_instead_of_calling_provider(aenv, runs):
    from tcp_ui import relations
    from tcp_ui.tests import inproc
    parent = runs["supported"]
    man = json.loads((aenv / "runs" / parent / "evidence" / "manifest.json").read_text())
    ai = next(e for e in man["artifacts"] if e["kind"] == "ai")
    os.remove(aenv / "runs" / parent / "evidence" / ai["file"])
    rid, rdir = relations.create_resume_run(parent, "fusion", strict_replay=True)
    inproc.run(rdir)
    evs = events(rdir)
    assert any(e.get("action") == "strict_replay_blocked" and e["kind"] == "ai" for e in evs)
    cp = os.path.join(rdir, "ui", "calls.json")
    calls = json.load(open(cp)) if os.path.exists(cp) else []
    assert all(c["service"] != "ai" for c in calls)
    with open(os.path.join(rdir, "ui", "result.json")) as f: res = json.load(f)
    assert res["decision"] == "REVIEW_REQUIRED" and "AI_OBSERVATION_UNAVAILABLE" in res["reason_codes"]


def test_running_regeneration_is_not_finalized(aenv, runs, monkeypatch):
    """A regeneration run the UI server is still executing must not be judged (was: RUN_INTERRUPTED -> FAILED)."""
    import sys, types
    from tcp_assistant.services import pipeline_controller
    started = []
    monkeypatch.setattr(pipeline_controller, "LAUNCHER", lambda rid, rdir: started.append((rid, rdir)))  # launched, not finished
    t, cid = conv(runs, "missing_road_type")
    call("POST", f"conversations/{cid}/decisions", {"type": "FACT", "field": "road.road_type", "action": "CORRECT",
                                                    "value": "RURAL", "reason": "x"}, token=t)
    r = review(t, cid)
    st, _, res = call("POST", f"conversations/{cid}/confirm", {"review_sha256": r["review_sha256"], "mode": "CONFIRM_AND_REGENERATE"}, token=t)
    rid, rdir = started[0]
    fake = types.SimpleNamespace(live_ids=lambda: {rid})
    monkeypatch.setitem(sys.modules, "tcp_ui.server", fake)
    call("GET", f"conversations/{cid}", token=t)
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "REGENERATING"
    st2, _, dup = call("POST", f"plan-versions/{res['plan_version_id']}/regenerate", {"conversation_id": cid}, token=t)
    assert st2 == 409                                  # no second attempt while one is running
    from tcp_ui.tests import inproc
    inproc.run(rdir)                                  # the run finishes
    monkeypatch.setitem(sys.modules, "tcp_ui.server", types.SimpleNamespace(live_ids=lambda: set()))
    call("GET", f"conversations/{cid}", token=t)
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "DRAFT_COMPLIANT"
    assert r["review"]["versions"]["new_site_evidence_version"].endswith("-v2")   # review matches what confirm creates
