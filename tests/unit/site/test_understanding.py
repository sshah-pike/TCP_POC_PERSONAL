"""Site understanding wired beside the old path (S6 step 11): trace, gate, stage switches, determinism, context-only facts. Offline."""
import ast
import hashlib
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

from tcp_planner.ai import call1
from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO
from tcp_planner.config import settings
from tcp_planner.data_sources.osm import OsmWay
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import site_exceptions as SX
from tcp_planner.site_model import understanding as U
from tcp_planner.site_model.facts import SiteFact, answer_record
from tcp_planner.site_model.site_config import load_site_config

W = H = 400
MPP = 0.1                          # 100 px = 10 m
ASPHALT, GROUND = (70, 70, 72), (150, 140, 120)


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def image_bytes():
    a = np.zeros((H, W, 3)); a[:] = GROUND; a[300:380, :] = ASPHALT           # an east-west road 8 m wide, 10 m south of the work point (200,200)
    buf = io.BytesIO(); Image.fromarray(a.astype(np.uint8), "RGB").save(buf, "PNG"); return buf.getvalue()


IMG = image_bytes()
RECORD = {"sent_px": [W, H], "mpp_sent": MPP, "sha256": hashlib.sha256(IMG).hexdigest()}
VALUES = {"work_location": ("BEYOND_SHOULDER", "enum"), "work_side": ("N", "enum"), "lanes_per_direction": ("1", "count"), "oneway": ("false", "bool"),
          "shoulder_present": ("false", "bool"), "divided_highway": ("false", "bool"), "median_work": ("false", "bool"),
          "bicycle_lane_present": ("false", "bool"), "sidewalk_present": ("false", "bool"), "sidewalk_side": ("NONE", "enum"),
          "parking_present": ("false", "bool"), "bus_stop_present": ("false", "bool"), "driveway_present": ("false", "bool"),
          "crosswalk_present": ("false", "bool"), "intersection_in_view": ("false", "bool"), "grade_crossing_present": ("false", "bool"),
          "obstructions": ("NONE", "text"), "approaching_lanes_one": ("true", "bool")}


def response(version=1, overrides=None, road_name="Main St", shadow=0.1, canopy=0.0, marks=None):
    vals = {**VALUES, **(overrides or {})}
    facts = []
    for r in call1.FIELDS:
        v, u = vals[r.name]
        f = {"field": r.name, "value": v, "unit": u, "status": "RESOLVED", "confidence": 0.95, "evidence": "seen"}
        if version == 2: f["reason"] = "visible"
        facts.append(f)
    if version == 2:
        for name, v, u in (("road_name", road_name, "text"), ("other_roads_seen", "NONE", "text"), ("shadow_share", str(shadow), "share"), ("canopy_share", str(canopy), "share")):
            facts.append({"field": name, "value": v, "unit": u, "status": "RESOLVED", "confidence": 0.9, "evidence": "seen", "reason": "visible"})
    mk = marks if marks is not None else [("road_edge_left", "40,300;360,300"), ("road_edge_right", "40,380;360,380"), ("work_point", "200,200")]
    return json.dumps({"facts": facts, "marks": [{"feature": f, "points": p, "status": "RESOLVED", "evidence": "e"} for f, p in mk]})


def way(id_, north_m=-14.0, **tags):
    t = {"highway": "secondary", "name": "Main St", "lanes": "2", "oneway": "no", "shoulder": "no", **tags}
    return OsmWay(id_, t, ((-100.0, north_m), (100.0, north_m)))


def run(pack=None, ways=(None,), **kw):
    ways = (way(1),) if ways == (None,) else ways
    base = dict(response_text=response(), image_bytes=IMG, image_record=RECORD, profile="gpt-5.6-sol", site_id="s1", zone_id="z1", project_id="p1",
                ways=ways, pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read()))
    base.update(kw)
    return U.understand_site(U.SiteInput(**base))


def fact(u, name): return next(f for f in u.facts if f.field == name)


