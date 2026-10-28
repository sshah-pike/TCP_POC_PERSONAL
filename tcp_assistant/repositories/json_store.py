"""JSON-file implementation of RecordStore.

<root>/<collection>/<id>.json          create-only (O_EXCL), content_sha256 verified on read
<root>/<collection>/<id>.events.jsonl  append-only lifecycle events
<root>/<collection>/<id>/<name>        create-only blobs (artifact files)
<root>/heads/<key>.json                lineage head pointer (compare-and-set under a process lock)
"""
import hashlib, json, os, re, threading

from tcp_planner.contracts import canonical_json, sha256_hex
from .base import RecordStore, ImmutableExists, IntegrityError

SAFE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_LOCK = threading.RLock()


def _safe(part):
    if not SAFE.match(part or "") or part in (".", ".."): raise ValueError(f"unsafe storage name {part!r}")
    return part


def record_hash(record):
    return sha256_hex(canonical_json({k: v for k, v in record.items() if k != "content_sha256"}))


class JsonStore(RecordStore):
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def _dir(self, collection):
        return os.path.join(self.root, _safe(collection))

    def _path(self, collection, record_id, suffix=".json"):
        return os.path.join(self._dir(collection), _safe(record_id) + suffix)

    def create(self, collection, record_id, record):
        rec = dict(record); rec["content_sha256"] = record_hash(rec)
        data = json.dumps(rec, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        path = self._path(collection, record_id)
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
            except FileExistsError:
                raise ImmutableExists(f"{collection}/{record_id} already exists")
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        return rec

    def get(self, collection, record_id):
        try:
            with open(self._path(collection, record_id), encoding="utf-8") as f: rec = json.load(f)
        except (OSError, ValueError):
            return None
        if rec.get("content_sha256") != record_hash(rec):
            raise IntegrityError(f"{collection}/{record_id} content hash mismatch")
        return rec

    def list(self, collection):
        try: names = sorted(n for n in os.listdir(self._dir(collection)) if n.endswith(".json"))
        except OSError: return []
        return [r for r in (self.get(collection, n[:-5]) for n in names) if r]

    def append_event(self, collection, record_id, event, durable=False):
        line = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str) + "\n"
        path = self._path(collection, record_id, ".events.jsonl")
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line); f.flush()
                if durable: os.fsync(f.fileno())
        return event

    def events(self, collection, record_id):
        out = []
        try:
            with open(self._path(collection, record_id, ".events.jsonl"), encoding="utf-8") as f:
                for ln in f:
                    if ln.strip(): out.append(json.loads(ln))
        except OSError:
            pass
        return out

    def put_blob(self, collection, record_id, name, data):
        d = os.path.join(self._dir(collection), _safe(record_id)); path = os.path.join(d, _safe(name))
        with _LOCK:
            os.makedirs(d, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o644)
            except FileExistsError:
                raise ImmutableExists(f"{collection}/{record_id}/{name} already exists")
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

    def blob_path(self, collection, record_id, name):
        return os.path.join(self._dir(collection), _safe(record_id), _safe(name))

    def head(self, key):
        try:
            with open(os.path.join(self.root, "heads", _safe(key) + ".json"), encoding="utf-8") as f: return json.load(f)
        except (OSError, ValueError):
            return None

    def compare_and_set_head(self, key, expected, new):
        path = os.path.join(self.root, "heads", _safe(key) + ".json")
        with _LOCK:
            cur = self.head(key)
            if (cur or {}).get("value") != expected: return False
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"key": key, "value": new, "previous": expected}, f, sort_keys=True); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
