"""Consistency checks (S6 step 9, review R5): config driven, only lower trust, check 8 runs only when parking and shoulder read false."""
import pytest

from tcp_planner.ai.call1 import Observation
from tcp_planner.contracts import FT, REVIEW_REQUIRED, SUPPORTED_AUTO
from tcp_planner.site_model import consistency as K
from tcp_planner.site_model.code_checks import CheckResult
from tcp_planner.site_model.facts import MeasuredLength, Interval, Mark, SiteFact, rule_inputs
from tcp_planner.site_model.site_config import lane_width_plausible_m, load_site_config


def obs(**vals):
    out = {}
    for k, v in vals.items():
        out[k] = Observation(field=k, value=v, status="RESOLVED", confidence=0.9, evidence="e") if v is not None else Observation(field=k, status="UNKNOWN", reason_code="occluded")
    return out


def fact(field, value, flags=(), registry=True):
    from tcp_planner.site_model.outcomes import outcome_for
    return SiteFact(field=field, registry_id=field if registry else None, source="AI", outcome=outcome_for(field, value), value=value, confidence=0.9, flags=flags)


def tw(m):
    return MeasuredLength(name="traveled_way_width", value_ft=m / FT, interval_ft=Interval(lo=m / FT - 1, hi=m / FT + 1, unit="ft"), method="AI_MARKS", mpp=0.5, pixel_error_px=3.0)


GATE_OK = dict(parking_present=False, shoulder_present=False)
LO, HI = lane_width_plausible_m()


# ---------------------------------------------------------------- lane count against width (R5)
def test_check_8_runs_only_when_parking_and_shoulder_are_both_read_false():
    facts = [fact("lanes_per_direction", 2)]
    for gate in (dict(parking_present=True, shoulder_present=False), dict(parking_present=False, shoulder_present=True),
                 dict(parking_present=None, shoulder_present=False), dict(parking_present=False, shoulder_present=None), {}):
        o = obs(lanes_per_direction=2, oneway=False, **gate)
        out, qs, r = K.lane_count_vs_width(facts, o, tw(80.0), load_site_config())
        assert r.ran is False and r.ok is None and out == facts and qs == (), gate
    o = obs(lanes_per_direction=2, oneway=False, **GATE_OK)
    assert K.lane_count_vs_width(facts, o, tw(4 * (LO + HI) / 2), load_site_config())[2].ran is True


def test_a_plausible_lane_width_passes_and_changes_nothing():
    o = obs(lanes_per_direction=2, oneway=False, **GATE_OK)
    facts = [fact("lanes_per_direction", 2)]
    out, qs, r = K.lane_count_vs_width(facts, o, tw(4 * 3.4), load_site_config())
    assert r.ok is True and out == facts and qs == () and abs(r.data["per_lane_m"] - 3.4) < 0.01


@pytest.mark.parametrize("width_m", [4 * 1.2, 4 * 9.0])
def test_an_implausible_width_makes_the_lane_count_unknown_with_a_question_candidate(width_m):
    o = obs(lanes_per_direction=2, oneway=False, **GATE_OK)
    out, qs, r = K.lane_count_vs_width([fact("lanes_per_direction", 2, ("NEEDS_SECOND_SOURCE",))], o, tw(width_m), load_site_config())
    f = out[0]
    assert r.ok is False and f.outcome == "UNKNOWN" and f.reason_code == "check_failed" and f.candidates[-1].value == 2 and "NEEDS_SECOND_SOURCE" not in f.flags
    assert qs[0].kind == "LANES_DISAGREE" and qs[0].candidate is True and qs[0].suggested == 2 and qs[0].field == "lanes_per_direction"


def test_a_one_way_road_divides_by_the_one_way_lane_count():
    o = obs(lanes_per_direction=3, oneway=True, **GATE_OK)
    assert K.lane_count_vs_width([fact("lanes_per_direction", 3)], o, tw(3 * 3.4), load_site_config())[2].ok is True
    assert K.lane_count_vs_width([fact("lanes_per_direction", 3)], obs(lanes_per_direction=3, oneway=False, **GATE_OK), tw(3 * 3.4), load_site_config())[2].ok is False


def test_an_already_unknown_lane_fact_is_not_asked_again():
    o = obs(lanes_per_direction=2, oneway=False, **GATE_OK)
    u = SiteFact(field="lanes_per_direction", registry_id="lanes_per_direction", source="AI", outcome="UNKNOWN", reason_code="single_source")
    out, qs, r = K.lane_count_vs_width([u], o, tw(4 * 1.2), load_site_config())
    assert out == [u] and qs == () and r.ok is False


# ---------------------------------------------------------------- lane lines against the lane count (R5)
def lines(n, ran=True):
    return CheckResult("lane_lines", ran, True if ran else None, "e", {"interior_lines": n, "implied_total_lanes": n + 1}, ("CALIBRATION_PENDING",))


def test_no_painted_line_never_lowers_confidence():
    o = obs(lanes_per_direction=2, oneway=False)
    facts = [fact("lanes_per_direction", 2)]
    out, r = K.lane_lines_vs_lane_count(facts, o, lines(0, ran=False), load_site_config())
    assert out == facts and r.ran is False


