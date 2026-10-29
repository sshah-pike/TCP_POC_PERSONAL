"""S2 commit 6: the assistant's JsonStore runs on the ArtifactStore and StateStore; pre-S2 data stays readable."""
import json

import pytest

from tcp_planner.review.assistant.repositories.base import ImmutableExists, IntegrityError, LegacyStreamReadOnly
from tcp_planner.review.assistant.repositories.json_store import JsonStore


def test_records_are_write_once_files_and_blobs_are_not_listed_as_records(tmp_path):
    s = JsonStore(tmp_path)
    s.create("artifacts", "a1", {"k": 1})
    s.put_blob("artifacts", "a1", "annotated.png", b"png-bytes")
    s.create("artifacts", "a2", {"k": 2})
    assert [r["k"] for r in s.list("artifacts")] == [1, 2]
    assert sorted(p.name for p in (tmp_path / "artifacts").iterdir()) == ["a1", "a1.json", "a2.json"]
    with pytest.raises(ImmutableExists): s.create("artifacts", "a1", {"k": 1})  # even with the same content
    with pytest.raises(ImmutableExists): s.put_blob("artifacts", "a1", "annotated.png", b"png-bytes")


def test_put_blob_returns_a_key_not_a_path(tmp_path):
    s = JsonStore(tmp_path)
    blob = s.put_blob("artifacts", "a1", "annotated.png", b"xyz")
    assert blob == {"uri": "artifacts/a1/annotated.png", "sha256": blob["sha256"], "size_bytes": 3}
    assert "path" not in blob and open(s.blob_path("artifacts", "a1", "annotated.png"), "rb").read() == b"xyz"


def test_tampered_record_is_detected(tmp_path):
    s = JsonStore(tmp_path)
    s.create("versions", "v1", {"a": 1})
    p = tmp_path / "versions" / "v1.json"
    doc = json.loads(p.read_text()); doc["a"] = 9; p.write_text(json.dumps(doc))
    with pytest.raises(IntegrityError): s.get("versions", "v1")


def test_events_are_state_stream_lines_with_the_durable_flag_passed_on(tmp_path):
    s = JsonStore(tmp_path)
    s.append_event("conversations", "c1", {"type": "a"})
    s.append_event("conversations", "c1", {"type": "b"}, durable=True)
    assert s.events("conversations", "c1") == [{"type": "a"}, {"type": "b"}]
    lines = (tmp_path / "conversations" / "c1.events.jsonl").read_text().splitlines()
    assert [json.loads(x)["seq"] for x in lines] == [1, 2]
    assert s.events("conversations", "none") == []


def test_pre_s2_event_stream_is_read_but_not_appended_to(tmp_path):
    (tmp_path / "conversations").mkdir()
    (tmp_path / "conversations" / "old.events.jsonl").write_text('{"type":"a"}\n{"type":"b"}\n', encoding="utf-8")
    s = JsonStore(tmp_path)
    assert s.events("conversations", "old") == [{"type": "a"}, {"type": "b"}]
    with pytest.raises(LegacyStreamReadOnly): s.append_event("conversations", "old", {"type": "c"})
    assert (tmp_path / "conversations" / "old.events.jsonl").read_text(encoding="utf-8") == '{"type":"a"}\n{"type":"b"}\n'


def test_heads_compare_and_set_and_a_pre_s2_head_is_carried_over(tmp_path):
    s = JsonStore(tmp_path)
    assert s.compare_and_set_head("k", None, "v1") and not s.compare_and_set_head("k", None, "v2")
    assert s.compare_and_set_head("k", "v1", "v2") and s.head("k")["value"] == "v2" and s.head("k")["previous"] == "v1"
    assert (tmp_path / "heads" / "k.state.json").is_file()
    (tmp_path / "heads" / "old.json").write_text(json.dumps({"key": "old", "value": "x1", "previous": None}), encoding="utf-8")
    assert s.head("old")["value"] == "x1"
    assert not s.compare_and_set_head("old", "nope", "x2") and s.compare_and_set_head("old", "x1", "x2")
    assert s.head("old") == {"key": "old", "value": "x2", "previous": "x1"}
    assert json.loads((tmp_path / "heads" / "old.json").read_text())["value"] == "x1"  # the old file is left as it was


def test_unsafe_names_are_rejected(tmp_path):
    s = JsonStore(tmp_path)
    for bad in ("../x", "a/b", ""):
        with pytest.raises(ValueError): s.create("versions", bad, {})
