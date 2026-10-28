"""Deterministic placement geometry for existing devices (no AI): along-alignment movement, spatial relationships,
candidate positions, evaluation and staging. Pass/fail rule results come only from the unchanged validators."""
import functools, json, math, os

from tcp_planner.geometry.local_frame import SiteFrame, offset_point, enu, cum
from tcp_planner.contracts import FT, r
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.tools import Tool
from ..flags import CONFIG_DIR
from . import decisions as D, preview, proposals, run_context

DIRECTION = {"INCREASING_STATION": +1, "DECREASING_STATION": -1}   # direction of travel along increasing station
UNITS = {"FT": FT, "M": 1.0}
CONFLICT_KINDS = ("intersections", "driveways", "crosswalks", "roundabouts", "ramps")  # as the GeometryValidator
_C = {}


def register(c):
    _C["c"] = c
    for t in (Tool("calculate_device_position", lambda tctx, **k: calculate(**k)),
              Tool("check_spatial_conflicts", lambda tctx, **k: {"conflicts": spatial(**k)}),
              Tool("calculate_candidate_positions", lambda tctx, **k: {"candidates": candidates(**k)}),
              Tool("evaluate_rule_impact", lambda tctx, **k: _rule_impact(**k)),
              Tool("check_artifact_coverage", lambda tctx, **k: coverage(**k)),
              Tool("stage_placement", _stage, permission="review:decide", mutates=True)):
        c.tools.register(t)


def c():
    return _C["c"]


@functools.lru_cache(maxsize=1)
def _gcfg_cached(mtime):
    with open(os.path.join(CONFIG_DIR, "review_geometry_config.json"), encoding="utf-8") as f: return json.load(f)


def gcfg():
    return _gcfg_cached(os.path.getmtime(os.path.join(CONFIG_DIR, "review_geometry_config.json")))


# ---------------------------------------------------------------- context
def proposal_state(ctx, cid):
    """Effective site model + plan of the CURRENT proposal (staged decisions and placements) - the base for new moves."""
    doc, _ = D.effective(ctx, cid)
    extra = proposals.revision_extra(ctx, cid)
    p = preview.compute(ctx, doc, extra)
    return p["_new_site"], p["_new_derived"]["plan"], p, extra


def _obj(plan, oid):
    """Existing object by reference: exact, then case-insensitive / known ID format (core/entity_resolution.py)."""
    from ..core.entity_resolution import resolve, AMBIGUOUS
    objs = (plan or {}).get("objects", []); ids = [x["object_id"] for x in objs]
    r = resolve(oid, ids)
    if r["resolution_method"] == AMBIGUOUS:
        raise AssistantError("ENTITY_AMBIGUOUS", f"{oid!r} matches more than one object: {', '.join(r['candidates'])}.",
                             409, details={"candidates": r["candidates"], "resolution": r})
    o = next((x for x in objs if x["object_id"] == r["resolved_entity_id"]), None)
    if o is None:
        raise AssistantError("ENTITY_NOT_FOUND", f"{oid} does not exist in the current plan. Existing objects: {', '.join(ids)}.",
                             404, details={"existing_objects": ids, "requested": oid})
    return o


# ---------------------------------------------------------------- coverage
def coverage(site, points):
    """points: [(station, lateral)] -> verdicts against the analysed alignment and the analysed image extent."""
    frame = SiteFrame(site); meta = site["imagery"]["metadata"]
    cx, cy = enu(meta["center"]["latitude"], meta["center"]["longitude"], frame.lat0, frame.lon0)
    hx, hy = meta["ground_extent_m"]["width"] / 2, meta["ground_extent_m"]["height"] / 2
    out = []
    for s, lat in points:
        on_align = 0.0 <= s <= frame.length
        (x, y), _ = offset_point(frame.centerline, min(max(s, 0.0), frame.length), lat)
        in_img = abs(x - cx) <= hx and abs(y - cy) <= hy
        out.append({"station_m": r(s, 3), "within_analysed_alignment": on_align, "within_analysed_image": in_img,
                    "covered": on_align and in_img})
    return {"points": out, "covered": all(p["covered"] for p in out), "azure_maps_required": False,
            "reason": None if all(p["covered"] for p in out) else "outside saved evidence coverage; new imagery would be "
                      "required (disabled by SME_ACTION_POLICY: request_new_imagery / proceed_outside_evidence_coverage)",
            "note": "Local crop improves review focus but does not add image detail."}


