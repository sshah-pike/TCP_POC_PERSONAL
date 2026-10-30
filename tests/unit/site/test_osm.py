"""OSM through Overpass (S6 commit 3): bounded query, replay offline, the rules per field. No network."""
import json
import math

import pytest

from tcp_planner.data_sources import base as B
from tcp_planner.data_sources import osm
from tcp_planner.data_sources.osm import OsmWay
from tcp_planner.site_model import fusion_v2 as F
from tcp_planner.site_model import osm_rules as R
from tcp_planner.site_model.site_config import load_site_config, setting
from tests.support.source_fixtures import SourceFixtures

LAT0, LON0 = 41.5774, -71.6908
K = math.pi / 180 * osm.EARTH_R_M


def latlon(x, y):
    return LAT0 + y / K, LON0 + x / (K * math.cos(math.radians(LAT0)))


def element(id_, tags, pts):
    return {"type": "way", "id": id_, "tags": tags, "geometry": [dict(zip(("lat", "lon"), latlon(*p))) for p in pts]}


def answer(*els):
    return json.dumps({"version": 0.6, "elements": list(els)}).encode()


class Transport:
    def __init__(self, content): self.calls, self.content = [], content

    def __call__(self, method, url, params, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers})
        return 200, self.content


def client(tmp_path, transport=None):
    return B.SourceClient(hook=SourceFixtures(str(tmp_path / "site")), transport=transport, now=lambda: "2026-10-31T12:00:00+00:00")


def way(id_, tags, pts):
    return OsmWay(id_, {"highway": "secondary", **tags}, tuple(pts))


EW = [(-100.0, 5.0), (100.0, 5.0)]          # an east-west road 5 m north of the work point


# ---------------------------------------------------------------- the adapter
def test_the_query_is_bounded_and_asks_for_tags_and_geometry_only():
    cfg = load_site_config()
    q = osm.build_query(LAT0, LON0, 150, setting("osm", "highway_classes", cfg)[0])
    assert q.startswith("[out:json][timeout:25];way(around:150,") and q.endswith("out tags geom;")
    assert '["highway"~"^(motorway|' in q and "relation" not in q and "node(" not in q


def test_fetch_records_once_then_replays_with_no_transport(tmp_path):
    t = Transport(answer(element(1, {"highway": "secondary", "lanes": "4"}, EW)))
    r = osm.fetch_ways(client(tmp_path, t), LAT0, LON0)
    assert len(t.calls) == 1 and r.ways[0].id == 1 and r.ways[0].tags["lanes"] == "4" and r.call.replayed is False
    assert t.calls[0]["url"].startswith("https://overpass-api.de/") and "tcp-planner" in t.calls[0]["headers"]["User-Agent"]
    again = osm.fetch_ways(client(tmp_path, None), LAT0, LON0)
    assert again.call.replayed is True and again.ways == r.ways and len(t.calls) == 1


def test_the_geometry_is_in_metres_east_and_north_of_the_work_point():
    ws = osm.parse_overpass(answer(element(7, {"highway": "primary"}, [(-30, 12), (40, 12)])), (LAT0, LON0))
    (x1, y1), (x2, y2) = ws[0].points
    assert abs(x1 + 30) < 0.01 and abs(y1 - 12) < 0.01 and abs(x2 - 40) < 0.01


def test_a_radius_above_the_allow_list_limit_is_refused_before_any_request(tmp_path):
    t = Transport(answer())
    with pytest.raises(B.SourceError) as e: osm.fetch_ways(client(tmp_path, t), LAT0, LON0, radius_m=601)
    assert e.value.code == "SOURCE_QUERY_TOO_LARGE" and t.calls == []


def test_an_answer_with_too_many_elements_is_refused(tmp_path):
    els = [element(i, {"highway": "service"}, EW) for i in range(1, 5002)]
    with pytest.raises(B.SourceError) as e: osm.fetch_ways(client(tmp_path, Transport(answer(*els))), LAT0, LON0)
    assert e.value.code in ("SOURCE_RESPONSE_TOO_LARGE",)


def test_a_bad_answer_raises_a_source_error():
    for bad in (b"<html>busy</html>", b"[]", b'{"elements": "x"}'):
        with pytest.raises(B.SourceError): osm.parse_overpass(bad, (LAT0, LON0))


