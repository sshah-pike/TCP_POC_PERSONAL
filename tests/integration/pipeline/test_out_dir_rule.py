"""S2 5a: the pipeline Run writes through an ArtifactStore; a non-empty --out is an error unless --overwrite."""
import hashlib
import os

import pytest

from tcp_planner.contracts import TcpError
from tcp_planner.orchestration import offline_scenarios as offline
from tcp_planner.orchestration import pipeline
from tcp_planner.orchestration.pipeline import run_pipeline, main


def _run(out, **kw):
    sc = offline.build("supported")
    return run_pipeline(out_dir=str(out), operator=dict(sc["operator"]), map_provider=sc["map_provider"],
                        vision_provider=sc["vision_provider"], osm_source=lambda lat, lon, r: sc["osm_elements"],
                        lat=sc["lat"], lon=sc["lon"], dwt_config=None, **kw)


def _listing(d):
    return sorted(os.listdir(d))


def test_empty_or_new_out_is_accepted_and_leaves_no_temp_files(tmp_path):
    (tmp_path / "empty").mkdir()
    for name in ("empty", "new"):
        res = _run(tmp_path / name)
        assert res["decision"] and "plan.json" in res["outputs"]
        assert not [n for n in _listing(tmp_path / name) if n.startswith(".tmp-") or n.endswith(".lock")]


def test_non_empty_out_is_an_error_and_names_the_flag(tmp_path):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TcpError) as e:
        _run(tmp_path)
    assert e.value.code == "OUT_DIR_NOT_EMPTY" and "--overwrite" in e.value.message
    assert _listing(tmp_path) == ["keep.txt"]


def test_cli_non_empty_out_exits_2_with_the_exact_flag(tmp_path, capsys):
    (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
    assert main(["--offline", "supported", "--no-dwt", "--out", str(tmp_path)]) == 2
    assert "--overwrite" in capsys.readouterr().err
    assert _listing(tmp_path) == ["keep.txt"]


def test_overwrite_replaces_a_previous_run(tmp_path):
    first = _run(tmp_path / "o")
    with pytest.raises(TcpError):
        _run(tmp_path / "o")
    again = _run(tmp_path / "o", overwrite=True)
    assert again["plan_hash"] == first["plan_hash"] and again["outputs"] == first["outputs"]


def test_outputs_are_sealed_in_the_store_with_matching_sha256(tmp_path):
    run = pipeline.Run(tmp_path / "o")
    run.write("a.json", {"b": 1, "a": 2})
    with open(run.path("img.png"), "wb") as f: f.write(b"\x89PNG-bytes")
    run.adopt("img.png")
    for name, ref in run.refs.items():
        with open(run.path(name), "rb") as f: assert hashlib.sha256(f.read()).hexdigest() == ref.sha256
    assert run.written == ["a.json", "img.png"]


def test_rewriting_an_output_with_different_content_fails(tmp_path):
    run = pipeline.Run(tmp_path / "o")
    run.write("a.json", {"v": 1})
    run.write("a.json", {"v": 1})  # same bytes: fine
    with pytest.raises(Exception) as e:
        run.write("a.json", {"v": 2})
    assert "already holds different bytes" in str(e.value)
