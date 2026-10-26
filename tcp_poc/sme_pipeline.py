"""Post-fusion derivation shared by the SME assistant preview and revision runs.

Calls exactly the pipeline building blocks app.run_pipeline uses after fusion, in the same order: eligibility ->
TA-1 rules -> placement -> (SME placement adjustments / proposed objects, revision only) -> plan -> the UNCHANGED
RuleValidator and GeometryValidator -> (SME dispositions, revision only). Validators are never altered: a FAIL stays a
FAIL; acceptance as an SME exception is a separate disposition (tcp_poc/sme_disposition.py).
"""
from .models import SUPPORTED_AUTO, content_hash, deep_copy
from .eligibility import evaluate as evaluate_eligibility
from .rule_engine import execute as execute_rules
from .geometry import place_objects
from .validators import RuleValidator, GeometryValidator


class _Named:
    def __init__(self, name): self.name = name


def derive(site, pack, config, imagery_meta, ai_info=None, map_name=None, revision=None):
    """-> {"eligibility", "plan" (or None), "validation" (or None), "issues", "rules_out", "ta_exception"}."""
    from . import app
    elig = evaluate_eligibility(site, pack, config)
    out = {"eligibility": elig, "plan": None, "validation": None, "issues": [], "rules_out": None, "ta_exception": None}
    elig_for_rules = elig
    if elig["decision"] != SUPPORTED_AUTO:
        from . import sme_disposition
        ta_exc = sme_disposition.ta_exception(elig, revision, site, pack, config) if revision else None
        if not ta_exc: return out
        out["ta_exception"] = ta_exc
        elig_for_rules = dict(elig, decision=SUPPORTED_AUTO, sme_ta_exception=ta_exc["exception_id"])
    template = pack.ta1_template()
    rules_out = execute_rules(site, elig_for_rules, pack, template)
    placed, issues = place_objects(rules_out["objects"], site, config)
    if revision and (revision.get("placement_adjustments") or revision.get("proposed_objects") or revision.get("removed_objects")):
        from . import plan_adjustments
        placed, more = plan_adjustments.apply(placed, revision, site, config, pack)
        issues = issues + more
    plan = app._build_plan(site, pack, template, rules_out, placed, imagery_meta,
                           ai_info or {"provider": None, "model": None}, _Named(map_name))
    rv = RuleValidator().validate(plan, site, elig, pack)       # real eligibility: exceptions never turn FAIL into PASS
    gv = GeometryValidator().validate(plan, site, config)
    if issues:
        gv["checks"].append({"id": "GEO-PLACEMENT", "status": "FAIL", "severity": "BLOCK", "detail": issues})
        gv["status"] = "FAIL"
    validation = {"rule_validation": rv, "geometry_validation": gv, "plan_ref": None}
    plan["validation"] = {"rule": rv["status"], "geometry": gv["status"]}
    out.update(plan=plan, validation=validation, issues=issues, rules_out=rules_out)
    if revision is not None:
        out["dispositions"] = apply_revision(plan, validation, revision, elig, out["ta_exception"])
    return out


def finalize_plan(plan, validation):
    """Hash + id exactly as app.run_pipeline does for an exported plan."""
    plan = deep_copy(plan)
    plan["plan_hash"] = content_hash(plan, drop={"plan_hash", "plan_id"})
    plan["plan_id"] = "TCP-" + plan["plan_hash"][:16].upper()
    validation = dict(validation, plan_ref={"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]})
    return plan, validation


def failed_checks(validation):
    out = []
    for part in ("rule_validation", "geometry_validation"):
        for c in (validation or {}).get(part, {}).get("checks", []):
            if c["status"] == "FAIL": out.append(c)
    return out


def apply_revision(plan, validation, revision, eligibility, ta_exc):
    """Revision runs only: dispositions (validators untouched) + lineage + plan status, before the plan hash."""
    from . import sme_disposition, sme_revision
    disp = sme_disposition.evaluate(validation, revision, eligibility, ta_exc)
    plan["revision"] = sme_revision.plan_fields(revision)
    plan["version"] = revision.get("version_number") or plan["version"]
    plan["sme_dispositions"] = sme_disposition.plan_block(disp, revision)
    if disp["all_accepted"]:
        plan["status"] = disp["plan_status"]
        if disp["plan_status"] == sme_revision.PLAN_STATUS_EXCEPTION:
            plan["disclaimer"] = plan["disclaimer"] + " - DRAFT WITH SME ENGINEERING EXCEPTION (NOT COMPLIANT, NOT INDEPENDENTLY APPROVED)"
    return disp
