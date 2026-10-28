"""Independent validation. Never calls the rule engine or placement code; re-derives every check
from the PlanModel, SiteModel, approved rule pack and imagery metadata."""
import re
from tcp_planner.contracts import FT, RESOLVED, SUPPORTED_AUTO
from tcp_planner.geometry.local_frame import SiteFrame, signed_lateral

ALLOWED_OBJECT_TYPES = {"SIGN", "WORK_LOCATION"}
PROHIBITED_HINTS = ("TAPER", "CONE", "DRUM", "BARRICADE", "CHANNEL", "ARROW", "FLAGGER", "POLICE", "PEDESTRIAN",
                    "LANE_CLOSURE", "LANE_SHIFT", "END_ROAD_WORK", "G20-2", "BUFFER")
TRACE_KEYS = ("rule_pack_id", "rule_pack_version", "rule_pack_hash", "ta_id", "rule_id", "source_section", "source_table")
EXPECTED_SIDE = {"INCREASING_STATION": "RIGHT", "DECREASING_STATION": "LEFT"}


def _check(cid, ok, detail=None, maps_to=None):
    c = {"id": cid, "status": "PASS" if ok else "FAIL", "severity": "BLOCK"}
    if maps_to: c["rule_pack_validation_id"] = maps_to
    if detail: c["detail"] = detail
    return c


def _cmp(actual, expected):
    if actual is None: return False
    if isinstance(expected, list): return actual in expected
    m = re.match(r"^(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$", expected.strip()) if isinstance(expected, str) else None
    if m:
        if isinstance(actual, bool) or not isinstance(actual, (int, float)): return False
        v = float(m.group(2)); return {">=": actual >= v, "<=": actual <= v, ">": actual > v, "<": actual < v}[m.group(1)]
    return actual == expected


