"""Evidence store on files (S2): manifest as a state record inside the run folder, legacy manifest.json read-only."""
import json, os, shutil

import pytest

from tcp_planner.storage import evidence_store as E, stores
from tcp_planner.storage.interfaces import IntegrityError

RUN = "20261028-212645-f05da1"
OTHER = "20261028-212700-aaaaaa"


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    return tmp_path / "runs"


def save_map(run_id, data=b"png-bytes"):
    ev = E.EvidenceStore(run_id)
    return ev.save("map", data, "png", {"kind": "map", "geometry_hash": "g"}, {"meta": {}}, "tcp.map.retrieve")


def test_save_writes_blob_and_manifest_inside_the_run_folder(runs):
    entry = save_map(RUN)
    assert entry["file"] == "map_1.png"
    assert sorted(os.listdir(runs / RUN / "evidence")) == ["manifest.state.json", "map_1.png"]
    env = json.loads((runs / RUN / "evidence" / "manifest.state.json").read_text("utf-8"))
    assert env["key"] == "evidence/manifest" and env["version"] == 1 and env["schema_version"] == 1
    assert [e["file"] for e in E.load_manifest(RUN)] == ["map_1.png"]


def test_a_second_save_bumps_the_manifest_version(runs):
    ev = E.EvidenceStore(RUN)
    ev.save("map", b"a", "png", {"k": 1}, {}, "s"); ev.save("osm", b"{}", "json", {"k": 2}, {}, "s")
    env = json.loads((runs / RUN / "evidence" / "manifest.state.json").read_text("utf-8"))
    assert env["version"] == 2 and [e["file"] for e in env["value"]["artifacts"]] == ["map_1.png", "osm_1.json"]


def test_a_copied_run_folder_is_self_contained(runs, tmp_path):
    save_map(RUN)
    shutil.copytree(runs / RUN, runs / OTHER)                      # copy the folder, nothing else
    got = E.load_manifest(OTHER)
    assert [e["file"] for e in got] == ["map_1.png"]
    r = E.resolve(OTHER, got[0])
    assert r["ref"].uri == f"{OTHER}/evidence/map_1.png" and E.read_bytes(r) == b"png-bytes" and E.verify_file(r) is None


def test_a_moved_runs_folder_still_resolves(runs, tmp_path, monkeypatch):
    save_map(RUN)
    moved = tmp_path / "elsewhere" / "runs2"; moved.parent.mkdir()
    shutil.move(str(runs), str(moved)); monkeypatch.setenv("TCP_UI_RUNS_DIR", str(moved))
    [e] = E.load_manifest(RUN)
    assert E.verify_file(E.resolve(RUN, e)) is None


def test_tampered_or_missing_blob_is_reported(runs):
    save_map(RUN)
    [e] = E.load_manifest(RUN); path = runs / RUN / "evidence" / "map_1.png"
    path.write_bytes(b"changed")
    assert "hash mismatch" in E.verify_file(E.resolve(RUN, e))
    with pytest.raises(IntegrityError): E.read_bytes(E.resolve(RUN, e))
    path.unlink()
    assert E.verify_file(E.resolve(RUN, e)) == "artifact file missing"


def test_reference_entries_resolve_to_the_run_that_saved_the_file(runs):
    src = save_map(RUN)
    ref = E.EvidenceStore(OTHER).reference({"kind": "map", "origin_run": RUN, "origin_artifact_id": src["artifact_id"],
                                            "origin_file": src["file"], "sha256": src["sha256"], "signature": {},
                                            "signature_hash": "h", "metadata": {}}, "tcp.map.retrieve")
    r = E.resolve(OTHER, ref)
    assert r["origin_run"] == RUN and r["ref"].uri == f"{RUN}/evidence/map_1.png" and E.verify_file(r) is None


def test_legacy_manifest_json_is_read_only_and_unknown_runs_are_empty(runs):
    (runs / RUN / "evidence").mkdir(parents=True)
    (runs / RUN / "evidence" / "map_1.png").write_bytes(b"old")
    entry = {"artifact_id": "map_1", "kind": "map", "mode": "saved", "file": "map_1.png",
             "sha256": E.sha256_bytes(b"old"), "size_bytes": 3}
    (runs / RUN / "evidence" / "manifest.json").write_text(json.dumps({"schema": "tcp-evidence-v1", "artifacts": [entry]}), "utf-8")
    before = sorted(os.listdir(runs / RUN / "evidence"))
    [e] = E.load_manifest(RUN)
    assert E.verify_file(E.resolve(RUN, e)) is None
    assert sorted(os.listdir(runs / RUN / "evidence")) == before          # reading wrote nothing
    assert E.load_manifest(OTHER) == [] and not (runs / OTHER).exists()    # an unknown run: empty, and nothing created
    assert stores.run_state(RUN) is None                                   # a legacy run has no state files yet
