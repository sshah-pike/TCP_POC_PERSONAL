"""FileStateStore specifics: locking, stale takeover, lost-lock abort, replace retry, reads, torn events, key collisions."""
import json, multiprocessing, os, time

import pytest

from tcp_planner.storage import file_state as FS
from tcp_planner.storage.file_state import FileStateStore, LockLost
from tcp_planner.storage.interfaces import InvalidKey, StorageError, StaleHead
from tcp_planner.storage.local_fs import LocalFsArtifactStore


def files_under(root):
    return sorted(os.path.relpath(os.path.join(d, n), root).replace("\\", "/") for d, _s, ns in os.walk(root) for n in ns)


# ------------------------------------------------------------------ layout
def test_layout_envelope_and_no_leftovers(tmp_path):
    st = FileStateStore(tmp_path)
    st.put_new("ui/request", {"a": 1}, 3)
    st.append_event("ui/events", {"e": 1}, 2)
    assert files_under(tmp_path) == ["ui/events.events.jsonl", "ui/request.state.json"]  # no .lock, no .tmp- left behind
    env = json.loads((tmp_path / "ui" / "request.state.json").read_text("utf-8"))
    assert env == {"key": "ui/request", "version": 1, "schema_version": 3, "value": {"a": 1}}
    line = json.loads((tmp_path / "ui" / "events.events.jsonl").read_text("utf-8").splitlines()[0])
    assert line == {"seq": 1, "schema_version": 2, "event": {"e": 1}}


def test_reads_never_create_files_or_folders(tmp_path):
    root = tmp_path / "state"
    st = FileStateStore(root)
    assert st.get("a/b") is None and st.list() == [] and st.list("a") == [] and st.events("a/e") == []
    assert not root.exists()


# ------------------------------------------------------------------ stale lock takeover
def _die_holding_lock(root, key):
    st = FileStateStore(root)
    st._acquire(st._state_path(key))  # take the lock and never release it
    os._exit(0)


def test_a_dead_process_lock_is_taken_over_after_the_timeout(tmp_path):
    root = str(tmp_path / "state")
    FileStateStore(root).put_new("heads/x", {"n": 0}, 1)
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=_die_holding_lock, args=(root, "heads/x")); p.start(); p.join(60)
    assert os.path.exists(os.path.join(root, "heads", "x.state.json.lock"))  # the dead owner's lock is still there
    st = FileStateStore(root, stale_lock_s=0.5, lock_wait_s=20)
    t0 = time.time()
    r = st.compare_and_set("heads/x", 1, {"n": 1}, 1)
    assert r.version == 2 and time.time() - t0 >= 0.4  # waited for the lock to go stale
    assert not any(f.endswith(".lock") or ".lock.stale-" in f for f in files_under(root))


def test_a_fresh_lock_is_respected_and_times_out(tmp_path):
    holder = FileStateStore(tmp_path, stale_lock_s=30)
    holder._acquire(holder._state_path("k/a"))
    waiter = FileStateStore(tmp_path, stale_lock_s=30, lock_wait_s=0.3)
    with pytest.raises(StorageError): waiter.put_new("k/a", {}, 1)
    assert waiter.get("k/a") is None


# ------------------------------------------------------------------ lost lock: never replace
def _steal(st, key):
    """What a taker does: replace the lock file with another owner's."""
    lock = st._state_path(key) + FS.LOCK_SUFFIX
    with open(lock, "w", encoding="utf-8") as f: json.dump({"pid": os.getpid() + 1, "ts": time.time(), "token": "thief"}, f)


def test_a_writer_whose_lock_was_taken_over_must_not_replace_the_file(tmp_path):
    st = FileStateStore(tmp_path, stale_lock_s=0.2)  # the thief's lock is never released: let it go stale quickly
    st.put_new("heads/x", {"n": 0}, 1)
    before = (tmp_path / "heads" / "x.state.json").read_bytes()
    st._pre_replace_hook = lambda: _steal(st, "heads/x")  # the lock is taken over on every attempt
    with pytest.raises(LockLost): st.compare_and_set("heads/x", 1, {"n": 99}, 1)
    assert (tmp_path / "heads" / "x.state.json").read_bytes() == before          # nothing replaced
    assert not [f for f in files_under(tmp_path) if os.path.basename(f).startswith(".tmp-")]  # temp file cleaned up