# ---------------------------------------------------------------- the happy path: AI and OSM agree
def test_ai_and_osm_agreeing_gives_found_safety_facts_with_both_sources(pack):
    u = run(pack)
    for name in ("lanes_per_direction", "oneway", "shoulder_present", "divided_highway"):
        f = fact(u, name)
        assert f.outcome in ("FOUND", "NOT_PRESENT") and f.source == "AI+osm_overpass" and "NEEDS_SECOND_SOURCE" not in f.flags, name
    assert fact(u, "shoulder_present").outcome == "NOT_PRESENT" and fact(u, "lanes_per_direction").value == 1
    assert fact(u, "work_location").value == "BEYOND_SHOULDER" and fact(u, "work_location").outcome == "FOUND"      # a road is near and the point is clear of it


# ---------------------------------------------------------------- the gate is called where the result is built
def test_a_result_using_an_ai_only_unconfirmed_fact_is_review_required_and_names_it(pack):
    u = run(pack)
    assert u.decision == REVIEW_REQUIRED and u.trace["gate"]["decision"] == REVIEW_REQUIRED
    named = {r["fact"] for r in u.reasons}
    assert {"median_work", "bicycle_lane_present", "approaching_lanes_one"} <= named
    assert all(r["flag"] == "AI_ONLY_UNCONFIRMED" for r in u.reasons if r["fact"] in ("median_work", "bicycle_lane_present", "approaching_lanes_one"))
    assert all("AI_ONLY_UNCONFIRMED" in fact(u, n).flags for n in ("median_work", "bicycle_lane_present", "approaching_lanes_one"))


def test_gated_for_a_caller_that_used_only_some_facts(pack):
    u = run(pack)
    assert u.gated(SUPPORTED_AUTO, used=["lanes_per_direction", "oneway", "shoulder_present"]) == (SUPPORTED_AUTO, [])
    d, reasons = u.gated(SUPPORTED_AUTO, used=["lanes_per_direction", "median_work"])
    assert d == REVIEW_REQUIRED and [r["fact"] for r in reasons] == ["median_work"]


def test_a_missing_oneway_tag_makes_the_result_review_required_naming_oneway(pack):
    ow = {k: v for k, v in way(1).tags.items() if k != "oneway"}
    u = run(pack, ways=(OsmWay(1, ow, way(1).points),))
    assert fact(u, "oneway").outcome == "FOUND" and "OSM_TAG_ASSUMED" in fact(u, "oneway").flags
    assert "oneway" in {r["fact"] for r in u.reasons}
    assert u.gated(SUPPORTED_AUTO, used=["oneway"])[0] == REVIEW_REQUIRED


# ---------------------------------------------------------------- stage switches: what each stage adds
def run_cfg(pack, **switches):
    cfg = load_site_config()
    for k, v in switches.items(): cfg["stages"][k]["value"] = v
    base = dict(response_text=response(), image_bytes=IMG, image_record=RECORD, profile="gpt-5.6-sol", ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read()))
    return U.understand_site(U.SiteInput(**base), cfg)


def test_osm_off_leaves_every_safety_field_on_a_single_source(pack):
    u = run_cfg(pack, osm=False)
    for name in ("lanes_per_direction", "oneway", "shoulder_present", "divided_highway"):
        f = fact(u, name)
        assert f.outcome == "UNKNOWN" and f.reason_code == "single_source", name
    assert u.trace["stages"]["osm"] == "off" and u.trace["skipped"]["osm"] == "off"
    assert sum(q.candidate for q in u.questions) >= 4


def test_every_stage_can_be_switched_off_and_is_recorded_in_the_trace(pack):
    names = [n for n in load_site_config()["stages"] if n != "note"]
    assert set(names) == {"osm", "bearing", "snapping", "edge_rule", "lane_lines", "shadow_canopy", "osm_offset", "consistency", "site_exceptions", "enhanced_prompt"}
    for n in names:
        if n == "enhanced_prompt": continue
        u = run_cfg(pack, **{n: False})
        assert u.trace["stages"][n] == "off", n


