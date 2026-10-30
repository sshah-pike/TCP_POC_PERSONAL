"""TA layer of rule pack v1: notes, figure transcriptions, device sequences and eligibility on synthetic fact sets.

The fact sets below are synthetic test inputs, not data read from any KML or drawing. The three named after the
reference jobs carry the facts those jobs are described with in plan section 6 (owner decision Q6).
"""
import pytest
from tcp_planner.rules.rule_pack_eval import ELIGIBLE, NOT_ELIGIBLE, UNDETERMINED, evaluate_eligibility, screen_tas
from tcp_planner.rules.rule_pack_models import Evidence
from tcp_planner.rules.rule_pack_store import JsonRulePackStore

NOTES = {"6P-1": 6, "6P-6": 14, "6P-10": 13, "6P-33": 7}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def test_every_figure_note_is_loaded_with_a_quote(pack):
    for fig, n in NOTES.items():
        refs = [r for r in pack.records("source_ref") if r.figure == fig and r.note]
        assert sorted(int(r.note) for r in refs) == list(range(1, n + 1)) and all(r.evidence == Evidence.QUOTE for r in refs)
        cited = {s for r in pack.records("rule") for s in r.source_ref_ids}
        assert {r.id for r in refs} <= cited | {s for c in pack.records("eligibility_condition") for s in c.source_ref_ids}


def test_figure_only_values_are_never_applied(pack):
    """A number read only from a drawing is either SOURCE_REVIEW_REQUIRED or cited only next to a text source."""
    fig = {r.id for r in pack.records("source_ref") if r.evidence == Evidence.FIGURE_TRANSCRIPTION}
    for r in pack.records("rule"):
        if r.source_ref_ids and set(r.source_ref_ids) <= fig:
            if r.value is not None or r.value_max is not None: assert r.role == "CITED_ONLY" and r.overlaps, r.id
            if r.unit and r.value is None: assert r.status.value == "SOURCE_REVIEW_REQUIRED", r.id


def test_every_figure_transcription_points_at_its_render(pack):
    for r in pack.records("source_ref"):
        if r.evidence == Evidence.FIGURE_TRANSCRIPTION:
            assert r.figure_render.uri.endswith(f"figure_{r.figure}_p{r.page_printed}.png")


@pytest.mark.parametrize("ta,seq", [
    ("TA-1", [("W20-1", 1, "A")]),
    ("TA-10", [("W20-7", 1, "A"), ("W20-4", 2, "B"), ("W20-1", 3, "C")]),
    ("TA-33", [("W4-2R", 1, "A"), ("W20-5R", 2, "B"), ("W20-1", 3, "C")]),
    ("TA-6", [("W20-1", 1, "A")]),
])
def test_advance_sign_sequences_follow_the_figures(pack, ta, seq):
    uses = [u for u in pack.records("ta_device_use") if u.ta_id == ta and u.spacing_dimension]
    got = sorted((pack.get(u.device_id).code, u.sequence, u.spacing_dimension) for u in uses)
    assert got == sorted(seq) and all(u.required for u in uses)


# ---------- eligibility (synthetic fact sets) ----------
COLORADO_TA10 = {"road_type": "URBAN_LOW_SPEED", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": True,
                 "work_location": "IN_LANE", "oneway": False, "divided_highway": False, "lanes_per_direction": 1}
E_SECOND_TA6 = {"road_type": "URBAN_LOW_SPEED", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False,
                "work_location": "ON_SHOULDER_OR_ENCROACHING", "shoulder_present": True, "remaining_lane_width_ft": 11,
                "oneway": False, "divided_highway": False, "lanes_per_direction": 1}
GRANITE_TA33_UNDIVIDED = {"road_type": "URBAN_HIGH_SPEED", "posted_speed_mph": 35, "traffic_volume": "HIGH", "lane_closure": True,
                          "work_location": "IN_LANE", "oneway": False, "divided_highway": False, "lanes_per_direction": 2,
                          "closed_lane_side": "RIGHT"}
DIVIDED_TA33 = dict(GRANITE_TA33_UNDIVIDED, divided_highway=True)
BEYOND_SHOULDER_TA1 = {"road_type": "RURAL", "posted_speed_mph": 45, "traffic_volume": "HIGH", "lane_closure": False,
                       "work_location": "BEYOND_SHOULDER"}


def _results(pack, facts):
    return {ta: r["result"] for ta, r in screen_tas(pack, facts)["per_ta"].items()}


def test_colorado_facts_match_ta10_only(pack):
    assert _results(pack, COLORADO_TA10) == {"TA-1": NOT_ELIGIBLE, "TA-6": NOT_ELIGIBLE, "TA-10": ELIGIBLE, "TA-33": NOT_ELIGIBLE}


