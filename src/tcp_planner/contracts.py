"""Shared contracts: decisions, reason codes, errors, canonical JSON and hashing.

Every pipeline artifact (ProjectGeometry, SiteModel, EligibilityResult, PlanModel) is a
plain JSON-serialisable dict so it can be written, hashed and diffed without custom encoders.
"""
import copy, hashlib, json, math, os, re

APP_VERSION = "tcp-poc 0.2.0"
FT = 0.3048  # unit conversion only (international foot), not a regulatory value

# ---------- decisions ----------
SUPPORTED_AUTO = "SUPPORTED_AUTO"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
UNSUPPORTED_POC = "UNSUPPORTED_POC"

UNSUPPORTED_MESSAGE = ("This POC currently processes only two-lane, two-way, undivided conventional roads "
                       "with work beyond the shoulder and no lane or pedestrian impact.")
REVIEW_MESSAGE = ("Automatic generation stopped: one or more safety-critical site facts are missing, "
                  "low-confidence or conflicting. A person must resolve them before a draft can be generated.")

# ---------- field resolution status ----------
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
CONFLICT = "CONFLICT"
LOW_CONFIDENCE = "LOW_CONFIDENCE"


class TcpError(Exception):
    """Structured failure. `code` is a stable reason code; `details` is JSON-safe context."""
    def __init__(self, code, message, details=None):
        super().__init__(f"{code}: {message}")
        self.code = code; self.message = message; self.details = details or {}

    def to_dict(self):
        return {"error_code": self.code, "message": self.message, "details": self.details}


class InputRejected(TcpError):
    """Project input cannot produce a single usable work reference."""
    def __init__(self, reason_codes, message, details=None):
        super().__init__(reason_codes[0], message, details)
        self.reason_codes = list(reason_codes)


class RulePackError(TcpError): pass
class ProviderError(TcpError): pass
class MapProviderError(TcpError): pass
class OsmError(TcpError): pass
class DwtRenderError(TcpError): pass


# ---------- canonical JSON / hashing ----------
VOLATILE_KEYS = frozenset({"retrieved_at", "generated_at", "duration_ms"})


def _strip(obj, drop):
    if isinstance(obj, dict):
        return {k: _strip(v, drop) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [_strip(v, drop) for v in obj]
    if isinstance(obj, float):
        if not math.isfinite(obj): raise ValueError("non-finite float cannot be canonicalised")
        return obj
    return obj


def canonical_json(obj, drop=()):
    """Sorted keys, compact separators, UTF-8. `drop` keys are removed at every depth."""
    return json.dumps(_strip(obj, frozenset(drop)), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def sha256_hex(data):
    if isinstance(data, str): data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(obj, drop=()):
    return sha256_hex(canonical_json(obj, drop=set(drop) | VOLATILE_KEYS))


def r(value, nd):
    """Round floats for reproducible artifacts; passes None through."""
    return None if value is None else round(float(value), nd)


def deep_copy(obj):
    return copy.deepcopy(obj)


def field(value, status, confidence=None, observations=None, source=None, note=None):
    """A fused SiteModel attribute. Observations from each source are always preserved."""
    out = {"value": value, "status": status, "confidence": r(confidence, 3),
           "observations": observations or []}
    if source is not None: out["source"] = source
    if note: out["note"] = note
    return out


# ---------- key-like strings removed from provider error text ----------
_SECRET_ENV = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)")
_REDACT = (
    (re.compile(r"(?i)\b(api[_-]?key|subscription[_-]?key|access[_-]?token|token|key|sig|signature|password|secret|auth\w*|code)"
                r"=[^&\s'\"),]+"), r"\1=<redacted>"),
    (re.compile(r"(?i)(https?://[^\s'\"()?#]+)[?#][^\s'\"()]*"), r"\1?<query removed>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer <redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "<redacted>"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "<redacted>"),  # long key-like tokens (Azure/Foundry keys)
)


def redact(text, limit=None):
    """Provider error text with known secret values and key-like strings removed (optionally truncated)."""
    s = str(text or "")
    for k, v in os.environ.items():
        if _SECRET_ENV.search(k) and v and len(v) >= 8: s = s.replace(v, "<redacted>")
    for pattern, repl in _REDACT: s = pattern.sub(repl, s)
    return s[:limit] if limit else s


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
