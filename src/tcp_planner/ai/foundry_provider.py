"""Microsoft Foundry as a VisionProvider: one provider, one connection, deployment-driven model selection.

The pipeline sees only VisionProvider.analyze() -> the canonical, validate_observation()-checked observation.

    FoundryVisionProvider
        -> common Foundry connection (endpoint + key from .env)
        -> profile from foundry_profiles.json (deployment name, API family, effort)
        -> the SAME prompt, images and wire schema for every model
        -> API-family adapter (request envelope + response envelope only)
        -> transport normalization (tri-state -> canonical)
        -> existing validate_observation()

API families (verified 2026-10-18 against this Foundry resource, same endpoint host and key for all deployments):
  anthropic_messages   /anthropic/v1/messages   Claude deployments (image block base64, output_config.format)
  openai_responses     /openai/v1/responses     GPT deployments (input_image data URL, text.format json_schema strict)
Claude deployments also answer on /openai/v1/responses, but there the image is dropped and the schema is not
enforced - so each profile names the API family that was verified for it.

Configuration:
  .env (secrets / common):  TCP_FOUNDRY_API_KEY or ANTHROPIC_FOUNDRY_API_KEY
                            TCP_FOUNDRY_ENDPOINT (https://<resource>.services.ai.azure.com), or derived from
                            ANTHROPIC_FOUNDRY_BASE_URL / ANTHROPIC_FOUNDRY_RESOURCE
                            TCP_FOUNDRY_PROFILE (optional; else default_profile)
  foundry_profiles.json:    profile id -> display_name, deployment, api, effort, enabled (no secrets)

Diagnostics:
  TCP_DEBUG_SENT=1          writes every request (exact image bytes, system + user prompt text, schema, meta.json with
                            model, image sizes and SHA-256 per image) to ./debug_sent/ - request data only, never the
                            response. Off by default; a warning is printed whenever it writes.
  API errors                keep the API's own error text (up to ERROR_TEXT_LIMIT characters, key-like strings
                            removed); billing / quota / credit errors get their own code (AI_BILLING_OR_QUOTA).
"""
import base64, copy, datetime, hashlib, io, json, os
from urllib.parse import urlsplit
from tcp_planner.contracts import ProviderError, redact, canonical_json, sha256_hex
from tcp_planner.config.settings import PROJECT_ROOT, CONFIG_DIR
from .vision_provider import (VisionProvider, OBSERVATION_SCHEMA, SYSTEM_PROMPT, build_prompt, api_schema,
                              validate_observation)

# ---------------------------------------------------------------- wire format "tri-state-v1"
# Two limits of the Claude structured-output compiler, both reported by the API for the canonical schema:
#  1. at most 16 union-typed (nullable) parameters - the canonical schema has 23;
#  2. "compiled grammar is too large" - the feature object is repeated in six arrays.
# On the wire only: every canonical boolean-or-null field is sent as one string enum (not a union) - lossless,
# YES -> true, NO -> false, UNKNOWN -> null - and the feature object is defined once ($defs) and referenced by
# the six arrays (identical structure, nothing to decode). The full structure stays enforced by the API.
TRI_STATE = {"YES": True, "NO": False, "UNKNOWN": None}
TRI_STATE_FORMAT = "tri-state-v1"
TRI_STATE_PROMPT = ("Yes/no fields in this response use the strings YES, NO or UNKNOWN "
                    "(UNKNOWN when it is not visible).")


def _is_nullable_boolean(schema):
    t = schema.get("type")
    return isinstance(t, list) and sorted(t) == ["boolean", "null"]


def _tri_state_canonical(schema):
    """Canonical schema with nullable booleans replaced by the tri-state enum (structure otherwise identical)."""
    if _is_nullable_boolean(schema):
        return {"type": "string", "enum": list(TRI_STATE)}
    s = dict(schema)
    if "properties" in s: s["properties"] = {k: _tri_state_canonical(v) for k, v in s["properties"].items()}
    if "items" in s: s["items"] = _tri_state_canonical(s["items"])
    return s