def test_a_lost_lock_once_is_retried_and_the_write_lands_exactly_once(tmp_path):
    st = FileStateStore(tmp_path, stale_lock_s=0.2)  # the thief's lock is never released: let it go stale quickly
    st.put_new("heads/x", {"n": 0}, 1)
    calls = []

    def hook():
        calls.append(1)
        if len(calls) == 1: _steal(st, "heads/x")
    st._pre_replace_hook = hook
    r = st.compare_and_set("heads/x", 1, {"n": 1}, 1)
    assert len(calls) == 2 and r.version == 2 and st.get("heads/x").value == {"n": 1}
    with pytest.raises(StaleHead): st.compare_and_set("heads/x", 1, {"n": 2}, 1)  # not applied twice


def test_a_live_lock_moved_by_a_slow_taker_is_put_back(tmp_path, monkeypatch):
    st = FileStateStore(tmp_path, stale_lock_s=30)
    live = st._acquire(st._state_path("k/b"))             # a live lock sits at the path ...
    stale_view = {"pid": 1, "ts": time.time() - 3600, "token": "old"}  # ... but the taker looked at an old stale one
    real = FS._read_lock; calls = []

    def read(path):
        calls.append(path)
        return stale_view if len(calls) == 1 else real(path)
    monkeypatch.setattr(FS, "_read_lock", read)
    st._take_over_if_stale(live.path)
    assert os.path.exists(live.path) and live.owned()      # moved, noticed it was not the stale lock, put it back
    assert not [f for f in files_under(tmp_path) if ".lock.stale-" in f]


# ------------------------------------------------------------------ os.replace retry
def test_replace_retries_on_permission_error_then_succeeds(tmp_path, monkeypatch):
    st = FileStateStore(tmp_path)
    real = os.replace; fails = {"n": 3}; slept = []

    def flaky(src, dst):
        if fails["n"] > 0: fails["n"] -= 1; raise PermissionError("held by another process")
        return real(src, dst)
    monkeypatch.setattr(FS.os, "replace", flaky); monkeypatch.setattr(FS, "_sleep", slept.append)
    st.put_new("a/b", {"x": 1}, 1)
    assert st.get("a/b").value == {"x": 1} and len(slept) >= 3


def test_replace_gives_up_after_the_retries_and_leaves_no_temp_file(tmp_path, monkeypatch):
    st = FileStateStore(tmp_path)
    monkeypatch.setattr(FS.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr(FS, "_sleep", lambda s: None)
    with pytest.raises(StorageError): st.put_new("a/b", {"x": 1}, 1)
    assert st.get("a/b") is None
    assert files_under(tmp_path) == []


# ------------------------------------------------------------------ events
def test_a_torn_last_event_line_is_reported_on_append_and_skipped_on_read(tmp_path):
    st = FileStateStore(tmp_path)
    st.append_event("s/e", {"i": 1}, 1)
    with open(tmp_path / "s" / "e.events.jsonl", "ab") as f: f.write(b'{"seq":2,"schema_version":1,"eve')  # crash mid-append
    assert [e["seq"] for e in st.events("s/e")] == [1]            # a reader skips the incomplete tail
    with pytest.raises(StorageError): st.append_event("s/e", {"i": 2}, 1)  # a writer refuses to build on it


def test_a_complete_but_corrupt_event_line_is_an_error(tmp_path):
    st = FileStateStore(tmp_path)
    st.append_event("s/e", {"i": 1}, 1)
    with open(tmp_path / "s" / "e.events.jsonl", "ab") as f: f.write(b"not json\n")
    with pytest.raises(StorageError): st.events("s/e")


def test_a_corrupt_state_file_is_an_error_not_a_missing_key(tmp_path):
    st = FileStateStore(tmp_path)
    st.put_new("a/b", {"x": 1}, 1)
    (tmp_path / "a" / "b.state.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError): st.get("a/b")
    with pytest.raises(StorageError): st.compare_and_set("a/b", 1, {}, 1)


# ------------------------------------------------------------------ sharing a folder with artifacts
@pytest.mark.parametrize("key", ["r1/x.state.json", "r1/x.events.jsonl", "r1/x.lock", "r1/ui/request.state.json"])
def test_artifact_keys_may_not_use_state_file_suffixes(tmp_path, key):
    with pytest.raises(InvalidKey): LocalFsArtifactStore(tmp_path).put(key, b"x", "application/octet-stream")


def test_artifact_listing_ignores_state_files_in_the_same_folder(tmp_path):
    arts = LocalFsArtifactStore(tmp_path); st = FileStateStore(tmp_path)
    arts.put("r1/output/plan.json", b"{}", "application/json")
    st.put_new("r1/ui/request", {"a": 1}, 1); st.append_event("r1/ui/events", {"e": 1}, 1)
    assert [r.uri for r in arts.list("r1")] == ["r1/output/plan.json"]
    assert [r.key for r in st.list("r1")] == ["r1/ui/request"]
