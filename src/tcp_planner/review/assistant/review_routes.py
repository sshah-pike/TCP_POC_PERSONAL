"""Review routes (registered on import by api.py). All authorization is enforced here, in the backend."""
from tcp_planner.review.assistant.routes import route
from .core import authz
from .core.errors import AssistantError


def _svc():
    from .services.container import container
    return container()


def _conv_access(ident, cid):
    from .services import conversations
    conv = conversations.get(cid)
    if conv["created_by"].get("subject_id") != ident.subject_id and not authz.has(ident, "audit:read"):
        raise AssistantError("AUTHZ_DENIED", "This review belongs to another reviewer.", 403, False)
    return conv


@route("GET", "runs/{run_id}/eligibility")
def run_eligibility(ident, run_id, **_):
    authz.require(ident, "review:read"); _svc()
    from .services import run_context
    ctx, reasons = run_context.eligibility(run_id)
    return {"run_id": run_id, "eligible": ctx is not None, "reasons": reasons,
            "can_start": ctx is not None and authz.has(ident, "review:decide")}


@route("POST", "conversations")
def start_conversation(ident, payload, **_):
    authz.require(ident, "review:decide"); _svc()
    from .services import conversations
    return 201, "json", conversations.start(ident, payload.get("run_id"))


@route("GET", "conversations")
def list_conversations(ident, query, **_):
    authz.require(ident, "review:read"); _svc()
    from .services import conversations, assistant_state
    rid = (query.get("run_id") or [None])[0]
    if rid: return {"conversations": assistant_state.conversations_for_run(ident, rid)}
    return {"conversations": conversations.list_mine(ident)}


@route("GET", "conversations/{cid}")
def get_conversation(ident, cid, **_):
    authz.require(ident, "review:read"); _svc(); _conv_access(ident, cid)
    from .services import conversations
    return conversations.view(ident, cid)


@route("GET", "artifacts/{aid}")
def get_artifact(ident, aid, **_):
    authz.require(ident, "artifact:read")
    a = _svc().store.get("artifacts", aid)
    if not a: raise AssistantError("NOT_FOUND", "Artifact not found.", 404)
    return {"artifact": a}


@route("GET", "artifacts/{aid}/file")
def get_artifact_file(ident, aid, **_):
    authz.require(ident, "artifact:read")
    import hashlib, os
    s = _svc().store; a = s.get("artifacts", aid)
    if not a or not a.get("file"): raise AssistantError("NOT_FOUND", "Artifact not found.", 404)
    path = s.blob_path("artifacts", aid, a["file"])
    if not os.path.isfile(path): raise AssistantError("NOT_FOUND", "Artifact file missing.", 404)
    with open(path, "rb") as f: digest = hashlib.sha256(f.read()).hexdigest()
    if digest != (a.get("png_sha256") or a.get("file_sha256")):
        raise AssistantError("ARTIFACT_INTEGRITY", "Artifact file failed its hash check.", 500, False)
    return 200, "file", {"path": path}


@route("GET", "audit")
def audit(ident, query, **_):
    authz.require(ident, "audit:read")
    stream = (query.get("conversation_id") or [None])[0]
    evs = _svc().audit.read(stream)
    return {"events": evs[-2000:], "chain_valid": _svc().audit.verify_chain(evs) if stream else None}


# ---------------------------------------------------------------- phase 3: structured decisions + preview (no AI)
def _head(ident, cid, payload=None):
    """Conversation + head context. When the request carries `context` (the floating assistant and workspace always send
    it) the run / conversation / site-evidence / plan versions / context hash must match: stale or cross-run requests
    are rejected (assistant_state.check_context)."""
    from .services import conversations, assistant_state
    conv = _conv_access(ident, cid)
    tctx = conversations.tool_ctx(ident, cid, conv["run_id"])
    ctx = conversations.head_context(cid, conv, tctx)
    if payload is not None and conversations.archived(cid):   # writes on a deleted (archived) session are refused
        raise AssistantError("SESSION_ARCHIVED", "This review session was deleted. Start or select another session.", 409, False)
    if payload: assistant_state.check_context(payload, conv, ctx)
    return conv, tctx, ctx