# ---------------------------------------------------------------- movement
def calculate(site, plan, object_id, direction=None, distance=None, unit="FT", preserve_lateral_offset=True, station_m=None):
    o = _obj(plan, object_id)
    if o["object_type"] == "WORK_LOCATION":
        raise AssistantError("OBJECT_NOT_MOVABLE", "W1 is the work location from the project input; it cannot be moved here.", 400)
    if site["road"]["centerline_status"] != "RESOLVED" or not site["road"]["road_edges"].get("left_offset_m"):
        raise AssistantError("GEOMETRY_UNAVAILABLE", "No usable roadway alignment/edges; the position cannot be calculated.", 409, False)
    frame = SiteFrame(site); p = o["placement"]
    cur_xy = frame.enu(p["latitude"], p["longitude"])
    from tcp_planner.geometry.local_frame import signed_lateral
    d_snap, s_cur, lat_cur = signed_lateral(frame.centerline, cur_xy)
    trav = DIRECTION.get(o.get("approach"), 0)
    if station_m is not None:
        s_new = float(station_m); req = {"operation": "SET_DEVICE_STATION", "station_m": s_new}
    else:
        if direction not in ("UPSTREAM", "DOWNSTREAM") or unit not in UNITS:
            raise AssistantError("BAD_REQUEST", "direction must be UPSTREAM/DOWNSTREAM and unit FT/M.")
        if not isinstance(distance, (int, float)) or isinstance(distance, bool) or not math.isfinite(distance) or distance <= 0:
            raise AssistantError("BAD_REQUEST", "distance must be a positive number.")
        if not trav: raise AssistantError("DIRECTION_UNDEFINED", f"{object_id} has no approach; use a station instead.", 400)
        dm = distance * UNITS[unit]
        if dm > gcfg()["max_move_m"]: raise AssistantError("BAD_REQUEST", f"Movement above {gcfg()['max_move_m']} m is not supported.")
        # upstream = against the direction of travel of this approach
        s_new = s_cur + (-trav if direction == "UPSTREAM" else trav) * dm
        req = {"operation": "MOVE_DEVICE", "device_id": object_id, "direction": direction, "distance": distance, "unit": unit,
               "distance_m": r(dm, 3), "preserve_lateral_offset": bool(preserve_lateral_offset)}
    lat_new = lat_cur if preserve_lateral_offset else lat_cur  # standard roadside offset is constant along this alignment
    (x1, y1), _ = offset_point(frame.centerline, min(max(s_new, 0.0), frame.length), lat_new)
    la1, lo1 = frame.latlon(x1, y1)
    step = gcfg()["path_sample_step_m"]; n = max(2, int(abs(s_new - s_cur) / step) + 1)
    path = []
    for i in range(n):
        s = s_cur + (s_new - s_cur) * i / (n - 1)
        (px, py), _ = offset_point(frame.centerline, min(max(s, 0.0), frame.length), lat_new)
        path.append(list(frame.latlon(px, py)))
    corr = site["road"].get("centerline_correction") or {}
    cfg = run_context.config()
    from ..core.entity_resolution import resolve
    res = resolve(object_id, [x["object_id"] for x in plan["objects"]])
    if "device_id" in req: req["device_id"] = o["object_id"]
    return {"object_id": o["object_id"], "approach": o.get("approach"), "requested": req, "reference": res,
            "current": {"latitude": p["latitude"], "longitude": p["longitude"], "station_m": r(s_cur, 3),
                        "offset_m": r(lat_cur, 3), "side": "LEFT" if lat_cur > 0 else "RIGHT",
                        "recorded_station_m": p.get("station_m"), "snap_distance_m": r(abs(d_snap - abs(lat_cur)), 3)},
            "proposed": {"latitude": r(la1, 7), "longitude": r(lo1, 7), "station_m": r(s_new, 3), "offset_m": r(lat_new, 3),
                         "side": "LEFT" if lat_new > 0 else "RIGHT"},
            "station_change_m": r(s_new - s_cur, 3), "actual_along_alignment_m": r(abs(s_new - s_cur), 3),
            "actual_along_alignment_ft": r(abs(s_new - s_cur) / FT, 1),
            "straight_line_m": r(math.dist(cur_xy, (x1, y1)), 3),
            "path_length_at_offset_m": r(sum(math.dist(frame.enu(*a), frame.enu(*b)) for a, b in zip(path, path[1:])), 3),
            "distance_basis": "requested distance is applied to centerline stationing; the device path at a constant offset "
                              "is longer/shorter on curves (path_length_at_offset_m)",
            "lateral_offset_preserved": bool(preserve_lateral_offset), "lateral_offset_change_m": r(lat_new - lat_cur, 3),
            "method": "Along the saved roadway alignment (cross-section-corrected OSM centerline) in the local tangent plane at the "
                      "work reference; constant lateral offset; never a latitude/longitude delta",
            "movement_path": path,
            "accuracy": {"centerline_source": "OSM+MEASURED" if corr.get("applied") else "OSM",
                         "centerline_correction_applied": bool(corr.get("applied")),
                         "declared_alignment_uncertainty_m": cfg["fusion"]["centerline_error_allowance_m"],
                         "image_metres_per_pixel": site["imagery"]["metadata"]["metres_per_pixel"],
                         "frame": "LOCAL_TANGENT_PLANE_AT_WORK_REFERENCE"},
            "limitations": ["feature positions are station points with approximate extents (POC implementation geometry)",
                            "alignment beyond the analysed length is not extrapolated"]}


