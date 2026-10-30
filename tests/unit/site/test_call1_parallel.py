"""--parallel N on the owner's live script (D-104). A fake sender: nothing is called live."""
import importlib.util, json, os, threading, time

import pytest

from tcp_planner.contracts import ProviderError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SPIKE = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "raw")


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("s06_call1_check", os.path.join(ROOT, "scripts", "s06_call1_check.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m, "OUT", str(tmp_path / "out"))
    monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "SECRET-KEY-123"); monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("TCP_LIVE", "1")
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.load_env_file", lambda *a, **k: None)
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.use_os_trust_store", lambda: None)
    return m


def _text():
    d = json.load(open(os.path.join(SPIKE, "granite_B_r1.response.json"), encoding="utf-8"))
    return next(b["text"] for b in d["content"] if b.get("type") == "text")


class Reply:
    def __init__(self): self.text, self.truncated, self.model, self.request_id = _text(), False, "m", "r"; self.usage = {"input_tokens": 3600, "output_tokens": 2100}


def test_default_is_one_at_a_time(script, monkeypatch):
    active, peak = [0], [0]; lock = threading.Lock()

    def send(p, r, send=None):
        with lock: active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        with lock: active[0] -= 1
        return Reply()
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", send)
    assert script.main(["--profile", "gpt-5.6-sol"]) == 0
    assert peak[0] == 1


def test_parallel_prints_wall_time_and_per_call_time(script, monkeypatch, capsys):
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: Reply())
    assert script.main(["--profile", "gpt-5.6-sol", "--parallel", "3"]) == 0
    out = capsys.readouterr().out
    assert "running 9 calls, 3 at a time" in out and "wall time" in out and "per-call seconds" in out and "HTTP 429: 0" in out and "ok 9, errors 0" in out


def test_parallel_peak_concurrency_is_n(script, monkeypatch):
    active, peak = [0], [0]; lock = threading.Lock(); gate = threading.Event()

    def send(p, r, send=None):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
            if active[0] >= 3: gate.set()
        gate.wait(5)
        with lock: active[0] -= 1
        return Reply()
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", send)
    assert script.main(["--profile", "gpt-5.6-sol", "--parallel", "3"]) == 0
    assert peak[0] == 3


def test_parallel_reports_every_429_and_error_body_and_skips_nothing(script, monkeypatch, capsys):
    seen = []; lock = threading.Lock()

    def send(p, r, send=None):
        with lock: seen.append(1); n = len(seen)
        if n % 3 == 0:
            raise ProviderError("AI_RATE_LIMITED", "slow down", {"http_status": 429, "api_error_text": "Rate limit exceeded: retry after 7s"})
        if n == 4: raise ProviderError("AI_BAD_REQUEST", "bad", {"http_status": 400, "api_error_text": "image rejected"})
        return Reply()
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", send)
    code = script.main(["--profile", "gpt-5.6-sol", "--parallel", "4"])
    out = capsys.readouterr().out
    assert code == 1 and len(seen) == 9                                      # no call skipped after an error
    assert out.count("HTTP status: 429") == 3 and "Rate limit exceeded: retry after 7s" in out
    assert "HTTP status: 400" in out and "image rejected" in out and "SECRET-KEY-123" not in out
    assert "HTTP 429: 3" in out and "errors 4" in out


def test_parallel_saves_one_result_file_per_ok_call(script, monkeypatch):
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: Reply())
    script.main(["--profile", "gpt-5.6-sol", "--parallel", "2", "--from", "7"])
    saved = sorted(os.listdir(os.path.join(script.OUT, "gpt-5.6-sol")))
    assert saved == ["call7.json", "call8.json", "call9.json"]


def test_parallel_dry_run_prints_bodies_and_calls_nothing(script, monkeypatch, capsys):
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: pytest.fail("a call was made"))
    assert script.main(["--profile", "gpt-5.6-sol", "--parallel", "3", "--dry-run", "--from", "8"]) == 0
    out = capsys.readouterr().out
    assert out.count("request body") == 2 and "=== call 8" in out and "=== call 9" in out and "SECRET-KEY-123" not in out


def test_parallel_below_one_is_refused(script):
    assert script.main(["--profile", "gpt-5.6-sol", "--parallel", "0"]) == 2


def test_the_command_for_d104_is_in_the_script_help():
    src = open(os.path.join(ROOT, "scripts", "s06_call1_check.py"), encoding="utf-8").read()
    assert "--profile gpt-5.6-sol --parallel 3" in src and "D-104" in src
