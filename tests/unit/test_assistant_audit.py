"""S2 commit 6: the audit log is a state stream with its hash chain built under the stream lock."""
import json
import multiprocessing
import os

import pytest

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.review.assistant.core import audit as audit_mod
from tcp_planner.review.assistant.core.audit import AuditService
from tcp_planner.review.assistant.core.errors import AssistantError
from tcp_planner.storage.interfaces import StorageError


def test_events_are_chained_and_land_in_a_stream_file(tmp_path):
    a = AuditService(tmp_path)
    e1 = a.write("X", stream="c1", conversation_id="c1", n=1)
    e2 = a.write("Y", stream="c1", conversation_id="c1", n=2)
    assert e1["prev_event_hash"] is None and e2["prev_event_hash"] == e1["event_hash"]
    evs = a.read("c1")
    assert [e["event_type"] for e in evs] == ["X", "Y"] and AuditService.verify_chain(evs)
    files = [p.name for p in (tmp_path / "audits").rglob("*") if p.is_file()]
    assert files == ["c1.events.jsonl"]
    evs[1]["n"] = 99
    assert not AuditService.verify_chain(evs)  # tampering shows


def test_only_consequential_events_are_fsynced(tmp_path, monkeypatch):
    from tcp_planner.storage import file_state
    calls = []
    real = os.fsync
    monkeypatch.setattr(file_state.os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    a = AuditService(tmp_path)
    a.write("X", stream="c1"); assert calls == []
    a.write("Y", stream="c1", consequential=True); assert len(calls) == 1


def test_a_failed_write_raises_audit_write_failed(tmp_path, monkeypatch):
    a = AuditService(tmp_path)
    def boom(*args, **kw): raise StorageError("disk full")
    monkeypatch.setattr(a.state, "append_event_after", boom)
    with pytest.raises(AssistantError) as e: a.write("X", stream="c1")
    assert e.value.code == "AUDIT_WRITE_FAILED"


def _legacy_chain(root, day, stream, n):
    """A pre-S2 file: one bare chained event per line in audits/<day>/<stream>.jsonl."""
    d = os.path.join(root, "audits", day); os.makedirs(d)
    prev, lines = None, []
    for i in range(n):
        ev = {"event_type": f"OLD{i}", "prev_event_hash": prev}
        ev["event_hash"] = sha256_hex(canonical_json(ev)); prev = ev["event_hash"]
        lines.append(json.dumps(ev, sort_keys=True))
    with open(os.path.join(d, stream + ".jsonl"), "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")


def test_pre_s2_file_is_read_and_its_chain_continues(tmp_path, monkeypatch):
    import datetime
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    _legacy_chain(str(tmp_path), day, "c1", 2)
    before = (tmp_path / "audits" / day / "c1.jsonl").read_bytes()
    a = AuditService(tmp_path)
    a.write("NEW", stream="c1")
    evs = a.read("c1")
    assert [e["event_type"] for e in evs] == ["OLD0", "OLD1", "NEW"] and AuditService.verify_chain(evs)
    assert (tmp_path / "audits" / day / "c1.jsonl").read_bytes() == before  # the old file is never touched
    assert [e["event_type"] for e in a.read()] == ["OLD0", "OLD1", "NEW"]


def test_read_orders_by_day_then_stream_and_filters(tmp_path):
    a = AuditService(tmp_path)
    a.write("A", stream="b"); a.write("B", stream="a"); a.write("C", stream="b")
    assert [e["event_type"] for e in a.read()] == ["B", "A", "C"]
    assert [e["event_type"] for e in a.read("b")] == ["A", "C"] and a.read("nope") == []


def _writer(root, n):
    a = AuditService(root)
    for i in range(n): a.write("W", stream="shared", i=i, consequential=True)


def test_chain_does_not_fork_with_several_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ps = [ctx.Process(target=_writer, args=(str(tmp_path), 10)) for _ in range(3)]
    for p in ps: p.start()
    for p in ps: p.join(180)
    evs = AuditService(tmp_path).read("shared")
    assert len(evs) == 30 and AuditService.verify_chain(evs)
