"""Supported / review / unsupported classification. Runs BEFORE any rule execution or placement.

Reads only the SiteModel, the approved rule pack and scope config.
Failed condition with a resolved value -> UNSUPPORTED_POC. Anything unresolved -> REVIEW_REQUIRED.
"""
from .models import (FT, RESOLVED, SUPPORTED_AUTO, REVIEW_REQUIRED, UNSUPPORTED_POC,
                     UNSUPPORTED_MESSAGE, REVIEW_MESSAGE, RulePackError)

FIELD_LABEL = {
    "road.lane_count": "LANE_COUNT", "road.traffic_direction": "TWO_WAY_STATUS", "road.divided": "DIVIDED_STATUS",
    "facility_type": "FACILITY_TYPE", "work.location": "WORK_LOCATION",
    "work.encroaches_traveled_way": "TRAVELED_WAY_ENCROACHMENT", "work.requires_lane_closure": "LANE_CLOSURE",
    "work.requires_alternating_one_lane_traffic": "ALTERNATING_TRAFFIC",
    "work.affects_pedestrian_route": "PEDESTRIAN_IMPACT", "site.complex_intersection_conflict": "INTERSECTION_CONFLICT",
}
FAIL_CODE = {
    "road.lane_count": "LANE_COUNT_NOT_TWO", "road.traffic_direction": "NOT_TWO_WAY", "road.divided": "DIVIDED_ROAD",
    "facility_type": "FACILITY_NOT_CONVENTIONAL_ROAD", "work.location": "WORK_NOT_BEYOND_SHOULDER",
    "work.encroaches_traveled_way": "TRAVELED_WAY_ENCROACHMENT", "work.requires_lane_closure": "LANE_CLOSURE_REQUIRED",
    "work.requires_alternating_one_lane_traffic": "ALTERNATING_TRAFFIC_REQUIRED",
    "work.affects_pedestrian_route": "PEDESTRIAN_ROUTE_IMPACT", "site.complex_intersection_conflict": "INTERSECTION_CONFLICT",
}
OPS = {"EQ": lambda a, b: a == b, "NE": lambda a, b: a != b, "IN": lambda a, b: a in b,
       "LE": lambda a, b: a <= b, "GE": lambda a, b: a >= b}


def conflict_window_m(site_model, rule_pack, config):
    """Half-length of the analysed corridor around the work station used for conflict checks."""
    rt = site_model["road"]["road_type"]
    margin = config["eligibility"]["intersection_window_margin_m"]
    if rt["status"] == RESOLVED:
        try:
            _, a_ft = rule_pack.spacing_value_ft(rt["value"], "A")
            return a_ft * FT + margin
        except RulePackError:
            pass
    return float("inf")  # unknown spacing -> every analysed feature counts (conservative)


def intersection_conflict(site_model, rule_pack, config):
    """(value, status, details) for site.complex_intersection_conflict."""
    s0 = site_model["work"]["reference_station_m"]; win = conflict_window_m(site_model, rule_pack, config)
    feats = site_model["features"]
    near = lambda f: f.get("station_m") is None or abs(f["station_m"] - s0) <= win
    hits = [f for k in ("intersections", "roundabouts", "ramps") for f in feats[k] if near(f)]
    ai_conf = site_model["feature_confidence"]["intersection_conflict"]
    ai_ok = site_model["evidence"]["ai"]["available"] and ai_conf is not None and \
        ai_conf >= config["fusion"]["min_critical_confidence"]
    details = {"window_m": None if win == float("inf") else round(win, 2), "features_in_window": hits}
    sme = ((site_model.get("sme_overlay") or {}).get("facts") or {}).get("site.complex_intersection_conflict")
    if sme is not None and not hits:  # SME decision (revision runs only); feature evidence in the window takes precedence
        details["sme_decision"] = sme
        return sme["value"], (RESOLVED if sme["value"] is not None else "UNRESOLVED"), details
    if hits and win == float("inf"):
        # spacing unknown: only features inside the smallest possible approved window are definite conflicts
        margin = config["eligibility"]["intersection_window_margin_m"]
        min_win = min(rule_pack.spacing_value_ft(rt, "A")[1] for rt in config["supported_road_types"]) * FT + margin
        definite = [f for f in hits if f.get("station_m") is not None and abs(f["station_m"] - s0) <= min_win]
        details["minimum_window_m"] = round(min_win, 2)
        if not definite: return None, "UNRESOLVED", details
        details["features_in_window"] = definite
    if hits: return True, RESOLVED, details          # positive evidence from any source blocks automation
    if ai_ok: return False, RESOLVED, details
    return None, "UNRESOLVED" if not site_model["evidence"]["ai"]["available"] else "LOW_CONFIDENCE", details


