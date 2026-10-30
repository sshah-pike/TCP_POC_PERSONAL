"""S0 acceptance: a replayed saved run gives the same request fingerprints twice.

The sites under tests/fixtures/recorded/ were seeded from saved evidence (python -m tests.support.record seed ...).
Each replay runs the whole pipeline with map, OSM and AI served from fixtures only; the network is blocked by the root
conftest, and a missing fixture raises MissingFixtureError.
"""
import json, os

import pytest

from tcp_planner.orchestration.pipeline import run_pipeline
from tests.support.providers import Harness

RECORDED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fixtures", "recorded")
SITES = sorted(d for d in os.listdir(RECORDED) if os.path.isfile(os.path.join(RECORDED, d, "site.json")))


def replay(site, out):
    h = Harness(os.path.join(RECORDED, site))
    res = run_pipeline(out_dir=str(out), **h.run_kwargs())
    return h, res


def test_sites_are_present():
    assert {"granite_p30", "alton_bradford", "exeter_ten_rod"} <= set(SITES)


@pytest.mark.parametrize("site", SITES)
def test_replayed_run_gives_same_fingerprints_twice(site, tmp_path):
    h1, r1 = replay(site, tmp_path / "a")
    h2, r2 = replay(site, tmp_path / "b")
    fps = h1.fingerprints()
    kinds = [k for k, _ in fps]
    assert "map" in kinds and "osm" in kinds and "ai" in kinds     # every external call was served by a fixture
    assert fps == h2.fingerprints()                                 # same request fingerprints, same order
    assert r1["decision"] == r2["decision"] and r1["plan_hash"] == r2["plan_hash"]
    assert all(os.path.isfile(os.path.join(h1.store.dir, k, f"{fp}.json")) for k, fp in fps)  # each one is a stored fixture
