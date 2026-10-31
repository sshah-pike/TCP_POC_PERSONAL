"""Call 1, prompt version 3 (S6 STOP 7): pins, schema, parser, the blind request with lane_px, the context-only road_axis and
centre_at_intersection, the site-name scan, and the proof that versions 1 and 2 did not change."""
import io
import json
import os
import re

import pytest
from PIL import Image

from tcp_planner.ai import call1
from tcp_planner.ai import prompt_registry as pr
from tcp_planner.config import settings
from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.imagery.prepare import resize_for_model
from tcp_planner.site_model.site_config import load_site_config
from tests.unit.site import test_call1_request as RQ
from tests.unit.site import test_call1_v2 as TV2
from tests.unit.site import test_understanding as TU

# --- pins: a change to any of these is deliberate (update the hash in the same commit; recorded call-1 results go stale)
SYSTEM_ALL = "5e731eab10a7455ac1ace58f3f30520bc0fb0dc2d0aa4eb397cd1b57bed7266b"        # the system text of versions 1, 2 and 3
USER_V1 = "81b8f01912963d536b1c1b14d702f0abd6bcc062f512522ad3729f49bcbef988"
USER_V2 = "00ac1ea2810962ee8e5a99297489210f46a2090e9ccfcfb407bba7b88dfefe96"
USER_V3 = "0b1cc612c1e5631b21f1dd22f5fc82041ae9c7dbf39512e852975eb82a2e3689"
SCHEMA_V1 = "39d25f9a2c671005ed7a11a09659e01ee863dc7f6dce96a1399af9f2e3f43e02"
SCHEMA_V2 = "c651156d3f4a6efdb04fa1aa18e7eea0ac32f64a4d9b0d59d7c85ab3f1af109e"
SCHEMA_V3 = "6bc5082ef78685ddf3ea8b26abfeafcb136ed622c530946cf035c1e323560bc5"
COMBINED_V3 = "b3171df6be8f98367342a0892286fa715477f953dd29db593550f32a3af2cfe8"       # sha256 of system + NUL + user, the request fingerprint's prompt hash input
V1_REQUEST_PROMPT_SHA = "720ac0e1898533f5bfafd6623ec6c9e3797d2b5f5a0338fb85da84124fe48fc3"      # Granite P32 request, as before

PLACEHOLDERS = {"w", "h", "mpp", "lane_px", "cx", "cy", "words"}
CONTEXT_V3 = ("shadow_share", "canopy_share", "road_axis", "centre_at_intersection")
EXTRA_V3 = [("shadow_share", "0.2", "share"), ("canopy_share", "0.05", "share"), ("road_axis", "E-W", "enum"), ("centre_at_intersection", "false", "bool")]


def _img_bytes():
    buf = io.BytesIO(); Image.new("RGB", (1280, 1280), (90, 120, 60)).save(buf, "JPEG"); return buf.getvalue()


def _req(version=3, max_px=1280, mpp=0.448139, cfg=None):
    sent, rec = resize_for_model(_img_bytes(), max_px, mpp)
    return call1.build_request(sent, rec, cfg=cfg, version=version)


# ---------------------------------------------------------------- pins, and versions 1 and 2 untouched
def test_the_version_3_prompt_files_are_pinned_and_the_system_text_is_identical():
    assert pr.load_prompt("call1_user", 3).sha256 == USER_V3
    assert [pr.load_prompt("call1_system", v).sha256 for v in (1, 2, 3)] == [SYSTEM_ALL] * 3
    assert len({pr.load_prompt("call1_system", v).text for v in (1, 2, 3)}) == 1
    assert sha256_hex("\x00".join([pr.load_prompt("call1_system", 3).text, pr.load_prompt("call1_user", 3).text])) == COMBINED_V3


def test_versions_1_and_2_are_byte_for_byte_what_they_were():
    assert pr.load_prompt("call1_user", 1).sha256 == USER_V1 == call1.INSTRUCTIONS_SHA256
    assert pr.load_prompt("call1_user", 2).sha256 == USER_V2
    assert pr.load_prompt("call1_system", 1).sha256 == SYSTEM_ALL == call1.SYSTEM_SHA256
    assert len({USER_V1, USER_V2, USER_V3}) == 3
    assert [sha256_hex(canonical_json(call1.wire_schema(v))) for v in (1, 2, 3)] == [SCHEMA_V1, SCHEMA_V2, SCHEMA_V3]
    assert sha256_hex(canonical_json(call1.wire_schema())) == SCHEMA_V1                        # the default stays version 1


