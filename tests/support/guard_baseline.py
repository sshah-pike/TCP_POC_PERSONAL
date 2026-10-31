"""Baseline for the "protected files unchanged" guards: the last commit of the previous slice (S1 decision 1, option B).

The guards compare the working tree with BASELINE_REF, so a change committed inside the current slice is still caught.
A deliberate, approved change is listed in APPROVED with the git blob hash of its approved content: any further edit
to that file fails again. At the start of each slice, move BASELINE_REF to the previous slice's last commit and
empty APPROVED.
"""
import os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_REF = "449eb4c4cc7de64847e699e8c86b769ea76e599f"  # merge-base of HEAD with origin/tcp-mvp/base (S6 session 1 merge)
APPROVED = {}


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def unapproved_changes(paths):
    """Paths that differ from BASELINE_REF and are not at their approved content."""
    changed = _git("diff", "--name-only", BASELINE_REF, "--", *paths).split()
    return [p for p in changed if APPROVED.get(p) != _git("hash-object", p).strip()]
