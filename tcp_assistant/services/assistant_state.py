"""Floating-assistant support (read models only; no SME business logic is duplicated here).

context      run / conversation / site-evidence / plan-version identity + context_hash; every mutating request may carry
             it and is rejected when stale (STALE_CONTEXT) or for another run (CROSS_RUN_REJECTED).
attention    user-facing categories derived from findings, the staged change set and version status:
             Blocking issue | Pending review | Warning | Information | Completed. Blocking items drive auto-open.
run summary  for the run open in RunView WITHOUT creating a conversation.
ui state     acknowledged blocking items (manual close suppression), persisted as conversation events.
draft QA     deterministic answers about the active draft only (no model call).
"""
import re

from tcp_planner.contracts import canonical_json, sha256_hex
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from . import findings as F, run_context, versions as V

CATEGORY = {"BLOCKING": "Blocking issue", "PENDING": "Pending review", "WARNING": "Warning", "INFO": "Information",
            "DONE": "Completed"}
_C = {}


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


# ---------------------------------------------------------------- context
def context_of(conv, ctx):
    lk = conv["lineage_key"]; se = V.se_head(lk); pv = V.pv_head(lk)
    base = {"conversation_id": conv["conversation_id"], "base_run_id": conv["run_id"], "run_id": ctx["run_id"],
            "site_evidence_version": (se or {}).get("site_evidence_version") or f"machine:{ctx['machine_site_model']['site_model_id']}",
            "plan_version": (pv or {}).get("plan_version_id") or ("baseline" if ctx.get("plan") else None)}
    return {**base, "context_hash": sha256_hex(canonical_json(base))}


def conversation_runs(conv):
    runs = {conv["run_id"]}
    for ra in c().store.list("resume-attempts"):
        if ra.get("conversation_id") == conv["conversation_id"] and ra.get("run_id"): runs.add(ra["run_id"])
    return runs


def check_context(payload, conv, ctx):
    sent = (payload or {}).get("context")
    if not sent: return None
    if not isinstance(sent, dict): raise AssistantError("BAD_REQUEST", "context must be an object.")
    cur = context_of(conv, ctx)
    if sent.get("conversation_id") != conv["conversation_id"]:
        raise AssistantError("CONVERSATION_MISMATCH", "This request belongs to a different review session.", 409, False)
    if sent.get("run_id") != cur["run_id"]:
        if sent.get("run_id") not in conversation_runs(conv):
            raise AssistantError("CROSS_RUN_REJECTED", "This request refers to a different run than the active review.", 409, False,
                                 details={"active_run_id": cur["run_id"], "sent_run_id": sent.get("run_id")})
        raise AssistantError("STALE_CONTEXT", "The review moved to a newer run/version. Reload and review again.", 409,
                             details={"current": cur})
    for k in ("site_evidence_version", "plan_version", "context_hash"):
        if sent.get(k) != cur[k]:
            raise AssistantError("STALE_CONTEXT", f"The {k.replace('_', ' ')} changed since this view was loaded. Reload and review again.",
                                 409, details={"current": cur, "field": k})
    return cur


# ---------------------------------------------------------------- attention / categories
def category(f):
    if f["state"] == F.SME: return "DONE"
    if f["requires_review"]: return "BLOCKING" if f["severity"] == "BLOCKING" else "PENDING"
    return "WARNING" if f["severity"] == "WARNING" else "INFO"


def attention(fnd, staged=None, preview=None, review_blocking=None, versions_status=None):
    items = []
    for f in fnd:
        cat = category(f)
        items.append({"id": f["finding_id"], "kind": "FINDING", "category": cat, "label": CATEGORY[cat], "title": f["label"],
                      "message": f.get("reason") or f.get("reason_code"), "finding_id": f["finding_id"], "severity": f["severity"],
                      "section": "SITE" if f["category"] in ("SITE_FACT", "FEATURE", "SERVICE") else "CHANGE"})
    if staged:
        out = (preview or {}).get("plan_outcome") or {}
        if out.get("status") == "BLOCKED":
            fid = "DECISION:" + sha256_hex(canonical_json(sorted(out.get("failed_checks") or out.get("reason_codes") or [])))[:10]
            items.append({"id": fid, "kind": "EXCEPTION_DECISION", "category": "BLOCKING", "label": CATEGORY["BLOCKING"],
                          "title": "Staged change is blocked",
                          "message": "Resolve or accept as SME exception: " + ", ".join(out.get("failed_checks") or out.get("reason_codes") or []),
                          "section": "CHANGE", "checks": out.get("failed_checks") or []})
        else:
            items.append({"id": "CONFIRM:" + sha256_hex(canonical_json(sorted(staged)))[:10], "kind": "CONFIRMATION_REQUIRED",
                          "category": "BLOCKING", "label": "Decision required", "title": "Staged change awaits final review",
                          "message": f"{len(staged)} staged change(s). Open the full change review to confirm or cancel.",
                          "section": "CHANGE"})
    for pv_id, st in (versions_status or {}).items():
        if st == "DRAFT_GENERATION_FAILED":
            items.append({"id": f"RESUME:{pv_id}", "kind": "RESUME_DECISION", "category": "BLOCKING", "label": CATEGORY["BLOCKING"],
                          "title": f"Regeneration of {pv_id} failed", "message": "Retry regeneration or edit the request.",
                          "section": "CHANGE", "plan_version_id": pv_id})
        elif st == "REGENERATING":
            items.append({"id": f"RUN:{pv_id}", "kind": "PIPELINE_RUNNING", "category": "INFO", "label": "Running",
                          "title": f"Regenerating {pv_id}", "message": "Strict-replay pipeline run in progress.", "section": "CHANGE"})
    counts = {k: sum(1 for i in items if i["category"] == k) for k in CATEGORY}
    return {"items": items, "counts": counts, "blocking_ids": sorted(i["id"] for i in items if i["category"] == "BLOCKING"),
            "running": any(i["kind"] == "PIPELINE_RUNNING" for i in items)}


