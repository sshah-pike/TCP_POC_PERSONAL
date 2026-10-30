"""Question and answer records (S6 addendum 2026-10-31): no log store in S6 or S7, but every stored answer keeps kind, field,
zone id, project id, OSM way id and the answer time."""
import json

import pytest
from pydantic import ValidationError

from tcp_planner.site_model import bearing_check as BC
from tcp_planner.site_model import edge_rule as ER
from tcp_planner.site_model import osm_rules as OR
from tcp_planner.site_model.facts import AnswerRecord, Mark, Question, answer_record, question_scope
from tcp_planner.data_sources.osm import OsmWay

WHEN = "2026-10-31T14:05:00+00:00"


def q(**kw):
    base = dict(question_id="abc", kind="WHICH_ROAD", reason="r", field="road", osm_way_id=77, context={"k": 1})
    base.update(kw)
    return Question(**base)


def test_an_answer_record_keeps_all_six_keys():
    r = answer_record(q(), "way 77", "sme-1", WHEN, zone_id="z1", project_id="p1")
    d = json.loads(r.model_dump_json())
    assert {k: d[k] for k in ("kind", "field", "zone_id", "project_id", "osm_way_id", "answered_at")} == {
        "kind": "WHICH_ROAD", "field": "road", "zone_id": "z1", "project_id": "p1", "osm_way_id": 77, "answered_at": WHEN}
    assert d["question_id"] == "abc" and d["answer"] == "way 77" and d["answered_by"] == "sme-1" and d["schema_version"]


def test_scope_fills_zone_and_project_on_a_question():
    s = question_scope(q(), "z9", "p9")
    assert (s.zone_id, s.project_id, s.osm_way_id, s.field) == ("z9", "p9", 77, "road")
    r = answer_record(s, "x", "sme", WHEN)
    assert r.zone_id == "z9" and r.project_id == "p9"


def test_the_field_falls_back_to_a_single_reveals_entry_and_is_never_empty():
    assert answer_record(q(field=None, reveals=("lane_width_ft",)), "11", "sme", WHEN).field == "lane_width_ft"
    with pytest.raises(ValueError): answer_record(q(field=None, reveals=()), "x", "sme", WHEN)
    with pytest.raises(ValueError): answer_record(q(field=None, reveals=("a", "b")), "x", "sme", WHEN)


@pytest.mark.parametrize("when", ["", "yesterday", "2026-10-31T14:05:00", "2026-10-31"])
def test_an_answer_needs_a_timestamp_with_a_time_zone(when):
    with pytest.raises(ValidationError): answer_record(q(), "a", "sme", when)


def test_an_answer_needs_an_actor_and_text():
    with pytest.raises(ValidationError): answer_record(q(), "", "sme", WHEN)
    with pytest.raises(ValidationError): answer_record(q(), "a", " ", WHEN)


def test_a_record_cannot_carry_an_unknown_kind_or_extra_key():
    with pytest.raises(ValidationError): AnswerRecord(question_id="a", kind="NOPE", field="f", answer="x", answered_by="s", answered_at=WHEN)
    with pytest.raises(ValidationError): AnswerRecord(question_id="a", kind="WHICH_ROAD", field="f", answer="x", answered_by="s", answered_at=WHEN, extra=1)


def test_every_question_the_s6_code_raises_can_be_stored_as_an_answer():
    """Each producer names its field (or one reveals entry) and, where an OSM way is involved, its way id."""
    way = OsmWay(5, {"highway": "secondary", "lanes": "3"}, ((-100.0, 3.0), (100.0, 3.0)))
    lanes_q = OR.osm_read([way]).questions[0]
    assert answer_record(lanes_q, "2", "sme", WHEN).osm_way_id == 5
    mark = lambda f, pts: Mark(feature=f, status="RESOLVED", points=pts)
    marks = (mark("road_edge_left", ((100, 300), (1200, 300))), mark("road_edge_right", ((100, 360), (1200, 360))))
    b = BC.check_bearing(marks, [way])                      # marks run east-west, way too: agree; force a mismatch with a north-south way
    ns = OsmWay(6, {"highway": "secondary"}, ((3.0, -100.0), (3.0, 100.0)))
    mm = BC.check_bearing(marks, [ns]).questions[0]
    r = answer_record(mm, "OSM_IS_RIGHT", "sme", WHEN)
    assert (r.kind, r.field, r.osm_way_id) == ("BEARING_MISMATCH", "road", 6)
    near = ER.check_edge(marks + (mark("work_point", ((640, 305),)),), 0.5, True).question
    assert answer_record(near, "IN_LANE", "sme", WHEN).field == "work_location"


def test_the_older_questions_name_their_field_through_reveals():
    from tcp_planner.ai import call1
    from tcp_planner.site_model.start_fields import lane_closure_conflict
    wl = call1.map_work_location(call1.Observation(field="work_location", value="ROADWAY", status="RESOLVED", confidence=0.95),
                                 call1.MARKS_DISAGREE, 0.85)[1]
    assert answer_record(wl, "IN_LANE", "sme", WHEN).field == "work_location"