# ---------------------------------------------------------------- spatial relationships
def _features(site):
    for kind in CONFLICT_KINDS + ("obstructions",):
        for f in site["features"].get(kind, []):
            yield kind, f


def spatial(site, plan, movement, cfg=None):
    cfg = cfg or run_context.config(); g = gcfg()
    clear = cfg["placement"]["sign_feature_clearance_m"]; thr = cfg["fusion"]["min_critical_confidence"]
    s0, s1 = movement["current"]["station_m"], movement["proposed"]["station_m"]; side = movement["proposed"]["side"]
    fp = g["device_footprint_length_m"] / 2; out = []
    lo, hi = sorted((s0, s1))

    def add(rel, sev, feature=None, **kw):
        out.append({"relationship": rel, "severity": sev, "feature": feature, **kw})

    cov = coverage(site, [(s1, movement["proposed"]["offset_m"])])
    if not cov["covered"]:
        add("OUTSIDE_EVIDENCE_COVERAGE", "BLOCKING", None, detail=cov["points"][0], overridable=False,
            explanation="Proposed position is outside the saved evidence coverage; the placement cannot be shown to be safe.")
    for kind, f in _features(site):
        fid = f.get("feature_key") or f"{f.get('source')}:{kind}"
        feat = {"feature_id": fid, "type": kind.rstrip("s").upper(), "source": f.get("source"), "station_m": f.get("station_m"),
                "side": f.get("side"), "confidence": f.get("confidence"), "evidence_version": site["site_model_id"],
                "status": f.get("sme_decision") or ("MAPPED" if f.get("source") == "OSM" else
                                                    "OBSERVED" if (f.get("confidence") or 0) >= thr else "LOW_CONFIDENCE")}
        if f.get("station_m") is None:
            add("FEATURE_GEOMETRY_UNCERTAIN", "BLOCKING" if kind in CONFLICT_KINDS else "WARNING", feat,
                explanation="feature position unknown; the validator treats it as a conflict for every sign"); continue
        sf = f["station_m"]; h = g["feature_influence_half_length_m"].get(kind, 3.0)
        uncertain = f.get("source") == "AI" and (f.get("confidence") or 0) < thr and not f.get("sme_decision")
        dist_edge = max(0.0, abs(s1 - sf) - h - fp)
        if abs(s1 - sf) <= h + fp:
            add("PROPOSED_POINT_INSIDE", "WARNING" if uncertain else "BLOCKING", feat, distance_to_boundary_m=0.0,
                overlap_m=r(h + fp - abs(s1 - sf), 3), influence_half_length_m=h,
                explanation=f"proposed device inside the approximate {kind[:-1]} area")
        if kind in CONFLICT_KINDS and abs(s1 - sf) <= clear + fp:
            add("PLACEMENT_CLEARANCE_OVERLAPS", "WARNING" if uncertain else "BLOCKING", feat,
                distance_m=r(abs(s1 - sf), 3), required_clearance_m=clear, overlap_m=r(clear + fp - abs(s1 - sf), 3),
                rule="GEO-DRIVEWAY-INTERSECTION-CONFLICT / VAL-CONFLICT (poc_config placement.sign_feature_clearance_m)",
                overridable=True)
        elif abs(s1 - sf) <= clear + g["near_distance_m"]:
            add("PROPOSED_POINT_NEAR", "WARNING", feat, distance_to_boundary_m=r(dist_edge, 3),
                margin_to_required_clearance_m=r(abs(s1 - sf) - clear, 3),
                limited_margin=abs(s1 - sf) - clear < g["limited_margin_m"])
        if lo < sf < hi:
            add("FEATURE_BETWEEN_CURRENT_AND_PROPOSED", "WARNING", feat, explanation="the device would move past this feature")
        if lo - h <= sf <= hi + h:
            add("PATH_CROSSES_FEATURE", "WARNING" if not uncertain else "WARNING", feat)
        if uncertain and abs(s1 - sf) <= clear + g["near_distance_m"]:
            add("FEATURE_GEOMETRY_UNCERTAIN", "WARNING", feat, explanation="low-confidence feature: confirm, reject or leave unresolved")
    for sw in site["features"].get("sidewalks", []):
        if sw.get("present") is True and sw.get("side") == side:
            add("PROPOSED_POINT_NEAR", "BLOCKING", {"feature_id": sw.get("feature_key") or f"{sw.get('source')}:sidewalk:{side}",
                                                    "type": "SIDEWALK", "source": sw.get("source"), "side": side},
                rule="GEO-PEDESTRIAN-CONFLICT", explanation="sidewalk / pedestrian route on the device side", overridable=True)
    half = site["road"]["road_edges"].get("left_offset_m") or 0
    if abs(movement["proposed"]["offset_m"]) <= half:
        add("PROPOSED_POINT_INSIDE", "BLOCKING", {"feature_id": "road_edges", "type": "TRAVELED_WAY"}, rule="GEO-TRAVELED-WAY")
    ws = site["work"]["reference_station_m"]
    if abs(s1 - ws) <= g["near_distance_m"]:
        add("PROPOSED_POINT_NEAR", "WARNING", {"feature_id": "W1", "type": "WORK_AREA"}, distance_m=r(abs(s1 - ws), 3))
    for o in (plan or {}).get("objects", []):
        if o["object_id"] in (movement["object_id"], "W1"): continue
        if abs((o["placement"].get("station_m") or 1e9) - s1) <= g["device_spacing_warning_m"]:
            add("PLACEMENT_CLEARANCE_OVERLAPS", "WARNING", {"feature_id": o["object_id"], "type": "PROPOSED_DEVICE"
                                                            if o.get("sme") else "EXISTING_DEVICE"})
    add("NOT_ASSESSED", "INFORMATIONAL", None, explanation="median, curb, shoulder, bridge and existing field devices are "
                                                           "not in the saved site geometry")
    if movement["lateral_offset_preserved"]: add("LATERAL_OFFSET_PRESERVED", "INFORMATIONAL", None)
    if cov["covered"]: add("NO_AZURE_MAPS_CALL_REQUIRED", "INFORMATIONAL", None, explanation="existing saved imagery covers the position")
    return out


