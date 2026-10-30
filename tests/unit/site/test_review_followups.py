"""Owner replies after STOP 3: shadow vehicle layout_not_allowed, the per-TA meaning of the omission input, and the
PROPOSED-footprint review gate."""
import pytest

from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import precalc as P
from tcp_planner.site_model.facts import Interval, MeasuredLength, SiteFact, rule_inputs


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def lane(value):
    iv = Interval(lo=value, hi=value, unit="ft")
    m = MeasuredLength(name="lane_width", value_ft=value, interval_ft=iv, method="AI_MARKS", mpp=0.3, pixel_error_px=3.0, inputs=("x",), calculation="c")
    return SiteFact(field="lane_width_ft", registry_id="lane_width_ft", value=value, unit="ft", source="AI_MARKS", status="RESOLVED", interval=iv, measured=m)


# ---------------------------------------------------------------- shadow vehicle: the decision table, row by row
def test_layout_omits_but_the_duration_does_not_allow_it_is_layout_not_allowed(pack):
    f, q = P.shadow_vehicle(pack, "TA-6", {"duration": "LONG_TERM"}, True)
    assert (f.status, f.value, f.reason_code) == ("UNKNOWN", None, "layout_not_allowed") and "SOURCE_REVIEW_REQUIRED" in f.flags
    assert q.kind == "LAYOUT_NOT_ALLOWED" and q.options == ("change the layout", "change the duration") and q.reveals == ("shadow_vehicle_present",)
    assert "R-TA6-N10" in q.reason and "SHORT_DURATION" in q.reason and "LONG_TERM" in q.reason          # names the note and the allowed duration
    assert "the layout omits taper and devices" in q.reason and "the taper and channelizing devices may be omitted" in q.reason


@pytest.mark.parametrize("ta,duration,allowed", [("TA-6", "SHORT_TERM", "SHORT_DURATION"), ("TA-6", "MOBILE", "SHORT_DURATION"),
                                                ("TA-1", "LONG_TERM", "SHORT_TERM or SHORT_DURATION or MOBILE"),
                                                ("TA-1", "INTERMEDIATE", "SHORT_TERM or SHORT_DURATION or MOBILE")])
def test_the_question_lists_the_durations_the_note_allows(pack, ta, duration, allowed):
    f, q = P.shadow_vehicle(pack, ta, {"duration": duration}, True)
    assert f.reason_code == "layout_not_allowed" and f"only for duration {allowed}" in q.reason


def test_it_is_never_true_or_false_when_the_layout_is_not_allowed(pack):
    for ta, d in (("TA-6", "LONG_TERM"), ("TA-1", "LONG_TERM"), ("TA-10", "SHORT_DURATION"), ("TA-33", "MOBILE")):
        f, q = P.shadow_vehicle(pack, ta, {"duration": d}, True)
        assert f.value is None and f.status == "UNKNOWN" and q is not None, (ta, d)


def test_a_ta_with_no_note_for_it_never_allows_the_omission(pack):
    for ta in ("TA-10", "TA-33"):
        f, q = P.shadow_vehicle(pack, ta, {"duration": "SHORT_DURATION"}, True)
        assert f.reason_code == "layout_not_allowed" and f"no note of {ta} allows" in q.reason


def test_the_unknown_layout_result_makes_a_result_review_required(pack):
    f, _ = P.shadow_vehicle(pack, "TA-6", {"duration": "LONG_TERM"}, True)
    assert "SOURCE_REVIEW_REQUIRED" in f.flags and f.status == "UNKNOWN"          # the flag that forces REVIEW_REQUIRED (CLAUDE.md rule 2)


def test_every_other_row_of_the_table(pack):
    assert P.shadow_vehicle(pack, "TA-6", {"duration": "SHORT_DURATION"}, True)[0].value is True
    assert P.shadow_vehicle(pack, "TA-6", {"duration": "LONG_TERM"}, False)[0].value is False
    assert P.shadow_vehicle(pack, "TA-6", {"duration": "LONG_TERM"}, None)[0].reason_code == "missing"
    f, q = P.shadow_vehicle(pack, "TA-6", {}, True)                             # duration unknown: not decidable, so no question here
    assert (f.reason_code, q) == ("missing", None)


# ---------------------------------------------------------------- TA-1 note 4 and TA-6 note 10: one fact, shown in the trace
def test_the_note_text_is_in_the_trace_for_both_tas(pack):
    f1, _ = P.shadow_vehicle(pack, "TA-1", {"duration": "SHORT_TERM"}, True)
    f6, _ = P.shadow_vehicle(pack, "TA-6", {"duration": "SHORT_DURATION"}, True)
    assert "R-TA1-N4" in f1.evidence and "all signs and channelizing devices may be eliminated" in f1.evidence
    assert "R-TA6-N10" in f6.evidence and "the taper and channelizing devices may be omitted" in f6.evidence
    assert "activated high-intensity" in f1.evidence and "activated high-intensity" in f6.evidence


def test_what_the_input_means_per_ta_is_written_down_and_matches_the_pack(pack):
    assert P.OMISSION_MEANING == {"TA-1": "the layout omits signs and devices", "TA-6": "the layout omits taper and devices"}
    assert "SIGNS_AND_DEVICES" in P.shadow_rules(pack, "TA-1")[0].action and "TAPER_AND_DEVICES" in P.shadow_rules(pack, "TA-6")[0].action
    f1, _ = P.shadow_vehicle(pack, "TA-1", {"duration": "MOBILE"}, True); f6, _ = P.shadow_vehicle(pack, "TA-6", {"duration": "SHORT_DURATION"}, True)
    assert "the layout omits signs and devices" in f1.evidence and "the layout omits taper and devices" in f6.evidence


def test_the_input_is_named_layout_omits_not_taper_and_devices():
    import inspect
    assert list(inspect.signature(P.shadow_vehicle).parameters) == ["pack", "ta_id", "context", "layout_omits"]


# ---------------------------------------------------------------- the PROPOSED footprint gate
def test_a_result_that_used_the_proposed_footprint_is_review_required_and_names_it(pack):
    depth, _ = P.encroachment_depth(3.0, 0.5)
    rem, _ = P.remaining_lane_width(pack, lane(14.0), depth)
    decision, reasons = rule_inputs([depth, rem]).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED
    assert ("encroachment_depth_ft", "PROPOSED") in {(r["fact"], r["flag"]) for r in reasons}
    assert "proposed footprint" in next(r["reason"] for r in reasons if r["fact"] == "encroachment_depth_ft")


def test_an_sme_override_number_clears_it(pack):
    depth, _ = P.encroachment_depth(3.0, 0.5, sme_override_ft=2.0)
    rem, _ = P.remaining_lane_width(pack, lane(14.0), depth)
    assert rule_inputs([depth, rem]).gate(SUPPORTED_AUTO) == (SUPPORTED_AUTO, [])


def test_a_result_that_did_not_read_the_footprint_is_not_gated(pack):
    depth, _ = P.encroachment_depth(3.0, 0.5)
    assert rule_inputs([depth]).gate(SUPPORTED_AUTO, used=["lane_width_ft"]) == (SUPPORTED_AUTO, [])
    assert rule_inputs([depth]).gate(SUPPORTED_AUTO, used=["encroachment_depth_ft"])[0] == REVIEW_REQUIRED
