"""Pre-calculation (S6 commit 4): vehicle width, footprint, remaining width, the remaining-width table, and the TA-dependent
pure functions. The pack is read; no regulatory value is typed in the code (test_lengths scans for that)."""
import io, os, tokenize

import pytest

from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import precalc as P
from tcp_planner.site_model.facts import Interval, MeasuredLength, SiteFact

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OPTION_MET = {"duration": "SHORT_TERM", "traffic_volume": "LOW", "low_speed_road": True, "heavy_vehicles": False}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def lane(value, half=0.0):
    iv = Interval(lo=value - half, hi=value + half, unit="ft")
    m = MeasuredLength(name="lane_width", value_ft=value, interval_ft=iv, method="AI_MARKS", mpp=0.3, pixel_error_px=3.0, inputs=("x",), calculation="c",
                       flags=("CALIBRATION_PENDING",))
    return SiteFact(field="lane_width_ft", registry_id="lane_width_ft", value=value, unit="ft", source="AI_MARKS", status="RESOLVED",
                    interval=iv, measured=m, flags=("CALIBRATION_PENDING",))


def remaining(pack, lane_ft, depth_ft, half=0.0, ctx=None):
    depth = P.encroachment_depth(depth_ft, 0.0)[0]
    return P.remaining_lane_width(pack, lane(lane_ft, half), depth, ctx)


# ---------------------------------------------------------------- pack and config are the only sources
def test_the_table_limits_come_from_the_pack(pack):
    full, opt, cond, fid, oid = P._limits(pack)
    assert (full, opt) == (10, 9) and fid == "R-6N07-REMAINING-WIDTH" and oid == "R-6N07-NINE-FT-OPTION"   # these tests state the table's numbers
    assert cond is not None


def test_no_ft_limit_is_typed_in_precalc(pack):
    limits = {9.0, 10.0, 15.0}
    src = open(os.path.join(ROOT, "src", "tcp_planner", "site_model", "precalc.py"), encoding="utf-8").read()
    nums = {float(t.string) for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.NUMBER}
    assert not (nums & limits)


def test_the_freeway_enum_value_is_in_the_registry(pack):
    enum = next(r for r in pack.records("registry_field") if r.id == "road_type").enum_values
    assert P.EXPRESSWAY in enum


# ---------------------------------------------------------------- vehicle width
def test_default_vehicle_width_is_102_in_flagged_and_optional():
    f = P.work_vehicle_width()
    assert f.value == pytest.approx(8.5) and f.unit == "ft" and "DEFAULT_ASSUMED" in f.flags and f.source == "DEFAULT"
    assert "23 CFR 658.15" in f.evidence
    off = P.work_vehicle_width(use_default=False)
    assert (off.status, off.reason_code) == ("UNKNOWN", "no_source")


def test_a_measured_vehicle_width_replaces_the_default_and_has_no_flag():
    f = P.work_vehicle_width(measured_ft=7.9)
    assert f.value == 7.9 and f.source == "GEOMETRY" and "DEFAULT_ASSUMED" not in f.flags


# ---------------------------------------------------------------- footprint
def test_depth_and_clearance_unknown_gives_unknown_and_one_question():
    f, q = P.encroachment_depth()
    assert (f.status, f.reason_code) == ("UNKNOWN", "no_source") and "SOURCE_REVIEW_REQUIRED" in f.flags
    assert q.kind == "FACT_UNKNOWN" and set(q.reveals) == {"encroachment_depth_ft", "remaining_lane_width_ft"}
    assert P.encroachment_depth(4.0, None)[0].status == "UNKNOWN" and P.encroachment_depth(None, 1.0)[0].status == "UNKNOWN"


def test_the_default_vehicle_width_alone_never_makes_a_footprint():
    veh = P.work_vehicle_width()
    f, q = P.encroachment_depth(None, None, veh, include_vehicle=True)
    assert f.status == "UNKNOWN" and q is not None


