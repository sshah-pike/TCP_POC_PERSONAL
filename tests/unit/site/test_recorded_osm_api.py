"""The OSM fixtures recorded from api.openstreetmap.org on 2026-10-31 (owner-permitted live run), replayed offline through the provider.
These pin what the fixtures hold; no network."""
import base64
import json
import os

import pytest

from tcp_planner.data_sources import base as B
from tcp_planner.data_sources import osm
from tcp_planner.site_model import bearing_check as BC
from tcp_planner.site_model import osm_rules as OR
from tests.support.source_fixtures import SourceFixtures

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RECORDED = os.path.join(ROOT, "tests", "fixtures", "recorded")
SITES = {  # site: (lat, lon, nearest way id, class, name, ref, distance m rounded to 0.1, ways in the radius)
    "granite": (41.3710266, -71.8203533, 19374756, "primary", "Granite Street", "US 1", 6.7, 23),
    "granite_p28": (41.3722748, -71.8205168, 19374756, "primary", "Granite Street", "US 1", 8.2, 25),
    "second": (42.3374380, -71.0268586, 8649090, "residential", "East Second Street", None, 4.2, 21),
    "colorado": (42.2757591, -71.1012145, 8651991, "residential", "Colorado Street", None, 3.5, 10),
    "union_p2": (42.3627586, -71.1867940, 9317366, "residential", "Union Street", None, 4.0, 20),
    "tenrod": (41.5773933, -71.6908347, 92387458, "secondary", "Ten Rod Road", "RI 165", 12.0, 1),
}


def replay(site):
    lat, lon = SITES[site][:2]
    client = B.SourceClient(hook=SourceFixtures(os.path.join(RECORDED, site)), transport=None)
    return osm.fetch_ways(client, lat, lon)


@pytest.mark.parametrize("site", sorted(SITES))
def test_each_recorded_site_replays_offline_with_the_expected_nearest_way(site):
    lat, lon, wid, cls, name, ref, dist, n = SITES[site]
    r = replay(site)
    assert r.call.replayed is True and r.info["provider"] == "osm_api" and len(r.ways) == n
    near = min(r.ways, key=lambda w: osm.point_to_polyline((0.0, 0.0), w.points)[0])
    d = osm.point_to_polyline((0.0, 0.0), near.points)[0]
    assert near.id == wid and near.tags["highway"] == cls and near.tags.get("name") == name and near.tags.get("ref") == ref and round(d, 1) == dist


@pytest.mark.parametrize("site", sorted(SITES))
def test_each_fixture_holds_the_raw_xml_the_request_and_the_source(site):
    d = os.path.join(RECORDED, site, "source"); files = os.listdir(d)
    assert len(files) == 1
    doc = json.load(open(os.path.join(d, files[0]), encoding="utf-8"))
    assert doc["source"] == "osm_api" and doc["status"] == 200 and doc["request"]["url"] == "https://api.openstreetmap.org/api/0.6/map" and doc["request"]["source_id"] == "osm_api"
    assert base64.b64decode(doc["body_b64"]).lstrip().startswith(b"<?xml") and "bbox" in doc["request"]["params"]
    assert files[0] == osm.request_key(SITES[site][0], SITES[site][1]) + ".json"


def test_the_granite_point_has_two_roads_close_together_so_the_reference_is_not_clear():
    ways = replay("granite").ways
    chk = BC.check_bearing((), ways)
    assert chk.status == BC.WHICH_ROAD and len(chk.questions) == 1 and chk.questions[0].kind == "WHICH_ROAD"
    assert BC.check_bearing((), replay("granite_p28").ways).status == BC.NO_MARKS               # the second Granite point has a clear reference (US 1)


def test_the_rule_results_the_recorded_sites_give():
    for site, lanes in (("second", 1), ("colorado", 1)):
        ways = replay(site).ways
        chk = BC.check_bearing((), ways)
        r = OR.osm_read(ways, choice=chk.reference).readings
        assert r["lanes_per_direction"].value == lanes and r["divided_highway"].value is False and r["oneway"].lower_confidence is True and r["shoulder_present"].reason_code == "no_tag"


def test_overpass_never_reuses_these_fixtures():
    from tests.support.fixtures import MissingFixtureError
    from tcp_planner.site_model.site_config import load_site_config
    cfg = load_site_config(); cfg["osm"]["provider"]["value"] = "overpass"
    client = B.SourceClient(hook=SourceFixtures(os.path.join(RECORDED, "second")), transport=None)
    with pytest.raises(MissingFixtureError): osm.fetch_ways(client, SITES["second"][0], SITES["second"][1], cfg)
