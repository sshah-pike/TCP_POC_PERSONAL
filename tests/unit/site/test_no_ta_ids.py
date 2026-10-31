"""No TA id in the S6 site-understanding code added under the owner's resume prompt (2026-10-31). Site understanding observes the
site; choosing a TA is the S7 router's job and is driven by the rule pack, never by this code.

Two older modules name TA ids and are listed here on purpose (they predate the rule): site_model/precalc.py (S6 STOP 3: the shadow vehicle
note texts and the TA-6 remaining-width labels) and site_model/fusion.py (the old pipeline's fusion). Any other file that gains a TA id
fails this test.
"""
import os
import re

from tcp_planner.config import settings

ROOT = settings.PROJECT_ROOT
PATTERN = re.compile(r"\bTA[-_ ]?(?:1|6|10|33)\b|\bTA[0-9]|\bta_id\b|\bTA-\d+")
PREDATING = {"src/tcp_planner/site_model/precalc.py", "src/tcp_planner/site_model/fusion.py"}


def _files():
    roots = ["src/tcp_planner/site_model", "src/tcp_planner/data_sources", "prompts", "config/site_understanding.json", "config/data_sources.json",
             "config/site_exceptions.json"]
    singles = ["src/tcp_planner/imagery/snap.py", "src/tcp_planner/imagery/crops.py", "src/tcp_planner/ai/call1.py", "src/tcp_planner/ai/prompt_registry.py"]
    out = []
    for r in roots:
        p = os.path.join(ROOT, r)
        if os.path.isfile(p): out.append(r); continue
        for dp, _, names in os.walk(p):
            for n in names:
                if n.endswith((".py", ".txt", ".json")): out.append(os.path.relpath(os.path.join(dp, n), ROOT).replace("\\", "/"))
    out += singles
    out += sorted("scripts/" + n for n in os.listdir(os.path.join(ROOT, "scripts")) if n.startswith("s06_") and n.endswith(".py"))
    return sorted(set(out))


def test_no_s06_file_added_since_the_rule_names_a_ta_id():
    offenders = {}
    for rel in _files():
        if rel in PREDATING: continue
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        hits = PATTERN.findall(text)
        if hits: offenders[rel] = hits[:3]
    assert offenders == {}, offenders


def test_the_files_that_predate_the_rule_are_exactly_the_two_listed():
    named = {rel for rel in _files() if PATTERN.search(open(os.path.join(ROOT, rel), encoding="utf-8").read())}
    assert named <= PREDATING, named - PREDATING


def test_the_scan_covers_the_new_modules():
    files = set(_files())
    for rel in ("src/tcp_planner/site_model/understanding.py", "src/tcp_planner/site_model/code_checks.py", "src/tcp_planner/site_model/consistency.py",
                "src/tcp_planner/site_model/bearing_check.py", "src/tcp_planner/site_model/edge_rule.py", "src/tcp_planner/site_model/osm_rules.py",
                "src/tcp_planner/site_model/fusion_apply.py", "src/tcp_planner/site_model/site_exceptions.py", "src/tcp_planner/data_sources/osm.py",
                "src/tcp_planner/imagery/snap.py", "prompts/call1_user.v2.txt", "config/site_exceptions.json"):
        assert rel in files, rel
    assert len(files) > 30