def blocking(conflicts):
    return [x for x in conflicts if x["severity"] == "BLOCKING"]


# ---------------------------------------------------------------- candidates (never applied automatically)
def candidates(site, plan, movement, feature_id=None):
    g = gcfg(); cfg = run_context.config(); clear = cfg["placement"]["sign_feature_clearance_m"]; fp = g["device_footprint_length_m"] / 2
    o = _obj(plan, movement["object_id"]); trav = DIRECTION.get(o.get("approach"), 1)
    conf = [x for x in spatial(site, plan, movement, cfg) if x.get("feature") and x["severity"] == "BLOCKING"
            and x["feature"].get("station_m") is not None]
    target = next((x["feature"] for x in conf if not feature_id or x["feature"]["feature_id"] == feature_id), None)
    out = [{"kind": "ORIGINAL", "station_m": movement["current"]["station_m"], "label": "Keep current position"}]
    if target:
        sf = target["station_m"]; kind = target["type"].lower() + "s"
        h = g["feature_influence_half_length_m"].get(kind, 3.0); off = max(h, clear) + fp + 0.5
        # BEFORE = reached by traffic before the feature (upstream side); AFTER = beyond the far side
        out.append({"kind": "BEFORE_FEATURE", "feature_id": target["feature_id"], "station_m": r(sf - trav * off, 3),
                    "label": f"Place before {target['type'].lower()} {target['feature_id']}"})
        out.append({"kind": "AFTER_FEATURE", "feature_id": target["feature_id"], "station_m": r(sf + trav * off, 3),
                    "label": f"Place after {target['type'].lower()} {target['feature_id']}"})
    s_req = movement["proposed"]["station_m"]; step = g["candidate_step_m"]; found = None
    for k in range(0, int(g["max_move_m"] / step)):
        for sgn in ((1, -1) if k else (1,)):
            s = s_req + sgn * k * step
            mv = dict(movement, proposed=dict(movement["proposed"], station_m=r(s, 3)))
            if not blocking([x for x in spatial(site, plan, mv, cfg) if x["relationship"] != "PROPOSED_POINT_NEAR"
                             or x.get("rule")]):
                found = s; break
        if found is not None: break
    if found is not None:
        out.append({"kind": "NEAREST_WITHOUT_SPATIAL_CONFLICT", "station_m": r(found, 3),
                    "label": "Nearest position without a blocking spatial conflict"})
    frame = SiteFrame(site); lat = movement["proposed"]["offset_m"]
    for cnd in out:
        (x, y), _ = offset_point(frame.centerline, min(max(cnd["station_m"], 0.0), frame.length), lat)
        la, lo = frame.latlon(x, y)
        mv = dict(movement, proposed=dict(movement["proposed"], station_m=cnd["station_m"], latitude=r(la, 7), longitude=r(lo, 7)))
        cnd.update(latitude=r(la, 7), longitude=r(lo, 7), offset_m=lat,
                   move_from_current_m=r(cnd["station_m"] - movement["current"]["station_m"], 3),
                   blocking_spatial=[x["relationship"] + ":" + str((x.get("feature") or {}).get("feature_id")) for x in blocking(spatial(site, plan, mv, cfg))],
                   note=g["candidate_label"], auto_applied=False)
    return out


