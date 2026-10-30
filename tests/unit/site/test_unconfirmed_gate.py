"""AI_ONLY_UNCONFIRMED facts stay rule inputs, and any result that used one is REVIEW_REQUIRED with the fact named
(S6 STOP 1, point 2). Also: the live script's TLS rules (point 4)."""
import json, os, re

import pytest

from tcp_planner.ai.call1 import (MARKS_AGREE, MARKS_DISAGREE, MARKS_MISSING, Call1Result, FIELDS, Observation, _norm_value,
                                  map_work_location)
from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO, UNSUPPORTED_POC
from tcp_planner.site_model.facts import RuleInputs, SiteFact, rule_inputs
from tcp_planner.site_model.site_config import call1_setting, confidence_floor

FLOOR = confidence_floor("work_location")[0]
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _wl(marks):
    obs = Observation(field="work_location", value="ROADWAY", status="RESOLVED", confidence=0.95, evidence="e")
    return map_work_location(obs, marks, FLOOR)[0]


def test_the_flag_is_set_exactly_when_the_marks_are_missing():
    assert "AI_ONLY_UNCONFIRMED" in _wl(MARKS_MISSING).flags
    assert "AI_ONLY_UNCONFIRMED" not in _wl(MARKS_AGREE).flags


def test_unconfirmed_fact_stays_a_rule_input_and_is_named():
    inputs = rule_inputs([_wl(MARKS_MISSING)])
    assert isinstance(inputs, RuleInputs) and list(inputs) == ["work_location"] and inputs.unconfirmed == ["work_location"]
    assert inputs["work_location"].value == "IN_LANE"


def test_a_result_that_used_it_is_review_required_with_the_fact_named():
    inputs = rule_inputs([_wl(MARKS_MISSING)])
    decision, reasons = inputs.gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED
    assert [r["fact"] for r in reasons] == ["work_location"] and "work_location" in reasons[0]["reason"]


def test_a_confirmed_fact_does_not_change_the_decision():
    assert rule_inputs([_wl(MARKS_AGREE)]).gate(SUPPORTED_AUTO) == (SUPPORTED_AUTO, [])


def test_a_result_that_did_not_read_the_fact_is_not_gated():
    other = SiteFact(field="median_work", registry_id="median_work", value=False, source="AI", outcome="FOUND")
    inputs = rule_inputs([_wl(MARKS_MISSING), other])
    assert inputs.gate(SUPPORTED_AUTO, used=["median_work"]) == (SUPPORTED_AUTO, [])
    assert inputs.gate(SUPPORTED_AUTO, used=["median_work", "work_location"])[0] == REVIEW_REQUIRED


def test_a_worse_decision_is_kept_and_the_reason_is_still_listed():
    decision, reasons = rule_inputs([_wl(MARKS_MISSING)]).gate(UNSUPPORTED_POC)
    assert decision == UNSUPPORTED_POC and reasons


def test_the_flag_cannot_be_dropped_between_the_fact_and_the_result():
    """Through serialization, a copy, the stored record and the rule-input gate the flag is still there."""
    fact = _wl(MARKS_MISSING)
    stored = SiteFact.model_validate(json.loads(fact.model_dump_json()))          # persisted and read back
    copied = stored.model_copy(update={"evidence": "changed text"})                # an ordinary update keeps flags
    for f in (fact, stored, copied):
        assert "AI_ONLY_UNCONFIRMED" in f.flags
        assert rule_inputs([f]).gate(SUPPORTED_AUTO)[0] == REVIEW_REQUIRED


def test_the_only_reader_of_facts_for_rules_returns_the_flagged_fact_itself():
    fact = _wl(MARKS_MISSING)
    assert rule_inputs([fact])["work_location"] is fact                            # no rebuilt copy that could lose a flag


def test_to_site_facts_carries_the_flag_into_the_gate():
    from tcp_planner.ai.call1 import to_site_facts
    obs = {}
    for r in FIELDS:
        v = {"bool": "false", "count": "1", "text": "NONE"}.get(r.kind) or ("ROADWAY" if r.name == "work_location" else r.values[0])
        obs[r.name] = Observation(field=r.name, value=_norm_value(r, v), status="RESOLVED", confidence=0.95, evidence="e")
    facts, _ = to_site_facts(Call1Result(obs, (), ()), work_location_marks=MARKS_MISSING)
    decision, reasons = rule_inputs(facts).gate(SUPPORTED_AUTO)
    assert decision == REVIEW_REQUIRED and [r["fact"] for r in reasons] == ["work_location"]


# ---------------------------------------------------------------- TLS (point 4)
def _src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


def test_no_module_that_can_call_the_model_turns_certificate_checks_off():
    bad = re.compile(r"verify\s*=\s*False|CERT_NONE|_create_unverified_context|check_hostname\s*=\s*False|REQUESTS_CA_BUNDLE\s*=\s*['\"]{2}")
    for parts in (("scripts", "s06_call1_check.py"), ("src", "tcp_planner", "ai", "call1.py"),
                  ("src", "tcp_planner", "ai", "foundry_provider.py"), ("src", "tcp_planner", "imagery", "prepare.py")):
        assert not bad.search(_src(*parts)), parts


def test_the_live_script_trusts_the_os_store_before_any_call(monkeypatch, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("s06_call1_check", os.path.join(ROOT, "scripts", "s06_call1_check.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m, "OUT", str(tmp_path))
    monkeypatch.setenv("TCP_LIVE", "1"); monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "k"); monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://e")
    order = []
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.load_env_file", lambda *a, **k: order.append("env"))
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.use_os_trust_store", lambda: order.append("trust"))

    class Reply: text = ""; truncated = False; usage = {}
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda *a, **k: order.append("call") or Reply())
    m.main(["--profile", "gpt-5.6-sol", "--only", "1"])
    assert order[:3] == ["env", "trust", "call"]


def test_the_trust_store_call_comes_before_the_provider_imports_in_the_script():
    src = _src("scripts", "s06_call1_check.py")
    assert src.index("use_os_trust_store()") < src.index("from tcp_planner.ai import call1\n    from tcp_planner.ai.foundry_provider")
