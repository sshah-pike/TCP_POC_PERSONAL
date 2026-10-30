"""Applying the fusion rules (S6, owner answers to STOP 5): single source gives UNKNOWN plus a question CANDIDATE with the AI value
pre-filled; disagreement gives UNKNOWN; agreement stands; sidewalk is record only; a code check is never a second source."""
import pytest

from tcp_planner.data_sources.osm import OsmWay
from tcp_planner.site_model import fusion_apply as FA
from tcp_planner.site_model import fusion_v2 as FV
from tcp_planner.site_model import osm_rules as OR
from tcp_planner.site_model.facts import SiteFact
from tests.unit.site.test_osm import EW, way


def ai(field, value, flags=("NEEDS_SECOND_SOURCE",), registry=True, conf=0.9):
    from tcp_planner.site_model.outcomes import outcome_for
    return SiteFact(field=field, registry_id=field if registry else None, source="AI", outcome=outcome_for(field, value), value=value, confidence=conf,
                    evidence="seen", flags=flags)


def osm_of(**tags):
    return OR.osm_read([way(1, tags, EW)])


def run(facts, osm=None):
    return FA.fuse_fields(facts, osm)


def only(res, field): return next(f for f in res.facts if f.field == field)


# ---------------------------------------------------------------- agreement
def test_ai_and_osm_agree_the_fact_stands_without_the_second_source_flag():
    res = run([ai("lanes_per_direction", 2)], osm_of(lanes="4"))
    f = only(res, "lanes_per_direction")
    assert f.outcome == "FOUND" and f.value == 2 and f.source == "AI+osm_overpass" and "NEEDS_SECOND_SOURCE" not in f.flags
    assert res.records["lanes_per_direction"].agreement == FV.AGREE and res.questions == ()
    assert {c.source for c in f.candidates} == {"AI", "osm_overpass"}


def test_not_present_agreement_for_the_shoulder():
    f = only(run([ai("shoulder_present", False)], osm_of(shoulder="no")), "shoulder_present")
    assert f.outcome == "NOT_PRESENT" and f.value is False and f.source.startswith("AI+")


# ---------------------------------------------------------------- disagreement
def test_disagreement_is_unknown_with_both_values_kept_and_a_candidate_question():
    res = run([ai("lanes_per_direction", 3)], osm_of(lanes="4"))
    f = only(res, "lanes_per_direction")
    assert f.outcome == "UNKNOWN" and f.value is None and f.reason_code == "source_disagreement" and "NEEDS_SECOND_SOURCE" not in f.flags
    assert [(c.source, c.value) for c in f.candidates if c.value is not None] == [("AI", 3), ("osm_overpass", 2)]
    q = res.questions[0]
    assert q.kind == "LANES_DISAGREE" and q.candidate is True and q.suggested == 3 and q.field == "lanes_per_direction"


# ---------------------------------------------------------------- single source (owner answer 1)
def test_single_source_osm_not_consulted_is_unknown_with_the_ai_value_as_a_prefilled_candidate():
    res = run([ai("shoulder_present", True)], None)
    f = only(res, "shoulder_present")
    assert f.outcome == "UNKNOWN" and f.value is None and f.reason_code == "single_source" and "NEEDS_SECOND_SOURCE" not in f.flags
    assert f.candidates[-1].source == "AI" and f.candidates[-1].value is True                       # visible
    q = res.questions[0]
    assert q.candidate is True and q.suggested is True and q.kind == "FACT_UNKNOWN" and q.field == "shoulder_present" and q.options == ("True",)
    assert res.records["shoulder_present"].agreement == FV.SINGLE_SOURCE


def test_a_missing_osm_tag_is_a_single_source_too():
    res = run([ai("shoulder_present", False)], osm_of())            # no shoulder tag: no information
    assert only(res, "shoulder_present").reason_code == "single_source" and len(res.questions) == 1 and res.questions[0].suggested is False
    assert res.records["shoulder_present"].agreement == FV.UNDECIDABLE


