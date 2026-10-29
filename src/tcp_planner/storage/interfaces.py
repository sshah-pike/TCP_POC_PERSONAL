"""Storage interfaces (ADR-006, ADR-007). Local adapters only; the cloud is out of the MVP (D-40).

All reads and writes of run data go through these three interfaces. Persisted data never holds a raw path: it holds an
ArtifactRef {uri, sha256, size, media_type}, where uri is a store-relative POSIX key such as
"<run_id>/output/plan.json" that only the store resolves.

- ArtifactStore: write-once blobs, addressed by key, hash-verified on read.
- StateStore: versioned records with compare-and-set heads, and append-only event streams.
- RulePackStore: interface only here; S4 implements it.
"""
import abc, contextlib, re
from dataclasses import dataclass


class StorageError(Exception):
    code = "STORAGE_ERROR"


class InvalidKey(StorageError): code = "INVALID_KEY"
class ArtifactExists(StorageError): code = "ARTIFACT_EXISTS"          # same key, different bytes
class ArtifactMissing(StorageError): code = "ARTIFACT_MISSING"
class IntegrityError(StorageError): code = "INTEGRITY_ERROR"          # stored bytes do not match the recorded sha256
class StateExists(StorageError): code = "STATE_EXISTS"
class StateMissing(StorageError): code = "STATE_MISSING"
class StaleHead(StorageError): code = "STALE_HEAD"                    # compare-and-set found a different version
class SchemaVersionError(StorageError): code = "SCHEMA_VERSION"


_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ +=@~-]*$")


def validate_key(key):
    """A key is a relative POSIX path of safe segments. No leading or trailing slash, no '..', no backslash, no drive."""
    if not isinstance(key, str) or not key or key != key.strip():
        raise InvalidKey(f"invalid key {key!r}")
    segs = key.split("/")
    for s in segs:
        if s in (".", "..") or not _SEGMENT_RE.match(s) or s.endswith(".") or s.endswith(" "):
            raise InvalidKey(f"invalid key segment {s!r} in {key!r}")
    return key


# Suffixes the file StateStore uses for its own files. An artifact key may not end in one, so the two stores can share
# a folder without ever colliding.
RESERVED_SUFFIXES = (".state.json", ".events.jsonl", ".lock")


def validate_artifact_key(key):
    validate_key(key)
    if key.endswith(RESERVED_SUFFIXES):
        raise InvalidKey(f"artifact key {key!r} ends in a suffix reserved for state files")
    return key


_MEDIA_TYPES = {".json": "application/json", ".jsonl": "application/x-ndjson", ".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".pdf": "application/pdf", ".dxf": "image/vnd.dxf", ".dwg": "image/vnd.dwg",
                ".kml": "application/vnd.google-earth.kml+xml", ".txt": "text/plain", ".log": "text/plain"}
DEFAULT_MEDIA_TYPE = "application/octet-stream"


def media_type_for_key(key):
    """The media type a key's extension stands for. It is derived, not stored, so it moves with the file."""
    dot = key.rfind(".")
    return _MEDIA_TYPES.get(key[dot:].lower(), DEFAULT_MEDIA_TYPE) if dot > key.rfind("/") else DEFAULT_MEDIA_TYPE


def checked_media_type(key, media_type):
    expected = media_type_for_key(key)
    if media_type != expected:
        raise InvalidKey(f"media_type {media_type!r} does not match key {key!r} (expected {expected!r})")
    return expected


@dataclass(frozen=True)
class ArtifactRef:
    uri: str
    sha256: str
    size: int
    media_type: str

    def to_dict(self):
        return {"uri": self.uri, "sha256": self.sha256, "size": self.size, "media_type": self.media_type}

    @classmethod
    def from_dict(cls, d):
        try: return cls(uri=validate_artifact_key(d["uri"]), sha256=d["sha256"], size=int(d["size"]), media_type=d["media_type"])
        except (KeyError, TypeError, ValueError) as e: raise StorageError(f"malformed artifact reference: {e}") from e


