"""Call 1 of site understanding (S6): the field table, the response parser and the work_location mapping.

The AI only observes: it returns facts (strings) and image positions (pixels), never a length (D-64). Code decides.
Parsing rule: a missing or malformed fact becomes UNKNOWN with a fixed reason; enum values are compared without case;
evidence is stored whole (over the word cap it is flagged, never cut) and never parsed for numbers.
The schema, prompt and request builder join this module in the next commit.
"""
import json, math
from typing import NamedTuple, Optional
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr, ValidationError
from tcp_planner.site_model.facts import SiteFact, Mark, Question, Candidate, question_id
from tcp_planner.site_model.site_config import call1_setting, load_site_config

SOURCE_AI = "AI"
EVIDENCE_CODES = ("not_visible", "occluded", "low_resolution", "ambiguous")   # P2': fixed reason for UNKNOWN evidence
MARK_FEATURES = ("road_edge_left", "road_edge_right", "lane_line", "shoulder_edge", "work_point", "curb")
COMPASS = ("N", "S", "E", "W")


class Row(NamedTuple):
    name: str               # wire field name
    kind: str               # bool | count | enum | text
    values: tuple           # allowed values for enum, else ()
    registry_id: Optional[str]
    unit: Optional[str]     # registry unit; filled by code, never read from the model


# The one list of call 1 fields (S6 Q6 A: the 18 spike fields). registry_id None = CONTEXT_ONLY: shown to the SME, no rule reads it.
FIELDS = (
    Row("work_location", "enum", ("ROADWAY", "SHOULDER", "BEYOND_SHOULDER", "SIDEWALK", "UNKNOWN"), "work_location", None),
    Row("work_side", "enum", COMPASS + ("UNKNOWN",), None, None),
    Row("lanes_per_direction", "count", (), "lanes_per_direction", "count"),
    Row("oneway", "bool", (), "oneway", None),
    Row("shoulder_present", "bool", (), "shoulder_present", None),
    Row("divided_highway", "bool", (), "divided_highway", None),
    Row("median_work", "bool", (), "median_work", None),
    Row("bicycle_lane_present", "bool", (), "bicycle_lane_present", None),
    Row("sidewalk_present", "bool", (), None, None),
    Row("sidewalk_side", "enum", COMPASS + ("BOTH", "NONE", "UNKNOWN"), None, None),
    Row("parking_present", "bool", (), None, None),
    Row("bus_stop_present", "bool", (), None, None),
    Row("driveway_present", "bool", (), None, None),
    Row("crosswalk_present", "bool", (), None, None),
    Row("intersection_in_view", "bool", (), None, None),
    Row("grade_crossing_present", "bool", (), None, None),   # registry fact waits for the FRA source (session 2)
    Row("obstructions", "text", (), None, None),
    Row("approaching_lanes_one", "bool", (), "approaching_lanes_one", None),
)
BY_NAME = {r.name: r for r in FIELDS}

# Registry fields that list AI as a source and are deliberately NOT asked in call 1 (call 2, S7, or an SME question).
NOT_IN_CALL1 = {
    "work_side": "registry values LEFT/RIGHT stay an SME question; the compass work_side here is context only",
    "behind_barrier": "TA-specific: call 2",
    "opposite_shoulder_suitable": "TA-specific: call 2",
    "closed_lane_side": "TA-specific: call 2",
    "lanes_closed_count": "TA-specific: call 2",
    "positive_barrier_present": "TA-specific: call 2 (with code and map data)",
    "ramp_present": "TA-specific: call 2 (with code and map data)",
}


# ---------------------------------------------------------------- wire models (extra fields rejected)
class _WireFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: StrictStr
    value: StrictStr
    unit: StrictStr
    status: StrictStr
    confidence: StrictInt | StrictFloat
    evidence: StrictStr


class _WireMark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: StrictStr
    points: StrictStr
    status: StrictStr
    evidence: StrictStr


