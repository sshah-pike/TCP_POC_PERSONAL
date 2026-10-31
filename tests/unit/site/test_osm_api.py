"""The OSM main API provider (S6): XML parsing, the box, the true-distance filter, the widened and shrunk retries, provider selection, fixtures,
the pipeline's limited transport. Fakes only: no network, and a transport that fails on any host but api.openstreetmap.org."""
import base64
import importlib.util
import json
import math
import os
import sys

import pytest

from tcp_planner.data_sources import base as B
from tcp_planner.data_sources import osm, osm_api
from tcp_planner.site_model import fusion_v2 as F
from tcp_planner.site_model import osm_rules as OR
from tcp_planner.site_model.site_config import load_site_config, setting
from tests.support.fixtures import MissingFixtureError
from tests.support.source_fixtures import SourceFixtures

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
LAT0, LON0 = 41.3710266, -71.8203533
K = math.pi / 180 * osm.EARTH_R_M
API_HOST = "api.openstreetmap.org"
CLASSES = setting("osm", "highway_classes", load_site_config())[0]


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", name + ".py"))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m


def ll(x, y, lat0=LAT0, lon0=LON0):
    return lat0 + y / K, lon0 + x / (K * math.cos(math.radians(lat0)))


def xml(ways, lat0=LAT0, lon0=LON0, extra=""):
    """An OSM map answer. ways: [(id, tags, [(x_m, y_m), ...])]. Every node of every way is in the answer, as the API returns them."""
    nodes, body, nid = [], [], 1000
    for wid, tags, pts in ways:
        refs = []
        for x, y in pts:
            nid += 1; la, lo = ll(x, y, lat0, lon0)
            nodes.append(f'<node id="{nid}" lat="{la!r}" lon="{lo!r}" version="1"/>'); refs.append(nid)
        t = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        body.append(f'<way id="{wid}" version="2">' + "".join(f'<nd ref="{r}"/>' for r in refs) + t + "</way>")
    return ('<?xml version="1.0" encoding="UTF-8"?><osm version="0.6" generator="CGImap">' + "".join(nodes) + "".join(body) + extra + "</osm>").encode()


def overpass_json(ways, lat0=LAT0, lon0=LON0):
    els = [{"type": "way", "id": wid, "tags": tags, "geometry": [dict(zip(("lat", "lon"), ll(x, y, lat0, lon0))) for x, y in pts]} for wid, tags, pts in ways]
    return json.dumps({"version": 0.6, "elements": els}).encode()


EW5 = [(-120.0, 5.0), (0.0, 5.0), (120.0, 5.0)]
MAIN = (1, {"highway": "secondary", "name": "Main St", "ref": "US 1", "lanes": "4", "lanes:forward": "2", "lanes:backward": "2", "oneway": "no", "sidewalk": "both", "shoulder": "no"}, EW5)


class Transport:
    """Answers from a list of (status, content); records every call; fails on any host but the API's."""
    def __init__(self, answers, hosts=(API_HOST,)): self.answers, self.calls, self.hosts, self.refused = list(answers), [], hosts, []

    def __call__(self, method, url, params, body, headers, timeout):
        host = url.split("/")[2]
        if host not in self.hosts:
            self.refused.append(host); raise AssertionError(f"a request went to {host}")
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers, "timeout": timeout})
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception): raise a
        return a


def client(tmp_path=None, transport=None):
    hook = SourceFixtures(str(tmp_path / "site")) if tmp_path is not None else None
    return B.SourceClient(hook=hook, transport=transport, now=lambda: "2026-10-31T12:00:00+00:00")


# ================================================================= parsing
def test_the_xml_parser_reads_ways_tags_and_ordered_geometry():
    wid, tags, pts = MAIN
    ways = osm_api.parse_map_xml(xml([MAIN]), (LAT0, LON0), CLASSES)
    assert len(ways) == 1 and ways[0].id == 1 and ways[0].tags == tags
    assert [round(x) for x, _ in ways[0].points] == [-120, 0, 120] and all(abs(y - 5.0) < 0.05 for _, y in ways[0].points)            # drawn order kept