def test_the_version_1_and_2_requests_are_the_same_text_as_before():
    assert _req(1)["parts"][1][1] == pr.load_prompt("call1_user", 1).text.format(w=1280, h=1280, mpp=0.448139, cx=640, cy=640, words=15)
    assert _req(2)["parts"][1][1] == pr.load_prompt("call1_user", 2).text.format(w=1280, h=1280, mpp=0.448139, cx=640, cy=640, words=15)
    assert "lane_px" not in pr.load_prompt("call1_user", 1).text + pr.load_prompt("call1_user", 2).text


def test_the_fingerprint_of_version_1_keeps_its_hash_and_version_3_names_itself(monkeypatch, tmp_path):
    p = RQ._profile("gpt-x", monkeypatch, tmp_path, "openai_responses")
    f1, f3 = call1.request_fingerprint(_req(1), p), call1.request_fingerprint(_req(3), p)
    assert f1["prompt_sha256"] == V1_REQUEST_PROMPT_SHA and f1["prompt_version"] == 1
    assert f3["prompt_version"] == 3 and f3["schema_name"] == "tcp_site_facts_v3" and f3["schema_sha256"] == SCHEMA_V3
    assert f3["prompt_sha256"] not in (f1["prompt_sha256"], call1.request_fingerprint(_req(2), p)["prompt_sha256"])


# ---------------------------------------------------------------- the template
def test_the_template_has_exactly_the_planned_placeholders_and_formats_cleanly():
    t = pr.load_prompt("call1_user", 3).text
    assert set(re.findall(r"\{(\w+)(?::[^}]*)?\}", t)) == PLACEHOLDERS
    for spec in ("{mpp:.3f}", "{lane_px:.0f}", "{w}x{h}", "({cx},{cy})", "{words}"):
        assert spec in t, spec
    assert t.startswith("Image {w}x{h} px, north-up, {mpp:.3f} m per pixel; a normal traffic lane is about {lane_px:.0f} px wide at this scale.")
    assert t.endswith("Report no length or distance. Return the JSON object only.")
    t.format(w=1, h=1, mpp=0.5, lane_px=7.0, cx=0, cy=0, words=15)                             # no stray brace


def test_the_text_change_from_version_2_is_the_planned_one():
    old, new = pr.load_prompt("call1_user", 2).text, pr.load_prompt("call1_user", 3).text
    for gone in ("road_name", "other_roads_seen", "Choose the road nearest the work location"):
        assert gone in old and gone not in new, gone
    for added in ("{lane_px:.0f} px wide", "centre_at_intersection to true", "Give road_axis for that road (N-S, E-W, NE-SW, NW-SE or CURVED)",
                  "The work location is a point, not a place on a road", "never infer it from the surroundings", "BEYOND_SHOULDER (off the pavement",
                  "Do not draw an edge across a junction", "Confidence: 0.9 or more only for what you can see directly",
                  "answer UNKNOWN with reason canopy, shadowed or occluded"):
        assert added in new and added not in old, added
    for kept in ("Reason: for every fact exactly one of visible, not_visible, occluded, low_resolution, ambiguous, shadowed, canopy",
                 "For UNKNOWN, evidence is exactly one of: not_visible, occluded, low_resolution, ambiguous.",
                 "shadow_share and canopy_share: a number from 0 to 1", "nearest_edge_point: one point", "Evidence: at most {words} words."):
        assert kept in old and kept in new, kept


def test_the_prompt_asks_for_no_length_and_no_distance():
    t = pr.load_prompt("call1_user", 3).text + pr.load_prompt("call1_system", 3).text
    assert "Report no length or distance" in t and "never report a length" in t
    assert t.lower().count("distance") == t.lower().count("length or distance")
    user = pr.load_prompt("call1_user", 3).text.lower()                                       # the user text asks for no unit of length at all
    assert " ft" not in user and "feet" not in user and "metres" not in user and "meters" not in user


NAMES = ("granite", "second", "colorado", "union", "watertown", "boston", "newton", "lowell", "lunenburg", "westerly", "mattapan")


