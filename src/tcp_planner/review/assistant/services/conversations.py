"""Conversation service: one conversation per (run, reviewer session start). Messages are append-only events.

Assistant messages are deterministic: a site-understanding summary, the annotated image, then one review-card message
per finding that requires review. User free text (phase 8) is stored ONLY here (never in audit).
"""
from ..core.canonical import now_iso, message_hash, canonical_text, CANON_VERSION
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.profile import load_profile
from ..core.tools import ToolContext
from . import findings as F, run_context

_C = {}


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


def tool_ctx(ident, conversation_id=None, run_id=None):
    return ToolContext(ident, load_profile("sme_review"), c().audit, conversation_id, run_id)


def head_context(cid, conv, tctx):
    """Review context for the lineage head: the run of the latest generated plan version (else the base run); when a
    newer site-evidence version was saved without regeneration, its decisions are overlaid on the machine model."""
    from . import versions, run_context
    from tcp_planner.review import decision_overlay as sme_overlay
    from tcp_planner.routing.eligibility import evaluate
    from tcp_planner.contracts import content_hash
    head_run = versions.head_run(conv) or conv["run_id"]
    ctx = c().tools.invoke(tctx, "load_run_context", run_id=head_run)["ctx"]
    se = versions.se_head(conv["lineage_key"])
    applied = (ctx.get("sme_revision_applied") or {}).get("decisions") or {"facts": [], "features": [], "sidewalks": []}
    if se and se["decisions_sha256"] != content_hash(applied):
        cfg = run_context.config()
        ctx["site_model"] = sme_overlay.apply(ctx["machine_site_model"], se["decisions"], cfg)
        ctx["eligibility"] = evaluate(ctx["site_model"], ctx["rule_pack"], cfg)
        ctx["plan"] = None; ctx["validation"] = None
        ctx["sme_revision_applied"] = {**(ctx.get("sme_revision_applied") or {}), "decisions": se["decisions"]}
        ctx["run_state"] = {**ctx["run_state"], "decision": ctx["eligibility"]["decision"],
                            "reason_codes": ctx["eligibility"]["reason_codes"]}
        ctx["site_evidence_only"] = se["site_evidence_version"]
    ctx["head_run_id"] = head_run
    return ctx


def finalize(ident, cid, conv):
    """Verify finished regenerations; post a new review round (new annotated image) for successful ones."""
    from . import pipeline_controller
    for pv_id, status, ra in pipeline_controller.finalize_pending(ident):
        if ra.get("conversation_id") != cid: continue
        if status in ("DRAFT_COMPLIANT", "DRAFT_WITH_ENGINEERING_EXCEPTION"):
            tctx = tool_ctx(ident, cid, ra["run_id"])
            ctx = c().tools.invoke(tctx, "load_run_context", run_id=ra["run_id"])["ctx"]
            add_message(cid, "assistant", "PIPELINE_STATUS", {"title": "Regeneration finished", "run_id": ra["run_id"], "status": status})
            add_message(cid, "assistant", "VERSION_RESULT", {"title": f"{pv_id} is now {status}", "plan_version_id": pv_id,
                                                             "status": status, "run_id": ra["run_id"]})
            post_review(ident, cid, conv, ctx, tctx, f"Regenerated draft {pv_id}: {status}", plan_version_id=pv_id)
        else:
            add_message(cid, "assistant", "TEXT", {"text": f"Regeneration of {pv_id} failed ({status}). The parent version is "
                                                           "unchanged; you can retry regeneration.", "plan_version_id": pv_id})


def start(ident, run_id):
    if not isinstance(run_id, str) or not run_id: raise AssistantError("BAD_REQUEST", "run_id required.")
    tctx = tool_ctx(ident, run_id=run_id)
    ctx = c().tools.invoke(tctx, "load_run_context", run_id=run_id)["ctx"]
    cid = new_id("conv"); tctx.conversation_id = cid
    prof = tctx.profile
    conv = c().store.create("conversations", cid, {
        "schema": "tcp-conversation-v1", "conversation_id": cid, "profile": prof["name"], "profile_version": prof["version"],
        "run_id": run_id, "lineage_key": ctx["lineage_key"], "created_at": now_iso(),
        "created_by": ident.audit_fields(), "base_site_model_id": ctx["site_model"]["site_model_id"],
        "machine_site_model_id": ctx["machine_site_model"]["site_model_id"], "rule_pack": ctx["rule_pack_ref"],
        "canonicalization_version": CANON_VERSION})
    c().audit.write("CONVERSATION_STARTED", ident, conversation_id=cid, run_id=run_id, consequential=True,
                    rule_pack=ctx["rule_pack_ref"], site_model_id=ctx["site_model"]["site_model_id"])
    post_review(ident, cid, conv, ctx, tctx, "Site understanding review")
    return view(ident, cid)


def display_plan(ctx):
    """Exported plan, else the deterministic placement the pipeline computed but did not export (validation failed)."""
    if ctx["plan"]: return ctx["plan"], True
    from . import preview
    d = preview.current_derivation(ctx)
    return d["plan"], False


