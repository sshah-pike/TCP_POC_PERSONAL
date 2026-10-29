"""Project records and project inputs on the stores (S2). The store is a helper only: what a project holds (work
locations, zones, status) is decided in S3 and is not invented here.

state:     <runs>/_shared/projects/<project_id>.state.json    one versioned record per project (compare-and-set)
artifacts: <runs>/projects/<project_id>/input/<name>          write-once inputs (for example the uploaded KML)

A project record is plain JSON and never holds a raw path (D-77): inputs are referenced by their store key.
"""
import datetime, re

from tcp_planner.storage.interfaces import StateExists, StaleHead, StorageError, media_type_for_key
from tcp_planner.storage.rawpaths import find_raw_paths

SCHEMA_VERSION = 1
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NAME_KEEP = re.compile(r"[^A-Za-z0-9._-]")
RESERVED_FIELDS = ("project_id", "created_at")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _check_id(project_id):
    if not PROJECT_ID_RE.match(project_id or "") or project_id.endswith("."): raise StorageError(f"invalid project id {project_id!r}")
    return project_id


def _check_value(value):
    if not isinstance(value, dict): raise StorageError("a project record must be a JSON object")
    hits = find_raw_paths(value)
    if hits: raise StorageError(f"a project record may not hold a raw path (use a store key): {hits[0][0]}")
    return value


def input_name(original_name):
    """File name part of an input key: letters, digits, '.', '_' and '-' kept, anything else '_'."""
    name = _NAME_KEEP.sub("_", (original_name or "").replace("\\", "/").split("/")[-1]).lstrip("._-")
    return name or "input"


class ProjectStore:
    def __init__(self, state, artifacts):
        self.state = state; self.artifacts = artifacts

    @staticmethod
    def _key(project_id):
        return f"projects/{_check_id(project_id)}"

    def create(self, project_id, record):
        """New project. record may not use the reserved fields (project_id, created_at). StateExists if it exists."""
        _check_value(record)
        if any(k in record for k in RESERVED_FIELDS): raise StorageError(f"{RESERVED_FIELDS} are set by the store")
        value = {"project_id": project_id, "created_at": _now(), **record}
        return self.state.put_new(self._key(project_id), value, SCHEMA_VERSION).value

    def get(self, project_id):
        rec = self.state.get(self._key(project_id))
        return None if rec is None else rec.value

    def list(self):
        return [r.value for r in self.state.list("projects")]

    def update(self, project_id, fn, attempts=8):
        """fn(current record) -> new record (project_id and created_at unchanged). Retried when another writer got in first."""
        key = self._key(project_id)
        for _ in range(attempts):
            cur = self.state.get(key)
            if cur is None: raise StorageError(f"project {project_id} does not exist")
            new = _check_value(fn(dict(cur.value)))
            if any(new.get(k) != cur.value[k] for k in RESERVED_FIELDS): raise StorageError(f"{RESERVED_FIELDS} can not change")
            try: return self.state.compare_and_set(key, cur.version, new, SCHEMA_VERSION).value
            except StaleHead: continue
        raise StaleHead(f"project {project_id} kept changing")

    def put_input(self, project_id, original_name, data):
        """Write-once input file of the project. -> ArtifactRef (keep ref.uri, a store key, in the record)."""
        if self.get(project_id) is None: raise StorageError(f"project {project_id} does not exist")
        key = f"projects/{project_id}/input/{input_name(original_name)}"
        return self.artifacts.put(key, data, media_type_for_key(key))

    def get_input(self, ref_or_uri):
        return self.artifacts.get(ref_or_uri)
