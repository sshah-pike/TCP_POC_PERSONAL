"""HTTP routes for /api/assistant/* (mounted by src/tcp_planner/web_api/server.py). Returns (status, kind, body); kind = json | file.

Feature flag off: only GET /api/assistant/status answers (enabled=false); every other route is unavailable and no
assistant storage is created.
"""
from . import flags
from .core import identity as idn
from .core.errors import AssistantError, disabled

SESSION_HEADER = "X-TCP-Session"
ROUTES = []


def route(method, pattern, auth=True):
    def deco(fn):
        ROUTES.append((method, tuple(pattern.strip("/").split("/")) if pattern else (), fn, auth)); return fn
    return deco


def _match(pattern, parts):
    if len(pattern) != len(parts): return None
    params = {}
    for p, v in zip(pattern, parts):
        if p.startswith("{"): params[p[1:-1]] = v
        elif p != v: return None
    return params


def dispatch(method, parts, query, payload, headers):
    """parts: path segments after /api/assistant."""
    try:
        if not flags.enabled():
            if method == "GET" and parts == ["status"]:
                return 200, "json", {"enabled": False, "state": "DISABLED"}
            raise disabled()
        for m, pattern, fn, auth in ROUTES:
            if m != method: continue
            params = _match(pattern, parts)
            if params is None: continue
            ident = idn.resolve(headers.get(SESSION_HEADER)) if auth else None
            out = fn(ident=ident, payload=payload or {}, query=query or {}, token=headers.get(SESSION_HEADER), **params)
            if isinstance(out, tuple): return out
            return 200, "json", out
        return 404, "json", {"error": "not found", "error_code": "NOT_FOUND"}
    except AssistantError as e:
        return e.status, "json", {"error": e.message, **e.to_dict()}


def _svc():
    from .services.container import container
    return container()


# ---------------------------------------------------------------- phase 1: status, identity, sessions
@route("GET", "status", auth=False)
def status(**_):
    from .core.profile import public_profiles
    return {"enabled": True, "state": "ENABLED", "profiles": public_profiles()}


@route("GET", "identities", auth=False)
def identities(**_):
    ids = idn.provider().list_identities()
    return {"identity_provider": idn.provider().name, "identities": ids,
            "configured": bool(ids), "note": None if ids else "Create config/assistant/users.local.json from users.example.json."}


@route("POST", "sessions", auth=False)
def create_session(payload, **_):
    token, ident = idn.create_session(payload.get("subject_id"))
    _svc().audit.write("SESSION_CREATED", ident, consequential=True)
    return 201, "json", {"session_token": token, "identity": dict(ident)}


@route("GET", "session")
def whoami(ident, **_):
    from .core import authz
    return {"identity": dict(ident), "permissions": sorted(authz.permissions(ident))}


@route("POST", "sessions/end")
def end_session(ident, token, **_):
    idn.end_session(token)
    _svc().audit.write("SESSION_ENDED", ident)
    return {"ended": True}


from tcp_planner.review.assistant import review_routes as api_review  # noqa: E402,F401  (registers review routes)
