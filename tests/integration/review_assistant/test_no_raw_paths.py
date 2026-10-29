"""S2 acceptance: no raw path in any persisted JSON.

Builds every kind of persisted data in one isolated tree - runs (records, events, evidence, pipeline outputs, a resumed
run), assistant data (conversations, change sets, versions, site evidence, heads, audit, sessions, artifacts), ground-truth
labels and a project - then scans every .json and .jsonl file under it for a Windows drive path, a UNC path, an absolute
POSIX path or a parent-directory step."""
import json
import os

import pytest

from tests.support.rawpath_scan import scan_tree
from .conftest import call, login
from .test_phase4_versions import conv, review, stage_fact, confirm, inproc_launch  # noqa: F401


def _file_kinds(root):
    kinds = set()
    for _b, _d, names in os.walk(root):
        for n in names:
            kinds.add("events" if n.endswith(".events.jsonl") else "state" if n.endswith(".state.json")
                      else "json" if n.endswith(".json") else "other")
    return kinds


def test_no_persisted_json_holds_a_raw_path(aenv, runs, inproc_launch, monkeypatch):
    monkeypatch.setenv("TCP_UI_LABELS_DIR", str(aenv / "labels"))
    t, cid = conv(runs, "missing_road_type")
    stage_fact(t, cid, "road.road_type", "CORRECT", "RURAL", "county road records")
    r = review(t, cid)
    st, _, res = confirm(t, cid, r, "CONFIRM_AND_REGENERATE")
    assert st == 200 and len(inproc_launch) == 1
    call("GET", f"conversations/{cid}", token=t)  # finalizes the attempt

    from tcp_planner.evaluation import ground_truth_labels as labels
    d = labels.save_draft({"work_reference": {"latitude": 41.4, "longitude": -71.7}, "work_path": []},
                          {"road.lane_count": {"value": 2}}, "ai", "from evidence", runs["missing_road_type"])
    labels.confirm(d["site_id"], "A. Reviewer", "checked")

    from tcp_planner.storage import project_store, stores
    projects = project_store.ProjectStore(stores.state(), stores.artifacts())
    projects.create("P-001", {"name": "Main St"})
    projects.put_input("P-001", "site.kml", b"<kml/>")

    kinds = _file_kinds(str(aenv))
    assert {"events", "state", "json"} <= kinds  # the tree really holds every layout
    for sub in ("runs", "assistant_data", "labels"):
        assert os.path.isdir(aenv / sub), sub
    assert os.path.isdir(aenv / "assistant_data" / "audits") and os.path.isdir(aenv / "assistant_data" / "sessions")
    assert os.path.isdir(aenv / "runs" / "_shared" / "projects") and os.path.isdir(aenv / "assistant_data" / "heads")
    assert os.path.isdir(aenv / "assistant_data" / "artifacts") or os.path.isdir(aenv / "assistant_data" / "versions")

    assert scan_tree(str(aenv)) == {}


def test_the_scan_itself_catches_a_raw_path(tmp_path):
    (tmp_path / "a.state.json").write_text(json.dumps({"value": {"p": "C:\\runs\\r1\\output"}}), encoding="utf-8")
    (tmp_path / "b.events.jsonl").write_text(json.dumps({"event": {"p": "/home/u/x"}}) + "\n", encoding="utf-8")
    assert sorted(scan_tree(str(tmp_path))) == ["a.state.json", "b.events.jsonl"]