def _uri(ref_or_uri):
    return validate_artifact_key(ref_or_uri.uri if isinstance(ref_or_uri, ArtifactRef) else ref_or_uri)


class ArtifactStore(abc.ABC):
    """Write-once blobs. There is no delete and no overwrite."""

    @abc.abstractmethod
    def put(self, key, data, media_type):
        """Store bytes at key. Same bytes again: returns the same ref. Different bytes: ArtifactExists. -> ArtifactRef"""

    @abc.abstractmethod
    def get(self, ref_or_uri):
        """Bytes, verified against the sha256 when a ref is given (IntegrityError on mismatch); ArtifactMissing if absent."""

    @abc.abstractmethod
    def open(self, ref_or_uri):
        """A binary file-like object, verified like get()."""

    @abc.abstractmethod
    def stat(self, key):
        """The ArtifactRef of an existing key, or None."""

    @abc.abstractmethod
    def list(self, prefix=""):
        """ArtifactRefs whose key is under prefix (a whole-segment prefix), sorted by uri."""

    @abc.abstractmethod
    def keys(self, prefix=""):
        """Sorted keys under prefix, without reading any content (list() hashes every file)."""

    def exists(self, key):
        return self.stat(key) is not None

    @contextlib.contextmanager
    def materialize(self, ref_or_uri, suffix=""):
        """A temporary local file path holding the verified bytes, for tools that only take a path. Local use only; the
        path is never persisted and the file is removed on exit."""
        import os, tempfile
        data = self.get(ref_or_uri)
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f: f.write(data)
            yield path
        finally:
            with contextlib.suppress(OSError): os.remove(path)


@dataclass(frozen=True)
class StateRecord:
    key: str
    version: int          # 1 on creation, +1 on every compare_and_set
    schema_version: int
    value: dict

    def to_dict(self):
        return {"key": self.key, "version": self.version, "schema_version": self.schema_version, "value": self.value}


class StateStore(abc.ABC):
    """Versioned records and append-only event streams. Values are JSON objects."""

    @abc.abstractmethod
    def get(self, key):
        """StateRecord or None."""

    @abc.abstractmethod
    def put_new(self, key, value, schema_version):
        """Create at version 1. StateExists if the key is taken. -> StateRecord"""

    @abc.abstractmethod
    def compare_and_set(self, key, expected_version, value, schema_version):
        """Replace the value only if the current version equals expected_version; StaleHead otherwise,
        StateMissing if the key does not exist. -> StateRecord (version + 1)"""

    @abc.abstractmethod
    def list(self, prefix=""):
        """StateRecords whose key is under prefix (a whole-segment prefix), sorted by key."""

    @abc.abstractmethod
    def append_event(self, stream, event, schema_version, durable=False):
        """Append a JSON object to a stream. -> sequence number (1, 2, ...). durable=True: the event is on disk before
        this returns (use it for state-changing events); the default is flushed only."""

    @abc.abstractmethod
    def append_event_after(self, stream, build, schema_version, durable=False):
        """Like append_event, but the event is build(last event dict or None), computed under the stream's write lock, so
        a hash chain can not fork. -> sequence number"""

    @abc.abstractmethod
    def streams(self, prefix=""):
        """Sorted names of the event streams under prefix (a whole-segment prefix)."""

    @abc.abstractmethod
    def events(self, stream, after=0):
        """[{"seq", "schema_version", "event"}] with seq > after, in order."""


class RulePackStore(abc.ABC):
    """Interface only (S2). S4 implements it and may refine the signatures. Every value read from a rule pack comes
    with its rule_id, source table, section and page, and the pack version and hash."""

    @abc.abstractmethod
    def list_versions(self, pack_id): ...

    @abc.abstractmethod
    def load(self, pack_id, version=None):
        """The pack document. version None means the active version."""

    @abc.abstractmethod
    def content_hash(self, pack_id, version=None): ...
