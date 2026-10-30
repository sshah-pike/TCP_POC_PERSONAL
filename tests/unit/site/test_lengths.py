"""Lengths from pixels, intervals and the straddle test (S6 commit 3). Synthetic marks with a known scale; no model call.

mpp = 0.3048 m per pixel makes one pixel exactly one foot, so every expected number can be checked by hand.
"""
import io, json, math, os, re, tokenize

import pytest

from tcp_planner.ai.call1 import parse_call1
from tcp_planner.rules.rule_pack_models import Cmp
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Interval, Mark
from tcp_planner.site_model.measure import EdgePair, edge_pair

PX_IS_FT = 0.3048     # metres per pixel: 1 px = 1 ft (the conversion only; not a regulatory value)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def mark(feature, pts, status="RESOLVED"):
    return Mark(feature=feature, points=tuple(pts), status=status, reason_code=None if status == "RESOLVED" else "malformed")


def road(angle, width, length=300.0, cx=500.0, cy=500.0):
    b = math.radians(angle); u = (math.sin(b), -math.cos(b)); v = (-u[1], u[0])
    mk = lambda off: [(cx + u[0] * t + v[0] * off, cy + u[1] * t + v[1] * off) for t in (-length / 2, 0.0, length / 2)]
    return mk(-width / 2), mk(width / 2), u, v


def edges_marks(angle, width):
    a, b, _, _ = road(angle, width)
    return [mark("road_edge_left", a), mark("road_edge_right", b)]


# ---------------------------------------------------------------- scale
def test_pixel_to_feet_is_exact_at_the_known_scale():
    assert L.px_to_ft(100, PX_IS_FT) == pytest.approx(100.0)
    assert L.px_to_ft(1, 0.448139) == pytest.approx(0.448139 / 0.3048)
    assert L.m_to_ft(0.3048) == pytest.approx(1.0)


def test_resize_rescales_the_conversion():
    """Half the pixels across the same ground: mpp_sent doubles, so the same road is half as many pixels and the same feet."""
    full = L.traveled_way_width(edges_marks(90, 24), PX_IS_FT)[0]
    half = L.traveled_way_width(edges_marks(90, 12), PX_IS_FT * 2)[0]
    assert full.value_ft == pytest.approx(half.value_ft) == pytest.approx(24.0)


# ---------------------------------------------------------------- interval
def test_interval_is_edge_error_times_scale_times_two_edges():
    m, _ = L.traveled_way_width(edges_marks(90, 12), PX_IS_FT)
    assert m.value_ft == pytest.approx(12.0) and m.pixel_error_px == 3.0 and m.method == "AI_MARKS"
    assert (m.interval_ft.lo, m.interval_ft.hi) == pytest.approx((6.0, 18.0))      # +/- 3 px x 1 ft/px x 2 edges (AI marks)
    assert "CALIBRATION_PENDING" in m.flags and m.inputs and "mpp_sent" in " ".join(m.inputs)


def test_interval_grows_with_coarser_pixels_and_never_goes_below_zero():
    fine = L.interval_ft(30.0, 0.0, PX_IS_FT)[0]; coarse = L.interval_ft(30.0, 0.0, PX_IS_FT * 3)[0]
    assert (coarse.hi - coarse.lo) == pytest.approx(3 * (fine.hi - fine.lo))
    assert L.interval_ft(3.0, 0.0, PX_IS_FT * 3)[0].lo == 0.0


def test_interval_adds_the_section_spread():
    iv = L.interval_ft(12.0, 1.5, PX_IS_FT)[0]
    assert (iv.lo, iv.hi) == pytest.approx((4.5, 19.5))                  # +/- (6 + 1.5), AI marks
    iv = L.interval_ft(12.0, 1.5, PX_IS_FT, method="CROSS_SECTION")[0]
    assert (iv.lo, iv.hi) == pytest.approx((8.5, 15.5))                  # +/- (2 + 1.5), cross-section 1 px


def test_spike_scale_uncertainty_per_method():
    """D-38 / Q9: the cross-section's one pixel per edge at 0.44 m per pixel is about 0.88 m (2.9 ft) each way; the AI marks' 3 px are three times that."""
    cs = L.interval_ft(24.0, 0.0, 0.4419, method="CROSS_SECTION")[0]; ai = L.interval_ft(24.0, 0.0, 0.4419)[0]
    assert (cs.hi - cs.lo) / 2 == pytest.approx(2 * 0.4419 / 0.3048, rel=1e-9)
    assert (ai.hi - ai.lo) / 2 == pytest.approx(3 * (cs.hi - cs.lo) / 2)