class Observation(BaseModel):
    """One parsed fact, still the model's word: value is the normalized wire value."""
    model_config = ConfigDict(frozen=True)
    field: str
    value: Optional[object] = None
    status: str                      # RESOLVED | UNKNOWN
    reason_code: Optional[str] = None
    confidence: Optional[float] = None
    evidence: str = ""
    flags: tuple = ()


class Call1Result(NamedTuple):
    observations: dict   # field name -> Observation, one per table row (UNKNOWN when missing or malformed)
    marks: tuple         # Mark records
    notes: tuple         # parse notes: dropped items, unknown fields, over-long evidence (audit, never silent)


def _unknown(name, reason, evidence="", confidence=None, flags=()):
    return Observation(field=name, status="UNKNOWN", reason_code=reason, evidence=evidence, confidence=confidence, flags=tuple(flags))


def _valid_conf(c):
    return isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and 0 <= c <= 1


def _norm_value(row, text):
    """Normalized value, or raise ValueError. 'UNKNOWN' (any case) is handled by the caller."""
    t = text.strip()
    if row.kind == "bool":
        if t.lower() in ("true", "false"): return t.lower() == "true"
        raise ValueError("not a boolean")
    if row.kind == "count":
        try: f = float(t)
        except ValueError: raise ValueError("not a number")
        if not math.isfinite(f) or f != int(f) or f < 0: raise ValueError("not a count")
        return int(f)
    if row.kind == "enum":
        if t.upper() in row.values: return t.upper()
        raise ValueError("not in enum")
    if not t: raise ValueError("empty text")
    return t


def _observation(row, w, max_words):
    flags = []
    if max_words and len(w.evidence.split()) > max_words: flags.append("EVIDENCE_OVER_15_WORDS")
    if w.unit.strip().lower() != row.kind: flags.append("UNIT_MISMATCH")
    conf = float(w.confidence) if _valid_conf(w.confidence) else None
    status = w.status.strip().upper()
    ev_code = w.evidence.strip().lower()
    if status == "CONFLICT":
        return _unknown(row.name, "ai_conflict", w.evidence, conf, flags + ["AI_CONFLICT"])
    if status not in ("RESOLVED", "UNKNOWN"):
        return _unknown(row.name, "malformed", w.evidence, conf, flags)
    if status == "UNKNOWN" or w.value.strip().upper() == "UNKNOWN":
        return _unknown(row.name, ev_code if ev_code in EVIDENCE_CODES else "not_stated", w.evidence, conf, flags)
    if conf is None: return _unknown(row.name, "malformed", w.evidence, None, flags)
    try: value = _norm_value(row, w.value)
    except ValueError: return _unknown(row.name, "malformed", w.evidence, conf, flags)
    return Observation(field=row.name, value=value, status="RESOLVED", confidence=conf, evidence=w.evidence, flags=tuple(flags))


def parse_points(text, image_size=None):
    """'x1,y1;x2,y2' -> ((x, y), ...) or None when malformed. Points must be finite and, when the image size is known, inside it."""
    pts = []
    for part in text.split(";"):
        xy = part.strip().split(",")
        if len(xy) != 2: return None
        try: x, y = float(xy[0]), float(xy[1])
        except ValueError: return None
        if not (math.isfinite(x) and math.isfinite(y)) or x < 0 or y < 0: return None
        if image_size and (x > image_size[0] or y > image_size[1]): return None
        pts.append((x, y))
    return tuple(pts) or None


def _mark(w, image_size):
    feature, status = w.feature.strip().lower(), w.status.strip().upper()
    if feature not in MARK_FEATURES or status not in ("RESOLVED", "UNKNOWN"): return None
    if status == "UNKNOWN": return Mark(feature=feature, status="UNKNOWN", reason_code="not_stated", evidence=w.evidence)
    pts = parse_points(w.points, image_size)
    if pts is None: return Mark(feature=feature, status="UNKNOWN", reason_code="malformed", evidence=w.evidence)
    return Mark(feature=feature, points=pts, status="RESOLVED", evidence=w.evidence)