@route("POST", "conversations/{cid}/decisions")
def stage_decision(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can change it.", 403, False)
    r = _svc().tools.invoke(tctx, "stage_decision", ctx=ctx, cid=cid, payload=payload)
    return {"staged": r["key"], "decision": r["decision"], **_preview_body(tctx, ctx, cid)}


@route("POST", "conversations/{cid}/decisions/remove")
def unstage_decision(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    from .services import decisions
    decisions.unstage(ident, cid, str(payload.get("key") or ""))
    return _preview_body(tctx, ctx, cid)


@route("GET", "conversations/{cid}/preview")
def get_preview(ident, cid, **_):
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid)
    return _preview_body(tctx, ctx, cid)


def _preview_body(tctx, ctx, cid):
    from .services import decisions, preview, proposals
    doc, staged = decisions.effective(ctx, cid)
    extra = proposals.revision_extra(ctx, cid) if hasattr(proposals, "revision_extra") else None
    p = _svc().tools.invoke(tctx, "preview_site_decisions", ctx=ctx, decision_doc=doc, revision_extra=extra)["preview"]
    return {"staged": [{"key": k, **d} for k, d in sorted(staged.items())], "preview": preview.public(p)}


# ---------------------------------------------------------------- phase 4: final review, confirmation, versions
@route("GET", "conversations/{cid}/review")
def final_review(ident, cid, **_):
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid)
    from .services import proposals
    b = proposals.build(ident, cid, ctx)
    _svc().audit.write("REVIEW_SHOWN", ident, conversation_id=cid, review_sha256=b["review_sha256"], run_id=ctx["run_id"])
    _chat_once(cid, "FINAL_REVIEW", b["review_sha256"], {
        "title": "Full change review ready", "review_sha256": b["review_sha256"],
        "blocked": bool(b["review"]["blocking"]), "plan_status": b["review"]["versions"].get("expected_status_after_regeneration"),
        "text": ("Blocked - see the listed conflicts and actions." if b["review"]["blocking"] else
                 "Ready to confirm. Nothing changes until you confirm with this exact review.")})
    return {"review": b["review"], "review_sha256": b["review_sha256"]}


def _chat_once(cid, kind, key, body):
    """Post an assistant chat message once per distinct key (one FINAL_REVIEW message per review hash)."""
    from .services.conversations import add_message
    for e in reversed(_svc().store.events("conversations", cid)):
        if e.get("type") == "message" and e.get("kind") == kind:
            if e["body"].get("_key") == key: return None
            break
    return add_message(cid, "assistant", kind, {**body, "_key": key})


@route("POST", "conversations/{cid}/confirm")
def confirm(ident, cid, payload, **_):
    authz.require(ident, "changeset:confirm")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can confirm it.", 403, False)
    if payload.get("mode") == "CONFIRM_AND_REGENERATE": authz.require(ident, "pipeline:resume")
    from .services import proposals
    from .services.conversations import add_message
    res = proposals.confirm(ident, cid, ctx, payload.get("review_sha256"), payload.get("mode"), payload.get("resume_stage"))
    add_message(cid, "assistant", "CONFIRMATION", {"title": "Change set confirmed", "mode": payload.get("mode"),
                "change_set_id": res.get("change_set_id"), "text": f"Confirmed by {ident.subject_id} (self-confirmed POC)."})
    add_message(cid, "assistant", "VERSION_RESULT", {"title": "Versions created", "site_evidence_version": res.get("site_evidence_version"),
                "plan_version_id": res.get("plan_version_id"), "status": "PROPOSED_REVISION" if res.get("plan_version_id") else None})
    if res.get("resume_attempt"):
        add_message(cid, "assistant", "PIPELINE_STATUS", {"title": "Regeneration started", "run_id": res["resume_attempt"]["run_id"],
                    "text": "Strict-replay pipeline run started from Fusion (no Azure Maps / OSM / AI calls)."})
    if res.get("resume_error"):
        add_message(cid, "assistant", "ERROR", {"title": "Regeneration could not start", "text": res["resume_error"].get("message")})
    return res


@route("POST", "plan-versions/{pv}/regenerate")
def regenerate(ident, pv, payload, **_):
    authz.require(ident, "pipeline:resume")
    rec = _svc().store.get("versions", pv)
    if not rec: raise AssistantError("NOT_FOUND", "Plan version not found.", 404)
    from .services import versions, pipeline_controller
    if versions.status(rec) not in ("PROPOSED_REVISION", "DRAFT_GENERATION_FAILED"):
        raise AssistantError("NOT_ALLOWED", "Only proposed or failed versions can be (re)generated.", 409)
    cid = payload.get("conversation_id")
    _conv_access(ident, cid)
    return {"resume_attempt": pipeline_controller.start(ident, cid, pv, payload.get("resume_stage") or "fusion")}


