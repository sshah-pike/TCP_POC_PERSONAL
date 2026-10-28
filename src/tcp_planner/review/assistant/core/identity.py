"""Identity: IdentityProvider interface, local POC provider (dropdown selection, no credentials) and opaque sessions.

The browser never asserts an identity per request. It selects a configured local identity once; the backend issues an
opaque random session token and stores only its SHA-256. Every request resolves the token to an identity server-side.
EntraIdentityProvider is a placeholder: subject mapping is decided inside it later.
"""
import abc, datetime, hashlib, json, os, re, secrets, threading

from ..flags import CONFIG_DIR, data_dir
from .errors import AssistantError, unauthenticated

ROLES = ("SME_REVIEWER", "AUDITOR", "ADMIN")
NA = "N/A"
SESSION_TTL_HOURS = 8
SUBJECT_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
FORBIDDEN_KEYS = ("password", "passwd", "secret", "token", "credential", "hash", "key")


class Identity(dict):
    """Production-oriented identity fields; unavailable fields are "N/A"."""

    @property
    def subject_id(self): return self["subject_id"]

    @property
    def roles(self): return tuple(self["roles"])

    def audit_fields(self):
        return {k: self.get(k, NA) for k in ("subject_id", "display_name", "roles", "identity_provider",
                                             "authentication_status", "tenant_id", "entra_object_id", "upn",
                                             "session_id")}


class IdentityProvider(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def list_identities(self): ...

    @abc.abstractmethod
    def identity(self, subject_id, session_id): ...


def users_file():
    return os.environ.get("TCP_ASSISTANT_USERS_FILE") or os.path.join(CONFIG_DIR, "users.local.json")


class LocalIdentityProvider(IdentityProvider):
    """Reads config/assistant/users.local.json (not committed). Contains no credentials."""
    name = "LOCAL_POC"

    def _load(self):
        try:
            with open(users_file(), encoding="utf-8") as f: doc = json.load(f)
        except (OSError, ValueError):
            return []
        out = []
        for u in doc.get("users") or []:
            if not isinstance(u, dict) or any(k.lower() in FORBIDDEN_KEYS or any(b in k.lower() for b in FORBIDDEN_KEYS)
                                              for k in u):
                continue  # entries that look like credentials are ignored, never used
            sid = str(u.get("subject_id") or "")
            roles = [r for r in u.get("roles") or [] if r in ROLES]
            if SUBJECT_RE.match(sid) and roles:
                out.append({"subject_id": sid, "display_name": str(u.get("display_name") or sid)[:80], "roles": roles})
        return out

    def list_identities(self):
        return self._load()

    def identity(self, subject_id, session_id):
        u = next((x for x in self._load() if x["subject_id"] == subject_id), None)
        if u is None: return None
        return Identity(subject_id=u["subject_id"], display_name=u["display_name"], roles=list(u["roles"]),
                        identity_provider=self.name, authentication_status="LOCAL_SELECTION_SESSION",
                        tenant_id=NA, entra_object_id=NA, upn=NA, session_id=session_id)


class EntraIdentityProvider(IdentityProvider):
    """Future: Microsoft Entra ID. Subject mapping (oid/upn -> subject_id) is defined here when implemented."""
    name = "ENTRA_ID"

    def list_identities(self):
        raise AssistantError("IDENTITY_PROVIDER_NOT_IMPLEMENTED", "Entra ID sign-in is not implemented in this POC.", 501)

    def identity(self, subject_id, session_id):
        raise AssistantError("IDENTITY_PROVIDER_NOT_IMPLEMENTED", "Entra ID sign-in is not implemented in this POC.", 501)


def provider():
    return LocalIdentityProvider()


# ---------------------------------------------------------------- opaque sessions (only the token hash is stored)
_LOCK = threading.Lock()


def _sessions_dir():
    return os.path.join(data_dir(), "sessions")


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def create_session(subject_id, idp=None):
    idp = idp or provider()
    if not SUBJECT_RE.match(str(subject_id or "")): raise AssistantError("IDENTITY_UNKNOWN", "Unknown identity.", 400)
    session_id = "sess-" + secrets.token_hex(8)
    ident = idp.identity(subject_id, session_id)
    if ident is None: raise AssistantError("IDENTITY_UNKNOWN", "Unknown identity.", 400)
    token = secrets.token_urlsafe(32)
    rec = {"session_id": session_id, "subject_id": subject_id, "identity_provider": idp.name,
           "created_at": _now().isoformat(timespec="seconds"),
           "expires_at": (_now() + datetime.timedelta(hours=SESSION_TTL_HOURS)).isoformat(timespec="seconds")}
    with _LOCK:
        os.makedirs(_sessions_dir(), exist_ok=True)
        path = os.path.join(_sessions_dir(), _token_hash(token) + ".json")
        with open(path, "x", encoding="utf-8") as f: json.dump(rec, f, sort_keys=True)
    return token, ident


def resolve(token, idp=None):
    if not token or not isinstance(token, str) or len(token) > 200: raise unauthenticated()
    path = os.path.join(_sessions_dir(), _token_hash(token) + ".json")
    try:
        with open(path, encoding="utf-8") as f: rec = json.load(f)
    except (OSError, ValueError):
        raise unauthenticated()
    if datetime.datetime.fromisoformat(rec["expires_at"]) < _now():
        end_session(token); raise unauthenticated()
    ident = (idp or provider()).identity(rec["subject_id"], rec["session_id"])
    if ident is None: raise unauthenticated()  # identity removed from configuration
    return ident


def end_session(token):
    try: os.remove(os.path.join(_sessions_dir(), _token_hash(token) + ".json"))
    except OSError: pass
