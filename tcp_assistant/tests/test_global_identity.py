"""Global protection tests: no-revision pipeline output is byte-identical to the committed (pre-assistant) pipeline,
with the assistant flag off and on; validators / rule pack untouched; protected untracked run directory untouched."""
import hashlib, io, os, re, subprocess, sys, tarfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOLATILE = re.compile(rb'"(generated_at|retrieved_at)": "[^"]*"')
SCENARIOS = ("supported", "four_lane", "one_way", "missing_lane_count", "missing_road_type", "lane_conflict", "poor_image",
             "encroach", "lane_closure", "intersection", "sidewalk", "ai_unavailable", "driveway_at_sign")
PROTECTED = "runs/20261020-214203-7f7232"


def _head_tree(dest):
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD", "tcp_poc"], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t: t.extractall(dest, filter="data")


def _run(cwd, out, sc, flag, extra=()):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TCP_", "AZURE", "ANTHROPIC"))}
    env["TCP_SME_ASSISTANT_ENABLED"] = flag; env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "tcp_poc.app", "--offline", sc, "--no-dwt", "--out", str(out), *extra],
                       cwd=cwd, env=env, capture_output=True, text=True)
    return r.returncode


def _json_files(d):
    out = {}
    for n in sorted(os.listdir(d)):
        if n.endswith(".json"):
            with open(os.path.join(d, n), "rb") as f: out[n] = VOLATILE.sub(rb'"\1": "<volatile>"', f.read())
    return out


@pytest.fixture(scope="module")
def head_root(tmp_path_factory):
    d = tmp_path_factory.mktemp("head"); _head_tree(d)
    return d


@pytest.mark.parametrize("sc", SCENARIOS)
def test_no_revision_outputs_byte_identical_to_head(head_root, tmp_path, sc):
    codes = {}
    for label, cwd, flag in (("head", head_root, "false"), ("off", ROOT, "false"), ("on", ROOT, "true")):
        codes[label] = _run(cwd, tmp_path / label, sc, flag)
    assert codes["head"] == codes["off"] == codes["on"]
    head = _json_files(tmp_path / "head")
    assert head and head == _json_files(tmp_path / "off") == _json_files(tmp_path / "on")
    assert not (tmp_path / "on" / "machine_site_model.json").exists()


def test_kml_input_byte_identical(head_root, tmp_path):
    for label, cwd in (("head", head_root), ("now", ROOT)):
        _run(cwd, tmp_path / label, "supported", "true", ("--offline-input", "kml"))
    assert _json_files(tmp_path / "head") == _json_files(tmp_path / "now")


def test_validators_rule_pack_and_core_rules_unchanged():
    r = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "tcp_poc/validators.py", "tcp_poc/rule_engine.py",
                        "tcp_poc/geometry.py", "tcp_poc/site_fusion.py", "tcp_poc/APPROVED_TWO_LANE_POC_RULE_PACK.json",
                        "tcp_poc/poc_config.json"], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == ""


def test_protected_untracked_run_directory_untouched():
    """The pre-existing untracked run directory still has exactly the files recorded before implementation."""
    d = os.path.join(ROOT, PROTECTED)
    if not os.path.isdir(d): pytest.skip("protected run directory not present on this machine")
    files = sorted(os.path.relpath(os.path.join(a, n), d).replace("\\", "/") for a, _, ns in os.walk(d) for n in ns)
    assert len(files) == 27 and "output/plan.json" in files
    r = subprocess.run(["git", "status", "--porcelain", "--", PROTECTED], cwd=ROOT, capture_output=True, text=True)
    assert r.stdout.strip().startswith("??")
