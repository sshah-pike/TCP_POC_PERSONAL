"""The UI records of a run (request, resume, comparison, process, result, ...) as state records in the run's own folder.

<runs>/<run_id>/ui/<name>.state.json       one record per name, envelope {key, version, schema_version, value}
<runs>/<run_id>/ui/events.events.jsonl     the run's event stream (span start/end, evidence events, ...)

Nothing here holds an absolute path (D-77): paths inside a record are keys relative to the runs folder, for example
"<run_id>/input/site.kml". `resolve` turns a key into a path under the current runs folder, so a runs folder can be moved
as a whole and its runs resumed.

Runs made before S2 keep their ui/<name>.json files (the "legacy" layout). Reading falls back to those files; writing
to a legacy run is refused and never creates a file in its folder.
"""
import json, os

from tcp_planner.config import settings
from tcp_planner.storage import stores
from tcp_planner.storage.interfaces import StateExists, StaleHead, validate_key
from tcp_planner.storage.file_state import STATE_SUFFIX, EVENTS_SUFFIX

SCHEMA_VERSION = 1
EVENTS_STREAM = "ui/events"
NAMES = ("request", "resume", "comparison", "prep", "report", "result", "process", "usage", "diagnostics", "calls",
         "deps", "rule_pack", "tls")
LIST_RECORDS = ("usage", "diagnostics", "calls")  # lists: stored as {"items": [...]} (state values are objects)
LEGACY_MESSAGE = ("This run was made before the storage change. It can be viewed but not resumed, revised or compared. "
                  "Start a new run.")


class LegacyRunReadOnly(Exception):
    code = "LEGACY_RUN_READ_ONLY"

    def __init__(self, run_id=None):
        super().__init__(LEGACY_MESSAGE)
        self.run_id = run_id


def run_root(run_id):
    return os.path.join(os.path.abspath(settings.runs_dir()), validate_key(run_id))


def resolve(key):
    """Absolute path of a run-relative key under the current runs folder."""
    return os.path.join(os.path.abspath(settings.runs_dir()), *validate_key(key).split("/"))


def to_key(path):
    """Run-relative key of a path inside the runs folder (the inverse of resolve)."""
    root = os.path.abspath(settings.runs_dir())
    rel = os.path.relpath(os.path.abspath(path), root)
    if rel.startswith("..") or os.path.isabs(rel): raise ValueError("path is outside the runs folder")
    return rel.replace(os.sep, "/")


def _store(run_id):
    return stores._file_state(run_root(run_id))


def _legacy_path(run_id, name):
    return os.path.join(run_root(run_id), "ui", name + ".json")


def has_records(run_id):
    ui = os.path.join(run_root(run_id), "ui")
    try: return any(n.endswith((STATE_SUFFIX, EVENTS_SUFFIX)) for n in os.listdir(ui))
    except OSError: return False


def is_legacy(run_id):
    """A run or comparison folder in the old layout: a ui/request.json (or comparison.json) and no state files."""
    return not has_records(run_id) and any(os.path.isfile(_legacy_path(run_id, n)) for n in ("request", "comparison"))


def exists(run_id):
    return has_records(run_id) or is_legacy(run_id)


def _check_name(name):
    if name not in NAMES: raise ValueError(f"unknown run record {name!r}")


def read(run_id, name, default=None):
    """The record's value, or default. Falls back to the legacy ui/<name>.json file."""
    _check_name(name)
    rec = _store(run_id).get(f"ui/{name}")
    if rec is not None: return rec.value["items"] if name in LIST_RECORDS else rec.value
    try:
        with open(_legacy_path(run_id, name), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return default


def update(run_id, name, fn, attempts=8):
    """Atomic read-modify-write: fn(current value or None) -> new value, or None to leave the record alone. Returns the
    value held afterwards. A concurrent writer is detected by the record's version and the update is retried."""
    _check_name(name)
    if is_legacy(run_id): raise LegacyRunReadOnly(run_id)
    st, key = _store(run_id), f"ui/{name}"
    wrap = name in LIST_RECORDS
    for _ in range(attempts):
        cur = st.get(key)
        cur_value = None if cur is None else cur.value["items"] if wrap else cur.value
        new = fn(cur_value)
        if new is None: return cur_value
        if wrap: new = {"items": new}
        try:
            if cur is None: st.put_new(key, new, SCHEMA_VERSION)
            else: st.compare_and_set(key, cur.version, new, SCHEMA_VERSION)
            return new["items"] if wrap else new
        except (StateExists, StaleHead):
            continue
    raise StaleHead(f"run record {name} of {run_id} kept changing")


def write(run_id, name, value):
    return update(run_id, name, lambda _cur: value)


def create(run_id, name, value):
    """Write a record that must not exist yet (request, resume, comparison)."""
    _check_name(name)
    if is_legacy(run_id): raise LegacyRunReadOnly(run_id)
    return _store(run_id).put_new(f"ui/{name}", value, SCHEMA_VERSION)


def events(run_id, after=0):
    """The event dicts of the run's stream, in order (legacy runs: the lines of ui/events.jsonl that parse)."""
    got = _store(run_id).events(EVENTS_STREAM, after)
    if got or has_records(run_id): return [e["event"] for e in got]
    out = []
    try:
        with open(os.path.join(run_root(run_id), "ui", "events.jsonl"), encoding="utf-8") as f:
            for line in f:
                try: out.append(json.loads(line))
                except ValueError: pass  # a line being written right now
    except OSError:
        pass
    return out[after:] if after else out


def append_event(run_id, event, durable=False):
    if is_legacy(run_id): raise LegacyRunReadOnly(run_id)
    return _store(run_id).append_event(EVENTS_STREAM, event, SCHEMA_VERSION, durable=durable)