def build_facts(site_model, rule_pack, config):
    road, work = site_model["road"], site_model["work"]
    ic_val, ic_status, ic_details = intersection_conflict(site_model, rule_pack, config)
    facts = {
        "road.lane_count": (road["lane_count"]["value"], road["lane_count"]["status"]),
        "road.traffic_direction": (road["traffic_direction"]["value"], road["traffic_direction"]["status"]),
        "road.divided": (road["divided"]["value"], road["divided"]["status"]),
        "facility_type": (road["facility_type"]["value"], road["facility_type"]["status"]),
        "work.location": (work["location"]["value"], work["location"]["status"]),
        "site.complex_intersection_conflict": (ic_val, ic_status),
    }
    for k in ("encroaches_traveled_way", "requires_lane_closure", "requires_alternating_one_lane_traffic",
              "affects_pedestrian_route"):
        facts[f"work.{k}"] = (work[k]["value"], work[k]["status"])
    return facts, ic_details


def evaluate(site_model, rule_pack, config):
    facts, ic_details = build_facts(site_model, rule_pack, config)
    failed, unresolved, passed = [], [], []
    for cond in rule_pack.section("01_eligibility_rules")["all_required"]:
        f, op, expected = cond["field"], cond["operator"], cond["value"]
        label = FIELD_LABEL.get(f, f.upper().replace(".", "_"))
        if f not in facts or op not in OPS:
            unresolved.append({"field": f, "status": "UNMAPPED_RULE_FIELD", "reason_code": f"{label}_UNMAPPED"}); continue
        value, status = facts[f]
        if status != RESOLVED or value is None:
            unresolved.append({"field": f, "status": status, "reason_code": f"{label}_{status if status != RESOLVED else 'UNRESOLVED'}"})
        elif not OPS[op](value, expected):
            failed.append({"field": f, "operator": op, "expected": expected, "actual": value,
                           "reason_code": FAIL_CODE.get(f, f"{label}_FAILED")})
        else:
            passed.append(f)

    # ---- scope checks beyond the rule-pack conditions ----
    road, work, feats = site_model["road"], site_model["work"], site_model["features"]
    pg = site_model["project_geometry"]
    if pg["input_feature_count"] > 2 or not pg.get("work_reference"):
        failed.append({"field": "project.work_locations", "reason_code": "MULTIPLE_WORK_LOCATIONS"})
    s0 = work["reference_station_m"]; win = ic_details["window_m"] or float("inf")
    near = lambda f: f.get("station_m") is None or abs(f["station_m"] - s0) <= win
    if any(near(f) for f in feats["roundabouts"]): failed.append({"field": "features.roundabouts", "reason_code": "ROUNDABOUT_PRESENT"})
    if any(near(f) for f in feats["ramps"]): failed.append({"field": "features.ramps", "reason_code": "RAMP_OR_FREEWAY_PRESENT"})
    if road["facility_type"]["value"] in ("FREEWAY", "TRUNK_ROAD", "RAMP_OR_LINK"):
        failed.append({"field": "facility_type", "reason_code": "RAMP_OR_FREEWAY_PRESENT"})

    rt = road["road_type"]
    if rt["status"] != RESOLVED:
        unresolved.append({"field": "road.road_type", "status": rt["status"], "reason_code": "ROAD_TYPE_UNRESOLVED"})
    elif rt["value"] not in rule_pack.road_types():
        failed.append({"field": "road.road_type", "actual": rt["value"], "reason_code": "RULE_PACK_NOT_APPLICABLE"})
    elif rt["value"] not in config["supported_road_types"]:
        failed.append({"field": "road.road_type", "actual": rt["value"], "reason_code": "ROAD_TYPE_NOT_SUPPORTED"})

    for key, label in (("centerline_status", "CENTERLINE"),):
        if road[key] != RESOLVED: unresolved.append({"field": f"road.{key}", "status": road[key], "reason_code": f"{label}_UNRESOLVED"})
    if road["road_edges"]["status"] != RESOLVED:
        unresolved.append({"field": "road.road_edges", "status": road["road_edges"]["status"],
                           "reason_code": f"ROAD_EDGES_{road['road_edges']['status']}"})
    if work["side"]["status"] != RESOLVED:
        unresolved.append({"field": "work.side", "status": work["side"]["status"], "reason_code": f"WORK_SIDE_{work['side']['status']}"})
    if not site_model["evidence"]["ai"]["available"]:
        unresolved.append({"field": "evidence.ai", "status": "UNAVAILABLE", "reason_code": "AI_OBSERVATION_UNAVAILABLE"})
    if site_model["imagery"]["quality"] == "POOR":
        unresolved.append({"field": "imagery.quality", "status": "POOR", "reason_code": "IMAGE_QUALITY_POOR"})
    for e in site_model.get("escalations") or []:  # agent escalations (e.g. CROSS_VIEW_MISMATCH, NO_POSITION_AFTER_CROP)
        if not any(u["reason_code"] == e["reason_code"] for u in unresolved):
            unresolved.append({"field": e["field"], "status": e["status"], "reason_code": e["reason_code"]})
    for c in site_model["critical_conflicts"]:
        code = c["field"].split(".")[-1].upper() + "_CONFLICT"
        if not any(u["reason_code"] == code for u in unresolved):
            unresolved.append({"field": c["field"], "status": "CONFLICT", "reason_code": code})

    # ---- TA-1 applicability (rule-pack section 03) ----
    sel = rule_pack.section("03_typical_application_selection")["selection_conditions"]
    ta_ok = (work["location"]["value"] == sel["work_location"] and work["location"]["status"] == RESOLVED and
             work["encroaches_traveled_way"]["value"] is sel["traveled_way_affected"] and
             work["requires_lane_closure"]["value"] is False)
    if not ta_ok and not failed and not unresolved:
        failed.append({"field": "typical_application", "reason_code": "TA1_NOT_APPLICABLE"})

    decision = UNSUPPORTED_POC if failed else REVIEW_REQUIRED if unresolved else SUPPORTED_AUTO
    reason_codes = sorted({x["reason_code"] for x in failed + unresolved})
    return {
        "decision": decision, "generate_draft": decision == SUPPORTED_AUTO,
        "reason_codes": reason_codes,
        "message": {SUPPORTED_AUTO: "Site matches the approved two-lane TA-1 POC scope.",
                    REVIEW_REQUIRED: REVIEW_MESSAGE, UNSUPPORTED_POC: UNSUPPORTED_MESSAGE}[decision],
        "failed_conditions": failed, "unresolved_fields": unresolved, "passed_conditions": sorted(passed),
        "selected_typical_application": rule_pack.selected_ta() if decision == SUPPORTED_AUTO else None,
        "detected_facts": {f: {"value": v, "status": s} for f, (v, s) in sorted(facts.items())},
        "intersection_analysis": ic_details,
        "site_model": {"id": site_model["site_model_id"], "version": site_model["version"]},
        "rule_pack": rule_pack.ref,
    }
