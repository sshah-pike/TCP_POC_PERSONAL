"""Parser for call 1 (S6 commit 1): the 9 real spike responses, corrupted copies, fallbacks to UNKNOWN."""
import copy, glob, json, os

import pytest

from tcp_planner.ai.call1 import FIELDS, MARK_FEATURES, parse_call1, to_site_facts
from tcp_planner.site_model.facts import rule_inputs

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "site", "spike", "raw")
FILES = sorted(glob.glob(os.path.join(RAW, "*_B_r*.response.json")))


def _text(path):
    return next(b["text"] for b in json.load(open(path, encoding="utf-8"))["content"] if b.get("type") == "text")


def _doc(path=FILES[0]):
    return json.loads(_text(path))


def _set(d, name, **kw):
    for f in d["facts"]:
        if f["field"] == name: f.update(kw)
    return d


def test_nine_spike_responses_exist():
    assert len(FILES) == 9


@pytest.mark.parametrize("path", FILES, ids=[os.path.basename(p)[:12] for p in FILES])
def test_real_response_parses_with_all_18_fields_and_valid_marks(path):
    res = parse_call1(_text(path), image_size=(1280, 1280))
    assert set(res.observations) == {r.name for r in FIELDS}
    assert not [n for n in res.notes if "malformed" in n or "unknown or missing" in n], res.notes
    assert all(o.reason_code != "malformed" for o in res.observations.values())
    assert res.marks and all(m.feature in MARK_FEATURES for m in res.marks)
    facts, _ = to_site_facts(res)
    assert len(facts) == 18


def test_case_insensitive_enums_and_booleans():
    d = _doc()
    _set(d, "oneway", value="TRUE", status="resolved", confidence=0.7)
    _set(d, "work_side", value="w", status="Resolved", confidence=0.7)
    _set(d, "sidewalk_side", value="both", status="RESOLVED", confidence=0.7)
    o = parse_call1(d).observations
    assert o["oneway"].value is True and o["work_side"].value == "W" and o["sidewalk_side"].value == "BOTH"


def test_missing_fact_becomes_unknown():
    d = _doc(); d["facts"] = [f for f in d["facts"] if f["field"] != "oneway"]
    o = parse_call1(d).observations["oneway"]
    assert (o.status, o.reason_code, o.value) == ("UNKNOWN", "missing", None)


@pytest.mark.parametrize("patch", [{"value": "maybe"}, {"confidence": "high"}, {"confidence": 1.5}, {"confidence": True},
                                   {"status": "PROBABLY"}, {"extra": 1}, {"value": 3}])
def test_malformed_fact_becomes_unknown(patch):
    d = _set(_doc(), "oneway", value="true", status="RESOLVED", confidence=0.7)
    _set(d, "oneway", **patch)
    o = parse_call1(d).observations["oneway"]
    assert (o.status, o.reason_code, o.value) == ("UNKNOWN", "malformed", None)


def test_count_must_be_a_whole_non_negative_number():
    for v, ok in (("2", 2), ("1.0", 1), ("1.5", None), ("-1", None), ("two", None)):
        d = _set(_doc(), "lanes_per_direction", value=v, status="RESOLVED", confidence=0.7)
        o = parse_call1(d).observations["lanes_per_direction"]
        assert (o.value if o.status == "RESOLVED" else None) == ok, v


def test_conflict_status_becomes_unknown_with_flag():
    o = parse_call1(_set(_doc(), "divided_highway", status="CONFLICT")).observations["divided_highway"]
    assert o.status == "UNKNOWN" and o.reason_code == "ai_conflict" and "AI_CONFLICT" in o.flags


def test_duplicate_fact_becomes_unknown():
    d = _doc(); d["facts"].append(copy.deepcopy(next(f for f in d["facts"] if f["field"] == "oneway")))
    assert parse_call1(d).observations["oneway"].reason_code == "duplicate"


def test_unknown_field_is_dropped_and_noted():
    d = _doc(); d["facts"].append({"field": "lane_width_ft", "value": "12", "unit": "text", "status": "RESOLVED",
                                   "confidence": 0.9, "evidence": "x"})
    res = parse_call1(d)
    assert "lane_width_ft" not in res.observations and any("lane_width_ft" in n for n in res.notes)


def test_unknown_evidence_code_gives_reason_code():
    d = _set(_doc(), "bus_stop_present", value="UNKNOWN", status="UNKNOWN", evidence="occluded")
    assert parse_call1(d).observations["bus_stop_present"].reason_code == "occluded"


def test_long_evidence_is_kept_whole_and_flagged():
    long = " ".join(["word"] * 40)
    res = parse_call1(_set(_doc(), "oneway", value="false", status="RESOLVED", confidence=0.7, evidence=long))
    o = res.observations["oneway"]
    assert o.evidence == long and "EVIDENCE_OVER_15_WORDS" in o.flags and any("oneway" in n for n in res.notes)


@pytest.mark.parametrize("bad", ["not json", "[]", '{"facts": 1, "marks": []}', '{"facts": []}', ""])
def test_unusable_response_gives_18_unknown(bad):
    res = parse_call1(bad)
    assert len(res.observations) == 18
    assert all(o.status == "UNKNOWN" and o.reason_code == "malformed" for o in res.observations.values())


def test_marks_valid_malformed_and_outside_the_image():
    d = _doc()
    d["marks"] = [
        {"feature": "LANE_LINE", "points": "10,20;30,40", "status": "resolved", "evidence": "a"},
        {"feature": "curb", "points": "10,20;x", "status": "RESOLVED", "evidence": "b"},
        {"feature": "work_point", "points": "2000,10", "status": "RESOLVED", "evidence": "c"},
        {"feature": "curb", "points": "", "status": "UNKNOWN", "evidence": "not_visible"},
        {"feature": "banana", "points": "1,1", "status": "RESOLVED", "evidence": "d"},
    ]
    res = parse_call1(d, image_size=(1280, 1280))
    assert [(m.feature, m.status, m.reason_code) for m in res.marks] == [
        ("lane_line", "RESOLVED", None), ("curb", "UNKNOWN", "malformed"), ("work_point", "UNKNOWN", "malformed"),
        ("curb", "UNKNOWN", "not_stated")]
    assert res.marks[0].points == ((10.0, 20.0), (30.0, 40.0)) and any("marks[4]" in n for n in res.notes)


def test_safety_critical_resolved_facts_wait_for_a_second_source():
    facts, _ = to_site_facts(parse_call1(_text(FILES[0])))
    crit = {"lanes_per_direction", "divided_highway", "shoulder_present", "oneway"}
    for f in facts:
        assert ("NEEDS_SECOND_SOURCE" in f.flags) == (f.field in crit and f.status == "RESOLVED"), f.field
    assert not (crit & {f.field for f in rule_inputs(facts).values()})


def test_ai_never_supplies_a_length_field():
    assert not [r for r in FIELDS if r.unit in ("ft", "in", "m") or r.name.endswith(("_ft", "_in", "_m"))]
