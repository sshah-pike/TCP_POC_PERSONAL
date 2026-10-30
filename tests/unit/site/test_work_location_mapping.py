"""work_location mapping (S6 commit 1, owner decision 5): one test per cell of the table shown at STOP 1."""
import itertools

import pytest

from tcp_planner.ai.call1 import (BEYOND_SHOULDER, IN_LANE, MARKS_AGREE, MARKS_DISAGREE, MARKS_MISSING, ON_SHOULDER, Observation,
                                  map_work_location)
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model.site_config import call1_setting

FLOOR = call1_setting("work_location_min_confidence")
HI, LO = 0.9, 0.84

# (wire value, marks) -> (registry value or None, flags, reason_code, question)
TABLE = {
    ("ROADWAY", MARKS_AGREE): (IN_LANE, (), None, False),
    ("ROADWAY", MARKS_MISSING): (IN_LANE, ("AI_ONLY_UNCONFIRMED",), None, False),
    ("ROADWAY", MARKS_DISAGREE): (None, (), "source_disagreement", True),
    ("SHOULDER", MARKS_AGREE): (ON_SHOULDER, (), None, False),
    ("SHOULDER", MARKS_MISSING): (ON_SHOULDER, ("AI_ONLY_UNCONFIRMED",), None, False),
    ("SHOULDER", MARKS_DISAGREE): (None, (), "source_disagreement", True),
    ("BEYOND_SHOULDER", MARKS_AGREE): (BEYOND_SHOULDER, (), None, False),
    ("BEYOND_SHOULDER", MARKS_MISSING): (BEYOND_SHOULDER, (), None, False),
    ("BEYOND_SHOULDER", MARKS_DISAGREE): (BEYOND_SHOULDER, (), None, False),
    ("SIDEWALK", MARKS_AGREE): (None, (), "no_registry_value", False),
    ("SIDEWALK", MARKS_MISSING): (None, (), "no_registry_value", False),
    ("SIDEWALK", MARKS_DISAGREE): (None, (), "no_registry_value", False),
}


def _obs(value, conf=HI, status="RESOLVED"):
    return Observation(field="work_location", value=None if status == "UNKNOWN" else value, status=status, confidence=conf,
                       evidence="e", reason_code="not_visible" if status == "UNKNOWN" else None)


@pytest.mark.parametrize("cell", list(TABLE), ids=[f"{v}-{m}" for v, m in TABLE])
def test_cell_at_or_above_the_floor(cell):
    value, flags, reason, question = TABLE[cell]
    fact, q = map_work_location(_obs(cell[0]), cell[1], FLOOR)
    assert fact.value == value and fact.status == ("RESOLVED" if value else "UNKNOWN")
    assert set(flags) <= set(fact.flags) and ("AI_ONLY_UNCONFIRMED" in fact.flags) == ("AI_ONLY_UNCONFIRMED" in flags)
    assert fact.reason_code == reason and (q is not None) == question
    assert fact.registry_id == "work_location" and fact.source == "AI"
    if value is None: assert fact.candidates and fact.candidates[0].value == cell[0]   # the observation stays visible
    if q: assert q.kind == "WORK_LOCATION_CONFLICT" and set(q.options) == {IN_LANE, ON_SHOULDER, BEYOND_SHOULDER}


@pytest.mark.parametrize("value,marks", list(itertools.product(("ROADWAY", "SHOULDER", "BEYOND_SHOULDER", "SIDEWALK"),
                                                               (MARKS_AGREE, MARKS_MISSING, MARKS_DISAGREE))))
def test_cell_below_the_floor_is_unknown_without_question(value, marks):
    fact, q = map_work_location(_obs(value, LO), marks, FLOOR)
    assert (fact.value, fact.status, fact.reason_code, q) == (None, "UNKNOWN", "low_confidence", None)
    assert fact.candidates[0].value == value


def test_confidence_exactly_at_the_floor_passes():
    assert map_work_location(_obs("ROADWAY", FLOOR), MARKS_AGREE, FLOOR)[0].value == IN_LANE


@pytest.mark.parametrize("marks", [MARKS_AGREE, MARKS_MISSING, MARKS_DISAGREE])
def test_unknown_observation_stays_unknown(marks):
    fact, q = map_work_location(_obs("UNKNOWN", HI, "UNKNOWN"), marks, FLOOR)
    assert (fact.value, fact.status, fact.reason_code, q) == (None, "UNKNOWN", "not_visible", None)


def test_floor_is_the_owner_value_from_config():
    assert FLOOR == 0.85


def test_mapped_values_are_registry_values():
    enum = next(r for r in JsonRulePackStore().load().records("registry_field") if r.id == "work_location").enum_values
    assert {IN_LANE, ON_SHOULDER, BEYOND_SHOULDER} <= set(enum)