@route("GET", "plan-versions/{pv}")
def plan_version(ident, pv, **_):
    authz.require(ident, "review:read")
    rec = _svc().store.get("versions", pv)
    if not rec: raise AssistantError("NOT_FOUND", "Plan version not found.", 404)
    from .services import versions
    return versions.plan_version_view(rec)


# ---------------------------------------------------------------- phase 5: SME exceptions (deterministic; never AI)
@route("POST", "conversations/{cid}/exceptions")
def request_exception(ident, cid, payload, **_):
    authz.require(ident, "exception:confirm")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can request exceptions.", 403, False)
    r = _svc().tools.invoke(tctx, "record_exception", ctx=ctx, cid=cid, payload=payload)
    return {"staged": r["key"], "exception": r["exception"], **_preview_body(tctx, ctx, cid)}


# ---------------------------------------------------------------- phase 6: existing-device placement (deterministic)
@route("POST", "conversations/{cid}/placements/evaluate")
def evaluate_placement(ident, cid, payload, **_):
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid, payload)
    from .services import geometry_tools
    ev = geometry_tools.evaluate(ident, cid, ctx, {k: v for k, v in payload.items() if k != "context"})
    _svc().audit.write("TOOL_INVOCATION", ident, conversation_id=cid, tool_name="evaluate_placement", tool_version="1",
                       status="OK", external_call=False, model_deployment="N/A", affected_entities=[ev["movement"]["object_id"]])
    msg = geometry_tools.post_evaluation(cid, ev, source="button", message_id=payload.get("message_id"))
    return {"evaluation": ev, "message_id": msg["message_id"]}


@route("POST", "conversations/{cid}/placements")
def stage_placement(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can change it.", 403, False)
    r = _svc().tools.invoke(tctx, "stage_placement", ctx=ctx, cid=cid, req={k: v for k, v in payload.items() if k != "context"})
    from .services.conversations import add_message
    m = r["evaluation"]["movement"]
    add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": f"{m['object_id']} movement staged (not committed)",
                "text": f"{m['object_id']}: station {m['current']['station_m']} m -> {m['proposed']['station_m']} m "
                        f"({m['actual_along_alignment_ft']} ft along the road). Plan result if confirmed: "
                        f"{r['evaluation']['plan_outcome']['status']}. Review the change set before confirming."})
    return {"staged": r["key"], "evaluation": r["evaluation"], **_preview_body(tctx, ctx, cid)}


