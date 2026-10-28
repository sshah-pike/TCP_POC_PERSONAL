"""SME exception / disposition layer, separate from the unchanged validators.

    unchanged validator -> PASS / FAIL -> this module -> BLOCKED | ACCEPTED_WITH_SME_OVERRIDE -> plan status

A FAIL is never turned into PASS: the rule status stays CONFLICT and validation_results.json still records FAIL.
A failed check is accepted only when the revision carries a matching, SME-confirmed exception whose policy action is
enabled for the confirming role, the policy master switch is on, and the failure is not a non-overridable condition.
"""
from tcp_planner.contracts import SUPPORTED_AUTO

ACCEPTED = "ACCEPTED_WITH_SME_OVERRIDE"
BLOCKED = "BLOCKED"
SCOPE = "THIS_PLAN_VERSION_ONLY"
# failed checks / placement issues that map to policy conditions
CHECK_CONDITION = {"GEO-ANALYZED-GEOMETRY": "OUTSIDE_EVIDENCE_COVERAGE", "GEO-IMAGE-EXTENT": "OUTSIDE_EVIDENCE_COVERAGE"}
ISSUE_CONDITION = {"PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY": "OUTSIDE_EVIDENCE_COVERAGE", "ROAD_EDGE_UNRESOLVED": "NO_USABLE_GEOMETRY",
                   "PLACEMENT_NOT_CALCULABLE": "CHANGE_NOT_CALCULABLE"}
TA_NON_OVERRIDABLE = {"RULE_PACK_NOT_APPLICABLE", "ROAD_TYPE_NOT_SUPPORTED", "MULTIPLE_WORK_LOCATIONS"}
TA_COVERED_CHECKS = {"VAL-ELIGIBILITY", "VAL-TA"}


def _policy(revision):
    return revision.get("_policy")


def _allowed(revision, ex):
    pol = _policy(revision)
    if pol is None: return False, "SME action policy not verified"
    ok, why = pol.allowed(ex.get("action"), ex.get("confirmed_by_roles") or [])
    if not ok: return False, why
    if pol.reason_required(ex.get("action")) and not (ex.get("reason") or "").strip(): return False, "exception reason missing"
    if ex.get("approval_mode") != "SELF_CONFIRMED_POC" or not ex.get("confirmed_by"): return False, "exception not confirmed"
    return True, None


def _objects(check):
    d = check.get("detail") or {}
    if isinstance(d, list):  # GEO-PLACEMENT: list of placement issues
        return sorted({i.get("object") for i in d if isinstance(i, dict) and i.get("object")})
    objs = set(d.get("objects") or []) | {c.get("object") for c in d.get("conflicts") or [] if isinstance(c, dict)}
    return sorted(o for o in objs if o)


def _conditions(check):
    conds = set()
    if check["id"] in CHECK_CONDITION: conds.add(CHECK_CONDITION[check["id"]])
    if check["id"] == "GEO-PLACEMENT":
        for i in check.get("detail") or []:
            if isinstance(i, dict) and i.get("code") in ISSUE_CONDITION: conds.add(ISSUE_CONDITION[i["code"]])
    return sorted(conds)


def ta_exception(eligibility, revision, site, pack, config):
    """The confirmed TA exception allowing TA-1 generation although TA-1 does not apply, or None (fail closed)."""
    if not revision or eligibility["decision"] == SUPPORTED_AUTO: return None
    ex = next((e for e in revision.get("exceptions") or [] if e.get("type") == "TA_NOT_APPLICABLE"), None)
    if ex is None or eligibility.get("unresolved_fields"): return None   # unresolved facts are never bypassed
    codes = sorted({c["reason_code"] for c in eligibility.get("failed_conditions") or []})
    if not codes or set(codes) & TA_NON_OVERRIDABLE or codes != sorted(ex.get("reason_codes") or []): return None
    pol = _policy(revision)
    if pol is None or not pol.exceptions_enabled: return None
    ok, _ = _allowed(revision, ex)
    return ex if ok else None


def evaluate(validation, revision, eligibility, ta_exc=None):
    """-> {"dispositions": [...], "all_accepted", "active_exceptions", "plan_status"}."""
    failed = [c for part in ("rule_validation", "geometry_validation") for c in (validation or {}).get(part, {}).get("checks", [])
              if c["status"] == "FAIL"]
    pol = _policy(revision)
    exceptions = [e for e in (revision or {}).get("exceptions") or [] if e.get("type") != "TA_NOT_APPLICABLE"]
    out, active = [], set()
    for c in failed:
        objs = _objects(c); conds = _conditions(c)
        row = {"check_id": c["id"], "rule_pack_validation_id": c.get("rule_pack_validation_id"), "validator_result": "FAIL",
               "rule_status": "CONFLICT", "objects": objs, "disposition": BLOCKED, "exception_id": None, "reason": None}
        hard = [x for x in conds if pol is None or not pol.condition_overridable(x)]
        if hard:
            row["reason"] = f"non-overridable condition: {', '.join(hard)}"; out.append(row); continue
        if ta_exc and c["id"] in TA_COVERED_CHECKS:
            row.update(disposition=ACCEPTED, exception_id=ta_exc["exception_id"], scope=SCOPE); active.add(ta_exc["exception_id"])
            out.append(row); continue
        covered, used = set(), []
        for e in exceptions:
            if e.get("check_id") != c["id"]: continue
            ok, why = _allowed(revision, e)
            if not ok or (pol is not None and not pol.exceptions_enabled):
                row["reason"] = why or "SME exceptions disabled"; continue
            if e.get("object_ids") is None: covered |= set(objs) | {"*"}; used.append(e["exception_id"]); continue
            if set(e["object_ids"]) & set(objs): covered |= set(e["object_ids"]); used.append(e["exception_id"])
        match = used and ("*" in covered or set(objs) <= covered)
        if match:  # every object of the failed check is covered by confirmed exceptions
            row.update(disposition=ACCEPTED, exception_id=used[0] if len(used) == 1 else used, scope=SCOPE); active.update(used)
        elif not row["reason"]:
            row["reason"] = "no SME exception confirmed for this conflict"
        out.append(row)
    if ta_exc: active.add(ta_exc["exception_id"])
    all_ok = all(r["disposition"] == ACCEPTED for r in out)
    return {"dispositions": out, "all_accepted": all_ok, "active_exceptions": sorted(active),
            "plan_status": None if not all_ok else ("DRAFT_WITH_ENGINEERING_EXCEPTION" if active else "DRAFT_COMPLIANT"),
            "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False}


def plan_block(disp, revision):
    """Exceptions recorded inside plan.json (rendered on the debug plan and the sheet)."""
    ids = set(disp["active_exceptions"])
    exc = [{k: e.get(k) for k in ("exception_id", "type", "action", "check_id", "object_ids", "reason_codes", "reason",
                                  "requested_by", "confirmed_by", "confirmed_at", "approval_mode", "independent_approval",
                                  "scope", "summary")}
           for e in (revision or {}).get("exceptions") or [] if e.get("exception_id") in ids]
    return {"plan_status": disp["plan_status"], "dispositions": disp["dispositions"], "active_exceptions": exc,
            "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False,
            "note": "Validator results are unchanged (FAIL = rule CONFLICT). Accepted only as plan-specific SME engineering "
                    "exceptions for this plan version; not independently approved; not compliant."}
