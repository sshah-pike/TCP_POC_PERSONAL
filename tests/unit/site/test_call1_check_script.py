"""The owner's live check script (S6 commit 2) with a fake sender: single call, body printed first, stop at the first API error."""
import importlib.util, json, os

import pytest

from tcp_planner.contracts import ProviderError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SPIKE = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "raw")


@pytest.fixture
def script(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("s06_call1_check", os.path.join(ROOT, "scripts", "s06_call1_check.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m, "OUT", str(tmp_path / "out"))
    monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "SECRET-KEY-123")
    monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("TCP_LIVE", "1")
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.load_env_file", lambda *a, **k: None)   # no .env, no global TLS change
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.use_os_trust_store", lambda: None)
    return m


def _spike_text(name="granite_B_r1"):
    doc = json.load(open(os.path.join(SPIKE, name + ".response.json"), encoding="utf-8"))
    return next(b["text"] for b in doc["content"] if b.get("type") == "text")


class _Reply:
    def __init__(self, text): self.text, self.truncated, self.model, self.request_id = text, False, "m", "r"; self.usage = {"input_tokens": 3597, "output_tokens": 2100}


def test_dry_run_prints_the_body_and_never_the_key_or_a_call(script, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: pytest.fail("a call was made"))
    assert script.main(["--profile", "gpt-5.6-sol", "--dry-run", "--only", "1"]) == 0
    out = capsys.readouterr().out
    assert "request body" in out and "tcp_site_facts" in out and "<image 447191 bytes sha256 5560a76c" in out
    assert "SECRET-KEY-123" not in out and "=== call 2" not in out


def test_live_run_needs_the_live_flag(script, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    assert script.main(["--profile", "gpt-5.6-sol", "--only", "1"]) == 2


def test_only_runs_one_call_prints_body_first_and_saves_a_result(script, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: calls.append(1) or _Reply(_spike_text()))
    assert script.main(["--profile", "claude-opus-5-5", "--only", "1"]) == 0
    out = capsys.readouterr().out
    assert len(calls) == 1 and out.index("request body") < out.index("result:") and "SECRET-KEY-123" not in out
    saved = json.load(open(os.path.join(script.OUT, "claude-opus-5-5", "call1.json"), encoding="utf-8"))
    assert saved["schema_valid"] is True and saved["input_tokens"] == 3597 and saved["lanes_per_direction"]["status"] in ("RESOLVED", "UNKNOWN")
    assert "api_key" not in json.dumps(saved).lower() and saved["fingerprint"]["api"] == "anthropic_messages"


def test_all_nine_calls_run_in_order(script, monkeypatch):
    seen = []
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: seen.append(r["image"]["sha256"]) or _Reply(_spike_text()))
    assert script.main(["--profile", "gpt-5.6-sol"]) == 0
    assert len(seen) == 9 and len(set(seen)) == 3


def test_stops_at_the_first_api_error_and_prints_status_and_body(script, capsys, monkeypatch):
    n = []
    def fake(p, r, send=None):
        n.append(1)
        if len(n) == 2: raise ProviderError("AI_BAD_REQUEST", "bad", {"http_status": 400, "api_error_text": "Invalid schema: nope"})
        return _Reply(_spike_text())
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", fake)
    assert script.main(["--profile", "gpt-5.6-sol"]) == 1
    out = capsys.readouterr().out
    assert len(n) == 2 and "HTTP status: 400" in out and "Invalid schema: nope" in out and "SECRET-KEY-123" not in out


def test_a_truncated_or_empty_reply_stops_the_run(script, capsys, monkeypatch):
    r = _Reply(""); monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, q, send=None: r)
    assert script.main(["--profile", "gpt-5.6-sol", "--only", "3"]) == 1


def test_unknown_profile_is_refused(script, capsys):
    assert script.main(["--profile", "nope", "--dry-run"]) == 2


def test_summary_prints_saved_rows(script, capsys, monkeypatch):
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: _Reply(_spike_text()))
    script.main(["--profile", "gpt-5.6-sol", "--only", "1"]); capsys.readouterr()
    assert script.main(["--profile", "gpt-5.6-sol", "--summary"]) == 0
    assert "| 1 | granite | 1 | gpt-5.6-sol |" in capsys.readouterr().out


