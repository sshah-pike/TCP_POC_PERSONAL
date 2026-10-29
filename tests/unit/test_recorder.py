"""S2 5b: the worker's Recorder writes state records, reports failures once per distinct error, and retries the final
record."""
import math
import pathlib

import pytest

from tcp_planner.orchestration import run_worker as w
from tcp_planner.storage import run_records as records

RID = "20261029-120000-abcdef"


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(w.time, "sleep", lambda s: None)
    return tmp_path / "runs"


def test_write_and_event_land_as_state_records_in_the_run_folder(runs):
    rec = w.Recorder(RID)
    assert rec.write("process", {"state": "RUNNING"}) and rec.write("process", {"state": "FINISHED"})
    rec.event(event="span_start", name="tcp.input.parse")
    rec.event(event="process_finished", durable=True)
    assert records.read(RID, "process") == {"state": "FINISHED"}
    assert [e["event"] for e in records.events(RID)] == ["span_start", "process_finished"]
    assert sorted(p.name for p in (runs / RID / "ui").iterdir()) == ["events.events.jsonl", "process.state.json"]


def test_non_json_values_are_stored_as_text_like_before(runs):
    rec = w.Recorder(RID)
    assert rec.write("result", {"p": pathlib.Path("a"), "n": math.nan, "t": (1, 2)})
    assert records.read(RID, "result") == {"p": "a", "n": "NaN", "t": [1, 2]}


def test_list_records_round_trip(runs):
    rec = w.Recorder(RID)
    rec.add_usage({"calls": 1}); rec.add_usage({"calls": 2})
    assert records.read(RID, "usage") == [{"calls": 1}, {"calls": 2}]


def test_failures_are_reported_once_per_distinct_error_and_never_raised(runs, monkeypatch, capsys):
    def boom(*a, **k): raise OSError("disk full")
    monkeypatch.setattr(records, "append_event", boom); monkeypatch.setattr(records, "write", boom)
    rec = w.Recorder(RID)
    for _ in range(5):
        rec.event(event="span_start"); assert rec.write("usage", []) is False
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[recorder]")]
    assert len(lines) == 2 and "disk full" in lines[0] and "event span_start" in lines[0] and "write usage" in lines[1]
    def other(*a, **k): raise OSError("access denied")
    monkeypatch.setattr(records, "append_event", other)
    rec.event(event="span_start")  # a different error is reported again
    assert "access denied" in capsys.readouterr().out


def test_final_record_is_retried_then_raises(runs, monkeypatch):
    real, calls = records.write, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3: raise OSError("locked")
        return real(*a, **k)
    monkeypatch.setattr(records, "write", flaky)
    w.Recorder(RID).write_final("process", {"state": "FINISHED"})
    assert len(calls) == 3 and records.read(RID, "process") == {"state": "FINISHED"}

    def always(*a, **k): raise OSError("locked")
    monkeypatch.setattr(records, "write", always)
    with pytest.raises(w.RecorderWriteError, match="process"):
        w.Recorder(RID).write_final("process", {"state": "FINISHED"})


def test_durable_flag_is_passed_through(runs, monkeypatch):
    seen = []
    monkeypatch.setattr(records, "append_event", lambda run_id, ev, durable=False: seen.append(durable))
    rec = w.Recorder(RID)
    rec.event(event="span_start"); rec.event(event="run_result", durable=True)
    assert seen == [False, True]


def test_result_record_holds_the_run_relative_key_not_the_folder():
    rec = w._result_record({"decision": "X", "out_dir": r"C:\runs\r1\output"}, "r1")
    assert rec == {"decision": "X", "out_key": "r1/output"}


def test_observer_failures_are_reported_once_per_distinct_error(runs, monkeypatch, capsys):
    """The worker's observers (diagnostics, usage, rule pack, TLS) no longer swallow their errors silently."""
    rec = w.Recorder(RID)
    import tcp_planner.audit.provider_diagnostics as pd
    monkeypatch.setattr(pd, "describe", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cannot describe")))
    for _ in range(3): w._record(rec, ValueError("x"), "azure", 0.0)
    rec.note("usage record", KeyError("model")); rec.note("usage record", KeyError("model"))
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[recorder]")]
    assert len(lines) == 2
    assert "provider diagnostic record failed" in lines[0] and "cannot describe" in lines[0]
    assert "usage record failed" in lines[1]


def test_no_observer_swallows_an_error_silently():
    import inspect
    src = inspect.getsource(w)
    assert "except Exception:\n            pass" not in src and "except Exception:\n        pass" not in src
    assert "except Exception:\n                pass" not in src and "except Exception:\n                    pass" not in src
