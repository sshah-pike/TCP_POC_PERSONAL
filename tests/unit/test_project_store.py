"""S2 commit 7: project store helper, RulePackStore interface, shared raw-path finder."""
import hashlib

import pytest

from tcp_planner.storage import stores
from tcp_planner.storage.interfaces import RulePackStore, StateExists, StaleHead, StorageError
from tcp_planner.storage.memory import InMemoryArtifactStore, InMemoryStateStore
from tcp_planner.storage.project_store import ProjectStore, input_name
from tcp_planner.storage.rawpaths import find_raw_paths


@pytest.fixture(params=["memory", "files"])
def projects(request, tmp_path, monkeypatch):
    if request.param == "memory": return ProjectStore(InMemoryStateStore(), InMemoryArtifactStore())
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    return ProjectStore(stores.state(), stores.artifacts())


def test_create_get_list(projects):
    rec = projects.create("P-001", {"name": "Main St", "zones": []})
    assert rec["project_id"] == "P-001" and rec["created_at"] and rec["name"] == "Main St"
    assert projects.get("P-001") == rec and projects.get("nope") is None
    projects.create("P-002", {})
    assert [p["project_id"] for p in projects.list()] == ["P-001", "P-002"]
    with pytest.raises(StateExists): projects.create("P-001", {})


def test_reserved_fields_bad_ids_and_raw_paths_are_refused(projects):
    for bad in ({"project_id": "x"}, {"created_at": "x"}):
        with pytest.raises(StorageError): projects.create("P-1", bad)
    for bad_id in ("", "../x", "a/b", "-x", "x" * 65, "a b"):
        with pytest.raises(StorageError): projects.create(bad_id, {})
    for path in ("C:\\runs\\r1\\site.kml", "/home/u/site.kml", "../site.kml"):
        with pytest.raises(StorageError, match="raw path"): projects.create("P-1", {"kml": path})
    assert projects.get("P-1") is None


def test_update_is_compare_and_set_and_keeps_the_identity_fields(projects):
    projects.create("P-1", {"n": 1})
    assert projects.update("P-1", lambda r: {**r, "n": 2})["n"] == 2
    with pytest.raises(StorageError): projects.update("P-1", lambda r: {**r, "project_id": "other"})
    with pytest.raises(StorageError, match="raw path"): projects.update("P-1", lambda r: {**r, "p": "C:\\x\\y"})
    with pytest.raises(StorageError): projects.update("missing", lambda r: r)
    calls = []

    def racing(r):  # another writer gets in between the read and the write: the update is retried on the new record
        if not calls:
            calls.append(1); projects.update("P-1", lambda x: {**x, "other": True})
        return {**r, "n": 3}
    out = projects.update("P-1", racing)
    assert out["n"] == 3 and out["other"] is True


def test_inputs_are_write_once_store_keys(projects):
    projects.create("P-1", {})
    ref = projects.put_input("P-1", "C:\\Users\\me\\My Site (1).kml", b"<kml/>")
    assert ref.uri == "projects/P-1/input/My_Site__1_.kml" and ref.sha256 == hashlib.sha256(b"<kml/>").hexdigest()
    assert projects.get_input(ref) == b"<kml/>"
    projects.update("P-1", lambda r: {**r, "input": ref.to_dict()})  # the record holds the key, not a path
    assert projects.put_input("P-1", "C:\\other\\My Site (1).kml", b"<kml/>") == ref  # same bytes: fine
    with pytest.raises(Exception): projects.put_input("P-1", "My Site (1).kml", b"<kml>different</kml>")
    with pytest.raises(StorageError): projects.put_input("nope", "a.kml", b"x")


def test_input_names():
    assert input_name("a/b/../c d.kml") == "c_d.kml" and input_name("..\\.hidden") == "hidden" and input_name("???") == "input"


def test_project_state_lives_in_the_shared_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    p = ProjectStore(stores.state(), stores.artifacts())
    p.create("P-1", {}); p.put_input("P-1", "s.kml", b"<kml/>")
    assert (tmp_path / "runs" / "_shared" / "projects" / "P-1.state.json").is_file()
    assert (tmp_path / "runs" / "projects" / "P-1" / "input" / "s.kml").is_file()


def test_json_rule_pack_store_conforms_to_the_interface():
    import inspect
    from tcp_planner.rules.rule_pack_store import JsonRulePackStore
    assert RulePackStore.__abstractmethods__ == {"list_versions", "load", "content_hash"}
    with pytest.raises(TypeError): RulePackStore()
    assert issubclass(JsonRulePackStore, RulePackStore)
    assert isinstance(JsonRulePackStore(), RulePackStore)
    for name in RulePackStore.__abstractmethods__:
        assert inspect.signature(getattr(JsonRulePackStore, name)) == inspect.signature(getattr(RulePackStore, name)), name


def test_shared_raw_path_finder():
    assert len(find_raw_paths({"a": "C:\\x\\y", "b": "/home/u/f", "c": "../x", "d": ["\\\\srv\\s\\f"], "e": {"C:/k": 1}})) == 5
    assert find_raw_paths({"uri": "20261013-131822-3a950b/output/plan.json", "t": "50 ft / 100 ft", "u": "https://x/y/z"}) == []