def test_without_profile_the_default_gpt_profile_is_used_and_claude_still_works(script, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False); monkeypatch.delenv("TCP_FOUNDRY_PROFILE", raising=False)
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: pytest.fail("a call was made"))
    assert script.main(["--dry-run", "--only", "1"]) == 0
    out = capsys.readouterr().out
    assert "gpt-5.6-sol" in out
    assert script.main(["--profile", "claude-opus-5-5", "--dry-run", "--only", "1"]) == 0
    out2 = capsys.readouterr().out
    assert "claude-opus-5-5" in out2 and "output_config" in out2


def test_the_default_profile_in_config_is_gpt_5_6_sol():
    from tcp_planner.ai.foundry_provider import load_profiles
    doc = load_profiles()
    assert doc["default_profile"] == "gpt-5.6-sol" and "claude-opus-5-5" in doc["profiles"]


def test_prompt_version_2_dry_run_prints_the_enhanced_body_and_version_1_stays_the_default(script, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: pytest.fail("a call was made"))
    assert script.main(["--profile", "gpt-5.6-sol", "--dry-run", "--only", "1", "--prompt-version", "2"]) == 0
    out = capsys.readouterr().out
    assert "tcp_site_facts_v2" in out and "OUTER edges" in out and "nearest_edge_point" in out
    assert script.main(["--profile", "gpt-5.6-sol", "--dry-run", "--only", "1"]) == 0
    out1 = capsys.readouterr().out
    assert '"name": "tcp_site_facts"' in out1 and "OUTER edges" not in out1


def test_version_2_results_go_to_their_own_folder_and_say_which_version(script, tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_LIVE", "1")
    monkeypatch.setattr(script, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(script, "VERSION", 2)
    assert script.out_root() == str(tmp_path / "out") + "_v2"
    monkeypatch.setattr(script, "VERSION", 1)
    assert script.out_root() == str(tmp_path / "out")


def test_prompt_version_3_dry_run_prints_the_v3_body_and_the_default_stays_version_1(script, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: pytest.fail("a call was made"))
    assert script.main(["--profile", "gpt-5.6-sol", "--dry-run", "--only", "1", "--prompt-version", "3"]) == 0
    out = capsys.readouterr().out
    assert "tcp_site_facts_v3" in out and "centre_at_intersection" in out and "px wide at this scale" in out and "road_name" not in out
    assert script.main(["--profile", "gpt-5.6-sol", "--dry-run", "--only", "1"]) == 0
    out1 = capsys.readouterr().out
    assert '"name": "tcp_site_facts"' in out1 and "road_axis" not in out1


def test_version_3_results_go_to_their_own_folder_and_say_which_version(script, tmp_path, monkeypatch):
    monkeypatch.setattr(script, "OUT", str(tmp_path / "out"))
    monkeypatch.setattr(script, "VERSION", 3)
    assert script.out_root() == str(tmp_path / "out") + "_v3"
    monkeypatch.setattr(script, "VERSION", 2)
    assert script.out_root() == str(tmp_path / "out") + "_v2"


def test_a_version_3_live_run_saves_under_the_v3_folder_with_prompt_version_3(script, tmp_path, monkeypatch):
    seen = []
    def fake(p, r, send=None):
        seen.append(r["prompt_version"]); return _Reply(_spike_text())
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", fake)
    assert script.main(["--profile", "gpt-5.6-sol", "--only", "1", "--prompt-version", "3"]) == 0
    saved = json.load(open(os.path.join(str(tmp_path / "out") + "_v3", "gpt-5.6-sol", "call1.json"), encoding="utf-8"))
    assert seen == [3] and saved["prompt_version"] == 3 and saved["fingerprint"]["schema_name"] == "tcp_site_facts_v3"
    assert not os.path.exists(os.path.join(script.OUT, "gpt-5.6-sol"))                        # nothing written over the version 1 folder