def tri_state_schema():
    """Structured-output schema sent to the model (same api_schema() transform as every provider)."""
    canon = _tri_state_canonical(copy.deepcopy(OBSERVATION_SCHEMA))
    feats = canon["properties"]["features"]["properties"]
    feature = feats[next(iter(feats))]["items"]
    assert all(v["items"] == feature for v in feats.values())  # one shared definition is exact
    for k in feats: feats[k] = {"type": "array", "items": {"$ref": "#/$defs/feature"}}
    schema = api_schema(canon)
    schema["$defs"] = {"feature": api_schema(feature)}
    return schema


def decode_tri_state(value, schema=OBSERVATION_SCHEMA, path="$"):
    """Wire observation -> canonical observation. Anything that is not exactly YES/NO/UNKNOWN where the canonical
    schema expects boolean-or-null fails closed (AI_SCHEMA_INVALID). All other checks are left to
    validate_observation(), which runs on the result unchanged."""
    if _is_nullable_boolean(schema):
        if isinstance(value, str) and value in TRI_STATE:
            return TRI_STATE[value]
        raise ProviderError("AI_SCHEMA_INVALID", "observation rejected by wire format",
                            {"errors": [f"{path}: expected YES/NO/UNKNOWN"]})
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        return {k: decode_tri_state(v, props[k], f"{path}.{k}") if k in props else v for k, v in value.items()}
    if isinstance(value, list) and "items" in schema:
        return [decode_tri_state(v, schema["items"], f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def count_union_parameters(schema):
    """Number of union-typed (anyOf / type-array) parameters in a schema, as the structured-output limit counts."""
    n = 1 if ("anyOf" in schema or isinstance(schema.get("type"), list)) else 0
    for v in (schema.get("properties") or {}).values(): n += count_union_parameters(v)
    if "items" in schema: n += count_union_parameters(schema["items"])
    for v in schema.get("anyOf") or []: n += count_union_parameters(v)
    for v in (schema.get("$defs") or {}).values(): n += count_union_parameters(v)
    return n




# ---------------------------------------------------------------- common connection
RAW_LIMIT = 20000          # characters of the model's raw text kept for inspection (model output only)
MAX_OUTPUT_TOKENS = 16000
MAX_UNION_PARAMETERS = 16  # Claude structured-output compiler limit reported by the API (wire schema stays under it)


def foundry_connection():
    """(endpoint root, key) shared by every deployment of the Foundry resource."""
    key = os.environ.get("TCP_FOUNDRY_API_KEY") or os.environ.get("ANTHROPIC_FOUNDRY_API_KEY")
    endpoint = os.environ.get("TCP_FOUNDRY_ENDPOINT")
    if not endpoint and os.environ.get("ANTHROPIC_FOUNDRY_BASE_URL"):
        u = urlsplit(os.environ["ANTHROPIC_FOUNDRY_BASE_URL"]); endpoint = f"{u.scheme}://{u.netloc}"
    if not endpoint and os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE"):
        endpoint = f"https://{os.environ['ANTHROPIC_FOUNDRY_RESOURCE']}.services.ai.azure.com"
    if not key: raise ProviderError("AI_CREDENTIALS_MISSING", "set TCP_FOUNDRY_API_KEY (or ANTHROPIC_FOUNDRY_API_KEY)")
    if not endpoint: raise ProviderError("AI_ENDPOINT_MISSING", "set TCP_FOUNDRY_ENDPOINT (or ANTHROPIC_FOUNDRY_BASE_URL)")
    return endpoint.rstrip("/"), key


class Reply:
    def __init__(self, text, model, request_id, usage, truncated=False):
        self.text = text; self.model = model; self.request_id = request_id; self.usage = usage; self.truncated = truncated


# ---------------------------------------------------------------- shared API error classifier
ERROR_TEXT_LIMIT = 2000    # characters of the API's own error text kept (key-like strings removed)
BILLING_MARKERS = ("billing", "quota", "credit", "payment", "spending limit", "insufficient_funds")
BILLING_CODE = "AI_BILLING_OR_QUOTA"
BILLING_MESSAGE = "Foundry billing / quota / credit problem - this is a billing issue, not a site problem"
STATUS_CODE = {401: "AI_AUTH_FAILED", 403: "AI_AUTH_FAILED", 404: "AI_MODEL_NOT_FOUND", 429: "AI_RATE_LIMITED",
               400: "AI_BAD_REQUEST"}


def classify_api_error(status, text, default_code=None):
    """ProviderError for a failed Foundry API call (both API families). Billing, quota and credit errors get their
    own code and a message that says so; the pipeline outcome stays the same (AI unavailable -> REVIEW_REQUIRED)."""
    text = redact(text, ERROR_TEXT_LIMIT) or (f"HTTP {status}" if status else "API error")
    details = {"http_status": status, "api_error_text": text}
    if any(m in text.lower() for m in BILLING_MARKERS):
        return ProviderError(BILLING_CODE, f"{BILLING_MESSAGE}: {text}", details)
    return ProviderError(default_code or STATUS_CODE.get(status, "AI_API_ERROR"), text, details)


# ---------------------------------------------------------------- API-family adapters (envelopes only)
class AnthropicMessagesAPI:
    """Anthropic Messages API on Foundry (Claude deployments)."""
    name = "anthropic_messages"
    CAPABILITIES = {"image_input": True, "structured_output": True, "usage_reporting": True,
                    "verified": "2026-10-16/18 live: image input, tri-state-v1 schema enforced, usage reported"}

    def send(self, endpoint, key, deployment, effort, parts, schema, system=SYSTEM_PROMPT):
        try:
            import anthropic
        except ImportError:
            raise ProviderError("AI_SDK_MISSING", "pip install anthropic")
        content = [{"type": "text", "text": v} if k == "text" else
                   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.standard_b64encode(v).decode()}} for k, v in parts]
        client = anthropic.AnthropicFoundry(api_key=key, base_url=endpoint + "/anthropic/")
        try:
            resp = client.messages.create(
                model=deployment, max_tokens=MAX_OUTPUT_TOKENS, system=system,
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": content}])
        except anthropic.AuthenticationError as e:
            raise classify_api_error(401, getattr(e, "message", None) or "Foundry authentication failed")
        except anthropic.PermissionDeniedError as e:
            raise classify_api_error(403, getattr(e, "message", None) or "Foundry key lacks access to this deployment")
        except anthropic.NotFoundError as e:
            raise classify_api_error(404, getattr(e, "message", None) or "Foundry deployment or endpoint not found")
        except anthropic.RateLimitError as e:
            raise classify_api_error(429, getattr(e, "message", None) or "Foundry rate limit")
        except anthropic.BadRequestError as e:
            raise classify_api_error(400, getattr(e, "message", None) or "bad request")
        except anthropic.APIStatusError as e:
            raise classify_api_error(e.status_code, getattr(e, "message", None) or f"HTTP {e.status_code}", "AI_API_ERROR")
        except anthropic.APIConnectionError:
            raise ProviderError("AI_CONNECTION_FAILED", "could not reach Foundry")
        if resp.stop_reason == "refusal":
            raise ProviderError("AI_REFUSAL", "model declined the request")
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
                 "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0}
        text = next((b.text for b in resp.content if b.type == "text"), None)
        return Reply(text, resp.model, getattr(resp, "_request_id", None), usage, resp.stop_reason == "max_tokens")


class OpenAIResponsesAPI:
    """OpenAI-compatible Responses API on Foundry (GPT deployments)."""
    name = "openai_responses"
    CAPABILITIES = {"image_input": True, "structured_output": True, "usage_reporting": True,
                    "verified": "2026-10-18 live (gpt-5.6-sol): input_image read, strict json_schema enforced, "
                                "full tri-state-v1 observation schema accepted, usage reported"}

    def send(self, endpoint, key, deployment, effort, parts, schema, system=SYSTEM_PROMPT):
        import requests
        content = [{"type": "input_text", "text": v} if k == "text" else
                   {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(v).decode(),
                    "detail": "high"} for k, v in parts]
        body = {"model": deployment, "instructions": system, "max_output_tokens": MAX_OUTPUT_TOKENS,
                "input": [{"role": "user", "content": content}],
                "text": {"format": {"type": "json_schema", "name": "tcp_observation", "schema": schema, "strict": True}}}
        if effort: body["reasoning"] = {"effort": effort}
        try:
            r = requests.post(endpoint + "/openai/v1/responses", json=body, timeout=(10, 600),
                              headers={"api-key": key, "Content-Type": "application/json", "User-Agent": "tcp-poc/0.2"})
        except requests.RequestException:
            raise ProviderError("AI_CONNECTION_FAILED", "could not reach Foundry")
        try: j = r.json()
        except ValueError: j = {}
        if r.status_code != 200:
            err = (j.get("error") or {}) if isinstance(j, dict) else {}
            text = err.get("message") if isinstance(err, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            if code and str(code) not in str(text or ""): text = f"{code}: {text}" if text else str(code)
            raise classify_api_error(r.status_code, text or getattr(r, "text", None) or f"HTTP {r.status_code}")
        items = [c for o in j.get("output") or [] if o.get("type") == "message" for c in o.get("content") or []]
        if any(c.get("type") == "refusal" for c in items):
            raise ProviderError("AI_REFUSAL", "model declined the request")
        text = "".join(c.get("text") or "" for c in items if c.get("type") == "output_text") or None
        u = j.get("usage") or {}
        usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                 "cache_read_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens") or 0,
                 "cache_creation_input_tokens": (u.get("input_tokens_details") or {}).get("cache_write_tokens") or 0,
                 "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0}
        return Reply(text, j.get("model"), j.get("id"), usage, j.get("status") == "incomplete")


APIS = {AnthropicMessagesAPI.name: AnthropicMessagesAPI, OpenAIResponsesAPI.name: OpenAIResponsesAPI}


# ---------------------------------------------------------------- profiles (non-secret registry)
PROFILES_PATH = os.path.join(CONFIG_DIR, "foundry_profiles.json")


def load_profiles(path=None):
    path = path or os.environ.get("TCP_FOUNDRY_PROFILES_FILE") or PROFILES_PATH
    if not os.path.isfile(path): return {"default_profile": None, "profiles": {}}
    with open(path, encoding="utf-8") as f: doc = json.load(f)
    doc.setdefault("profiles", {}); doc.setdefault("default_profile", None)
    return doc


def _deployment(p):
    return p.get("deployment") or (os.environ.get(p["deployment_env"]) if p.get("deployment_env") else None)


def profile_catalog():
    """Profiles for the UI: names, deployment, API family, availability. No secrets, no endpoint."""
    doc = load_profiles(); out = []
    for name, p in doc["profiles"].items():
        api = APIS.get(p.get("api"))
        enabled = p.get("enabled", True) is not False
        out.append({"name": name, "display_name": p.get("display_name") or name, "api": p.get("api"),
                    "backend": p.get("api"), "description": p.get("description"),
                    "deployment": p.get("deployment") or (("from " + p["deployment_env"]) if p.get("deployment_env") else None),
                    "effort": p.get("effort"), "enabled": enabled, "backend_implemented": api is not None,
                    "capabilities": getattr(api, "CAPABILITIES", None),
                    "available": api is not None and enabled, "default": name == doc.get("default_profile")})
    return out


# ---------------------------------------------------------------- request content (identical for every model)
MULTIVIEW_PROMPT = (
    "\nIMAGES 2-{n} are closer north-up views of the same place, given so details can be checked. Report every pixel "
    "position (image_x, image_y) and road_edges.traveled_way_width_px in IMAGE 1 pixels ({mpp:g} m per pixel): a width "
    "measured in another image converts as metres = pixels x that image's metres per pixel, then IMAGE 1 pixels = "
    "metres / {mpp:g}. LEFT/RIGHT mean the same for every image. Base each value and confidence on all images together.")


def _jpeg(image):
    buf = io.BytesIO(); image.save(buf, "JPEG", quality=88); return buf.getvalue()


def view_caption(k, view):
    """Application-computed facts about one extra view (not instructions)."""
    m = view["meta"]; W, H = m["width_pixels"], m["height_pixels"]; mpp = m["metres_per_pixel"]
    dx, dy = view["offset_m"]
    px, py = W / 2 - dx / mpp, H / 2 + dy / mpp  # work reference relative to this view's centre
    where = (f"the work reference is at pixel ({px:.0f},{py:.0f})" if 0 <= px < W and 0 <= py < H
             else "the work reference is outside this view")
    return (f"IMAGE {k} - {view['label']}: north-up, {W}x{H} px, {mpp:.3f} m per pixel "
            f"({W * mpp:.0f} m across), centre {dx:+.0f} m east and {dy:+.0f} m north of the work reference; {where}.")


def build_parts(image, context, views=None):
    """Ordered (kind, value) parts of the user message; single-resolution keeps the original [image, prompt]."""
    prompt = build_prompt(context) + "\n" + TRI_STATE_PROMPT
    if not views:
        return [("image", _jpeg(image)), ("text", prompt)]
    parts = [("text", "IMAGE 1 - overview (the image the facts below describe)."), ("image", _jpeg(image))]
    for k, v in enumerate(views, start=2):
        parts += [("text", view_caption(k, v)), ("image", _jpeg(v["image"]))]
    parts.append(("text", prompt + MULTIVIEW_PROMPT.format(n=len(views) + 1, mpp=context["metres_per_pixel"])))
    return parts


# ---------------------------------------------------------------- request debug dump (TCP_DEBUG_SENT=1)
DEBUG_SENT_ENV = "TCP_DEBUG_SENT"
DEBUG_SENT_DIR = os.path.join(PROJECT_ROOT, "debug_sent")


def debug_sent_enabled():
    return os.environ.get(DEBUG_SENT_ENV, "").strip() == "1"


def _write_text(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f: f.write(text)


def dump_sent(request, provider):
    """Write exactly what is sent to the model - request data only, never the response. Returns the folder."""
    from PIL import Image
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    folder = os.path.join(DEBUG_SENT_DIR, f"{stamp}_{request['mode']}")
    os.makedirs(folder, exist_ok=True)
    images, user = [], []
    for kind, value in request["parts"]:
        if kind == "image":
            name = f"image_{len(images) + 1:02d}.jpg"
            with open(os.path.join(folder, name), "wb") as f: f.write(value)
            with Image.open(io.BytesIO(value)) as im: w, h = im.size
            images.append({"file": name, "width_px": w, "height_px": h, "bytes": len(value),
                           "sha256": hashlib.sha256(value).hexdigest()})
            user.append(f"[{name}]")
        else:
            user.append(value)
    _write_text(folder, "system_prompt.txt", request["system"])
    _write_text(folder, "user_prompt.txt", "\n\n".join(user))
    _write_text(folder, "schema.json", json.dumps(request["schema"], indent=2, sort_keys=True))
    _write_text(folder, "meta.json", json.dumps({
        "mode": request["mode"], "model": provider.deployment, "profile": provider.profile, "api": provider.api,
        "effort": provider.effort, "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "images": images, "note": f"request data only ({DEBUG_SENT_ENV}=1); the model response is not stored"},
        indent=2, sort_keys=True))
    print(f"   WARNING: {DEBUG_SENT_ENV}=1 - the exact model request (images, prompts, schema) was written to {folder}",
          flush=True)
    return folder


# ---------------------------------------------------------------- provider (what the pipeline sees)
AGENT_MODES = ("agent_call1", "agent_call2")


class FoundryVisionProvider(VisionProvider):
    name = "foundry"
    supports_views = True
    supports_agent = True

    def __init__(self, profile=None):
        doc = load_profiles()
        self.profile = profile or os.environ.get("TCP_FOUNDRY_PROFILE") or doc.get("default_profile")
        self.profile_cfg = doc["profiles"].get(self.profile) if self.profile else None
        p = self.profile_cfg or {}
        self.deployment = _deployment(p) or (None if self.profile_cfg else os.environ.get("TCP_FOUNDRY_DEPLOYMENT"))
        self.api = (os.environ.get("TCP_FOUNDRY_API") or p.get("api") or AnthropicMessagesAPI.name).strip().lower()
        self.model = self.deployment
        self.effort = p.get("effort") or os.environ.get("TCP_AI_EFFORT", "high")

    def build_request(self, image, context, views=None, grounding=None):
        """{"mode", "system", "parts", "schema", "records"}: exactly what is sent, for every mode."""
        mode = (grounding or {}).get("mode") or "baseline"
        if mode in AGENT_MODES:
            from tcp_planner.ai import vision_agent as agent
            return agent.build_request(mode, image, context, views, grounding)
        if mode == "grounded_v2":
            from tcp_planner.ai import grounded_vision as grounded
            parts, schema, records = grounded.build(image, context, views, grounding.get("claims"))
            return {"mode": mode, "system": SYSTEM_PROMPT, "parts": parts, "schema": schema, "records": records}
        return {"mode": "baseline", "system": SYSTEM_PROMPT, "parts": build_parts(image, context, views),
                "schema": tri_state_schema(), "records": None}

    def request_fingerprint(self, image, context, views=None, grounding=None):
        """Hashes of the exact request (prompt text, schema, image bytes) plus model and profile: part of the AI
        evidence signature, so changing any of them forces a new model call on resume."""
        req = self.build_request(image, context, views, grounding)
        return {"prompt_sha256": sha256_hex("\x00".join([req["system"]] + [v for k, v in req["parts"] if k == "text"])),
                "schema_sha256": sha256_hex(canonical_json(req["schema"])),
                "images_sha256": sha256_hex("".join(hashlib.sha256(v).hexdigest() for k, v in req["parts"] if k == "image")),
                "model": self.deployment, "profile": self.profile, "api": self.api, "effort": self.effort}

    def analyze(self, image, context, views=None, grounding=None):
        """grounding=None -> baseline (unchanged). grounding={"mode": "grounded_v2", "geo_side", "claims"} -> grounded_v2.
        grounding={"mode": "agent_call1" | "agent_call2", ...} -> the two agent calls (src/tcp_planner/ai/vision_agent.py)."""
        if self.profile and self.profile_cfg is None:
            raise ProviderError("AI_PROFILE_UNKNOWN", f"unknown Foundry profile {self.profile!r}")
        if self.profile_cfg is not None and self.profile_cfg.get("enabled", True) is False:
            raise ProviderError("AI_PROFILE_DISABLED", f"Foundry profile {self.profile!r} is disabled")
        api = APIS.get(self.api)
        if api is None:
            raise ProviderError("AI_PROVIDER_UNKNOWN", f"unknown Foundry API {self.api!r}")
        endpoint, key = foundry_connection()
        if not self.deployment:
            raise ProviderError("AI_DEPLOYMENT_MISSING", "profile has no deployment")
        req = self.build_request(image, context, views, grounding)
        mode = req["mode"]
        dumped = dump_sent(req, self) if debug_sent_enabled() else None
        reply = api().send(endpoint, key, self.deployment, self.effort, req["parts"], req["schema"], system=req["system"])
        raw = {"raw_response": (reply.text or "")[:RAW_LIMIT], "usage": reply.usage}
        if reply.truncated: raise ProviderError("AI_TRUNCATED", "response hit the output limit", raw)
        if not reply.text: raise ProviderError("AI_EMPTY_RESPONSE", "no text returned", raw)
        try: wire = json.loads(reply.text)
        except ValueError: raise ProviderError("AI_SCHEMA_INVALID", "response is not JSON", raw)
        g_info = None
        try:
            if mode in AGENT_MODES:
                from tcp_planner.ai import vision_agent as agent
                observation, g_info = agent.decode_response(mode, wire, context, views)
                from tcp_planner.ai import grounded_vision as grounded
                g_info["checks"] = grounded.check(observation, g_info, grounding.get("geo_side"), grounding.get("claims"),
                                                  grounding.get("lane_width_plausible_m"))
                g_info.update(images=req["records"], claims=grounding.get("claims"))
            elif mode == "grounded_v2":
                from tcp_planner.ai import grounded_vision as grounded
                shaped, g_info = grounded.decode(wire, context, views)
                observation = decode_tri_state(shaped)
                g_info["checks"] = grounded.check(observation, g_info, grounding.get("geo_side"), grounding.get("claims"),
                                                  grounding.get("lane_width_plausible_m"))
                g_info.update(images=req["records"], annotation=grounded.ANNOTATION, claims=grounding.get("claims"))
            else:
                observation = decode_tri_state(wire)
        except ProviderError as e:
            e.details.update(raw); raise
        try: validated = validate_observation(observation)
        except ProviderError as e:
            e.details.update(raw); raise
        return {"observation": validated, "provider": self.name, "model": reply.model, "request_id": reply.request_id,
                "foundry_api": api.name, "wire_format": TRI_STATE_FORMAT, "profile": self.profile,
                "deployment": self.deployment, "raw_response": raw["raw_response"], "usage": reply.usage,
                "vision_mode": mode, "grounding": g_info, "debug_sent": dumped,
                "evidence_mode": "multi" if views else "single", "views": [v["role"] for v in views or []]}