def test_ways_without_geometry_or_with_one_point_are_dropped():
    els = [{"type": "way", "id": 1, "tags": {"highway": "x"}}, element(2, {"highway": "x"}, [(0, 0)]),
           {"type": "node", "id": 3}, element(4, {"highway": "x"}, EW)]
    assert [w.id for w in osm.parse_overpass(answer(*els), (LAT0, LON0))] == [4]


def test_the_host_is_the_allow_listed_one():
    assert osm.URL.startswith("https://overpass-api.de/") and "overpass-api.de" in B.load_sources()["sources"]["osm_overpass"]["hosts"]


def test_bearing_and_angle_helpers():
    assert osm.bearing_deg(0, 1) == 0 and osm.bearing_deg(1, 0) == 90 and osm.bearing_deg(0, -1) == 180 and osm.bearing_deg(-1, 0) == 270
    assert osm.axis_diff_deg(10, 190) == 0 and osm.axis_diff_deg(0, 90) == 90 and osm.axis_diff_deg(170, 10) == 20
    assert osm.direction_diff_deg(10, 350) == 20 and osm.direction_diff_deg(0, 180) == 180


# ---------------------------------------------------------------- choosing the way
def test_the_nearest_way_within_the_distance_is_chosen_and_a_service_way_ranks_last():
    main = way(1, {}, EW)
    drive = way(2, {"highway": "service"}, [(0.0, 1.0), (0.0, 40.0)])         # closer to the point, but a service way
    ranked = R.rank_ways([drive, main])
    assert [c.way.id for c in ranked] == [1, 2] and abs(ranked[0].distance_m - 5.0) < 1e-9 and abs(ranked[0].bearing_deg - 90) < 1e-9


def test_a_way_beyond_the_configured_distance_is_not_the_road_of_the_job():
    far = way(1, {}, [(-100, 60), (100, 60)])
    assert R.rank_ways([far]) == []
    r = R.osm_read([far])
    assert r.way_id is None and all(x.outcome == "UNKNOWN" and x.reason_code == "no_source" for x in r.readings.values())


# ---------------------------------------------------------------- lanes per direction
def lanes(tags):
    return R.osm_read([way(1, tags, EW)]).readings["lanes_per_direction"], R.osm_read([way(1, tags, EW)]).questions


def test_lanes_from_forward_and_backward_when_equal():
    r, q = lanes({"lanes:forward": "2", "lanes:backward": "2", "lanes": "4"})
    assert (r.outcome, r.value, q) == ("FOUND", 2, ())


def test_forward_and_backward_that_differ_give_unknown_and_a_question():
    r, q = lanes({"lanes:forward": "3", "lanes:backward": "1"})
    assert r.outcome == "UNKNOWN" and r.reason_code == "ambiguous" and q[0].kind == "LANES_UNSPLIT" and q[0].osm_way_id == 1
    assert q[0].field == "lanes_per_direction" and q[0].context["lanes:forward"] == "3"


def test_an_even_total_on_a_two_way_road_is_divided_by_two():
    r, q = lanes({"lanes": "4"})
    assert (r.outcome, r.value, q) == ("FOUND", 2, ())
    assert lanes({"lanes": "2", "oneway": "no"})[0].value == 1


def test_an_odd_total_on_a_two_way_road_is_unknown_with_a_question():
    r, q = lanes({"lanes": "3"})
    assert r.outcome == "UNKNOWN" and len(q) == 1 and q[0].kind == "LANES_UNSPLIT" and "odd" in q[0].reason


def test_only_one_of_forward_or_backward_is_not_enough_it_falls_back_to_the_total():
    assert lanes({"lanes:forward": "2", "lanes": "4"})[0].value == 2
    r, q = lanes({"lanes:forward": "2", "lanes": "5"})
    assert r.outcome == "UNKNOWN" and q


def test_a_missing_lanes_tag_is_no_information_and_no_question():
    r, q = lanes({})
    assert (r.outcome, r.reason_code, q) == ("UNKNOWN", "no_tag", ())


