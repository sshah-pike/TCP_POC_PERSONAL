"""Baseline for the "protected files unchanged" guards: the last commit of the previous slice (S1 decision 1, option B).

The guards compare the working tree with BASELINE_REF, so a change committed inside the current slice is still caught.
A deliberate, approved change is listed in APPROVED with the git blob hash of its approved content: any further edit
to that file fails again. At the start of each slice, move BASELINE_REF to the previous slice's last commit and
empty APPROVED.
"""
import os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_REF = "13757f2a2421a7c84ae2fb50a47535012cbdc753"  # last commit of tcp-mvp/s00-setup
APPROVED = {
    # S1: added input.duplicate_distance_m = 1.0 (approved S1 plan)
    "config/pipeline_config.json": "af0b263e46ed6c55112ce2a1a7e269028c120c32",
}


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def unapproved_changes(paths):
    """Paths that differ from BASELINE_REF and are not at their approved content."""
    changed = _git("diff", "--name-only", BASELINE_REF, "--", *paths).split()
    return [p for p in changed if APPROVED.get(p) != _git("hash-object", p).strip()]
