"""STOP 5 review changes R2, R3, R4 (owner, 2026-10-31)."""
import json

import pytest

from tcp_planner.ai import call1
from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO
from tcp_planner.data_sources.osm import OsmWay
from tcp_planner.site_model import edge_rule as ER
from tcp_planner.site_model import fusion_apply as FA
from tcp_planner.site_model import fusion_v2 as FV
from tcp_planner.site_model import osm_rules as OR
from tcp_planner.site_model.facts import Mark, SiteFact, rule_inputs
from tcp_planner.site_model.site_config import load_site_config, setting
from tests.unit.site.test_osm import EW, way


def wire(field, value, conf=0.95):
    row = call1.BY_NAME[field]
    return {"field": field, "value": value, "unit": row.kind, "status": "RESOLVED", "confidence": conf, "evidence": "seen"}


def facts_of(*items):
    r = call1.parse_call1(json.dumps({"facts": list(items), "marks": []}))
    return {f.field: f for f in call1.to_site_facts(r, call1.MARKS_AGREE)[0]}


# ---------------------------------------------------------------- R2: AI-only registry facts
@pytest.mark.parametrize("field", ["median_work", "bicycle_lane_present", "approaching_lanes_one"])
def test_an_ai_only_value_that_reaches_a_rule_input_is_review_required_naming_the_fact(field):
    f = facts_of(wire(field, "true"))[field]
    assert f.outcome == "FOUND" and "AI_ONLY_UNCONFIRMED" in f.flags and f.registry_id == field
    decision, reasons = rule_inputs([f]).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED and [r["fact"] for r in reasons] == [field] and field in reasons[0]["reason"]


def test_not_present_is_flagged_too_and_unknown_is_not_a_rule_input():
    f = facts_of(wire("bicycle_lane_present", "false"))["bicycle_lane_present"]
    assert f.outcome == "NOT_PRESENT" and "AI_ONLY_UNCONFIRMED" in f.flags
    u = facts_of({**wire("median_work", "UNKNOWN"), "status": "UNKNOWN", "evidence": "occluded"})["median_work"]
    assert u.outcome == "UNKNOWN" and "AI_ONLY_UNCONFIRMED" not in u.flags and rule_inputs([u]) == {}


def test_other_common_facts_are_not_flagged_and_no_new_floor_number_was_added():
    fs = facts_of(wire("parking_present", "true"), wire("sidewalk_present", "true"))
    assert all("AI_ONLY_UNCONFIRMED" not in f.flags for f in (fs["parking_present"], fs["sidewalk_present"]))
    cfg = load_site_config()
    assert cfg["call1"]["ai_only_review_fields"]["value"] == ["median_work", "bicycle_lane_present", "approaching_lanes_one"]
    assert cfg["confidence_floors"]["default"]["common"]["value"] is None and cfg["confidence_floors"]["profiles"] == {}


# ---------------------------------------------------------------- R3: OSM_TAG_ASSUMED
def ai_oneway(value):
    return SiteFact(field="oneway", registry_id="oneway", source="AI", outcome="FOUND", value=value, confidence=0.9, flags=("NEEDS_SECOND_SOURCE",))


def test_a_found_oneway_resting_on_a_missing_osm_tag_carries_osm_tag_assumed_and_is_review_required():
    res = FA.fuse_fields([ai_oneway(False)], OR.osm_read([way(1, {}, EW)]))              # no oneway tag: counted as not one-way
    f = res.facts[0]
    assert f.outcome == "FOUND" and f.value is False and "OSM_TAG_ASSUMED" in f.flags and "NEEDS_SECOND_SOURCE" not in f.flags
    decision, reasons = rule_inputs(list(res.facts)).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED and [r["fact"] for r in reasons] == ["oneway"] and reasons[0]["flag"] == "OSM_TAG_ASSUMED"
    assert "missing OSM oneway tag" in reasons[0]["reason"]


