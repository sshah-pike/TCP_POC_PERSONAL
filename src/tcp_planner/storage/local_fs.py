"""ArtifactStore on the local filesystem. Keys map to files under one root; nothing outside the root is reachable."""
import hashlib, io, os, tempfile

from tcp_planner.storage.interfaces import (ArtifactStore, ArtifactRef, ArtifactExists, ArtifactMissing, IntegrityError,
                                            validate_key, validate_artifact_key, RESERVED_SUFFIXES, media_type_for_key, checked_media_type, _uri)

TMP_PREFIX = ".tmp-"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class LocalFsArtifactStore(ArtifactStore):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.root, *validate_artifact_key(key).split("/"))

    def _ref(self, key, data):
        return ArtifactRef(key, _sha(data), len(data), media_type_for_key(key))

    def put(self, key, data, media_type):
        data = bytes(data)
        checked_media_type(validate_artifact_key(key), media_type)
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=TMP_PREFIX)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            try:
                os.link(tmp, path)  # fails if the key exists: write-once even with concurrent writers
            except FileExistsError:
                with open(path, "rb") as f: existing = f.read()
                if existing != data: raise ArtifactExists(f"{key} already holds different bytes") from None
        finally:
            try: os.remove(tmp)
            except OSError: pass
        return self._ref(key, data)

    def _read(self, ref_or_uri):
        key = _uri(ref_or_uri)
        try:
            with open(self._path(key), "rb") as f: data = f.read()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            raise ArtifactMissing(key) from None
        if isinstance(ref_or_uri, ArtifactRef) and _sha(data) != ref_or_uri.sha256:
            raise IntegrityError(f"{key}: sha256 does not match the reference")
        return data

    def get(self, ref_or_uri):
        return self._read(ref_or_uri)

    def open(self, ref_or_uri):
        return io.BytesIO(self._read(ref_or_uri))

    def stat(self, key):
        path = self._path(key)
        if not os.path.isfile(path): return None
        with open(path, "rb") as f: return self._ref(key, f.read())

    def keys(self, prefix=""):
        base = self._path(prefix) if prefix else self.root
        files = [base] if os.path.isfile(base) else [os.path.join(d, n) for d, _s, ns in os.walk(base) for n in ns]
        out = []
        for p in files:
            name = os.path.basename(p)
            if name.startswith(TMP_PREFIX) or name.endswith(RESERVED_SUFFIXES) or ".lock.stale-" in name: continue
            out.append(os.path.relpath(p, self.root).replace(os.sep, "/"))
        return sorted(out)

    def list(self, prefix=""):
        out = []
        for key in self.keys(prefix):
            with open(self._path(key), "rb") as f: out.append(self._ref(key, f.read()))
        return out
