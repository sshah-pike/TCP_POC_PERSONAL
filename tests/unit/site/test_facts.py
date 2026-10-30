"""Site fact records (S6 commit 1): invariants, schema_version, and the rule-input gate for CONTEXT_ONLY facts."""
import json

import pytest
from pydantic import ValidationError

from tcp_planner.ai.call1 import FIELDS, Observation, parse_call1, to_site_facts
from tcp_planner.site_model.facts import Interval, Question, SiteFact, rule_inputs, question_id

CONTEXT = [r.name for r in FIELDS if r.registry_id is None]


def _all_resolved_facts():
    """Every table field RESOLVED at high confidence, as the AI would claim it."""
    from tcp_planner.ai.call1 import _norm_value
    obs = {}
    for r in FIELDS:
        v = {"bool": "true", "count": "1", "text": "NONE"}.get(r.kind) or next(x for x in r.values if x != "UNKNOWN")
        obs[r.name] = Observation(field=r.name, value=_norm_value(r, v), status="RESOLVED", confidence=0.95, evidence="e")
    from tcp_planner.ai.call1 import Call1Result
    return to_site_facts(Call1Result(obs, (), ()), work_location_marks="AGREE")[0]


def test_no_rule_input_can_read_a_context_only_fact():
    facts = _all_resolved_facts()
    ctx = {f.field for f in facts if "CONTEXT_ONLY" in f.flags}
    assert ctx == set(CONTEXT) and all(f.status == "RESOLVED" for f in facts if f.field in ctx)   # resolved, still not readable
    ids = rule_inputs(facts)
    assert not (ctx & {f.field for f in ids.values()})
    assert all(f.registry_id for f in ids.values())


def test_a_fact_cannot_be_context_only_and_carry_a_registry_id():
    with pytest.raises(ValidationError):
        SiteFact(field="x", registry_id="oneway", value=True, source="AI", outcome="FOUND", flags=("CONTEXT_ONLY",))


def test_rule_inputs_skips_a_fact_with_no_registry_id_even_without_the_flag():
    f = SiteFact(field="x", value=True, source="AI", outcome="FOUND")
    assert rule_inputs([f]) == {}


def test_rule_inputs_returns_registry_facts_that_are_resolved_and_unblocked():
    ok = SiteFact(field="median_work", registry_id="median_work", value=False, source="AI", outcome="FOUND")
    blocked = SiteFact(field="oneway", registry_id="oneway", value=False, source="AI", outcome="FOUND", flags=("NEEDS_SECOND_SOURCE",))
    unknown = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="UNKNOWN", reason_code="missing")
    assert list(rule_inputs([ok, blocked, unknown])) == ["median_work"]


def test_fact_invariants():
    with pytest.raises(ValidationError): SiteFact(field="x", value=1, source="AI", outcome="UNKNOWN")
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="FOUND")
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="UNKNOWN", reason_code="because")
    with pytest.raises(ValidationError): SiteFact(field="x", source="AI", outcome="UNKNOWN", flags=("MADE_UP",))
    with pytest.raises(ValidationError): Interval(lo=2, hi=1, unit="ft")


def test_every_record_carries_schema_version_and_round_trips_json():
    facts = _all_resolved_facts()
    q = Question(question_id=question_id("FACT_UNKNOWN", "x"), kind="FACT_UNKNOWN", reason="r")
    for rec in [*facts, q]:
        d = json.loads(rec.model_dump_json())
        assert d["schema_version"] == "1" and type(rec).model_validate(d) == rec


def test_unit_is_filled_by_code():
    f = next(f for f in _all_resolved_facts() if f.field == "lanes_per_direction")
    assert f.unit == "count" and f.value == 1


def test_question_id_is_deterministic():
    assert question_id("K", "a") == question_id("K", "a") != question_id("K", "b")


def test_evidence_is_stored_not_parsed_for_numbers():
    import inspect, tcp_planner.ai.call1 as c1, tcp_planner.site_model.facts as ft
    for mod in (c1, ft):
        src = inspect.getsource(mod)
        assert "re.search" not in src and "re.findall" not in src and "import re" not in src
