"""Add-on rules (S4b stage D; D-90): Sect. 6G.10 sidewalk closed and Sect. 6I.02 detours are optional per zone.

They never make a sign required or placed on their own. The sidewalk rules apply only when the SME switches on the
S11 add-on toggle ADDON:sidewalk_closed, which is the registry fact addon_sidewalk_closed; the detour rules only when
vehicle_detour_required or pedestrian_detour_required is true. An unset fact evaluates to None, so nothing fires.
"""
import pytest
from tcp_planner.rules.rule_pack_effective import effective_rules
from tcp_planner.rules.rule_pack_models import expr_fields
from tcp_planner.rules.rule_pack_store import JsonRulePackStore

TOPICS = ("sidewalk_closure", "detour")
TOGGLE = "addon_sidewalk_closed"
SIDEWALK_GATED = {"R-6G10-P01-SIDEWALK-CLOSED-SIGNS", "R-6G10-P02-R9-9", "R-6G10-P03-R9-10", "R-6G10-P04-R9-11",
                  "R-6G10-P05-R9-11A", "R-6G10-P06-DETECTABLE-BARRICADE"}
ADDON_SIGNS = {"R9-9", "R9-10", "R9-11", "R9-11a", "M4-9", "M4-9a", "M4-9b", "M4-9c", "M4-8a"}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def _applies(pack, facts):
    """{rule_id: applies} over every add-on rule, for every TA (the rules are shared, ta_id None)."""
    out = {}
    for ta in (None, "TA-1", "TA-6", "TA-10", "TA-33"):
        for topic in TOPICS:
            for e in effective_rules(pack, topic, ta, facts)["applied"]: out[e["rule_id"]] = e["applies"]
    return out


def test_every_addon_rule_has_a_condition(pack):
    rules = [r for r in pack.records("rule") if r.topic in TOPICS]
    assert len(rules) == 16 and all(r.condition is not None and r.ta_id is None for r in rules)
    gates = {r.id: set(expr_fields(r.condition)) for r in rules}
    assert {rid for rid, f in gates.items() if f == {TOGGLE}} == SIDEWALK_GATED
    assert set().union(*gates.values()) == {TOGGLE, "vehicle_detour_required", "pedestrian_detour_required"}


@pytest.mark.parametrize("facts", [{}, {TOGGLE: False}, {"posted_speed_mph": 25, "lane_closure": True},
                                   {TOGGLE: False, "vehicle_detour_required": False, "pedestrian_detour_required": False}])
def test_toggle_off_or_unset_fires_nothing(pack, facts):
    got = _applies(pack, facts)
    assert len(got) == 16 and not [rid for rid, a in got.items() if a is True]
    if TOGGLE not in facts:
        assert all(got[rid] is None for rid in SIDEWALK_GATED)      # unset stays None, never False-then-default


def test_toggle_on_applies_only_the_sidewalk_rules(pack):
    got = _applies(pack, {TOGGLE: True})
    assert {rid for rid, a in got.items() if a is True} == SIDEWALK_GATED


def test_detour_rules_apply_only_with_their_own_fact(pack):
    veh = _applies(pack, {"vehicle_detour_required": True})
    assert {rid for rid, a in veh.items() if a is True} == {"R-6I02-P01-DETOUR-MARKED", "R-6I02-P06-M4-9", "R-6I02-P07-M4-9-STREET-NAME",
                                                             "R-6I02-P08-M4-8A", "R-6I02-P09-M4-8A-NUMBERED"}
    ped = _applies(pack, {"pedestrian_detour_required": True})
    assert {rid for rid, a in ped.items() if a is True} == {"R-6G10-P01-PEDESTRIAN-DETOUR-SIGNS", "R-6I02-P10-M4-9A", "R-6I02-P11-M4-9A-ARROW",
                                                             "R-6I02-P12-M4-9A-ARROW-PLAQUE", "R-6I02-P13-M4-9B-M4-9C"}


def test_no_addon_sign_is_required_or_placed_by_a_ta(pack):
    """Add-on signs have size rows but no device rows and no ta_device_use rows (follow-up before S8)."""
    devices = {d.code for d in pack.records("device")}
    assert not ADDON_SIGNS & devices
    used = {pack.get(u.device_id).code for u in pack.records("ta_device_use")}
    assert not ADDON_SIGNS & used