def _rule_impact(ctx, decision_doc, revision_extra):
    p = preview.compute(ctx, decision_doc, revision_extra)
    return {"rules": p["rules"], "dispositions": p.get("dispositions"), "plan_outcome": p["plan_outcome"], "ta": p["ta"]}


# ---------------------------------------------------------------- evaluate / stage (deterministic)
def evaluate(ident, cid, ctx, req):
    site, plan, _, extra = proposal_state(ctx, cid)
    mv = calculate(site, plan, req.get("object_id"), req.get("direction"), req.get("distance"), req.get("unit", "FT"),
                   req.get("preserve_lateral_offset", True), req.get("station_m"))
    conflicts = spatial(site, plan, mv)
    adj = _adjustment(mv, req)
    extra2 = dict(extra, placement_adjustments=[a for a in extra["placement_adjustments"] if a["object_id"] != mv["object_id"]] + [adj])
    doc, _ = D.effective(ctx, cid)
    p = preview.compute(ctx, doc, extra2)
    rows = {r_["check_id"]: r_ for r_ in p["rules"]}
    a_ft = (rows.get("VAL-SPACING") or {})
    result = {"movement": mv, "spatial_conflicts": conflicts, "blocking": blocking(conflicts),
              "rule_impact": [r_ for r_ in p["rules"] if r_.get("proposed") == "FAIL" or r_.get("current") != r_.get("proposed")],
              "rule_requirement": {"check": "VAL-SPACING", "requirement": "sign longitudinal distance equals Table 6B-1 A",
                                   "rule_distance_ft": next((o["placement"].get("rule_distance_ft") or o["placement"].get("longitudinal_distance_ft")
                                                             for o in plan["objects"] if o["object_id"] == mv["object_id"]), None),
                                   "current": a_ft.get("rule_status_current"), "proposed": a_ft.get("rule_status_proposed")},
              "ta_impact": {"current_ta": p["ta"]["current"]["ta_id"], "remains_applicable": p["ta"]["proposed"]["applicable"],
                            "candidate_tas": p["ta"]["approved_candidates_found"], "changed_conditions": p["ta"]["changed_conditions"]},
              "artifact_impact": {"azure_maps_required": False, "reuse": "saved imagery, OSM and AI evidence (strict replay)",
                                  "regenerate": ["plan.json", "validation_results.json", "debug_plan", "tcp_sheet"]},
              "plan_outcome": p["plan_outcome"], "adjustment": adj, "exceptions_needed": [r_["check_id"] for r_ in p["rules"] if r_.get("proposed") == "FAIL"],
              "ai_calls": 0}
    if result["blocking"] or result["exceptions_needed"]:
        result["candidates"] = candidates(site, plan, mv)
        result["actions"] = ["KEEP_CURRENT_POSITION", "PLACE_BEFORE_FEATURE", "PLACE_AFTER_FEATURE", "USE_NEAREST_CANDIDATE",
                             "CHOOSE_DIFFERENT_DISTANCE", "PROCEED_AS_SME_EXCEPTION", "ENTER_CUSTOM_INSTRUCTION"]
    return result


