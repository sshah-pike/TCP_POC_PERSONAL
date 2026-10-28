"""Fuse OSM + AI + operator inputs into the canonical SiteModel.

Rules of fusion (fail closed):
- Every source observation is preserved next to the resolved value.
- A model-read critical field resolves on one of these paths (pipeline_config "agent" / "fusion"):
    AGREEMENT  the field is in agent.agreement_fields, the target OSM way carries the tag EXPLICITLY, the way was
               last edited within agent.agreement_osm_max_age_years, the model value equals the OSM value and the
               model confidence >= agent.agreement_floor. Call-1 answers only (agent); source "AI+OSM_AGREEMENT".
    NORMAL     model confidence >= fusion.min_critical_confidence and no OSM value contradicts it (call-1 answer).
    CROP       the same cutoff for an answer taken from the agent's call 2 (close-view crops); never the agreement path.
    GEOMETRY   work side / encroachment decided by bounded geometry, the model agreeing or silent (see below).
  OSM alone never resolves a field; a missing or implicit OSM tag never counts as agreement.
- Disagreement -> CONFLICT (surfaced, never silently chosen). Missing -> UNRESOLVED. No defaults.
- CROSS_VIEW_MISMATCH: the agent's calls 1 and 2 disagree on a consistency field -> unresolved even if both are confident.

Which statuses each decision depends on:
  road.road_edges              model width (both edges visible) measured in an image at or finer than
                               fusion.width_max_measure_mpp (agent calls report the image) +
                               attribute_confidence.road_edges at the normal cutoff
                               (or AGREEMENT with an explicit OSM width tag); OSM width conflict; cross-view mismatch.
  work.side                    KML/coordinate distance to the OSM centreline > fusion.work_side_geometry_min_distance_m
                               (else UNRESOLVED) + the model side: agrees or UNKNOWN -> RESOLVED; opposite -> CONFLICT.
  work.encroaches_traveled_way model width (any road_edges confidence) and lane count (resolved value, else the model's)
                               -> per-lane width within fusion.lane_width_plausible_m, else UNRESOLVED; outer limit =
                               width/2 + encroachment_tolerance_m + centerline_error_allowance_m; any work point inside
                               -> encroaching (True); all outside -> False only if the model says outside at >= the
                               agreement floor (call 1) / the normal cutoff (call 2).
  work.location                encroaches True -> TRAVELED_WAY; False -> the model's SHOULDER / BEYOND_SHOULDER at the
                               normal cutoff; otherwise follows encroachment.
  work.requires_lane_closure   operator declaration or encroaches (unchanged); alternating traffic follows lane closure.
  work.affects_pedestrian_route work-side sidewalk (AGREEMENT with an explicit sidewalk tag, or the normal cutoff) +
                               crosswalks near the work.
Downstream modules read only the SiteModel.
"""
import datetime

from tcp_planner.contracts import field, r, content_hash, RESOLVED, UNRESOLVED, CONFLICT, LOW_CONFIDENCE
from tcp_planner.geometry.local_frame import signed_lateral, at, bearing_deg, offset_polyline, to_latlon_list, project

CRITICAL_FIELDS = ("road.lane_count", "road.two_way", "road.divided", "road.facility_type", "road.road_type",
                   "road.centerline_status", "road.road_edges", "work.side", "work.encroaches_traveled_way",
                   "work.location", "work.requires_lane_closure", "work.requires_alternating_one_lane_traffic",
                   "work.affects_pedestrian_route")

AGREEMENT_SOURCE = "AI+OSM_AGREEMENT"
CROSS_VIEW_MISMATCH = "CROSS_VIEW_MISMATCH"
NO_POSITION_AFTER_CROP = "NO_POSITION_AFTER_CROP"
PATH_AGREEMENT, PATH_NORMAL, PATH_GEOMETRY, PATH_CROP = "AGREEMENT", "NORMAL", "GEOMETRY", "CROP"
PATH_MEASURED = "MEASURED"  # deterministic cross-section from a close view (src/tcp_planner/site_model/cross_section.py)


def reference_bearing(osm):
    cl = osm["centerline_enu"]; _, s0, _ = signed_lateral(cl, (0.0, 0.0))
    _, (tx, ty) = at(cl, s0)
    return bearing_deg(tx, ty)


def _age_years(timestamp, now_iso):
    if not timestamp: return None
    try:
        t = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        now = datetime.datetime.fromisoformat(now_iso) if now_iso else datetime.datetime.now(datetime.timezone.utc)
        return (now - t).total_seconds() / (365.25 * 86400)
    except (TypeError, ValueError):
        return None


