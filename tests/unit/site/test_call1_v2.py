"""Call 1, prompt version 2 (the enhanced prompt, S6 step 8): pins, schema, parser, and the BLIND request (no OSM or code values)."""
import ast
import hashlib
import io
import json
import os

import pytest
from PIL import Image

from tcp_planner.ai import call1
from tcp_planner.ai import prompt_registry as pr
from tcp_planner.config import settings
from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.imagery.prepare import resize_for_model
from tests.unit.site import test_call1_request as RQ

# --- pins: a change to any of these is deliberate (update the hash in the same commit; recorded call-1 results go stale)
SYSTEM_V2 = "5e731eab10a7455ac1ace58f3f30520bc0fb0dc2d0aa4eb397cd1b57bed7266b"          # identical to version 1: the diff is the user template
USER_V2 = "00ac1ea2810962ee8e5a99297489210f46a2090e9ccfcfb407bba7b88dfefe96"
COMBINED_V2 = sha256_hex("\x00".join([pr.load_prompt("call1_system", 2).text, pr.load_prompt("call1_user", 2).text]))
SCHEMA_V1 = "39d25f9a2c671005ed7a11a09659e01ee863dc7f6dce96a1399af9f2e3f43e02"
SCHEMA_V2 = "c651156d3f4a6efdb04fa1aa18e7eea0ac32f64a4d9b0d59d7c85ab3f1af109e"


def _req(version=2, max_px=1280, mpp=0.448139):
    buf = io.BytesIO(); Image.new("RGB", (1280, 1280), (90, 120, 60)).save(buf, "JPEG")
    sent, rec = resize_for_model(buf.getvalue(), max_px, mpp)
    return call1.build_request(sent, rec, version=version)


# ---------------------------------------------------------------- pins
def test_the_version_2_prompt_files_are_pinned_and_version_1_is_untouched():
    assert pr.load_prompt("call1_system", 2).sha256 == SYSTEM_V2 == call1.SYSTEM_SHA256
    assert pr.load_prompt("call1_user", 2).sha256 == USER_V2
    assert pr.load_prompt("call1_user", 1).sha256 == call1.INSTRUCTIONS_SHA256 != USER_V2
    assert COMBINED_V2 != "58a344b4f526c55c965b35f80d9c8d78d222932fdbda2e80b1f606ce2550ad6f"            # the combined hash did change
    assert sha256_hex(canonical_json(call1.wire_schema())) == SCHEMA_V1 == sha256_hex(canonical_json(call1.wire_schema(1)))


def test_the_version_2_schema_is_pinned():
    assert sha256_hex(canonical_json(call1.wire_schema(2))) == SCHEMA_V2 != SCHEMA_V1


def test_the_text_change_from_version_1_is_exactly_the_planned_one():
    old, new = pr.load_prompt("call1_user", 1).text, pr.load_prompt("call1_user", 2).text
    for phrase in ("the two OUTER edges of the asphalt", "not the sidewalk edge", "not a gutter or kerb line", "road_name", "other_roads_seen",
                   "shadow_share and canopy_share", "nearest_edge_point", "Reason: for every fact exactly one of visible, not_visible, occluded, "
                   "low_resolution, ambiguous, shadowed, canopy", "Choose the road nearest the work location"):
        assert phrase in new and phrase not in old, phrase
    for kept in ("Image {w}x{h} px, north-up, {mpp:.3f} m per pixel", "Report no length or distance. Return the JSON object only.",
                 "For UNKNOWN, evidence is exactly one of: not_visible, occluded, low_resolution, ambiguous."):
        assert kept in old and kept in new, kept


def test_the_prompt_asks_for_no_length_and_no_distance_in_feet_or_metres():
    t = pr.load_prompt("call1_user", 2).text + pr.load_prompt("call1_system", 2).text
    assert "Report no length or distance" in t and "never report a length" in t
    assert t.lower().count("distance") == t.lower().count("length or distance")                # every mention is the ban itself; the edge distance is computed by code from a point


# ---------------------------------------------------------------- schema
def test_schema_v2_is_strict_clean_and_flat_and_extends_v1_only_as_planned():
    v1, v2 = call1.wire_schema(1), call1.wire_schema(2)
    assert RQ._strict_problems(v2) == []
    assert not {"anyOf", "oneOf", "allOf", "$ref", "$defs", "minimum", "maximum", "pattern", "nullable"} & RQ._keywords(v2)
    assert '"null"' not in json.dumps(v2)
    f1, f2 = v1["properties"]["facts"]["items"]["properties"], v2["properties"]["facts"]["items"]["properties"]
    assert set(f2) - set(f1) == {"reason"} and f2["reason"]["enum"] == list(call1.REASONS_V2)
    assert f2["field"]["enum"] == f1["field"]["enum"] + ["road_name", "other_roads_seen", "shadow_share", "canopy_share"]
    assert f2["unit"]["enum"] == f1["unit"]["enum"] + ["share"]
    m1, m2 = (v["properties"]["marks"]["items"]["properties"]["feature"]["enum"] for v in (v1, v2))
    assert m2 == m1 + ["nearest_edge_point"]
    from tcp_planner.ai.foundry_provider import count_union_parameters
    assert count_union_parameters(v2) == 0


