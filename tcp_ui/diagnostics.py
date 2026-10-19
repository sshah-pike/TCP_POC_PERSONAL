"""Sanitized technical diagnostics for provider failures (observability only).

The pipeline keeps its stable reason codes (e.g. MAP_REQUEST_FAILED). This module turns the underlying
exception - which the providers keep as the implicit __context__ of the TcpError they raise - into a
category plus a sanitized message for the UI. Nothing here feeds back into any pipeline decision.
"""
import os, re

MAX_MESSAGE = 400
_SENSITIVE_PARAM = re.compile(
    r"(?i)\b(api[_-]?key|subscription[_-]?key|access[_-]?token|token|key|sig|signature|password|secret|auth\w*|code)"
    r"=[^&\s'\"),]+")
_URL = re.compile(r"(?i)\b(https?://[^\s'\"()]+)")
_PATH_QUERY = re.compile(r"(?<=url: )(\S+?)\?\S*")         # urllib3: "... with url: /path?query (Caused by ...)"
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KEY_LIKE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_SECRET_ENV = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)")


def _secret_values():
    return [v for k, v in os.environ.items() if _SECRET_ENV.search(k) and v and len(v) >= 8]


def _strip_url(m):
    url = m.group(1)
    base = re.split(r"[?#]", url, maxsplit=1)[0]
    return base + ("?<query removed>" if base != url else "")


def sanitize(text, limit=MAX_MESSAGE):
    """Remove query strings, credential-like parameters, bearer tokens and known secret values."""
    s = str(text or "")
    for v in _secret_values():
        s = s.replace(v, "<redacted>")
    s = _URL.sub(_strip_url, s)
    s = _PATH_QUERY.sub(lambda m: m.group(1) + "?<query removed>", s)
    s = _SENSITIVE_PARAM.sub(lambda m: m.group(1) + "=<redacted>", s)
    s = _BEARER.sub("Bearer <redacted>", s)
    s = _KEY_LIKE.sub("<redacted>", s)
    return s[:limit] if limit else s


def sanitize_obj(obj):
    """Sanitize every string inside a JSON-like structure (keeps structure; no truncation)."""
    if isinstance(obj, str): return sanitize(obj, limit=None)
    if isinstance(obj, dict): return {k: sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)): return [sanitize_obj(v) for v in obj]
    return obj


def _category(exc):
    """Category for an exception raised by the requests/urllib3 stack (checked most specific first)."""
    try:
        import requests
        from requests import exceptions as rx
    except ImportError:  # pragma: no cover - requests is a pipeline dependency
        requests = None
    text = str(exc).lower()
    if requests is not None:
        if isinstance(exc, rx.SSLError):
            return "TLS_CERTIFICATE_VERIFY_FAILED" if "certificate verify failed" in text else "TLS_ERROR"
        if isinstance(exc, rx.ProxyError): return "PROXY_ERROR"
        if isinstance(exc, rx.ConnectTimeout): return "CONNECT_TIMEOUT"
        if isinstance(exc, rx.ReadTimeout): return "READ_TIMEOUT"
        if isinstance(exc, rx.Timeout): return "TIMEOUT"
        if isinstance(exc, rx.ConnectionError):
            dns = ("nameresolutionerror", "getaddrinfo failed", "name or service not known", "nodename nor servname")
            return "DNS_FAILURE" if any(d in text for d in dns) else "CONNECTION_FAILED"
        if isinstance(exc, rx.HTTPError): return "HTTP_ERROR"
        if isinstance(exc, rx.RequestException): return "REQUEST_FAILED"
    if type(exc).__name__ in ("UnidentifiedImageError", "JSONDecodeError", "ParseError", "DecodeError"):
        return "RESPONSE_PARSE_FAILED"
    return "UNKNOWN_PROVIDER_ERROR"


def describe(error, provider=None, duration_ms=None):
    """Sanitized diagnostic dict for an exception raised out of a provider call.

    `error` is what the provider raised: a TcpError (MapProviderError / OsmError) whose __context__ is the
    original library exception, or an unexpected exception that escaped the provider."""
    code = getattr(error, "code", None)
    details = getattr(error, "details", None) or {}
    cause = error.__context__ if code else error
    d = {"provider": provider, "pipeline_error_code": code, "duration_ms": duration_ms, "http_status": None}
    if code and cause is not None:
        d.update(category=_category(cause), exception_type=f"{type(cause).__module__}.{type(cause).__name__}",
                 message=sanitize(cause))
        resp = getattr(cause, "response", None)
        if resp is not None: d["http_status"] = getattr(resp, "status_code", None)
        if d["http_status"] is None: d["http_status"] = details.get("http_status")  # e.g. undecodable image body
        if details.get("content_type"): d["message"] += f" (content-type {sanitize(details['content_type'])})"
    elif code:  # the provider decided from the response itself (no library exception)
        status = details.get("http_status")
        d.update(http_status=status, exception_type=f"{type(error).__module__}.{type(error).__name__}",
                 message=sanitize(getattr(error, "message", error)))
        if code.endswith("_CREDENTIALS_MISSING"):
            d["category"] = "CREDENTIALS_MISSING"
        elif code in ("MAP_GEOREFERENCE_MISMATCH", "MAP_NO_COVERAGE", "OSM_NO_ROAD"):
            d["category"] = "INVALID_PROVIDER_RESPONSE"
        elif status is not None and status != 200:
            d["category"] = "HTTP_ERROR"
        elif status == 200:
            d["category"] = "INVALID_IMAGERY_RESPONSE"
            if details.get("content_type"): d["message"] += f" (content-type {sanitize(details['content_type'])})"
        else:
            d["category"] = "UNKNOWN_PROVIDER_ERROR"
    else:
        d.update(category=_category(error), exception_type=f"{type(error).__module__}.{type(error).__name__}",
                 message=sanitize(error))
    return d
