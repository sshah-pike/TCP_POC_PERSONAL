"""SME placement adjustments and proposed objects (revision runs and the assistant preview only).

Movement is ALONG the saved roadway alignment (site_model.road.centerline, local ENU frame at the work reference):
station s -> s', lateral offset preserved (LEFT-positive), coordinates from geometry.offset_point. Never a lat/lon delta.
Rule distances are not changed: a moved sign keeps rule_distance_ft (Table 6B-1 A) and records its actual distance, so
the unchanged validators report VAL-SPACING / GEO-STATION as FAIL (rule CONFLICT) unless the SME confirms an exception.
Proposed objects that are not approved TA-1 catalog devices get object_type SME_PROPOSED_OBJECT, which the unchanged
RuleValidator reports as VAL-PROHIBITED-OBJECTS FAIL: they can never pass as approved objects.
"""
import math

from tcp_planner.contracts import FT, r
from tcp_planner.geometry.local_frame import SiteFrame, offset_point, bearing_deg, signed_lateral

APPROACH_DIRECTION = {"INCREASING_STATION": +1, "DECREASING_STATION": -1}
SME_OBJECT_TYPE = "SME_PROPOSED_OBJECT"


def _place_point(frame, station, lateral, direction):
    (x, y), (tx, ty) = offset_point(frame.centerline, station, lateral)
    lat, lon = frame.latlon(x, y)
    b = bearing_deg(tx * direction, ty * direction) if direction else None
    return x, y, lat, lon, b


def move(obj, adj, frame, issues):
    o = dict(obj); p = dict(o["placement"])
    s_new = float(adj["station_m"])
    if not (0.0 <= s_new <= frame.length):
        issues.append({"code": "PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY", "object": o["object_id"]})
    lateral = float(adj["lateral_m"])
    direction = APPROACH_DIRECTION.get(o.get("approach"), 0)
    x, y, lat, lon, b = _place_point(frame, min(max(s_new, 0.0), frame.length), lateral, direction)
    dist_m = abs(s_new - frame.work_station)
    p.update(station_m=r(s_new, 3), latitude=r(lat, 7), longitude=r(lon, 7), local_enu_m=[r(x, 3), r(y, 3)],
             rule_distance_ft=p.get("rule_distance_ft", p.get("longitudinal_distance_ft")),
             longitudinal_distance_ft=r(dist_m / FT, 3), longitudinal_distance_m=r(dist_m, 3),
             lateral_offset_from_centerline_m=r(abs(lateral), 3), side_of_centerline="LEFT" if lateral > 0 else "RIGHT")
    if b is not None: p.update(approach_bearing_deg=r(b, 2), face_azimuth_deg=r((b + 180.0) % 360.0, 2))
    o["placement"] = p
    o["sme"] = {"change": "MOVED", "label": "SME MOVED", "from_station_m": obj["placement"].get("station_m"),
                "requested": adj.get("requested"), "adjustment_id": adj.get("adjustment_id"),
                "method": "ALONG_ALIGNMENT_CONSTANT_OFFSET" if adj.get("preserve_lateral_offset", True) else "ALONG_ALIGNMENT"}
    return o


