"""Foundry vision provider: one provider, deployment-driven profiles, two API-family envelopes (no network).

The canonical schema and validate_observation() are untouched; every model gets the same prompt, images and wire
schema; failures fail closed.
"""
import copy, json, os
import pytest

anthropic = pytest.importorskip("anthropic")
import requests
from anthropic.resources.messages import Messages

from tcp_planner.orchestration import offline_scenarios as offline
from tcp_planner.ai import foundry_provider as fp
from tcp_planner.orchestration.pipeline import run_pipeline
from tcp_planner.ai.foundry_provider import FoundryVisionProvider
from tcp_planner.contracts import SUPPORTED_AUTO, REVIEW_REQUIRED, ProviderError
from tcp_planner.ai.vision_provider import (get_vision_provider, OBSERVATION_SCHEMA, SYSTEM_PROMPT, api_schema,
                                            validate_observation)

OBS = offline.build("supported")["vision_provider"].observation
REVERSE = {True: "YES", False: "NO", None: "UNKNOWN"}


def to_wire(value, schema=OBSERVATION_SCHEMA):
    if fp._is_nullable_boolean(schema): return REVERSE[value]
    if isinstance(value, dict) and "properties" in schema:
        return {k: to_wire(v, schema["properties"][k]) if k in schema["properties"] else v for k, v in value.items()}
    if isinstance(value, list) and "items" in schema: return [to_wire(v, schema["items"]) for v in value]
    return value


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_FOUNDRY_BASE_URL", "ANTHROPIC_FOUNDRY_RESOURCE", "TCP_FOUNDRY_API",
              "TCP_FOUNDRY_PROFILE", "TCP_FOUNDRY_DEPLOYMENT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://example-resource.services.ai.azure.com")
    doc = {"default_profile": "claude", "profiles": {
        "claude": {"deployment": "claude-dep", "api": "anthropic_messages", "effort": "high"},
        "gpt": {"deployment": "gpt-dep", "api": "openai_responses", "effort": "high"},
        "off": {"deployment": "x", "api": "anthropic_messages", "enabled": False}}}
    path = tmp_path / "profiles.json"; path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("TCP_FOUNDRY_PROFILES_FILE", str(path))


# ---------------- real registry
def test_real_profiles_registry():
    doc = fp.load_profiles(fp.PROFILES_PATH)
    assert doc["default_profile"] == "gpt-5.6-sol"  # the agent's call-2 schema exceeds the Claude grammar limit
    p = doc["profiles"]
    assert {k: (v["deployment"], v["api"]) for k, v in p.items()} == {
        "claude-opus-5-5": ("claude-opus-5-5", "anthropic_messages"),
        "claude-opus-5-5-fast": ("claude-opus-5-5-fast", "anthropic_messages"),
        "gpt-5.6-sol": ("gpt-5.6-sol", "openai_responses")}
    text = open(fp.PROFILES_PATH, encoding="utf-8").read().lower()
    assert "api_key\"" not in text and "https://" not in text  # no secrets or endpoints in the registry


def test_catalog_lists_availability(env):
    cat = {p["name"]: p for p in fp.profile_catalog()}
    assert cat["claude"]["available"] and cat["gpt"]["available"] and not cat["off"]["available"]
    assert cat["claude"]["default"] and cat["gpt"]["api"] == "openai_responses"


def test_connection_from_common_or_existing_settings(monkeypatch, env):
    assert fp.foundry_connection() == ("https://example-resource.services.ai.azure.com", "test-key")
    monkeypatch.delenv("TCP_FOUNDRY_ENDPOINT"); monkeypatch.delenv("TCP_FOUNDRY_API_KEY")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_API_KEY", "k2")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_BASE_URL", "https://res.services.ai.azure.com/anthropic/")
    assert fp.foundry_connection() == ("https://res.services.ai.azure.com", "k2")
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL")
    with pytest.raises(ProviderError) as e: fp.foundry_connection()
    assert e.value.code == "AI_ENDPOINT_MISSING"
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY")
    with pytest.raises(ProviderError) as e: fp.foundry_connection()
    assert e.value.code == "AI_CREDENTIALS_MISSING"


# ---------------- wire format (unchanged)
def test_wire_schema_within_structured_output_limit():
    assert fp.count_union_parameters(api_schema()) == 23
    wire = fp.tri_state_schema()
    assert fp.count_union_parameters(wire) == 4 <= fp.MAX_UNION_PARAMETERS
    feats = wire["properties"]["features"]["properties"]
    assert len(feats) == 6 and all(v["items"] == {"$ref": "#/$defs/feature"} for v in feats.values())


