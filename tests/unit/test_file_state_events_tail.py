"""S2 5b: append_event reads the sequence number from the file tail, and only durable events are fsynced."""
import json
import os
import time

import pytest

from tcp_planner.storage import file_state
from tcp_planner.storage.file_state import FileStateStore
from tcp_planner.storage.interfaces import StorageError
from tcp_planner.storage.memory import InMemoryStateStore


def _seed(path, n, pad=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        for i in range(1, n + 1):
            f.write((json.dumps({"seq": i, "schema_version": 1, "event": {"i": i, "pad": "x" * pad}},
                                sort_keys=True, separators=(",", ":")) + "\n").encode())


def test_seq_continues_from_the_tail_for_one_line_many_lines_and_lines_longer_than_a_block(tmp_path):
    st = FileStateStore(tmp_path)
    assert st.append_event("a/e", {"i": 1}, 1) == 1  # missing file
    _seed(tmp_path / "b" / "e.events.jsonl", 1)
    assert st.append_event("b/e", {"i": 2}, 1) == 2  # a single complete line
    _seed(tmp_path / "c" / "e.events.jsonl", 50)
    assert st.append_event("c/e", {"i": 51}, 1) == 51
    _seed(tmp_path / "d" / "e.events.jsonl", 3, pad=3 * FileStateStore.TAIL_BLOCK)  # last line spans several blocks
    assert st.append_event("d/e", {"i": 4}, 1) == 4
    assert [e["seq"] for e in st.events("d/e")] == [1, 2, 3, 4]


def test_torn_tail_and_invalid_last_line_are_refused(tmp_path):
    st = FileStateStore(tmp_path)
    _seed(tmp_path / "t" / "e.events.jsonl", 2)
    with open(tmp_path / "t" / "e.events.jsonl", "ab") as f: f.write(b'{"seq":3,"schema_version":1,"eve')
    with pytest.raises(StorageError, match="torn"): st.append_event("t/e", {"i": 3}, 1)
    _seed(tmp_path / "u" / "e.events.jsonl", 1)
    with open(tmp_path / "u" / "e.events.jsonl", "ab") as f: f.write(b"not json\n")
    with pytest.raises(StorageError): st.append_event("u/e", {"i": 2}, 1)


def test_only_durable_events_are_fsynced(tmp_path, monkeypatch):
    calls = []
    real = os.fsync
    monkeypatch.setattr(file_state.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    st = FileStateStore(tmp_path)
    st.append_event("s/e", {"k": "progress"}, 1)
    st.append_event("s/e", {"k": "progress"}, 1, durable=False)
    assert calls == []  # not the event file, and not the lock file
    st.append_event("s/e", {"k": "finished"}, 1, durable=True)
    assert len(calls) == 1
    assert [e["seq"] for e in st.events("s/e")] == [1, 2, 3]


def test_memory_fake_accepts_durable():
    assert InMemoryStateStore().append_event("s", {"a": 1}, 1, durable=True) == 1


def test_append_cost_does_not_grow_with_the_stream(tmp_path):
    """2,000 appends (the size of a long run's event stream): the last 500 cost less than 3x the first 500, and a
    stream pre-seeded with 20,000 events costs about the same per append as an empty one. The old code parsed the whole
    file on every call, so the second check would fail there by a wide margin."""
    st = FileStateStore(tmp_path)
    ev = {"event": "span_end", "name": "tcp.vision.analyze", "status": "OK", "attributes": {"k": "v" * 120}}
    times = []
    for i in range(2000):
        t = time.perf_counter(); st.append_event("ui/events", dict(ev, i=i), 1); times.append(time.perf_counter() - t)
    assert sum(times[-500:]) < 3 * sum(times[:500])
    assert [e["seq"] for e in st.events("ui/events", after=1995)] == [1996, 1997, 1998, 1999, 2000]

    _seed(tmp_path / "big" / "e.events.jsonl", 20000, pad=100)
    t = time.perf_counter()
    for i in range(200): st.append_event("big/e", {"i": i}, 1)
    big = time.perf_counter() - t
    t = time.perf_counter()
    for i in range(200): st.append_event("small/e", {"i": i}, 1)
    small = time.perf_counter() - t
    assert big < 3 * small + 0.5, (big, small)
