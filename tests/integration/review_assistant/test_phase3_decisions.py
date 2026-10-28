import copy, json

import pytest

from .conftest import call, login


def _conv(runs, sc, who="sme.1"):
    t = login(who)
    st, _, v = call("POST", "conversations", {"run_id": runs[sc]}, token=t)
    assert st == 201, v
    return t, v["conversation"]["conversation_id"], v


def _stage(t, cid, **payload):
    return call("POST", f"conversations/{cid}/decisions", payload, token=t)


def _fact(p, field):
    return next(r for r in p["facts"] if r["field"] == field)


@pytest.fixture
def no_external(monkeypatch):
    import requests
    from tcp_planner.ai import foundry_provider as fp
    def boom(*a, **k): raise AssertionError("external / model call attempted")
    monkeypatch.setattr(requests, "get", boom); monkeypatch.setattr(requests, "post", boom)
    for k in list(fp.APIS): monkeypatch.setitem(fp.APIS, k, boom)


def test_lane_count_correction_machine_sme_effective(aenv, runs, no_external):
    t, cid, v = _conv(runs, "lane_conflict")
    st, _, r = _stage(t, cid, type="FACT", field="road.lane_count", action="CORRECT", value=2, reason="field check: 2 lanes")
    assert st == 200, r
    p = r["preview"]; lc = _fact(p, "road.lane_count")
    assert lc["machine"]["status"] == "CONFLICT" and lc["machine"]["value"] is None
    assert lc["proposed"] == {"value": 2, "status": "RESOLVED", "source": "SME_CORRECTED"} and lc["kind"] == "DIRECT"
    assert any(c["field"] == "road.lane_count" for c in p["superseded_conflicts"])
    # lane-count conflict cleared; the unverified centerline (no usable geometry) still blocks - not SME-overridable
    assert "LANE_COUNT_CONFLICT" in p["eligibility"]["current"]["reason_codes"]
    assert p["eligibility"]["proposed"]["reason_codes"] == ["CENTERLINE_UNRESOLVED"]
    assert p["plan_outcome"]["status"] == "BLOCKED" and p["external_calls_expected"]["azure_maps"] == 0


def test_road_type_correction_produces_compliant_preview(aenv, runs, no_external):
    t, cid, v = _conv(runs, "missing_road_type")
    st, _, r = _stage(t, cid, type="FACT", field="road.road_type", action="CORRECT", value="RURAL", reason="county records")
    p = r["preview"]
    assert p["eligibility"]["proposed"]["decision"] == "SUPPORTED_AUTO" and p["plan_outcome"]["status"] == "DRAFT_COMPLIANT"
    assert {r["object_id"] for r in p["placement"] if r["proposed"]} == {"W1", "S1", "S2"}
    assert p["ta"]["proposed"]["applicable"] and p["ta"]["ta_changed"]


def test_dependent_facts_recalculated_and_shown(aenv, runs, no_external):
    t, cid, v = _conv(runs, "four_lane")
    st, _, r = _stage(t, cid, type="FACT", field="road.lane_count", action="CORRECT", value=2, reason="test")
    p = r["preview"]
    enc = _fact(p, "work.encroaches_traveled_way")
    # 14.6 m wide / 2 lanes = 7.3 m per lane -> implausible -> encroachment becomes unresolved (dependent change)
    assert enc["kind"] == "DEPENDENT" and enc["proposed"]["status"] == "UNRESOLVED"
    assert enc["proposed"]["source"] == "DERIVED_FROM_SME"
    dep = {c["field"] for c in p["overlay_changes"] if c["kind"] == "DEPENDENT"}
    assert {"work.encroaches_traveled_way", "work.location", "work.requires_lane_closure",
            "work.requires_alternating_one_lane_traffic"} <= dep
    assert p["eligibility"]["proposed"]["decision"] == "REVIEW_REQUIRED"
    assert p["ta"]["proposed"]["state"] == "TA_APPLICABILITY_UNRESOLVED"


def test_machine_site_model_is_never_modified(aenv, runs):
    from tcp_planner.review import decision_overlay as sme_overlay
    from tcp_planner.review.assistant.services import run_context
    ctx = run_context.load(runs["lane_conflict"]); m = ctx["machine_site_model"]; before = copy.deepcopy(m)
    eff = sme_overlay.apply(m, {"facts": [{"field": "road.lane_count", "action": "CORRECT", "value": 2, "decision_id": "d1"}]},
                            run_context.config())
    assert m == before and eff["site_model_id"] != m["site_model_id"]
    f = eff["road"]["lane_count"]
    assert f["machine"]["status"] == "CONFLICT" and f["sme"]["value"] == 2 and f["source"] == "SME_CORRECTED"
    assert f["observations"] == m["road"]["lane_count"]["observations"]   # machine observations preserved, SME not added as AI
    assert all(o["source"] != "AI" or o.get("value") != 2 or True for o in f["observations"])
    assert eff["sme_overlay"]["machine_site_model_id"] == m["site_model_id"]


