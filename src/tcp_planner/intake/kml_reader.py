"""KML / coordinate input -> WorkLocation records (parse_all) and the legacy single-point ProjectGeometry.

Only coordinates are authoritative (D-66). Names, descriptions, styles, LookAt, links and ExtendedData (including
tcp:* keys and selected_ta) are never interpreted: parse_all does not descend into ExtendedData, and a name is kept
only as a display label. parse_kml is the legacy adapter over the same scan until S3 removes the one-point limit.
"""
import math, os
import xml.etree.ElementTree as ET
from tcp_planner.contracts import InputRejected, canonical_json, sha256_hex, r
from tcp_planner.geometry.local_frame import enu, cum
from tcp_planner.intake import work_location as wl

GEOMETRY_TAGS = {"Point", "LineString", "LinearRing", "Polygon", "MultiGeometry", "Model", "Track", "MultiTrack"}
METADATA_TAGS = {"name", "description", "Style", "StyleMap", "styleUrl", "LookAt", "Camera", "Snippet", "ExtendedData",
                 "link", "Link", "atom:link", "address", "phoneNumber"}
CONTAINER_TAGS = {"kml", "Document", "Folder"}
UNSUPPORTED_TAGS = {"Model", "Track", "MultiTrack", "LinearRing"}
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


def location_from_coordinates(lat, lon):
    """A latitude/longitude pair -> one POINT WorkLocation (coordinates and offline projects, S3). Same checks as
    from_coordinates; the id and hash come from the geometry only, exactly as for a KML Point."""
    ref = from_coordinates(lat, lon)["work_reference"]
    geom = {"type": wl.POINT, "coords": [ref["latitude"], ref["longitude"]]}
    ghash = wl.geometry_hash_of(geom)
    return wl.WorkLocation(location_id=wl.base_location_id(ghash), ordinal=0,
                           source=wl.Source(file=None, input_hash=ghash, placemark_index=0, geometry_index=0, name=None),
                           geometry=geom, geometry_hash=ghash)