def test_a_one_way_road_has_all_its_lanes_in_one_direction():
    assert lanes({"oneway": "yes", "lanes": "3"})[0].value == 3
    assert lanes({"oneway": "yes", "lanes": "3", "lanes:forward": "3"})[0].value == 3
    assert lanes({"oneway": "-1", "lanes": "2"})[0].value == 2
    assert lanes({"oneway": "yes"})[0].reason_code == "no_tag"


def test_a_reversible_road_gives_no_lane_count():
    r, q = lanes({"oneway": "reversible", "lanes": "2"})
    assert r.outcome == "UNKNOWN" and q == ()


# ---------------------------------------------------------------- one-way
def oneway(tags):
    return R.osm_read([way(1, tags, EW)]).readings["oneway"]


def test_oneway_tags():
    assert (oneway({"oneway": "yes"}).outcome, oneway({"oneway": "yes"}).value) == ("FOUND", True)
    assert oneway({"oneway": "-1"}).value is True
    r = oneway({"oneway": "no"})
    assert (r.outcome, r.value, r.lower_confidence) == ("FOUND", False, False)
    assert oneway({"oneway": "reversible"}).outcome == "UNKNOWN"


def test_a_missing_oneway_tag_counts_as_not_one_way_at_lower_confidence():
    r = oneway({})
    assert (r.outcome, r.value, r.lower_confidence) == ("FOUND", False, True)
    rb = oneway({"junction": "roundabout"})
    assert rb.value is True and rb.lower_confidence is True


def test_the_ai_must_also_say_false_when_the_oneway_tag_is_missing():
    r = oneway({})
    agree = F.compare("oneway", False, [r])
    assert agree.agreement == F.AGREE and agree.candidates[1].confidence_class == F.LOW       # lower confidence, never medium
    said_true = F.compare("oneway", True, [r])
    assert said_true.agreement == F.UNDECIDABLE and "stand-in" in said_true.note               # not a contradiction, not a confirmation
    stated = F.compare("oneway", True, [oneway({"oneway": "no"})])
    assert stated.agreement == F.DISAGREE                                                      # a real tag does contradict


# ---------------------------------------------------------------- shoulder and sidewalk
def test_shoulder_tags():
    def sh(tags): return R.osm_read([way(1, tags, EW)]).readings["shoulder_present"]
    assert (sh({"shoulder": "yes"}).outcome, sh({"shoulder": "yes"}).value) == ("FOUND", True)
    assert sh({"shoulder:right": "yes", "shoulder:left": "no"}).outcome == "FOUND"
    n = sh({"shoulder": "no"})
    assert (n.outcome, n.value) == ("NOT_PRESENT", False)
    assert sh({"shoulder:both": "no"}).outcome == "NOT_PRESENT"
    missing = sh({})
    assert (missing.outcome, missing.reason_code) == ("UNKNOWN", "no_tag")                      # a missing tag is no information
    assert sh({"shoulder": "gravel"}).outcome == "UNKNOWN"


def test_sidewalk_tags():
    def sw(tags): return R.osm_read([way(1, tags, EW)]).readings["sidewalk_present"]
    assert sw({"sidewalk": "both"}).outcome == "FOUND" and sw({"sidewalk:left": "yes"}).value is True
    assert sw({"sidewalk": "no"}).outcome == "NOT_PRESENT" and sw({"sidewalk": "none"}).outcome == "NOT_PRESENT"
    assert sw({}).reason_code == "no_tag"


def test_a_not_present_shoulder_agrees_with_an_ai_false_in_fusion():
    r = R.osm_read([way(1, {"shoulder": "no"}, EW)]).readings["shoulder_present"]
    assert F.compare("shoulder_present", False, [r]).agreement == F.AGREE
    assert F.compare("shoulder_present", True, [r]).agreement == F.DISAGREE
    assert F.compare("shoulder_present", False, [R.osm_read([way(1, {}, EW)]).readings["shoulder_present"]]).agreement == F.UNDECIDABLE


# ---------------------------------------------------------------- divided, from geometry
NORTH_SIDE = [(-100.0, 5.0), (100.0, 5.0)]
SOUTH_SIDE = [(100.0, -25.0), (-100.0, -25.0)]           # drawn westbound, 30 m south


def divided(ways):
    return R.osm_read(ways).readings["divided_highway"]


