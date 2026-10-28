"""Deterministic SME decision overlay: machine_site_model + sme_decisions -> effective_site_model.

Never modifies the machine model (works on a deep copy). For every SME-decided fact the effective field keeps the
original machine value, status, confidence, source and observations under "machine" and the SME action under "sme";
an SME value is never represented as an AI/OSM observation (source SME_CONFIRMED / SME_CORRECTED / SME_UNRESOLVED).
Dependent facts are recalculated with the same rules as src/tcp_planner/site_model/fusion.py and marked DERIVED_FROM_SME:

  road.lane_count, road.road_edges ──► work.encroaches_traveled_way ──► work.location
  work.location (direct) ──► work.encroaches_traveled_way (TRAVELED_WAY <=> encroaching)
  work.encroaches_traveled_way ──► work.requires_lane_closure ──► work.requires_alternating_one_lane_traffic
  work.side, sidewalks, crosswalk features ──► work.affects_pedestrian_route
  road.two_way ──► road.traffic_direction ; features ──► eligibility intersection analysis (unchanged code)

Used identically by the assistant preview and by revision runs of the pipeline (src/tcp_planner/orchestration/pipeline.py --sme-revision).
"""
from tcp_planner.contracts import deep_copy, content_hash, field, r, RESOLVED, UNRESOLVED, CONFLICT, LOW_CONFIDENCE
from tcp_planner.geometry.local_frame import signed_lateral, enu, offset_polyline, to_latlon_list, from_latlon_list

OVERLAY_VERSION = "tcp-sme-overlay-v1"
FACT_TYPES = {"road.lane_count": "int", "road.two_way": "bool", "road.divided": "bool", "road.facility_type": "enum",
              "road.road_type": "enum", "road.road_edges": "float", "work.side": "enum", "work.location": "enum",
              "work.encroaches_traveled_way": "bool", "work.affects_pedestrian_route": "bool",
              "site.complex_intersection_conflict": "bool"}
FEATURE_KINDS = ("intersections", "driveways", "crosswalks", "roundabouts", "ramps", "obstructions")
SME_SOURCE = {"CONFIRM": "SME_CONFIRMED", "CORRECT": "SME_CORRECTED", "MARK_UNRESOLVED": "SME_UNRESOLVED"}
DERIVED = "DERIVED_FROM_SME"
TRACKED = ("road.lane_count", "road.two_way", "road.traffic_direction", "road.divided", "road.facility_type",
           "road.road_type", "road.road_edges", "work.side", "work.location", "work.encroaches_traveled_way",
           "work.requires_lane_closure", "work.requires_alternating_one_lane_traffic", "work.affects_pedestrian_route")
AGENT_ESCALATIONS = ("CROSS_VIEW_MISMATCH", "AI_CALL2_UNAVAILABLE", "CROPS_UNAVAILABLE", "MODEL_CALL_LIMIT_REACHED")


def feature_key(kind, f, ai_index):
    if f.get("feature_key"): return f["feature_key"]
    if f.get("source") == "OSM":
        return f"osm:{kind}:" + (f"way:{f['way_id']}" if f.get("way_id") else f"node:{f.get('node_id')}")
    return f"ai:{kind}:{ai_index}"


def keyed_features(features):
    """{key: (kind, feature)} in machine order (AI index counts AI features of the kind)."""
    out = {}
    for kind in FEATURE_KINDS:
        n = 0
        for f in features.get(kind, []):
            k = feature_key(kind, f, n if f.get("source") == "AI" else None)
            if f.get("source") == "AI": n += 1
            out[k] = (kind, f)
    return out


def _get(sm, key):
    if key == "road.road_edges": return sm["road"]["road_edges"]
    g, n = key.split(".", 1)
    return sm["road" if g == "road" else "work"][n]


def _set(sm, key, f):
    g, n = key.split(".", 1)
    sm["road" if g == "road" else "work"][n] = f


def _machine_block(f):
    return {k: f.get(k) for k in ("value", "status", "confidence", "source", "note")}


def _sme_field(orig, d):
    act = d["action"]
    value = d.get("value", orig.get("value")) if act == "CONFIRM" else (d.get("value") if act == "CORRECT" else None)
    status = UNRESOLVED if act == "MARK_UNRESOLVED" else RESOLVED
    out = field(value, status, None, list(orig.get("observations") or []), source=SME_SOURCE[act],
                note=f"SME {act.lower().replace('_', ' ')}" + (f": {d['reason']}" if d.get("reason") else ""))
    out["machine"] = orig.get("machine") or _machine_block(orig)
    out["sme"] = {k: d.get(k) for k in ("decision_id", "action", "value", "reason", "decided_by", "decided_at", "finding_id")}
    return out