def test_cross_section_keeps_one_pixel_and_marks_use_three():
    cs, _ = L.traveled_way_width(edges_marks(90, 30), PX_IS_FT, GOOD_SECTION)
    ai, _ = L.traveled_way_width(edges_marks(90, 24), PX_IS_FT)
    assert cs.pixel_error_px == 1.0 and ai.pixel_error_px == 3.0 and "CALIBRATION_PENDING" in cs.flags + ai.flags


def test_a_tapering_pair_widens_the_interval_by_its_spread():
    a = [(0.0, 0.0), (300.0, 0.0), (600.0, 0.0)]; b = [(0.0, 12.0), (300.0, 16.0), (600.0, 20.0)]
    m, _ = L.traveled_way_width([mark("road_edge_left", a), mark("road_edge_right", b)], PX_IS_FT)
    assert m.interval_ft.hi - m.interval_ft.lo == pytest.approx(2 * (6.0 + 8.0), abs=0.1)   # +/- (error term 6 ft + spread 8 ft)


# ---------------------------------------------------------------- sources and precedence (D-80)
GOOD_SECTION = {"status": "OK", "width_m": 7.3152, "spread_m": 0.0, "metres_per_pixel": 0.1}      # 24 ft
BAD_SECTION = {"status": "INCONCLUSIVE", "reason": "sections disagree by 0.9 m", "metres_per_pixel": 0.1}


def test_cross_section_first_when_both_are_available():
    m, _ = L.traveled_way_width(edges_marks(90, 30), PX_IS_FT, GOOD_SECTION)
    assert m.method == "CROSS_SECTION" and m.value_ft == pytest.approx(24.0)


def test_section_ok_and_marks_bad():
    m, _ = L.traveled_way_width([mark("road_edge_left", [(1, 1)], "UNKNOWN")], PX_IS_FT, GOOD_SECTION)
    assert m.method == "CROSS_SECTION"


def test_section_failed_and_marks_good():
    m, _ = L.traveled_way_width(edges_marks(90, 12), PX_IS_FT, BAD_SECTION)
    assert m.method == "AI_MARKS" and "INCONCLUSIVE" in m.calculation          # the failed section is named in the trace


def test_both_bad_gives_no_width_and_a_reason():
    assert L.traveled_way_width([mark("road_edge_left", [(1, 1), (9, 9)], "UNKNOWN")], PX_IS_FT, BAD_SECTION) == (None, "malformed")
    assert L.traveled_way_width([], PX_IS_FT) == (None, "missing")


@pytest.mark.parametrize("marks,reason", [
    ([Mark(feature="road_edge_left", points=((1.0, 1.0),), status="RESOLVED")], "malformed"),          # one point is not a line
    ([Mark(feature="road_edge_left", status="UNKNOWN", reason_code="not_stated")], "not_visible"),
])
def test_invalid_marks_give_a_reason(marks, reason):
    assert L.traveled_way_width(marks + [mark("road_edge_right", [(0, 0), (9, 0)])], PX_IS_FT)[1] == reason


def test_two_road_edge_marks_of_one_feature_are_ambiguous():
    a, b, _, _ = road(90, 12)
    marks = [mark("road_edge_left", a), mark("road_edge_left", a), mark("road_edge_right", b)]
    assert L.traveled_way_width(marks, PX_IS_FT) == (None, "ambiguous")


# ---------------------------------------------------------------- the straddle test reads the pack
def _iv(lo, hi): return Interval(lo=lo, hi=hi, unit="ft")


def test_no_limit_inside_gives_no_hit(pack):
    assert L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(10.5, 12.0)) == []
    assert L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(6.0, 8.5)) == []


def test_the_10_ft_limit_inside_is_found_from_the_pack(pack):
    hit = L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(9.5, 10.5))
    assert "E-TA6-REMAINING-WIDTH" in hit and "R-TA6-N1" in hit and "R-6N07-REMAINING-WIDTH" in hit


def test_the_9_ft_option_matters_only_when_its_other_conditions_could_hold(pack):
    assert "E-TA6-REMAINING-WIDTH" in L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(8.5, 9.5))
    ctx = {"duration": "SHORT_TERM", "traffic_volume": "LOW", "low_speed_road": True, "heavy_vehicles": False}
    # with the note 4 option fully met, 9 ft passes: the interval 9.2 to 9.8 holds no limit, 8.5 to 9.5 still holds the 9
    assert L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(9.2, 9.8), ctx) == [] or \
        "E-TA6-REMAINING-WIDTH" not in L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(9.2, 9.8), ctx)
    assert "E-TA6-REMAINING-WIDTH" in L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(8.5, 9.5), ctx)