def test_e_second_facts_leave_ta6_undetermined_on_its_unsourced_conditions(pack):
    assert _results(pack, E_SECOND_TA6) == {"TA-1": NOT_ELIGIBLE, "TA-6": UNDETERMINED, "TA-10": NOT_ELIGIBLE, "TA-33": NOT_ELIGIBLE}
    r = evaluate_eligibility(pack, "TA-6", E_SECOND_TA6)
    assert [q["condition_id"] for q in r["questions"]] == ["E-TA6-MINOR-ROAD"]
    assert {c["condition_id"]: c["result"] for c in r["conditions"]}["E-TA6-LOW-SPEED"] is None   # cutoff has no source


def test_granite_undivided_facts_match_ta33_through_the_6n11_four_lane_reading(pack):
    """S4b stage E: undivided, two lanes each way, right lane closed is sourced from Sect. 6N.11 paras 02 and 06."""
    assert _results(pack, GRANITE_TA33_UNDIVIDED) == {"TA-1": NOT_ELIGIBLE, "TA-6": NOT_ELIGIBLE, "TA-10": NOT_ELIGIBLE, "TA-33": ELIGIBLE}
    r = evaluate_eligibility(pack, "TA-33", GRANITE_TA33_UNDIVIDED)
    rows = {c["condition_id"]: c["result"] for c in r["conditions"]}
    assert rows["E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT"] is True and rows["E-TA33-FORM-DIVIDED"] is False
    assert r["questions"] == []
    assert pack.get("E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT").interpretation.startswith("INTERPRETATION (owner-confirmed")


@pytest.mark.parametrize("change", [
    {"lanes_per_direction": 3},                       # three or more lanes each way
    {"closed_lane_side": "MEDIAN_SIDE"},              # left-hand lane closed
    {"lanes_per_direction": 3, "closed_lane_side": "MEDIAN_SIDE"},
])
def test_broader_undivided_cases_stay_source_review_required(pack, change):
    facts = dict(GRANITE_TA33_UNDIVIDED, **change)
    r = evaluate_eligibility(pack, "TA-33", facts)
    assert r["result"] == UNDETERMINED
    assert [q["condition_id"] for q in r["questions"]] == ["E-TA33-FORM-UNDIVIDED-OTHER"]


def test_undivided_without_the_closed_lane_side_is_undetermined_not_a_match(pack):
    facts = {k: v for k, v in GRANITE_TA33_UNDIVIDED.items() if k != "closed_lane_side"}
    assert evaluate_eligibility(pack, "TA-33", facts)["result"] == UNDETERMINED


def test_the_6n11_split_keeps_one_sourced_reading_and_one_open_question(pack):
    sourced, open_ = pack.get("R-6N11-TA33-UNDIVIDED-FOUR-LANE-RIGHT"), pack.get("R-6N11-TA33-UNDIVIDED-OTHER")
    assert sourced.status.value == "SOURCED" and set(sourced.source_ref_ids) == {"SR-6N11-P02", "SR-6N11-P06"}
    assert open_.status.value == "SOURCE_REVIEW_REQUIRED" and open_.sme_question and open_.condition is None


def test_divided_highway_matches_ta33_as_encoded(pack):
    assert _results(pack, DIVIDED_TA33)["TA-33"] == ELIGIBLE
    assert screen_tas(pack, DIVIDED_TA33)["eligible"] == ["TA-33"]


def test_beyond_shoulder_matches_ta1_only(pack):
    assert screen_tas(pack, BEYOND_SHOULDER_TA1)["eligible"] == ["TA-1"]


def test_one_way_single_lane_closure_is_no_ta_match(pack):
    facts = dict(COLORADO_TA10, oneway=True)
    s = screen_tas(pack, facts)
    assert s["decision"] == "NO_TA_MATCH" and s["eligible"] == [] and s["undetermined"] == []


def test_missing_fact_gives_undetermined_not_a_match(pack):
    facts = {k: v for k, v in COLORADO_TA10.items() if k != "lanes_per_direction"}
    assert evaluate_eligibility(pack, "TA-10", facts)["result"] == UNDETERMINED


def test_ta33_road_form_is_one_ored_rule(pack):
    groups = {c.any_group for c in pack.records("eligibility_condition") if c.ta_id == "TA-33" and c.id.startswith("E-TA33-FORM")}
    assert groups == {"ROAD_FORM"}
    failed = evaluate_eligibility(pack, "TA-33", dict(DIVIDED_TA33, lanes_per_direction=1))["failed"]
    assert failed == ["E-TA33-MULTI-LANE"]
