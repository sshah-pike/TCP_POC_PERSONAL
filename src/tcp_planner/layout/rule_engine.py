"""Deterministic TA-1 rule execution.

Consumes only: SiteModel, the approved rule pack and the TA-1 template built from it.
Returns semantic plan objects with placement *requests* (no coordinates, no drawing).
Contains no regulatory values: every number and sign code is read from the rule pack.
"""
import re
from tcp_planner.contracts import RESOLVED, SUPPORTED_AUTO, RulePackError
from tcp_planner.rules.rule_pack_loader import SECTION_TITLES

APPROACHES = ("INCREASING_STATION", "DECREASING_STATION")  # both traffic streams of a two-way road


def generated_by(rule_pack, rule_id, section_key, table=None, extra=None):
    g = {"rule_pack_id": rule_pack.id, "rule_pack_version": rule_pack.version, "rule_pack_hash": rule_pack.hash,
         "ta_id": rule_pack.selected_ta(), "rule_id": rule_id,
         "source_section": f"{section_key} ({SECTION_TITLES[section_key]})", "source_table": table}
    if extra: g.update(extra)
    return g


# ---------- structured option conditions (section 05) ----------
def _compare(actual, expected):
    if actual is None: return False  # unknown never satisfies an option
    if isinstance(expected, list): return actual in expected
    if isinstance(expected, str):
        m = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+(?:\.\d+)?)$", expected.strip())
        if m:
            if isinstance(actual, bool) or not isinstance(actual, (int, float)): return False
            op, v = m.group(1), float(m.group(2))
            return {">=": actual >= v, "<=": actual <= v, ">": actual > v, "<": actual < v, "==": actual == v}[op]
    return actual == expected


def _option_facts(site_model):
    f = {"work." + k: v for k, v in site_model["work"]["ta1_option_facts"].items()}
    for k, v in site_model["work"]["ta1_option_facts"].items():
        f[k] = v  # top-level keys such as operation_type / vehicle_high_intensity_warning_lights
    loc = site_model["work"]["location"]
    if loc["status"] == RESOLVED: f["work.location"] = loc["value"]
    return f


def option_applies(rule, facts):
    if "when" in rule: return all(_compare(facts.get(k), v) for k, v in rule["when"].items())
    if "when_any" in rule: return any(all(_compare(facts.get(k), v) for k, v in c.items()) for c in rule["when_any"])
    return False


def evaluate_sign_options(site_model, rule_pack):
    """Return (eliminate_all, omit, replacement, applied, notes). Only positively confirmed conditions apply."""
    facts = _option_facts(site_model)
    eliminate_all = omit = False; replacement = None; applied = []; notes = []
    for rule in rule_pack.section("05_sign_selection_rules"):
        if not option_applies(rule, facts): continue
        act = rule["action"]
        if act.get("all_signs_and_channelizing_devices") == "MAY_BE_ELIMINATED": eliminate_all = True
        elif act.get("W20-1") == "MAY_BE_OMITTED": omit = True
        elif act.get("replace") == "W20-1" and act.get("with"): replacement = act["with"]
        elif rule.get("strength") == "STANDARD":
            notes.append({"rule_id": rule["id"], "note": "standard constraint recorded; no object change"})
            continue
        else:
            continue
        applied.append({"rule_id": rule["id"], "strength": rule.get("strength"), "action": act,
                        "conditions_confirmed": {k: facts.get(k) for k in (rule.get("when") or {})} or
                        [{k: facts.get(k) for k in c} for c in rule.get("when_any", [])]})
    return eliminate_all, omit, replacement, applied, notes


def execute(site_model, eligibility, rule_pack, template):
    if eligibility["decision"] != SUPPORTED_AUTO:
        raise RulePackError("RULES_NOT_ELIGIBLE", "rule execution requested for a non-supported site")
    if template["id"] != "TA-1" or template["id"] != rule_pack.selected_ta():
        raise RulePackError("RULE_PACK_TA_NOT_SUPPORTED", "only TA-1 is executable in this POC")
    if template["taper_active"] or template["channelizing_required"] or template["termination_sign_required"]:
        raise RulePackError("TEMPLATE_INCONSISTENT", "TA-1 template unexpectedly requires taper/devices/termination")

    road_type = site_model["road"]["road_type"]["value"]
    table, a_ft = rule_pack.spacing_value_ft(road_type, template["advance_sign_spacing_dimension"])
    eliminate_all, omit, replacement, applied, notes = evaluate_sign_options(site_model, rule_pack)

    objects = [{
        "object_id": "W1", "object_type": "WORK_LOCATION",
        "geometry_type": "LINESTRING_WITH_POINT" if site_model["project_geometry"]["work_path"] else "POINT",
        "dwt_layer": rule_pack.dwt_layer("work_area"), "dwt_block": rule_pack.dwt_block("WORK_LOCATION"),
        "placement_request": {"kind": "WORK_REFERENCE"},
        "generated_by": generated_by(rule_pack, "15_work_zone_geometry.areas.ACTIVITY", "15_work_zone_geometry"),
    }]
    if not (eliminate_all or omit):
        code = replacement or template["default_advance_sign"]
        sign = rule_pack.sign(code)
        rule_id = next((a["rule_id"] for a in applied if a["action"].get("replace")), f"12_sign_placement_rules.{code}")
        placement_rule = rule_pack.section("12_sign_placement_rules").get(template["default_advance_sign"])
        if placement_rule is None:
            raise RulePackError("RULE_PACK_RULE_MISSING", "no placement rule for advance sign")
        for i, approach in enumerate(APPROACHES, start=1):
            objects.append({
                "object_id": f"S{i}", "object_type": "SIGN", "sign_code": code, "legend": sign["name"],
                "sign_catalog": {k: sign[k] for k in ("category", "shape", "background_color", "legend_color") if k in sign},
                "approach": approach,
                "dwt_layer": rule_pack.dwt_layer("signs"), "dwt_block": rule_pack.dwt_block(code),
                "placement_request": {"kind": "ADVANCE_SIGN", "approach": approach, "longitudinal_distance_ft": a_ft,
                                      "lateral_position": placement_rule["lateral_position"]},
                "generated_by": generated_by(rule_pack, rule_id, "12_sign_placement_rules", table,
                                             {"spacing_section": "06_advance_warning_spacing_tables",
                                              "table_row": road_type, "table_dimension": "A", "table_value_ft": a_ft}),
            })
    return {
        "objects": objects,
        "options_applied": applied, "standard_notes": notes,
        "spacing": {"table": table, "road_type": road_type, "dimension": "A", "value_ft": a_ft},
        "not_generated": {
            "taper": "07_taper_formulas.active_for_selected_TA=false",
            "buffer": "08_buffer_tables.active_for_selected_TA=false",
            "channelizing_devices": "09_channelizing_device_rules.selected_TA.required=false",
            "termination_sign": "16_termination_rules.selected_TA.termination_sign_required=false",
            "lane_closure_flagger_police_arrow_panel_pedestrian": "outside TA-1 scope",
        },
    }
