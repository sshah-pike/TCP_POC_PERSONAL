"""S6 STOP 3 follow-ups: PROPOSED footprint with SME override, arrow board REQUIRED, lane-width question hint, the D-93 gate for
default values, and the rule ids found per action in pack 1.1.0."""
import pytest

from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import lengths as L, precalc as P
from tcp_planner.site_model.facts import Interval, MeasuredLength, Mark, SiteFact, rule_inputs

PX_IS_FT = 0.3048


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def lane(value, half=0.0):
    iv = Interval(lo=value - half, hi=value + half, unit="ft")
    m = MeasuredLength(name="lane_width", value_ft=value, interval_ft=iv, method="AI_MARKS", mpp=0.3, pixel_error_px=3.0, inputs=("x",), calculation="c")
    return SiteFact(field="lane_width_ft", registry_id="lane_width_ft", value=value, unit="ft", source="AI_MARKS", status="RESOLVED", interval=iv, measured=m)


# ---------------------------------------------------------------- 1. footprint: PROPOSED, trace, SME override wins
def test_footprint_is_marked_proposed_with_formula_and_inputs_in_the_trace():
    f, _ = P.encroachment_depth(4.0, 1.5)
    assert "PROPOSED" in f.flags and f.value == pytest.approx(5.5) and f.source == "SME_FORM"
    assert f.measured.calculation.startswith(P.FOOTPRINT_FORMULA) and "PROPOSED" in f.measured.calculation
    assert f.measured.inputs == ("work_space_depth_ft=4.0", "clearance_ft=1.5", "work vehicle not included")
    assert f.evidence == f.measured.calculation


def test_the_default_vehicle_flag_follows_into_the_trace_when_it_sets_the_depth():
    veh = P.work_vehicle_width()
    f, _ = P.encroachment_depth(4.0, 1.5, veh, include_vehicle=True)
    assert set(f.flags) == {"PROPOSED", "DEFAULT_ASSUMED"} and "work_vehicle_width_ft=8.5 (included)" in f.measured.inputs


def test_the_sme_single_number_wins_over_every_other_input():
    veh = P.work_vehicle_width()
    f, q = P.encroachment_depth(4.0, 1.5, veh, include_vehicle=True, sme_override_ft=2.0)
    assert f.value == 2.0 and f.source == "SME_OVERRIDE" and q is None
    assert f.flags == () and "PROPOSED" not in f.flags and "DEFAULT_ASSUMED" not in f.flags    # the SME's number is not a proposal or a default
    assert any("not used: the override wins" in i for i in f.measured.inputs)


def test_the_override_alone_makes_the_footprint_without_depth_and_clearance():
    f, q = P.encroachment_depth(sme_override_ft=3.5)
    assert (f.status, f.value, q) == ("RESOLVED", 3.5, None)
    assert P.encroachment_depth(sme_override_ft=0)[0].value == 0.0


@pytest.mark.parametrize("bad", [-1, "3", True])
def test_a_bad_override_is_refused(bad):
    with pytest.raises(ValueError): P.encroachment_depth(sme_override_ft=bad)


def test_the_question_for_the_unknown_footprint_asks_for_one_number():
    f, q = P.encroachment_depth()
    assert f.status == "UNKNOWN" and "encroachment depth in feet" in q.reason


def test_a_result_that_used_the_proposed_footprint_is_traceable_through_remaining_width(pack):
    depth, _ = P.encroachment_depth(3.0, 0.5)
    r, _ = P.remaining_lane_width(pack, lane(14.0), depth)
    assert "PROPOSED" in r.flags and r.measured.inputs[1] == "encroachment_depth_ft=3.5"
    over, _ = P.encroachment_depth(3.0, 0.5, sme_override_ft=2.0)
    assert P.remaining_lane_width(pack, lane(14.0), over)[0].value == pytest.approx(12.0)         # the override wins in the arithmetic too
    assert "PROPOSED" not in P.remaining_lane_width(pack, lane(14.0), over)[0].flags