def test_the_15_ft_edge_distance_is_found_from_the_pack(pack):
    assert "R-TA1-N3" in L.thresholds_inside(pack, "distance_from_edge_ft", _iv(14.0, 16.0))
    assert L.thresholds_inside(pack, "distance_from_edge_ft", _iv(20.0, 25.0)) == []


def test_a_point_interval_has_no_straddle(pack):
    assert L.thresholds_inside(pack, "remaining_lane_width_ft", _iv(10.0, 10.0)) == []


def test_unrelated_field_has_no_limit(pack):
    assert L.thresholds_inside(pack, "shoulder_width_ft", _iv(0.0, 99.0)) == []


def test_no_pack_threshold_is_typed_in_the_measurement_code(pack):
    """The numbers the pack uses as ft limits must not appear as numeric literals in the measurement modules."""
    limits = {float(e.value) for _, e in L._expressions(pack) for e in _cmps(e)
              if e.field.endswith("_ft") and isinstance(e.value, (int, float)) and not isinstance(e.value, bool)}
    assert limits and {9.0, 10.0, 15.0} <= limits
    for rel in ("src/tcp_planner/site_model/lengths.py", "src/tcp_planner/site_model/measure.py"):
        src = open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read()
        nums = {float(t.string) for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.NUMBER}
        assert not (nums & limits), (rel, nums & limits)


def _cmps(e):
    if isinstance(e, Cmp): yield e
    else:
        for x in (getattr(e, "all", None) or getattr(e, "any", None) or [getattr(e, "not_", None)]):
            if x is not None: yield from _cmps(x)


# ---------------------------------------------------------------- facts
CLEAN = {"parking_present": False, "shoulder_present": False}


def test_lane_width_is_the_traveled_way_over_the_lane_count_on_a_clean_road(pack):
    res = L.measure_lengths(edges_marks(90, 24), PX_IS_FT * 0.5, pack, total_lanes=2, gate=CLEAN)    # 12 ft over 2 lanes = 6 ft
    lane = next(f for f in res.facts if f.field == "lane_width_ft")
    assert lane.status == "UNKNOWN"                     # 6 ft is not a plausible lane, not accepted
    res = L.measure_lengths(edges_marks(90, 24), PX_IS_FT, pack, total_lanes=2, gate=CLEAN)
    lane = next(f for f in res.facts if f.field == "lane_width_ft")
    assert lane.status == "RESOLVED" and lane.value == pytest.approx(12.0) and lane.unit == "ft"
    assert (lane.interval.lo, lane.interval.hi) == pytest.approx((9.0, 15.0))              # (24 -+ 6) / 2, AI marks 3 px
    assert lane.measured.name == "lane_width" and "total_lanes=2" in lane.measured.inputs and "CALIBRATION_PENDING" in lane.flags
    assert res.measured["traveled_way_width"].value_ft == pytest.approx(24.0)


def test_lane_width_is_unknown_without_a_lane_count(pack):
    res = L.measure_lengths(edges_marks(90, 24), PX_IS_FT, pack, gate=CLEAN)
    lane = next(f for f in res.facts if f.field == "lane_width_ft")
    assert (lane.status, lane.reason_code, lane.value) == ("UNKNOWN", "missing", None)
    assert [q.kind for q in res.questions] == ["FACT_UNKNOWN"] and res.questions[0].reveals == ("lane_width_ft",)


@pytest.mark.parametrize("angle", [0, 33, 90, 135])
def test_distance_from_edge_for_any_road_direction(pack, angle):
    a, b, u, v = road(angle, 24)
    px, py = 500 + v[0] * (12 + 40), 500 + v[1] * (12 + 40)           # 40 px beyond the b edge
    marks = [mark("road_edge_left", a), mark("road_edge_right", b), mark("work_point", [(px, py)])]
    f = next(f for f in L.measure_lengths(marks, PX_IS_FT, pack).facts if f.field == "distance_from_edge_ft")
    assert f.status == "RESOLVED" and f.value == pytest.approx(40.0, abs=1e-6)


def test_distance_from_edge_is_unknown_between_the_edges(pack):
    a, b, _, _ = road(90, 24)
    marks = [mark("road_edge_left", a), mark("road_edge_right", b), mark("work_point", [(500, 505)])]
    f = next(f for f in L.measure_lengths(marks, PX_IS_FT, pack).facts if f.field == "distance_from_edge_ft")
    assert (f.status, f.reason_code) == ("UNKNOWN", "ambiguous") and f.measured.value_ft < 0