class RuleValidator:
    def validate(self, plan, site_model, eligibility, rule_pack):
        checks = []
        objs = plan["objects"]; signs = [o for o in objs if o["object_type"] == "SIGN"]
        road, work = site_model["road"], site_model["work"]

        # VAL-ELIGIBILITY: re-read the approved conditions directly against the SiteModel
        get = {"road.lane_count": road["lane_count"], "road.divided": road["divided"],
               "facility_type": road["facility_type"], "work.location": work["location"],
               "work.encroaches_traveled_way": work["encroaches_traveled_way"],
               "work.requires_lane_closure": work["requires_lane_closure"],
               "work.requires_alternating_one_lane_traffic": work["requires_alternating_one_lane_traffic"],
               "work.affects_pedestrian_route": work["affects_pedestrian_route"]}
        bad = []
        for c in rule_pack.section("01_eligibility_rules")["all_required"]:
            f = c["field"]
            if f == "road.traffic_direction":
                ok = road["two_way"]["status"] == RESOLVED and road["two_way"]["value"] is True and c["value"] == "TWO_WAY"
            elif f == "site.complex_intersection_conflict":
                ok = eligibility["detected_facts"].get(f, {}).get("value") is False and \
                     not eligibility["intersection_analysis"]["features_in_window"]
            elif f in get:
                ok = get[f]["status"] == RESOLVED and get[f]["value"] == c["value"]
            else:
                ok = False
            if not ok: bad.append(f)
        checks.append(_check("VAL-ELIGIBILITY", eligibility["decision"] == SUPPORTED_AUTO and not bad,
                             {"failed_fields": bad} if bad else None, "VAL-ELIGIBILITY"))

        sel = rule_pack.section("03_typical_application_selection")
        ta_ok = (plan["template"]["id"] == sel["selected_ta"] == "TA-1" and
                 work["location"]["value"] == sel["selection_conditions"]["work_location"] and
                 work["encroaches_traveled_way"]["value"] is sel["selection_conditions"]["traveled_way_affected"])
        checks.append(_check("VAL-TA", ta_ok, None, "VAL-TA"))

        # VAL-SIGN: one advance sign per approach unless a documented, confirmed option removes it
        rules = {r["id"]: r for r in rule_pack.section("05_sign_selection_rules")}
        facts = dict(work["ta1_option_facts"]); facts.update({"work." + k: v for k, v in work["ta1_option_facts"].items()})
        facts["work.location"] = work["location"]["value"]
        def confirmed(rid):
            r = rules.get(rid)
            if not r: return False
            if "when" in r: return all(_cmp(facts.get(k), v) for k, v in r["when"].items())
            return any(all(_cmp(facts.get(k), v) for k, v in c.items()) for c in r.get("when_any", []))
        removal_ok = any(confirmed(a["rule_id"]) and (a["action"].get("W20-1") == "MAY_BE_OMITTED" or
                         a["action"].get("all_signs_and_channelizing_devices") == "MAY_BE_ELIMINATED")
                         for a in plan["options_applied"])
        approaches = sorted(EXPECTED_SIDE)
        have = sorted(s["approach"] for s in signs)
        sign_ok = (have == approaches) or (not signs and removal_ok)
        checks.append(_check("VAL-SIGN", sign_ok, {"approaches_with_sign": have}, "VAL-SIGN"))

        catalog = rule_pack.section("04_sign_catalog")
        replaced_ok = lambda code: code == "W20-1" or any(
            confirmed(a["rule_id"]) and a["action"].get("with") == code for a in plan["options_applied"])
        cat_bad = [s["object_id"] for s in signs if s["sign_code"] not in catalog or not replaced_ok(s["sign_code"])
                   or s["legend"] != catalog.get(s["sign_code"], {}).get("name")]
        checks.append(_check("VAL-SIGN-CATALOG", not cat_bad, {"objects": cat_bad} if cat_bad else None, "VAL-SIGN"))

        # VAL-SPACING: recorded distance equals Table 6B-1 A for the resolved road type
        tbl = rule_pack.section("06_advance_warning_spacing_tables")
        row = next((x for x in tbl["values"] if x["road_type"] == road["road_type"]["value"]), None)
        spacing_bad = []
        for s in signs:
            p, g = s["placement"], s["generated_by"]
            if (row is None or g.get("source_table") != tbl["table"] or g.get("table_value_ft") != row["A"] or
                    p["longitudinal_distance_ft"] != row["A"] or
                    abs(abs(p["station_m"] - p["work_station_m"]) - row["A"] * FT) > 0.01):
                spacing_bad.append(s["object_id"])
        checks.append(_check("VAL-SPACING", not spacing_bad and row is not None,
                             {"objects": spacing_bad, "expected_ft": row and row["A"]}, "VAL-SPACING"))

        prohibited = [o["object_id"] for o in objs if o["object_type"] not in ALLOWED_OBJECT_TYPES or
                      any(h in (o["object_type"] + str(o.get("sign_code", ""))).upper() for h in PROHIBITED_HINTS)]
        checks.append(_check("VAL-PROHIBITED-OBJECTS", not prohibited, {"objects": prohibited} if prohibited else None))

        trace_bad = []
        for o in objs:
            g = o.get("generated_by") or {}
            if (any(k not in g for k in TRACE_KEYS) or g["rule_pack_id"] != rule_pack.id or
                    g["rule_pack_version"] != rule_pack.version or g["rule_pack_hash"] != rule_pack.hash or
                    g["ta_id"] != rule_pack.selected_ta() or not g["rule_id"] or not g["source_section"]):
                trace_bad.append(o.get("object_id"))
        checks.append(_check("VAL-TRACE", not trace_bad, {"objects": trace_bad} if trace_bad else None, "VAL-TRACE"))

        ped = work["affects_pedestrian_route"]
        checks.append(_check("VAL-PED", ped["status"] == RESOLVED and ped["value"] is False, None, "VAL-PED"))
        return {"status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL", "checks": checks}