def run_summary(ident, run_id):
    """Launcher data for the run open in RunView. Never creates a conversation."""
    from tcp_planner.storage import run_store as store
    st = store.build_state(run_id, with_lineage=False, live_ids=_live())
    if st is None: raise AssistantError("NOT_FOUND", "Run not found.", 404)
    convs = conversations_for_run(ident, run_id)
    base = {"run_id": run_id, "pipeline_status": st["state"], "decision": st.get("decision"), "conversations": convs,
            "latest_conversation_id": convs[0]["conversation_id"] if convs else None}
    if st["state"] == "RUNNING":
        return {**base, "eligible": None, "attention": {"items": [], "counts": {k: 0 for k in CATEGORY}, "blocking_ids": [],
                                                         "running": True}}
    ctx, reasons = run_context.eligibility(run_id)
    if ctx is None: return {**base, "eligible": False, "reasons": reasons, "attention": None}
    fnd = F.derive(ctx, run_context.config())
    return {**base, "eligible": True, "attention": attention(fnd)}


def conversations_for_run(ident, run_id):
    out = []
    for conv in c().store.list("conversations"):
        if conv["created_by"].get("subject_id") != ident.subject_id and "AUDITOR" not in ident.roles and "ADMIN" not in ident.roles:
            continue
        from .conversations import archived
        if run_id in conversation_runs(conv) and not archived(conv["conversation_id"]):
            out.append({k: conv[k] for k in ("conversation_id", "run_id", "created_at", "lineage_key")})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def _live():
    import sys
    srv = sys.modules.get("tcp_planner.web_api.server")
    try: return srv.live_ids() if srv else set()
    except Exception: return set()


# ---------------------------------------------------------------- ui state
def ui_state(cid):
    st = {"acknowledged_blocking": [], "updated_at": None}
    for e in c().store.events("conversations", cid):
        if e.get("type") == "ui_state": st = {"acknowledged_blocking": e.get("acknowledged_blocking", []), "updated_at": e["at"]}
    return st


def set_ui_state(cid, acknowledged):
    ack = sorted({str(x)[:80] for x in (acknowledged or [])})[:200]
    c().store.append_event("conversations", cid, {"type": "ui_state", "acknowledged_blocking": ack, "at": now_iso()})
    return ui_state(cid)


# ---------------------------------------------------------------- deterministic draft QA (active run only)
QUESTIONS = {
    "WHY_BLOCKING": "Why is this finding blocking?", "WHAT_RERUNS": "What step will rerun?",
    "AZURE_CALLED": "Will Azure Maps be called?", "ARTIFACTS_REUSED": "What artifacts are reused?",
    "VALIDATOR_RESULT": "What is the validator result?", "VERSION_DIFF": "What changed between versions?",
    "TA_STATUS": "Is TA-1 still applicable?",
}
_MATCH = [("AZURE_CALLED", r"\b(azure|map(s)?|imagery)\b.*\b(call|called|request|fetch|used)\b|\b(call|calls)\b.*\bazure\b"),
          ("WHAT_RERUNS", r"\b(rerun|re-run|resume|which steps?|what steps?|restart)\b"),
          ("ARTIFACTS_REUSED", r"\b(artifacts?|reuse[ds]?|reusing|evidence files?)\b"),
          ("VALIDATOR_RESULT", r"\b(validator|validation|rule results?|checks?)\b"),
          ("VERSION_DIFF", r"\b(changed between|difference|diff|what changed|compare)\b.*\bversion|\bversion\b.*\b(changed|differ)"),
          ("TA_STATUS", r"\b(ta-?1|typical application|ta applicab)"),
          ("WHY_BLOCKING", r"\bwhy\b.*\b(block|blocking|blocked|stuck|cannot proceed|can't proceed)\b")]