def test_lines_that_imply_another_lane_count_lower_it_with_a_review_flag_and_never_raise_it():
    o = obs(lanes_per_direction=2, oneway=False)                       # 4 lanes read
    out, r = K.lane_lines_vs_lane_count([fact("lanes_per_direction", 2)], o, lines(1), load_site_config())      # 1 line implies 2 lanes
    f = out[0]
    assert r.ok is False and f.outcome == "FOUND" and f.value == 2 and "CODE_CHECK_LOWERED" in f.flags
    decision, reasons = rule_inputs(out).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED and [x["fact"] for x in reasons] == ["lanes_per_direction"] and reasons[0]["flag"] == "CODE_CHECK_LOWERED"
    agree, r2 = K.lane_lines_vs_lane_count([fact("lanes_per_direction", 2)], o, lines(3), load_site_config())
    assert r2.ok is True and agree[0].flags == ()


# ---------------------------------------------------------------- approaching lanes and the sidewalk pair
def test_approaching_lanes_contradiction_makes_both_unknown_with_question_candidates():
    o = obs(lanes_per_direction=2, approaching_lanes_one=True, oneway=False)
    facts = [fact("lanes_per_direction", 2), fact("approaching_lanes_one", True)]
    out, qs, r = K.approaching_lanes_vs_lane_count(facts, o, load_site_config())
    assert r.ok is False and [f.outcome for f in out] == ["UNKNOWN", "UNKNOWN"] and {q.field for q in qs} == {"lanes_per_direction", "approaching_lanes_one"}
    assert all(q.candidate for q in qs)
    ok = K.approaching_lanes_vs_lane_count(facts, obs(lanes_per_direction=1, approaching_lanes_one=True, oneway=False), load_site_config())
    assert ok[2].ok is True and ok[0] == facts


def test_sidewalk_pair_contradiction_makes_both_unknown():
    facts = [fact("sidewalk_present", False, registry=False), fact("sidewalk_side", "N", registry=False)]
    out, r = K.sidewalk_pair(facts, obs(sidewalk_present=False, sidewalk_side="N"), load_site_config())
    assert r.ok is False and [f.outcome for f in out] == ["UNKNOWN", "UNKNOWN"]
    good, r2 = K.sidewalk_pair(facts, obs(sidewalk_present=False, sidewalk_side="NONE"), load_site_config())
    assert r2.ok is True and good == facts
    assert K.sidewalk_pair(facts, obs(sidewalk_present=True, sidewalk_side="NONE"), load_site_config())[1].ok is False


# ---------------------------------------------------------------- work location against the edges (the marks check)
def marks(work_y):
    return (Mark(feature="road_edge_left", status="RESOLVED", points=((100, 600), (1200, 600))), Mark(feature="road_edge_right", status="RESOLVED", points=((100, 700), (1200, 700))),
            Mark(feature="work_point", status="RESOLVED", points=((640, work_y),)))


def test_the_marks_check():
    assert K.work_marks_check(marks(650), "ROADWAY") == K.AGREE and K.work_marks_check(marks(650), "SHOULDER") == K.DISAGREE
    assert K.work_marks_check(marks(500), "BEYOND_SHOULDER") == K.AGREE and K.work_marks_check(marks(500), "ROADWAY") == K.DISAGREE
    assert K.work_marks_check((), "ROADWAY") == K.MISSING and K.work_marks_check(marks(650), "SIDEWALK") == K.MISSING
    assert K.work_marks_check(marks(650)[:2], "ROADWAY") == K.MISSING


# ---------------------------------------------------------------- switches and the runner
def test_every_check_has_a_config_switch_and_the_runner_obeys_it():
    cfg = load_site_config()
    assert set(k for k in cfg["consistency"] if k != "note") == {"lane_count_vs_width", "lane_lines_vs_lane_count", "approaching_lanes_vs_lane_count", "sidewalk_pair", "work_location_vs_edges"}
    o = obs(lanes_per_direction=2, approaching_lanes_one=True, oneway=False, sidewalk_present=False, sidewalk_side="N", **GATE_OK)
    facts = [fact("lanes_per_direction", 2), fact("approaching_lanes_one", True), fact("sidewalk_present", False, registry=False), fact("sidewalk_side", "N", registry=False)]
    full = K.run_consistency(facts, o, tw(4 * 1.0), lines(1), cfg)
    assert {r.name for r in full.results} == {"lane_count_vs_width", "lane_lines_vs_lane_count", "approaching_lanes_vs_lane_count", "sidewalk_pair"}
    for name in ("lane_count_vs_width", "lane_lines_vs_lane_count", "approaching_lanes_vs_lane_count", "sidewalk_pair"): cfg["consistency"][name]["value"] = False
    off = K.run_consistency(facts, o, tw(4 * 1.0), lines(1), cfg)
    assert list(off.facts) == facts and off.results == () and off.questions == ()


def test_no_check_ever_creates_a_value():
    o = obs(lanes_per_direction=None, oneway=False, **GATE_OK)
    u = SiteFact(field="lanes_per_direction", registry_id="lanes_per_direction", source="AI", outcome="UNKNOWN", reason_code="occluded")
    res = K.run_consistency([u], o, tw(40.0), lines(2), load_site_config())
    assert list(res.facts) == [u]