def test_canonical_schema_untouched_and_round_trip_lossless():
    before = copy.deepcopy(OBSERVATION_SCHEMA)
    fp.tri_state_schema(); assert fp.decode_tri_state(to_wire(OBS)) == OBS
    assert OBSERVATION_SCHEMA == before


@pytest.mark.parametrize("bad", [True, False, None, "yes", "MAYBE", 1, ""])
def test_unexpected_tri_state_value_fails_closed(bad):
    w = to_wire(OBS); w["work_reference"]["appears_outside_traveled_way"] = bad
    with pytest.raises(ProviderError) as e: fp.decode_tri_state(w)
    assert e.value.code == "AI_SCHEMA_INVALID"


# ---------------- envelopes
class Block:
    def __init__(self, text): self.type = "text"; self.text = text


class Usage:
    input_tokens = 1200; output_tokens = 300; cache_read_input_tokens = 5; cache_creation_input_tokens = 0


class AResp:
    def __init__(self, text, stop="end_turn"):
        self.content = [Block(text)]; self.stop_reason = stop; self.model = "claude-opus-5-5"; self.usage = Usage()


def fake_messages(monkeypatch, result, seen):
    def create(self, **kw):
        seen.update(kw)
        if isinstance(result, Exception): raise result
        return result
    monkeypatch.setattr(Messages, "create", create)


class OResp:
    def __init__(self, status, body):
        self.status_code = status; self._b = body

    def json(self): return self._b


def oai_body(text, status="completed", content_type="output_text"):
    return {"id": "resp_1", "model": "gpt-5.6-sol-2026-07-09", "status": status,
            "output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": content_type, "text": text}]}],
            "usage": {"input_tokens": 900, "output_tokens": 400, "input_tokens_details": {"cached_tokens": 7},
                      "output_tokens_details": {"reasoning_tokens": 120}}}


def fake_post(monkeypatch, resp, seen):
    def post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, headers=headers)
        if isinstance(resp, Exception): raise resp
        return resp
    monkeypatch.setattr(requests, "post", post)


def _img():
    from PIL import Image
    return Image.new("RGB", (64, 64), (90, 90, 90))


def _ctx():
    return {"image_width_px": 64, "image_height_px": 64, "metres_per_pixel": 0.5, "reference_bearing_deg": 90.0,
            "osm_context": {"highway": "secondary", "lanes": 2, "oneway": None, "name": "Demo Road"}}


def test_anthropic_envelope(env, monkeypatch):
    seen = {}; fake_messages(monkeypatch, AResp(json.dumps(to_wire(OBS))), seen)
    r = FoundryVisionProvider("claude").analyze(_img(), _ctx())
    assert seen["model"] == "claude-dep" and "fallbacks" not in seen and "betas" not in seen
    assert seen["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": fp.tri_state_schema()}}
    assert [c["type"] for c in seen["messages"][0]["content"]] == ["image", "text"]  # single-resolution unchanged
    assert seen["system"] == SYSTEM_PROMPT
    assert r["usage"] == {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 5, "cache_creation_input_tokens": 0}
    assert r["foundry_api"] == "anthropic_messages" and r["evidence_mode"] == "single" and r["observation"] == OBS


def test_openai_responses_envelope(env, monkeypatch):
    seen = {}; fake_post(monkeypatch, OResp(200, oai_body(json.dumps(to_wire(OBS)))), seen)
    r = FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    assert seen["url"] == "https://example-resource.services.ai.azure.com/openai/v1/responses"
    assert seen["headers"]["api-key"] == "test-key"
    b = seen["body"]
    assert b["model"] == "gpt-dep" and b["instructions"] == SYSTEM_PROMPT and b["reasoning"] == {"effort": "high"}
    assert b["text"]["format"] == {"type": "json_schema", "name": "tcp_observation", "schema": fp.tri_state_schema(), "strict": True}
    content = b["input"][0]["content"]
    assert [c["type"] for c in content] == ["input_image", "input_text"]
    assert content[0]["image_url"].startswith("data:image/jpeg;base64,") and content[0]["detail"] == "high"
    assert r["usage"] == {"input_tokens": 900, "output_tokens": 400, "cache_read_input_tokens": 7,
                          "cache_creation_input_tokens": 0, "reasoning_tokens": 120}
    assert r["model"] == "gpt-5.6-sol-2026-07-09" and r["observation"] == OBS