def match_question(text):
    t = text.lower().strip()
    if not (t.endswith("?") or re.match(r"^(why|what|which|will|is|are|does|do|how|can)\b", t)): return None
    for qid, pat in _MATCH:
        if re.search(pat, t): return qid
    return None


def answer(ident, cid, ctx, qid, target_id=None):
    from . import decisions as D, preview as P, proposals as PR
    fnd = F.derive(ctx, run_context.config())
    staged = D.staged(cid)
    if qid == "WHY_BLOCKING":
        bl = [f for f in fnd if f["requires_review"] and f["severity"] == "BLOCKING" and (not target_id or target_id in (f["finding_id"], f["subject"]))]
        lines = [f"{f['label']} ({f['finding_id']}): {f.get('reason') or f.get('reason_code') or f['state']}"
                 + (f"; rule {f['rule_id']}: {f.get('rule_text')}" if f.get("rule_id") else "") for f in bl]
        if staged:
            doc, _ = D.effective(ctx, cid); p = P.compute(ctx, doc, PR.revision_extra(ctx, cid))
            if p["plan_outcome"]["status"] == "BLOCKED":
                lines.append("Staged change blocked by validator result(s) "
                             + ", ".join(p["plan_outcome"].get("failed_checks") or p["plan_outcome"].get("reason_codes") or [])
                             + ". Rule status stays CONFLICT unless resolved; an SME exception may accept it for this plan version only.")
        return "\n".join(lines) or "Nothing is blocking the active draft."
    if qid in ("WHAT_RERUNS", "ARTIFACTS_REUSED", "AZURE_CALLED"):
        rp = PR._resume_plan(ctx)
        if not rp.get("available"): return f"Regeneration is not available: {rp.get('reason')}."
        if qid == "WHAT_RERUNS":
            return (f"Recommended restart: {rp['recommended_stage']}. Reused (no external call): "
                    + ", ".join(sorted({x.get('title') or x.get('stage') for x in rp['reused']})) + ". Re-run deterministically: "
                    + ", ".join(str(x.get("title") if isinstance(x, dict) else x) for x in rp["rerun"])
                    + (". Nothing is staged yet, so nothing will run." if not staged else "."))
        if qid == "ARTIFACTS_REUSED":
            return "Reused saved artifacts (hash-verified, strict replay): " + "; ".join(
                f"{x.get('kind')} {x.get('artifact')} from run {x.get('source_run')}" for x in rp["reused"])
        return ("No. Regeneration uses strict replay of the saved Azure Maps imagery, OSM data and AI observations; "
                "if any saved artifact could not be replayed the run fails closed instead of calling Azure Maps.")
    if qid == "VALIDATOR_RESULT":
        val = ctx.get("validation") or P.current_derivation(ctx).get("validation") or {}
        rows = [f"{ch['id']}: {'COMPLIANT' if ch['status'] == 'PASS' else 'CONFLICT'}"
                for part in ("rule_validation", "geometry_validation") for ch in (val.get(part) or {}).get("checks", [])]
        disp = (ctx.get("plan") or {}).get("sme_dispositions")
        tail = ("" if not disp else " Accepted SME exceptions: " +
                ", ".join(f"{d['check_id']} -> {d['disposition']}" for d in disp["dispositions"] if d["disposition"] != "BLOCKED"))
        return ("Validator results for the active draft (unchanged validators): " + "; ".join(rows) + "." + tail) if rows else \
            "The validators did not run for this draft (the site was not eligible)."
    if qid == "VERSION_DIFF":
        plan = ctx.get("plan") or {}; rev = plan.get("revision") or {}
        if not rev: return "The active draft is the original automated plan; there is no earlier SME version to compare."
        parent = run_context._read(__import__("os").path.join(__import__("tcp_planner.storage.run_store", fromlist=["x"]).run_path(rev["parent_run_id"], "output"), "plan.json")) or {}
        a = {o["object_id"]: o["placement"].get("station_m") for o in parent.get("objects", [])}
        b = {o["object_id"]: o["placement"].get("station_m") for o in plan.get("objects", [])}
        ch = [f"{k}: {a.get(k)} -> {b.get(k)} m" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        return (f"{rev.get('plan_version_id')} vs parent ({rev.get('parent_run_id')}): "
                + ("; ".join(ch) or "no object position changes") + f". Plan status {plan.get('status')}.")
    if qid == "TA_STATUS":
        ta = next((f for f in fnd if f["category"] == "TA"), None)
        return (f"{ta['label']}: {ta['status']}. Approved alternative TAs in the rule pack: "
                + (", ".join(ta["candidates"]) or "none") + ".") if ta else "TA status unavailable."
    raise AssistantError("BAD_REQUEST", "Unknown question.", 400)
