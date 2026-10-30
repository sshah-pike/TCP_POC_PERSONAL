"""The committed S4 review report matches the pack, and carries the items the owner required."""
import os
from scripts.rule_pack_report import EDITION_LINE, OUT, build_report
from tcp_planner.rules.rule_pack_store import JsonRulePackStore


def _committed():
    with open(OUT, encoding="utf-8") as f: return f.read().replace("\r\n", "\n")


def test_committed_report_matches_the_pack():
    assert _committed() == build_report(JsonRulePackStore().load()), "run: python scripts/rule_pack_report.py"


def test_report_carries_the_required_sections():
    text = _committed()
    assert EDITION_LINE in text.splitlines()[:5]
    for heading in ("## Every value, with quote and page", "## Figure-only values", "## Unsourced items and their SME questions",
                    "## Proposed amendment to D-60 (Sect. 6N.11)", "## Proposals for the owner (not edited)",
                    "### source_ref count by commit", "## External inputs needed", "## S4b changes",
                    "### Records removed or replaced", "### Flags written into a device `name`", "### Size rows and the device catalog",
                    "### Add-on rules: gate and action kind", "### Follow-ups"):
        assert heading in text
    for item in ("D-51", "D-68", "Open question 15", "Open question 17", "Open question 18", "S8 client modules"):
        assert f"**{item}" in text


def test_every_record_with_a_value_appears_in_the_report():
    pack, text = JsonRulePackStore().load(), _committed()
    for t in ("table_row", "formula", "rule", "eligibility_condition", "source_ref"):
        for r in pack.records(t):
            if t != "source_ref" or r.evidence.value == "FIGURE_TRANSCRIPTION":
                assert f"| {r.id} |" in text, r.id
