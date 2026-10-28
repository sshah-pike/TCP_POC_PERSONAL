import math

import pytest

from tcp_planner.contracts import FT
from .conftest import call, login
from .test_phase3_decisions import no_external  # noqa: F401
from .test_phase4_versions import inproc_launch, conv, review, confirm, out  # noqa: F401


def ev(t, cid, **p):
    return call("POST", f"conversations/{cid}/placements/evaluate", p, token=t)


def stage(t, cid, **p):
    return call("POST", f"conversations/{cid}/placements", p, token=t)


def _ctx_site(runs, sc):
    from tcp_planner.review.assistant.services import run_context
    return run_context.load(runs[sc])


def test_movement_along_alignment_and_offset_preserved(aenv, runs, no_external):
    t, cid = conv(runs, "supported")
    st, _, r = ev(t, cid, object_id="S1", direction="UPSTREAM", distance=100, unit="FT", preserve_lateral_offset=True)
    assert st == 200, r
    m = r["evaluation"]["movement"]
    assert m["approach"] == "INCREASING_STATION" and m["station_change_m"] == pytest.approx(-100 * FT, abs=1e-3)  # upstream = lower station
    assert m["actual_along_alignment_m"] == pytest.approx(30.48, abs=1e-3)
    assert m["straight_line_m"] <= m["path_length_at_offset_m"] + 1e-3
    assert m["proposed"]["offset_m"] == m["current"]["offset_m"] and m["lateral_offset_preserved"]
    # proposed coordinate lies on the saved alignment at the computed station/offset (not a lat/lon delta)
    from tcp_planner.geometry.local_frame import SiteFrame, signed_lateral
    ctx = _ctx_site(runs, "supported"); frame = SiteFrame(ctx["site_model"])
    d, s, lat = signed_lateral(frame.centerline, frame.enu(m["proposed"]["latitude"], m["proposed"]["longitude"]))
    assert s == pytest.approx(m["proposed"]["station_m"], abs=0.05) and lat == pytest.approx(m["proposed"]["offset_m"], abs=0.05)
    st, _, r2 = ev(t, cid, object_id="S2", direction="UPSTREAM", distance=100, unit="FT")
    assert r2["evaluation"]["movement"]["station_change_m"] == pytest.approx(30.48, abs=1e-3)       # S2 travels the other way
    # rule results from the unchanged validators: moved sign -> VAL-SPACING / GEO-STATION CONFLICT
    rows = {x["check_id"]: x for x in r["evaluation"]["rule_impact"]}
    assert rows["VAL-SPACING"]["rule_status_proposed"] == "CONFLICT" and rows["GEO-STATION"]["proposed"] == "FAIL"
    assert r["evaluation"]["ta_impact"]["remains_applicable"] and r["evaluation"]["ai_calls"] == 0
    assert r["evaluation"]["artifact_impact"]["azure_maps_required"] is False


def test_intersection_conflict_stops_before_commit_with_alternatives(aenv, runs, no_external):
    t, cid = conv(runs, "supported")
    ctx = _ctx_site(runs, "supported")
    inter = next(f for f in ctx["site_model"]["features"]["intersections"] if f["source"] == "OSM")
    s2 = next(o for o in ctx["plan"]["objects"] if o["object_id"] == "S2")["placement"]["station_m"]
    dist_ft = (inter["station_m"] - s2) / FT                                     # lands on the intersection
    st, _, r = ev(t, cid, object_id="S2", direction="UPSTREAM", distance=round(dist_ft, 1), unit="FT")
    e = r["evaluation"]
    rel = {(x["relationship"], (x["feature"] or {}).get("type")) for x in e["blocking"]}
    assert ("PROPOSED_POINT_INSIDE", "INTERSECTION") in rel and ("PLACEMENT_CLEARANCE_OVERLAPS", "INTERSECTION") in rel
    inside = next(x for x in e["blocking"] if x["relationship"] == "PROPOSED_POINT_INSIDE")
    assert inside["feature"]["source"] == "OSM" and inside["feature"]["evidence_version"] and "overlap_m" in inside
    assert {"KEEP_CURRENT_POSITION", "PLACE_BEFORE_FEATURE", "PLACE_AFTER_FEATURE", "USE_NEAREST_CANDIDATE",
            "PROCEED_AS_SME_EXCEPTION"} <= set(e["actions"])
    kinds = {c["kind"]: c for c in e["candidates"]}
    assert {"ORIGINAL", "BEFORE_FEATURE", "AFTER_FEATURE", "NEAREST_WITHOUT_SPATIAL_CONFLICT"} <= set(kinds)
    assert all(c["auto_applied"] is False and "SME verification required" in c["note"] for c in e["candidates"])
    assert kinds["BEFORE_FEATURE"]["blocking_spatial"] == [] and kinds["NEAREST_WITHOUT_SPATIAL_CONFLICT"]["blocking_spatial"] == []
    assert call("GET", f"conversations/{cid}", token=t)[2]["staged"] == []          # nothing applied automatically
    # staging the conflicting move is possible, but confirmation is blocked (validator conflict, no exception)
    st, _, r = stage(t, cid, object_id="S2", direction="UPSTREAM", distance=round(dist_ft, 1), unit="FT", reason="field request")
    assert st == 200 and r["preview"]["plan_outcome"]["status"] == "BLOCKED"
    rv = review(t, cid)
    assert rv["review"]["geometry"]["spatial_conflicts"] and not rv["review"]["modes"]["CONFIRM_AND_REGENERATE"]["available"]
    assert confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")[0] == 409