class GeometryValidator:
    def validate(self, plan, site_model, config):
        frame = SiteFrame(site_model)
        meta = site_model["imagery"]["metadata"]
        half_x = meta["ground_extent_m"]["width"] / 2; half_y = meta["ground_extent_m"]["height"] / 2
        clear = config["placement"]["sign_feature_clearance_m"]
        checks = []; lane_bad, side_bad, extent_bad, analysed_bad, station_bad, conflict, ped_bad = ([] for _ in range(7))
        feats = site_model["features"]
        sidewalk_side = {f["side"] for f in feats["sidewalks"] if f["present"] is True}

        def inside_lane(pt, side_hint=None):
            d, s, lat = signed_lateral(frame.centerline, pt)
            side = "LEFT" if lat > 0 else "RIGHT"; half = frame.half_width(side)
            return half is None or abs(lat) <= half, side, s, d

        for o in plan["objects"]:
            p = o["placement"]
            pts = [frame.enu(p["latitude"], p["longitude"])]
            if o["object_type"] == "WORK_LOCATION":
                pts += [frame.enu(q["latitude"], q["longitude"]) for q in p.get("path", [])]
            for pt in pts:
                if abs(pt[0]) > half_x or abs(pt[1]) > half_y: extent_bad.append(o["object_id"])
                inside, side, s, d = inside_lane(pt)
                if inside: lane_bad.append(o["object_id"])
                if not (0.0 < s < frame.length): analysed_bad.append(o["object_id"])
            if o["object_type"] == "SIGN":
                _, side, s, _ = inside_lane(pts[0])
                if side != EXPECTED_SIDE[o["approach"]]: side_bad.append(o["object_id"])
                expect = o["generated_by"]["table_value_ft"] * FT
                if abs(abs(s - frame.work_station) - expect) > 1.0: station_bad.append(o["object_id"])
                for kind in ("driveways", "intersections", "crosswalks", "roundabouts", "ramps"):
                    for f in feats[kind]:
                        if f.get("station_m") is None or abs(f["station_m"] - s) <= clear:
                            conflict.append({"object": o["object_id"], "feature": kind, "source": f["source"],
                                             "station_m": f.get("station_m")})
                if side in sidewalk_side: ped_bad.append({"object": o["object_id"], "issue": "sidewalk on sign side"})
        w0 = frame.work_station
        for f in feats["crosswalks"]:
            if f.get("station_m") is None or abs(f["station_m"] - w0) <= clear:
                ped_bad.append({"object": "W1", "issue": "crosswalk near work"})

        checks.append(_check("GEO-TRAVELED-WAY", not lane_bad, {"objects": sorted(set(lane_bad))} if lane_bad else None, "VAL-LANE"))
        checks.append(_check("GEO-WORK-VEHICLE", True, {"note": "no work-vehicle object generated for TA-1 POC"}, "VAL-LANE"))
        checks.append(_check("GEO-SIGN-SIDE", not side_bad, {"objects": side_bad} if side_bad else None))
        checks.append(_check("GEO-ANALYZED-GEOMETRY", not analysed_bad, {"objects": sorted(set(analysed_bad))} if analysed_bad else None))
        checks.append(_check("GEO-STATION", not station_bad, {"objects": station_bad} if station_bad else None, "VAL-SPACING"))
        checks.append(_check("GEO-DRIVEWAY-INTERSECTION-CONFLICT", not conflict, {"conflicts": conflict} if conflict else None, "VAL-CONFLICT"))
        checks.append(_check("GEO-PEDESTRIAN-CONFLICT", not ped_bad, {"conflicts": ped_bad} if ped_bad else None, "VAL-PED"))
        checks.append(_check("GEO-IMAGE-EXTENT", not extent_bad, {"objects": sorted(set(extent_bad))} if extent_bad else None))
        return {"status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL", "checks": checks}