def test_footprint_is_the_deepest_extent_plus_clearance():
    assert P.encroachment_depth(4.0, 1.5)[0].value == pytest.approx(5.5)
    veh = P.work_vehicle_width()                                   # 8.5 ft
    f, _ = P.encroachment_depth(4.0, 1.5, veh, include_vehicle=True)
    assert f.value == pytest.approx(10.0) and "DEFAULT_ASSUMED" in f.flags                 # the default flag follows the number
    assert P.encroachment_depth(4.0, 1.5, veh, include_vehicle=False)[0].value == pytest.approx(5.5)
    assert P.encroachment_depth(12.0, 1.5, veh, include_vehicle=True)[0].flags == ("PROPOSED",)   # work space deeper: no default flag


# ---------------------------------------------------------------- remaining width
def test_remaining_width_is_lane_minus_depth_with_the_shifted_interval(pack):
    f, q = remaining(pack, 14.0, 3.0, half=1.0)
    assert f.status == "RESOLVED" and q is None and f.value == pytest.approx(11.0)
    assert (f.interval.lo, f.interval.hi) == pytest.approx((10.0, 12.0))
    assert f.measured.inputs == ("lane_width_ft=14.0", "encroachment_depth_ft=3.0") and f.source == "GEOMETRY"


def test_remaining_width_is_unknown_without_lane_or_depth(pack):
    unk = SiteFact(field="lane_width_ft", registry_id="lane_width_ft", unit="ft", source="CODE", status="UNKNOWN", reason_code="ambiguous")
    depth_unknown = P.encroachment_depth()[0]
    assert P.remaining_lane_width(pack, unk, P.encroachment_depth(3.0, 0.0)[0])[0].reason_code == "ambiguous"
    assert P.remaining_lane_width(pack, lane(12.0), depth_unknown)[0].reason_code == "no_source"
    assert P.remaining_lane_width(pack, None, None)[0].status == "UNKNOWN"


def test_a_pack_limit_inside_the_remaining_interval_gives_unknown_and_a_question(pack):
    f, q = remaining(pack, 13.0, 3.0, half=0.6)                      # remaining 10.0 +/- 0.6
    assert (f.status, f.reason_code) == ("UNKNOWN", "threshold_in_interval") and q.kind == "WIDTH_NEAR_THRESHOLD"
    assert f.measured.value_ft == pytest.approx(10.0)
    assert P.remaining_width_decision(pack, f).result == "UNKNOWN"


def test_remaining_width_carries_the_calibration_flag(pack):
    assert "CALIBRATION_PENDING" in remaining(pack, 14.0, 2.0)[0].flags


# ---------------------------------------------------------------- the table, every row
TABLE = [  # remaining ft, context, result
    (12.0, {}, P.HOLD), (10.5, {"heavy_vehicles": True}, P.HOLD), (10.0, {}, P.HOLD),                     # 10 ft or more: any context
    (9.5, OPTION_MET, P.HOLD_NINE), (9.0, OPTION_MET, P.HOLD_NINE),                                        # 9 to 10, option met
    (9.5, {**OPTION_MET, "heavy_vehicles": True}, P.CLOSURE),                                              # heavy vehicles
    (9.5, {k: v for k, v in OPTION_MET.items() if k != "heavy_vehicles"}, P.CLOSURE),                      # heavy unknown
    (9.5, {**OPTION_MET, "traffic_volume": "HIGH"}, P.CLOSURE),                                            # volume
    (9.5, {**OPTION_MET, "duration": "LONG_TERM"}, P.CLOSURE),                                             # duration
    (9.5, {**OPTION_MET, "low_speed_road": False}, P.CLOSURE),                                             # speed
    (9.5, {k: v for k, v in OPTION_MET.items() if k != "low_speed_road"}, P.CLOSURE),                      # low-speed unknown
    (9.5, {}, P.CLOSURE),                                                                                   # nothing known
    (8.9, OPTION_MET, P.CLOSURE), (8.0, {}, P.CLOSURE), (4.0, OPTION_MET, P.CLOSURE),                      # under 9 ft
]


@pytest.mark.parametrize("value,ctx,result", TABLE, ids=[f"{v}-{i}" for i, (v, _, _) in enumerate(TABLE)])
def test_remaining_width_table_row(pack, value, ctx, result):
    f, _ = remaining(pack, value, 0.0, ctx=ctx)
    assert f.status == "RESOLVED"
    d = P.remaining_width_decision(pack, f, ctx)
    assert d.result == result
    assert (d.label is not None) == (result == P.HOLD_NINE)           # the 9 ft option is labelled on the plan


