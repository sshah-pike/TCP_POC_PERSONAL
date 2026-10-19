"""KML / coordinate input -> canonical ProjectGeometry.

Only geometry is authoritative. Names, descriptions, styles, LookAt, links and ExtendedData are
display metadata: they are counted, never interpreted, and can never change rules or decisions.
"""
import math, os
import xml.etree.ElementTree as ET
from .models import InputRejected, canonical_json, sha256_hex, r
from .geometry import enu, cum

GEOMETRY_TAGS = {"Point", "LineString", "LinearRing", "Polygon", "MultiGeometry", "Model", "Track", "MultiTrack"}
METADATA_TAGS = {"name", "description", "Style", "StyleMap", "styleUrl", "LookAt", "Camera", "Snippet", "ExtendedData",
                 "link", "Link", "atom:link", "address", "phoneNumber"}
MAX_KML_BYTES = 5 * 1024 * 1024


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def _valid_latlon(lat, lon):
    return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def _parse_coords(text):
    pts = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) < 2: raise ValueError("coordinate tuple needs lon,lat")
        lon, lat = float(parts[0]), float(parts[1])
        if not _valid_latlon(lat, lon): raise ValueError("coordinate out of range")
        pts.append((lat, lon))
    if not pts: raise ValueError("empty coordinates")
    return pts


def from_coordinates(lat, lon):
    try: lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise InputRejected(["INVALID_COORDINATES"], "latitude/longitude must be numbers")
    if not _valid_latlon(lat, lon):
        raise InputRejected(["INVALID_COORDINATES"], "latitude/longitude out of range")
    ref = {"latitude": r(lat, 7), "longitude": r(lon, 7)}
    return {"input_type": "COORDINATES", "source_file": None, "work_reference": ref, "work_path": [],
            "input_feature_count": 1, "input_hash": "sha256:" + sha256_hex(canonical_json(ref)),
            "non_authoritative_metadata": {"ignored_element_count": 0}}


def parse_kml(path, max_work_path_m):
    if not os.path.isfile(path):
        raise InputRejected(["INVALID_KML"], "KML file not found")
    with open(path, "rb") as f: raw = f.read(MAX_KML_BYTES + 1)
    if len(raw) > MAX_KML_BYTES:
        raise InputRejected(["INVALID_KML"], "KML file too large for this POC")
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise InputRejected(["INVALID_KML"], "DTD/entity declarations are not accepted")
    try: root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise InputRejected(["INVALID_KML"], f"KML is not well-formed XML ({e.code})")
    if _local(root.tag) != "kml":
        raise InputRejected(["INVALID_KML"], "root element is not <kml>")

    points, lines, unsupported, ignored = [], [], [], 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag in METADATA_TAGS: ignored += 1
        if tag not in GEOMETRY_TAGS: continue
        if tag == "Point":
            c = next((x for x in el if _local(x.tag) == "coordinates"), None)
            try: pts = _parse_coords(c.text if c is not None else "")
            except ValueError: raise InputRejected(["INVALID_COORDINATES"], "Point has invalid coordinates")
            if len(pts) != 1: raise InputRejected(["INVALID_COORDINATES"], "Point must have exactly one coordinate")
            points.append(pts[0])
        elif tag == "LineString":
            c = next((x for x in el if _local(x.tag) == "coordinates"), None)
            try: pts = _parse_coords(c.text if c is not None else "")
            except ValueError: raise InputRejected(["INVALID_COORDINATES"], "LineString has invalid coordinates")
            if len(pts) < 2: raise InputRejected(["INVALID_COORDINATES"], "LineString needs two or more coordinates")
            lines.append(pts)
        elif tag == "MultiGeometry":
            continue  # children are visited individually; counts below catch multiple work items
        else:
            # LinearRing inside a Polygon is reported once via Polygon
            if tag != "LinearRing": unsupported.append(tag)

    reasons = []
    if unsupported: reasons.append("UNSUPPORTED_GEOMETRY")
    if len(points) > 1: reasons.append("MULTIPLE_WORK_POINTS")
    if len(lines) > 1: reasons.append("MULTIPLE_WORK_AREAS")
    if not points: reasons.append("NO_WORK_REFERENCE_POINT")
    if reasons:
        raise InputRejected(reasons, "KML must contain exactly one work Point and at most one LineString work path",
                            {"points": len(points), "line_strings": len(lines), "unsupported": sorted(set(unsupported))})

    lat, lon = points[0]
    path_pts = lines[0] if lines else []
    if path_pts:
        local = [enu(a, b, lat, lon) for a, b in path_pts]
        length = cum(local)[-1]
        if length > max_work_path_m:
            raise InputRejected(["WORK_PATH_TOO_LONG"], "work path exceeds the POC short-path limit",
                                {"length_m": round(length, 1)})
    return {"input_type": "KML", "source_file": os.path.basename(path),
            "work_reference": {"latitude": r(lat, 7), "longitude": r(lon, 7)},
            "work_path": [{"latitude": r(a, 7), "longitude": r(b, 7)} for a, b in path_pts],
            "input_feature_count": len(points) + len(lines),
            "input_hash": "sha256:" + sha256_hex(raw),
            "non_authoritative_metadata": {"ignored_element_count": ignored}}