def test_a_stated_oneway_tag_carries_no_flag_and_passes_the_gate():
    res = FA.fuse_fields([ai_oneway(False)], OR.osm_read([way(1, {"oneway": "no"}, EW)]))
    f = res.facts[0]
    assert f.outcome == "FOUND" and "OSM_TAG_ASSUMED" not in f.flags
    assert rule_inputs(list(res.facts)).gate(SUPPORTED_AUTO) == (SUPPORTED_AUTO, [])


def test_the_flag_is_one_of_the_review_flags():
    from tcp_planner.site_model.facts import FLAGS, REVIEW_FLAGS
    assert "OSM_TAG_ASSUMED" in FLAGS and "OSM_TAG_ASSUMED" in REVIEW_FLAGS


# ---------------------------------------------------------------- R4: no-road-near distance and the candidate question
MPP = 0.5


def edge_marks(work_y=650, with_edges=True):
    out = []
    if with_edges:
        out += [Mark(feature="road_edge_left", status="RESOLVED", points=((100, 600), (1200, 600))),
                Mark(feature="road_edge_right", status="RESOLVED", points=((100, 700), (1200, 700)))]
    return tuple(out) + (Mark(feature="work_point", status="RESOLVED", points=((640, work_y),)),)


def wl(value="BEYOND_SHOULDER"):
    return SiteFact(field="work_location", registry_id="work_location", source="AI", outcome="FOUND", value=value, confidence=0.95, evidence="grass")


def test_the_no_road_near_distance_is_in_config_and_calibration_pending():
    assert setting("edge_rule", "no_road_near_m", load_site_config()) == (25, ("CALIBRATION_PENDING",))


def test_road_near_uses_the_configured_distance():
    near = way(1, {}, [(-100.0, 20.0), (100.0, 20.0)])
    far = way(2, {}, [(-100.0, 26.0), (100.0, 26.0)])
    assert ER.road_near([near]) is True and ER.road_near([far]) is False and ER.road_near([]) is False
    assert ER.road_near([way(3, {"highway": "service"}, [(-100.0, 5.0), (100.0, 5.0)])]) is True      # a service road is still a road
    cfg = load_site_config(); cfg["edge_rule"]["no_road_near_m"]["value"] = 30
    assert ER.road_near([far], cfg=cfg) is True


def test_with_a_road_within_the_distance_a_beyond_shoulder_answer_is_found():
    # work point 60 m from the nearest edge mark (far clear of the 5 m rule), an OSM road within 25 m
    r = ER.check_edge(edge_marks(work_y=820), MPP, ER.road_near([way(1, {}, [(-100.0, 20.0), (100.0, 20.0)])]))
    assert r.status == ER.CLEAR
    f, q = ER.apply_edge_rule(wl("BEYOND_SHOULDER"), r)
    assert f.outcome == "FOUND" and f.value == "BEYOND_SHOULDER" and q is None
    # road known from OSM, no edge marks at all: the rule does not apply and the answer stays FOUND
    r2 = ER.check_edge(edge_marks(with_edges=False), MPP, True)
    f2, q2 = ER.apply_edge_rule(wl("BEYOND_SHOULDER"), r2)
    assert r2.status == ER.NO_DISTANCE and f2.outcome == "FOUND" and q2 is None


def test_with_no_road_near_there_is_one_question_candidate_pre_filled_and_informational():
    r = ER.check_edge(edge_marks(with_edges=False), MPP, ER.road_near([]))
    assert r.status == ER.NO_ROAD
    f, q = ER.apply_edge_rule(wl("BEYOND_SHOULDER"), r)
    assert f.outcome == "UNKNOWN" and f.reason_code == "no_road_near" and any(c.value == "BEYOND_SHOULDER" for c in f.candidates)
    assert q.kind == "WORK_LOCATION_NEAR_EDGE" and q.candidate is True and q.suggested == "BEYOND_SHOULDER" and q.field == "work_location"
    assert q.context["no_road_near_m"] == 25


def test_the_near_edge_question_stays_a_normal_question():
    f, q = ER.apply_edge_rule(wl("IN_LANE"), ER.check_edge(edge_marks(work_y=605), MPP, True))
    assert f.reason_code == "near_edge" and q.candidate is False
