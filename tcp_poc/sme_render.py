"""Text for SME exceptions shown on generated artifacts (debug plan, TCP sheet). Empty for normal plans."""
PURPLE = "#7b2cbf"


def exception_lines(plan, limit=8):
    d = plan.get("sme_dispositions") or {}
    exc = d.get("active_exceptions") or []
    if not exc and plan.get("status") != "DRAFT_WITH_ENGINEERING_EXCEPTION": return []
    rev = plan.get("revision") or {}
    lines = [f"{plan.get('status')} - SME REVISION {rev.get('plan_version_id')} (CHANGE SET {rev.get('change_set_id')})",
             "SME ENGINEERING EXCEPTION(S): RULE STATUS REMAINS CONFLICT - NOT COMPLIANT - SELF-CONFIRMED (POC), "
             "NOT INDEPENDENTLY APPROVED - THIS PLAN VERSION ONLY"]
    for e in exc[:limit]:
        tgt = e.get("check_id") or ",".join(e.get("reason_codes") or []) or e.get("type")
        objs = f" [{', '.join(e.get('object_ids') or [])}]" if e.get("object_ids") else ""
        lines.append(f"* {e.get('exception_id')} {e.get('type')}: {tgt}{objs} - confirmed by {e.get('confirmed_by')}: "
                     f"{(e.get('reason') or '')[:80]}")
    if len(exc) > limit: lines.append(f"* ... {len(exc) - limit} more (see plan.json sme_dispositions)")
    return lines


def object_tag(o):
    s = o.get("sme") or {}
    if not s: return None
    return s.get("label") or ("SME " + (s.get("approval_class") or s.get("change") or "EXCEPTION"))