def test_version_2_request_shape_and_names():
    r = _req(2)
    assert r["prompt_version"] == 2 and r["schema_name"] == "tcp_site_facts_v2" and r["schema"] == call1.wire_schema(2)
    assert r["system"] == call1.SYSTEM and "OUTER edges" in r["parts"][1][1] and "Image 1280x1280 px" in r["parts"][1][1]
    v1 = _req(1)
    assert v1["prompt_version"] == 1 and v1["schema_name"] == "tcp_site_facts" and v1["schema"] == call1.wire_schema()
    assert call1.build_request(*resize_for_model(_img_bytes(), 1280, 0.448139)) ["prompt_version"] == 1             # version 1 stays the default


def _img_bytes():
    buf = io.BytesIO(); Image.new("RGB", (1280, 1280), (90, 120, 60)).save(buf, "JPEG"); return buf.getvalue()


def test_the_fingerprint_names_the_prompt_version_and_the_old_version_keeps_its_hashes(monkeypatch, tmp_path):
    p = RQ._profile("gpt-x", monkeypatch, tmp_path, "openai_responses")
    f1, f2 = call1.request_fingerprint(_req(1), p), call1.request_fingerprint(_req(2), p)
    assert f1["prompt_version"] == 1 and f2["prompt_version"] == 2 and f1["prompt_sha256"] != f2["prompt_sha256"] and f1["schema_sha256"] != f2["schema_sha256"]
    assert f1["prompt_sha256"] == "720ac0e1898533f5bfafd6623ec6c9e3797d2b5f5a0338fb85da84124fe48fc3"       # Granite P32 request, as before


def test_both_api_families_get_the_version_2_body(monkeypatch, tmp_path):
    r = _req(2)
    a = call1.wire_body(RQ._profile("c", monkeypatch, tmp_path, "anthropic_messages"), r)
    o = call1.wire_body(RQ._profile("g", monkeypatch, tmp_path, "openai_responses"), r)
    assert a["output_config"]["format"]["schema"] == o["text"]["format"]["schema"] == r["schema"]
    assert o["text"]["format"]["name"] == "tcp_site_facts_v2" and o["text"]["format"]["strict"] is True
    assert a["messages"][0]["content"][1]["text"] == o["input"][0]["content"][1]["text"]


# ---------------------------------------------------------------- the request is blind
def test_the_request_text_is_the_template_filled_with_image_numbers_only():
    r = _req(2)
    text = r["parts"][1][1]
    tmpl = pr.load_prompt("call1_user", 2).text
    assert text == tmpl.format(w=1280, h=1280, mpp=0.448139, cx=640, cy=640, words=15)
    import inspect
    assert list(inspect.signature(call1.build_request).parameters) == ["image_bytes", "record", "cfg", "version"]       # nothing else can be passed in


@pytest.mark.parametrize("version", [1, 2])
def test_no_osm_or_code_value_is_in_the_request(version):
    r = _req(version)
    blob = (r["system"] + r["parts"][1][1] + json.dumps(r["schema"])).lower()
    for word in ("osm", "openstreetmap", "overpass", "way id", "lanes:forward", "lanes:backward", "oneway=", "highway=", "bearing", "tolerance",
                 "margin", "wrong_road", "site_exception", "second source", "needs_second_source"):
        assert word not in blob, word


