"""The committed S5 review report matches the catalog and the pack, and lists what the owner asked for."""
from scripts.device_catalog_report import EDITION_LINE, OUT, build_report
from tcp_planner.rules.device_catalog import load_catalog
from tcp_planner.rules.rule_pack_store import JsonRulePackStore


def _committed():
    with open(OUT, encoding="utf-8") as f: return f.read().replace("\r\n", "\n")


def test_committed_report_matches_catalog_and_pack():
    assert _committed() == build_report(load_catalog(), JsonRulePackStore().load()), "run: python scripts/device_catalog_report.py"


def test_report_lists_client_state_and_review_required_entries():
    text, cat = _committed(), load_catalog()
    assert EDITION_LINE in text.splitlines()[:5]
    for h in ("## CLIENT_CODE and STATE_CODE entries", "## SOURCE_REVIEW_REQUIRED entries", "## Aliases (printed_as)",
              "## Signs with no freeway size", "## Entries no TA uses"):
        assert h in text
    for e in cat.entries:
        if e.code_status.value in ("CLIENT_CODE", "STATE_CODE"): assert f"| {e.device_id} |" in text