def test_a_missing_oneway_tag_with_ai_true_is_single_source_and_ai_false_agrees_at_low_class():
    t = run([ai("oneway", True)], osm_of())
    assert only(t, "oneway").outcome == "UNKNOWN" and t.records["oneway"].agreement == FV.UNDECIDABLE
    f = run([ai("oneway", False)], osm_of())
    assert only(f, "oneway").outcome == "FOUND" and f.records["oneway"].agreement == FV.AGREE
    assert [c.confidence_class for c in f.records["oneway"].candidates if c.source == "osm_overpass"] == [FV.LOW]


def test_osms_own_question_is_the_one_asked_and_it_becomes_a_candidate():
    res = run([ai("lanes_per_direction", 1)], osm_of(lanes="3"))             # odd total, two-way
    assert len(res.questions) == 1 and res.questions[0].kind == "LANES_UNSPLIT" and res.questions[0].candidate is True and res.questions[0].suggested == 1
    assert res.questions[0].osm_way_id == 1


def test_a_source_failure_is_single_source():
    res = run([ai("divided_highway", False)], OR.source_failed("HTTP 429"))
    assert only(res, "divided_highway").reason_code == "single_source" and res.questions[0].candidate


def test_an_unknown_ai_reading_stays_unknown_with_its_own_reason_and_no_new_question():
    u = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="UNKNOWN", reason_code="occluded")
    res = run([u], osm_of(shoulder="yes"))
    assert only(res, "shoulder_present") == u and res.questions == ()


def test_every_candidate_question_is_non_blocking_and_prefilled():
    facts = [ai("lanes_per_direction", 2), ai("oneway", True), ai("shoulder_present", True), ai("divided_highway", False)]
    res = run(facts, None)
    assert len(res.questions) == 4 and all(q.candidate and q.suggested is not None for q in res.questions)


# ---------------------------------------------------------------- never a code check as second source
@pytest.mark.parametrize("source", ["CODE", "PIXEL_CHECK", "AI", "LANE_LINES", "SNAP", "azure_maps"])
def test_a_code_pixel_check_or_the_imagery_is_never_a_second_source(source):
    fake = OR.OsmRead(1, {}, {"lanes_per_direction": FV.SourceReading.found(source, 2)}, (), 1.0)
    with pytest.raises(ValueError, match="never a second source"): run([ai("lanes_per_direction", 2)], fake)


def test_the_allowed_second_sources_are_the_enabled_data_sources_without_the_imagery():
    assert FA.second_sources() == frozenset({"osm_overpass"})
    assert FA.second_sources({"sources": {"osm_overpass": {"enabled": True, "hosts": ["h"]}, "azure_maps": {"enabled": True, "hosts": ["h"]},
                                          "massgis": {"enabled": False, "hosts": []}}}) == frozenset({"osm_overpass"})


# ---------------------------------------------------------------- sidewalk: record only (owner answer 3)
def test_sidewalk_disagreement_is_recorded_lowers_the_class_to_low_and_asks_nothing():
    fact = ai("sidewalk_present", True, flags=("CONTEXT_ONLY",), registry=False)
    res = run([fact], osm_of(sidewalk="no"))
    f = only(res, "sidewalk_present")
    assert f.value is True and f.outcome == "FOUND" and f.reason_code is None and res.questions == ()          # value untouched, no question
    assert res.records["sidewalk_present"].agreement == FV.DISAGREE
    osm_c = [c for c in f.candidates if c.source == "osm_overpass"][0]
    assert osm_c.confidence_class == FV.LOW and osm_c.outcome == "NOT_PRESENT"


def test_sidewalk_agreement_is_recorded_as_medium_and_no_osm_tag_changes_nothing():
    fact = ai("sidewalk_present", True, flags=("CONTEXT_ONLY",), registry=False)
    agree = only(run([fact], osm_of(sidewalk="both")), "sidewalk_present")
    assert [c.confidence_class for c in agree.candidates if c.source == "osm_overpass"] == [FV.MEDIUM]
    none = only(run([fact], osm_of()), "sidewalk_present")                         # no OSM sidewalk tag: nothing to compare
    assert none.value is True and none.outcome == "FOUND" and [c.outcome for c in none.candidates] == ["UNKNOWN"]
    assert only(run([fact], None), "sidewalk_present") == fact


def test_other_facts_pass_through_unchanged():
    f = ai("parking_present", True, flags=("CONTEXT_ONLY",), registry=False)
    assert run([f], osm_of(shoulder="yes")).facts == (f,)
