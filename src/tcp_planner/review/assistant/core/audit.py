"""Append-only, hash-chained audit log.

audits/<YYYY-MM-DD>/<stream>.events.jsonl   stream = conversation id, or "system"
Each event: event_hash = sha256(canonical JSON without event_hash); prev_event_hash links the file's chain.
Full user text is NEVER written here (only conversation_id / message_id / message_sha256 / canon version).
Consequential events are fsync'd; a failed write raises AUDIT_WRITE_FAILED so the caller does not act.
"""
import datetime, json, os, re

from tcp_planner.contracts import canonical_json, sha256_hex, redact
from tcp_planner.storage import stores
from tcp_planner.storage.interfaces import StorageError
from ..flags import data_dir
from .canonical import now_iso, CANON_VERSION
from .errors import AssistantError
from .identity import NA

STREAM_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SECRET_KEY_RE = re.compile(r"(?i)(api[_-]?key|subscription[_-]?key|access[_-]?token|auth[_-]?token|session[_-]?token|"
                           r"bearer|secret|password|passwd|credential|authorization|^token$|^key$)")


def _scrub(obj):
    """Defence in depth: drop secret-like keys and redact strings."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if SECRET_KEY_RE.search(str(k)) and k not in ("message_sha256",) else _scrub(v))
                for k, v in obj.items()}
    if isinstance(obj, list): return [_scrub(v) for v in obj]
    if isinstance(obj, str): return redact(obj, 2000)
    return obj


class AuditService:
    """The log lives in the data directory as one event stream per day and conversation: audits/<day>/<stream> (a state
    stream file, <stream>.events.jsonl). The stream's write lock covers "read the last hash, append", so the chain can
    not fork even with several processes writing. Pre-S2 files (<stream>.jsonl) are read as they are and the first new
    event continues their chain."""

    def __init__(self, root=None):
        self.data = os.path.abspath(root or data_dir())
        self.root = os.path.join(self.data, "audits")
        self.state = stores._file_state(self.data)

    @staticmethod
    def _stream_name(stream):
        return stream if STREAM_RE.match(stream or "") else "system"

    def _legacy_path(self, day, stream):
        return os.path.join(self.root, day, stream + ".jsonl")

    def _legacy_events(self, day, stream):
        try:
            with open(self._legacy_path(day, stream), encoding="utf-8") as f: return [json.loads(ln) for ln in f if ln.strip()]
        except OSError:
            return []

    def write(self, event_type, identity=None, stream=None, consequential=False, **fields):
        base = {"schema": "tcp-audit-event-v1", "event_type": event_type, "timestamp": now_iso(),
                "identity": identity.audit_fields() if identity is not None else {"subject_id": NA},
                "canonicalization_version": CANON_VERSION, "consequential": bool(consequential)}
        base.update(_scrub(fields))
        name = self._stream_name(stream or fields.get("conversation_id") or "system")
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

        built = {}

        def build(last):
            ev = dict(base)
            if last is not None: ev["prev_event_hash"] = last.get("event_hash")
            else:
                legacy = self._legacy_events(day, name)
                ev["prev_event_hash"] = legacy[-1].get("event_hash") if legacy else None
            ev["event_hash"] = sha256_hex(canonical_json(ev))
            built["ev"] = json.loads(json.dumps(ev, sort_keys=True, ensure_ascii=False, default=str))
            return built["ev"]
        try:
            self.state.append_event_after(f"audits/{day}/{name}", build, 1, durable=bool(consequential))
        except (OSError, TypeError, ValueError, StorageError) as e:
            raise AssistantError("AUDIT_WRITE_FAILED", "The action was not performed because it could not be audited.",
                                 500, recoverable=True, actions=["RETRY"], details={"reason": type(e).__name__})
        return built["ev"]

    def read(self, stream=None):
        names = {}  # (day, stream) -> events: pre-S2 file first, then the stream
        if os.path.isdir(self.root):
            for day in sorted(os.listdir(self.root)):
                d = os.path.join(self.root, day)
                if not os.path.isdir(d): continue
                for n in sorted(os.listdir(d)):
                    if n.endswith(".jsonl") and not n.endswith(".events.jsonl") and (not stream or n[:-6] == stream):
                        names[(day, n[:-6])] = self._legacy_events(day, n[:-6])
        for full in self.state.streams("audits"):
            _a, day, name = full.split("/", 2)
            if not stream or name == stream:
                names.setdefault((day, name), []).extend(e["event"] for e in self.state.events(full))
        return [ev for key in sorted(names) for ev in names[key]]

    @staticmethod
    def verify_chain(events):
        prev = None
        for ev in events:
            body = {k: v for k, v in ev.items() if k != "event_hash"}
            if ev.get("prev_event_hash") != prev or sha256_hex(canonical_json(body)) != ev.get("event_hash"): return False
            prev = ev["event_hash"]
        return True