def test_call1_imports_no_data_source_and_no_code_check():
    tree = ast.parse(open(call1.__file__, encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module: mods.add(n.module)
        if isinstance(n, ast.Import): mods |= {a.name for a in n.names}
    banned = ("tcp_planner.data_sources", "tcp_planner.site_model.osm_rules", "tcp_planner.site_model.bearing_check", "tcp_planner.site_model.edge_rule",
              "tcp_planner.site_model.fusion_apply", "tcp_planner.site_model.site_exceptions", "tcp_planner.imagery.snap")
    assert not [m for m in mods if m.startswith(banned)], mods


def test_building_the_request_never_touches_osm(monkeypatch):
    def boom(*a, **k): raise AssertionError("OSM was consulted while building the request")
    import tcp_planner.data_sources.osm as osm
    import tcp_planner.site_model.osm_rules as rules
    monkeypatch.setattr(osm, "fetch_ways", boom); monkeypatch.setattr(rules, "osm_read", boom)
    assert _req(2)["parts"][1][1] and _req(1)["parts"][1][1]


# ---------------------------------------------------------------- parser, version 2
def v2_fact(field, value, unit, conf=0.9, reason="visible", status="RESOLVED", evidence="seen"):
    return {"field": field, "value": value, "unit": unit, "status": status, "confidence": conf, "evidence": evidence, "reason": reason}


def v2_doc(extra=(), marks=()):
    facts = []
    for r in call1.FIELDS:
        v = {"bool": ("false", "bool"), "count": ("2", "count"), "enum": ("N", "enum"), "text": ("NONE", "text")}[r.kind]
        if r.name == "work_location": v = ("ROADWAY", "enum")
        facts.append(v2_fact(r.name, v[0], v[1]))
    return json.dumps({"facts": facts + list(extra), "marks": list(marks)})


EXTRA = [v2_fact("road_name", "US 1", "text"), v2_fact("other_roads_seen", "Cross St", "text"),
         v2_fact("shadow_share", "0.2", "share", reason="shadowed"), v2_fact("canopy_share", "0.05", "share", reason="canopy")]


def test_a_version_2_response_parses_with_reasons_shares_and_the_new_mark():
    marks = [{"feature": "nearest_edge_point", "points": "300,410", "status": "RESOLVED", "evidence": "edge"},
             {"feature": "road_edge_left", "points": "10,10;100,10", "status": "RESOLVED", "evidence": "e"}]
    res = call1.parse_call1(v2_doc(EXTRA, marks), (1280, 1280), version=2)
    o = res.observations
    assert o["shadow_share"].value == 0.2 and o["canopy_share"].value == 0.05 and o["road_name"].value == "US 1" and o["other_roads_seen"].value == "Cross St"
    assert o["lanes_per_direction"].ai_reason == "visible" and o["shadow_share"].ai_reason == "shadowed" and o["canopy_share"].ai_reason == "canopy"
    assert [m.feature for m in res.marks] == ["nearest_edge_point", "road_edge_left"] and res.marks[0].points == ((300.0, 410.0),)
    assert res.notes == () and call1.schema_problems(v2_doc(EXTRA, marks), res) == []


def test_the_new_facts_become_context_only_facts_that_no_rule_reads():
    res = call1.parse_call1(v2_doc(EXTRA), (1280, 1280), version=2)
    facts, _ = call1.to_site_facts(res)
    by = {f.field: f for f in facts}
    for name in ("road_name", "other_roads_seen", "shadow_share", "canopy_share"):
        assert "CONTEXT_ONLY" in by[name].flags and by[name].registry_id is None
    from tcp_planner.site_model.facts import rule_inputs
    assert not ({"road_name", "other_roads_seen", "shadow_share", "canopy_share"} & set(rule_inputs(facts)))


@pytest.mark.parametrize("bad", ["1.5", "-0.1", "lots", "nan"])
def test_a_share_outside_zero_to_one_is_unknown_malformed(bad):
    res = call1.parse_call1(v2_doc([v2_fact("shadow_share", bad, "share")]), (1280, 1280), version=2)
    assert res.observations["shadow_share"].status == "UNKNOWN" and res.observations["shadow_share"].reason_code == "malformed"


def test_a_missing_version_2_fact_is_unknown_and_an_unknown_reason_is_dropped():
    res = call1.parse_call1(v2_doc([v2_fact("shadow_share", "0.1", "share", reason="because")]), (1280, 1280), version=2)
    assert res.observations["canopy_share"].reason_code == "missing" and res.observations["shadow_share"].ai_reason is None


def test_version_1_parsing_is_unchanged_and_rejects_the_version_2_extras():
    spike = os.path.join(settings.PROJECT_ROOT, "tests", "fixtures", "site", "bearing", "marks_nine_and_nine.json")
    assert os.path.isfile(spike)
    res = call1.parse_call1(v2_doc(EXTRA), (1280, 1280))                        # a v2 document read as version 1: facts malformed (extra key), extras dropped
    assert all(o.ai_reason is None for o in res.observations.values()) and "road_name" not in res.observations
    assert len(res.observations) == 18


def test_unknown_fact_keeps_its_reason():
    doc = v2_doc([v2_fact("shadow_share", "UNKNOWN", "share", status="UNKNOWN", evidence="occluded", reason="canopy")])
    o = call1.parse_call1(doc, (1280, 1280), version=2).observations["shadow_share"]
    assert o.status == "UNKNOWN" and o.reason_code == "occluded" and o.ai_reason == "canopy"
