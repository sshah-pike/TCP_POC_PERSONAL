"""OpenStreetMap through the public Overpass API (S6 commit 3; D-53, D-62).

One small bounded query per site: highway ways within a radius of the work point, tags and geometry only. Everything goes
through `SourceClient` (allow list, fingerprint, fixture replay, size bound, SourceCall record). OSM values are LOW confidence
by default (D-92) and never fill a mandatory start field.

Geometry is kept in a local frame around the work point: x east, y north, metres (equirectangular, fine for a few hundred metres).
"""
import json
import math
from typing import NamedTuple

from tcp_planner.data_sources.base import SourceClient, SourceError
from tcp_planner.site_model.site_config import load_site_config, setting

SOURCE_ID = "osm_overpass"
URL = "https://overpass-api.de/api/interpreter"
EARTH_R_M = 6371008.8


class OsmWay(NamedTuple):
    id: int
    tags: dict
    points: tuple          # ((x_east_m, y_north_m), ...) in the local frame of the query


class OsmResult(NamedTuple):
    ways: tuple
    call: object           # SourceCall
    origin: tuple          # (lat, lon) of the local frame


def to_local(lat0, lon0, lat, lon):
    """(east_m, north_m) of a point in the local frame at (lat0, lon0)."""
    k = math.pi / 180 * EARTH_R_M
    return ((lon - lon0) * k * math.cos(math.radians(lat0)), (lat - lat0) * k)


def build_query(lat, lon, radius_m, classes, timeout_s):
    """Overpass QL: ways of the listed highway classes within radius_m, tags and geometry. The class list and the server-side timeout come from config."""
    pat = "|".join(classes)
    return (f'[out:json][timeout:{timeout_s:g}];way(around:{radius_m:g},{lat:.7f},{lon:.7f})["highway"~"^({pat})$"];out tags geom;')


def parse_overpass(content, origin):
    """Ways from an Overpass JSON answer. A way without geometry or with fewer than two points is dropped."""
    try:
        doc = json.loads(content)
    except ValueError as e:
        raise SourceError("SOURCE_BAD_RESPONSE", f"Overpass answer is not JSON: {e}")
    if not isinstance(doc, dict) or not isinstance(doc.get("elements"), list):
        raise SourceError("SOURCE_BAD_RESPONSE", "Overpass answer has no elements list")
    ways = []
    for el in doc["elements"]:
        if not isinstance(el, dict) or el.get("type") != "way" or not isinstance(el.get("id"), int): continue
        geom = el.get("geometry")
        if not isinstance(geom, list): continue
        pts = tuple(to_local(origin[0], origin[1], g["lat"], g["lon"]) for g in geom
                    if isinstance(g, dict) and isinstance(g.get("lat"), (int, float)) and isinstance(g.get("lon"), (int, float)))
        tags = {str(k): str(v) for k, v in (el.get("tags") or {}).items()}
        if len(pts) >= 2: ways.append(OsmWay(el["id"], tags, pts))
    return tuple(ways)


def fetch_ways(client: SourceClient, lat, lon, cfg=None, radius_m=None):
    """OsmResult for the highway ways near (lat, lon). Refuses a radius above the allow list's query limit and an answer with
    more elements than allowed. A source failure raises SourceError; the caller turns it into UNKNOWN with reason source_failed."""
    cfg = cfg or load_site_config()
    radius = radius_m if radius_m is not None else setting("osm", "query_radius_m", cfg)[0]
    limits = client.cfg["sources"][SOURCE_ID]["query_limits"]
    if radius > limits["max_radius_m"]:
        raise SourceError("SOURCE_QUERY_TOO_LARGE", f"radius {radius} m is above the limit of {limits['max_radius_m']} m")
    q = build_query(lat, lon, radius, setting("osm", "highway_classes", cfg)[0], setting("osm", "query_timeout_s", cfg)[0])
    resp = client.request(SOURCE_ID, URL, params={"data": q}, attribute_names=("highway", "lanes", "lanes:forward", "lanes:backward",
                                                                                 "oneway", "shoulder", "sidewalk", "name", "ref"))
    try:
        n = len(json.loads(resp.content).get("elements", []))
    except (ValueError, AttributeError):
        n = 0
    if n > limits["max_elements"]:
        raise SourceError("SOURCE_RESPONSE_TOO_LARGE", f"Overpass returned {n} elements; the limit is {limits['max_elements']}")
    return OsmResult(parse_overpass(resp.content, (lat, lon)), resp.call, (lat, lon))


# ---------------------------------------------------------------- local geometry
def point_to_polyline(pt, points):
    """(distance_m, nearest_point, segment_bearing_deg) from pt to the polyline. Bearing is the compass bearing of the nearest
    segment in the direction the way is drawn (0 = north, clockwise, 0 to 360)."""
    best = None
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - x1) * dx + (pt[1] - y1) * dy) / L2))
        nx, ny = x1 + t * dx, y1 + t * dy
        d = math.hypot(pt[0] - nx, pt[1] - ny)
        if best is None or d < best[0]:
            best = (d, (nx, ny), bearing_deg(dx, dy))
    return best


def bearing_deg(dx_east, dy_north):
    return math.degrees(math.atan2(dx_east, dy_north)) % 360


def axis_diff_deg(a, b):
    """Smallest angle between two bearings taken modulo 180 (a road has no direction): 0 to 90."""
    d = abs(a - b) % 180
    return min(d, 180 - d)


def direction_diff_deg(a, b):
    """Smallest angle between two bearings taken modulo 360: 0 to 180."""
    d = abs(a - b) % 360
    return min(d, 360 - d)