def test_tags_lanes_forward_backward_oneway_sidewalk_survive_and_the_osm_rules_read_them():
    ways = osm_api.parse_map_xml(xml([(2, {"highway": "primary", "lanes:forward": "2", "lanes:backward": "2", "oneway": "no", "sidewalk": "left"}, EW5)]), (LAT0, LON0), CLASSES)
    r = OR.osm_read(ways).readings
    assert (r["lanes_per_direction"].outcome, r["lanes_per_direction"].value) == ("FOUND", 2) and r["oneway"].value is False and r["sidewalk_present"].value is True


def test_a_service_way_is_kept_and_a_footway_a_building_and_an_untagged_way_are_not():
    ways = osm_api.parse_map_xml(xml([(1, {"highway": "service"}, EW5), (2, {"highway": "footway"}, EW5), (3, {"building": "yes"}, EW5), (4, {}, EW5),
                                       (5, {"highway": "residential"}, EW5)]), (LAT0, LON0), CLASSES)
    assert [w.id for w in ways] == [1, 5]


def test_a_way_that_crosses_the_box_with_no_node_inside_it_is_kept_when_the_api_returns_it():
    far = (9, {"highway": "tertiary"}, [(-900.0, 5.0), (900.0, 5.0)])                     # both nodes far outside a 300 m box; the segment crosses it
    ways = osm_api.parse_map_xml(xml([far]), (LAT0, LON0), CLASSES)
    near = osm_api.within_radius(ways, 150)
    assert [w.id for w in near] == [9] and len(ways[0].points) == 2


def test_a_way_with_missing_nodes_keeps_the_nodes_it_has_and_a_way_with_fewer_than_two_is_dropped():
    text = xml([(1, {"highway": "service"}, EW5)]).decode().replace("</osm>", '<way id="2"><nd ref="1"/><nd ref="999999"/><tag k="highway" v="service"/></way></osm>')
    assert [w.id for w in osm_api.parse_map_xml(text.encode(), (LAT0, LON0), CLASSES)] == [1]


@pytest.mark.parametrize("bad", [b"<html>busy</html>", b"not xml at all", b'<?xml version="1.0"?><error/>', b""])
def test_an_answer_that_is_not_osm_xml_is_a_source_error(bad):
    with pytest.raises(B.SourceError) as e: osm_api.parse_map_xml(bad, (LAT0, LON0), CLASSES)
    assert e.value.code == "SOURCE_BAD_RESPONSE"


# ================================================================= the box and the true-distance filter
def test_the_box_is_a_square_of_the_configured_half_size_in_metres():
    left, bottom, right, top = osm_api.bbox_for(LAT0, LON0, 300, 0.25)
    assert abs((top - bottom) * K - 600) < 0.5 and abs((right - left) * K * math.cos(math.radians(LAT0)) - 600) < 0.5
    assert osm_api.bbox_param((left, bottom, right, top)).count(",") == 3 and left < LON0 < right and bottom < LAT0 < top


def test_a_box_over_the_api_area_limit_is_refused_before_any_request(tmp_path):
    with pytest.raises(B.SourceError) as e: osm_api.bbox_for(LAT0, LON0, 40000, 0.25)
    assert e.value.code == "SOURCE_QUERY_TOO_LARGE"
    cfg = load_site_config(); cfg["osm"]["api_bbox_half_m"]["value"] = 40000
    t = Transport([(200, xml([MAIN]))])
    with pytest.raises(B.SourceError): osm.fetch_ways(client(transport=t), LAT0, LON0, cfg)
    assert t.calls == []


def test_the_first_request_asks_for_the_configured_box_on_the_configured_url():
    t = Transport([(200, xml([MAIN]))])
    osm.fetch_ways(client(transport=t), LAT0, LON0)
    c = t.calls[0]
    assert c["url"] == "https://api.openstreetmap.org/api/0.6/map" and set(c["params"]) == {"bbox"}
    left, bottom, right, top = (float(v) for v in c["params"]["bbox"].split(","))
    assert abs((top - bottom) * K - 600) < 0.5


