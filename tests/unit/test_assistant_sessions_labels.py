"""S2 commit 6: sessions and ground-truth labels are state records; pre-S2 labels stay readable."""
import json

import pytest

from tcp_planner.evaluation import ground_truth_labels as labels
from tcp_planner.review.assistant.core import identity
from tcp_planner.review.assistant.core.errors import AssistantError
from tcp_planner.storage import run_store as store

PG = {"work_reference": {"latitude": 41.4, "longitude": -71.7}, "work_path": []}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_ASSISTANT_DATA_DIR", str(tmp_path / "assistant"))
    monkeypatch.setenv("TCP_UI_LABELS_DIR", str(tmp_path / "labels"))
    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"subject_id": "sme.1", "display_name": "SME", "roles": ["SME_REVIEWER"]}]}))
    monkeypatch.setenv("TCP_ASSISTANT_USERS_FILE", str(users))
    return tmp_path


def test_session_is_a_state_record_keyed_by_the_token_hash_and_ending_marks_it(dirs):
    idp = None  # the local provider reads the users file
    token, _ = identity.create_session("sme.1", idp)
    files = [p.name for p in (dirs / "assistant" / "sessions").iterdir()]
    assert files == [identity._token_hash(token) + ".state.json"]
    assert token not in (dirs / "assistant" / "sessions" / files[0]).read_text()
    identity.resolve(token, idp)
    identity.end_session(token); identity.end_session(token)  # twice is fine
    with pytest.raises(AssistantError): identity.resolve(token, idp)
    rec = json.loads((dirs / "assistant" / "sessions" / files[0]).read_text())
    assert rec["value"]["ended_at"] and rec["version"] == 2  # the record stays, marked
    with pytest.raises(AssistantError): identity.resolve("not-a-token", idp)


def test_label_draft_confirm_revoke_are_versioned_records(dirs):
    fields = {"road.lane_count": {"value": 2}}
    d = labels.save_draft(PG, fields, "ai", "from evidence", "20261029-120000-abcdef")
    sid = d["site_id"]
    assert (dirs / "labels" / f"{sid}.state.json").is_file()
    c = labels.confirm(sid, "A. Reviewer", "checked on the image", {"road.lane_count": 4})
    assert c["status"] == "CONFIRMED" and c["fields"]["road.lane_count"]["value"] == 4
    with pytest.raises(store.BadRequest): labels.save_draft(PG, fields, "ai", "again", "20261029-120000-abcdef")
    r = labels.revoke(sid, "A. Reviewer", "wrong")
    assert r["status"] == "DRAFT" and [h["action"] for h in r["history"]] == ["draft", "confirm", "revoke"]
    rec = json.loads((dirs / "labels" / f"{sid}.state.json").read_text())
    assert rec["version"] == 3 and rec["value"]["history"] == r["history"]
    assert [x["site_id"] for x in labels.list_labels()] == [sid]


def test_pre_s2_label_is_read_and_carried_over_by_the_first_change(dirs):
    sid = labels.site_id_for(PG)
    legacy = {"site_id": sid, "name": None, "work_reference": PG["work_reference"], "work_path": [], "source_run_id": "x",
              "status": "DRAFT", "fields": {"road.lane_count": {"value": 2, "tolerance": None, "note": None, "evidence": []}},
              "drafted_by": "old", "drafted_at": "2026-10-01T00:00:00+00:00", "confirmed_by": None, "confirmed_at": None,
              "confirm_reason": None, "history": [{"action": "draft", "by": "old", "at": "2026-10-01T00:00:00+00:00", "reason": "r"}]}
    (dirs / "labels").mkdir()
    old_file = dirs / "labels" / f"{sid}.json"
    old_file.write_text(json.dumps(legacy), encoding="utf-8")
    before = old_file.read_bytes()
    assert labels.get(sid)["drafted_by"] == "old" and [x["site_id"] for x in labels.list_labels()] == [sid]
    c = labels.confirm(sid, "A. Reviewer", "ok")
    assert [h["action"] for h in c["history"]] == ["draft", "confirm"]  # the old history is kept
    assert old_file.read_bytes() == before  # never rewritten
    assert labels.get(sid)["status"] == "CONFIRMED" and len(labels.list_labels()) == 1  # the record shadows the old file


def test_label_ids_are_validated(dirs):
    for bad in ("../x", "short", "G" * 16):
        with pytest.raises(store.BadRequest): labels.get(bad)
