"""Regenerate the stored expected outputs of the 13 offline scenarios (tests/fixtures/expected/offline/).

  python -m tests.support.make_expected          write; refuses to overwrite a different stored output unless --force

The stored files are the oracle for tests/integration/review_assistant/test_global_identity.py (it used to compare against
a git-archive of HEAD). Regenerate only for an intended pipeline output change, and review the diff like code.
Only the volatile timestamps (generated_at, retrieved_at) are masked; every other byte is compared.
"""
import json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPECTED = os.path.join(ROOT, "tests", "fixtures", "expected", "offline")
VOLATILE = re.compile(rb'"(generated_at|retrieved_at)": "[^"]*"')
SCENARIOS = ("supported", "four_lane", "one_way", "missing_lane_count", "missing_road_type", "lane_conflict", "poor_image",
             "encroach", "lane_closure", "intersection", "sidewalk", "ai_unavailable", "driveway_at_sign")


def run_offline(out, sc, flag="false", extra=()):
    """Run the offline scenario in a subprocess with a clean environment. Returns the exit code."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TCP_", "AZURE", "ANTHROPIC"))}
    env["TCP_SME_ASSISTANT_ENABLED"] = flag; env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    r = subprocess.run([sys.executable, "-m", "tcp_planner.orchestration.pipeline", "--offline", sc, "--no-dwt",
                        "--out", str(out), *extra], cwd=ROOT, env=env, capture_output=True, text=True)
    return r.returncode


def json_files(d):
    """{name: bytes} of every .json in d, volatile timestamps masked."""
    out = {}
    for n in sorted(os.listdir(d)):
        if n.endswith(".json"):
            with open(os.path.join(d, n), "rb") as f: out[n] = VOLATILE.sub(rb'"\1": "<volatile>"', f.read())
    return out


def stored(name):
    """(exit_code, {file: bytes}) stored for a scenario; name is a scenario or 'supported_kml'."""
    d = os.path.join(EXPECTED, name)
    with open(os.path.join(d, "exit_code.json"), encoding="utf-8") as f: code = json.load(f)["exit_code"]
    files = {}
    for n in sorted(os.listdir(d)):
        if n != "exit_code.json":
            with open(os.path.join(d, n), "rb") as f: files[n] = f.read()
    return code, files


def write(name, code, files, force):
    d = os.path.join(EXPECTED, name)
    if os.path.isdir(d) and not force:
        old = stored(name)
        if old != (code, files): raise SystemExit(f"{name}: stored output differs from a fresh run; use --force if intended")
        return
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "exit_code.json"), "w", encoding="utf-8") as f: json.dump({"exit_code": code}, f)
    for n, b in files.items():
        with open(os.path.join(d, n), "wb") as f: f.write(b)


def main(argv=None):
    force = "--force" in (argv or sys.argv[1:])
    with tempfile.TemporaryDirectory() as tmp:
        for sc in SCENARIOS:
            out = os.path.join(tmp, sc); code = run_offline(out, sc)
            write(sc, code, json_files(out), force); print("stored", sc, code)
        out = os.path.join(tmp, "kml"); code = run_offline(out, "supported", "true", ("--offline-input", "kml"))
        write("supported_kml", code, json_files(out), force); print("stored supported_kml", code)


if __name__ == "__main__":
    main()