@route("POST", "conversations/{cid}/placements/keep")
def keep_placement(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    from .services import decisions
    decisions.unstage(ident, cid, f"ADJUST:{payload.get('object_id')}")
    return _preview_body(tctx, ctx, cid)


# ---------------------------------------------------------------- phase 7: new / unsupported objects, removal
@route("POST", "conversations/{cid}/objects")
def stage_object(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can change it.", 403, False)
    r = _svc().tools.invoke(tctx, "stage_object", ctx=ctx, cid=cid, req=payload)
    return {"staged": r["key"], "object": r["object"], **_preview_body(tctx, ctx, cid)}


@route("POST", "conversations/{cid}/objects/remove")
def remove_object(ident, cid, payload, **_):
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can change it.", 403, False)
    r = _svc().tools.invoke(tctx, "remove_object", ctx=ctx, cid=cid, req=payload)
    return {**{k: v for k, v in r.items() if not k.startswith("_")}, **_preview_body(tctx, ctx, cid)}



@route("POST", "conversations/{cid}/placements/relative")
def relative_placement(ident, cid, payload, **_):
    """Before/after a saved feature -> deterministic station -> evaluation (not staged)."""
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid, payload)
    from .services import geometry_tools as G
    site, plan, _, _ = G.proposal_state(ctx, cid)
    st = G.relative_station(site, plan, payload.get("object_id"), payload.get("feature_key"), payload.get("relation"))
    ev = G.evaluate(ident, cid, ctx, {"object_id": payload.get("object_id"), "station_m": st,
                                      "candidate_kind": f"{payload.get('relation')}_FEATURE", "message_id": payload.get("message_id")})
    return {"station_m": st, "evaluation": ev}


# ---------------------------------------------------------------- phase 8: natural-language interpretation
@route("POST", "conversations/{cid}/messages")
def post_message(ident, cid, payload, **_):
    authz.require(ident, "message:submit")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can send messages.", 403, False)
    from .services import interpret_tools
    return interpret_tools.submit(ident, cid, ctx, tctx, payload.get("text"))


# ---------------------------------------------------------------- floating assistant: summary, attention, ui state, forms, QA
@route("GET", "runs/{run_id}/assistant-summary")
def run_assistant_summary(ident, run_id, **_):
    """Launcher badge for the run open in RunView. Never creates a conversation."""
    authz.require(ident, "review:read"); _svc()
    from .services import assistant_state
    return assistant_state.run_summary(ident, run_id)


@route("GET", "conversations/{cid}/attention")
def conversation_attention(ident, cid, **_):
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid)
    from .services import assistant_state, decisions, findings, preview, proposals, versions, run_context
    fnd = findings.derive(ctx, run_context.config())
    staged = decisions.staged(cid); p = None
    if staged:
        doc, _ = decisions.effective(ctx, cid); p = preview.compute(ctx, doc, proposals.revision_extra(ctx, cid))
    vs = {pv["plan_version_id"]: versions.status(pv) for pv in _svc().store.list("versions") if pv.get("lineage_key") == conv["lineage_key"]}
    latest = max(vs, key=lambda k: int(k.rsplit("-v", 1)[1])) if vs else None
    att = assistant_state.attention(fnd, staged, p, None, {latest: vs[latest]} if latest else {})
    return {"attention": att, "context": assistant_state.context_of(conv, ctx), "ui_state": assistant_state.ui_state(cid)}


@route("GET", "conversations/{cid}/context")
def conversation_context(ident, cid, **_):
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid)
    from .services import assistant_state
    return {"context": assistant_state.context_of(conv, ctx)}


@route("POST", "conversations/{cid}/ui-state")
def set_ui_state(ident, cid, payload, **_):
    authz.require(ident, "review:read"); _conv_access(ident, cid)
    from .services import assistant_state
    return {"ui_state": assistant_state.set_ui_state(cid, payload.get("acknowledged_blocking"))}


@route("POST", "conversations/{cid}/forms/submit")
def submit_form(ident, cid, payload, **_):
    """Complete a partially interpreted request with structured values. Deterministic - never calls the model."""
    authz.require(ident, "review:decide")
    conv, tctx, ctx = _head(ident, cid, payload)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this review can change it.", 403, False)
    from .services import clarify_forms
    return clarify_forms.submit(ident, cid, ctx, tctx, payload.get("interpretation_id"), payload.get("op_index"), payload.get("values"))


@route("POST", "conversations/{cid}/ask")
def ask(ident, cid, payload, **_):
    """Deterministic question about the ACTIVE draft only (template id). No model call."""
    authz.require(ident, "review:read")
    conv, tctx, ctx = _head(ident, cid, payload)
    from .services import assistant_state
    from .services.conversations import add_message
    qid = payload.get("question_id")
    if qid not in assistant_state.QUESTIONS: raise AssistantError("BAD_REQUEST", "Unknown question.", 400)
    txt = assistant_state.answer(ident, cid, ctx, qid, payload.get("target_id"))
    add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": assistant_state.QUESTIONS[qid], "text": txt,
                                                           "question_id": qid, "answer_source": "DETERMINISTIC_TEMPLATE"})
    _svc().audit.write("DRAFT_QA", ident, conversation_id=cid, question_id=qid, model_call=False)
    return {"question_id": qid, "answer": txt, "model_call": False}


@route("POST", "conversations/{cid}/archive")
def archive_conversation(ident, cid, payload, **_):
    """'Delete session' = archive: hidden from session lists and closed to changes. Messages, change sets, versions and
    the audit trail are kept (immutable). Confirmed versions are unaffected; unconfirmed staged changes are discarded."""
    authz.require(ident, "review:decide")
    conv = _conv_access(ident, cid)
    if conv["created_by"].get("subject_id") != ident.subject_id:
        raise AssistantError("AUTHZ_DENIED", "Only the reviewer who owns this session can delete it.", 403, False)
    from .services import conversations
    return {"archived": conversations.archive(ident, cid, payload.get("reason"))}
