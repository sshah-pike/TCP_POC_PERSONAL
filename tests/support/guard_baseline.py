"""Baseline for the "protected files unchanged" guards: the last commit of the previous slice (S1 decision 1, option B).

The guards compare the working tree with BASELINE_REF, so a change committed inside the current slice is still caught.
A deliberate, approved change is listed in APPROVED with the git blob hash of its approved content: any further edit
to that file fails again. At the start of each slice, move BASELINE_REF to the previous slice's last commit and
empty APPROVED.
"""
import os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASELINE_REF = "b2c95fe56fcb4ed9e43804edae57a5c0bd1013f6"  # last commit of tcp-mvp/s02-storage
APPROVED = {
    # S3 Q3/Q4 (owner decision): new "project" section, max_zones 3 and max_parallel_zone_runs 3; no other change
    "config/pipeline_config.json": "48b0efb8999d66ef9f25fb86b0dce94d08a55a79",
}


def _git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def unapproved_changes(paths):
    """Paths that differ from BASELINE_REF and are not at their approved content."""
    changed = _git("diff", "--name-only", BASELINE_REF, "--", *paths).split()
    return [p for p in changed if APPROVED.get(p) != _git("hash-object", p).strip()]