def test_the_prompt_names_no_test_site_road_city_state_or_ta():
    blob = (pr.load_prompt("call1_user", 3).text + pr.load_prompt("call1_system", 3).text + json.dumps(call1.wire_schema(3))).lower()
    for n in NAMES: assert n not in blob, n
    assert "ta-" not in blob and not re.search(r"\bta\s?\d", blob)
    raw = open(pr.prompt_path("call1_user", 3), encoding="utf-8").read().lower()               # the header too
    for n in NAMES: assert n not in raw, n
    assert "ta-" not in raw


# ---------------------------------------------------------------- schema
def test_schema_v3_is_strict_flat_and_differs_from_v2_only_as_planned():
    v2, v3 = call1.wire_schema(2), call1.wire_schema(3)
    assert RQ._strict_problems(v3) == []
    assert not {"anyOf", "oneOf", "allOf", "$ref", "$defs", "minimum", "maximum", "pattern", "nullable"} & RQ._keywords(v3)
    assert '"null"' not in json.dumps(v3)
    from tcp_planner.ai.foundry_provider import count_union_parameters
    assert count_union_parameters(v3) == 0
    f2, f3 = (s["properties"]["facts"]["items"]["properties"] for s in (v2, v3))
    assert f3["field"]["enum"] == [r.name for r in call1.FIELDS] + list(CONTEXT_V3)
    assert "road_name" not in f3["field"]["enum"] and "other_roads_seen" not in f3["field"]["enum"]
    assert set(f3) == set(f2) and f3["reason"]["enum"] == f2["reason"]["enum"] == list(call1.REASONS_V2) and f3["unit"] == f2["unit"]
    assert v3["properties"]["marks"] == v2["properties"]["marks"]
    assert call1.fields_for(3)[-2].values == ("N-S", "E-W", "NE-SW", "NW-SE", "CURVED", "UNKNOWN")


def test_the_version_3_request_shape_and_both_api_families(monkeypatch, tmp_path):
    r = _req(3)
    assert r["prompt_version"] == 3 and r["schema_name"] == "tcp_site_facts_v3" and r["schema"] == call1.wire_schema(3) and r["system"] == call1.SYSTEM
    a = call1.wire_body(RQ._profile("c", monkeypatch, tmp_path, "anthropic_messages"), r)
    o = call1.wire_body(RQ._profile("g", monkeypatch, tmp_path, "openai_responses"), r)
    assert a["output_config"]["format"]["schema"] == o["text"]["format"]["schema"] == r["schema"]
    assert o["text"]["format"]["name"] == "tcp_site_facts_v3" and o["text"]["format"]["strict"] is True
    assert call1.build_request(*resize_for_model(_img_bytes(), 1280, 0.448139))["prompt_version"] == 1       # version 1 stays the default


def test_an_unknown_version_is_refused():
    with pytest.raises(ValueError): call1.fields_for(4)


# ---------------------------------------------------------------- lane_px and the blind request
@pytest.mark.parametrize("mpp, shown", [(0.448139, "7"), (0.25, "13"), (0.05, "66"), (1.0, "3")])
def test_lane_px_is_the_reference_width_over_the_scale(mpp, shown):
    width = load_site_config()["call1"]["reference_lane_width_m"]["value"]
    assert width == 3.3 and call1.lane_px(mpp) == pytest.approx(3.3 / mpp)
    sent, rec = resize_for_model(_img_bytes(), 1280, mpp)
    assert f"is about {shown} px wide at this scale" in call1.build_request(sent, rec, version=3)["parts"][1][1]


def test_the_reference_width_is_a_pending_config_value_and_comes_from_config_only():
    entry = load_site_config()["call1"]["reference_lane_width_m"]
    assert entry["source"] == "CALIBRATION_PENDING"
    cfg = load_site_config(); cfg["call1"]["reference_lane_width_m"]["value"] = 4.4
    assert "is about 10 px wide" in _req(3, mpp=0.448139, cfg=cfg)["parts"][1][1]              # 4.4 / 0.448 = 9.8
    src = open(call1.__file__, encoding="utf-8").read()
    assert "3.3" not in src