def test_the_true_distance_filter_drops_a_way_outside_150_m_and_keeps_one_inside():
    inside = (1, {"highway": "residential"}, [(-100.0, 149.0), (100.0, 149.0)])
    outside = (2, {"highway": "residential"}, [(-100.0, 151.0), (100.0, 151.0)])
    t = Transport([(200, xml([inside, outside]))])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert [w.id for w in r.ways] == [1] and r.info["attempts"][0]["highway_ways_in_answer"] == 2 and r.info["attempts"][0]["ways_within_radius"] == 1
    assert len(t.calls) == 1 and r.info["widened"] is False                              # a way was found: no wider call


def test_the_radius_is_the_config_value_not_the_box():
    cfg = load_site_config(); cfg["osm"]["query_radius_m"]["value"] = 50
    t = Transport([(200, xml([(1, {"highway": "residential"}, [(-100.0, 80.0), (100.0, 80.0)]), (2, {"highway": "residential"}, [(-100.0, 20.0), (100.0, 20.0)])]))])
    assert [w.id for w in osm.fetch_ways(client(transport=t), LAT0, LON0, cfg).ways] == [2]


# ================================================================= the widened retry and the too-many-nodes retry
def test_no_way_within_the_radius_widens_the_box_once_and_records_it():
    t = Transport([(200, xml([(1, {"highway": "residential"}, [(-100.0, 250.0), (100.0, 250.0)])])), (200, xml([MAIN]))])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert [w.id for w in r.ways] == [1] and len(t.calls) == 2 and r.info["widened"] is True and r.info["shrunk"] is False
    assert [a["bbox_half_m"] for a in r.info["attempts"]] == [300, 600] and "600" in r.info["note"]
    h1 = [float(v) for v in t.calls[0]["params"]["bbox"].split(",")]; h2 = [float(v) for v in t.calls[1]["params"]["bbox"].split(",")]
    assert (h2[3] - h2[1]) > 1.9 * (h1[3] - h1[1])


def test_the_widened_retry_happens_only_once_even_when_the_wide_box_finds_nothing():
    t = Transport([(200, xml([]))])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert r.ways == () and len(t.calls) == 2 and r.info["widened"] is True


def test_http_400_too_many_nodes_retries_once_with_the_smaller_box_and_says_so():
    t = Transport([(400, b"You requested too many nodes (limit is 50000). Either request a smaller area, or use planet.osm"), (200, xml([MAIN]))])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert [w.id for w in r.ways] == [1] and len(t.calls) == 2 and r.info["shrunk"] is True and r.info["widened"] is False
    assert [a.get("bbox_half_m") for a in r.info["attempts"]] == [300, 150] and r.info["attempts"][0]["error"] == "HTTP 400 too many nodes" and "too many nodes" in r.info["note"]
    h = [float(v) for v in t.calls[1]["params"]["bbox"].split(",")]
    assert abs((h[3] - h[1]) * K - 300) < 0.5


def test_after_a_shrink_an_empty_answer_is_not_widened():
    t = Transport([(400, b"too many nodes"), (200, xml([]))])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert r.ways == () and len(t.calls) == 2 and r.info["widened"] is False


def test_the_shrunk_box_failing_again_is_an_error_not_a_loop():
    t = Transport([(400, b"too many nodes")])
    with pytest.raises(B.SourceError) as e: osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert e.value.details["http_status"] == 400 and len(t.calls) == 2


def test_a_wide_box_with_too_many_nodes_keeps_the_first_answer():
    t = Transport([(200, xml([])), (400, b"too many nodes")])
    r = osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert r.ways == () and r.info["widened"] is True and "first answer is kept" in r.info["note"] and len(t.calls) == 2


def test_any_other_http_400_is_not_retried():
    t = Transport([(400, b"bbox is malformed")])
    with pytest.raises(B.SourceError) as e: osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert len(t.calls) == 1 and e.value.details["http_status"] == 400