def test_band_row_is_unknown_for_each_limit(pack):
    for centre, half in ((10.0, 0.5), (9.0, 0.5)):
        f, q = remaining(pack, centre, 0.0, half=half, ctx=OPTION_MET)
        d = P.remaining_width_decision(pack, f, OPTION_MET)
        assert f.status == "UNKNOWN" and d.result == "UNKNOWN" and q is not None, centre


def test_unknown_width_gives_unknown_decision(pack):
    d = P.remaining_width_decision(pack, P.remaining_lane_width(pack, None, None)[0])
    assert d.result == "UNKNOWN" and "unknown" in d.reason


def test_the_decision_names_the_pack_rules_in_its_reason(pack):
    f, _ = remaining(pack, 9.5, 0.0, ctx=OPTION_MET)
    assert "R-6N07-NINE-FT-OPTION" in P.remaining_width_decision(pack, f, OPTION_MET).reason


# ---------------------------------------------------------------- TA-dependent pure functions
def test_freeway_flag_from_road_type():
    assert P.freeway("EXPRESSWAY_FREEWAY").value is True and P.freeway("RURAL").value is False and P.freeway(None).status == "UNKNOWN"


def test_shadow_vehicle_required_when_the_duration_allows_the_omission(pack):
    f, q = P.shadow_vehicle(pack, "TA-6", {"duration": "SHORT_DURATION"}, True)
    assert f.value is True and q is None and "R-TA6-N10" in f.evidence and "the taper and channelizing devices may be omitted" in f.evidence
    assert P.shadow_vehicle(pack, "TA-1", {"duration": "MOBILE"}, True)[0].value is True
    assert P.shadow_vehicle(pack, "TA-6", {}, True)[0].reason_code == "missing"
    off, _ = P.shadow_vehicle(pack, "TA-6", {"duration": "SHORT_DURATION"}, False)
    assert off.value is False and "optional" in off.evidence
    assert P.shadow_vehicle(pack, "TA-6", {}, None)[0].status == "UNKNOWN"


def test_tma_suggestion_is_off_while_the_pack_has_no_threshold(pack):
    f = P.tma_suggestion(pack, 55)
    assert (f.status, f.reason_code) == ("UNKNOWN", "no_source") and f.value is None and "SOURCE_REVIEW_REQUIRED" in f.flags


def test_tma_suggestion_uses_a_sourced_threshold_and_is_labelled_policy(pack):
    class R:  # a pack whose threshold rule has a source
        id = "R-X"; topic = "truck_mounted_attenuator"; unit = "mph"; value = 45; role = "APPLY"
        from tcp_planner.rules.rule_pack_models import Status as _S
        status = _S.SOURCED
    class FakePack:
        def records(self, t): return [R] if t == "rule" else []
    assert P.tma_suggestion(FakePack(), 50).value is True and P.tma_suggestion(FakePack(), 40).value is False
    assert "POLICY_SUGGESTED" in P.tma_suggestion(FakePack(), 50).flags


def test_arrow_board_mandatory_on_a_freeway_lane_closure(pack):
    f = P.arrow_board(pack, {"freeway": True, "lane_closure": True})
    assert f.value is True and "R-TA33-N7" in f.evidence
    assert P.arrow_board(pack, {"freeway": False, "lane_closure": True}).value is False
    assert P.arrow_board(pack, {"freeway": False, "lane_closure": True, "arrow_board_wanted": True}).value is True
    assert P.arrow_board(pack, {"freeway": True, "lane_closure": False}).value is False
    assert P.arrow_board(pack, {"lane_closure": True}).status == "UNKNOWN"        # freeway not known: the condition cannot be decided


def test_the_pure_functions_do_not_touch_the_start_facts(pack):
    ctx = {"freeway": True, "lane_closure": True}; before = dict(ctx)
    P.arrow_board(pack, ctx); P.shadow_vehicle(pack, "TA-6", ctx, True); P.remaining_width_decision(pack, None, ctx)
    assert ctx == before