def test_distance_near_15_ft_becomes_unknown_with_a_question(pack):
    a, b, u, v = road(90, 24)
    px, py = 500 + v[0] * (12 + 15), 500 + v[1] * (12 + 15)
    marks = [mark("road_edge_left", a), mark("road_edge_right", b), mark("work_point", [(px, py)])]
    res = L.measure_lengths(marks, PX_IS_FT, pack)
    f = next(f for f in res.facts if f.field == "distance_from_edge_ft")
    assert (f.status, f.reason_code, f.value) == ("UNKNOWN", "threshold_in_interval", None)
    assert f.interval.lo < 15 < f.interval.hi and f.measured.value_ft == pytest.approx(15.0)      # the number stays visible
    wn = [q for q in res.questions if q.kind == "WIDTH_NEAR_THRESHOLD"]
    assert len(wn) == 1 and "R-TA1-N3" in wn[0].reason


def test_distance_far_from_every_limit_stays_resolved(pack):
    a, b, u, v = road(90, 24)
    px, py = 500 + v[0] * (12 + 60), 500 + v[1] * (12 + 60)
    marks = [mark("road_edge_left", a), mark("road_edge_right", b), mark("work_point", [(px, py)])]
    res = L.measure_lengths(marks, PX_IS_FT, pack)
    f = next(f for f in res.facts if f.field == "distance_from_edge_ft")
    assert f.status == "RESOLVED" and f.value == pytest.approx(60.0) and not [q for q in res.questions if q.kind == "WIDTH_NEAR_THRESHOLD"]


def test_shoulder_width_to_the_nearer_edge(pack):
    a, b, u, v = road(90, 24)
    sh = [(x + v[0] * 8, y + v[1] * 8) for x, y in b]       # shoulder edge 8 px beyond edge b
    marks = [mark("road_edge_left", a), mark("road_edge_right", b), mark("shoulder_edge", sh)]
    f = next(f for f in L.measure_lengths(marks, PX_IS_FT, pack).facts if f.field == "shoulder_width_ft")
    assert f.status == "RESOLVED" and f.value == pytest.approx(8.0, abs=1e-6)


def test_missing_shoulder_edge_gives_unknown_with_reason(pack):
    f = next(f for f in L.measure_lengths(edges_marks(90, 24), PX_IS_FT, pack).facts if f.field == "shoulder_width_ft")
    assert (f.status, f.reason_code) == ("UNKNOWN", "missing")


def test_median_width_has_no_source_in_call_1(pack):
    f = next(f for f in L.measure_lengths(edges_marks(90, 24), PX_IS_FT, pack).facts if f.field == "median_width_ft")
    assert (f.status, f.reason_code) == ("UNKNOWN", "no_source")


def test_every_length_fact_has_a_trace_and_a_contained_value(pack):
    a, b, u, v = road(60, 24)
    marks = edges_marks(60, 24) + [mark("work_point", [(500 + v[0] * 60, 500 + v[1] * 60)])]
    for f in L.measure_lengths(marks, PX_IS_FT, pack, total_lanes=2, gate=CLEAN).facts:
        if f.status == "RESOLVED":
            assert f.interval.lo <= f.value <= f.interval.hi and f.measured and f.measured.calculation and f.measured.inputs
            assert f.registry_id == f.field and f.unit == "ft" and f.source in ("AI_MARKS", "CROSS_SECTION")


def test_real_spike_marks_give_widths_with_intervals(pack):
    """Real model marks (E Second St, pre-tuning prompt): pixels only in, feet out, using the spike scale."""
    d = json.load(open(os.path.join(ROOT, "tests", "fixtures", "site", "spike", "raw", "second_B_r1.response.json"), encoding="utf-8"))
    text = next(b["text"] for b in d["content"] if b.get("type") == "text")
    mpp = json.load(open(os.path.join(ROOT, "tests", "fixtures", "site", "spike", "inputs", "second.json"), encoding="utf-8"))["metres_per_pixel"]
    tw = L.traveled_way_width(parse_call1(text, (1280, 1280)).marks, mpp)[0]
    assert tw.method == "AI_MARKS" and tw.interval_ft.lo < tw.value_ft < tw.interval_ft.hi
    assert tw.value_ft == pytest.approx(20 * mpp / 0.3048, rel=0.5)


def test_no_module_parses_a_number_from_evidence():
    for rel in ("lengths.py", "measure.py"):
        src = open(os.path.join(ROOT, "src", "tcp_planner", "site_model", rel), encoding="utf-8").read()
        assert "import re" not in src and "re.search" not in src