def _adjustment(mv, req):
    return {"adjustment_id": new_id("adj"), "object_id": mv["object_id"], "station_m": mv["proposed"]["station_m"],
            "lateral_m": mv["proposed"]["offset_m"], "preserve_lateral_offset": mv["lateral_offset_preserved"],
            "requested": mv["requested"], "calculation": {k: mv[k] for k in ("current", "proposed", "station_change_m",
                                                                             "actual_along_alignment_m", "straight_line_m",
                                                                             "lateral_offset_preserved", "method", "accuracy")},
            "candidate_kind": req.get("candidate_kind"), "message_id": req.get("message_id")}


def _stage(tctx, ctx, cid, req):
    ident = tctx.identity
    D.authorize(ident, "move_existing_device", req.get("reason"))
    ev = evaluate(ident, cid, ctx, req)
    hard = [x for x in ev["blocking"] if x.get("overridable") is False]
    if hard:
        pol = D.policy()
        if not (pol.condition_overridable("OUTSIDE_EVIDENCE_COVERAGE") and pol.allowed("proceed_outside_evidence_coverage", ident.roles)[0]):
            raise AssistantError("OUTSIDE_EVIDENCE_COVERAGE", "The proposed position is outside the saved evidence coverage. "
                                 "This change is blocked (non-overridable in this POC).", 409, False, details={"evaluation": _public(ev)})
    adj = dict(ev["adjustment"], spatial_conflicts=[x for x in ev["spatial_conflicts"] if x["severity"] != "INFORMATIONAL"],
               reason=(req.get("reason") or "").strip()[:500])
    key = f"ADJUST:{adj['object_id']}"
    c().store.append_event("conversations", cid, {"type": "stage", "key": key, "decision": {
        "adjustment": adj, "action": "MOVE_DEVICE", "object_id": adj["object_id"], "decision_id": adj["adjustment_id"],
        "reason": adj["reason"], "decided_by": ident.subject_id, "decided_at": now_iso(), "message_id": req.get("message_id"),
        "value": adj["station_m"]}}, durable=True)
    c().audit.write("PLACEMENT_STAGED", ident, consequential=True, conversation_id=cid, object_id=adj["object_id"],
                    adjustment_id=adj["adjustment_id"], requested=adj["requested"], station_m=adj["station_m"],
                    entity_reference={k: (ev["movement"].get("reference") or {}).get(k) for k in
                                      ("original_reference", "normalized_reference", "resolved_entity_id", "resolution_method")})
    return {"key": key, "evaluation": _public(ev), "_tool_meta": {"affected_entities": [adj["object_id"]]}}


def _public(ev):
    return ev


