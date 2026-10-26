"""Complete deterministic impact preview: machine vs current vs proposed effective site model, dependent facts,
eligibility, TA, unchanged validators, placement, plan outcome. No AI and no external calls."""
from tcp_poc import sme_overlay, sme_pipeline
from tcp_poc.models import content_hash, FT
from . import findings as F, run_context, ta_eval

RULE_STATUS = {"PASS": "COMPLIANT", "FAIL": "CONFLICT"}


def derive_for(ctx, site, revision=None):
    ev = site.get("evidence", {}).get("ai", {})
    if revision is not None and "_policy" not in revision:
        from tcp_poc.sme_policy import load_policy
        revision = dict(revision, _policy=load_policy())
    return sme_pipeline.derive(site, ctx["rule_pack"], run_context.config(), site["imagery"]["metadata"],
                               {"provider": ev.get("provider"), "model": ev.get("model")},
                               (ctx["evidence"]["map"].get("signature") or {}).get("provider"), revision)


def current_derivation(ctx):
    if "_current" not in ctx: ctx["_current"] = derive_for(ctx, ctx["site_model"], ctx.get("sme_revision_applied"))
    return ctx["_current"]


def proposed_site(ctx, decisions):
    """Exactly what a revision run computes: the overlay is always applied to the machine model (even if empty)."""
    return sme_overlay.apply(ctx["machine_site_model"], decisions, run_context.config())


def _fact_rows(ctx, machine, cur, new, decisions):
    direct = {d["field"] for d in decisions.get("facts") or []}
    rows = []
    for key, (label, typ, essential) in F.FACTS.items():
        if key == "site.complex_intersection_conflict":
            mv = (cur["machine_ic"]["value"], cur["machine_ic"]["status"], None, [], "MACHINE", None)
        else:
            mv = F.fact_value(machine, None, key)
        cv = F.fact_value(cur["site"], cur["eligibility"], key); nv = F.fact_value(new["site"], new["eligibility"], key)
        rows.append({"field": key, "label": label, "essential": essential,
                     "machine": {"value": mv[0], "status": mv[1], "confidence": mv[2], "source": mv[4]} if mv else None,
                     "current": {"value": cv[0], "status": cv[1], "source": cv[4]},
                     "proposed": {"value": nv[0], "status": nv[1], "source": nv[4]},
                     "kind": "DIRECT" if key in direct else ("DEPENDENT" if (nv[0], nv[1]) != (mv[0] if mv else None, mv[1] if mv else None) else "UNCHANGED"),
                     "changed_vs_current": (cv[0], cv[1], cv[4]) != (nv[0], nv[1], nv[4])})
    return rows


def _rules(cur, new):
    out = {}
    for tag, d in (("current", cur["derived"]), ("proposed", new["derived"])):
        el = d["eligibility"]
        for part in ("rule_validation", "geometry_validation"):
            for chk in ((d["validation"] or {}).get(part) or {}).get("checks", []):
                row = out.setdefault(chk["id"], {"check_id": chk["id"], "rule_id": chk.get("rule_pack_validation_id") or chk["id"]})
                row[tag] = chk["status"]; row[f"rule_status_{tag}"] = RULE_STATUS[chk["status"]]
                row[f"detail_{tag}"] = chk.get("detail")
        if d["validation"] is None:
            for row in out.values():
                row.setdefault(tag, "NOT_EVALUATED")
                row.setdefault(f"rule_status_{tag}", "REQUIRES_DIFFERENT_TA" if el["decision"] == "UNSUPPORTED_POC" else "UNRESOLVED")
    for row in out.values():
        for tag, d in (("current", cur["derived"]), ("proposed", new["derived"])):
            if tag not in row:
                row[tag] = "NOT_EVALUATED"
                row[f"rule_status_{tag}"] = "REQUIRES_DIFFERENT_TA" if d["eligibility"]["decision"] == "UNSUPPORTED_POC" else "UNRESOLVED"
    return sorted(out.values(), key=lambda r: r["check_id"])


def placements(plan):
    return {o["object_id"]: {"object_type": o["object_type"], "sign_code": o.get("sign_code"), "approach": o.get("approach"),
                             "station_m": o["placement"].get("station_m"), "latitude": o["placement"].get("latitude"),
                             "longitude": o["placement"].get("longitude"),
                             "lateral_offset_m": o["placement"].get("lateral_offset_from_centerline_m"),
                             "side": o["placement"].get("side_of_centerline"),
                             "distance_ft": o["placement"].get("longitudinal_distance_ft"), "sme": o.get("sme")}
            for o in (plan or {}).get("objects", [])}


