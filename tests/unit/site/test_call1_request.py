"""Call 1 request (S6 commit 2): schema, prompt, request body per API family, fingerprint, image preparation. No network."""
import base64, hashlib, io, json, os

import pytest
from PIL import Image

from tcp_planner.ai import call1
from tcp_planner.ai.foundry_provider import AnthropicMessagesAPI, FoundryVisionProvider, OpenAIResponsesAPI, tri_state_schema
from tcp_planner.contracts import ProviderError
from tcp_planner.imagery.prepare import resize_for_model

SPIKE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "site", "spike")


def _img(w, h, fmt="JPEG"):
    buf = io.BytesIO(); Image.new("RGB", (w, h), (90, 120, 60)).save(buf, fmt); return buf.getvalue()


def _request(max_px=1280, w=1280, h=1280, mpp=0.448139):
    sent, rec = resize_for_model(_img(w, h), max_px, mpp)
    return call1.build_request(sent, rec)


def _profile(name, monkeypatch, tmp_path, api, effort="high"):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"default_profile": name, "default_max_image_px": 1280, "profiles": {
        name: {"deployment": name + "-dep", "api": api, "effort": effort, "max_image_px": 1280}}}), encoding="utf-8")
    monkeypatch.setenv("TCP_FOUNDRY_PROFILES_FILE", str(path))
    for k in ("TCP_FOUNDRY_PROFILE", "TCP_FOUNDRY_API", "TCP_FOUNDRY_DEPLOYMENT"): monkeypatch.delenv(k, raising=False)
    return FoundryVisionProvider(profile=name)


# ---------------------------------------------------------------- schema
def _objects(n, path="$"):
    if isinstance(n, dict):
        if n.get("type") == "object" or "properties" in n: yield path, n
        for k, v in n.items(): yield from _objects(v, f"{path}.{k}")
    elif isinstance(n, list):
        for i, v in enumerate(n): yield from _objects(v, f"{path}[{i}]")


def _strict_problems(schema):
    """Strict-mode rules of the Responses API: every object closed (additionalProperties false) with every property required."""
    return [p for p, o in _objects(schema) if o.get("additionalProperties") is not False or sorted(o.get("required", [])) != sorted(o.get("properties", {}))]


def _keywords(n):
    """Schema keywords and type names used (property names are not keywords)."""
    out = set()
    if isinstance(n, dict):
        for k, v in n.items():
            out.add(k)
            if k == "properties":
                for sub in v.values(): out |= _keywords(sub)
            elif k == "type" and isinstance(v, str): out.add("type:" + v)
            elif k not in ("enum", "required"): out |= _keywords(v)
    elif isinstance(n, list):
        for v in n: out |= _keywords(v)
    return out


def test_schema_is_strict_clean_and_flat():
    s = call1.wire_schema(); text = json.dumps(s)
    assert _strict_problems(s) == []
    assert not {"anyOf", "oneOf", "allOf", "$ref", "$defs", "minimum", "maximum", "pattern", "nullable"} & _keywords(s)
    assert '"null"' not in text and '"type": ["' not in text   # no union type, no nullable
    from tcp_planner.ai.foundry_provider import count_union_parameters
    assert count_union_parameters(s) == 0


def test_schema_uses_only_keywords_the_working_observation_schema_already_uses():
    """The working tcp_observation schema (accepted by gpt-5.6-sol in strict mode) builds on the same keyword set."""
    working = tri_state_schema()
    assert _strict_problems(working) == []                    # same strict rules hold for the working schema
    assert _keywords(call1.wire_schema()) <= _keywords(working)


def test_schema_equals_the_spike_schema_that_claude_accepted_9_of_9():
    path = os.path.join(SPIKE, "raw", "granite_B_r1.request.json")
    spike = json.load(open(path, encoding="utf-8"))["output_config"]["format"]["schema"]
    assert call1.wire_schema() == spike


def test_field_enum_is_the_table():
    s = call1.wire_schema()
    assert s["properties"]["facts"]["items"]["properties"]["field"]["enum"] == [r.name for r in call1.FIELDS]
    assert s["properties"]["marks"]["items"]["properties"]["feature"]["enum"] == list(call1.MARK_FEATURES)


