"""OSM main API provider (S6): the 0.6 map call with a bounding box. The default OSM provider; Overpass stays selectable (config osm.provider).

The old fast adapter used this service; the Overpass server was slow (28 s) and the company gateway blocked most other requests to it.
This provider returns the SAME internal structure as the Overpass one (`OsmWay`: id, tags, ordered points in the local frame in metres), so
the OSM rules, the bearing check, fusion and the trace do not know which provider ran.

  1. box          a square of half-size osm.api_bbox_half_m around the point (metres per degree from the earth radius), refused when its area
                  is above osm.api_max_bbox_area_deg2 (the API's own limit); sent as bbox=left,bottom,right,top
  2. parse        XML: nodes, then ways. Only ways with a highway tag in osm.highway_classes are kept; geometry is built from the nodes in the
                  order of the way. A way that crosses the box with no node inside it is kept when the API returned it
  3. filter       the box is not the query: a way is kept by the TRUE distance from the point to its polyline, within osm.query_radius_m
  4. retries      no highway way within the radius: ONE more call with osm.api_bbox_retry_half_m. HTTP 400 too many nodes: ONE more call with
                  osm.api_bbox_shrink_half_m. Both are recorded in `OsmResult.info` for the trace. A timeout or an HTTP 408, 429 or 5xx is
                  retried by the recorder with osm.retry_waits_s (the same retry config as Overpass); HTTP 400 otherwise is never retried
Every request goes through the allow-listed SourceClient (host from config and config/data_sources.json, the project User-Agent, the source's
timeout, fixture replay); the raw XML and the request URL are the recorded fixture, with source "osm_api".
"""
import math
import xml.etree.ElementTree as ET

from tcp_planner.data_sources import osm as O
from tcp_planner.data_sources.base import SourceError
from tcp_planner.site_model.site_config import load_site_config, setting

API_SOURCE_ID = "osm_api"
ATTRIBUTES = ("highway", "lanes", "lanes:forward", "lanes:backward", "oneway", "shoulder", "sidewalk", "name", "ref")


def bbox_for(lat, lon, half_m, max_area_deg2):
    """(left, bottom, right, top) of a square of half-size `half_m` around the point; refused when its area exceeds the API limit."""
    k = math.pi / 180 * O.EARTH_R_M
    dlat, dlon = half_m / k, half_m / (k * math.cos(math.radians(lat)))
    left, bottom, right, top = lon - dlon, lat - dlat, lon + dlon, lat + dlat
    area = (right - left) * (top - bottom)
    if area > max_area_deg2:
        raise SourceError("SOURCE_QUERY_TOO_LARGE", f"a box of half-size {half_m} m is {area:.4f} square degrees; the API limit is {max_area_deg2}")
    return left, bottom, right, top


def bbox_param(b):
    return ",".join(f"{v:.7f}" for v in b)


def parse_map_xml(content, origin, classes):
    """Highway ways of an OSM map answer as OsmWay tuples (document order). Raises SourceError for an answer that is not OSM XML."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise SourceError("SOURCE_BAD_RESPONSE", f"the OSM answer is not XML: {e}")
    if root.tag != "osm":
        raise SourceError("SOURCE_BAD_RESPONSE", f"the OSM answer has the root element {root.tag!r}, not osm")
    nodes = {}
    for n in root.findall("node"):
        try: nodes[n.get("id")] = (float(n.get("lat")), float(n.get("lon")))
        except (TypeError, ValueError): continue
    ways = []
    for w in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in w.findall("tag") if t.get("k") is not None}
        if tags.get("highway") not in classes: continue
        pts = tuple(O.to_local(origin[0], origin[1], *nodes[r]) for r in (nd.get("ref") for nd in w.findall("nd")) if r in nodes)
        try: wid = int(w.get("id"))
        except (TypeError, ValueError): continue
        if len(pts) >= 2: ways.append(O.OsmWay(wid, tags, pts))
    return tuple(ways)


def within_radius(ways, radius_m):
    """The ways whose polyline lies within radius_m of the work point (the origin of the local frame): the true distance, not the box."""
    return tuple(w for w in ways if O.point_to_polyline((0.0, 0.0), w.points)[0] <= radius_m)


def too_many_nodes(error, text, status):
    return (error.code == "SOURCE_HTTP_ERROR" and (error.details or {}).get("http_status") == status
            and text.lower() in str((error.details or {}).get("body", "")).lower())


def first_request(lat, lon, cfg=None):
    """(url, params) of the first request this provider makes for a point (used to name the fixture)."""
    cfg = cfg or load_site_config()
    b = bbox_for(lat, lon, setting("osm", "api_bbox_half_m", cfg)[0], setting("osm", "api_max_bbox_area_deg2", cfg)[0])
    return setting("osm", "api_url", cfg)[0], {"bbox": bbox_param(b)}


def fetch_ways_api(client, lat, lon, cfg=None, radius_m=None):
    """OsmResult for the highway ways within the radius of (lat, lon). `info` records every box asked, the ways found, and whether the
    box was widened or shrunk. A source failure raises SourceError; the caller turns it into UNKNOWN (source_failed)."""
    cfg = cfg or load_site_config()
    s = lambda name: setting("osm", name, cfg)[0]
    url, classes = s("api_url"), s("highway_classes")
    radius = radius_m if radius_m is not None else s("query_radius_m")
    attempts = []
    info = {"provider": "osm_api", "url": url, "attempts": attempts, "widened": False, "shrunk": False, "note": None}

    def one(half):
        params = {"bbox": bbox_param(bbox_for(lat, lon, half, s("api_max_bbox_area_deg2")))}
        resp = client.request(API_SOURCE_ID, url, params=params, attribute_names=ATTRIBUTES)
        in_box = parse_map_xml(resp.content, (lat, lon), classes)
        near = within_radius(in_box, radius)
        attempts.append({"bbox_half_m": half, "bbox": params["bbox"], "bytes": len(resp.content), "highway_ways_in_answer": len(in_box), "ways_within_radius": len(near)})
        return resp, near

    try:
        resp, near = one(s("api_bbox_half_m"))
    except SourceError as e:
        if not too_many_nodes(e, s("api_too_many_nodes_text"), s("api_too_many_nodes_status")): raise
        attempts.append({"bbox_half_m": s("api_bbox_half_m"), "error": "HTTP 400 too many nodes"})
        info["shrunk"] = True; info["note"] = f"HTTP 400 too many nodes at half-size {s('api_bbox_half_m')} m: repeated once with {s('api_bbox_shrink_half_m')} m"
        resp, near = one(s("api_bbox_shrink_half_m"))
    if not near and not info["shrunk"]:
        info["widened"] = True; info["note"] = f"no highway way within {radius} m: repeated once with half-size {s('api_bbox_retry_half_m')} m"
        try:
            resp2, near2 = one(s("api_bbox_retry_half_m"))
        except SourceError as e:
            if not too_many_nodes(e, s("api_too_many_nodes_text"), s("api_too_many_nodes_status")): raise
            attempts.append({"bbox_half_m": s("api_bbox_retry_half_m"), "error": "HTTP 400 too many nodes"})
            info["note"] += "; the wider box held too many nodes, the first answer is kept"
        else:
            resp, near = resp2, near2
    return O.OsmResult(near, resp.call, (lat, lon), info)
