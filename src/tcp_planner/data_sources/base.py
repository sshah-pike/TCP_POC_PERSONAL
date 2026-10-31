"""Allow-listed, fingerprinted client for external data sources (S6 commit 6; D-53, D-62, D-63).

Every request goes through `SourceClient.request`:
  1. the source must be enabled in config/data_sources.json and the URL's host must be one of its hosts - otherwise the request is
     refused BEFORE any network use (SourceError SOURCE_HOST_NOT_ALLOWED / SOURCE_DISABLED / SOURCE_UNKNOWN);
  2. the request is fingerprinted (source, method, URL, sorted parameters, body): the fingerprint is how a recorded response is found;
  3. fixture hook: when `hook` is given and holds the fingerprint the recorded response is returned and the network is not touched.
     In replay mode (hook with no transport) a missing fixture is an error. With a `transport` (the owner's recording run, TCP_LIVE=1)
     the live response is saved through the hook;
  4. the response size is bounded (max_bytes of the source); the call is recorded as a SourceCall (source, host, fingerprint, time,
     licence note, attribute names, artifact ref) and the raw response can be stored write-once in an ArtifactStore.
A descriptive User-Agent from config/data_sources.json is sent with every live request. No source ever fills a mandatory start field.
"""
import base64, datetime, json, os
from typing import NamedTuple, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from tcp_planner.config.settings import CONFIG_DIR
from tcp_planner.contracts import TcpError, canonical_json, sha256_hex

SCHEMA_VERSION = "1"
PATH = os.path.join(CONFIG_DIR, "data_sources.json")


class SourceError(TcpError): pass


def load_sources(path=None):
    with open(path or PATH, encoding="utf-8") as f: return json.load(f)


class SourceCall(BaseModel):
    """What was asked of a source and when. Stored with the facts that came from it (trace)."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = SCHEMA_VERSION
    source_id: str
    host: str
    request_fingerprint: str
    retrieved_at: str
    license_note: str
    attribute_names: tuple = ()
    artifact_ref: Optional[dict] = None       # {uri, sha256, size, media_type} of the stored raw response
    replayed: bool = False


class SourceResponse(NamedTuple):
    call: SourceCall
    content: bytes
    status: int


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def request_record(source_id, method, url, params=None, body=None):
    """The canonical request a fixture is keyed by. Parameters are sorted; nothing secret belongs here (keys go in headers)."""
    return {"kind": "source", "source_id": source_id, "method": method.upper(), "url": url,
            "params": {k: str(v) for k, v in sorted((params or {}).items())}, "body": body}


def request_fingerprint(record):
    return sha256_hex(canonical_json(record))


class SourceClient:
    def __init__(self, sources=None, hook=None, transport=None, store=None, now=None):
        """sources: the parsed allow list (default config/data_sources.json). hook: fixture adapter with load(record) and, for
        recording, save(record, doc). transport: callable(method, url, params, body, headers, timeout) -> (status, content bytes);
        None means replay only. store: an ArtifactStore for the raw responses."""
        self.cfg = sources or load_sources(); self.hook, self.transport, self.store = hook, transport, store
        self._now = now or _now; self.calls = []

    # ------------------------------------------------------------ the allow list
    def check(self, source_id, url):
        """(source entry, host). Raises SourceError, with no network use, for an unknown or disabled source or a host not listed."""
        src = self.cfg["sources"].get(source_id)
        if src is None: raise SourceError("SOURCE_UNKNOWN", f"{source_id!r} is not in the data source allow list")
        if not src.get("enabled") or not src.get("hosts"):
            raise SourceError("SOURCE_DISABLED", f"{source_id} is not enabled ({src.get('status') or 'disabled'})")
        parts = urlsplit(url); host = (parts.hostname or "").lower()
        if parts.scheme != "https": raise SourceError("SOURCE_HOST_NOT_ALLOWED", f"{url!r}: only https requests are allowed")
        if host not in [h.lower() for h in src["hosts"]]:
            raise SourceError("SOURCE_HOST_NOT_ALLOWED", f"host {host!r} is not allowed for {source_id}", {"host": host, "allowed": src["hosts"]})
        return src, host

    # ------------------------------------------------------------ the request
    def request(self, source_id, url, params=None, *, method="GET", body=None, attribute_names=(), headers=None):
        src, host = self.check(source_id, url)
        rec = request_record(source_id, method, url, params, body); fp = request_fingerprint(rec)
        replayed = False
        if self.hook is not None and self.hook.has(fp):
            doc = self.hook.load(rec)
            status, content, retrieved = doc["status"], base64.b64decode(doc["body_b64"]), doc["retrieved_at"]; replayed = True
        elif self.transport is None:
            if self.hook is not None: self.hook.load(rec)      # raises the hook's own "never recorded" error
            raise SourceError("SOURCE_NO_TRANSPORT", f"{source_id}: no recorded response and no live transport (replay never calls the network)")
        else:
            h = {"User-Agent": self.cfg["user_agent"], **(headers or {})}
            try:
                status, content = self.transport(method.upper(), url, dict(params or {}), body, h, src.get("timeout_s"))
            except Exception as e:        # a timeout or a dropped connection: named, never a bare traceback, and never recorded
                kind = "SOURCE_TIMEOUT" if "timeout" in type(e).__name__.lower() else "SOURCE_NETWORK_ERROR"
                raise SourceError(kind, f"{source_id}: {type(e).__name__} after the {src.get('timeout_s')} s read timeout" if kind == "SOURCE_TIMEOUT"
                                  else f"{source_id}: {type(e).__name__}", {"exception": type(e).__name__, "timeout_s": src.get("timeout_s")})
            retrieved = self._now()
            if not 200 <= status < 300:                         # an error answer is never recorded as a fixture
                raise SourceError("SOURCE_HTTP_ERROR", f"{source_id}: HTTP {status}", {"http_status": status, "body": content[:500].decode("utf-8", "replace")})
            if len(content) > src["max_bytes"]:
                raise SourceError("SOURCE_RESPONSE_TOO_LARGE", f"{source_id}: {len(content)} bytes exceeds the limit of {src['max_bytes']}")
            if self.hook is not None:
                self.hook.save(rec, {"status": status, "body_b64": base64.b64encode(content).decode(), "retrieved_at": retrieved})
        if len(content) > src["max_bytes"]:
            raise SourceError("SOURCE_RESPONSE_TOO_LARGE", f"{source_id}: {len(content)} bytes exceeds the limit of {src['max_bytes']}")
        ref = None
        if self.store is not None:
            r = self.store.put(f"sources/{source_id}/{fp}", content, "application/octet-stream")
            ref = {"uri": r.uri, "sha256": r.sha256, "size": r.size, "media_type": r.media_type}
        call = SourceCall(source_id=source_id, host=host, request_fingerprint=fp, retrieved_at=retrieved, license_note=src["license_note"],
                          attribute_names=tuple(attribute_names), artifact_ref=ref, replayed=replayed)
        self.calls.append(call)
        return SourceResponse(call, content, status)


def requests_transport(method, url, params, body, headers, timeout):
    """The live transport (the owner's recording run only; tests block the network). Certificate checks stay on."""
    import requests
    r = requests.request(method, url, params=params, data=body, headers=headers, timeout=(5, timeout or 30))
    return r.status_code, r.content
