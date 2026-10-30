"""Per-profile confidence floors (S6 commit 6): a default entry plus optional per-profile entries."""
import copy
import json

import pytest

from tcp_planner.ai import call1
from tcp_planner.site_model.site_config import FLOOR_KINDS, confidence_floor, load_site_config


def wire(field, value, conf, status="RESOLVED"):
    row = call1.BY_NAME[field]
    return {"field": field, "value": value, "unit": row.kind, "status": status, "confidence": conf, "evidence": "seen"}


def parsed(*facts):
    return call1.parse_call1(json.dumps({"facts": list(facts), "marks": []}))


def cfg_with(profiles=None, default=None):
    cfg = load_site_config()
    if default: cfg["confidence_floors"]["default"].update(default)
    cfg["confidence_floors"]["profiles"] = profiles or {}
    return cfg


def test_the_default_entry_and_no_profiles_ship_in_config():
    floors = load_site_config()["confidence_floors"]
    assert set(floors["default"]) == set(FLOOR_KINDS) and floors["profiles"] == {}
    assert floors["default"]["work_location"]["value"] == 0.85
    assert floors["default"]["safety_critical"]["value"] is None and floors["default"]["common"]["value"] is None
    assert floors["default"]["safety_critical"]["source"] == "CALIBRATION_PENDING"


def test_a_profile_without_an_entry_gets_the_default():
    assert confidence_floor("work_location", "gpt-5.6-sol") == (0.85, ())
    assert confidence_floor("common", None) == (None, ("CALIBRATION_PENDING",))


def test_a_profile_entry_wins_over_the_default_for_its_own_kind_only():
    cfg = cfg_with({"gpt-5.6-sol": {"work_location": {"value": 0.9, "source": "owner"}}})
    assert confidence_floor("work_location", "gpt-5.6-sol", cfg) == (0.9, ())
    assert confidence_floor("work_location", "claude-opus-5-5", cfg) == (0.85, ())
    assert confidence_floor("common", "gpt-5.6-sol", cfg) == (None, ("CALIBRATION_PENDING",))      # falls back per kind


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError): confidence_floor("everything")


def test_work_location_uses_the_profile_floor():
    r = parsed(wire("work_location", "BEYOND_SHOULDER", 0.88))
    cfg = cfg_with({"strict": {"work_location": {"value": 0.95, "source": "owner"}}})
    loose, _ = call1.to_site_facts(r, call1.MARKS_AGREE, cfg, profile="other")
    strict, _ = call1.to_site_facts(r, call1.MARKS_AGREE, cfg, profile="strict")
    assert {f.field: f for f in loose}["work_location"].outcome == "FOUND"
    wl = {f.field: f for f in strict}["work_location"]
    assert wl.outcome == "UNKNOWN" and wl.reason_code == "low_confidence"


def test_common_and_safety_critical_floors_turn_low_confidence_readings_unknown():
    r = parsed(wire("parking_present", "true", 0.6), wire("lanes_per_direction", "2", 0.6), wire("sidewalk_present", "false", 0.95))
    cfg = cfg_with({"p": {"common": {"value": 0.7, "source": "owner"}, "safety_critical": {"value": 0.8, "source": "owner"}}})
    by = {f.field: f for f in call1.to_site_facts(r, call1.MARKS_AGREE, cfg, profile="p")[0]}
    assert by["parking_present"].outcome == "UNKNOWN" and by["parking_present"].reason_code == "low_confidence"
    assert by["lanes_per_direction"].outcome == "UNKNOWN" and "NEEDS_SECOND_SOURCE" not in by["lanes_per_direction"].flags
    assert by["sidewalk_present"].outcome == "NOT_PRESENT"


def test_without_a_floor_nothing_changes():
    r = parsed(wire("parking_present", "true", 0.1), wire("lanes_per_direction", "2", 0.1))
    by = {f.field: f for f in call1.to_site_facts(r, call1.MARKS_AGREE, None)[0]}
    assert by["parking_present"].outcome == "FOUND" and by["lanes_per_direction"].outcome == "FOUND"


def test_the_accuracy_report_uses_the_floor_of_each_profile():
    import importlib.util, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "scripts", "s06_accuracy_report.py")
    spec = importlib.util.spec_from_file_location("acc", path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    src = open(path, encoding="utf-8").read()
    assert 'confidence_floor(k, profile, cfg)' in src and "call1_setting(\"work_location_min_confidence\"" not in src
