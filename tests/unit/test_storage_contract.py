"""Contract suite: every ArtifactStore and StateStore adapter must pass these tests (S2)."""
import hashlib, multiprocessing, os, sys, threading

import pytest

from tcp_planner.storage.interfaces import (ArtifactRef, ArtifactExists, ArtifactMissing, IntegrityError, InvalidKey,
                                            StateExists, StateMissing, StaleHead, StorageError, ArtifactStore, StateStore)
from tcp_planner.storage.local_fs import LocalFsArtifactStore
from tcp_planner.storage.memory import InMemoryArtifactStore, InMemoryStateStore
from tcp_planner.storage.file_state import FileStateStore

JSON = "application/json"


@pytest.fixture(params=["local_fs", "memory"])
def artifacts(request, tmp_path):
    return LocalFsArtifactStore(tmp_path / "store") if request.param == "local_fs" else InMemoryArtifactStore()


@pytest.fixture(params=["file_state", "memory"])
def state(request, tmp_path):
    return FileStateStore(tmp_path / "state") if request.param == "file_state" else InMemoryStateStore()


# ------------------------------------------------------------------ ArtifactStore
def test_put_returns_ref_and_get_round_trips(artifacts):
    ref = artifacts.put("r1/output/plan.json", b'{"a":1}', JSON)
    assert ref == ArtifactRef("r1/output/plan.json", hashlib.sha256(b'{"a":1}').hexdigest(), 7, JSON)
    assert artifacts.get(ref) == b'{"a":1}' and artifacts.get(ref.uri) == b'{"a":1}'
    assert artifacts.open(ref).read() == b'{"a":1}'
    assert artifacts.stat(ref.uri) == ref and artifacts.exists(ref.uri)


def test_write_once_same_bytes_idempotent_different_bytes_fail(artifacts):
    a = artifacts.put("r1/output/x.json", b"one", JSON)
    assert artifacts.put("r1/output/x.json", b"one", JSON) == a
    with pytest.raises(ArtifactExists): artifacts.put("r1/output/x.json", b"two", JSON)
    assert artifacts.get("r1/output/x.json") == b"one"


def test_there_is_no_delete_or_overwrite_api():
    for cls in (ArtifactStore, LocalFsArtifactStore, InMemoryArtifactStore):
        assert not any(hasattr(cls, n) for n in ("delete", "remove", "overwrite", "replace", "update"))


def test_missing_and_hash_mismatch(artifacts):
    with pytest.raises(ArtifactMissing): artifacts.get("r1/nope.json")
    assert artifacts.stat("r1/nope.json") is None
    ref = artifacts.put("r1/a.json", b"abc", JSON)
    with pytest.raises(IntegrityError): artifacts.get(ArtifactRef(ref.uri, "0" * 64, ref.size, ref.media_type))


def test_invalid_keys_and_media_type_mismatch(artifacts):
    for bad in ("/abs/x.json", "../x.json", "a/../x.json", "C:/x.json", "a\\b.json"):
        with pytest.raises(InvalidKey): artifacts.put(bad, b"x", JSON)
    with pytest.raises(InvalidKey): artifacts.put("r1/a.json", b"x", "image/png")


def test_list_whole_segment_prefix_sorted(artifacts):
    for k in ("r1/output/b.json", "r1/output/a.json", "r1/ui/c.json", "r10/output/d.json"):
        artifacts.put(k, k.encode(), JSON)
    assert [r.uri for r in artifacts.list("r1")] == ["r1/output/a.json", "r1/output/b.json", "r1/ui/c.json"]
    assert [r.uri for r in artifacts.list("r1/output")] == ["r1/output/a.json", "r1/output/b.json"]
    assert len(artifacts.list()) == 4


def test_materialize_gives_a_temp_file_that_is_removed(artifacts):
    ref = artifacts.put("r1/img.png", b"\x89PNG", "image/png")
    with artifacts.materialize(ref, suffix=".png") as p:
        assert open(p, "rb").read() == b"\x89PNG"
    assert not os.path.exists(p)


def test_concurrent_writers_one_wins_without_corruption(artifacts):
    results = []

    def w(i):
        try: artifacts.put("r1/race.json", f"v{i}".encode(), JSON); results.append("ok")
        except ArtifactExists: results.append("exists")
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert results.count("ok") == 1 and results.count("exists") == 7
    assert artifacts.get("r1/race.json") in {f"v{i}".encode() for i in range(8)}


# ------------------------------------------------------------------ StateStore
def test_put_new_get_and_duplicate(state):
    r = state.put_new("projects/p1", {"status": "RUNNING"}, 1)
    assert (r.version, r.schema_version, r.value) == (1, 1, {"status": "RUNNING"})
    assert state.get("projects/p1") == r and state.get("projects/none") is None
    with pytest.raises(StateExists): state.put_new("projects/p1", {}, 1)


def test_compare_and_set_rejects_a_stale_head(state):
    state.put_new("heads/x", {"n": 0}, 1)
    r2 = state.compare_and_set("heads/x", 1, {"n": 1}, 1)
    assert r2.version == 2
    with pytest.raises(StaleHead): state.compare_and_set("heads/x", 1, {"n": 99}, 1)
    assert state.get("heads/x").value == {"n": 1}
    with pytest.raises(StateMissing): state.compare_and_set("heads/none", 1, {}, 1)