def test_an_opposite_parallel_one_way_carriageway_within_the_distance_is_a_divided_road():
    a = way(1, {"oneway": "yes", "name": "Main St"}, NORTH_SIDE)
    b = way(2, {"oneway": "yes", "name": "Main St"}, SOUTH_SIDE)
    r = divided([a, b])
    assert (r.outcome, r.value) == ("FOUND", True) and "way 2" in r.note


def test_a_two_way_chosen_way_is_not_divided():
    r = divided([way(1, {"name": "Main St"}, NORTH_SIDE), way(2, {"oneway": "yes", "name": "Main St"}, SOUTH_SIDE)])
    assert (r.outcome, r.value) == ("NOT_PRESENT", False)


def test_a_one_way_chosen_way_with_no_opposite_way_is_unknown_not_not_present():
    r = divided([way(1, {"oneway": "yes", "name": "Main St"}, NORTH_SIDE)])
    assert r.outcome == "UNKNOWN" and r.reason_code == "ambiguous"


def test_the_opposite_way_must_run_the_other_way_be_parallel_close_and_share_the_name():
    base = {"oneway": "yes", "name": "Main St"}
    a = way(1, base, NORTH_SIDE)
    assert divided([a, way(2, base, [(-100.0, -25.0), (100.0, -25.0)])]).outcome == "UNKNOWN"           # same direction
    assert divided([a, way(2, base, [(0.0, -25.0), (0.0, 80.0)])]).outcome == "UNKNOWN"                  # not parallel
    assert divided([a, way(2, base, [(100.0, -100.0), (-100.0, -100.0)])]).outcome == "UNKNOWN"          # farther than the configured distance
    assert divided([a, way(2, {**base, "name": "Other Rd"}, SOUTH_SIDE)]).outcome == "UNKNOWN"           # another road
    assert divided([a, way(2, {**base, "highway": "service"}, SOUTH_SIDE)]).outcome == "UNKNOWN"         # a service way is never the other side
    assert divided([a, way(2, {"name": "Main St"}, SOUTH_SIDE)]).outcome == "UNKNOWN"                    # the other way is two-way


def test_a_reversed_one_way_counts_as_running_the_other_way():
    a = way(1, {"oneway": "yes", "name": "Main St"}, NORTH_SIDE)
    b = way(2, {"oneway": "-1", "name": "Main St"}, list(reversed(SOUTH_SIDE)))        # drawn eastbound, travel westbound
    assert divided([a, b]).value is True


def test_ref_can_stand_in_for_the_name():
    a = way(1, {"oneway": "yes", "ref": "RI 138"}, NORTH_SIDE)
    b = way(2, {"oneway": "yes", "ref": "RI 138"}, SOUTH_SIDE)
    assert divided([a, b]).value is True


# ---------------------------------------------------------------- failure and values
def test_a_source_failure_is_unknown_with_reason_source_failed_never_not_present():
    r = R.source_failed("HTTP 429")
    assert set(r.readings) == set(R.FIELDS) and r.way_id is None
    assert all(x.outcome == "UNKNOWN" and x.reason_code == "source_failed" for x in r.readings.values())
    for f in R.FIELDS: assert F.compare(f, False, [r.readings[f]]).agreement == F.UNDECIDABLE


def test_all_distances_and_angles_come_from_config_and_are_calibration_pending():
    cfg = load_site_config()
    for name in ("query_radius_m", "max_way_distance_m", "divided_max_separation_m", "divided_parallel_tolerance_deg", "divided_require_same_name_or_ref"):
        assert cfg["osm"][name]["source"] == "CALIBRATION_PENDING", name
        assert setting("osm", name, cfg)[1] == ("CALIBRATION_PENDING",)
    assert cfg["osm"]["query_radius_m"]["value"] <= B.load_sources()["sources"]["osm_overpass"]["query_limits"]["max_radius_m"]


def test_no_osm_reading_ever_fills_a_mandatory_start_field():
    from tcp_planner.site_model.start_fields import START_FIELDS
    assert not (set(R.FIELDS) & set(START_FIELDS))
    r = R.osm_read([way(1, {"oneway": "yes", "lanes": "2", "maxspeed": "35"}, EW)])
    assert "posted_speed_mph" not in r.readings and "road_type" not in r.readings