def test_same_prompt_and_images_for_every_api_family(env, monkeypatch):
    a, o = {}, {}
    fake_messages(monkeypatch, AResp(json.dumps(to_wire(OBS))), a)
    fake_post(monkeypatch, OResp(200, oai_body(json.dumps(to_wire(OBS)))), o)
    FoundryVisionProvider("claude").analyze(_img(), _ctx()); FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    a_text = [c["text"] for c in a["messages"][0]["content"] if c["type"] == "text"]
    o_text = [c["text"] for c in o["body"]["input"][0]["content"] if c["type"] == "input_text"]
    a_img = [c["source"]["data"] for c in a["messages"][0]["content"] if c["type"] == "image"]
    o_img = [c["image_url"].split(",", 1)[1] for c in o["body"]["input"][0]["content"] if c["type"] == "input_image"]
    assert a_text == o_text and a_img == o_img and a["system"] == o["body"]["instructions"]


def test_multi_view_parts_and_captions():
    from PIL import Image
    v = {"role": "work_area", "label": "work-area close-up", "offset_m": (10.0, -5.0), "image": Image.new("RGB", (100, 100)),
         "meta": {"width_pixels": 100, "height_pixels": 100, "metres_per_pixel": 0.5}}
    parts = fp.build_parts(_img(), _ctx(), [v])
    assert [k for k, _ in parts] == ["text", "image", "text", "image", "text"]
    cap = parts[2][1]
    assert "IMAGE 2 - work-area close-up" in cap and "pixel (30,40)" in cap  # 50 - 10/0.5, 50 + (-5)/0.5
    assert "IMAGE 1 pixels" in parts[-1][1]
    assert [k for k, _ in fp.build_parts(_img(), _ctx())] == ["image", "text"]


@pytest.mark.parametrize("status, code", [(401, "AI_AUTH_FAILED"), (403, "AI_AUTH_FAILED"), (404, "AI_MODEL_NOT_FOUND"),
                                          (429, "AI_RATE_LIMITED"), (400, "AI_BAD_REQUEST"), (500, "AI_API_ERROR")])
def test_openai_http_errors_fail_closed(env, monkeypatch, status, code):
    fake_post(monkeypatch, OResp(status, {"error": {"message": "nope"}}), {})
    with pytest.raises(ProviderError) as e: FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    assert e.value.code == code


@pytest.mark.parametrize("body, code", [(oai_body("{}", status="incomplete"), "AI_TRUNCATED"),
                                        (oai_body("no", content_type="refusal"), "AI_REFUSAL"),
                                        (oai_body("not json"), "AI_SCHEMA_INVALID"),
                                        (oai_body(json.dumps(OBS)), "AI_SCHEMA_INVALID")])  # raw booleans rejected
def test_openai_response_failures(env, monkeypatch, body, code):
    fake_post(monkeypatch, OResp(200, body), {})
    with pytest.raises(ProviderError) as e: FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    assert e.value.code == code


def test_connection_error_fails_closed(env, monkeypatch):
    fake_post(monkeypatch, requests.exceptions.ConnectTimeout("timeout"), {})
    with pytest.raises(ProviderError) as e: FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    assert e.value.code == "AI_CONNECTION_FAILED"


@pytest.mark.parametrize("profile, code", [("off", "AI_PROFILE_DISABLED"), ("nope", "AI_PROFILE_UNKNOWN")])
def test_profile_errors(env, profile, code):
    with pytest.raises(ProviderError) as e: FoundryVisionProvider(profile).analyze(_img(), _ctx())
    assert e.value.code == code


# ---------------- pipeline behaviour (same fail-closed path as every provider)
def run(provider, tmp_path):
    sc = offline.build("supported")
    return run_pipeline(out_dir=str(tmp_path), operator=dict(sc["operator"]), map_provider=sc["map_provider"],
                        vision_provider=provider, osm_source=lambda lat, lon, r: sc["osm_elements"],
                        lat=sc["lat"], lon=sc["lon"])


def test_selected_by_name(env, monkeypatch):
    monkeypatch.setenv("TCP_FOUNDRY_PROFILE", "gpt")
    p = get_vision_provider("foundry")
    assert isinstance(p, FoundryVisionProvider) and p.deployment == "gpt-dep" and p.api == "openai_responses"