def _derived(orig, value, status, confidence, because, note=None):
    out = field(value, status, confidence, list(orig.get("observations") or []), source=DERIVED,
                note=note or f"recalculated from SME decision(s): {', '.join(because)}")
    out["machine"] = orig.get("machine") or _machine_block(orig)
    out["derived_from"] = list(because)
    return out


def _obs(f, source):
    return next((o for o in f.get("observations") or [] if o.get("source") == source), {})


def _audit_entry(sm, name):
    return next((a for a in sm.get("audit") or [] if a.get("field") == name), {})


def apply(machine, decisions, config):
    """-> effective site model (new object). decisions = {"facts": [...], "features": [...], "sidewalks": [...]}."""
    eff = deep_copy(machine)
    fz = config["fusion"]; thr = fz["min_critical_confidence"]; floor = config["agent"]["agreement_floor"]
    facts = {d["field"]: d for d in decisions.get("facts") or []}
    unknown = sorted(set(facts) - set(FACT_TYPES))
    if unknown: raise ValueError(f"unsupported SME fact fields {unknown}")
    road, work = eff["road"], eff["work"]
    ref = eff["project_geometry"]["work_reference"]; lat0, lon0 = ref["latitude"], ref["longitude"]
    cl = from_latlon_list(road["centerline"], lat0, lon0)

    # ---- 1. direct road / work facts
    for key in ("road.lane_count", "road.two_way", "road.divided", "road.facility_type", "road.road_type", "work.side"):
        if key in facts: _set(eff, key, _sme_field(_get(machine, key), facts[key]))
    tw = road["two_way"]
    road["traffic_direction"] = {"value": None if tw["value"] is None else ("TWO_WAY" if tw["value"] else "ONE_WAY"),
                                 "status": tw["status"]}
    if "road.road_edges" in facts:
        d = facts["road.road_edges"]; m = machine["road"]["road_edges"]
        w = d.get("value", m.get("traveled_way_width_m")) if d["action"] == "CONFIRM" else (d.get("value") if d["action"] == "CORRECT" else None)
        e = {"status": RESOLVED if w else UNRESOLVED, "observations": list(m.get("observations") or []),
             "note": f"SME {d['action'].lower()}" + (f": {d['reason']}" if d.get("reason") else ""),
             "traveled_way_width_m": r(w, 3), "left_offset_m": r(w / 2, 3) if w else None,
             "right_offset_m": r(w / 2, 3) if w else None, "model": m.get("model"), "source": SME_SOURCE[d["action"]],
             "machine": {"traveled_way_width_m": m.get("traveled_way_width_m"), "status": m["status"], "source": m.get("source"),
                         "note": m.get("note")},
             "sme": {k: d.get(k) for k in ("decision_id", "action", "value", "reason", "decided_by", "decided_at", "finding_id")}}
        if w:
            e["left"] = to_latlon_list(offset_polyline(cl, w / 2), lat0, lon0)
            e["right"] = to_latlon_list(offset_polyline(cl, -w / 2), lat0, lon0)
        road["road_edges"] = e

    # ---- 2. features and sidewalks (machine originals kept in original_features)
    eff["original_features"] = deep_copy(machine.get("original_features") or machine["features"])
    feats = eff["features"]; keyed = keyed_features(feats); rejected = {}
    for k, (kind, f) in keyed.items(): f["feature_key"] = k
    fdec = {d["feature_key"]: d for d in decisions.get("features") or [] if d["action"] != "ADD"}
    for k, d in fdec.items():
        if k not in keyed: raise ValueError(f"unknown feature {k}")
        kind, f = keyed[k]
        meta = {"sme_decision": {"CONFIRM": "CONFIRMED", "REJECT": "REJECTED", "MODIFY": "MODIFIED"}[d["action"]],
                "sme_decision_id": d.get("decision_id"), "sme_reason": d.get("reason")}
        if d["action"] == "REJECT":
            feats[kind].remove(f); rejected[k] = {**f, **meta, "kind": kind}
        elif d["action"] == "MODIFY":
            f.update(meta, machine_station_m=f.get("station_m"), machine_side=f.get("side"),
                     station_m=r(d["station_m"], 2), side=d.get("side") or f.get("side"))
        else:
            f.update(meta)
    for d in decisions.get("features") or []:
        if d["action"] != "ADD": continue
        if d["kind"] not in FEATURE_KINDS: raise ValueError(f"unsupported feature kind {d['kind']}")
        feats[d["kind"]].append({"source": "SME", "kind": d["kind"], "station_m": r(d["station_m"], 2), "side": d.get("side"),
                                 "description": (d.get("description") or "")[:200], "confidence": None,
                                 "sme_feature_id": d["decision_id"], "feature_key": f"sme:{d['kind']}:{d['decision_id']}",
                                 "sme_decision": "ADDED", "sme_decision_id": d["decision_id"], "sme_reason": d.get("reason")})
    sw_dec = {d["side"]: d for d in decisions.get("sidewalks") or []}
    if sw_dec:
        feats["sidewalks"] = [s for s in feats.get("sidewalks", []) if s.get("side") not in sw_dec] + [
            {"source": "SME", "side": side, "present": d.get("present"), "feature_key": f"sme:sidewalks:{side}",
             "sme_decision": "CONFIRMED" if d.get("present") is not None else "UNKNOWN", "sme_decision_id": d.get("decision_id"),
             "sme_reason": d.get("reason")} for side, d in sorted(sw_dec.items())]

    # ---- 3. encroachment / location (direct, or recalculated from SME width / lane count / location)
    changed_inputs = [k for k in ("road.lane_count", "road.road_edges") if k in facts]
    if "work.encroaches_traveled_way" in facts:
        _set(eff, "work.encroaches_traveled_way", _sme_field(machine["work"]["encroaches_traveled_way"], facts["work.encroaches_traveled_way"]))
    elif "work.location" in facts and facts["work.location"]["action"] != "MARK_UNRESOLVED":
        loc = facts["work.location"]["value"] if facts["work.location"]["action"] == "CORRECT" else machine["work"]["location"]["value"]
        if loc is not None:
            work["encroaches_traveled_way"] = _derived(machine["work"]["encroaches_traveled_way"], loc == "TRAVELED_WAY", RESOLVED,
                                                       None, ["work.location"])
    elif changed_inputs:
        work["encroaches_traveled_way"] = _recompute_encroachment(eff, machine, cl, fz, thr, floor, changed_inputs)
    enc = work["encroaches_traveled_way"]
    if "work.location" in facts:
        _set(eff, "work.location", _sme_field(machine["work"]["location"], facts["work.location"]))
    elif _differs(enc, machine["work"]["encroaches_traveled_way"]):
        work["location"] = _recompute_location(machine, enc, thr)

    # ---- 4. lane closure / alternating traffic (always derived)
    if _differs(enc, machine["work"]["encroaches_traveled_way"]):
        mc = machine["work"]["requires_lane_closure"]
        op = bool(_obs(mc, "OPERATOR").get("value"))
        if op or enc["value"] is True: v, st, c = True, RESOLVED, 1.0
        elif enc["value"] is False: v, st, c = False, RESOLVED, enc.get("confidence")
        else: v, st, c = None, UNRESOLVED, None
        work["requires_lane_closure"] = _derived(mc, v, st, c, ["work.encroaches_traveled_way"])
        work["requires_alternating_one_lane_traffic"] = _derived(machine["work"]["requires_alternating_one_lane_traffic"], v, st, c,
                                                                 ["work.requires_lane_closure"])

    # ---- 5. pedestrian impact
    xw_changed = any(d.get("kind") == "crosswalks" or str(d.get("feature_key", "")).split(":")[1:2] == ["crosswalks"]
                     for d in decisions.get("features") or [])
    if "work.affects_pedestrian_route" in facts:
        _set(eff, "work.affects_pedestrian_route", _sme_field(machine["work"]["affects_pedestrian_route"], facts["work.affects_pedestrian_route"]))
    elif sw_dec or xw_changed or "work.side" in facts:
        work["affects_pedestrian_route"] = _recompute_pedestrian(eff, machine, sw_dec, fz)

    # ---- 6. intersection conflict (read by eligibility only when no feature is in the analysis window)
    overlay_facts = {}
    if "site.complex_intersection_conflict" in facts:
        d = facts["site.complex_intersection_conflict"]
        overlay_facts["site.complex_intersection_conflict"] = {
            "value": None if d["action"] == "MARK_UNRESOLVED" else d.get("value"),
            "source": SME_SOURCE[d["action"]], "decision_id": d.get("decision_id"), "action": d["action"],
            "note": "SME decision; positive feature evidence in the analysis window still takes precedence (eligibility)"}

    # ---- 7. conflicts / escalations superseded by SME decisions
    decided = lambda key: _get(eff, key).get("source") in (*SME_SOURCE.values(), DERIVED) and _status(_get(eff, key)) == RESOLVED
    kept, superseded = [], []
    for c in eff.get("critical_conflicts") or []:
        k = c["field"]
        (superseded if k in FACT_TYPES and k != "site.complex_intersection_conflict" and decided(k) else kept).append(c)
    eff["critical_conflicts"] = kept
    m_unresolved = [k for k, v in (machine.get("critical_field_status") or {}).items() if v != RESOLVED and k in TRACKED]
    all_addressed = all(_status(_get(eff, k)) == RESOLVED for k in m_unresolved)
    unplaced = [k for k, (kind, f) in keyed_features(machine["features"]).items() if f.get("source") == "AI" and f.get("station_m") is None]
    unplaced_done = all(k in fdec and fdec[k]["action"] in ("REJECT", "MODIFY") for k in unplaced)
    esc_kept, esc_sup = [], []
    for e in eff.get("escalations") or []:
        sup = (e.get("field") == "agent" and e.get("status") in AGENT_ESCALATIONS and all_addressed and m_unresolved) or \
              (e.get("reason_code") == "NO_POSITION_AFTER_CROP" and unplaced and unplaced_done)
        (esc_sup if sup else esc_kept).append(e)
    eff["escalations"] = esc_kept

    # ---- 8. status summary, change list, identity
    statuses = dict(eff.get("critical_field_status") or {})
    for k in statuses:
        if k == "road.centerline_status": continue
        try: statuses[k] = _status(_get(eff, k))
        except KeyError: pass
    eff["critical_field_status"] = statuses
    eff["eligibility_inputs_complete"] = all(v == RESOLVED for v in statuses.values()) and not eff["critical_conflicts"] and not eff["escalations"]
    eff["sme_feature_decisions"] = list(decisions.get("features") or []) + list(decisions.get("sidewalks") or [])
    eff["sme_overlay"] = {"version": OVERLAY_VERSION, "machine_site_model_id": machine["site_model_id"],
                          "decisions": decisions, "decisions_sha256": content_hash(decisions), "facts": overlay_facts,
                          "changes": diff(machine, eff, facts), "superseded_conflicts": superseded,
                          "superseded_escalations": esc_sup, "rejected_features": rejected}
    eff["version"] = machine.get("version", 1)
    eff["site_model_id"] = None
    eff["site_model_id"] = "SITE-" + content_hash(eff, drop={"site_model_id"})[:16].upper()
    return eff