def test_the_box_sizes_and_the_text_are_config_calibration_pending():
    cfg = load_site_config()["osm"]
    for k, v in (("api_bbox_half_m", 300), ("api_bbox_retry_half_m", 600), ("api_bbox_shrink_half_m", 150), ("api_max_bbox_area_deg2", 0.25), ("provider", "osm_api"),
                 ("api_too_many_nodes_text", "too many nodes"), ("query_radius_m", 150)):
        assert cfg[k]["value"] == v and cfg[k]["source"] == "CALIBRATION_PENDING", k
    assert cfg["api_bbox_half_m"]["value"] > cfg["query_radius_m"]["value"] and cfg["api_url"]["source"] == "CALIBRATION_PENDING"


# ================================================================= provider selection and no Overpass request
def overpass_cfg():
    cfg = load_site_config(); cfg["osm"]["provider"]["value"] = "overpass"; return cfg


def test_the_default_provider_is_the_osm_api_and_overpass_is_selectable():
    assert setting("osm", "provider", load_site_config())[0] == "osm_api"
    t = Transport([(200, xml([MAIN]))])
    assert osm.fetch_ways(client(transport=t), LAT0, LON0).info["provider"] == "osm_api" and t.calls[0]["url"].startswith("https://api.openstreetmap.org/")
    t2 = Transport([(200, overpass_json([MAIN]))], hosts=("overpass-api.de",))
    r = osm.fetch_ways(client(transport=t2), LAT0, LON0, overpass_cfg())
    assert r.info["provider"] == "overpass" and t2.calls[0]["url"].startswith("https://overpass-api.de/") and [w.id for w in r.ways] == [1]


def test_an_unknown_provider_is_an_error():
    cfg = load_site_config(); cfg["osm"]["provider"]["value"] = "other"
    with pytest.raises(B.SourceError) as e: osm.fetch_ways(client(transport=Transport([(200, b"")])), LAT0, LON0, cfg)
    assert e.value.code == "SOURCE_UNKNOWN_PROVIDER"


def test_no_overpass_request_is_made_when_the_provider_is_osm_api(tmp_path):
    rec = load("s06_record_osm")
    t = Transport([(200, xml([MAIN]))])                       # asserts on any host but the API's
    sites = [{"site_id": "A", "lat": LAT0, "lon": LON0}, {"site_id": "B", "lat": LAT0 + 0.01, "lon": LON0}]
    out = rec.record_sites(sites, str(tmp_path / "fx"), t, sleep=lambda s: None, log=lambda *_: None)
    assert [r["status"] for r in out] == ["recorded", "recorded"] and all(c["url"].startswith("https://api.openstreetmap.org/") for c in t.calls)
    assert t.refused == []
    probe = Transport([(200, b"")])                          # the same guard does catch a request to Overpass when the provider is overpass
    with pytest.raises(B.SourceError): osm.fetch_ways(client(transport=probe), LAT0, LON0, overpass_cfg())
    assert probe.refused == ["overpass-api.de"]


def test_the_osm_api_is_in_the_allow_list_and_no_other_host_was_added():
    src = B.load_sources()["sources"]
    assert src["osm_api"]["hosts"] == ["api.openstreetmap.org"] and src["osm_api"]["enabled"] is True and "ODbL" in src["osm_api"]["license_note"]
    assert src["osm_overpass"]["hosts"] == ["overpass-api.de"]
    enabled_hosts = sorted(h for v in src.values() if v.get("enabled") for h in v["hosts"])
    assert enabled_hosts == ["api.openstreetmap.org", "atlas.microsoft.com", "overpass-api.de"]
    c = client(transport=Transport([(200, b"")]))
    with pytest.raises(B.SourceError) as e: c.request("osm_api", "https://overpass-api.de/api/interpreter")
    assert e.value.code == "SOURCE_HOST_NOT_ALLOWED"


def test_the_user_agent_is_ours_never_the_library_default(tmp_path):
    t = Transport([(200, xml([MAIN]))])
    osm.fetch_ways(client(transport=t), LAT0, LON0)
    ua = t.calls[0]["headers"]["User-Agent"]
    assert ua == B.load_sources()["user_agent"] and ua.startswith("tcp-planner") and "python-requests" not in ua.lower() and "python-urllib" not in ua.lower()
    for word in ("@", "contact", "pike", "hexaware", "http"): assert word not in ua.lower()