# ---------------------------------------------------------------- 4. arrow board
@pytest.mark.parametrize("wanted", [True, False, None, "missing"])
def test_arrow_board_is_required_where_the_pack_requires_it_whatever_wanted_says(pack, wanted):
    ctx = {"freeway": True, "lane_closure": True}
    if wanted != "missing": ctx["arrow_board_wanted"] = wanted
    f = P.arrow_board(pack, ctx)
    assert f.value is True and f.evidence.startswith("REQUIRED by") and "R-TA33-N7" in f.evidence


def test_an_unasked_arrow_board_is_not_wanted_only_when_it_is_optional(pack):
    f = P.arrow_board(pack, {"freeway": False, "lane_closure": True})
    assert f.value is False and f.evidence.startswith("OPTIONAL_NOT_WANTED")
    assert P.arrow_board(pack, {"freeway": True, "lane_closure": False}).evidence.startswith("OPTIONAL_NOT_WANTED")   # freeway, no closed lane
    w = P.arrow_board(pack, {"freeway": False, "lane_closure": False, "arrow_board_wanted": True})
    assert w.value is True and w.evidence == "OPTIONAL_WANTED"


def test_a_closed_freeway_lane_is_required_even_when_the_sme_said_not_wanted(pack):
    assert P.arrow_board(pack, {"freeway": True, "lane_closure": True, "arrow_board_wanted": False}).value is True


# ---------------------------------------------------------------- 6. lane width question: hint only
def mark(feature, pts): return Mark(feature=feature, points=tuple(pts), status="RESOLVED")


def road(width):
    return [mark("road_edge_left", [(100.0, 500.0 - width / 2), (400.0, 500.0 - width / 2)]),
            mark("road_edge_right", [(100.0, 500.0 + width / 2), (400.0, 500.0 + width / 2)])]


def test_the_lane_width_question_asks_for_feet_and_shows_the_measured_range_and_source_as_a_hint(pack):
    res = L.measure_lengths(road(29), PX_IS_FT, pack, total_lanes=2, gate={"parking_present": True, "shoulder_present": False})
    q = next(q for q in res.questions if q.reveals == ("lane_width_ft",))
    assert "Enter the lane width in feet." in q.reason
    assert "Hint only, not used" in q.reason and "29.0 ft" in q.reason and "AI_MARKS" in q.reason and "23.0 to 35.0 ft" in q.reason
    f = next(f for f in res.facts if f.field == "lane_width_ft")
    assert (f.status, f.measured, f.interval, f.value) == ("UNKNOWN", None, None, None)          # the fact itself carries no number


def test_the_hint_never_reaches_rule_inputs(pack):
    res = L.measure_lengths(road(29), PX_IS_FT, pack, total_lanes=2, gate={"parking_present": True, "shoulder_present": False})
    ri = rule_inputs(res.facts)
    assert "lane_width_ft" not in ri
    assert all(f.value is None or f.field not in ("lane_width_ft",) for f in res.facts)
    for f in res.facts:
        if f.field == "lane_width_ft": assert "29" not in f.evidence and f.candidates == ()


def test_no_hint_when_the_traveled_way_could_not_be_measured(pack):
    res = L.measure_lengths([], PX_IS_FT, pack, gate={"parking_present": False, "shoulder_present": False})
    q = next(q for q in res.questions if q.reveals == ("lane_width_ft",))
    assert "Hint only" not in q.reason and "Enter the lane width in feet." in q.reason


def test_a_cross_section_hint_names_its_source(pack):
    section = {"status": "OK", "width_m": 8.8392, "spread_m": 0.0, "metres_per_pixel": 0.1}
    res = L.measure_lengths([], PX_IS_FT, pack, cross_section=section, gate={"parking_present": True, "shoulder_present": False})
    q = next(q for q in res.questions if q.reveals == ("lane_width_ft",))
    assert "source CROSS_SECTION" in q.reason and "29.0 ft" in q.reason