def parse_call1(response, image_size=None, cfg=None):
    """Parse the model's JSON (text or already decoded) into observations and marks. Never raises on model content."""
    max_words = call1_setting("evidence_max_words", cfg)
    notes, found, bad = [], {}, set()
    try: doc = json.loads(response) if isinstance(response, (str, bytes)) else response
    except ValueError: doc = None
    if not isinstance(doc, dict) or not isinstance(doc.get("facts"), list) or not isinstance(doc.get("marks"), list):
        notes.append("response is not an object with a facts list and a marks list")
        return Call1Result({r.name: _unknown(r.name, "malformed") for r in FIELDS}, (), tuple(notes))
    for i, item in enumerate(doc["facts"]):
        raw = item.get("field") if isinstance(item, dict) else None
        name = raw.strip().lower() if isinstance(raw, str) else None
        row = BY_NAME.get(name)
        if row is None: notes.append(f"facts[{i}]: unknown or missing field {raw!r} dropped"); continue
        try: w = _WireFact.model_validate(item)
        except ValidationError: notes.append(f"facts[{i}] {name}: malformed"); bad.add(name); continue
        if name in found: bad.add(name); notes.append(f"facts[{i}] {name}: duplicate"); continue
        found[name] = _observation(row, w, max_words)
        if "EVIDENCE_OVER_15_WORDS" in found[name].flags: notes.append(f"{name}: evidence over {max_words} words, stored whole")
    obs = {}
    for r in FIELDS:
        if r.name in found and not (r.name in bad): obs[r.name] = found[r.name]
        elif r.name in bad: obs[r.name] = _unknown(r.name, "duplicate" if r.name in found else "malformed")
        else: obs[r.name] = _unknown(r.name, "missing")
    marks = []
    for i, item in enumerate(doc["marks"]):
        try: m = _mark(_WireMark.model_validate(item), image_size)
        except ValidationError: m = None
        if m is None: notes.append(f"marks[{i}]: malformed, dropped")
        else: marks.append(m)
    return Call1Result(obs, tuple(marks), tuple(notes))


# ---------------------------------------------------------------- observations -> site facts
IN_LANE, ON_SHOULDER, BEYOND_SHOULDER = "IN_LANE", "ON_SHOULDER_OR_ENCROACHING", "BEYOND_SHOULDER"
MARKS_AGREE, MARKS_MISSING, MARKS_DISAGREE = "AGREE", "MISSING", "DISAGREE"   # work point vs edge/lane marks (computed in code)


def _fact(row, obs, flags=(), value=None, status=None, reason=None):
    st = status or obs.status
    fl = tuple(dict.fromkeys(list(obs.flags) + list(flags) + (["CONTEXT_ONLY"] if row.registry_id is None else [])))
    return SiteFact(field=row.name, registry_id=row.registry_id, value=obs.value if value is None and st == "RESOLVED" else value,
                    unit=row.unit, confidence=obs.confidence, source=SOURCE_AI, evidence=obs.evidence, status=st,
                    reason_code=reason or (obs.reason_code if st == "UNKNOWN" else None), flags=fl)


def map_work_location(obs, marks_check, floor):
    """(SiteFact, Question or None). The AI value (ROADWAY, SHOULDER, BEYOND_SHOULDER, SIDEWALK) becomes a registry value
    only when confidence reaches the floor; ROADWAY/SHOULDER also need the marks (agree: plain; missing: flagged AI-only;
    disagree: UNKNOWN plus a conflict question). BEYOND_SHOULDER maps straight through. SIDEWALK has no registry value."""
    row = BY_NAME["work_location"]
    cand = (Candidate(source=SOURCE_AI, value=obs.value),) if obs.value is not None else ()

    def unknown(reason, question=None):
        f = _fact(row, obs, status="UNKNOWN", reason=reason).model_copy(update={"candidates": cand})
        return f, question
    if obs.status != "RESOLVED": return unknown(obs.reason_code)
    if obs.confidence is None or obs.confidence < floor: return unknown("low_confidence")
    if obs.value == "BEYOND_SHOULDER": return _fact(row, obs, value=BEYOND_SHOULDER), None
    if obs.value == "SIDEWALK": return unknown("no_registry_value")
    value = IN_LANE if obs.value == "ROADWAY" else ON_SHOULDER
    if marks_check == MARKS_AGREE: return _fact(row, obs, value=value), None
    if marks_check == MARKS_MISSING: return _fact(row, obs, value=value, flags=("AI_ONLY_UNCONFIRMED",)), None
    q = Question(question_id=question_id("WORK_LOCATION_CONFLICT", "work_location"), kind="WORK_LOCATION_CONFLICT",
                 reason=f"the AI reads the work location as {obs.value}; the marks disagree",
                 options=(IN_LANE, ON_SHOULDER, BEYOND_SHOULDER), reveals=("work_location",))
    return unknown("source_disagreement", q)