def test_the_timeout_is_the_sources_read_timeout():
    t = Transport([(200, xml([MAIN]))])
    osm.fetch_ways(client(transport=t), LAT0, LON0)
    assert t.calls[0]["timeout"] == B.load_sources()["sources"]["osm_api"]["timeout_s"] == 90


# ================================================================= the same ways from both providers
def test_the_same_ways_from_overpass_json_and_from_xml_have_the_same_structure_and_the_same_rule_results():
    ways_def = [MAIN, (2, {"highway": "service", "name": "Lot"}, [(-30.0, 40.0), (30.0, 60.0)]),
                (3, {"highway": "residential", "oneway": "yes", "lanes": "1"}, [(-5.0, -90.0), (-5.0, 0.0), (5.0, 90.0)])]
    from_json = osm.parse_overpass(overpass_json(ways_def), (LAT0, LON0))
    from_xml = osm_api.parse_map_xml(xml(ways_def), (LAT0, LON0), CLASSES)
    key = lambda ws: sorted(((w.id, tuple(sorted(w.tags.items())), tuple((round(x, 3), round(y, 3)) for x, y in w.points)) for w in ws))
    assert key(from_json) == key(from_xml)
    assert all(type(a) is type(b) for a, b in zip(from_json, from_xml))
    a, b = OR.osm_read(tuple(from_json)), OR.osm_read(tuple(from_xml))
    assert (a.way_id, a.tags, a.questions) == (b.way_id, b.tags, b.questions)
    assert {k: (v.outcome, v.value, v.reason_code, v.lower_confidence) for k, v in a.readings.items()} == {k: (v.outcome, v.value, v.reason_code, v.lower_confidence) for k, v in b.readings.items()}
    assert round(a.distance_m, 3) == round(b.distance_m, 3)


def test_fetch_ways_gives_the_same_ways_through_either_provider(tmp_path):
    ways_def = [MAIN, (3, {"highway": "residential", "oneway": "yes", "lanes": "1"}, [(-5.0, -90.0), (5.0, 90.0)])]
    a = osm.fetch_ways(client(transport=Transport([(200, xml(ways_def))])), LAT0, LON0)
    b = osm.fetch_ways(client(transport=Transport([(200, overpass_json(ways_def))], hosts=("overpass-api.de",))), LAT0, LON0, overpass_cfg())
    norm = lambda r: sorted((w.id, tuple(sorted(w.tags.items())), tuple((round(x, 3), round(y, 3)) for x, y in w.points)) for w in r.ways)
    assert norm(a) == norm(b) and a.origin == b.origin


# ================================================================= fixtures
def test_the_recorded_fixture_holds_the_raw_xml_the_request_url_and_the_source(tmp_path):
    t = Transport([(200, xml([MAIN]))])
    r = osm.fetch_ways(client(tmp_path, t), LAT0, LON0)
    d = tmp_path / "site" / "source"; files = os.listdir(d); assert len(files) == 1
    doc = json.load(open(d / files[0], encoding="utf-8"))
    assert doc["source"] == "osm_api" and doc["request"]["source_id"] == "osm_api" and doc["request"]["url"] == "https://api.openstreetmap.org/api/0.6/map" and "bbox" in doc["request"]["params"]
    raw = base64.b64decode(doc["body_b64"]); assert raw.startswith(b"<?xml") and b"<osm" in raw and files[0] == osm.request_key(LAT0, LON0) + ".json"
    again = osm.fetch_ways(client(tmp_path, None), LAT0, LON0)
    assert again.call.replayed is True and [w.id for w in again.ways] == [w.id for w in r.ways] and len(t.calls) == 1