def test_values_must_be_json_objects_and_are_copied(state):
    with pytest.raises(StorageError): state.put_new("k/a", [1, 2], 1)
    v = {"a": [1]}
    state.put_new("k/b", v, 1); v["a"].append(2)
    assert state.get("k/b").value == {"a": [1]}


def test_list_by_whole_segment_prefix(state):
    for k in ("runs/r1/request", "runs/r1/result", "runs/r10/request", "labels/s1"):
        state.put_new(k, {"k": k}, 1)
    assert [r.key for r in state.list("runs/r1")] == ["runs/r1/request", "runs/r1/result"]
    assert len(state.list()) == 4


def test_events_are_append_only_and_ordered(state):
    assert [state.append_event("runs/r1/events", {"i": i}, 1) for i in range(3)] == [1, 2, 3]
    assert state.append_event("runs/r2/events", {"i": 0}, 1) == 1
    evs = state.events("runs/r1/events")
    assert [e["seq"] for e in evs] == [1, 2, 3] and [e["event"]["i"] for e in evs] == [0, 1, 2]
    assert evs[0]["schema_version"] == 1
    assert [e["seq"] for e in state.events("runs/r1/events", after=2)] == [3]
    assert state.events("runs/none") == []
    assert not any(hasattr(StateStore, n) for n in ("delete", "remove", "truncate"))


def test_cas_has_exactly_one_winner_among_threads(state):
    state.put_new("heads/race", {"w": None}, 1)
    wins = []

    def w(i):
        try: state.compare_and_set("heads/race", 1, {"w": i}, 1); wins.append(i)
        except StaleHead: pass
    ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and state.get("heads/race").value == {"w": wins[0]} and state.get("heads/race").version == 2


# ------------------------------------------------------------------ file state across processes
def _cas_worker(path, i, q):
    try:
        FileStateStore(path).compare_and_set("heads/p", 1, {"w": i}, 1); q.put("win")
    except StaleHead:
        q.put("stale")


def test_file_state_cas_one_winner_across_processes(tmp_path):
    path = str(tmp_path / "state")
    FileStateStore(path).put_new("heads/p", {"w": None}, 1)
    ctx = multiprocessing.get_context("spawn"); q = ctx.Queue()
    ps = [ctx.Process(target=_cas_worker, args=(path, i, q)) for i in range(4)]
    [p.start() for p in ps]; [p.join(60) for p in ps]
    got = sorted(q.get(timeout=10) for _ in ps)
    assert got == ["stale", "stale", "stale", "win"]
    assert FileStateStore(path).get("heads/p").version == 2


# ------------------------------------------------------------------ S2 commit 6 additions
def test_keys_match_list_without_reading_content(artifacts):
    for k in ("c/a.json", "c/a/blob.png", "c/b.json", "d/x.json"):
        artifacts.put(k, b"x", "image/png" if k.endswith(".png") else JSON)
    assert artifacts.keys("c") == ["c/a.json", "c/a/blob.png", "c/b.json"] == [r.uri for r in artifacts.list("c")]
    assert artifacts.keys() == ["c/a.json", "c/a/blob.png", "c/b.json", "d/x.json"]
    assert artifacts.keys("nothing") == []


def test_streams_lists_event_streams_by_whole_segment_prefix(state):
    for s in ("audits/2026-10-29/c1", "audits/2026-10-29/system", "audits/2026-10-30/c1", "conversations/c1", "auditsx/y"):
        state.append_event(s, {"i": 1}, 1)
    assert state.streams("audits") == ["audits/2026-10-29/c1", "audits/2026-10-29/system", "audits/2026-10-30/c1"]
    assert state.streams("conversations") == ["conversations/c1"] and state.streams("nope") == []


def test_append_event_after_builds_from_the_last_event(state):
    def chain(last): return {"n": 1 if last is None else last["n"] + 1, "prev": None if last is None else last["n"]}
    assert [state.append_event_after("s/e", chain, 1) for _ in range(3)] == [1, 2, 3]
    assert [e["event"] for e in state.events("s/e")] == [{"n": 1, "prev": None}, {"n": 2, "prev": 1}, {"n": 3, "prev": 2}]
    assert state.append_event("s/e", {"n": 9, "prev": 3}, 1) == 4


def _chain_worker(root, n):
    from tcp_planner.storage.file_state import FileStateStore as F
    st = F(root)
    for _ in range(n): st.append_event_after("s/e", lambda last: {"n": 1 if last is None else last["n"] + 1}, 1)


def test_append_event_after_never_forks_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ps = [ctx.Process(target=_chain_worker, args=(str(tmp_path), 15)) for _ in range(3)]
    for p in ps: p.start()
    for p in ps: p.join(120)
    evs = FileStateStore(tmp_path).events("s/e")
    assert [e["seq"] for e in evs] == list(range(1, 46)) and [e["event"]["n"] for e in evs] == list(range(1, 46))
