"""S2 5b: run records hold no absolute path, and a runs folder can be moved and its runs resumed (D-77)."""
import json
import os
import shutil

from tests.integration.web_api.test_evidence_resume import (  # noqa: F401  (fixtures and helpers)
    env, http, azure_run, resume, kml_bytes, LAT, LON)
from tests.support.rawpath_scan import scan_tree
from tcp_planner.storage import run_records as records
from tcp_planner.storage.evidence_store import load_manifest, resolve, verify_file


def _record_hits(runs_dir):
    """Raw-path hits in the run records and the evidence manifest (state records and event streams)."""
    return {f: h for f, h in scan_tree(runs_dir).items() if f.endswith((".state.json", ".events.jsonl"))}


def test_new_run_records_hold_no_absolute_path(env, monkeypatch):
    http(monkeypatch)
    parent, _ = azure_run(kml=kml_bytes(LAT, LON))
    child, _ = resume(parent, "vision", ai_profile="fake-a", ai_provider="foundry")
    runs = str(env / "runs")
    scanned = [n for _b, _d, ns in os.walk(runs) for n in ns if n.endswith((".state.json", ".events.jsonl"))]
    assert {"request.state.json", "result.state.json", "process.state.json", "resume.state.json", "manifest.state.json",
            "events.events.jsonl"} <= set(scanned)  # the scan really covers the records
    assert _record_hits(runs) == {}
    for rid in (parent, child):
        req = records.read(rid, "request")
        assert [a for a in req["argv"] if os.path.isabs(a)] == []
        assert req["request"]["kml_saved_path"] == f"{rid}/input/site.kml"
        assert req["argv"][req["argv"].index("--out") + 1] == f"{rid}/output"
        res = records.read(rid, "result")
        assert "out_dir" not in res and res["out_key"] == f"{rid}/output"
    assert records.read(child, "resume")["parent_run_id"] == parent


def test_moved_runs_folder_resumes(env, monkeypatch, tmp_path):
    """Make a run under folder A, move the whole folder to B, point the app at B and resume: it works, the evidence
    is verified by SHA-256 and nothing refers to A any more."""
    http(monkeypatch)
    parent, _ = azure_run(kml=kml_bytes(LAT, LON))
    a, b = tmp_path / "runs", tmp_path / "moved" / "elsewhere"
    assert not [h for h in _record_hits(str(a)).values() if h]
    b.parent.mkdir(); shutil.move(str(a), str(b))
    assert not a.exists()
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(b))
    h = http(monkeypatch)
    child, st = resume(parent, "vision", ai_profile="fake-a", ai_provider="foundry")
    assert st["state"] == "FINISHED" and st["lineage"]["actual_stage"] == "vision"
    assert [c for c in h.calls if c[0] in ("atlas.microsoft.com", "overpass-api.de") and c[1]["params"].get("width") == 1280] == []
    for e in load_manifest(child):
        assert verify_file(resolve(child, e)) is None
    for base, _d, names in os.walk(str(b)):
        for n in names:
            if n.endswith((".json", ".jsonl")):
                with open(os.path.join(base, n), "rb") as f: assert str(a).encode() not in f.read(), n
    assert records.read(child, "request")["request"]["kml_saved_path"] == f"{child}/input/site.kml"
    assert os.path.isfile(records.resolve(f"{child}/input/site.kml"))