def test_changing_the_provider_records_again_and_never_reuses_the_other_providers_fixture(tmp_path):
    osm.fetch_ways(client(tmp_path, Transport([(200, xml([MAIN]))])), LAT0, LON0)
    with pytest.raises(MissingFixtureError): osm.fetch_ways(client(tmp_path, None), LAT0, LON0, overpass_cfg())
    t2 = Transport([(200, overpass_json([MAIN]))], hosts=("overpass-api.de",))
    osm.fetch_ways(client(tmp_path, t2), LAT0, LON0, overpass_cfg())
    assert len(os.listdir(tmp_path / "site" / "source")) == 2 and osm.request_key(LAT0, LON0) != osm.request_key(LAT0, LON0, overpass_cfg())


def test_the_recorder_replays_what_is_recorded_reports_the_boxes_and_continues_a_partly_recorded_site(tmp_path):
    rec = load("s06_record_osm")
    sites = [{"site_id": "A", "lat": LAT0, "lon": LON0}]
    far = xml([(1, {"highway": "residential"}, [(-100.0, 250.0), (100.0, 250.0)])])
    t = Transport([(200, far), (200, xml([MAIN]))])
    out = rec.record_sites(sites, str(tmp_path / "fx"), t, sleep=lambda s: None, log=lambda *_: None)
    assert out[0]["status"] == "recorded" and out[0]["boxes"] == [300, 600] and "600" in out[0]["note"] and out[0]["ways"] == 1 and len(t.calls) == 2
    t2 = Transport([(200, b"")]); again = rec.record_sites(sites, str(tmp_path / "fx"), t2, sleep=lambda s: None, log=lambda *_: None)
    assert again[0]["status"] == "skipped" and t2.calls == []
    # a site whose first box is recorded but whose wider box is not: only the missing request goes out
    import shutil; fx2 = tmp_path / "fx2"; shutil.copytree(tmp_path / "fx", fx2)
    files = sorted(os.listdir(fx2 / "A" / "source"), key=lambda n: -os.path.getmtime(fx2 / "A" / "source" / n)); os.remove(fx2 / "A" / "source" / files[0])
    t3 = Transport([(200, xml([MAIN]))]); part = rec.record_sites(sites, str(fx2), t3, sleep=lambda s: None, log=lambda *_: None)
    assert part[0]["status"] == "recorded" and len(t3.calls) == 1


def test_the_recorder_stops_the_run_when_asked_and_leaves_the_rest_not_attempted(tmp_path):
    rec = load("s06_record_osm")
    sites = [{"site_id": s, "lat": LAT0 + i * 0.01, "lon": LON0} for i, s in enumerate("ABC")]
    t = Transport([(502, b"<html><body>Bad Gateway</body></html>")]); state = {"stop": None}

    def stop(): return state["stop"]
    inner = t

    def wrapped(*a, **k):
        r = inner(*a, **k)
        if r[0] == 502: state["stop"] = "HTTP 502"
        return r
    waits = []
    out = rec.record_sites(sites, str(tmp_path / "fx"), wrapped, sleep=waits.append, log=lambda *_: None, stop=stop)
    assert [r["status"] for r in out] == ["failed", "not_attempted", "not_attempted"] and len(t.calls) == 1 and waits == []             # no retry, no wait


# ================================================================= the pipeline's limited transport
P = load("s06_osm_pipeline")


class Clock:
    def __init__(self): self.t, self.sleeps = 0.0, []

    def __call__(self): return self.t

    def sleep(self, s): self.sleeps.append(s); self.t += s


def limited(answers, max_requests=8, gap=3, stops=(429, 502, 503, 504, 509)):
    c = Clock(); inner = Transport(answers)
    return P.LimitedTransport(inner, max_requests, gap, stops, c, c.sleep), inner, c


def call(lt, i=0): return lt("GET", "https://api.openstreetmap.org/api/0.6/map", {"bbox": str(i)}, None, {}, 90)


def test_at_most_8_requests_with_at_least_3_seconds_between_them():
    lt, inner, c = limited([(200, b"<osm/>")])
    for i in range(8): call(lt, i)
    assert lt.count == 8 and c.sleeps == [3.0] * 7
    with pytest.raises(P.RunStopped, match="request limit of 8"): call(lt)
    assert len(inner.calls) == 8 and lt.stop_reason == "request limit of 8 reached"