def to_site_facts(result, work_location_marks=MARKS_MISSING, cfg=None):
    """(facts, questions) for every table row. Safety-critical facts that are RESOLVED carry NEEDS_SECOND_SOURCE until the
    OSM cross-check (fusion) decides them: no rule input can read them before that."""
    cfg = cfg or load_site_config()
    critical = set(call1_setting("safety_critical_fields", cfg))
    floor = call1_setting("work_location_min_confidence", cfg)
    facts, questions = [], []
    for row in FIELDS:
        obs = result.observations[row.name]
        if row.name == "work_location":
            f, q = map_work_location(obs, work_location_marks, floor)
            if q: questions.append(q)
        else:
            f = _fact(row, obs, flags=("NEEDS_SECOND_SOURCE",) if row.name in critical and obs.status == "RESOLVED" else ())
        facts.append(f)
    return facts, questions


# ---------------------------------------------------------------- request: schema, prompt, builder (provider-neutral)
SCHEMA_NAME = "tcp_site_facts"      # the name given to a strict Responses API schema; the Messages API ignores it
MODE = "site_call1"
WIRE_UNITS = ("bool", "count", "enum", "text", "none")

# The prompt text lives in prompts/ (registry, hash verified on load). Wording history: spike text, then one change after STOP 2
# (the edge sentence no longer says "facing north"). Version 1 is the text the nine recorded calls used.
SYSTEM_ID, USER_ID, PROMPT_VERSION = "call1_system", "call1_user", 1
SYSTEM_SHA256 = "5e731eab10a7455ac1ace58f3f30520bc0fb0dc2d0aa4eb397cd1b57bed7266b"
INSTRUCTIONS_SHA256 = "81b8f01912963d536b1c1b14d702f0abd6bcc062f512522ad3729f49bcbef988"


def load_prompts(version=PROMPT_VERSION):
    """(system, user template) of one prompt version, from the registry. Version 1 is checked against its pinned hashes."""
    from tcp_planner.ai.prompt_registry import load_prompt
    pins = (SYSTEM_SHA256, INSTRUCTIONS_SHA256) if version == PROMPT_VERSION else (None, None)
    return load_prompt(SYSTEM_ID, version, expected_sha256=pins[0]), load_prompt(USER_ID, version, expected_sha256=pins[1])


SYSTEM = load_prompts()[0].text
INSTRUCTIONS = load_prompts()[1].text


def wire_schema():
    """Structured-output schema for call 1. Every property required, additionalProperties false, no union, no
    minimum/maximum, no $ref: the plain subset that both API families accept."""
    def obj(props): return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}
    facts = obj({"field": {"type": "string", "enum": [r.name for r in FIELDS]}, "value": {"type": "string"},
                 "unit": {"type": "string", "enum": list(WIRE_UNITS)},
                 "status": {"type": "string", "enum": ["RESOLVED", "UNKNOWN", "CONFLICT"]},
                 "confidence": {"type": "number"}, "evidence": {"type": "string"}})
    marks = obj({"feature": {"type": "string", "enum": list(MARK_FEATURES)}, "points": {"type": "string"},
                 "status": {"type": "string", "enum": ["RESOLVED", "UNKNOWN"]}, "evidence": {"type": "string"}})
    return obj({"facts": {"type": "array", "items": facts}, "marks": {"type": "array", "items": marks}})