def test_the_version_3_request_text_is_the_template_filled_with_image_numbers_only():
    r = _req(3)
    assert r["parts"][1][1] == pr.load_prompt("call1_user", 3).text.format(w=1280, h=1280, mpp=0.448139, lane_px=3.3 / 0.448139, cx=640, cy=640, words=15)
    import inspect
    assert list(inspect.signature(call1.build_request).parameters) == ["image_bytes", "record", "cfg", "version"]       # nothing else can be passed in


def test_no_osm_or_code_value_is_in_the_version_3_request():
    r = _req(3)
    blob = (r["system"] + r["parts"][1][1] + json.dumps(r["schema"])).lower()
    for word in ("osm", "openstreetmap", "overpass", "way id", "lanes:forward", "oneway=", "highway=", "bearing", "tolerance", "margin", "wrong_road",
                 "site_exception", "second source", "needs_second_source"):
        assert word not in blob, word


# ---------------------------------------------------------------- parser and context-only facts
def v3_doc(extra=EXTRA_V3, marks=()):
    facts = []
    for r in call1.FIELDS:
        v = {"bool": ("false", "bool"), "count": ("2", "count"), "enum": ("N", "enum"), "text": ("NONE", "text")}[r.kind]
        if r.name == "work_location": v = ("ROADWAY", "enum")
        facts.append(TV2.v2_fact(r.name, v[0], v[1]))
    facts += [TV2.v2_fact(n, v, u) for n, v, u in extra]
    return json.dumps({"facts": facts, "marks": list(marks)})


def test_a_version_3_response_parses_and_the_new_facts_are_context_only():
    res = call1.parse_call1(v3_doc(), (1280, 1280), version=3)
    o = res.observations
    assert list(o) == [r.name for r in call1.FIELDS] + list(CONTEXT_V3)
    assert o["road_axis"].value == "E-W" and o["centre_at_intersection"].value is False and o["shadow_share"].value == 0.2
    assert res.notes == () and call1.schema_problems(v3_doc(), res) == []
    facts, _ = call1.to_site_facts(res)
    by = {f.field: f for f in facts}
    assert [f.field for f in facts][-4:] == list(CONTEXT_V3)
    for n in CONTEXT_V3: assert "CONTEXT_ONLY" in by[n].flags and by[n].registry_id is None
    from tcp_planner.site_model.facts import rule_inputs
    assert not (set(CONTEXT_V3) & set(rule_inputs(facts)))


def test_the_axis_is_compared_without_case_and_a_bad_axis_or_flag_is_unknown_malformed():
    ok = call1.parse_call1(v3_doc([("road_axis", "ne-sw", "enum")]), (1280, 1280), version=3).observations["road_axis"]
    assert ok.status == "RESOLVED" and ok.value == "NE-SW"
    curved = call1.parse_call1(v3_doc([("road_axis", "CURVED", "enum"), ("centre_at_intersection", "TRUE", "bool")]), (1280, 1280), version=3).observations
    assert curved["road_axis"].value == "CURVED" and curved["centre_at_intersection"].value is True
    for field, bad, unit in (("road_axis", "NORTH", "enum"), ("road_axis", "N/S", "enum"), ("centre_at_intersection", "maybe", "bool")):
        o = call1.parse_call1(v3_doc([(field, bad, unit)]), (1280, 1280), version=3).observations[field]
        assert o.status == "UNKNOWN" and o.reason_code == "malformed", (field, bad)
    unk = call1.parse_call1(json.dumps({"facts": [TV2.v2_fact("road_axis", "UNKNOWN", "enum", status="UNKNOWN", evidence="ambiguous", reason="ambiguous")], "marks": []}),
                            (1280, 1280), version=3).observations["road_axis"]
    assert unk.status == "UNKNOWN" and unk.reason_code == "ambiguous"


def test_the_dropped_version_2_facts_are_not_fields_of_version_3_and_a_missing_one_is_unknown():
    res = call1.parse_call1(v3_doc(EXTRA_V3 + [("road_name", "US 1", "text")]), (1280, 1280), version=3)
    assert "road_name" not in res.observations and any("road_name" in n for n in res.notes)
    gone = call1.parse_call1(v3_doc(EXTRA_V3[:2]), (1280, 1280), version=3).observations
    assert gone["road_axis"].reason_code == "missing" and gone["centre_at_intersection"].reason_code == "missing"