def test_snapping_off_keeps_the_ai_points_and_on_changes_a_rough_mark(pack):
    rough = response(marks=[("road_edge_left", "40,306;360,306"), ("road_edge_right", "40,374;360,374"), ("work_point", "200,200")])
    cfg = load_site_config()
    on = U.understand_site(U.SiteInput(rough, IMG, RECORD, ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg)
    cfg["stages"]["snapping"]["value"] = False
    off = U.understand_site(U.SiteInput(rough, IMG, RECORD, ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg)
    e_on = next(m for m in on.marks if m.feature == "road_edge_left"); e_off = next(m for m in off.marks if m.feature == "road_edge_left")
    assert e_on.original_points and abs(e_on.points[0][1] - 299.5) < 1.5 and e_off.points[0][1] == 306 and not e_off.original_points


def test_enhanced_prompt_switch_picks_the_prompt_version_for_a_run_without_an_explicit_one(pack):
    cfg = load_site_config()
    u1 = U.understand_site(U.SiteInput(response(1), IMG, RECORD, pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg)
    assert u1.trace["prompt"]["version"] == 1
    cfg["stages"]["enhanced_prompt"]["value"] = True
    u2 = U.understand_site(U.SiteInput(response(2), IMG, RECORD, pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg)
    assert u2.trace["prompt"]["version"] == 2 and u2.trace["prompt"]["user_sha256"] != u1.trace["prompt"]["user_sha256"]


# ---------------------------------------------------------------- bearing failure, OSM failure, exceptions
NORTH_SOUTH_MARKS = [("road_edge_left", "300,100;300,360"), ("road_edge_right", "380,100;380,360"), ("work_point", "200,200")]


def test_a_bearing_failure_blocks_the_road_specific_facts_and_asks_which_road(pack):
    cfg = load_site_config(); cfg["stages"]["snapping"]["value"] = False          # keep the AI's own (wrong-way) marks; snapping is shown in the next test
    u = U.understand_site(U.SiteInput(response(marks=NORTH_SOUTH_MARKS), IMG, RECORD, ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg)
    assert fact(u, "lanes_per_direction").reason_code == "wrong_road_suspected" and fact(u, "work_side").reason_code == "wrong_road_suspected"
    assert fact(u, "lanes_per_direction").candidates and fact(u, "bus_stop_present").outcome == "NOT_PRESENT"          # AI value kept; a scene fact is untouched
    assert [q.kind for q in u.questions if q.kind == "WHICH_ROAD"] == ["WHICH_ROAD"] and u.trace["checks"]["bearing"]["status"] == "MISMATCH"


def test_snapping_rejects_marks_that_follow_no_edge_in_the_image(pack):
    u = run(pack, response_text=response(marks=NORTH_SOUTH_MARKS))               # the image has no north-south pavement edge
    edges = [m for m in u.marks if m.feature.startswith("road_edge")]
    assert edges and all(m.status == "UNKNOWN" and m.reason_code == "no_edge_nearby" for m in edges)
    assert u.trace["checks"]["bearing"]["status"] == "NO_MARKS"


def test_an_osm_failure_gives_single_source_and_is_traced(pack):
    u = run(pack, ways=None, osm_error="HTTP 429")
    assert fact(u, "shoulder_present").reason_code == "single_source" and u.trace["osm_error"] == "HTTP 429" and u.trace["skipped"]["bearing"] == "OSM failed"


def test_site_exceptions_apply_only_to_their_site_field_and_are_listed_in_the_trace(pack):
    entry = {"entry_id": "E1", "site_id": "s1", "field": "parking_present", "action": "SET_VALUE", "value": True, "reason": "known parking lane",
             "proposed_by_role": "SME", "entered_by_role": "ADMIN", "date": "2026-10-31"}
    loaded = SX.parse(json.dumps({"readme": {"purpose": "p"}, "schema_version": "1", "entries": [entry]}).encode())
    u = run(pack, exceptions=loaded)
    assert fact(u, "parking_present").value is True and fact(u, "parking_present").source == "SITE_EXCEPTION" and fact(u, "bus_stop_present").source == "AI"
    exc = u.trace["site_exceptions"]
    assert exc["sha256"] == loaded.sha256 and [x["entry_id"] for x in exc["uses"]] == ["E1"] and exc["roles"] == "role selected, not verified"
    other = run(pack, exceptions=loaded, site_id="s2")
    assert fact(other, "parking_present").source == "AI" and other.trace["site_exceptions"]["uses"] == []


def test_the_shipped_empty_exceptions_file_changes_nothing_and_its_hash_is_in_the_trace(pack):
    u = run(pack)
    assert u.trace["site_exceptions"]["entries"] == 0 and u.trace["site_exceptions"]["uses"] == []
    assert u.trace["site_exceptions"]["sha256"] == hashlib.sha256(open(SX.PATH, "rb").read()).hexdigest()


# ---------------------------------------------------------------- trace and determinism
def test_the_trace_records_the_config_values_used_the_hashes_and_every_check(pack):
    u = run(pack)
    t = u.trace
    assert t["actor"] == "CODE" and t["site_id"] == "s1" and t["zone_id"] == "z1" and t["project_id"] == "p1" and t["profile"] == "gpt-5.6-sol"
    assert t["prompt"]["version"] == 1 and t["prompt"]["user_sha256"] == call1.INSTRUCTIONS_SHA256 and t["prompt"]["schema_sha256"] == "39d25f9a2c671005ed7a11a09659e01ee863dc7f6dce96a1399af9f2e3f43e02"
    for section in ("osm", "bearing", "edge_rule", "confidence_floors", "snapping", "code_checks", "consistency", "stages"): assert section in t["config"]
    assert t["config"]["bearing"]["tolerance_deg"]["value"] == 30 and t["config"]["edge_rule"]["near_edge_m"]["source"] == "CALIBRATION_PENDING"
    assert len(t["config_sha256"]) == 64 and t["floors"]["work_location"] == 0.85 and t["stages"]["osm"] == "on"
    for name in ("bearing", "edge_rule", "lane_lines", "shadow_canopy", "osm_offset"): assert name in t["checks"], name
    assert t["checks"]["bearing"]["status"] == "AGREE" and t["fusion"]["lanes_per_direction"]["agreement"] == "AGREE"
    assert t["osm"]["way_id"] == 1 and t["gate"]["decision"] == u.decision


def test_the_config_hash_follows_the_config(pack):
    a = run(pack).trace["config_sha256"]
    cfg = load_site_config(); cfg["bearing"]["tolerance_deg"]["value"] = 31
    b = U.understand_site(U.SiteInput(response(), IMG, RECORD, ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read())), cfg).trace["config_sha256"]
    assert a != b


def test_replay_is_deterministic(pack):
    a, b = run(pack), run(pack)
    assert U.trace_sha256(a) == U.trace_sha256(b) and a.facts == b.facts and a.questions == b.questions and a.decision == b.decision
    assert json.dumps(a.trace)                                                       # plain JSON, no objects


def test_questions_carry_zone_project_way_and_can_all_be_stored_as_answers(pack):
    u = run(pack, ways=None, osm_error="down")
    assert u.questions and all(q.zone_id == "z1" and q.project_id == "p1" for q in u.questions)
    for q in u.questions: assert answer_record(q, "x", "sme", "2026-10-31T10:00:00+00:00").zone_id == "z1"


def test_no_raw_local_path_is_in_the_trace(pack):
    text = json.dumps(run(pack).trace)
    assert "C:\\\\" not in text and "/c/work" not in text and "var/" not in text


# ---------------------------------------------------------------- road_name, other_roads_seen, shadow_share, canopy_share are context only (STOP 6 conditions)
CONTEXT = ("road_name", "other_roads_seen", "shadow_share", "canopy_share")


def _src(mod): return open(mod.__file__, encoding="utf-8").read()


def test_no_fusion_bearing_which_road_exceptions_or_edge_rule_code_reads_the_context_only_facts():
    from tcp_planner.site_model import (bearing_check, consistency, edge_rule, facts, fusion_apply, fusion_v2, osm_rules, outcomes, site_exceptions)
    from tcp_planner.data_sources import osm as osm_adapter
    for mod in (fusion_apply, fusion_v2, bearing_check, edge_rule, site_exceptions, osm_rules, consistency, osm_adapter):
        src = _src(mod)
        for name in ("road_name", "other_roads_seen"): assert name not in src, (mod.__name__, name)
    for mod in (fusion_apply, fusion_v2, bearing_check, edge_rule, site_exceptions, osm_rules, consistency):
        for name in ("shadow_share", "canopy_share"): assert name not in _src(mod), (mod.__name__, name)
    assert not ({"road_name", "other_roads_seen", "shadow_share", "canopy_share"} & set(consistency.OCCLUSION_AFFECTED if hasattr(consistency, "OCCLUSION_AFFECTED") else ()))


def test_the_context_facts_are_context_only_and_the_models_values_change_nothing(pack):
    cfg = load_site_config()
    base = dict(image_bytes=IMG, image_record=RECORD, ways=(way(1),), pack=pack, exceptions=SX.parse(open(SX.PATH, "rb").read()), prompt_version=2)
    runs = [U.understand_site(U.SiteInput(response(2, road_name=n, shadow=s, canopy=c), **base), cfg)
            for n, s, c in (("Main St", 0.1, 0.0), ("Elm Avenue", 0.0, 0.0), ("Cross St", 0.9, 0.9), ("US 1", 0.5, 0.2))]
    for r in runs:
        for name in CONTEXT:
            f = fact(r, name)
            assert "CONTEXT_ONLY" in f.flags and f.registry_id is None
        assert name not in r.rule_inputs
    keep = lambda r: [(f.field, f.outcome, f.value, f.reason_code, f.flags, f.source) for f in r.facts if f.field not in CONTEXT]
    assert all(keep(r) == keep(runs[0]) for r in runs[1:])                       # the road name and the model's shares change no other fact...
    assert all(r.decision == runs[0].decision and [q.question_id for q in r.questions] == [q.question_id for q in runs[0].questions] for r in runs)
    assert all(r.trace["checks"]["bearing"] == runs[0].trace["checks"]["bearing"] and r.trace["fusion"] == runs[0].trace["fusion"] for r in runs)


def test_a_road_name_is_never_compared_with_an_osm_name(pack):
    cross = OsmWay(2, {"highway": "residential", "name": "Cross St", "lanes": "2", "oneway": "no"}, ((-100.0, -60.0), (100.0, -60.0)))
    same_name = run(pack, response_text=response(2, road_name="Main St"), prompt_version=2, ways=(way(1), cross))
    other_name = run(pack, response_text=response(2, road_name="Cross St"), prompt_version=2, ways=(way(1), cross))      # the AI names the OSM cross street
    assert same_name.trace["osm"]["way_id"] == other_name.trace["osm"]["way_id"] == 1 and same_name.trace["checks"]["bearing"]["way_id"] == 1


def test_the_model_shares_are_recorded_as_evidence_only(pack):
    u = run(pack, response_text=response(2, shadow=0.9, canopy=0.9), prompt_version=2)
    ev = u.trace["checks"]["model_shares"]
    assert ev["compared"] and ev["shadow_share"]["model"] == 0.9 and ev["shadow_share"]["differs"] is True
    assert fact(u, "shoulder_present").outcome == "NOT_PRESENT"                   # a model claim of heavy cover lowered nothing


# ---------------------------------------------------------------- beside the old path
def test_the_old_path_and_this_module_do_not_import_each_other():
    tree = ast.parse(_src(U))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module: mods.add(n.module)
        if isinstance(n, ast.Import): mods |= {a.name for a in n.names}
    assert not [m for m in mods if m.startswith(("tcp_planner.orchestration", "tcp_planner.review", "tcp_planner.ai.vision_agent", "tcp_planner.site_model.fusion"))
                and m != "tcp_planner.site_model.fusion_apply"], mods
    root = os.path.join(settings.PROJECT_ROOT, "src", "tcp_planner")
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".py") and "site_model" not in dirpath.replace("\\", "/").split("src/tcp_planner/")[-1].split("/")[:1]:
                text = open(os.path.join(dirpath, n), encoding="utf-8").read()
                assert "site_model.understanding" not in text and "site_model import understanding" not in text, os.path.join(dirpath, n)


def test_the_module_never_makes_a_call():
    src = _src(U)
    for word in ("send_call1", "requests.", "urlopen", "fetch_ways", "SourceClient"):
        assert word not in src, word