def post_review(ident, cid, conv, ctx, tctx, title, plan_version_id=None, site_evidence_version=None):
    fnd = c().tools.invoke(tctx, "list_review_findings", ctx=ctx)["findings"]
    plan, exported = display_plan(ctx)
    art = c().tools.invoke(tctx, "generate_annotated_image", ctx=ctx, site_model=ctx["site_model"], findings=fnd,
                           plan=plan, plan_version_id=plan_version_id, site_evidence_version=site_evidence_version)["artifact"]
    s = F.summary(fnd)
    add_message(cid, "assistant", "SUMMARY", {
        "title": title, "run_id": ctx["run_id"], "decision": ctx["run_state"]["decision"],
        "reason_codes": ctx["run_state"]["reason_codes"], "summary": s, "annotated_image_artifact_id": art["artifact_id"],
        "text": f"{title}: {s['requires_review']} item(s) need review ({s['blocking']} blocking). "
                "The image is a review artifact; structured site facts remain authoritative."})
    for f in fnd:
        if f["requires_review"]:
            add_message(cid, "assistant", "REVIEW_CARD", {"finding_id": f["finding_id"], "run_id": ctx["run_id"]})
    return fnd, art


def add_message(cid, role, kind, body, text=None, ident=None):
    mid = new_id("msg"); ts = now_iso()
    ev = {"type": "message", "message_id": mid, "role": role, "kind": kind, "created_at": ts, "body": body}
    if text is not None:
        ev["text"] = text; ev["canonical_text"] = canonical_text(text)
        ev["message_sha256"] = message_hash(cid, mid, ts, text); ev["canonicalization_version"] = CANON_VERSION
        ev["author"] = ident.subject_id if ident else None
    c().store.append_event("conversations", cid, ev, durable=role == "user")
    return ev


def get(cid):
    conv = c().store.get("conversations", cid)
    if not conv: raise AssistantError("NOT_FOUND", "Conversation not found.", 404)
    return conv


def view(ident, cid):
    conv = get(cid)
    finalize(ident, cid, conv)
    tctx = tool_ctx(ident, cid, conv["run_id"])
    ctx = head_context(cid, conv, tctx)
    fnd = c().tools.invoke(tctx, "list_review_findings", ctx=ctx)["findings"]
    events = c().store.events("conversations", cid)
    from . import versions
    from . import decisions
    return {"conversation": conv, "messages": [e for e in events if e.get("type") == "message"],
            "staged": [{"key": k, **d} for k, d in sorted(decisions.staged(cid).items())],
            "applied_decisions": decisions.to_doc(decisions.base_decisions(ctx)),
            "head_run_id": ctx["run_id"], "run_state": ctx["run_state"], "findings": fnd, "summary": F.summary(fnd),
            "plan": _plan_summary(ctx), "lineage": versions.lineage(conv["lineage_key"]),
            "site_evidence_only": ctx.get("site_evidence_only"),
            "rule_pack": ctx["rule_pack_ref"], "objects": _objects(ctx),
            "context": __import__("tcp_planner.review.assistant.services.assistant_state", fromlist=["x"]).context_of(conv, ctx)}


def _plan_summary(ctx):
    p = ctx["plan"]
    if not p: return None
    return {"plan_id": p["plan_id"], "plan_hash": p["plan_hash"], "status": p.get("status"), "version": p.get("version"),
            "revision": p.get("revision"), "template": p.get("template"), "sme_dispositions": p.get("sme_dispositions")}


def _objects(ctx):
    """Existing TCP objects currently present (for dropdowns): only what the (exported or computed) plan contains."""
    plan, exported = display_plan(ctx)
    return [{"object_id": o["object_id"], "object_type": o["object_type"], "sign_code": o.get("sign_code"),
             "approach": o.get("approach"), "station_m": o["placement"].get("station_m"), "exported": exported,
             "sme": o.get("sme")} for o in (plan or {}).get("objects", [])]


def archived(cid):
    """Archive state (append-only event; the conversation record and its audit history are never deleted)."""
    for e in reversed(c().store.events("conversations", cid)):
        if e.get("type") == "archived": return e
    return None


def archive(ident, cid, reason=None):
    from . import decisions
    if archived(cid): raise AssistantError("SESSION_ARCHIVED", "This review session is already deleted.", 409, False)
    staged = len(decisions.staged(cid))
    c().audit.write("SESSION_ARCHIVED", ident, consequential=True, conversation_id=cid, staged_discarded=staged,
                    reason=(reason or "")[:300])
    ev = {"type": "archived", "at": now_iso(), "by": ident.subject_id, "staged_discarded": staged, "reason": (reason or "")[:300]}
    c().store.append_event("conversations", cid, ev, durable=True)
    return ev


def list_mine(ident):
    out = []
    for conv in c().store.list("conversations"):
        if archived(conv["conversation_id"]): continue
        if conv["created_by"].get("subject_id") == ident.subject_id or "AUDITOR" in ident.roles or "ADMIN" in ident.roles:
            out.append({k: conv[k] for k in ("conversation_id", "run_id", "created_at", "lineage_key")})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)