# ---------------------------------------------------------------- file level
def _load(source, file_name=None):
    """-> (raw bytes, root element, file name). File-level failures raise InputRejected(INVALID_KML)."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        if not os.path.isfile(source): raise InputRejected(["INVALID_KML"], "KML file not found")
        with open(source, "rb") as f: raw = f.read(MAX_KML_BYTES + 1)
        file_name = file_name or os.path.basename(source)
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
    return raw, root, file_name


# ---------------------------------------------------------------- one geometry element
def _child(el, tag):
    return next((x for x in el if _local(x.tag) == tag), None)


def _raw_text(el):
    return " ".join(t.strip() for t in el.itertext() if t.strip())


def _coords_of(el):
    """-> (pairs, reason). reason is None, EMPTY (no coordinates) or INVALID_GEOMETRY (malformed or out of range)."""
    c = _child(el, "coordinates")
    text = c.text if c is not None else ""
    if not (text or "").strip(): return [], wl.EMPTY
    try: pts = _parse_coords(text)
    except ValueError: return [], wl.INVALID_GEOMETRY
    return [[r(a, 7), r(b, 7)] for a, b in pts], None


def _ring_of(boundary):
    """A Polygon boundary element -> (ring, reason). A ring must be closed with 4 or more pairs."""
    ring_el = _child(boundary, "LinearRing")
    if ring_el is None: return [], wl.EMPTY
    pts, why = _coords_of(ring_el)
    if why: return [], why
    if len(pts) < 4 or pts[0] != pts[-1]: return [], wl.INVALID_GEOMETRY
    return pts, None


def _shape(el, tag):
    """One geometry element -> (geometry dict or None, reason or None)."""
    if tag == "Point":
        pts, why = _coords_of(el)
        if not why and len(pts) != 1: why = wl.INVALID_GEOMETRY
        return (None, why) if why else ({"type": wl.POINT, "coords": pts[0]}, None)
    if tag == "LineString":
        pts, why = _coords_of(el)
        if not why and len(pts) < 2: why = wl.INVALID_GEOMETRY
        return (None, why) if why else ({"type": wl.LINESTRING, "coords": pts}, None)
    if tag == "Polygon":
        outer = _child(el, "outerBoundaryIs")
        if outer is None: return None, wl.EMPTY
        rings = []
        for b in [outer] + [x for x in el if _local(x.tag) == "innerBoundaryIs"]:
            ring, why = _ring_of(b)
            if why: return None, why
            rings.append(ring)
        return {"type": wl.POLYGON, "coords": rings}, None
    return None, wl.UNSUPPORTED_TYPE


# ---------------------------------------------------------------- whole document
def _geometries(el):
    """Direct geometry children of a Placemark or MultiGeometry; MultiGeometry is flattened, nested ones too.
    Only direct children are read, so nothing inside ExtendedData is ever seen."""
    for ch in el:
        tag = _local(ch.tag)
        if tag == "MultiGeometry": yield from _geometries(ch)
        elif tag in GEOMETRY_TAGS: yield ch, tag


def _placemarks(el):
    for ch in el:
        tag = _local(ch.tag)
        if tag == "Placemark": yield ch
        elif tag in CONTAINER_TAGS: yield from _placemarks(ch)


def _scan(raw, root, file_name):
    """Every geometry of every Placemark -> [(WorkLocation, kml tag)] with ids assigned. The tag is for the legacy
    adapter only."""
    input_hash = "sha256:" + sha256_hex(raw)
    rows = []  # (placemark_index, geometry_index, name, geometry, reasons, geometry hash, tag)
    for pi, pm in enumerate(_placemarks(root)):
        name_el = _child(pm, "name")
        name = (name_el.text or "").strip() if name_el is not None else None
        found = list(_geometries(pm))
        if not found:
            rows.append((pi, 0, name, None, [wl.EMPTY], wl.unusable_hash("Placemark", ""), "Placemark"))
        for gi, (el, tag) in enumerate(found):
            geom, why = _shape(el, tag)
            if tag in UNSUPPORTED_TAGS: why = wl.UNSUPPORTED_TYPE
            if geom is not None: rows.append((pi, gi, name, geom, [], wl.geometry_hash_of(geom), tag))
            else: rows.append((pi, gi, name, None, [why], wl.unusable_hash(tag, _raw_text(el)), tag))
    # ids come from geometry only; identical geometry gets -d2, -d3 ... in document order
    seen, out = {}, []
    for ordinal, (pi, gi, name, geom, reasons, ghash, tag) in enumerate(rows):
        base = wl.base_location_id(ghash)
        n = seen[base] = seen.get(base, 0) + 1
        out.append((wl.WorkLocation(
            location_id=base if n == 1 else f"{base}-d{n}", ordinal=ordinal,
            source=wl.Source(file=file_name, input_hash=input_hash, placemark_index=pi, geometry_index=gi, name=name),
            geometry=geom, geometry_hash=ghash, role=wl.WORK, display_label=name, reject_reasons=reasons), tag))
    return out


def _mark_duplicates(locs, max_m):
    """A Point under max_m from an earlier one is a duplicate of it. 'Earlier' is (geometry hash, id) order, so the
    input order never decides which one is kept."""
    kept = []
    pts = [l for l in locs if l.geometry and l.geometry["type"] == wl.POINT]
    for l in sorted(pts, key=lambda l: (l.geometry_hash, l.location_id)):
        lat, lon = l.geometry["coords"]
        keeper = next((k for k in kept if k.geometry_hash == l.geometry_hash
                       or math.dist(enu(*k.geometry["coords"], lat, lon), (0.0, 0.0)) < max_m), None)
        if keeper: l.reject_reasons.append(wl.DUPLICATE_OF + keeper.location_id)
        else: kept.append(l)


def parse_all(source, *, duplicate_distance_m, file_name=None):
    """Read every geometry of any KML (a path or bytes) into WorkLocations, in document order. Nothing is discarded:
    an unusable feature keeps its record with reject_reasons INVALID_GEOMETRY, EMPTY, UNSUPPORTED_TYPE or
    DUPLICATE_OF:<id>. duplicate_distance_m is the config value input.duplicate_distance_m."""
    locs = [l for l, _ in _scan(*_load(source, file_name))]
    _mark_duplicates(locs, duplicate_distance_m)
    return locs


# ---------------------------------------------------------------- legacy adapter (until S3)
def parse_kml(path, max_work_path_m):
    """One work Point and at most one LineString -> ProjectGeometry, built on the same scan as parse_all."""
    raw, root, file_name = _load(path)
    ignored = sum(1 for el in root.iter() if _local(el.tag) in METADATA_TAGS)
    points, lines, unsupported = [], [], []
    for l, tag in _scan(raw, root, file_name):  # duplicates are not marked: this path counts every Point
        if tag == "Polygon" or tag in UNSUPPORTED_TAGS - {"LinearRing"}: unsupported.append(tag)
        elif tag in ("Point", "LineString"):
            if l.reject_reasons: raise InputRejected(["INVALID_COORDINATES"], f"{tag} has invalid coordinates")
            if tag == "Point": points.append(tuple(l.geometry["coords"]))
            else: lines.append([tuple(c) for c in l.geometry["coords"]])
        # a standalone LinearRing, or a Placemark without geometry, was never counted

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
    return {"input_type": "KML", "source_file": file_name,
            "work_reference": {"latitude": r(lat, 7), "longitude": r(lon, 7)},
            "work_path": [{"latitude": r(a, 7), "longitude": r(b, 7)} for a, b in path_pts],
            "input_feature_count": len(points) + len(lines),
            "input_hash": "sha256:" + sha256_hex(raw),
            "non_authoritative_metadata": {"ignored_element_count": ignored}}
