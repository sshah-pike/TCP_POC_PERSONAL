"""Fail fast when a slice forgets to move BASELINE_REF (tests/support/guard_baseline.py).

The previous slice is the tcp-mvp/sNN branch with the highest slice number below the current one whose tip is an
ancestor of HEAD (a slice built in parallel, such as S4 beside S3, is not an ancestor and is skipped). BASELINE_REF
must equal that tip. Skipped outside a tcp-mvp/sNN branch (main, detached HEAD).
"""
import re, subprocess

import pytest

from tests.support.guard_baseline import BASELINE_REF, ROOT

SLICE_RE = re.compile(r"^tcp-mvp/s(\d+)([a-z]?)-")


def _git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def _slice(name):
    m = SLICE_RE.match(name)
    return (int(m.group(1)), m.group(2)) if m else None


def test_baseline_ref_is_last_commit_of_previous_slice():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    current = _slice(branch)
    if current is None: pytest.skip(f"not on a tcp-mvp/sNN branch ({branch})")
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
    assert BASELINE_REF == prev[1], (f"BASELINE_REF in tests/support/guard_baseline.py is {BASELINE_REF}, but the last "
                                     f"commit of the previous slice {prev[0]} is {prev[1]}: move BASELINE_REF there and "
                                     "empty APPROVED at the start of the slice")
