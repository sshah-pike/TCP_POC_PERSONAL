"""FOUND, NOT_PRESENT, UNKNOWN (S6 commit 2): fact model, parser, fusion, and the written meaning per field."""
import json

import pytest
from pydantic import ValidationError

from tcp_planner.ai import call1
from tcp_planner.site_model import fusion_v2 as fu
from tcp_planner.site_model import outcomes as oc
from tcp_planner.site_model.facts import SiteFact, rule_inputs


def _wire(field, value, status="RESOLVED", conf=0.9, evidence="seen"):
    row = call1.BY_NAME[field]
    return {"field": field, "value": value, "unit": row.kind if row.kind != "enum" else "enum", "status": status,
            "confidence": conf, "evidence": evidence}


def _parse(*facts):
    return call1.parse_call1(json.dumps({"facts": list(facts), "marks": []}))


# ---------------------------------------------------------------- the written table
def test_every_call1_field_has_a_written_outcome_meaning():
    assert set(oc.NOT_PRESENT_MEANING) == {r.name for r in call1.FIELDS}
    for name, meaning in oc.NOT_PRESENT_MEANING.items():
        assert meaning is None or (isinstance(meaning, str) and len(meaning) > 20), name


def test_only_yes_no_presence_fields_and_two_none_enums_have_not_present():
    for r in call1.FIELDS:
        if oc.has_not_present(r.name):
            assert r.kind == "bool" or r.name in oc.ABSENT_VALUES, r.name
    assert not oc.has_not_present("lanes_per_direction") and not oc.has_not_present("oneway") and not oc.has_not_present("work_location")


def test_outcome_for_values():
    assert oc.outcome_for("shoulder_present", False) == oc.NOT_PRESENT
    assert oc.outcome_for("shoulder_present", True) == oc.FOUND
    assert oc.outcome_for("shoulder_present", None) == oc.UNKNOWN
    assert oc.outcome_for("oneway", False) == oc.FOUND                  # a two-way road is a classification
    assert oc.outcome_for("sidewalk_side", "NONE") == oc.NOT_PRESENT and oc.outcome_for("sidewalk_side", "N") == oc.FOUND
    assert oc.outcome_for("obstructions", "none") == oc.NOT_PRESENT and oc.outcome_for("obstructions", "parked truck") == oc.FOUND
    assert oc.outcome_for("lanes_per_direction", 0) == oc.FOUND


# ---------------------------------------------------------------- parser
def test_parser_outcomes():
    r = _parse(_wire("shoulder_present", "false"), _wire("parking_present", "true"), _wire("oneway", "false"),
               _wire("lanes_per_direction", "2"), _wire("bus_stop_present", "UNKNOWN", status="UNKNOWN", evidence="occluded"),
               _wire("driveway_present", "maybe"))
    o = r.observations
    assert o["shoulder_present"].outcome == oc.NOT_PRESENT and o["parking_present"].outcome == oc.FOUND
    assert o["oneway"].outcome == oc.FOUND and o["lanes_per_direction"].outcome == oc.FOUND
    assert o["bus_stop_present"].outcome == oc.UNKNOWN and o["bus_stop_present"].reason_code == "occluded"
    assert o["driveway_present"].outcome == oc.UNKNOWN and o["driveway_present"].reason_code == "malformed"
    assert o["crosswalk_present"].outcome == oc.UNKNOWN                 # not returned: UNKNOWN, never NOT_PRESENT


def test_site_facts_carry_the_outcome():
    r = _parse(_wire("shoulder_present", "false"), _wire("sidewalk_present", "true"), _wire("sidewalk_side", "NONE"),
               _wire("parking_present", "UNKNOWN", status="UNKNOWN", evidence="low_resolution"))
    facts, _ = call1.to_site_facts(r)
    by = {f.field: f for f in facts}
    assert by["shoulder_present"].outcome == oc.NOT_PRESENT and by["shoulder_present"].value is False
    assert by["sidewalk_present"].outcome == oc.FOUND and by["sidewalk_side"].outcome == oc.NOT_PRESENT
    assert by["parking_present"].outcome == oc.UNKNOWN and by["parking_present"].reason_code == "low_resolution"
    assert all(f.outcome in oc.OUTCOMES for f in facts)


# ---------------------------------------------------------------- fact model
def test_fact_model_rejects_inconsistent_outcomes():
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="UNKNOWN", value=True)
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="FOUND")
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="NOT_PRESENT")
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="NOT_PRESENT", value=True)
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="MAYBE")
    assert SiteFact(field="x", source="AI", outcome="NOT_PRESENT", value=False).status == "RESOLVED"
    assert SiteFact(field="x", source="AI", outcome="UNKNOWN").status == "UNKNOWN"


def test_not_present_is_a_valid_rule_input_and_unknown_is_not():
    a = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="NOT_PRESENT", value=False)
    b = SiteFact(field="bicycle_lane_present", registry_id="bicycle_lane_present", source="AI", outcome="UNKNOWN", reason_code="occluded")
    ri = rule_inputs([a, b])
    assert set(ri) == {"shoulder_present"} and ri["shoulder_present"].value is False


def test_source_failed_is_a_reason_code():
    f = SiteFact(field="x", source="OSM", outcome="UNKNOWN", reason_code="source_failed")
    assert f.reason_code == "source_failed"


# ---------------------------------------------------------------- fusion
def test_not_present_from_a_source_agrees_with_an_ai_false():
    r = fu.compare("shoulder_present", False, [fu.SourceReading.not_present("OSM")])
    assert r.agreement == fu.AGREE and r.candidates[1].outcome == oc.NOT_PRESENT


def test_not_present_disagrees_with_an_ai_true():
    r = fu.compare("shoulder_present", True, [fu.SourceReading.not_present("OSM")])
    assert r.agreement == fu.DISAGREE


def test_a_source_that_could_not_decide_is_not_a_not_present():
    r = fu.compare("shoulder_present", False, [fu.SourceReading.unknown("OSM")])
    assert r.agreement == fu.UNDECIDABLE and r.candidates[1].outcome == oc.UNKNOWN and r.candidates[1].value is None


def test_found_readings_and_old_pairs_still_work():
    assert fu.compare("lanes_per_direction", 2, [fu.SourceReading.found("OSM", 2)]).agreement == fu.AGREE
    assert fu.compare("lanes_per_direction", 2, [("OSM", 3)]).agreement == fu.DISAGREE
    assert fu.compare("lanes_per_direction", 2, []).agreement == fu.SINGLE_SOURCE


def test_an_unknown_ai_reading_is_undecidable_and_has_unknown_outcome():
    r = fu.compare("shoulder_present", None, [fu.SourceReading.not_present("OSM")])
    assert r.agreement == fu.UNDECIDABLE and r.candidates[0].outcome == oc.UNKNOWN


def test_the_confidence_class_of_a_not_present_source_is_medium_when_it_agrees():
    r = fu.compare("shoulder_present", False, [fu.SourceReading.not_present("OSM")])
    assert r.candidates[1].confidence_class == fu.MEDIUM
