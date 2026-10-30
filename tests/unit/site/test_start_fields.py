"""Mandatory start fields in site understanding (S6 commit 4, D-59): read-only, never calculated, never overwritten."""
import copy, inspect, json, os

import pytest

from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import lengths as L, precalc as P, start_fields as S
from tcp_planner.site_model.facts import Interval, MeasuredLength, SiteFact, rule_inputs

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ZONE = {"project_id": "p1", "zone": {"zone_id": "z1", "ta_hypothesis": "AUTO"},
        "start_fields": {"road_type": "URBAN_LOW_SPEED", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def lane_fact(value, lo=None, hi=None):
    iv = Interval(lo=value if lo is None else lo, hi=value if hi is None else hi, unit="ft")
    m = MeasuredLength(name="lane_width", value_ft=value, interval_ft=iv, method="AI_MARKS", mpp=0.3, pixel_error_px=3.0, inputs=("x",), calculation="c")
    return SiteFact(field="lane_width_ft", registry_id="lane_width_ft", value=value, unit="ft", source="AI_MARKS", status="RESOLVED", interval=iv, measured=m)


def test_the_four_facts_equal_the_input_and_carry_source_ui():
    facts = S.start_facts(ZONE)
    assert [f.field for f in facts] == list(S.START_FIELDS)
    assert {f.field: f.value for f in facts} == ZONE["start_fields"]
    assert all(f.source == "UI" and f.status == "RESOLVED" and f.registry_id == f.field for f in facts)
    assert next(f for f in facts if f.field == "posted_speed_mph").unit == "mph"


def test_the_zone_input_is_byte_identical_before_and_after(pack):
    before = json.dumps(ZONE, sort_keys=True).encode()
    facts = S.start_facts(ZONE)
    dec = P.remaining_width_decision(pack, P.remaining_lane_width(pack, lane_fact(12.0), P.encroachment_depth(5.0, 5.0)[0])[0])
    S.lane_closure_conflict(dec, facts)
    assert json.dumps(ZONE, sort_keys=True).encode() == before


def test_a_start_fact_cannot_be_changed_after_it_is_made():
    f = S.start_facts(ZONE)[3]
    with pytest.raises(Exception): f.value = True


def test_missing_value_is_unknown_and_forces_review():
    z = copy.deepcopy(ZONE); z["start_fields"]["road_type"] = None
    f = S.start_facts(z)[0]
    assert (f.status, f.reason_code, f.source) == ("UNKNOWN", "missing", "UI") and "SOURCE_REVIEW_REQUIRED" in f.flags


def test_a_per_point_override_is_what_the_module_reads():
    z = copy.deepcopy(ZONE); z["start_fields"]["posted_speed_mph"] = 45          # the zone input already holds the merged override
    assert next(f for f in S.start_facts(z) if f.field == "posted_speed_mph").value == 45


def test_start_facts_are_rule_inputs_with_the_entered_values():
    ri = rule_inputs(S.start_facts(ZONE))
    assert {k: v.value for k, v in ri.items()} == ZONE["start_fields"]


# ---------------------------------------------------------------- the one defined contradiction (Q13 A)
def _dec(pack, value, ctx=None):
    depth = P.encroachment_depth(0.0, 0.0)[0]
    return P.remaining_width_decision(pack, P.remaining_lane_width(pack, lane_fact(value), depth, ctx)[0], ctx)


def test_closure_needed_but_sme_said_no_raises_a_question_and_changes_nothing(pack):
    facts = S.start_facts(ZONE)
    dec = _dec(pack, 8.0)
    assert dec.result == "LANE_CLOSURE_NEEDED"
    q = S.lane_closure_conflict(dec, facts)
    assert q.kind == "START_FIELD_CONFLICT" and q.reveals == ("lane_closure",) and q.default_if_skipped == "KEEP_AS_ENTERED"
    assert next(f for f in facts if f.field == "lane_closure").value is False        # unchanged
    assert S.start_facts(ZONE)[3].value is False


@pytest.mark.parametrize("value,closure", [(14.0, False), (10.0, False), (8.0, True)])
def test_only_a_needed_closure_with_no_entered_closure_conflicts(pack, value, closure):
    assert (S.lane_closure_conflict(_dec(pack, value), S.start_facts(ZONE)) is not None) is closure


def test_no_conflict_when_the_sme_already_entered_a_closure(pack):
    z = copy.deepcopy(ZONE); z["start_fields"]["lane_closure"] = True
    assert S.lane_closure_conflict(_dec(pack, 8.0), S.start_facts(z)) is None


def test_no_conflict_when_the_result_is_unknown(pack):
    unknown = P.remaining_width_decision(pack, P._unknown("remaining_lane_width_ft", "no_source", unit="ft"))
    assert unknown.result == "UNKNOWN" and S.lane_closure_conflict(unknown, S.start_facts(ZONE)) is None


# ---------------------------------------------------------------- nothing in site understanding writes a start field
def test_no_site_model_module_assigns_to_a_start_field():
    import ast
    names = set(S.START_FIELDS)
    for rel in ("lengths.py", "measure.py", "precalc.py", "start_fields.py", "facts.py"):
        tree = ast.parse(open(os.path.join(ROOT, "src", "tcp_planner", "site_model", rel), encoding="utf-8").read())
        for n in ast.walk(tree):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
            for t in targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in names:
                    pytest.fail(f"{rel} assigns to start field {t.slice.value!r}")


def test_start_fields_come_only_from_the_zone_input_and_never_from_computed_facts():
    src = inspect.getsource(S)
    assert "zone_input[\"start_fields\"]" in src and "AI" not in src.replace("RAI", "")
