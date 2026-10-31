"""Step 14: every calibration value of the S6 site-understanding code lives in config, tagged CALIBRATION_PENDING (or sourced).

Three guards: (1) every config entry has a source; (2) every `setting("section", "name")` the code reads exists in config; (3) the S6 modules
contain no numeric literal other than structural ones (0, 1, 2, a half, a straight angle and a full turn, the luminance weights, the earth
radius, the digits of a round()).
"""
import collections
import io
import json
import os
import re
import tokenize

from tcp_planner.config import settings

ROOT = settings.PROJECT_ROOT
CFG = json.load(open(os.path.join(ROOT, "config", "site_understanding.json"), encoding="utf-8"))
SOURCES = json.load(open(os.path.join(ROOT, "config", "data_sources.json"), encoding="utf-8"))
MODULES = ["site_model/bearing_check.py", "site_model/edge_rule.py", "site_model/osm_rules.py", "site_model/fusion_apply.py", "site_model/consistency.py",
           "site_model/code_checks.py", "site_model/understanding.py", "site_model/site_exceptions.py", "site_model/fusion_v2.py", "site_model/outcomes.py",
           "data_sources/osm.py", "imagery/snap.py"]
STRUCTURAL = {"0", "1", "2", "0.0", "1.0", "2.0", "0.5", "180", "180.0", "360", "0.299", "0.587", "0.114", "6371008.8"}


def entries(node, path=()):
    """(path, entry) for every config entry: a dict that has a 'value' key."""
    if isinstance(node, dict):
        if "value" in node: yield path, node
        else:
            for k, v in node.items(): yield from entries(v, path + (k,))


def test_every_config_entry_has_a_source_and_a_pending_one_says_so():
    seen = 0
    for path, e in entries(CFG):
        seen += 1
        assert isinstance(e.get("source"), str) and e["source"].strip(), "/".join(path)
        if e["source"] == "CALIBRATION_PENDING": assert e.get("note"), "/".join(path)
    assert seen > 60


def test_every_value_the_s6_checks_use_is_calibration_pending_unless_it_has_a_named_source():
    for section in ("osm", "bearing", "edge_rule", "snapping", "code_checks", "consistency"):
        for path, e in entries({section: CFG[section]}):
            if path[-1] in ("highway_classes",): continue                                         # sourced: OSM wiki Key:highway
            assert e["source"] == "CALIBRATION_PENDING", "/".join(path)


def test_the_calibration_values_the_owner_named_are_all_in_config():
    want = {("edge_rule", "near_edge_m"): 5, ("edge_rule", "no_road_near_m"): 25, ("bearing", "tolerance_deg"): 30, ("bearing", "nearest_margin_m"): 8,
            ("bearing", "which_road_distance_m"): 25, ("osm", "max_way_distance_m"): 25, ("osm", "divided_max_separation_m"): 60,
            ("osm", "divided_parallel_tolerance_deg"): 20, ("osm", "query_radius_m"): 150, ("measurement", "edge_pixel_error_px_cross_section"): 1.0,
            ("measurement", "edge_pixel_error_px_ai_marks"): 3.0, ("code_checks", "max_osm_offset_m"): 10, ("code_checks", "occlusion_share_max"): 0.35}
    for (sec, name), v in want.items():
        assert CFG[sec][name]["value"] == v and CFG[sec][name]["source"] == "CALIBRATION_PENDING", (sec, name)
    assert CFG["confidence_floors"]["default"]["safety_critical"]["source"] == "CALIBRATION_PENDING"
    assert CFG["confidence_floors"]["default"]["common"]["source"] == "CALIBRATION_PENDING" and CFG["confidence_floors"]["profiles"] == {}
    assert SOURCES["sources"]["osm_overpass"]["query_limits"]["max_radius_m"] == 600 and "CALIBRATION_PENDING" in SOURCES["sources"]["osm_overpass"]["query_limits"]["note"]


def test_every_setting_the_code_reads_exists_in_config():
    pat = re.compile(r'(?:setting|measurement_setting)\(\s*"(\w+)"\s*,\s*"(\w+)"')
    pat1 = re.compile(r'measurement_setting\(\s*"(\w+)"')
    pat2 = re.compile(r'confidence_floor\(\s*"(\w+)"')
    missing = []
    for dp, _, names in os.walk(os.path.join(ROOT, "src", "tcp_planner")):
        for n in names:
            if not n.endswith(".py"): continue
            text = open(os.path.join(dp, n), encoding="utf-8").read()
            for sec, name in pat.findall(text):
                if sec in CFG and name not in CFG[sec]: missing.append((n, sec, name))
            for name in pat1.findall(text):
                if name not in CFG["measurement"]: missing.append((n, "measurement", name))
    assert missing == [], missing


def test_the_s6_modules_hold_no_calibration_number():
    strip_round = re.compile(r"round\((?:[^()]|\([^()]*\))*,\s*\d\)")
    bad = {}
    for m in MODULES:
        src = open(os.path.join(ROOT, "src", "tcp_planner", m), encoding="utf-8").read()
        src = strip_round.sub("round(x)", src)
        found = collections.Counter(t.string for t in tokenize.generate_tokens(io.StringIO(src).readline) if t.type == tokenize.NUMBER)
        extra = {k: v for k, v in found.items() if k not in STRUCTURAL}
        if extra: bad[m] = extra
    assert bad == {}, bad


def test_the_generated_list_of_calibration_values_is_current():
    path = os.path.join(ROOT, "docs", "reports", "S6_calibration_values.md")
    text = open(path, encoding="utf-8").read()
    for sec_path, e in entries(CFG):
        if e["source"] == "CALIBRATION_PENDING": assert "/".join(sec_path) in text, "/".join(sec_path)