def test_candidate_plus_spacing_exception_end_to_end(aenv, runs, inproc_launch):
    t, cid = conv(runs, "supported")
    ctx = _ctx_site(runs, "supported")
    inter = next(f for f in ctx["site_model"]["features"]["intersections"] if f["source"] == "OSM")
    s2 = next(o for o in ctx["plan"]["objects"] if o["object_id"] == "S2")["placement"]["station_m"]
    e = ev(t, cid, object_id="S2", direction="UPSTREAM", distance=round((inter["station_m"] - s2) / FT, 1), unit="FT")[2]["evaluation"]
    before = next(c for c in e["candidates"] if c["kind"] == "BEFORE_FEATURE")
    st, _, r = stage(t, cid, object_id="S2", station_m=before["station_m"], candidate_kind="BEFORE_FEATURE", reason="sign before side street")
    assert st == 200, r
    fails = [x["check_id"] for x in r["preview"]["rules"] if x["proposed"] == "FAIL"]
    assert set(fails) == {"VAL-SPACING", "GEO-STATION"}                          # validators unchanged: spacing conflict
    for chk in fails:
        st, _, r = call("POST", f"conversations/{cid}/exceptions", {"type": "RULE_CONFLICT", "check_id": chk, "confirm_exception": True,
                                                                    "reason": "advance sign kept clear of the side street"}, token=t)
        assert st == 200, r
    assert r["preview"]["plan_outcome"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    rv = review(t, cid)
    assert rv["review"]["geometry"]["movements"][0]["proposed"]["station_m"] == before["station_m"]
    st, _, res = confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")
    assert st == 200, res
    child = res["resume_attempt"]["run_id"]
    call("GET", f"conversations/{cid}", token=t)
    assert call("GET", f"plan-versions/{res['plan_version_id']}", token=t)[2]["current_status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    plan = out(aenv, child, "plan.json")
    s2o = next(o for o in plan["objects"] if o["object_id"] == "S2")
    assert s2o["placement"]["station_m"] == before["station_m"] and s2o["sme"]["change"] == "MOVED"
    assert s2o["placement"]["rule_distance_ft"] == 500 and s2o["placement"]["longitudinal_distance_ft"] != 500
    val = out(aenv, child, "validation_results.json")
    assert next(c for c in val["rule_validation"]["checks"] if c["id"] == "VAL-SPACING")["status"] == "FAIL"


def test_out_of_coverage_blocked_and_bad_references(aenv, runs, no_external):
    t, cid = conv(runs, "supported")
    st, _, r = stage(t, cid, object_id="S1", direction="UPSTREAM", distance=1150, unit="FT", reason="x")
    assert st == 409 and r["error_code"] == "OUTSIDE_EVIDENCE_COVERAGE"
    st, _, r = ev(t, cid, object_id="S3", direction="UPSTREAM", distance=100, unit="FT")
    assert st == 404 and r["error_code"] == "ENTITY_NOT_FOUND" and set(r["details"]["existing_objects"]) == {"W1", "S1", "S2"}
    st, _, r = ev(t, cid, object_id="W1", direction="UPSTREAM", distance=10, unit="FT")
    assert st == 400 and r["error_code"] == "OBJECT_NOT_MOVABLE"
    st, _, r = stage(t, cid, object_id="S1", direction="UPSTREAM", distance=10, unit="FT")
    assert st == 400 and r["error_code"] == "REASON_REQUIRED"
    aud = login("aud.1")
    assert stage(aud, cid, object_id="S1", direction="UPSTREAM", distance=10, unit="FT", reason="x")[0] == 403


def test_keep_current_position_unstages(aenv, runs, no_external):
    t, cid = conv(runs, "supported")
    stage(t, cid, object_id="S1", direction="DOWNSTREAM", distance=20, unit="FT", reason="x")
    r = call("POST", f"conversations/{cid}/placements/keep", {"object_id": "S1"}, token=t)[2]
    assert r["staged"] == [] and r["preview"]["plan_outcome"]["status"] == "DRAFT_COMPLIANT"
