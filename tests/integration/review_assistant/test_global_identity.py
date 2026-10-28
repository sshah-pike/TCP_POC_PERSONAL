"""Global protection tests: no-revision pipeline output is byte-identical to the stored expected output of the 13 offline
scenarios (pre-assistant pipeline), with the assistant flag off and on; validators / rule pack untouched; protected run directory tracked and unchanged."""
import os, subprocess

import pytest

from tests.support.make_expected import SCENARIOS, json_files, run_offline, stored

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PROTECTED = "var/runs/20261020-214203-7f7232"


@pytest.mark.parametrize("sc", SCENARIOS)
def test_no_revision_outputs_match_stored_expected(tmp_path, sc):
    """Assistant flag off and on both reproduce the stored expected output (tests/fixtures/expected/offline/)."""
    code, files = stored(sc)
    for label, flag in (("off", "false"), ("on", "true")):
        assert run_offline(tmp_path / label, sc, flag) == code
        got = json_files(tmp_path / label)
        assert got == files
    assert not (tmp_path / "on" / "machine_site_model.json").exists()


def test_kml_input_matches_stored_expected(tmp_path):
    code, files = stored("supported_kml")
    assert run_offline(tmp_path / "now", "supported", "true", ("--offline-input", "kml")) == code
    assert json_files(tmp_path / "now") == files


def test_validators_rule_pack_and_core_rules_unchanged():
    r = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "src/tcp_planner/validation/validators.py",
                        "src/tcp_planner/layout/rule_engine.py", "src/tcp_planner/geometry/local_frame.py",
                        "src/tcp_planner/site_model/fusion.py", "rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json",
                        "config/pipeline_config.json"], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == ""


def test_protected_run_directory_tracked_and_unchanged():
    """The protected run directory is tracked (since b94fafd) and still equals HEAD (the 16 files committed in
    b94fafd; the rest of the folder is gitignored under var/) (D-79)."""
    d = os.path.join(ROOT, PROTECTED)
    if not os.path.isdir(d): pytest.skip("protected run directory not present on this machine")
    tracked = subprocess.run(["git", "ls-files", "--", PROTECTED], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    assert len(tracked) == 16 and all(os.path.isfile(os.path.join(ROOT, t)) for t in tracked)   # none deleted
    r = subprocess.run(["git", "status", "--porcelain", "--", PROTECTED], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == ""   # no tracked file modified or deleted, nothing staged