# ---------------------------------------------------------------- prompt and request
def test_prompt_states_scale_centre_and_the_no_length_rule():
    req = _request()
    text = dict((k, v) for k, v in req["parts"] if k == "text")["text"]
    assert "Image 1280x1280 px" in text and "0.448 m per pixel" in text and "centre (640,640)" in text
    assert "at most 15 words" in text and "not_visible, occluded, low_resolution, ambiguous" in text
    assert "Report no length or distance" in text and "never report a length" in req["system"]
    assert "YES" not in text and "tri-state" not in text.lower()         # provider-neutral wording


def test_request_uses_the_resized_image_and_its_scale():
    req = _request(max_px=640)
    assert req["image"]["sent_px"] == [640, 640] and abs(req["image"]["mpp_sent"] - 0.896278) < 1e-6
    text = req["parts"][1][1]
    assert "Image 640x640 px" in text and "0.896 m per pixel" in text and "centre (320,320)" in text
    assert hashlib.sha256(req["parts"][0][1]).hexdigest() == req["image"]["sha256"]


def test_request_has_schema_name_for_the_site_facts_call():
    assert _request()["schema_name"] == "tcp_site_facts" != "tcp_observation"


# ---------------------------------------------------------------- one body per API family (what each profile sends)
def test_anthropic_body(monkeypatch, tmp_path):
    p = _profile("claude-x", monkeypatch, tmp_path, "anthropic_messages"); req = _request()
    b = call1.wire_body(p, req)
    assert set(b) == {"model", "max_tokens", "system", "output_config", "messages"}
    assert b["model"] == "claude-x-dep" and b["max_tokens"] == 16000
    assert b["output_config"] == {"effort": "high", "format": {"type": "json_schema", "schema": req["schema"]}}
    block = b["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(block["source"]["data"]) == req["parts"][0][1]


def test_openai_body(monkeypatch, tmp_path):
    p = _profile("gpt-x", monkeypatch, tmp_path, "openai_responses"); req = _request()
    b = call1.wire_body(p, req)
    assert set(b) == {"model", "instructions", "max_output_tokens", "input", "text", "reasoning"}
    assert b["model"] == "gpt-x-dep" and b["max_output_tokens"] == 16000 and b["reasoning"] == {"effort": "high"}
    assert b["text"]["format"] == {"type": "json_schema", "name": "tcp_site_facts", "schema": req["schema"], "strict": True}
    assert b["input"][0]["content"][0]["type"] == "input_image" and b["input"][0]["content"][0]["detail"] == "high"


def test_the_only_difference_between_providers_is_the_envelope(monkeypatch, tmp_path):
    """Same schema object and same prompt text reach both API families; the schema name matters only to the Responses API."""
    req = _request()
    a = call1.wire_body(_profile("c", monkeypatch, tmp_path, "anthropic_messages"), req)
    o = call1.wire_body(_profile("g", monkeypatch, tmp_path, "openai_responses"), req)
    assert a["output_config"]["format"]["schema"] == o["text"]["format"]["schema"]
    assert a["system"] == o["instructions"]
    assert a["messages"][0]["content"][1]["text"] == o["input"][0]["content"][1]["text"]


def test_old_observation_body_is_unchanged_by_the_refactor():
    parts = [("image", b"\xff\xd8x"), ("text", "t")]
    o = OpenAIResponsesAPI.build_body("d", "high", parts, {"type": "object"}, "sys")
    assert o["text"]["format"]["name"] == "tcp_observation"                    # default name of the old call
    a = AnthropicMessagesAPI.build_body("d", "high", parts, {"type": "object"}, "sys")
    assert list(a) == ["model", "max_tokens", "system", "output_config", "messages"]


def test_describe_body_hides_images_and_keeps_the_rest(monkeypatch, tmp_path):
    req = _request()
    for api in ("anthropic_messages", "openai_responses"):
        shown = json.dumps(call1.describe_body(call1.wire_body(_profile("p" + api[:3], monkeypatch, tmp_path, api), req)))
        assert f"<image {len(req['parts'][0][1])} bytes sha256 {req['image']['sha256']}>" in shown
        assert base64.b64encode(req["parts"][0][1]).decode()[:80] not in shown
        assert "tcp_site_facts" in shown or "json_schema" in shown


# ---------------------------------------------------------------- fingerprint
def test_fingerprint_changes_with_prompt_schema_image_and_model(monkeypatch, tmp_path):
    p = _profile("g", monkeypatch, tmp_path, "openai_responses"); base = _request()
    fp = call1.request_fingerprint(base, p)
    assert fp == call1.request_fingerprint(_request(), p)                      # deterministic
    other_img = {**base, "parts": [("image", _img(1280, 1280, "PNG")), base["parts"][1]]}
    other_txt = {**base, "parts": [base["parts"][0], ("text", "other")]}
    other_schema = {**base, "schema": {**base["schema"], "title": "x"}}
    for changed in (other_img, other_txt, other_schema):
        assert call1.request_fingerprint(changed, p) != fp
    assert call1.request_fingerprint(base, _profile("g2", monkeypatch, tmp_path, "openai_responses")) != fp


# ---------------------------------------------------------------- calls (fakes)
class _Reply:
    def __init__(self, text="{}", usage=None): self.text, self.usage, self.truncated, self.model, self.request_id = text, usage or {}, False, "m", "r"


def test_send_call1_passes_the_request_and_schema_name(monkeypatch, tmp_path):
    p = _profile("g", monkeypatch, tmp_path, "openai_responses"); req = _request(); seen = {}
    def fake(deployment, effort, parts, schema, system=None, schema_name=None):
        seen.update(deployment=deployment, effort=effort, schema=schema, system=system, schema_name=schema_name); return _Reply()
    call1.send_call1(p, req, send=fake)
    assert seen == {"deployment": "g-dep", "effort": "high", "schema": req["schema"], "system": req["system"], "schema_name": "tcp_site_facts"}


def test_send_call1_does_not_hide_an_api_error(monkeypatch, tmp_path):
    p = _profile("g", monkeypatch, tmp_path, "openai_responses")
    def boom(*a, **k): raise ProviderError("AI_BAD_REQUEST", "bad", {"http_status": 400, "api_error_text": "image too large"})
    with pytest.raises(ProviderError) as e: call1.send_call1(p, _request(), send=boom)
    assert e.value.details["http_status"] == 400


# ---------------------------------------------------------------- image preparation
def test_no_upscale_and_original_jpeg_bytes_are_kept():
    data = _img(800, 600)
    out, rec = resize_for_model(data, 1280, 0.5)
    assert out == data and rec["resize_scale"] == 1.0 and rec["sent_px"] == [800, 600] and rec["mpp_sent"] == 0.5


def test_downscale_records_scale_and_hashes_the_bytes_sent():
    out, rec = resize_for_model(_img(1280, 1280), 640, 0.4)
    assert Image.open(io.BytesIO(out)).size == (640, 640) and rec["sent_px"] == [640, 640]
    assert rec["resize_scale"] == 0.5 and rec["mpp_sent"] == pytest.approx(0.8)
    assert rec["sha256"] == hashlib.sha256(out).hexdigest() and rec["size"] == len(out) and rec["media_type"] == "image/jpeg"


def test_downscale_keeps_the_aspect_ratio():
    out, rec = resize_for_model(_img(2000, 1000), 1000, 1.0)
    assert Image.open(io.BytesIO(out)).size == (1000, 500) and rec["mpp_sent"] == pytest.approx(2.0)


def test_png_is_sent_as_jpeg_without_resizing_when_small():
    out, rec = resize_for_model(_img(300, 200, "PNG"), 1280, 1.0)
    assert Image.open(io.BytesIO(out)).format == "JPEG" and rec["sent_px"] == [300, 200] and rec["resize_scale"] == 1.0


def test_resize_is_deterministic():
    d = _img(1280, 1280)
    assert resize_for_model(d, 512, 1.0)[0] == resize_for_model(d, 512, 1.0)[0]


@pytest.mark.parametrize("bad", [0, -5, 1.5, None, True])
def test_bad_limit_is_rejected(bad):
    with pytest.raises(ValueError): resize_for_model(_img(10, 10), bad)


def test_every_profile_has_the_1280_limit():
    from tcp_planner.ai.foundry_provider import load_profiles
    doc = load_profiles()
    assert doc["default_max_image_px"] == 1280
    assert all(p["max_image_px"] == 1280 for p in doc["profiles"].values())