def proposed(spec, frame, pack, site, issues):
    """A typed SME-proposed object. Approved catalog signs become SIGN objects; everything else SME_PROPOSED_OBJECT."""
    s = float(spec["station_m"]); lateral = float(spec["lateral_m"])
    if not (0.0 <= s <= frame.length): issues.append({"code": "PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY", "object": spec["object_id"]})
    direction = APPROACH_DIRECTION.get(spec.get("approach"), 0)
    x, y, lat, lon, b = _place_point(frame, min(max(s, 0.0), frame.length), lateral, direction)
    dist_m = abs(s - frame.work_station)
    trace = {"rule_pack_id": pack.id, "rule_pack_version": pack.version, "rule_pack_hash": pack.hash, "ta_id": pack.selected_ta(),
             "rule_id": f"SME_PROPOSED_OBJECT:{spec['object_id']}", "source_section": "SME REVISION (not generated from the rule pack)",
             "source_table": None, "sme_proposed": True}
    sme = {k: spec.get(k) for k in ("approval_class", "category", "purpose", "label", "proposal_id", "validation_coverage_gaps")}
    sme.update(change="PROPOSED", label=f"SME {spec.get('category')} ({spec.get('approval_class')})")
    placement = {"reference": "SME_PROPOSED", "station_m": r(s, 3), "work_station_m": r(frame.work_station, 3),
                 "latitude": r(lat, 7), "longitude": r(lon, 7), "local_enu_m": [r(x, 3), r(y, 3)],
                 "lateral_offset_from_centerline_m": r(abs(lateral), 3), "side_of_centerline": "LEFT" if lateral > 0 else "RIGHT",
                 "longitudinal_distance_ft": r(dist_m / FT, 3), "longitudinal_distance_m": r(dist_m, 3)}
    if b is not None: placement.update(approach_bearing_deg=r(b, 2), face_azimuth_deg=r((b + 180.0) % 360.0, 2))
    if spec.get("end_station_m") is not None:  # zone (taper / buffer / work zone): polyline at the same offset
        e = float(spec["end_station_m"]); a0, a1 = sorted((s, e))
        n = max(2, int(abs(a1 - a0) / 2.0) + 1)
        pts = [offset_point(frame.centerline, min(max(a0 + (a1 - a0) * i / (n - 1), 0.0), frame.length), lateral)[0] for i in range(n)]
        placement["zone"] = [{"latitude": r(q[0], 7), "longitude": r(q[1], 7)} for q in (frame.latlon(*pt) for pt in pts)]
        placement["end_station_m"] = r(e, 3)
        if not (0.0 <= e <= frame.length): issues.append({"code": "PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY", "object": spec["object_id"]})
    if spec.get("approval_class") == "APPROVED_CATALOG_DEVICE" and spec.get("category") == "SIGN":
        code = spec["sign_code"]; sign = pack.sign(code)
        road_type = site["road"]["road_type"]["value"]
        table, a_ft = pack.spacing_value_ft(road_type, "A")
        placement.update(approach=spec.get("approach"), rule_distance_ft=a_ft)
        return {"object_id": spec["object_id"], "object_type": "SIGN", "sign_code": code, "legend": sign["name"],
                "sign_catalog": {k: sign[k] for k in ("category", "shape", "background_color", "legend_color") if k in sign},
                "approach": spec.get("approach"), "dwt_layer": pack.dwt_layer("signs"), "dwt_block": pack.dwt_block(code),
                "placement": placement, "sme": sme,
                "generated_by": dict(trace, source_table=table, table_value_ft=a_ft, table_dimension="A", table_row=road_type)}
    return {"object_id": spec["object_id"], "object_type": SME_OBJECT_TYPE, "sme_category": spec.get("category"),
            "label": spec.get("label"), "approach": spec.get("approach"), "placement": placement, "sme": sme,
            "dwt_layer": None, "dwt_block": None, "generated_by": trace}


def apply(placed, revision, site, config, pack):
    """-> (objects, issues). Order: removals, moves, proposed objects (deterministic)."""
    frame = SiteFrame(site); issues = []
    removed = {x["object_id"] for x in revision.get("removed_objects") or [] if x.get("object_id") != "W1"}
    adj = {a["object_id"]: a for a in revision.get("placement_adjustments") or []}
    out = []
    for o in placed:
        if o["object_id"] in removed: continue
        if o["object_id"] in adj and o["object_type"] != "WORK_LOCATION":
            o = move(o, adj[o["object_id"]], frame, issues)
        out.append(o)
    for spec in sorted(revision.get("proposed_objects") or [], key=lambda s: s["object_id"]):
        if spec["object_id"] in removed: continue
        if any(o["object_id"] == spec["object_id"] for o in out):
            issues.append({"code": "PLACEMENT_NOT_CALCULABLE", "object": spec["object_id"], "detail": "duplicate object id"}); continue
        out.append(proposed(spec, frame, pack, site, issues))
    return out, issues


def lateral_of(site, lat, lon):
    """(station, LEFT-positive lateral) of a saved coordinate on the saved alignment."""
    frame = SiteFrame(site)
    d, s, lateral = signed_lateral(frame.centerline, frame.enu(lat, lon))
    return s, lateral, d
