"""Fail fast when a slice forgets to move BASELINE_REF (tests/support/guard_baseline.py).

The previous slice is the tcp-mvp/sNN branch with the highest slice number below the current one whose tip is an
ancestor of HEAD (a slice built in parallel, such as S4 beside S3, is not an ancestor and is skipped). BASELINE_REF
must equal that tip. That rule applies only to the old stacked branches tcp-mvp/s01 to s03.

Any other branch under tcp-mvp/ (s04 and later, s04b-pack-round, test-tiering, docs-decisions) is cut from
tcp-mvp/base: BASELINE_REF must equal the merge-base of HEAD with origin/tcp-mvp/base. Skipped on tcp-mvp/base,
main, detached HEAD and branches outside tcp-mvp/.
"""
import re, subprocess

import pytest

from tests.support.guard_baseline import BASELINE_REF, ROOT

SLICE_RE = re.compile(r"^tcp-mvp/s(\d+)([a-z]?)-")
BASE = "tcp-mvp/base"
LEGACY_LAST_SLICE = 3   # tcp-mvp/s01 to s03 were stacked on each other


def _git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def _slice(name):
    m = SLICE_RE.match(name)
    return (int(m.group(1)), m.group(2)) if m else None


def _previous_slice_tip(branch, current):
    tips = {}
    for line in _git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/tcp-mvp/",
                     "refs/remotes/origin/tcp-mvp/").stdout.splitlines():
        ref, sha = line.split()
        name = ref[len("origin/"):] if ref.startswith("origin/") else ref
        if name in tips and not ref.startswith("origin/"): tips[name] = sha   # the local branch wins
        tips.setdefault(name, sha)
    earlier = sorted(((_slice(n), n, sha) for n, sha in tips.items() if _slice(n) and _slice(n) < current), reverse=True)
    prev = next(((n, sha) for _, n, sha in earlier
                 if _git("merge-base", "--is-ancestor", sha, "HEAD", check=False).returncode == 0), None)
    assert prev is not None, f"no earlier slice branch is an ancestor of {branch}"
    return prev


def expected_baseline(branch, previous_slice_tip, merge_base_with_base):
    """(label, sha) BASELINE_REF must equal for this branch, or None when the check is skipped.

    The two lookups are callables, so tests can fake them."""
    if branch in ("HEAD", "main", BASE) or not branch.startswith("tcp-mvp/"): return None
    current = _slice(branch)
    if current is not None and current[1] == "" and current[0] <= LEGACY_LAST_SLICE:
        n, sha = previous_slice_tip(branch, current)
        return f"the last commit of the previous slice {n}", sha
    return f"the merge-base of HEAD with origin/{BASE}", merge_base_with_base()


def test_baseline_ref_matches_expected():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    expected = expected_baseline(branch, lambda b, c: _previous_slice_tip(b, c),
                                 lambda: _git("merge-base", "HEAD", f"origin/{BASE}").stdout.strip())
    if expected is None: pytest.skip(f"no baseline rule for {branch}")
    problem = baseline_problem(BASELINE_REF, expected)
    assert problem is None, problem


def baseline_problem(baseline_ref, expected):
    label, sha = expected
    if baseline_ref == sha: return None
    return (f"BASELINE_REF in tests/support/guard_baseline.py is {baseline_ref}, but {label} is {sha}: "
            "move BASELINE_REF there and empty APPROVED at the start of the slice")


# --- the rule itself, with faked lookups ---------------------------------------------------------------------------

def _fakes(prev=("tcp-mvp/s02-storage", "aaa"), base="bbb"):
    return (lambda b, c: prev), (lambda: base)


@pytest.mark.parametrize("branch", ["HEAD", "main", "tcp-mvp/base", "tmp/mergecheck"])
def test_rule_skips_base_main_detached_and_outside_tcp_mvp(branch):
    assert expected_baseline(branch, *_fakes()) is None


@pytest.mark.parametrize("branch", ["tcp-mvp/s01-intake", "tcp-mvp/s02-storage", "tcp-mvp/s03-orchestrator"])
def test_rule_old_stacked_branches_use_previous_slice_tip(branch):
    assert expected_baseline(branch, *_fakes())[1] == "aaa"


@pytest.mark.parametrize("branch", ["tcp-mvp/s04-rule-pack", "tcp-mvp/s05-x", "tcp-mvp/s04b-pack-round",
                                    "tcp-mvp/test-tiering", "tcp-mvp/docs-decisions"])
def test_rule_branch_off_base_uses_merge_base(branch):
    assert expected_baseline(branch, *_fakes()) == ("the merge-base of HEAD with origin/tcp-mvp/base", "bbb")


def test_rule_right_baseline_passes_and_wrong_baseline_fails():
    expected = expected_baseline("tcp-mvp/s05-x", *_fakes(base="bbb"))
    assert baseline_problem("bbb", expected) is None
    assert "merge-base" in baseline_problem("stale", expected)
