"""The call 1 field table against the rule pack registry (S6 commit 1). The registry and the pack are read, never edited."""
import pytest

from tcp_planner.ai.call1 import FIELDS, NOT_IN_CALL1, BY_NAME
from tcp_planner.rules.rule_pack_store import JsonRulePackStore


@pytest.fixture(scope="module")
def registry():
    return {r.id: r for r in JsonRulePackStore().load().records("registry_field")}


def test_table_has_the_18_spike_fields_once():
    assert len(FIELDS) == 18 and len(BY_NAME) == 18


def test_every_registry_id_in_the_table_exists_in_the_pack(registry):
    ids = [r.registry_id for r in FIELDS if r.registry_id]
    assert ids and all(i in registry for i in ids)


def test_every_registry_field_with_an_ai_source_is_in_the_table_or_the_named_list(registry):
    ai = {i for i, r in registry.items() if "AI" in getattr(r.source_type, "value", r.source_type)}
    in_table = {r.registry_id for r in FIELDS if r.registry_id}
    assert ai - in_table - set(NOT_IN_CALL1) == set(), "an AI-sourced registry field is neither in call 1 nor named as left out"
    assert set(NOT_IN_CALL1) <= ai and not (set(NOT_IN_CALL1) & in_table)


def test_context_only_rows_are_exactly_the_ten_without_registry_id():
    ctx = {r.name for r in FIELDS if r.registry_id is None}
    assert len(ctx) == 10 and {"work_side", "grade_crossing_present", "sidewalk_present", "obstructions"} <= ctx


def test_units_come_from_the_registry_not_the_model(registry):
    for r in FIELDS:
        if r.registry_id: assert r.unit == registry[r.registry_id].unit, r.name
