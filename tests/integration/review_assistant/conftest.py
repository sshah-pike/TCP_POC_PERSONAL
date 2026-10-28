import json, os, sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

USERS = {"users": [{"subject_id": "sme.1", "display_name": "SME One", "roles": ["SME_REVIEWER"]},
                   {"subject_id": "aud.1", "display_name": "Auditor One", "roles": ["AUDITOR"]},
                   {"subject_id": "adm.1", "display_name": "Admin One", "roles": ["ADMIN"]},
                   {"subject_id": "bad.1", "display_name": "Bad", "roles": ["SME_REVIEWER"], "password": "x"}]}


@pytest.fixture
def aenv(tmp_path, monkeypatch):
    """Assistant enabled, isolated data dir, runs dir and users file."""
    users = tmp_path / "users.local.json"; users.write_text(json.dumps(USERS), encoding="utf-8")
    monkeypatch.setenv("TCP_SME_ASSISTANT_ENABLED", "true")
    monkeypatch.setenv("TCP_ASSISTANT_DATA_DIR", str(tmp_path / "assistant_data"))
    monkeypatch.setenv("TCP_ASSISTANT_USERS_FILE", str(users))
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "runs").mkdir()
    from tcp_planner.review.assistant.services import container
    container.reset()
    yield tmp_path
    container.reset()


def call(method, path, payload=None, token=None):
    from tcp_planner.review.assistant import routes as api
    parts = [p for p in path.strip("/").split("/") if p]
    return api.dispatch(method, parts, {}, payload, {"X-TCP-Session": token})


def login(subject="sme.1"):
    st, _, body = call("POST", "sessions", {"subject_id": subject})
    assert st == 201, body
    return body["session_token"]


SCENARIOS = ("supported", "missing_road_type", "lane_conflict", "driveway_at_sign", "intersection", "four_lane", "sidewalk")


@pytest.fixture(scope="session")
def run_library(tmp_path_factory):
    """Offline UI-created runs (real runner -> pipeline, evidence saved), built once: scenario -> run_id."""
    root = tmp_path_factory.mktemp("runlib")
    old = os.environ.get("TCP_UI_RUNS_DIR"); os.environ["TCP_UI_RUNS_DIR"] = str(root)
    from tcp_planner.orchestration import offline_scenarios as offline
    from tcp_planner.storage import run_store as store
    from tests.integration.web_api import inproc
    ids = {}
    try:
        for sc in SCENARIOS:
            rid, rdir = store.create_run({"input_type": "offline", "offline_scenario": sc, "offline_input": "coordinates",
                                          "advanced": {"no_dwt": True}}, set(offline.SCENARIOS))
            inproc.run(rdir); ids[sc] = rid
    finally:
        if old is None: os.environ.pop("TCP_UI_RUNS_DIR", None)
        else: os.environ["TCP_UI_RUNS_DIR"] = old
    return root, ids


@pytest.fixture
def runs(aenv, run_library):
    """Copy of the run library inside this test's runs dir. Returns scenario -> run_id."""
    import shutil
    root, ids = run_library
    for rid in ids.values(): shutil.copytree(root / rid, aenv / "runs" / rid)
    return ids


def tree_hash(path):
    import hashlib
    h = {}
    for d, _, files in os.walk(path):
        for n in files:
            p = os.path.join(d, n)
            with open(p, "rb") as f: h[os.path.relpath(p, path)] = hashlib.sha256(f.read()).hexdigest()
    return h