@pytest.mark.parametrize("status", [429, 509, 502, 503, 504])
def test_the_first_429_509_or_gateway_page_stops_the_run_and_keeps_the_page_text(status):
    lt, inner, c = limited([(200, b"<osm/>"), (status, b"<html><style>p{}</style><body><h1>failed to connect</h1><p>Connection refused</p></body></html>")])
    call(lt, 0)
    assert call(lt, 1)[0] == status and lt.stop_reason == f"HTTP {status}" and lt.stop_page == "failed to connect Connection refused"
    with pytest.raises(P.RunStopped): call(lt, 2)
    assert len(inner.calls) == 2


def test_other_errors_do_not_stop_the_run():
    lt, inner, c = limited([(400, b"x"), (500, b"x"), (200, b"<osm/>")])
    for i in range(3): call(lt, i)
    assert lt.stop_reason is None and lt.count == 3


def test_the_limits_come_from_config_calibration_pending():
    cfg = load_site_config()["osm_diagnose"]
    assert cfg["api_max_requests"]["value"] == 8 and cfg["api_min_gap_s"]["value"] == 3 and cfg["stop_statuses"]["value"] == [429, 502, 503, 504, 509]
    for k in ("api_max_requests", "api_min_gap_s", "stop_statuses"): assert cfg[k]["source"] == "CALIBRATION_PENDING"


# ================================================================= diagnose and pipeline with the osm_api provider
D = load("s06_osm_diagnose")
SITE = {"site_id": "granite", "lat": LAT0, "lon": LON0}


def test_the_diagnose_project_path_for_osm_api_is_the_only_variant_and_calls_no_other_host():
    t = Transport([(200, xml([MAIN]))])
    r = D.real_runners(SITE, load_site_config(), B.load_sources(), t)
    assert list(r) == ["a"]
    res = r["a"]()
    assert res["status"] == 200 and res["json_ok"] is True and res["error"] is None and D.passed([res], 60) is True
    assert all(c["url"].startswith("https://api.openstreetmap.org/") for c in t.calls)


def test_stage_one_passes_on_200_and_parseable_xml_under_60_s_and_fails_otherwise():
    assert D.passed([D.result("a", 200, 100, 0.1, None, 5.0, None, True)], 60) is True
    assert D.passed([D.result("a", 200, 100, 0.1, None, 5.0, None, False)], 60) is False                     # XML not parseable
    assert D.passed([D.result("a", 200, 100, 0.1, None, 61.0, None, True)], 60) is False
    t = Transport([(200, b"<html>not osm</html>")])
    res = D.real_runners(SITE, load_site_config(), B.load_sources(), t)["a"]()
    assert res["json_ok"] is False and D.passed([res], 60) is False


def test_a_gateway_page_on_the_project_path_is_reported_with_status_and_text():
    t = Transport([(502, b"<html><body><h1>failed to connect</h1><p>Connection refused</p></body></html>")])
    res = D.real_runners(SITE, load_site_config(), B.load_sources(), t)["a"]()
    assert res["status"] == 502 and res["error"] == "SOURCE_HTTP_ERROR" and "Connection refused" in res["body_head"] and D.passed([res], 60) is False


def test_parseable_follows_the_provider():
    assert D.parseable(xml([MAIN]), "osm_api") is True and D.parseable(b"{}", "osm_api") is False and D.parseable(b"{}", "overpass") is True
    assert D.parseable(b"<osm/>", "overpass") is False


