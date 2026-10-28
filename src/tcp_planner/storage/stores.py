"""The configured local stores. Callers get the artifact and state stores here and never join paths themselves.

Everything lives under the runs folder (settings.runs_dir()), as files (D-84), so the folder can be copied or moved as a
whole and nothing persisted refers to its absolute location (D-77):
- artifacts: <runs>/<key>, for example <runs>/<run_id>/output/plan.json
- run state (records and event streams of one run): files inside that run's own folder, <runs>/<run_id>/, so a run
  is self-contained: copy it, move it, resume it
- state shared across runs (labels, projects, heads): <runs>/_shared/
"""
import os

from tcp_planner.config import settings
from tcp_planner.storage.file_state import FileStateStore, STATE_SUFFIX, EVENTS_SUFFIX
from tcp_planner.storage.interfaces import validate_key
from tcp_planner.storage.local_fs import LocalFsArtifactStore

SHARED_DIR = "_shared"


def artifacts():
    return LocalFsArtifactStore(settings.runs_dir())


def _file_state(root):
    return FileStateStore(root, stale_lock_s=settings.STATE_LOCK_STALE_S)


def state():
    """State shared across runs. Reading never creates the folder."""
    return _file_state(os.path.join(os.path.abspath(settings.runs_dir()), SHARED_DIR))


def run_state(run_id, create=False):
    """State of one run, or None when the run has no state files yet (old runs, unknown ids) and create is False.
    Reading never creates files or folders."""
    validate_key(run_id)
    root = os.path.join(os.path.abspath(settings.runs_dir()), run_id)
    if not create and not any(n.endswith((STATE_SUFFIX, EVENTS_SUFFIX)) for _d, _s, ns in os.walk(root) for n in ns):
        return None
    return _file_state(root)