def _status(f):
    return f.get("status")


def _val(f):
    return f.get("traveled_way_width_m") if "traveled_way_width_m" in f else f.get("value")


def _differs(a, b):
    return (_val(a), a.get("status")) != (_val(b), b.get("status"))


def _recompute_encroachment(eff, machine, cl, fz, thr, floor, because):
    """Same rule as site_fusion (bounded traveled-way limit + AI outside answer) with SME width / lane count."""
    mf = machine["work"]["encroaches_traveled_way"]
    if mf.get("status") == "CROSS_VIEW_MISMATCH" and mf.get("value") is not True:
        return _derived(mf, None, "CROSS_VIEW_MISMATCH", None, because, "cross-view mismatch remains: decide work location directly")
    e = eff["road"]["road_edges"]; geo = _obs(mf, "GEOMETRY")
    w = e.get("traveled_way_width_m") if e.get("status") == RESOLVED else geo.get("width_m")
    lc = eff["road"]["lane_count"]
    lanes = lc["value"] if lc["status"] == RESOLVED else (_obs(lc, "AI").get("value"))
    lo, hi = fz["lane_width_plausible_m"]
    per = w / lanes if (w and lanes) else None
    if per is None or not (lo <= per <= hi):
        why = "width missing" if not w else "lane count missing" if not lanes else f"implausible width ({per:.2f} m per lane outside {lo}-{hi} m)"
        return _derived(mf, None, UNRESOLVED, None, because, f"traveled-way limit unknown: {why}")
    limit = w / 2 + fz["encroachment_tolerance_m"] + fz["centerline_error_allowance_m"]
    ref = eff["project_geometry"]["work_reference"]
    pts = [(0.0, 0.0)] + [enu(p["latitude"], p["longitude"], ref["latitude"], ref["longitude"])
                          for p in eff["project_geometry"].get("work_path") or []]
    _, _, lateral = signed_lateral(cl, (0.0, 0.0))
    lats = [signed_lateral(cl, p)[2] for p in pts]
    geo_outside = all(abs(v) > limit for v in lats) and all((v > 0) == (lateral > 0) for v in lats)
    if not geo_outside: return _derived(mf, True, RESOLVED, 1.0, because)
    ai = _obs(mf, "AI"); ai_out = None if ai.get("value") is None else (not ai["value"]); conf = ai.get("confidence")
    cutoff = thr if _audit_entry(machine, "work.encroaches_traveled_way").get("source_call") == "CALL_2" else floor
    if ai_out is None: return _derived(mf, None, UNRESOLVED, None, because)
    if (conf or 0) < cutoff: return _derived(mf, None, LOW_CONFIDENCE, conf, because, f"AI confidence below {cutoff}")
    if ai_out is False: return _derived(mf, None, CONFLICT, None, because, "geometry outside, AI inside")
    return _derived(mf, False, RESOLVED, conf, because)


