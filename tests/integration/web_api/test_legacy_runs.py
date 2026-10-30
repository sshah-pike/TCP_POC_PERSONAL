"""S2 5c: runs made before the storage change (ui/*.json) can be listed and opened, never written to, never resumed.

The protected run 20261020-214203-7f7232 is tracked in git in the old layout; every test here checks that its files are
byte-identical afterwards and that no file (state record, lock, temp file) appeared in its folder."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from tcp_planner.orchestration import run_relations as relations
from tcp_planner.storage import run_records as records
from tcp_planner.web_api import server
from tests.integration.web_api.inproc import tree_hashes

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LEGACY_RUNS = os.path.join(ROOT, "var", "runs")
PROTECTED = "20261020-214203-7f7232"


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", LEGACY_RUNS)
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown(); srv.server_close()


def _snapshot():
    return tree_hashes(os.path.join(LEGACY_RUNS, PROTECTED))


def test_the_protected_run_is_a_legacy_run():
    assert records.is_legacy(PROTECTED) and records.exists(PROTECTED)
    assert os.path.isfile(os.path.join(LEGACY_RUNS, PROTECTED, "ui", "request.json"))
    assert not os.path.exists(os.path.join(LEGACY_RUNS, PROTECTED, "ui", "request.state.json"))


def test_listing_and_opening_a_legacy_run_changes_nothing(legacy):
    before = _snapshot()
    code, runs = legacy("GET", "/api/runs")
    assert code == 200 and PROTECTED in {r["run_id"] for r in runs}
    code, st = legacy("GET", f"/api/runs/{PROTECTED}")
    assert code == 200 and st["state"] == "FINISHED" and st["request"] and st["stages"] and st["evidence"]
    assert any(e["kind"] == "map" for e in st["evidence"])  # the old manifest.json is read
    assert st["log"] and records.events(PROTECTED)  # stdout.log and the old events.jsonl are read
    assert st["rule_pack"] and st["cost"]
    assert _snapshot() == before  # same files, same bytes, nothing new (no state record, lock or temp file)


def test_resume_of_a_legacy_run_is_refused_with_a_clear_message(legacy):
    before = _snapshot()
    code, body = legacy("POST", f"/api/runs/{PROTECTED}/resume", {"stage": "vision"})
    assert code == 409 and body["error_code"] == "LEGACY_RUN_READ_ONLY"
    assert body["error"] == records.LEGACY_MESSAGE and "can be viewed but not resumed" in body["error"]
    code, body = legacy("POST", "/api/comparisons", {"source_run_id": PROTECTED, "profiles": ["a", "b"]})
    assert code == 409 and body["error_code"] == "LEGACY_RUN_READ_ONLY"
    with pytest.raises(records.LegacyRunReadOnly): relations.create_resume_run(PROTECTED, "vision")
    assert _snapshot() == before


def test_no_write_path_reaches_a_legacy_run_folder():
    before = _snapshot()
    for call in (lambda: records.write(PROTECTED, "process", {"state": "FINISHED"}),
                 lambda: records.create(PROTECTED, "resume", {"a": 1}),
                 lambda: records.update(PROTECTED, "process", lambda cur: {"state": "FINISHED"}),
                 lambda: records.append_event(PROTECTED, {"event": "x"}, durable=True)):
        with pytest.raises(records.LegacyRunReadOnly) as e: call()
        assert e.value.code == "LEGACY_RUN_READ_ONLY"
    assert _snapshot() == before


def test_the_worker_refuses_to_run_a_legacy_run(monkeypatch, capsys):
    from tcp_planner.orchestration import run_worker
    monkeypatch.setenv("TCP_UI_RUNS_DIR", LEGACY_RUNS)
    before = _snapshot()
    assert run_worker.main([PROTECTED]) == 2
    assert "can be viewed but not resumed" in capsys.readouterr().out
    assert _snapshot() == before


def test_the_worker_takes_a_run_id_not_a_folder(capsys):
    from tcp_planner.orchestration import run_worker
    assert run_worker.main([os.path.join(LEGACY_RUNS, PROTECTED)]) == 2
    assert "run id" in capsys.readouterr().err