# ---------------------------------------------------------------- D-93: a result that used a default is REVIEW_REQUIRED
def test_a_result_that_used_the_default_vehicle_width_is_review_required_and_names_the_fact(pack):
    veh = P.work_vehicle_width()
    depth, _ = P.encroachment_depth(4.0, 1.5, veh, include_vehicle=True)
    rem, _ = P.remaining_lane_width(pack, lane(16.0), depth)
    assert "DEFAULT_ASSUMED" in rem.flags
    decision, reasons = rule_inputs([depth, rem, veh]).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED
    assert {r["fact"] for r in reasons} == {"work_vehicle_width_ft", "encroachment_depth_ft", "remaining_lane_width_ft"}
    assert {(r["fact"], r["flag"]) for r in reasons} == {
        ("work_vehicle_width_ft", "DEFAULT_ASSUMED"), ("encroachment_depth_ft", "DEFAULT_ASSUMED"), ("encroachment_depth_ft", "PROPOSED"),
        ("remaining_lane_width_ft", "DEFAULT_ASSUMED"), ("remaining_lane_width_ft", "PROPOSED")}


def test_the_gate_names_both_kinds_of_flag_and_leaves_clean_results_alone(pack):
    clean, _ = P.encroachment_depth(sme_override_ft=2.0)
    assert rule_inputs([clean]).gate(SUPPORTED_AUTO) == (SUPPORTED_AUTO, [])
    veh = P.work_vehicle_width()
    only_default = SiteFact(field="oneway", registry_id="oneway", value=False, source="AI", status="RESOLVED", flags=("AI_ONLY_UNCONFIRMED",))
    d, reasons = rule_inputs([veh, only_default]).gate(SUPPORTED_AUTO)
    assert d == REVIEW_REQUIRED and {(r["fact"], r["flag"]) for r in reasons} == {("work_vehicle_width_ft", "DEFAULT_ASSUMED"), ("oneway", "AI_ONLY_UNCONFIRMED")}


def test_an_sme_override_removes_the_default_flag_from_the_result(pack):
    depth, _ = P.encroachment_depth(4.0, 1.5, P.work_vehicle_width(), include_vehicle=True, sme_override_ft=3.0)
    rem, _ = P.remaining_lane_width(pack, lane(16.0), depth)
    assert rule_inputs([depth, rem]).gate(SUPPORTED_AUTO)[0] == SUPPORTED_AUTO


# ---------------------------------------------------------------- 7. rule ids found per action in pack 1.1.0
def test_the_rules_found_by_action_are_pinned_for_pack_1_1_0(pack):
    assert (pack.id, pack.version) == ("TCP_MUTCD_CH6_RULE_PACK", "1.1.0"), "a new pack: re-check and re-pin the ids below"
    lim = P.limit_rules(pack)
    found = {
        P.LANE_CLOSURE_ACTION: [lim[0].id], P.NINE_FT_ACTION: [lim[1].id],
        "shadow:TA-1": [r.id for r in P.shadow_rules(pack, "TA-1")], "shadow:TA-6": [r.id for r in P.shadow_rules(pack, "TA-6")],
        "shadow:TA-10": [r.id for r in P.shadow_rules(pack, "TA-10")], "shadow:TA-33": [r.id for r in P.shadow_rules(pack, "TA-33")],
        P.ARROW_ACTION: [P.arrow_rule(pack).id],
        "tma_threshold": [r.id for r in [P.tma_rule(pack)] if r],
    }
    assert found == {
        "LANE_CLOSURE_NEEDED": ["R-6N07-REMAINING-WIDTH"], "NINE_FT_LANE_ALLOWED": ["R-6N07-NINE-FT-OPTION"],
        "shadow:TA-1": ["R-TA1-N4"], "shadow:TA-6": ["R-TA6-N10"], "shadow:TA-10": [], "shadow:TA-33": [],
        "ARROW_BOARD_PER_CLOSED_LANE": ["R-TA33-N7"], "tma_threshold": []}


def test_every_selector_finds_exactly_the_shared_or_ta_rules_it_should(pack):
    assert all(r.ta_id is None for r in P.limit_rules(pack))
    assert all(r.ta_id == "TA-6" for r in P.shadow_rules(pack, "TA-6"))