def _recompute_location(machine, enc, thr):
    ml = machine["work"]["location"]; ai = _obs(ml, "AI"); rel, conf = ai.get("value"), ai.get("confidence")
    b = ["work.encroaches_traveled_way"]
    if enc["value"] is True: return _derived(ml, "TRAVELED_WAY", RESOLVED, enc.get("confidence"), b)
    if enc["value"] is False:
        if rel in ("BEYOND_SHOULDER", "SHOULDER") and (conf or 0) >= thr: return _derived(ml, rel, RESOLVED, conf, b)
        if rel in ("BEYOND_SHOULDER", "SHOULDER"): return _derived(ml, None, LOW_CONFIDENCE, conf, b, f"AI confidence below {thr}")
        if rel == "TRAVELED_WAY": return _derived(ml, None, CONFLICT, None, b, "geometry outside, AI says traveled way")
        return _derived(ml, None, UNRESOLVED, None, b)
    return _derived(ml, None, enc["status"], None, b)


def _recompute_pedestrian(eff, machine, sw_dec, fz):
    mp = machine["work"]["affects_pedestrian_route"]; side = eff["work"]["side"]
    because = [k for k, on in (("sidewalks", bool(sw_dec)), ("work.side", eff["work"]["side"].get("source", "").startswith("SME")),
                               ("crosswalk features", True)) if on]
    if side.get("status") != RESOLVED or side.get("value") not in ("LEFT", "RIGHT"):
        return _derived(mp, None, UNRESOLVED, None, because, "work side unresolved")
    s = side["value"]
    if s in sw_dec: sw = sw_dec[s].get("present")
    elif mp.get("status") == RESOLVED and not side.get("source", "").startswith("SME"):
        sw = _obs(mp, "AI").get("work_side_sidewalk")
    else: sw = None
    if sw is None: return _derived(mp, None, UNRESOLVED, None, because, f"sidewalk on the {s} (work) side not confirmed")
    s0 = eff["work"]["reference_station_m"]; radius = fz["pedestrian_conflict_radius_m"]
    near = [f for f in eff["features"].get("crosswalks", []) if f.get("station_m") is None or abs(f["station_m"] - s0) <= radius]
    return _derived(mp, bool(sw or near), RESOLVED, None, because)


def diff(machine, eff, facts):
    out = []
    for key in TRACKED:
        try: m, e = _get(machine, key), _get(eff, key)
        except KeyError: continue
        if not _differs(m, e) and e.get("source") == m.get("source"): continue
        out.append({"field": key, "kind": "DIRECT" if key in facts else "DEPENDENT",
                    "machine": {"value": _val(m), "status": m.get("status"), "confidence": m.get("confidence"), "source": m.get("source")},
                    "effective": {"value": _val(e), "status": e.get("status"), "source": e.get("source")},
                    "because": e.get("derived_from") or [key]})
    return out
