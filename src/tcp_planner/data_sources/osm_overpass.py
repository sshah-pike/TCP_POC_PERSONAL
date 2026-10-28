"""OpenStreetMap adapter: supplemental road-network evidence only (never decides regulation alone)."""
import math, re
import xml.etree.ElementTree as ET
from tcp_planner.contracts import OsmError
from tcp_planner.geometry.local_frame import enu, cum, project, signed_lateral, at

DRIVABLE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "living_street", "service", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
CONVENTIONAL = {"primary", "secondary", "tertiary", "unclassified", "residential"}
INTERSECTION_NODES = {"traffic_signals", "stop", "give_way"}


def fetch_osm(lat, lon, radius_m):
    import requests
    dlat = radius_m / 111320; dlon = radius_m / (111320 * max(math.cos(math.radians(lat)), 0.01))
    bbox = f"{lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
    try:
        resp = requests.get("https://api.openstreetmap.org/api/0.6/map", params={"bbox": bbox},
                            timeout=(5, 30), headers={"User-Agent": "tcp-poc/0.2"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        raise OsmError("OSM_REQUEST_FAILED", type(e).__name__)
    coords, elements = {}, []
    for node in root.findall("node"):
        nid = node.get("id"); pt = {"lat": float(node.get("lat")), "lon": float(node.get("lon"))}
        coords[nid] = pt
        tags = {t.get("k"): t.get("v") for t in node.findall("tag")}
        if tags.get("highway") in INTERSECTION_NODES | {"crossing", "mini_roundabout"}:
            elements.append(dict(type="node", id=nid, **pt, tags=tags))
    for way in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        refs = [n.get("ref") for n in way.findall("nd")]
        if tags.get("highway") and len(refs) > 1 and all(x in coords for x in refs):
            elements.append(dict(type="way", id=way.get("id"), tags=tags, nodes=refs,
                                 geometry=[coords[x] for x in refs],
                                 timestamp=way.get("timestamp"), version=way.get("version")))  # last edit of the way
    return elements


def parse_maxspeed_mph(value):
    """Informational only. Returns (mph, unit) or (None, None); never assumes a value."""
    if not value: return None, None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?\s*$", value, re.I)
    if not m: return None, None
    v = float(m.group(1)); unit = (m.group(2) or "km/h").lower()
    return (round(v), "mph") if unit == "mph" else (round(v / 1.609344), "km/h")


def _parse_width_m(value):
    if not value: return None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(m)?\s*$", value)
    return float(m.group(1)) if m else None


def _facility_from_highway(tags):
    hw = tags.get("highway", "")
    if tags.get("junction") in ("roundabout", "circular"): return "ROUNDABOUT"
    if hw == "motorway": return "FREEWAY"
    if hw == "trunk": return "TRUNK_ROAD"
    if hw.endswith("_link"): return "RAMP_OR_LINK"
    if hw in CONVENTIONAL: return "CONVENTIONAL_ROAD"
    return "OTHER_" + hw.upper() if hw else None


def _join_chain(target, ways, tol):
    """Extend the target way through end-to-end connected ways of the same road (same name/ref)."""
    key = lambda w: (w["tags"].get("name"), w["tags"].get("ref"))
    same = [w for w in ways if w is not target and key(w) == key(target) and any(key(target))]
    chain = list(target["pts"]); used = [target["id"]]
    for end in ("tail", "head"):
        while True:
            tip = chain[-1] if end == "tail" else chain[0]
            nxt = None
            for w in same:
                if w["id"] in used: continue
                starts, ends = math.dist(w["pts"][0], tip) <= tol, math.dist(w["pts"][-1], tip) <= tol
                if end == "tail" and (starts or ends):   # orient so pts[0] touches the tail
                    nxt = (w, w["pts"] if starts else w["pts"][::-1]); break
                if end == "head" and (starts or ends):   # orient so pts[-1] touches the head
                    nxt = (w, w["pts"] if ends else w["pts"][::-1]); break
            if not nxt: break
            w, pts = nxt; used.append(w["id"])
            chain = chain + pts[1:] if end == "tail" else pts[:-1] + chain
    return chain, used


def extract_evidence(elements, project_geometry, config):
    """Turn raw OSM elements into OSM observations in the local frame (origin = work reference)."""
    ref = project_geometry["work_reference"]; lat0, lon0 = ref["latitude"], ref["longitude"]
    cfg = config["osm"]
    ways = [dict(id=str(e["id"]), tags=e.get("tags", {}), timestamp=e.get("timestamp"), version=e.get("version"),
                 pts=[enu(g["lat"], g["lon"], lat0, lon0) for g in e["geometry"]])
            for e in elements if e["type"] == "way" and e.get("tags", {}).get("highway") in DRIVABLE
            and len(e.get("geometry", [])) > 1]
    if not ways:
        raise OsmError("OSM_NO_ROAD", "no drivable road found near the work reference")
    target = min(ways, key=lambda w: project(w["pts"], (0, 0))[0])
    centerline, chain_ids = _join_chain(target, ways, cfg["endpoint_join_tolerance_m"])
    T = target["tags"]
    chain_ways = [w for w in ways if w["id"] in chain_ids]
    variation = sorted({k for k in ("lanes", "oneway", "maxspeed", "highway")
                        if len({w["tags"].get(k) for w in chain_ways}) > 1})

    feats = {"intersections": [], "driveways": [], "crosswalks": [], "roundabouts": [], "ramps": []}
    attach = cfg["feature_attach_distance_m"]
    for w in ways:
        if w["id"] in chain_ids: continue
        hits = [(project(centerline, p), p) for p in w["pts"]]
        (d, s, _), _p = min(hits, key=lambda h: h[0][0])
        fac = _facility_from_highway(w["tags"])
        if fac == "ROUNDABOUT":
            feats["roundabouts"].append({"source": "OSM", "way_id": w["id"], "station_m": round(s, 2), "distance_m": round(d, 2)})
            continue
        if d > attach: continue
        sides = {("LEFT" if signed_lateral(centerline, p)[2] > 0 else "RIGHT") for p in w["pts"]
                 if signed_lateral(centerline, p)[0] > attach}
        side = "BOTH" if len(sides) == 2 else (sides.pop() if sides else "UNKNOWN")
        item = {"source": "OSM", "way_id": w["id"], "highway": w["tags"].get("highway"),
                "name": w["tags"].get("name"), "station_m": round(s, 2), "side": side}
        hw = w["tags"].get("highway", "")
        if hw == "service": feats["driveways"].append(item)
        elif fac in ("RAMP_OR_LINK", "FREEWAY", "TRUNK_ROAD"): feats["ramps"].append(item)
        else: feats["intersections"].append(item)
    for e in elements:
        if e["type"] != "node": continue
        p = enu(e["lat"], e["lon"], lat0, lon0); d, s, _ = project(centerline, p)
        if d > cfg["node_attach_distance_m"]: continue
        hw = e.get("tags", {}).get("highway")
        item = {"source": "OSM", "node_id": str(e["id"]), "highway": hw, "station_m": round(s, 2)}
        if hw == "crossing": feats["crosswalks"].append(item)
        elif hw == "mini_roundabout": feats["roundabouts"].append(item)
        elif hw in INTERSECTION_NODES: feats["intersections"].append(item)

    sidewalk = {"left": None, "right": None}
    sw = T.get("sidewalk")
    if sw in ("both", "left", "right", "no", "none", "separate"):
        sidewalk["left"] = sw in ("both", "left", "separate")
        sidewalk["right"] = sw in ("both", "right", "separate")
    for side in ("left", "right"):
        v = T.get(f"sidewalk:{side}")
        if v in ("yes", "separate"): sidewalk[side] = True
        elif v == "no": sidewalk[side] = False
    for e in elements:  # separately mapped sidewalks
        if e["type"] == "way" and e.get("tags", {}).get("footway") == "sidewalk":
            for g in e["geometry"]:
                d, s, lat = signed_lateral(centerline, enu(g["lat"], g["lon"], lat0, lon0))
                if d <= 20: sidewalk["left" if lat > 0 else "right"] = True

    mph, unit = parse_maxspeed_mph(T.get("maxspeed"))
    # explicit = the tag is present on the target way itself; a missing (implicit) tag never counts as agreement
    agreement_tags = sorted({t for tags in config.get("agent", {}).get("agreement_fields", {}).values() for t in tags})
    return {
        "target_way": {"id": target["id"], "timestamp": target["timestamp"], "version": target["version"],
                       "explicit_tags": {t: T[t] for t in agreement_tags if t in T},
                       "tag_is_explicit": {t: t in T for t in agreement_tags}},
        "target_way_ids": chain_ids, "name": T.get("name"), "highway": T.get("highway"),
        "facility_type": _facility_from_highway(T), "chain_tag_variation": variation,
        "lanes_tag": int(T["lanes"]) if str(T.get("lanes", "")).isdigit() else None,
        "oneway_tag": T.get("oneway"), "dual_carriageway_tag": T.get("dual_carriageway"),
        "divider_tag": T.get("divider"), "width_m": _parse_width_m(T.get("width")),
        "maxspeed_raw": T.get("maxspeed"), "maxspeed_mph": mph, "maxspeed_unit": unit,
        "centerline_enu": centerline, "centerline_length_m": round(cum(centerline)[-1], 2),
        "features": feats, "sidewalks": sidewalk,
    }
