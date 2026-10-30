"""Effective-rules view (S4 acceptance: precedence). Owner decision: the precedence test covers federal rules only;
at 25 mph urban the buffer comes from Table 6B-2 (155 ft, Option), never from a client drawing."""
import pytest
from tcp_planner.rules.rule_pack_effective import LAYER_ORDER, advance_sign_spacing, buffer_length, effective_rules
from tcp_planner.rules.rule_pack_store import JsonRulePackStore


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def test_layer_order():
    assert [l.value for l in LAYER_ORDER] == ["FEDERAL", "JURISDICTION", "CLIENT", "DEVIATION"]


@pytest.mark.parametrize("ta", [None, "TA-6", "TA-10", "TA-33"])
def test_buffer_at_25_mph_urban_is_table_6b2_option(pack, ta):
    b = buffer_length(pack, 25, ta)
    assert (b["status"], b["value"], b["unit"], b["layer"], b["strength"]) == ("SOURCED", 155, "ft", "FEDERAL", "OPTION")
    assert b["record_id"] == "T-6B2-25" and b["rule"] == "R-6B06-BUFFER-OPTION"
    assert b["trace"]["source_refs"][0]["page"] == "775" and b["trace"]["source_refs"][0]["table"] == "6B-2"


@pytest.mark.parametrize("speed", [27, 42, 80, 15])
def test_buffer_for_an_unprinted_speed_is_never_interpolated(pack, speed):
    b = buffer_length(pack, speed)
    assert b["status"] == "SOURCE_REVIEW_REQUIRED" and b["value"] is None


@pytest.mark.parametrize("road_type,dim,ft", [("URBAN_LOW_SPEED", "A", 100), ("URBAN_HIGH_SPEED", "B", 350),
                                              ("RURAL", "C", 500), ("EXPRESSWAY_FREEWAY", "C", 2640)])
def test_advance_sign_spacing_from_table_6b1(pack, road_type, dim, ft):
    s = advance_sign_spacing(pack, road_type, dim)
    assert (s["status"], s["value"], s["strength"]) == ("SOURCED", ft, "GUIDANCE")
    assert s["trace"]["source_refs"][0]["page"] == "773"


def test_unknown_road_type_has_no_spacing(pack):
    assert advance_sign_spacing(pack, "SUBURBAN", "A")["status"] == "UNKNOWN"


def test_only_federal_rules_are_effective(pack):
    topics = {r.topic for r in pack.records("rule")}
    for ta in (None, "TA-1", "TA-6", "TA-10", "TA-33"):
        for t in topics:
            v = effective_rules(pack, t, ta)
            assert {e["layer"] for e in v["applied"]} <= {"FEDERAL"} and v["overridden"] == []


def test_cited_only_records_are_never_applied(pack):
    v = effective_rules(pack, "advance_sign_spacing")
    assert [e["rule_id"] for e in v["applied"]] == ["R-6B04-TABLE-6B1-GUIDANCE"]
    assert {c["rule_id"] for c in v["cited_only"]} == {"R-6B04-P03-FREEWAY-HALF-MILE", "R-6B04-P04-URBAN-NEAREST-SIGN",
                                                      "R-6B04-P05-SINGLE-SIGN-100FT", "R-6B04-P06-RURAL-FIRST-SIGN",
                                                      "R-6B04-P06-RURAL-AREA-1500FT"}
    cited = {r.id for r in pack.records("rule") if r.role == "CITED_ONLY"}
    for t in {r.topic for r in pack.records("rule")}:
        for ta in (None, "TA-1", "TA-6", "TA-10", "TA-33"):
            assert not {e["rule_id"] for e in effective_rules(pack, t, ta)["applied"]} & cited


def test_ta_note_replaces_the_shared_section_it_restates(pack):
    """TA-6 note 1 and note 4 restate Sect. 6N.07 paras 02 and 04: for TA-6 only the notes apply, never both."""
    v = effective_rules(pack, "remaining_lane_width", "TA-6", {"remaining_lane_width_ft": 9.5})
    applied = {e["rule_id"] for e in v["applied"]}
    assert {"R-TA6-N1", "R-TA6-N4"} <= applied and not applied & {"R-6N07-REMAINING-WIDTH", "R-6N07-NINE-FT-OPTION"}
    assert {s["rule_id"]: s["by"] for s in v["superseded"]} == {"R-6N07-REMAINING-WIDTH": ["R-TA6-N1"],
                                                                "R-6N07-NINE-FT-OPTION": ["R-TA6-N4"]}
    other = {e["rule_id"] for e in effective_rules(pack, "remaining_lane_width", "TA-10")["applied"]}
    assert {"R-6N07-REMAINING-WIDTH", "R-6N07-NINE-FT-OPTION"} <= other and not other & {"R-TA6-N1", "R-TA6-N4"}


def test_conditions_are_evaluated_on_the_facts(pack):
    v = effective_rules(pack, "remaining_lane_width", "TA-6", {"remaining_lane_width_ft": 9.5})
    got = {e["rule_id"]: e["applies"] for e in v["applied"]}
    assert got["R-TA6-N1"] is True          # 9.5 < 10: lane closure needed
    assert got["R-TA6-N4"] is None          # the 9 ft option needs duration, volume, low speed, heavy vehicles
    assert all(e["trace"]["pack_hash"] == pack.hash for e in v["applied"])
