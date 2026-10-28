"""SME exceptions (plan-specific, this plan version only). Deterministic; AI can never request or authorize one.

RULE_CONFLICT       accept a FAILED unchanged validator check as an engineering exception (override_rule_conflict)
TA_NOT_APPLICABLE   generate the TA-1 draft although TA-1 does not apply (proceed_without_applicable_ta); never selects
                    another TA. Unresolved facts and non-overridable conditions can never be bypassed.
Every exception requires: policy action enabled, master switch on, SME role, full impact shown (final review hash),
explicit confirmation flag and a reason. Recorded as SELF_CONFIRMED_POC, independent_approval false.
"""
from tcp_planner.conflicts import sme_disposition as SD
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.tools import Tool
from . import decisions as D, preview, proposals

_C = {}


def register(c):
    _C["c"] = c
    c.tools.register(Tool("record_exception", record, permission="exception:confirm", mutates=True))


def c():
    return _C["c"]


def _proposed(ctx, cid):
    doc, _ = D.effective(ctx, cid)
    extra = proposals.revision_extra(ctx, cid)
    return preview.compute(ctx, doc, extra), extra


def record(tctx, ctx, cid, payload):
    ident = tctx.identity
    if payload.get("confirm_exception") is not True:
        raise AssistantError("EXCEPTION_NOT_CONFIRMED", "Explicit SME confirmation of the exception is required.", 400)
    reason = (payload.get("reason") or "").strip()[:500]
    typ = payload.get("type")
    p, extra = _proposed(ctx, cid)
    rules = {r["id"]: r for r in ctx["rule_pack"].section("18_validation_rules")}
    base = {"exception_id": new_id("exc"), "requested_by": ident.subject_id, "confirmed_by": ident.subject_id,
            "confirmed_by_roles": list(ident.roles), "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False,
            "confirmed_at": now_iso(), "scope": SD.SCOPE, "reason": reason, "rule_pack": ctx["rule_pack_ref"]}
    if typ == "RULE_CONFLICT":
        D.authorize(ident, "override_rule_conflict", reason)
        cid_ = payload.get("check_id")
        chk = next((c_ for part in ("rule_validation", "geometry_validation")
                    for c_ in ((p["_new_derived"]["validation"] or {}).get(part) or {}).get("checks", [])
                    if c_["id"] == cid_ and c_["status"] == "FAIL"), None)
        if chk is None:
            raise AssistantError("EXCEPTION_NOT_APPLICABLE", f"Validator {cid_} does not fail in the proposed revision.", 409)
        conds = SD._conditions(chk); pol = D.policy()
        hard = [x for x in conds if not pol.condition_overridable(x)]
        if hard:
            raise AssistantError("POLICY_NON_OVERRIDABLE", f"{cid_} is caused by a non-overridable condition: {', '.join(hard)}.",
                                 409, False, details={"conditions": hard})
        rid = chk.get("rule_pack_validation_id") or cid_
        cur = next((r for r in p["rules"] if r["check_id"] == cid_), {})
        ex = {**base, "type": "RULE_CONFLICT", "action": "override_rule_conflict", "check_id": cid_,
              "object_ids": SD._objects(chk) or None, "rule_id": rid, "rule_text": (rules.get(rid) or {}).get("check"),
              "rule_severity": (rules.get(rid) or {}).get("severity"), "validator_result": "FAIL", "rule_status": "CONFLICT",
              "current_validator_result": cur.get("current"), "proposed_validator_result": "FAIL", "detail": chk.get("detail"),
              "disposition_if_confirmed": SD.ACCEPTED, "plan_status_if_confirmed": "DRAFT_WITH_ENGINEERING_EXCEPTION",
              "engineering_impact": f"The plan will knowingly not satisfy {rid}: {(rules.get(rid) or {}).get('check')}. "
                                    "The rule result stays CONFLICT; the draft is marked DRAFT_WITH_ENGINEERING_EXCEPTION.",
              "summary": f"{cid_} accepted as SME exception"}
        key = f"EXCEPTION:RULE:{cid_}"
    elif typ == "TA_NOT_APPLICABLE":
        D.authorize(ident, "proceed_without_applicable_ta", reason)
        el = p["_new_derived"]["eligibility"]
        if el["decision"] == "SUPPORTED_AUTO":
            raise AssistantError("EXCEPTION_NOT_APPLICABLE", "TA-1 applies to the proposed revision; no TA exception is needed.", 409)
        if el.get("unresolved_fields"):
            raise AssistantError("ESSENTIAL_FACT_UNRESOLVED", "Unresolved site facts cannot be bypassed by an exception: "
                                 + ", ".join(u["reason_code"] for u in el["unresolved_fields"]), 409, False)
        codes = sorted({f["reason_code"] for f in el["failed_conditions"]})
        if set(codes) & SD.TA_NON_OVERRIDABLE:
            raise AssistantError("POLICY_NON_OVERRIDABLE", "The approved rule pack has no applicable spacing/scope for this site: "
                                 + ", ".join(sorted(set(codes) & SD.TA_NON_OVERRIDABLE)), 409, False)
        ex = {**base, "type": "TA_NOT_APPLICABLE", "action": "proceed_without_applicable_ta", "reason_codes": codes,
              "failed_conditions": el["failed_conditions"], "current_ta": p["ta"]["current"]["ta_id"],
              "candidate_tas": p["ta"]["approved_candidates_found"],
              "message": "Current TA is no longer applicable. No alternative TA is available in the current approved rule pack. "
                         "The TA-1 layout is generated as a plan-specific engineering exception; no other TA is selected.",
              "engineering_impact": "TA-1 devices and spacing are applied to a site that does not meet TA-1 conditions ("
                                    + ", ".join(codes) + "). Validator checks VAL-ELIGIBILITY / VAL-TA stay CONFLICT.",
              "summary": "TA-1 generated although not applicable"}
        key = "EXCEPTION:TA"
    else:
        raise AssistantError("BAD_REQUEST", "Exception type must be RULE_CONFLICT or TA_NOT_APPLICABLE.")
    c().store.append_event("conversations", cid, {"type": "stage", "key": key, "decision": {"exception": ex,
                           "action": ex["type"], "decision_id": ex["exception_id"], "finding_id": payload.get("finding_id"),
                           "reason": reason, "decided_by": ident.subject_id, "decided_at": ex["confirmed_at"]}}, durable=True)
    c().audit.write("EXCEPTION_STAGED", ident, consequential=True, conversation_id=cid, exception_id=ex["exception_id"],
                    exception_type=ex["type"], check_id=ex.get("check_id"), reason_codes=ex.get("reason_codes"),
                    approval_mode="SELF_CONFIRMED_POC", independent_approval=False, override_decision="REQUESTED_AND_SELF_CONFIRMED")
    return {"key": key, "exception": ex, "_tool_meta": {"affected_entities": [ex.get("check_id") or "TA"]}}
