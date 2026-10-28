"""TA applicability from approved structured TA data only (rule-pack section 03 + eligibility). Never from a model.

Multi-TA ready: candidates are read from 03_typical_application_selection (selected_ta + other_tas_allowed and, when a
future pack provides it, a structured "typical_applications" catalog with selection_conditions). Today the approved
pack contains TA-1 only, so no alternative can ever be reported as selected.
"""
NO_ALTERNATIVE = "No alternative TA is available in the current approved rule pack."
STAGE_FOR_TA = "eligibility"  # TA/rule selection happens in the eligibility stage


def catalog(pack):
    sel = pack.section("03_typical_application_selection")
    tas = [{"ta_id": sel["selected_ta"], "title": sel.get("title"), "figure": sel.get("figure"),
            "selection_conditions": sel["selection_conditions"], "approved": True}]
    for t in sel.get("typical_applications") or []:  # future structured catalog (not present in pack 1.0.0)
        if isinstance(t, dict) and t.get("ta_id") and t.get("selection_conditions") and t["ta_id"] != sel["selected_ta"]:
            tas.append({**t, "approved": True})
    for tid in sel.get("other_tas_allowed") or []:
        if not any(t["ta_id"] == tid for t in tas):
            tas.append({"ta_id": tid, "approved": True, "selection_conditions": None,
                        "note": "listed as allowed but no structured selection conditions in the approved pack"})
    return tas


def _conditions(ta, site):
    if not ta.get("selection_conditions") or site is None: return None
    sc = ta["selection_conditions"]; w = site["work"]
    actual = {"work_location": w["location"]["value"], "traveled_way_affected": w["encroaches_traveled_way"]["value"]}
    return [{"condition": k, "required": v, "actual": actual.get(k), "status": w["location"]["status"] if k == "work_location"
             else w["encroaches_traveled_way"]["status"], "met": actual.get(k) == v} for k, v in sc.items()]


def evaluate(pack, elig_cur, elig_new, site_cur, site_new):
    tas = catalog(pack); cur_ta = tas[0]
    cur_ok = (elig_cur or {}).get("decision") == "SUPPORTED_AUTO"
    new_ok = (elig_new or {}).get("decision") == "SUPPORTED_AUTO"
    cf = (elig_cur or {}).get("detected_facts") or {}; nf = (elig_new or {}).get("detected_facts") or {}
    changed = [{"fact": k, "current": cf.get(k), "proposed": nf.get(k)} for k in sorted(set(cf) | set(nf)) if cf.get(k) != nf.get(k)]
    cands = []
    for t in tas[1:]:
        conds = _conditions(t, site_new)
        cands.append({"ta_id": t["ta_id"], "evaluable": conds is not None, "conditions": conds,
                      "applies": bool(conds) and all(c["met"] for c in conds)})
    decision = (elig_new or {}).get("decision")
    if new_ok: state, msg = "CURRENT_TA_APPLICABLE", f"{cur_ta['ta_id']} remains applicable."
    elif decision == "UNSUPPORTED_POC":
        state, msg = "CURRENT_TA_NOT_APPLICABLE", f"Current TA is no longer applicable. {NO_ALTERNATIVE}" if not any(c["applies"] for c in cands) else "Current TA is no longer applicable."
    else: state, msg = "TA_APPLICABILITY_UNRESOLVED", "TA applicability cannot be decided until the unresolved site facts are resolved."
    return {"current": {"ta_id": cur_ta["ta_id"], "title": cur_ta.get("title"), "figure": cur_ta.get("figure"),
                        "matching_conditions": _conditions(cur_ta, site_cur), "applicable": cur_ok,
                        "classification": (elig_cur or {}).get("decision"), "rule_pack": pack.ref},
            "proposed": {"applicable": new_ok, "state": state, "message": msg, "classification": decision,
                         "matching_conditions": _conditions(cur_ta, site_new), "reason_codes": (elig_new or {}).get("reason_codes"),
                         "failed_conditions": (elig_new or {}).get("failed_conditions"),
                         "unresolved_fields": (elig_new or {}).get("unresolved_fields")},
            "changed_conditions": changed, "candidate_tas": cands,
            "approved_candidates_found": [c["ta_id"] for c in cands if c["applies"]],
            "ta_changed": cur_ok != new_ok,
            "device_and_rule_impact": None if new_ok else "TA-1 devices and rules no longer apply; no approved replacement.",
            "required_restart_stage": STAGE_FOR_TA if cur_ok != new_ok else None,
            "selection_source": "rule pack section 03 (approved structured data); never model knowledge"}