def test_version_2_parsing_is_unchanged():
    res = call1.parse_call1(TV2.v2_doc(TV2.EXTRA), (1280, 1280), version=2)
    assert list(res.observations)[-4:] == ["road_name", "other_roads_seen", "shadow_share", "canopy_share"] and "road_axis" not in res.observations
    facts, _ = call1.to_site_facts(res)
    assert [f.field for f in facts][-4:] == ["road_name", "other_roads_seen", "shadow_share", "canopy_share"]


def test_no_decision_code_reads_road_axis_or_centre_at_intersection():
    from tcp_planner.site_model import (bearing_check, consistency, edge_rule, facts, fusion_apply, fusion_v2, osm_rules, outcomes, site_exceptions,
                                        understanding, code_checks, lengths, precalc)
    from tcp_planner.data_sources import osm as osm_adapter
    for mod in (fusion_apply, fusion_v2, bearing_check, edge_rule, site_exceptions, osm_rules, consistency, osm_adapter, code_checks, lengths, outcomes,
                understanding, facts):
        src = open(mod.__file__, encoding="utf-8").read()
        for name in ("road_axis", "centre_at_intersection"): assert name not in src, (mod.__name__, name)


def _understand(pack, axis, centre):
    cfg = load_site_config()
    doc = json.loads(v3_doc([("shadow_share", "0.1", "share"), ("canopy_share", "0.0", "share"), ("road_axis", axis, "enum"),
                             ("centre_at_intersection", centre, "bool")], marks=[
        {"feature": f, "points": p, "status": "RESOLVED", "evidence": "e"}
        for f, p in (("road_edge_left", "40,300;360,300"), ("road_edge_right", "40,380;360,380"), ("work_point", "200,200"))]))
    for f in doc["facts"]:                                                                    # the shared fixture's value table, so the facts match a real run
        if f["field"] in TU.VALUES: f["value"], f["unit"] = TU.VALUES[f["field"]]
    return TU.U.understand_site(TU.U.SiteInput(json.dumps(doc), TU.IMG, TU.RECORD, ways=(TU.way(1),), pack=pack, prompt_version=3,
                                               exceptions=TU.SX.parse(open(TU.SX.PATH, "rb").read())), cfg)


def test_changing_road_axis_and_centre_at_intersection_changes_no_other_fact(pack):
    runs = [_understand(pack, a, c) for a, c in (("E-W", "false"), ("N-S", "true"), ("CURVED", "false"), ("UNKNOWN", "UNKNOWN"), ("NW-SE", "true"))]
    for r in runs:
        for n in ("road_axis", "centre_at_intersection"):
            f = TU.fact(r, n)
            assert "CONTEXT_ONLY" in f.flags and f.registry_id is None and n not in r.rule_inputs
    keep = lambda r: [(f.field, f.outcome, f.value, f.reason_code, f.flags, f.source) for f in r.facts if f.field not in ("road_axis", "centre_at_intersection")]
    assert all(keep(r) == keep(runs[0]) for r in runs[1:])
    assert all(r.decision == runs[0].decision and [q.question_id for q in r.questions] == [q.question_id for q in runs[0].questions] for r in runs)
    assert all(r.trace["checks"]["bearing"] == runs[0].trace["checks"]["bearing"] and r.trace["fusion"] == runs[0].trace["fusion"] for r in runs)
    assert all(r.trace["prompt"]["version"] == 3 and r.trace["prompt"]["user_sha256"] == USER_V3 and r.trace["prompt"]["schema_sha256"] == SCHEMA_V3 for r in runs)
    assert TU.fact(runs[1], "centre_at_intersection").value is True                           # kept and shown, not dropped


@pytest.fixture(scope="module")
def pack():
    from tcp_planner.rules.rule_pack_store import JsonRulePackStore
    return JsonRulePackStore().load()


# ---------------------------------------------------------------- the stage switch and the default are unchanged
def test_the_enhanced_prompt_switch_is_off_and_still_selects_version_2_not_3():
    cfg = load_site_config()
    assert cfg["stages"]["enhanced_prompt"]["value"] is False
    assert call1.PROMPT_VERSION == 1
    src = open(os.path.join(settings.PROJECT_ROOT, "src", "tcp_planner", "site_model", "understanding.py"), encoding="utf-8").read()
    assert "(2 if on[\"enhanced_prompt\"] else 1)" in src