def build_request(image_bytes, record, cfg=None):
    """Request in the provider's shape: {"mode", "system", "parts", "schema", "schema_name", "image"}.
    `image_bytes` and `record` come from imagery.prepare.resize_for_model: the bytes hashed are the bytes sent."""
    w, h = record["sent_px"]
    text = INSTRUCTIONS.format(w=w, h=h, mpp=record["mpp_sent"], cx=w // 2, cy=h // 2,
                               words=call1_setting("evidence_max_words", cfg))
    return {"mode": MODE, "system": SYSTEM, "parts": [("image", image_bytes), ("text", text)], "schema": wire_schema(),
            "schema_name": SCHEMA_NAME, "image": record}


def request_fingerprint(request, profile):
    """Hashes of the exact request (prompt, schema, image bytes) plus model, profile, API and effort; `profile` is a
    FoundryVisionProvider."""
    import hashlib
    from tcp_planner.contracts import sha256_hex, canonical_json
    return {"prompt_sha256": sha256_hex("\x00".join([request["system"]] + [v for k, v in request["parts"] if k == "text"])),
            "schema_sha256": sha256_hex(canonical_json(request["schema"])), "schema_name": request["schema_name"],
            "images_sha256": sha256_hex("".join(hashlib.sha256(v).hexdigest() for k, v in request["parts"] if k == "image")),
            "model": profile.deployment, "profile": profile.profile, "api": profile.api, "effort": profile.effort}


def profile_max_image_px(profile):
    """Image limit of a profile from config/foundry_profiles.json (its own max_image_px, else default_max_image_px)."""
    from tcp_planner.ai.foundry_provider import load_profiles
    doc = load_profiles(); own = (profile.profile_cfg or {}).get("max_image_px")
    return own if own is not None else doc["default_max_image_px"]


def wire_body(profile, request):
    """Exact body for the profile's API family (the Messages API keyword arguments, or the Responses JSON body)."""
    from tcp_planner.ai.foundry_provider import APIS
    api = APIS.get(profile.api)
    if api is None: raise ValueError(f"unknown Foundry API {profile.api!r}")
    return api.build_body(profile.deployment, profile.effort, request["parts"], request["schema"], request["system"],
                          request["schema_name"])


def describe_body(body):
    """Copy of a request body for printing: every embedded image shown as size and SHA-256, nothing else changed."""
    import base64, hashlib
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "base64" and "data" in n:
                raw = base64.b64decode(n["data"])
                return {**{k: walk(v) for k, v in n.items() if k != "data"}, "data": f"<image {len(raw)} bytes sha256 {hashlib.sha256(raw).hexdigest()}>"}
            return {k: walk(v) for k, v in n.items()}
        if isinstance(n, list): return [walk(v) for v in n]
        if isinstance(n, str) and n.startswith("data:image/"):
            raw = base64.b64decode(n.split(",", 1)[1])
            return f"<image {len(raw)} bytes sha256 {hashlib.sha256(raw).hexdigest()}>"
        return n
    return walk(body)


def send_call1(profile, request, send=None):
    """One call 1 to the profile's deployment. Returns the provider Reply; a failed call raises ProviderError with
    http_status and the API's own error text in .details (key-like strings removed). `send` is a fake for tests."""
    from tcp_planner.ai.foundry_provider import APIS, foundry_connection
    if send is None:
        api = APIS.get(profile.api)
        if api is None: raise ValueError(f"unknown Foundry API {profile.api!r}")
        endpoint, key = foundry_connection()
        send = lambda *a, **k: api().send(endpoint, key, *a, **k)
    return send(profile.deployment, profile.effort, request["parts"], request["schema"], system=request["system"],
                schema_name=request["schema_name"])


def schema_problems(response, result):
    """Why a call 1 response is not fully schema valid (empty list = valid): not JSON, a dropped or malformed item,
    a missing or duplicate field. Used for the model comparison; the parser itself never raises."""
    problems = [n for n in result.notes if "evidence over" not in n]
    problems += [f"{o.field}: {o.reason_code}" for o in result.observations.values() if o.reason_code in ("malformed", "missing", "duplicate")]
    return list(dict.fromkeys(problems))
