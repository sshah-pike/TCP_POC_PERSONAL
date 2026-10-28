"""In-memory fakes of the storage interfaces, for tests and as a second adapter for the contract suite."""
import hashlib, io, json, threading

from tcp_planner.storage.interfaces import (ArtifactStore, ArtifactRef, ArtifactExists, ArtifactMissing, IntegrityError,
                                            StateStore, StateRecord, StateExists, StateMissing, StaleHead, StorageError,
                                            validate_key, media_type_for_key, checked_media_type, _uri)


def _under(key, prefix):
    return not prefix or key == prefix or key.startswith(prefix + "/")


class InMemoryArtifactStore(ArtifactStore):
    def __init__(self): self._d = {}; self._lock = threading.Lock()

    def put(self, key, data, media_type):
        data = bytes(data); checked_media_type(validate_key(key), media_type)
        with self._lock:
            if key in self._d and self._d[key] != data: raise ArtifactExists(f"{key} already holds different bytes")
            self._d.setdefault(key, data)
        return ArtifactRef(key, hashlib.sha256(data).hexdigest(), len(data), media_type_for_key(key))

    def get(self, ref_or_uri):
        key = _uri(ref_or_uri)
        if key not in self._d: raise ArtifactMissing(key)
        data = self._d[key]
        if isinstance(ref_or_uri, ArtifactRef) and hashlib.sha256(data).hexdigest() != ref_or_uri.sha256:
            raise IntegrityError(f"{key}: sha256 does not match the reference")
        return data

    def open(self, ref_or_uri): return io.BytesIO(self.get(ref_or_uri))

    def stat(self, key):
        d = self._d.get(validate_key(key))
        return None if d is None else ArtifactRef(key, hashlib.sha256(d).hexdigest(), len(d), media_type_for_key(key))

    def list(self, prefix=""):
        if prefix: validate_key(prefix)
        return [self.stat(k) for k in sorted(self._d) if _under(k, prefix)]


class InMemoryStateStore(StateStore):
    def __init__(self): self._s = {}; self._e = {}; self._lock = threading.Lock()

    @staticmethod
    def _copy(v):
        if not isinstance(v, dict): raise StorageError("state values must be JSON objects")
        return json.loads(json.dumps(v, sort_keys=True))

    def get(self, key):
        r = self._s.get(validate_key(key))
        return StateRecord(key, r[0], r[1], self._copy(r[2])) if r else None

    def put_new(self, key, value, schema_version):
        validate_key(key); v = self._copy(value)
        with self._lock:
            if key in self._s: raise StateExists(key)
            self._s[key] = (1, int(schema_version), v)
        return StateRecord(key, 1, int(schema_version), self._copy(v))

    def compare_and_set(self, key, expected_version, value, schema_version):
        validate_key(key); v = self._copy(value)
        with self._lock:
            if key not in self._s: raise StateMissing(key)
            cur = self._s[key][0]
            if cur != expected_version: raise StaleHead(f"{key}: expected version {expected_version}, found {cur}")
            self._s[key] = (cur + 1, int(schema_version), v)
        return StateRecord(key, cur + 1, int(schema_version), self._copy(v))

    def list(self, prefix=""):
        if prefix: validate_key(prefix)
        return [self.get(k) for k in sorted(self._s) if _under(k, prefix)]

    def append_event(self, stream, event, schema_version):
        validate_key(stream); ev = self._copy(event)
        with self._lock:
            lst = self._e.setdefault(stream, []); lst.append((int(schema_version), ev)); return len(lst)

    def events(self, stream, after=0):
        return [{"seq": i, "schema_version": sv, "event": self._copy(ev)}
                for i, (sv, ev) in enumerate(self._e.get(validate_key(stream), []), start=1) if i > after]
