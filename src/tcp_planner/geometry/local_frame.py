"""Geometry component: local ENU frame, stationing, projection, interpolation and placement.

enu/inv/cum/project/at are the original tcp_demo helpers, kept unchanged in behaviour.
Local frame: x east, y north, metres, origin = work reference. Lateral offsets are LEFT-positive
relative to the centerline digitisation direction (increasing station).
Stationing, transforms and rotation are implementation calculations, not regulatory values.
"""
import math
from tcp_planner.contracts import FT, r

R = 6378137.0


def enu(lat, lon, lat0, lon0):
    return (math.radians(lon - lon0) * R * math.cos(math.radians(lat0)), math.radians(lat - lat0) * R)


def inv(x, y, lat0, lon0):
    return (lat0 + math.degrees(y / R), lon0 + math.degrees(x / (R * math.cos(math.radians(lat0)))))


def cum(pts):
    s = [0.0]
    for a, b in zip(pts, pts[1:]): s.append(s[-1] + math.dist(a, b))
    return s


def project(pts, p):
    cs = cum(pts); best = (1e18, 0, None)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]; dx, dy = b[0] - a[0], b[1] - a[1]; L2 = dx * dx + dy * dy
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        q = (a[0] + t * dx, a[1] + t * dy); d = math.dist(p, q)
        if d < best[0]: best = (d, cs[i] + t * math.sqrt(L2), q)
    return best  # dist, station, point


def at(pts, s):
    cs = cum(pts)
    if s <= 0: a, b = pts[0], pts[1]; t = s / (cs[1] or 1)
    elif s >= cs[-1]: a, b = pts[-2], pts[-1]; t = 1 + (s - cs[-1]) / ((cs[-1] - cs[-2]) or 1)
    else:
        i = max(k for k in range(len(cs) - 1) if cs[k] <= s); a, b = pts[i], pts[i + 1]; t = (s - cs[i]) / ((cs[i + 1] - cs[i]) or 1)
    L = math.dist(a, b) or 1; tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), (tx, ty)


# ---------- additions ----------
def bearing_deg(tx, ty):
    """Compass bearing of a direction vector, degrees clockwise from north."""
    return math.degrees(math.atan2(tx, ty)) % 360.0


def signed_lateral(pts, p):
    """(abs distance, station, LEFT-positive signed offset) of p from the centerline."""
    d, s, q = project(pts, p)
    _, (tx, ty) = at(pts, min(max(s, 0.0), cum(pts)[-1]))
    cross = tx * (p[1] - q[1]) - ty * (p[0] - q[0])
    return d, s, (d if cross >= 0 else -d)


def offset_point(pts, s, lateral):
    (x, y), (tx, ty) = at(pts, s)
    return (x - ty * lateral, y + tx * lateral), (tx, ty)


def offset_polyline(pts, lateral, n=80):
    total = cum(pts)[-1]
    return [offset_point(pts, total * i / (n - 1), lateral)[0] for i in range(n)]


def to_latlon_list(pts, lat0, lon0, nd=7):
    return [{"latitude": r(a, nd), "longitude": r(b, nd)} for a, b in (inv(x, y, lat0, lon0) for x, y in pts)]


def from_latlon_list(items, lat0, lon0):
    return [enu(p["latitude"], p["longitude"], lat0, lon0) for p in items]


class SiteFrame:
    """Local frame derived from a SiteModel (centerline + origin + road half-widths)."""
    def __init__(self, site_model):
        ref = site_model["project_geometry"]["work_reference"]
        self.lat0, self.lon0 = ref["latitude"], ref["longitude"]
        self.centerline = from_latlon_list(site_model["road"]["centerline"], self.lat0, self.lon0)
        self.length = cum(self.centerline)[-1]
        edges = site_model["road"]["road_edges"]
        self.left_half = edges.get("left_offset_m"); self.right_half = edges.get("right_offset_m")
        self.work_station = site_model["work"]["reference_station_m"]

    def enu(self, lat, lon):
        return enu(lat, lon, self.lat0, self.lon0)

    def latlon(self, x, y):
        return inv(x, y, self.lat0, self.lon0)

    def half_width(self, side):
        return self.left_half if side == "LEFT" else self.right_half


# ---------- deterministic placement of semantic rule-engine objects ----------
APPROACH_DIRECTION = {"INCREASING_STATION": +1, "DECREASING_STATION": -1}


def place_objects(objects, site_model, config):
    """Fill `placement` for each semantic object. Returns (placed_objects, issues).

    Issues are reason codes; any issue means automatic placement is not safe (REVIEW_REQUIRED).
    """
    frame = SiteFrame(site_model)
    offset_cfg = config["placement"]["sign_offset_beyond_edge_m"]
    issues = []; placed = []
    for obj in objects:
        obj = dict(obj)
        req = obj.pop("placement_request")
        if req["kind"] == "WORK_REFERENCE":
            placed.append(_place_work(obj, site_model, frame)); continue
        direction = APPROACH_DIRECTION[req["approach"]]
        dist_m = req["longitudinal_distance_ft"] * FT
        station = frame.work_station - direction * dist_m  # upstream of the work for this approach
        if not (0.0 <= station <= frame.length):
            issues.append({"code": "PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY", "object": obj["object_id"]})
        # traffic's right-hand roadside: RIGHT of centerline for +1, LEFT for -1
        side = "RIGHT" if direction > 0 else "LEFT"
        half = frame.half_width(side)
        if half is None:
            issues.append({"code": "ROAD_EDGE_UNRESOLVED", "object": obj["object_id"]}); half = 0.0
        lateral = (half + offset_cfg) * (1 if side == "LEFT" else -1)
        (x, y), (tx, ty) = offset_point(frame.centerline, min(max(station, 0.0), frame.length), lateral)
        travel_bearing = bearing_deg(tx * direction, ty * direction)
        lat, lon = frame.latlon(x, y)
        obj["placement"] = {
            "approach": req["approach"], "reference": "WORK_STATION",
            "work_station_m": r(frame.work_station, 3), "station_m": r(station, 3),
            "longitudinal_distance_ft": r(req["longitudinal_distance_ft"], 3), "longitudinal_distance_m": r(dist_m, 3),
            "side_of_centerline": side, "edge_offset_from_centerline_m": r(half, 3),
            "offset_beyond_edge_m": r(offset_cfg, 3), "lateral_offset_from_centerline_m": r(abs(lateral), 3),
            "offset_source": "poc_config.placement.sign_offset_beyond_edge_m (implementation, non-regulatory)",
            "local_enu_m": [r(x, 3), r(y, 3)], "latitude": r(lat, 7), "longitude": r(lon, 7),
            "approach_bearing_deg": r(travel_bearing, 2),
            "face_azimuth_deg": r((travel_bearing + 180.0) % 360.0, 2),
            "rotation_rule": "14_orientation_rules.calculation",
        }
        placed.append(obj)
    return placed, issues


def _place_work(obj, site_model, frame):
    work = site_model["work"]; pg = site_model["project_geometry"]
    ref = pg["work_reference"]
    obj["placement"] = {
        "reference": "WORK_STATION", "station_m": r(frame.work_station, 3),
        "side_of_centerline": work["side"]["value"],
        "lateral_offset_from_centerline_m": work["lateral_offset_from_centerline_m"],
        "latitude": ref["latitude"], "longitude": ref["longitude"],
        "path": pg["work_path"], "local_enu_m": [0.0, 0.0],
    }
    return obj