def _placement_rows(cur_plan, new_plan):
    a, b = placements(cur_plan), placements(new_plan)
    rows = []
    for oid in sorted(set(a) | set(b)):
        ca, cb = a.get(oid), b.get(oid)
        moved = None
        if ca and cb and ca["station_m"] is not None and cb["station_m"] is not None: moved = round(cb["station_m"] - ca["station_m"], 3)
        rows.append({"object_id": oid, "current": ca, "proposed": cb, "station_change_m": moved,
                     "station_change_ft": None if moved is None else round(moved / FT, 1),
                     "change": "ADDED" if not ca else "REMOVED" if not cb else ("MOVED" if (moved or 0) != 0 or
                               (ca["latitude"], ca["longitude"]) != (cb["latitude"], cb["longitude"]) else "UNCHANGED")})
    return rows


def plan_outcome(derived, dispositions=None):
    el = derived["eligibility"]
    dispositions = dispositions or derived.get("dispositions")
    if derived["plan"] is None:
        return {"status": "BLOCKED", "reason": "TA_NOT_APPLICABLE" if el["decision"] == "UNSUPPORTED_POC" else "SITE_FACTS_UNRESOLVED",
                "reason_codes": el["reason_codes"]}
    failed = sme_pipeline.failed_checks(derived["validation"])
    if dispositions and dispositions.get("all_accepted"):
        return {"status": dispositions["plan_status"], "failed_checks": [c["id"] for c in failed],
                "active_exceptions": dispositions["active_exceptions"]}
    if not failed and not derived.get("ta_exception"): return {"status": "DRAFT_COMPLIANT", "failed_checks": []}
    return {"status": "BLOCKED", "reason": "VALIDATION_CONFLICT", "failed_checks": [c["id"] for c in failed]}


def compute(ctx, decisions, revision_extra=None):
    """Full impact of a proposed decision set (+ optional revision parts from later phases)."""
    from tcp_poc.eligibility import intersection_conflict
    cfg = run_context.config()
    machine = ctx["machine_site_model"]
    cur_d = current_derivation(ctx)
    new_site = proposed_site(ctx, decisions)
    revision = {"decisions": decisions, **(revision_extra or {})}
    new_d = derive_for(ctx, new_site, revision)
    mic = intersection_conflict(machine, ctx["rule_pack"], cfg)
    cur = {"site": ctx["site_model"], "eligibility": cur_d["eligibility"], "derived": cur_d, "machine_ic": {"value": mic[0], "status": mic[1]}}
    new = {"site": new_site, "eligibility": new_d["eligibility"], "derived": new_d}
    ta = ta_eval.evaluate(ctx["rule_pack"], cur_d["eligibility"], new_d["eligibility"], ctx["site_model"], new_site)
    disp = new_d.get("dispositions")
    outcome = plan_outcome(new_d)
    ov = new_site.get("sme_overlay") or {}
    return {
        "decisions": decisions, "decisions_sha256": content_hash(decisions),
        "machine_site_model_id": machine["site_model_id"], "current_site_model_id": ctx["site_model"]["site_model_id"],
        "proposed_site_model_id": new_site["site_model_id"],
        "facts": _fact_rows(ctx, machine, cur, new, decisions),
        "overlay_changes": ov.get("changes", []), "superseded_conflicts": ov.get("superseded_conflicts", []),
        "superseded_escalations": ov.get("superseded_escalations", []),
        "rejected_features": sorted((ov.get("rejected_features") or {}).keys()),
        "feature_decisions": new_site.get("sme_feature_decisions", []),
        "eligibility": {"current": {k: cur_d["eligibility"][k] for k in ("decision", "reason_codes")},
                        "proposed": {k: new_d["eligibility"][k] for k in ("decision", "reason_codes")}},
        "ta": ta, "rules": _rules(cur, new),
        "placement": _placement_rows(cur_d["plan"], new_d["plan"]),
        "plan_outcome": outcome, "dispositions": disp,
        "external_calls_expected": {"azure_maps": 0, "osm": 0, "foundry_vision": 0, "foundry_text": 0},
        "ai_calls_expected": 0,
        "_new_site": new_site, "_new_derived": new_d,
    }


def public(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}
