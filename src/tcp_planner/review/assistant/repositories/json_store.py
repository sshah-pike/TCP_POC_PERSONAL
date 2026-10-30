"""RecordStore on the S2 stores (files only, D-84).

<root>/<collection>/<id>.json             a record, write-once (ArtifactStore), content_sha256 verified on read
<root>/<collection>/<id>.events.jsonl     lifecycle events (StateStore stream: {seq, schema_version, event} per line)
<root>/<collection>/<id>/<name>           write-once blobs (ArtifactStore)
<root>/heads/<key>.state.json             lineage head pointer (StateStore record, compare-and-set)

Data written before S2 is still readable: event streams without the envelope and head files (heads/<key>.json) are read
as they are. A pre-S2 event stream can not be appended to (LegacyStreamReadOnly); a head is carried over by the first
compare-and-set.
"""
import json, os, re

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.storage import stores
from tcp_planner.storage.interfaces import (ArtifactExists, ArtifactMissing, StateExists, StaleHead, StorageError,
                                            media_type_for_key)
from tcp_planner.storage.local_fs import LocalFsArtifactStore
from .base import RecordStore, ImmutableExists, IntegrityError, LegacyStreamReadOnly

SAFE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
SCHEMA_VERSION = 1


def _safe(part):
    if not SAFE.match(part or "") or part in (".", ".."): raise ValueError(f"unsafe storage name {part!r}")
    return part


def record_hash(record):
    return sha256_hex(canonical_json({k: v for k, v in record.items() if k != "content_sha256"}))


class JsonStore(RecordStore):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.artifacts = LocalFsArtifactStore(self.root)
        self.state = stores._file_state(self.root)

    def _key(self, collection, record_id):
        return f"{_safe(collection)}/{_safe(record_id)}.json"

    def create(self, collection, record_id, record):
        rec = dict(record); rec["content_sha256"] = record_hash(rec)
        data = json.dumps(rec, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
        key = self._key(collection, record_id)
        if self.artifacts.stat(key) is not None: raise ImmutableExists(f"{collection}/{record_id} already exists")
        try: self.artifacts.put(key, data, "application/json")
        except ArtifactExists: raise ImmutableExists(f"{collection}/{record_id} already exists") from None
        return rec

    def get(self, collection, record_id):
        try: rec = json.loads(self.artifacts.get(self._key(collection, record_id)).decode("utf-8"))
        except (ArtifactMissing, ValueError):
            return None
        if rec.get("content_sha256") != record_hash(rec):
            raise IntegrityError(f"{collection}/{record_id} content hash mismatch")
        return rec

    def list(self, collection):
        ids = [k.split("/")[1][:-5] for k in self.artifacts.keys(_safe(collection))
               if k.count("/") == 1 and k.endswith(".json")]
        return [r for r in (self.get(collection, i) for i in ids) if r]

    # ------------------------------------------------------------------ events
    def _stream(self, collection, record_id):
        return f"{_safe(collection)}/{_safe(record_id)}"

    def _legacy_events(self, collection, record_id):
        """Read-only: a pre-S2 stream (one bare JSON event per line)."""
        path = os.path.join(self.root, collection, record_id + ".events.jsonl"); out = []
        try:
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    if ln.strip(): out.append(json.loads(ln))
        except OSError:
            pass
        return out

    def append_event(self, collection, record_id, event, durable=False):
        stream = self._stream(collection, record_id)
        try: self.state.append_event(stream, json.loads(json.dumps(event, default=str)), SCHEMA_VERSION, durable=durable)
        except StorageError as e:
            if self._legacy_events(collection, record_id) and "valid event" in str(e):
                raise LegacyStreamReadOnly(f"{collection}/{record_id} was written before the storage change; "
                                           "it can be read but not appended to") from e
            raise
        return event

    def events(self, collection, record_id):
        try: return [e["event"] for e in self.state.events(self._stream(collection, record_id))]
        except (KeyError, TypeError, StorageError):
            return self._legacy_events(collection, record_id)

    # ------------------------------------------------------------------ blobs
    def _blob_key(self, collection, record_id, name):
        return f"{_safe(collection)}/{_safe(record_id)}/{_safe(name)}"

    def put_blob(self, collection, record_id, name, data):
        key = self._blob_key(collection, record_id, name)
        if self.artifacts.stat(key) is not None: raise ImmutableExists(f"{collection}/{record_id}/{name} already exists")
        try: ref = self.artifacts.put(key, data, media_type_for_key(key))
        except ArtifactExists: raise ImmutableExists(f"{collection}/{record_id}/{name} already exists") from None
        return {"uri": ref.uri, "sha256": ref.sha256, "size_bytes": ref.size}

    def blob_path(self, collection, record_id, name):
        """Where the blob is on this machine, to open or serve it. Never persist this value (D-77): keep the uri."""
        return os.path.join(self.root, *self._blob_key(collection, record_id, name).split("/"))

    # ------------------------------------------------------------------ heads
    def _legacy_head(self, key):
        try:
            with open(os.path.join(self.root, "heads", _safe(key) + ".json"), encoding="utf-8") as f: return json.load(f)
        except (OSError, ValueError):
            return None

    def head(self, key):
        rec = self.state.get(f"heads/{_safe(key)}")
        return rec.value if rec is not None else self._legacy_head(key)

    def compare_and_set_head(self, key, expected, new):
        skey = f"heads/{_safe(key)}"
        rec = self.state.get(skey)
        cur = rec.value if rec is not None else self._legacy_head(key)
        if (cur or {}).get("value") != expected: return False
        doc = {"key": key, "value": new, "previous": expected}
        try:
            if rec is None: self.state.put_new(skey, doc, SCHEMA_VERSION)
            else: self.state.compare_and_set(skey, rec.version, doc, SCHEMA_VERSION)
        except (StateExists, StaleHead):
            return False  # another writer moved the head first
        return True