def test_the_dry_runs_name_the_provider_and_request_nothing(tmp_path, capsys):
    rec = load("s06_record_osm")
    p = tmp_path / "s.csv"; p.write_text("site_id,lat,lon,extent_m\nA,%s,%s,212.4\n" % (LAT0, LON0), encoding="utf-8")
    assert rec.main(["--sites", str(p), "--out", str(tmp_path / "fx"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "GET https://api.openstreetmap.org/api/0.6/map?bbox=" in out and "provider osm_api" in out and not (tmp_path / "fx").exists()
    assert D.main(["--sites", str(p), "--dry-run"]) == 0
    assert "only variant a" in capsys.readouterr().out


def pipeline_world(tmp_path):
    sites = tmp_path / "sites.csv"; sites.write_text("site_id,lat,lon,extent_m,ta_situation\ngranite,%s,%s,212.4,x\nsecond,42.337438,-71.0268586,212.4,y\n" % (LAT0, LON0), encoding="utf-8")
    ts = tmp_path / "ts.csv"; ts.write_text("site_id,lat,lon,extent_m,ta_situation\ngranite,%s,%s,212.4,x\n" % (LAT0, LON0), encoding="utf-8")
    truth = tmp_path / "truth.csv"
    truth.write_text("site_id,lanes_per_direction,divided_highway,shoulder_present,oneway,parking_present,sidewalk_present,work_location,road_width_ft,truth_source,ta_situation\n"
                     "granite,2,false,false,false,false,true,,,drawing,x\n", encoding="utf-8")
    return str(sites), str(ts), str(truth)


def test_the_pipeline_runs_all_stages_with_the_osm_api_provider_and_never_touches_overpass(tmp_path, capsys):
    sites, ts, truth = pipeline_world(tmp_path)
    c = Clock(); times = []

    def answer_for(method, url, params, body, headers, timeout):
        assert url.startswith("https://api.openstreetmap.org/"), url
        times.append(c())
        left, bottom, right, top = (float(v) for v in params["bbox"].split(","))
        lat0, lon0 = (bottom + top) / 2, (left + right) / 2
        return 200, xml([(1, {"highway": "secondary", "name": "Main St", "ref": "US 1", "lanes": "4", "oneway": "no", "shoulder": "no", "maxspeed": "35 mph"}, EW5)], lat0, lon0)
    times = []
    runners = {"a": lambda: D.result("a", 200, 100, 0.1, None, 2.0, None, True)}
    rc = P.main(["--sites", sites, "--truth-sites", ts, "--truth", truth, "--out-dir", str(tmp_path / "runs")], runners=runners, transport=answer_for, clock=c, sleep=c.sleep,
                fixtures_root=str(tmp_path / "fx"), results_root=str(tmp_path / "var"), limit_transport=True)
    assert rc == 0
    run = tmp_path / "runs" / sorted(os.listdir(tmp_path / "runs"))[-1]
    report = (run / "REPORT.md").read_text(encoding="utf-8")
    assert "| granite | recorded | 1 |" in report and "box half-sizes asked (m)" in report and "| 300 |" in report and "all stages passed" in report
    assert (run / "second_source.csv").is_file() and "US 1" in report and "35 mph" in report
    assert len(times) == 2 and all(b - a >= 3 for a, b in zip(times, times[1:]))                               # at least 3 s between requests


def test_the_pipeline_stops_on_a_gateway_page_and_prints_the_status_and_the_page_text(tmp_path, capsys):
    sites, ts, truth = pipeline_world(tmp_path); c = Clock()
    gateway = (502, b"<html><body><h1>failed to connect</h1><p>The destination is not reachable. Connection refused</p></body></html>")
    seen = []

    def tr(method, url, params, body, headers, timeout): seen.append(url); return gateway
    rc = P.main(["--sites", sites, "--truth-sites", ts, "--truth", truth, "--out-dir", str(tmp_path / "runs")], transport=tr, clock=c, sleep=c.sleep,
                fixtures_root=str(tmp_path / "fx"), results_root=str(tmp_path / "var"), limit_transport=True,
                runners=D.real_runners)
    assert rc == 1
    out = capsys.readouterr().out
    assert "STAGE 1 FAILED" in out and "HTTP 502" in out and "Send REPORT.md" in out
    assert not (tmp_path / "fx").exists()


def test_osm_api_module_does_not_import_the_legacy_adapter_or_any_other_host():
    src = open(osm_api.__file__, encoding="utf-8").read()
    assert "osm_overpass" not in src.replace("API_SOURCE_ID", "") and "overpass-api.de" not in src and "api.openstreetmap.org" not in src      # the host is config
    import re
    assert not re.findall(r"https?://", src.split('"""', 2)[2])
