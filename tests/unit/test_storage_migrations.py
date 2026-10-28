import pytest

from tcp_planner.storage import migrations as M
from tcp_planner.storage.interfaces import SchemaVersionError
from tcp_planner.storage.memory import InMemoryStateStore
from tcp_planner.storage.sqlite_state import SqliteStateStore

KIND = "test_widget"


@pytest.fixture(autouse=True)
def _steps():
    saved = dict(M._STEPS)
    M._STEPS[(KIND, 1)] = lambda v: {**{k: x for k, x in v.items() if k != "name"}, "label": v["name"]}
    M._STEPS[(KIND, 2)] = lambda v: {**v, "tags": sorted(v.get("tags", []))}
    yield
    M._STEPS.clear(); M._STEPS.update(saved)


def test_chain_runs_in_order_and_reports_hashes():
    v1 = {"name": "a", "tags": ["z", "b"]}
    out, rep = M.migrate(KIND, v1, 1, 3)
    assert out == {"label": "a", "tags": ["b", "z"]}
    assert [s["from"] for s in rep["steps"]] == [1, 2] and rep["to_version"] == 3
    assert v1 == {"name": "a", "tags": ["z", "b"]}  # input untouched
    out2, rep2 = M.migrate(KIND, v1, 1, 3)
    assert out2 == out and rep2 == rep  # deterministic, hash-verified


def test_same_version_is_identity_and_gap_or_downgrade_fails():
    out, rep = M.migrate(KIND, {"x": 1}, 3, 3)
    assert out == {"x": 1} and rep["steps"] == [] and rep["input_sha256"] == rep["output_sha256"]
    with pytest.raises(SchemaVersionError): M.migrate(KIND, {}, 3, 4)       # no step 3 -> 4
    with pytest.raises(SchemaVersionError): M.migrate(KIND, {}, 4, 3)       # record newer than code
    with pytest.raises(SchemaVersionError): M.migrate("unknown_kind", {}, 1, 2)


def test_duplicate_registration_rejected():
    with pytest.raises(SchemaVersionError): M.register(KIND, 1)(lambda v: v)


@pytest.mark.parametrize("make", [lambda p: InMemoryStateStore(), lambda p: SqliteStateStore(p / "s.db")])
def test_round_trip_through_a_state_store(tmp_path, make):
    st = make(tmp_path)
    st.put_new("w/1", {"name": "a", "tags": ["z", "b"]}, 1)
    assert M.read_current(st, "w/1", KIND, 3) == {"label": "a", "tags": ["b", "z"]}
    assert st.get("w/1").schema_version == 1 and st.get("w/1").value["name"] == "a"  # stored record unchanged
    st.compare_and_set("w/1", 1, {"label": "a", "tags": []}, 3)
    assert M.read_current(st, "w/1", KIND, 3) == {"label": "a", "tags": []}
    assert M.read_current(st, "w/none", KIND, 3) is None