def relative_station(site, plan, object_id, feature_key, relation):
    """Deterministic station BEFORE (upstream, reached first by this approach's traffic) or AFTER a saved feature."""
    o = _obj(plan, object_id); object_id = o["object_id"]; trav = DIRECTION.get(o.get("approach"))
    if not trav: raise AssistantError("DIRECTION_UNDEFINED", f"{object_id} has no approach direction.", 400)
    f = next((f for kind, f in _features(site) if f.get("feature_key") == feature_key), None)
    if f is None or f.get("station_m") is None:
        raise AssistantError("ENTITY_NOT_FOUND", f"Feature {feature_key} is unknown or has no position.", 404)
    g = gcfg(); cfg = run_context.config()
    kind = feature_key.split(":")[1] if ":" in feature_key else "intersections"
    off = max(g["feature_influence_half_length_m"].get(kind, 3.0), cfg["placement"]["sign_feature_clearance_m"]) + g["device_footprint_length_m"] / 2 + 0.5
    return r(f["station_m"] - trav * off if relation == "BEFORE" else f["station_m"] + trav * off, 3)


def post_evaluation(cid, ev, source="button", reason=None, message_id=None):
    """Chat message for a deterministic placement evaluation: CONFLICT_RESULT when anything blocks, else DETERMINISTIC_RESULT.
    Engineering summary only; the full evaluation is kept for the 'details' view and the stage action."""
    from .conversations import add_message
    m = ev["movement"]; blocking = ev["blocking"]; exc = ev["exceptions_needed"]
    kind = "CONFLICT_RESULT" if (blocking or exc) else "DETERMINISTIC_RESULT"
    req = m["requested"]
    asked = (f"Move {m['object_id']} {req.get('distance')} {str(req.get('unit', '')).lower()} {str(req.get('direction', '')).lower()}"
             if req.get("operation") == "MOVE_DEVICE" else f"Place {m['object_id']} at station {m['proposed']['station_m']} m")
    summary = {"title": "Placement conflict detected" if kind == "CONFLICT_RESULT" else "Placement calculated - no conflicts",
               "requested": asked, "object_id": m["object_id"], "reference": m.get("reference"),
               "current_station_m": m["current"]["station_m"], "proposed_station_m": m["proposed"]["station_m"],
               "current": {k: m["current"][k] for k in ("latitude", "longitude", "offset_m")},
               "proposed": {k: m["proposed"][k] for k in ("latitude", "longitude", "offset_m")},
               "along_m": m["actual_along_alignment_m"], "along_ft": m["actual_along_alignment_ft"],
               "straight_m": m["straight_line_m"], "offset_preserved": m["lateral_offset_preserved"],
               "conflicts": [{"relationship": c["relationship"], "severity": c["severity"],
                              "feature": (c.get("feature") or {}).get("feature_id"), "type": (c.get("feature") or {}).get("type"),
                              "source": (c.get("feature") or {}).get("source"), "confidence": (c.get("feature") or {}).get("confidence"),
                              "overlap_m": c.get("overlap_m"), "distance_m": c.get("distance_m", c.get("distance_to_boundary_m"))}
                             for c in ev["spatial_conflicts"] if c["severity"] != "INFORMATIONAL"],
               "rule_impact": [{"check_id": r["check_id"], "current": r.get("rule_status_current"), "proposed": r.get("rule_status_proposed")}
                               for r in ev["rule_impact"]],
               "ta": ev["ta_impact"], "plan_outcome": ev["plan_outcome"]["status"], "exceptions_needed": exc,
               "candidates": [{k: x.get(k) for k in ("kind", "label", "station_m", "move_from_current_m", "blocking_spatial", "note")}
                              for x in ev.get("candidates") or []],
               "stage_payload": ({"object_id": m["object_id"], "direction": req["direction"], "distance": req["distance"],
                                  "unit": req["unit"], "preserve_lateral_offset": m["lateral_offset_preserved"], "message_id": message_id}
                                 if req.get("operation") == "MOVE_DEVICE" else
                                 {"object_id": m["object_id"], "station_m": m["proposed"]["station_m"], "message_id": message_id}),
               "source": source, "ai_calls": 0, "reason": reason, "evaluation": ev}
    return add_message(cid, "assistant", kind, summary)
