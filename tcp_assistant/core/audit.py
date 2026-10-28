"""Append-only, hash-chained audit log.

audits/<YYYY-MM-DD>/<stream>.jsonl   stream = conversation id, or "system"
Each event: event_hash = sha256(canonical JSON without event_hash); prev_event_hash links the file's chain.
Full user text is NEVER written here (only conversation_id / message_id / message_sha256 / canon version).
Consequential events are fsync'd; a failed write raises AUDIT_WRITE_FAILED so the caller does not act.
"""
import contextlib, datetime, json, os, re, threading, time

from tcp_planner.contracts import canonical_json, sha256_hex, redact
from ..flags import data_dir
from .canonical import now_iso, CANON_VERSION
from .errors import AssistantError
from .identity import NA

_LOCK = threading.Lock()
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
    def __init__(self, root=None):
        self.root = os.path.join(root or data_dir(), "audits")

    def _file(self, stream):
        if not STREAM_RE.match(stream or ""): stream = "system"
        day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.root, day, stream + ".jsonl")

    @staticmethod
    def _last_hash(path):
        """Hash of the file's real last event (read every time: other processes may append to the same file)."""
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END); size = f.tell(); block = b""; pos = size
                while pos > 0 and block.count(b"\n") < 2:
                    step = min(65536, pos); pos -= step; f.seek(pos); block = f.read(step) + block
        except OSError:
            return None
        lines = [ln for ln in block.splitlines() if ln.strip()]
        return json.loads(lines[-1]).get("event_hash") if lines else None

    @staticmethod
    @contextlib.contextmanager
    def _file_lock(path):
        """Cross-process exclusive lock on <file>.lock (Windows msvcrt / POSIX fcntl), plus the in-process lock."""
        with _LOCK, open(path + ".lock", "a+b") as lf:
            if os.name == "nt":
                import msvcrt
                lf.seek(0)
                for _ in range(1000):
                    try: msvcrt.locking(lf.fileno(), msvcrt.LK_NBLCK, 1); break
                    except OSError: time.sleep(0.01)
                else:
                    raise OSError("audit lock timeout")
                try: yield
                finally:
                    lf.seek(0); msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try: yield
                finally: fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def write(self, event_type, identity=None, stream=None, consequential=False, **fields):
        ev = {"schema": "tcp-audit-event-v1", "event_type": event_type, "timestamp": now_iso(),
              "identity": identity.audit_fields() if identity is not None else {"subject_id": NA},
              "canonicalization_version": CANON_VERSION, "consequential": bool(consequential)}
        ev.update(_scrub(fields))
        path = self._file(stream or fields.get("conversation_id") or "system")
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._file_lock(path):
                ev["prev_event_hash"] = self._last_hash(path)
                ev["event_hash"] = sha256_hex(canonical_json(ev))
                line = json.dumps(ev, sort_keys=True, ensure_ascii=False, default=str) + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line); f.flush()
                    if consequential: os.fsync(f.fileno())
        except (OSError, TypeError, ValueError) as e:
            raise AssistantError("AUDIT_WRITE_FAILED", "The action was not performed because it could not be audited.",
                                 500, recoverable=True, actions=["RETRY"], details={"reason": type(e).__name__})
        return ev

    def read(self, stream=None):
        out = []
        if not os.path.isdir(self.root): return out
        for day in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, day)
            for name in sorted(os.listdir(d)):
                if not name.endswith(".jsonl") or (stream and name != stream + ".jsonl"): continue
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    out += [json.loads(ln) for ln in f if ln.strip()]
        return out

    @staticmethod
    def verify_chain(events):
        prev = None
        for ev in events:
            body = {k: v for k, v in ev.items() if k != "event_hash"}
            if ev.get("prev_event_hash") != prev or sha256_hex(canonical_json(body)) != ev.get("event_hash"): return False
            prev = ev["event_hash"]
        return True