class _Ctx:
    """Per-build fusion context: agent inputs, OSM agreement eligibility and the audit trail."""

    def __init__(self, osm, config, agent):
        self.agent = agent; ag = agent or {}
        self.thr = config["fusion"]["min_critical_confidence"]
        self.floor = config["agent"]["agreement_floor"]
        self.max_age = config["agent"]["agreement_osm_max_age_years"]
        self.fields = config["agent"]["agreement_fields"]
        self.source = ag.get("group_source") or {}
        self.forced = ag.get("forced") or {}
        self.crops = ag.get("crop_for_group") or {}
        self.consistency = {c["group"]: c for c in ag.get("consistency") or []}
        tw = osm.get("target_way") or {}
        self.tw = tw; self.edit_date = tw.get("timestamp")
        self.age = _age_years(self.edit_date, ag.get("now"))
        self.audit = []

    def call(self, group):
        return self.source.get(group, "CALL_1")

    def cutoff(self, group):
        """Model confidence needed where the agreement floor applies to a call-1 answer (geometry-bounded decisions)."""
        return self.thr if self.call(group) == "CALL_2" else self.floor

    def answered_path(self, group):
        return PATH_CROP if self.call(group) == "CALL_2" else PATH_NORMAL

    def agreement(self, field_key, group, tags):
        """Eligibility of the OSM-agreement path for this field (explicit tag, recent edit, call-1 answer)."""
        explicit = {t: self.tw.get("explicit_tags", {}).get(t) for t in tags
                    if t in self.fields.get(field_key, []) and (self.tw.get("tag_is_explicit") or {}).get(t)}
        why = (None if self.agent is not None else "no agent context") or \
              (None if field_key in self.fields else f"{field_key} not in agent.agreement_fields") or \
              (None if explicit else "no explicit OSM tag on the target way") or \
              (None if self.age is not None else "OSM way edit date unknown") or \
              (None if self.age <= self.max_age else f"OSM way last edited {self.age:.1f} years ago") or \
              (None if self.call(group) == "CALL_1" else "call-2 answers never use the agreement path")
        return {"eligible": why is None, "not_eligible_because": why, "field": field_key, "tags": explicit,
                "edit_date": self.edit_date, "age_years": r(self.age, 2), "max_age_years": self.max_age}

    def record(self, name, group, f, path, model_value=None, model_conf=None, agreement=None, **extra):
        entry = {"field": name, "group": group, "decision": f["status"], "value": f["value"],
                 "path": path if f["status"] == RESOLVED else None,
                 "source_call": self.call(group) if (self.agent is not None and group) else None,
                 "model_value": model_value, "model_confidence": r(model_conf, 3),
                 "config": {"min_critical_confidence": self.thr, "agreement_floor": self.floor}}
        if agreement is not None:
            entry["osm"] = {k: agreement[k] for k in ("tags", "edit_date", "age_years", "max_age_years")}
            entry["osm"]["agreement_eligible"] = agreement["eligible"]
            entry["osm"]["not_eligible_because"] = agreement["not_eligible_because"]
        if group in self.crops: entry["crops"] = self.crops[group]
        if group in self.consistency: entry["consistency"] = self.consistency[group]
        if f.get("note"): entry["note"] = f["note"]
        entry.update(extra)
        self.audit.append(entry)

    def mismatch(self, group, f):
        """Cross-view mismatch (agent consistency check) overrides the field: unresolved, both values kept."""
        if group not in self.forced: return f
        c = self.forced[group]
        return field(None, CROSS_VIEW_MISMATCH, None, f["observations"],
                     note=f"call 1 ({c.get('call1')}) and call 2 ({c.get('call2')}) disagree")