def to_call1_wire(obs):
    """What a compliant model returns in agent call 1 (metres, IMAGE_1 positions, extras, no osm_conflicts)."""
    mpp = 2 * offline.HALF / offline.SIZE
    w = to_wire(obs); w.pop("osm_conflicts")
    re = w["road_edges"]; px = re.pop("traveled_way_width_px")
    re.update(traveled_way_width_m=round(px * mpp, 3), width_measured_in="IMAGE_1")
    w["work_reference"].update(distance_to_nearest_edge_m=5.35, distance_measured_in="IMAGE_1")
    for items in w["features"].values():
        for it in items:
            x, y = it.pop("image_x"), it.pop("image_y")
            it.update(image="IMAGE_1", x=x, y=y)
    w["extras"] = []
    return w


def to_call2_wire(obs, n_images):
    """Agent call 2: grounded wire (metres, positions in the image where seen, evidence), width from the close view."""
    w = to_call1_wire(obs); w.pop("extras"); w["osm_conflicts"] = []
    w["road_edges"]["width_measured_in"] = "IMAGE_2" if n_images > 1 else "IMAGE_1"
    w["evidence"] = {k: {"image": "IMAGE_2", "basis": "fake"} for k in
                     ("lane_count", "two_way", "divided", "road_edges", "work_side", "work_location", "intersections", "pedestrian")}
    return w


def agent_fakes(monkeypatch):
    """Both API families answer per request: call 1 (schema has extras) or call 2 (schema has evidence)."""
    def answer(schema, n_images):
        props = schema.get("properties") or {}
        wire = to_call1_wire(OBS) if "extras" in props else to_call2_wire(OBS, n_images)
        if "osm_claim_checks" in props: wire["osm_claim_checks"] = []
        return json.dumps(wire)

    def create(self, **kw):
        n = sum(1 for c in kw["messages"][0]["content"] if c["type"] == "image")
        return AResp(answer(kw["output_config"]["format"]["schema"], n))
    monkeypatch.setattr(Messages, "create", create)

    def post(url, json=None, headers=None, timeout=None):
        n = sum(1 for c in json["input"][0]["content"] if c["type"] == "input_image")
        return OResp(200, oai_body(answer(json["text"]["format"]["schema"], n)))
    monkeypatch.setattr(requests, "post", post)


@pytest.mark.parametrize("profile", ["claude", "gpt"])
def test_valid_observation_same_decision_as_static(env, monkeypatch, tmp_path, profile):
    # the pipeline runs the two-call agent; call 2 always runs because a wide-image width cannot resolve road edges
    agent_fakes(monkeypatch)
    res = run(FoundryVisionProvider(profile), tmp_path / "f")
    ref = run(offline.build("supported")["vision_provider"], tmp_path / "s")
    assert res["decision"] == ref["decision"] == SUPPORTED_AUTO and res["reason_codes"] == ref["reason_codes"]
    with open(tmp_path / "f" / "site_model.json", encoding="utf-8") as f:
        obs = json.load(f)["evidence"]["ai"]["observation"]  # merged call 1 + call 2; notes are concatenated
        assert {k: v for k, v in obs.items() if k != "notes"} == {k: v for k, v in OBS.items() if k != "notes"}


@pytest.mark.parametrize("mutate", [lambda w: w.update(unexpected_field=1), lambda w: w.pop("lane_count_total"),
                                    lambda w: w.update(image_quality="EXCELLENT")])
def test_canonical_validation_still_applies(env, monkeypatch, mutate):
    w = to_wire(OBS); mutate(w)
    fake_post(monkeypatch, OResp(200, oai_body(json.dumps(w))), {})
    with pytest.raises(ProviderError) as e: FoundryVisionProvider("gpt").analyze(_img(), _ctx())
    assert e.value.code == "AI_SCHEMA_INVALID" and "raw_response" in e.value.details


def test_failure_gives_review_and_no_plan(env, monkeypatch, tmp_path):
    fake_messages(monkeypatch, AResp("", stop="refusal"), {})
    res = run(FoundryVisionProvider("claude"), tmp_path)
    assert res["decision"] == REVIEW_REQUIRED and "AI_OBSERVATION_UNAVAILABLE" in res["reason_codes"]
    assert not (tmp_path / "plan.json").exists()