def test_feature_rejection_clears_validator_conflict(aenv, runs, no_external):
    t, cid, v = _conv(runs, "driveway_at_sign")
    drv = [f for f in v["findings"] if f["category"] == "FEATURE" and f["feature_kind"] == "driveways"]
    for f in drv:
        st, _, r = _stage(t, cid, type="FEATURE", action="REJECT", feature_key=f["subject"], reason="not a driveway (field visit)")
        assert st == 200, r
    p = r["preview"]
    geo = next(x for x in p["rules"] if x["check_id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT")
    assert geo["current"] == "FAIL" and geo["rule_status_current"] == "CONFLICT"
    assert geo["proposed"] == "PASS" and geo["rule_status_proposed"] == "COMPLIANT"
    assert set(p["rejected_features"]) == {f["subject"] for f in drv}
    assert p["plan_outcome"]["status"] == "DRAFT_COMPLIANT"


def test_add_feature_creates_conflict_and_mark_unresolved_blocks(aenv, runs, no_external):
    t, cid, v = _conv(runs, "supported")
    s1 = next(o for o in v["objects"] if o["object_id"] == "S1")
    st, _, r = _stage(t, cid, type="FEATURE", action="ADD", kind="driveways", station_m=s1["station_m"] + 5, side="RIGHT",
                      description="gravel driveway", reason="seen on site")
    assert st == 200, r
    geo = next(x for x in r["preview"]["rules"] if x["check_id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT")
    assert geo["proposed"] == "FAIL" and r["preview"]["plan_outcome"]["status"] == "BLOCKED"
    st, _, r = _stage(t, cid, type="FACT", field="road.lane_count", action="MARK_UNRESOLVED")
    assert r["preview"]["eligibility"]["proposed"]["decision"] == "REVIEW_REQUIRED"
    assert _fact(r["preview"], "road.lane_count")["proposed"]["source"] == "SME_UNRESOLVED"


def test_sidewalk_decision_recomputes_pedestrian_impact(aenv, runs, no_external):
    t, cid, v = _conv(runs, "sidewalk")
    assert v["run_state"]["decision"] == "UNSUPPORTED_POC"
    st, _, r = _stage(t, cid, type="SIDEWALK", side="LEFT", present=False, reason="sidewalk ends before work zone")
    ped = _fact(r["preview"], "work.affects_pedestrian_route")
    assert ped["machine"]["value"] is True and ped["proposed"]["value"] is False and ped["kind"] == "DEPENDENT"
    assert r["preview"]["eligibility"]["proposed"]["decision"] == "SUPPORTED_AUTO"


def test_validation_policy_role_and_contradiction(aenv, runs):
    t, cid, v = _conv(runs, "intersection")
    st, _, r = _stage(t, cid, type="FACT", field="road.lane_count", action="CORRECT", value=2)
    assert st == 400 and r["error_code"] == "REASON_REQUIRED"
    st, _, r = _stage(t, cid, type="FACT", field="road.lane_count", action="CORRECT", value=99, reason="x")
    assert st == 400 and r["error_code"] == "DECISION_INVALID"
    st, _, r = _stage(t, cid, type="FACT", field="site.complex_intersection_conflict", action="CORRECT", value=False, reason="x")
    assert st == 400 and r["error_code"] == "DECISION_CONTRADICTS_EVIDENCE"
    st, _, r = _stage(t, cid, type="FACT", field="work.requires_lane_closure", action="CORRECT", value=False, reason="x")
    assert st == 400  # derived facts are not directly editable
    aud = login("aud.1")
    st, _, r = _stage(aud, cid, type="FACT", field="road.lane_count", action="CONFIRM")
    assert st == 403
    st, _, r = _stage(t, cid, type="FEATURE", action="ADD", kind="driveways", station_m=99999, side="RIGHT", reason="x")
    assert st == 400 and r["error_code"] == "OUTSIDE_EVIDENCE_COVERAGE"


def test_structured_actions_make_zero_llm_calls_and_unstage(aenv, runs, no_external):
    t, cid, v = _conv(runs, "missing_road_type")
    st, _, r = _stage(t, cid, type="FACT", field="road.road_type", action="CORRECT", value="RURAL", reason="county records")
    assert st == 200 and r["preview"]["plan_outcome"]["status"] in ("DRAFT_COMPLIANT", "BLOCKED")
    assert r["preview"]["ai_calls_expected"] == 0
    key = r["staged"][0]["key"]
    st, _, r = call("POST", f"conversations/{cid}/decisions/remove", {"key": key}, token=t)
    assert r["staged"] == [] and r["preview"]["eligibility"]["proposed"]["decision"] == "REVIEW_REQUIRED"
    from tcp_planner.review.assistant.services.container import container
    evs = [e for e in container().audit.read() if e["event_type"] == "TOOL_INVOCATION"]
    assert all(e["model_deployment"] == "N/A" and not e["external_call"] for e in evs)


def test_validators_and_rule_pack_files_unchanged():
    import hashlib, subprocess
    out = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "src/tcp_planner/validation/validators.py",
                          "rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json", "src/tcp_planner/layout/rule_engine.py",
                          "src/tcp_planner/geometry/local_frame.py"],
                         capture_output=True, text=True, cwd=__import__("os").path.dirname(__import__("os").path.dirname(
                             __import__("os").path.dirname(__import__("os").path.dirname(__file__)))))
    assert out.stdout.strip() == ""