def _resolve(name, group, osm_val, osm_conf, osm_detail, ai_avail, ai_val, ai_conf, conflicts, ctx, agreement=None,
             equal=None):
    obs = []
    if osm_val is not None: obs.append({"source": "OSM", "value": osm_val, "confidence": r(osm_conf, 3), "detail": osm_detail})
    if ai_avail: obs.append({"source": "AI", "value": ai_val, "confidence": r(ai_conf, 3)})
    same = equal or (lambda a, b: a == b)
    thr = ctx.thr
    path = None
    if not ai_avail or ai_val is None:
        note = "AI observation missing; OSM alone is not sufficient" if osm_val is not None else "no observation"
        f = field(None, UNRESOLVED, None, obs, note=note)
    elif (agreement and agreement["eligible"] and osm_val is not None and same(osm_val, ai_val)
          and ai_conf is not None and ai_conf >= ctx.floor):
        f = field(ai_val, RESOLVED, max(ai_conf, osm_conf or 0), obs, source=AGREEMENT_SOURCE,
                  note=f"model agrees with explicit OSM tag at confidence >= {ctx.floor}"); path = PATH_AGREEMENT
    elif ai_conf is None or ai_conf < thr:
        f = field(None, LOW_CONFIDENCE, ai_conf, obs, note=f"AI confidence below {thr}")
    elif osm_val is not None and not same(osm_val, ai_val):
        conflicts.append({"field": name, "osm": osm_val, "ai": ai_val, "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
        f = field(None, CONFLICT, None, obs, note="OSM and AI disagree")
    else:
        conf = max(ai_conf, osm_conf or 0) if osm_val is not None else ai_conf
        f = field(ai_val, RESOLVED, conf, obs); path = ctx.answered_path(group)
    f = ctx.mismatch(group, f)
    ctx.record(name, group, f, path, ai_val, ai_conf, agreement)
    return f


def _ai_feature_to_site(item, kind, ai_mpp, ai_px, centerline):
    out = {"source": "AI", "kind": kind, "description": item["description"][:200], "side": item["side"],
           "confidence": r(item["confidence"], 3), "station_m": None}
    if item["image_x"] is not None and item["image_y"] is not None:
        x = (item["image_x"] - ai_px / 2) * ai_mpp; y = (ai_px / 2 - item["image_y"]) * ai_mpp
        d, s, lat = signed_lateral(centerline, (x, y))
        out.update(station_m=r(s, 2), distance_from_centerline_m=r(d, 2))
    return out


def build_site_model(project_geometry, osm, ai_result, ai_error, map_meta, operator, config, ai_error_text=None,
                     agent=None):
    """agent: inputs from src/tcp_planner/ai/vision_agent.py (which call answers each field group, cross-view mismatches, crops,
    consistency results, extras, escalations). None = no agent (no agreement path; every answer is a call-1 answer)."""
    ctx = _Ctx(osm, config, agent)
    thr = ctx.thr; fz = config["fusion"]
    osm_conf = fz["osm_tag_confidence"]; osm_implicit = fz["osm_implicit_confidence"]
    ai = ai_result["observation"] if ai_result else None
    ai_avail = ai is not None
    ac = ai["attribute_confidence"] if ai_avail else {}
    conflicts = []

    cl = osm["centerline_enu"]
    # measured cross-sections (agent): the OSM centreline is shifted onto the measured road centre before anything
    # else is derived from it (work side, encroachment, edges, sign placement and validation all use this frame)
    xs = (agent or {}).get("cross_section") or {}
    xs_ok = [m for m in xs.get("measurements") or [] if m.get("status") == "OK"]
    wp_m = next((m for m in xs_ok if m["role"] == "work_point"), None)
    if xs_ok:
        from .cross_section import corrected_centerline
        cl = corrected_centerline(cl, [(m["station_m"], m["centre_offset_m"]) for m in xs_ok],
                                  config["cross_section"]["centerline_resample_m"])
    dist, s0, lateral = signed_lateral(cl, (0.0, 0.0))
    ai_px = config["imagery"]["wide_image_px"]
    ai_mpp = map_meta["ground_extent_m"]["width"] / ai_px

    # ---------- road ----------
    lane_count = _resolve("road.lane_count", "lane_count", osm["lanes_tag"], osm_conf, "lanes tag",
                          ai_avail, ai and ai["lane_count_total"], ac.get("lane_count_total"), conflicts, ctx,
                          ctx.agreement("lane_count", "lane_count", ["lanes"]) if osm["lanes_tag"] is not None else None)

    ow = osm["oneway_tag"]
    if ow in ("yes", "true", "1", "-1", "reversible", "alternating"): osm_two_way, c, det = False, osm_conf, f"oneway={ow}"
    elif ow == "no": osm_two_way, c, det = True, osm_conf, "oneway=no"
    else: osm_two_way, c, det = True, osm_implicit, "implicit (no oneway tag)"
    two_way = _resolve("road.two_way", "two_way", osm_two_way, c, det, ai_avail, ai and ai["two_way_visible"],
                       ac.get("two_way_visible"), conflicts, ctx, ctx.agreement("two_way", "two_way", ["oneway"]))

    if osm["dual_carriageway_tag"] == "yes": osm_div, det = True, "dual_carriageway=yes"
    elif osm["divider_tag"] and osm["divider_tag"] != "no": osm_div, det = True, f"divider={osm['divider_tag']}"
    elif osm["divider_tag"] == "no": osm_div, det = False, "divider=no"
    else: osm_div, det = None, None
    divided = _resolve("road.divided", "divided", osm_div, osm_conf, det, ai_avail, ai and ai["divided_road_visible"],
                       ac.get("divided_road"), conflicts, ctx,
                       ctx.agreement("divided", "divided", ["divider", "dual_carriageway"]) if osm_div is not None else None)

    fac_obs = [{"source": "OSM", "value": osm["facility_type"], "detail": f"highway={osm['highway']}"}]
    if ai_avail:
        fac_obs.append({"source": "AI", "ramps_seen": len(ai["features"]["ramps"]),
                        "roundabouts_seen": len(ai["features"]["roundabouts"])})
    if osm["facility_type"] and ai_avail:
        facility = field(osm["facility_type"], RESOLVED, osm_conf, fac_obs,
                         note="road class from OSM; ramps/roundabouts checked from both sources in eligibility")
    else:
        facility = field(None, UNRESOLVED, None, fac_obs, note="needs OSM class and an AI observation")

    rt = operator.get("road_type")
    road_type = field(rt, RESOLVED if rt else UNRESOLVED, 1.0 if rt else None,
                      [{"source": "OPERATOR", "value": rt}] if rt else [], source="OPERATOR" if rt else None,
                      note=None if rt else "Table 6B-1 road type must be confirmed (--road-type); it is never inferred")

    spd = operator.get("speed_mph")
    speed = {"value": spd if spd else osm["maxspeed_mph"],
             "source": "OPERATOR" if spd else ("OSM" if osm["maxspeed_mph"] else None),
             "status": RESOLVED if (spd or osm["maxspeed_mph"]) else UNRESOLVED,
             "required_by_selected_ta": False,
             "note": "informational; TA-1 spacing in the approved pack is keyed by road type, not speed"}

    max_d = fz.get("max_work_to_centerline_m")
    cl_status = RESOLVED if (len(cl) >= 2 and (max_d is None or dist <= max_d)) else UNRESOLVED
    cl_note = None
    if xs.get("enabled") and config["cross_section"]["require_verified_centerline"] and wp_m is None:
        cl_status = UNRESOLVED  # an unchecked OSM centreline can be metres off: signs could land on the pavement
        cl_note = "road centre not verified at the work point (cross-section measurement inconclusive or not made)"
    if osm["chain_tag_variation"]:
        conflicts.append({"field": "road.centerline", "osm": "attributes vary along road: " +
                          ",".join(osm["chain_tag_variation"]), "ai": None, "resolution": "NOT_RESOLVED_AUTOMATICALLY"})

    # traveled-way width -> road edges (kept at the normal cutoff; AGREEMENT only with an explicit OSM width tag)
    edges_obs = []; width = None; status = UNRESOLVED; note = None; edges_path = None
    ai_w = None
    re_conf = ac.get("road_edges")
    if ai_avail:
        e = ai["road_edges"]
        if e["traveled_way_width_px"] is not None and e["left_visible"] and e["right_visible"]:
            ai_w = e["traveled_way_width_px"] * ai_mpp
        edges_obs.append({"source": "AI", "left_visible": e["left_visible"], "right_visible": e["right_visible"],
                          "width_m": r(ai_w, 3), "confidence": r(re_conf, 3)})
    if osm["width_m"] is not None: edges_obs.append({"source": "OSM", "width_m": osm["width_m"], "detail": "width tag"})
    w_tol = fz["road_width_conflict_tolerance_m"]
    w_agree = ctx.agreement("road_width", "road_edges", ["width"]) if osm["width_m"] is not None else None
    wm = (agent or {}).get("width_measure") or {}
    coarse = wm.get("mpp") is not None and wm["mpp"] > fz["width_max_measure_mpp"]
    if wp_m is not None:
        status = RESOLVED; width = wp_m["width_m"]; edges_path = PATH_MEASURED
        edges_obs.append({"source": "MEASURED", "width_m": wp_m["width_m"], "metres_per_pixel": wp_m["metres_per_pixel"],
                          "centre_source": wp_m["centre_source"], "spread_m": wp_m["spread_m"]})
        note = (f"edge line to edge line measured in a {wp_m['metres_per_pixel']:.3f} m/px close view "
                f"({len([s for s in wp_m['sections'] if 'width_m' in s])} sections, spread {wp_m['spread_m']} m); "
                f"model width {r(ai_w, 2)} m")
    elif ai_w is None: note = "edges not visible / width not measured"
    elif coarse:
        note = (f"width measured in {wm.get('image')} at {wm['mpp']:.3f} m/px; a close view at or finer than "
                f"{fz['width_max_measure_mpp']} m/px is required (fusion.width_max_measure_mpp)")
    elif (w_agree and w_agree["eligible"] and abs(osm["width_m"] - ai_w) <= w_tol and re_conf is not None
          and re_conf >= ctx.floor):
        status = RESOLVED; width = ai_w; edges_path = PATH_AGREEMENT
        note = f"model width agrees with explicit OSM width tag within {w_tol} m at confidence >= {ctx.floor}"
    elif (re_conf or 0) < thr: status = LOW_CONFIDENCE; note = f"AI confidence below {thr}"
    elif osm["width_m"] is not None and abs(osm["width_m"] - ai_w) > w_tol:
        status = CONFLICT
        conflicts.append({"field": "road.road_edges", "osm": osm["width_m"], "ai": r(ai_w, 2),
                          "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
    else: status = RESOLVED; width = ai_w; edges_path = ctx.answered_path("road_edges")
    if "road_edges" in ctx.forced and wp_m is None:
        c = ctx.forced["road_edges"]
        status, width, edges_path = CROSS_VIEW_MISMATCH, None, None
        note = f"call 1 ({c.get('call1')} m) and call 2 ({c.get('call2')} m) disagree"
    half = width / 2 if width else None
    road_edges = {"status": status, "observations": edges_obs, "note": note,
                  "traveled_way_width_m": r(width, 3), "left_offset_m": r(half, 3), "right_offset_m": r(half, 3),
                  "model": "symmetric about OSM centerline"}
    if edges_path == PATH_AGREEMENT: road_edges["source"] = AGREEMENT_SOURCE
    ctx.record("road.road_edges", "road_edges", {"status": status, "value": r(width, 3), "note": note}, edges_path,
               r(ai_w, 3), re_conf, w_agree)
    lat0 = project_geometry["work_reference"]["latitude"]; lon0 = project_geometry["work_reference"]["longitude"]
    if half:
        road_edges["left"] = to_latlon_list(offset_polyline(cl, half), lat0, lon0)
        road_edges["right"] = to_latlon_list(offset_polyline(cl, -half), lat0, lon0)

    # ---------- work ----------
    # side: bounded geometry decides; the model may agree, be silent, or block it by disagreeing
    side_min = fz["work_side_geometry_min_distance_m"]
    geo_side = None if dist <= side_min else ("LEFT" if lateral > 0 else "RIGHT")
    ai_side = ai["work_reference"]["side"] if ai_avail else None
    side_conf = ac.get("work_side")
    side_obs = []
    if geo_side: side_obs.append({"source": "GEOMETRY", "value": geo_side, "confidence": 1.0,
                                  "detail": f"KML/coordinate vs OSM centerline, {dist:.2f} m > {side_min} m"})
    if ai_avail: side_obs.append({"source": "AI", "value": None if ai_side in (None, "UNKNOWN") else ai_side,
                                  "confidence": r(side_conf, 3)})
    side_path = None; side_res = True
    if geo_side is None:
        side = field(None, UNRESOLVED, None, side_obs,
                     note=f"work reference within {side_min} m of the OSM centerline - side cannot be decided")
        side_res = False
    elif not ai_avail:
        side = field(None, UNRESOLVED, None, side_obs, note="AI observation missing")
    elif ai_side not in (None, "UNKNOWN") and ai_side != geo_side:
        conflicts.append({"field": "work.side", "osm": geo_side, "ai": ai_side, "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
        side = field(None, CONFLICT, None, side_obs, note="geometry and AI disagree")
    elif ai_side == geo_side and side_conf is not None and side_conf >= ctx.cutoff("work_side"):
        side = field(geo_side, RESOLVED, 1.0, side_obs, source="AI+GEOMETRY")
        side_path = ctx.answered_path("work_side") if side_conf >= thr else PATH_GEOMETRY
    else:
        side = field(geo_side, RESOLVED, 1.0, side_obs, source="GEOMETRY",
                     note="decided by geometry (model UNKNOWN or below the agreement floor, not contradicting)")
        side_path = PATH_GEOMETRY
    side = ctx.mismatch("work_side", side)
    ctx.record("work.side", "work_side", side, side_path, ai_side, side_conf, image_resolvable=side_res)

    # encroachment from bounded geometry, independent of road_edges confidence
    path_pts = [(0.0, 0.0)]
    if project_geometry["work_path"]:
        from tcp_planner.geometry.local_frame import enu
        path_pts += [enu(p["latitude"], p["longitude"], lat0, lon0) for p in project_geometry["work_path"]]
    lo, hi = fz["lane_width_plausible_m"]
    enc_w = wp_m["width_m"] if wp_m else (None if "road_edges" in ctx.forced else ai_w)
    lanes = lane_count["value"] if lane_count["status"] == RESOLVED else (ai and ai["lane_count_total"])
    per_lane = enc_w / lanes if (enc_w and lanes) else None
    plausible = per_lane is not None and lo <= per_lane <= hi
    limit = enc_w / 2 + fz["encroachment_tolerance_m"] + fz["centerline_error_allowance_m"] if plausible else None
    geo_outside = None
    if limit is not None:
        lats = [signed_lateral(cl, p)[2] for p in path_pts]
        geo_outside = all(abs(v) > limit for v in lats) and all((v > 0) == (lateral > 0) for v in lats)
    ai_out = ai["work_reference"]["appears_outside_traveled_way"] if ai_avail else None
    out_conf = ac.get("outside_traveled_way")
    enc_obs = [{"source": "GEOMETRY", "value": None if geo_outside is None else (not geo_outside),
                "detail": "work point/path vs bounded traveled-way limit", "outer_limit_m": r(limit, 3),
                "distance_to_centerline_m": r(dist, 3), "width_m": r(enc_w, 3), "per_lane_width_m": r(per_lane, 3)}]
    if ai_avail: enc_obs.append({"source": "AI", "value": None if ai_out is None else (not ai_out),
                                 "confidence": r(out_conf, 3)})
    enc_path = None
    if geo_outside is False: encroach = field(True, RESOLVED, 1.0, enc_obs); enc_path = PATH_GEOMETRY
    elif geo_outside is None:
        why = "width missing" if enc_w is None else "lane count missing" if not lanes else \
            f"implausible width ({per_lane:.2f} m per lane outside {lo}-{hi} m)"
        encroach = field(None, UNRESOLVED, None, enc_obs, note=f"traveled-way limit unknown: {why}")
    elif not ai_avail or ai_out is None: encroach = field(None, UNRESOLVED, None, enc_obs)
    elif (out_conf or 0) < ctx.cutoff("work_location"):
        encroach = field(None, LOW_CONFIDENCE, out_conf, enc_obs, note=f"AI confidence below {ctx.cutoff('work_location')}")
    elif ai_out is False:
        conflicts.append({"field": "work.encroaches_traveled_way", "osm": "geometry: outside", "ai": "inside",
                          "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
        encroach = field(None, CONFLICT, None, enc_obs)
    else:
        encroach = field(False, RESOLVED, out_conf, enc_obs)
        enc_path = ctx.answered_path("work_location") if out_conf >= thr else PATH_GEOMETRY
    if encroach["value"] is not True: encroach = ctx.mismatch("work_location", encroach)
    if encroach["status"] != RESOLVED: enc_path = None
    ctx.record("work.encroaches_traveled_way", "work_location", encroach, enc_path, ai_out, out_conf,
               outer_limit_m=r(limit, 3), distance_to_centerline_m=r(dist, 3),
               config_geometry={k: fz[k] for k in ("lane_width_plausible_m", "encroachment_tolerance_m",
                                                   "centerline_error_allowance_m")})

    rel = ai["work_reference"]["relative_position"] if ai_avail else None
    loc_obs = [{"source": "AI", "value": rel, "confidence": r(out_conf, 3)}] if ai_avail else []
    loc_path = None
    if encroach["value"] is True: location = field("TRAVELED_WAY", RESOLVED, encroach["confidence"], loc_obs); loc_path = enc_path
    elif encroach["value"] is False:
        if rel in ("BEYOND_SHOULDER", "SHOULDER") and (out_conf or 0) >= thr:
            location = field(rel, RESOLVED, out_conf, loc_obs); loc_path = ctx.answered_path("work_location")
        elif rel in ("BEYOND_SHOULDER", "SHOULDER"):
            location = field(None, LOW_CONFIDENCE, out_conf, loc_obs, note=f"AI confidence below {thr}")
        elif rel == "TRAVELED_WAY":
            conflicts.append({"field": "work.location", "osm": "geometry: outside", "ai": rel,
                              "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
            location = field(None, CONFLICT, None, loc_obs)
        else: location = field(None, UNRESOLVED, None, loc_obs)
    else: location = field(None, encroach["status"], None, loc_obs)
    if location["value"] != "TRAVELED_WAY": location = ctx.mismatch("work_location", location)
    ctx.record("work.location", "work_location", location, loc_path, rel, out_conf)

    op_closure = bool(operator.get("requires_lane_closure"))
    cl_obs = [{"source": "OPERATOR", "value": op_closure}, {"source": "DERIVED", "from": "work.encroaches_traveled_way",
                                                             "value": encroach["value"]}]
    if op_closure or encroach["value"] is True: closure = field(True, RESOLVED, 1.0, cl_obs)
    elif encroach["value"] is False: closure = field(False, RESOLVED, encroach["confidence"], cl_obs)
    else: closure = field(None, UNRESOLVED, None, cl_obs)
    alt_obs = [{"source": "DERIVED", "from": "work.requires_lane_closure", "value": closure["value"]}]
    alternating = field(closure["value"], closure["status"], closure["confidence"], alt_obs,
                        note="closing a lane of a two-lane two-way road requires alternating one-lane operation")
    for name, f in (("work.requires_lane_closure", closure), ("work.requires_alternating_one_lane_traffic", alternating)):
        ctx.record(name, None, f, ("OPERATOR" if op_closure else "DERIVED") if f["status"] == RESOLVED else None,
                   derived_from="operator declaration / work.encroaches_traveled_way")

    # pedestrian impact (work-side sidewalk or nearby crosswalk)
    radius = fz["pedestrian_conflict_radius_m"]
    ai_feats = {}
    if ai_avail:
        for kind, items in ai["features"].items():
            ai_feats[kind] = [_ai_feature_to_site(i, kind, ai_mpp, ai_px, cl) for i in items]
    osm_x = [f for f in osm["features"]["crosswalks"] if abs(f["station_m"] - s0) <= radius]
    ai_x = [f for f in ai_feats.get("crosswalks", []) if f["station_m"] is None or abs(f["station_m"] - s0) <= radius]
    sk = geo_side.lower() if geo_side else None
    osm_sw = osm["sidewalks"][sk] if sk else None
    ai_sw = ai["sidewalks"][f"{sk}_present"] if (ai_avail and sk) else None
    ped_conf = ac.get("pedestrian_impact")
    ped_obs = [{"source": "OSM", "work_side_sidewalk": osm_sw, "crosswalks_near_work": len(osm_x)}]
    if ai_avail: ped_obs.append({"source": "AI", "work_side_sidewalk": ai_sw, "crosswalks_near_work": len(ai_x),
                                 "confidence": r(ped_conf, 3)})
    sw_agree = ctx.agreement("sidewalks", "pedestrian", ["sidewalk", f"sidewalk:{sk}"]) if sk else None
    ped_path = None
    if not ai_avail or sk is None or ai_sw is None: ped = field(None, UNRESOLVED, None, ped_obs)
    elif (sw_agree and sw_agree["eligible"] and osm_sw is not None and osm_sw == ai_sw and ped_conf is not None
          and ped_conf >= ctx.floor):
        ped = field(bool(ai_sw or osm_x or ai_x), RESOLVED, ped_conf, ped_obs, source=AGREEMENT_SOURCE,
                    note=f"work-side sidewalk agrees with explicit OSM tag at confidence >= {ctx.floor}")
        ped_path = PATH_AGREEMENT
    elif (ped_conf or 0) < thr: ped = field(None, LOW_CONFIDENCE, ped_conf, ped_obs)
    elif osm_sw is not None and osm_sw != ai_sw:
        conflicts.append({"field": "work.affects_pedestrian_route", "osm": osm_sw, "ai": ai_sw,
                          "resolution": "NOT_RESOLVED_AUTOMATICALLY"})
        ped = field(None, CONFLICT, None, ped_obs)
    else: ped = field(bool(ai_sw or osm_x or ai_x), RESOLVED, ped_conf, ped_obs); ped_path = ctx.answered_path("pedestrian")
    ctx.record("work.affects_pedestrian_route", "pedestrian", ped, ped_path, ai_sw, ped_conf, sw_agree)

    # ---------- features (both sources, each tagged) ----------
    feats = {k: list(osm["features"].get(k, [])) + ai_feats.get(k, [])
             for k in ("intersections", "driveways", "crosswalks", "roundabouts", "ramps")}
    feats["obstructions"] = ai_feats.get("obstructions", [])
    feats["sidewalks"] = [{"source": "OSM", "side": s.upper(), "present": osm["sidewalks"][s]} for s in ("left", "right")]
    if ai_avail:
        feats["sidewalks"] += [{"source": "AI", "side": s.upper(), "present": ai["sidewalks"][f"{s}_present"]}
                               for s in ("left", "right")]
    unplaced = [{"kind": k, "description": f["description"]} for k, items in ai_feats.items() for f in items
                if f["station_m"] is None]
    escalations = list((agent or {}).get("escalations") or [])
    if unplaced and (agent or {}).get("call2_ran"):  # still no position after the crops: strict treatment stays
        escalations.append({"field": "features", "status": NO_POSITION_AFTER_CROP, "reason_code": NO_POSITION_AFTER_CROP,
                            "detail": unplaced})
    if ai_avail:
        ctx.record("features", "features",
                   {"status": RESOLVED if not unplaced else UNRESOLVED, "value": {k: len(v) for k, v in ai_feats.items()}},
                   ctx.answered_path("features") if not unplaced else None, None, ac.get("intersection_conflict"),
                   unplaced_features=unplaced,
                   note="intersection conflict itself is decided in eligibility (intersection_analysis)")

    sm = {
        "site_model_id": None, "version": 1,
        "project_geometry": project_geometry,
        "road": {
            "name": osm["name"] or "", "osm_way_ids": osm["target_way_ids"],
            "facility_type": facility, "lane_count": lane_count, "two_way": two_way,
            "traffic_direction": {"value": None if two_way["value"] is None else ("TWO_WAY" if two_way["value"] else "ONE_WAY"),
                                  "status": two_way["status"]},
            "divided": divided, "road_type": road_type, "speed_mph": speed,
            "centerline": to_latlon_list(cl, lat0, lon0), "centerline_status": cl_status,
            "centerline_length_m": osm["centerline_length_m"], "road_edges": road_edges,
            "centerline_correction": {"applied": bool(xs_ok), "note": cl_note,
                                      "measured": [{k: m.get(k) for k in ("role", "station_m", "status", "width_m",
                                                                          "centre_offset_m", "centre_source", "reason")}
                                                   for m in xs.get("measurements") or []]},
        },
        "work": {
            "reference_point": project_geometry["work_reference"], "reference_station_m": r(s0, 3),
            "distance_to_centerline_m": r(dist, 3), "lateral_offset_from_centerline_m": r(abs(lateral), 3),
            "side": side, "location": location, "encroaches_traveled_way": encroach,
            "requires_lane_closure": closure, "requires_alternating_one_lane_traffic": alternating,
            "affects_pedestrian_route": ped,
            "ta1_option_facts": dict(sorted((operator.get("options") or {}).items())),
        },
        "features": feats,
        "feature_confidence": {"intersection_conflict": r(ac.get("intersection_conflict"), 3),
                               "pedestrian_impact": r(ac.get("pedestrian_impact"), 3)},
        "imagery": {"metadata": map_meta, "quality": ai["image_quality"] if ai_avail else None,
                    "ai_image_px": ai_px, "ai_metres_per_pixel": r(ai_mpp, 6),
                    "reference_bearing_deg": r(reference_bearing(osm), 2)},
        "evidence": {
            "osm": {k: v for k, v in osm.items() if k != "centerline_enu"},
            "ai": {"available": ai_avail, "provider": (ai_result or {}).get("provider"),
                   "model": (ai_result or {}).get("model"), "error_code": ai_error,
                   "observation": ai},
        },
        "critical_conflicts": conflicts,
        "extras": list((agent or {}).get("extras") or []),
        "audit": ctx.audit,
        "escalations": escalations,
    }
    if ai_error_text:  # the API's own error text (key-like strings removed), kept for the engineer
        sm["evidence"]["ai"]["error_message"] = ai_error_text
    if agent is not None:
        sm["evidence"]["ai"]["agent"] = {k: agent.get(k) for k in ("calls", "crops", "crops_dropped", "consistency",
                                                                    "checks", "group_source", "unresolved_after_call1")}
    statuses = {"road.lane_count": lane_count["status"], "road.two_way": two_way["status"],
                "road.divided": divided["status"], "road.facility_type": facility["status"],
                "road.road_type": road_type["status"], "road.centerline_status": cl_status,
                "road.road_edges": road_edges["status"], "work.side": side["status"],
                "work.encroaches_traveled_way": encroach["status"], "work.location": location["status"],
                "work.requires_lane_closure": closure["status"],
                "work.requires_alternating_one_lane_traffic": alternating["status"],
                "work.affects_pedestrian_route": ped["status"]}
    sm["critical_field_status"] = statuses
    sm["eligibility_inputs_complete"] = all(v == RESOLVED for v in statuses.values()) and not conflicts and not escalations
    sm["site_model_id"] = "SITE-" + content_hash(sm, drop={"site_model_id"})[:16].upper()
    return sm
