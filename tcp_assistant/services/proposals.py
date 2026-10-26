"""Proposed revision: full final review (hash-bound), confirmation, immutable versions, safe regeneration.

Nothing is written to versions before the SME confirms the exact review hash. Confirmation recomputes the review;
any difference (staged items, heads, policy, rule pack, evidence) -> STALE_REVIEW.
"""
from tcp_poc.models import content_hash
from ..core.canonical import now_iso, obj_hash
from ..core.errors import AssistantError
from ..core.ids import new_id
from . import decisions as D, preview, versions as V, run_context

_C = {}
MODES = ("SAVE_SITE_FACTS_ONLY", "SAVE_PROPOSED_REVISION", "CONFIRM_AND_REGENERATE")
RESUME_STAGE = "fusion"   # SME decisions apply at Fusion; earlier stages would re-acquire evidence (external calls)
EARLIER = ("vision", "osm", "imagery", "rule_pack", "input")
REGENERATED = ("site_model.json", "eligibility_result.json", "validation_results.json", "plan.json", "debug_plan.png",
               "debug_plan.pdf", "tcp_sheet.png", "tcp_sheet.pdf", "run_report.txt")
NEW_OUTPUTS = ("machine_site_model.json", "sme_revision_applied.json", "annotated site-understanding image (new version)")


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


# ---------------------------------------------------------------- non-fact revision parts (phases 5-7)
def staged_parts(cid):
    st = D.staged(cid)
    return {"exceptions": [d for k, d in sorted(st.items()) if k.startswith("EXCEPTION:")],
            "adjustments": {k.split(":", 1)[1]: d for k, d in st.items() if k.startswith("ADJUST:")},
            "objects": {k.split(":", 1)[1]: d for k, d in st.items() if k.startswith("OBJECT:")},
            "removed": {k.split(":", 1)[1]: d for k, d in st.items() if k.startswith("REMOVE:")}}


def revision_extra(ctx, cid):
    """Exceptions (this version only) + cumulative placement adjustments / proposed objects / removals."""
    base = ctx.get("sme_revision_applied") or {}
    s = staged_parts(cid)
    adj = {a["object_id"]: a for a in base.get("placement_adjustments") or []}; adj.update({k: v["adjustment"] for k, v in s["adjustments"].items()})
    obj = {o["object_id"]: o for o in base.get("proposed_objects") or []}; obj.update({k: v["object"] for k, v in s["objects"].items()})
    rem = {r["object_id"]: r for r in base.get("removed_objects") or []}; rem.update({k: v["removal"] for k, v in s["removed"].items()})
    return {"exceptions": [e["exception"] for e in s["exceptions"]],
            "placement_adjustments": [adj[k] for k in sorted(adj)], "proposed_objects": [obj[k] for k in sorted(obj)],
            "removed_objects": [rem[k] for k in sorted(rem)]}


# ---------------------------------------------------------------- final review
def _resume_plan(ctx):
    from tcp_ui import relations
    try:
        pv = relations.resume_preview(ctx["run_id"], RESUME_STAGE)
    except Exception as e:
        return {"available": False, "reason": f"resume preview failed ({type(e).__name__})"}
    ok = not pv["moved_earlier"] and not pv["legacy"] and not pv["dependency_changes"]
    return {"available": ok, "recommended_stage": RESUME_STAGE, "parent_run_id": ctx["run_id"],
            "reason": None if ok else (pv["move_reason"] or "; ".join(pv["dependency_changes"]) or pv["legacy_reason"]),
            "reused": pv["reused"], "rerun": pv["rerun"],
            "allowed_choices": [{"stage": RESUME_STAGE, "allowed": ok, "recommended": True,
                                 "why_safe": "SME decisions are applied at Fusion; Fusion, Eligibility, Rules/Placement, "
                                             "Validation and Render re-run deterministically on replayed evidence"}] +
                               [{"stage": s, "allowed": False, "recommended": False,
                                 "why_not": "would re-acquire evidence with external calls (Azure Maps / OSM / Foundry); "
                                            "request_new_imagery / request_new_analysis are disabled by SME_ACTION_POLICY"}
                                for s in EARLIER] +
                               [{"stage": s, "allowed": False, "recommended": False,
                                 "why_not": "later than Fusion would skip applying the SME site decisions"}
                                for s in ("eligibility", "rules", "validation", "render")],
            "strict_replay": True}


def build(ident, cid, ctx):
    doc, staged = D.effective(ctx, cid)
    extra = revision_extra(ctx, cid)
    p = c().tools.invoke(_tctx(ident, cid, ctx), "preview_site_decisions", ctx=ctx, decision_doc=doc, revision_extra=extra)["preview"]
    lk = ctx["lineage_key"]; se, pv = V.se_head(lk), V.pv_head(lk)
    n_se, n_pv = V.next_numbers(lk)
    if pv is None and ctx["plan"] and ctx["run_id"] == _base_run(cid): n_pv = 2  # v1 = the automated baseline plan
    if se is None: n_se = 2  # confirmation first records the machine result as the immutable baseline v1
    resume = _resume_plan(ctx)
    from tcp_poc.sme_policy import load_policy
    pol = load_policy()
    outcome = p["plan_outcome"]
    parent_decisions_sha = (se or {}).get("decisions_sha256") or content_hash(D.to_doc(D.base_decisions(ctx)))
    facts_changed = p["decisions_sha256"] != parent_decisions_sha
    interp = _interpretations(cid, staged)
    blocking = []
    if outcome["status"] == "BLOCKED":
        blocking.append({"code": outcome.get("reason") or "BLOCKED", "message": "The proposed plan cannot be generated: " +
                         (", ".join(outcome.get("failed_checks") or outcome.get("reason_codes") or []) or outcome.get("reason", "")),
                         "resolutions": _resolutions(ident, ctx, p)})
    if not resume["available"]:
        blocking.append({"code": "EVIDENCE_NOT_REUSABLE", "message": f"Saved evidence cannot be replayed: {resume.get('reason')}"})
    for x in p.get("blocking_extra") or []: blocking.append(x)
    review = {
        "schema": "tcp-final-review-v1", "conversation_id": cid, "reviewer": ident.subject_id,
        "request": {"structured_actions": [{"key": k, **d} for k, d in sorted(staged.items())], "messages": interp},
        "site": {"facts": p["facts"], "overlay_changes": p["overlay_changes"], "superseded_conflicts": p["superseded_conflicts"],
                 "feature_decisions": p["feature_decisions"], "rejected_features": p["rejected_features"],
                 "machine_site_model_id": p["machine_site_model_id"], "current_site_model_id": p["current_site_model_id"],
                 "proposed_site_model_id": p["proposed_site_model_id"]},
        "geometry": {"placement": p["placement"], "movements": [a.get("calculation") for a in extra["placement_adjustments"]
                                                                 if a.get("calculation")],
                     "spatial_conflicts": [c_ for a in extra["placement_adjustments"] for c_ in (a.get("spatial_conflicts") or [])] +
                                          [c_ for o in extra["proposed_objects"] for c_ in (o.get("spatial_conflicts") or [])]},
        "rules": p["rules"], "dispositions": p.get("dispositions"), "eligibility": p["eligibility"],
        "exceptions": extra["exceptions"],
        "ta": p["ta"],
        "objects": {"proposed": extra["proposed_objects"], "removed": extra["removed_objects"],
                    "unsupported": [o for o in extra["proposed_objects"] if o.get("approval_class") != "APPROVED_CATALOG_DEVICE"],
                    "validation_coverage_gaps": [g for o in extra["proposed_objects"] for g in (o.get("validation_coverage_gaps") or [])]},
        "artifacts": {"reused": resume.get("reused") or [], "reused_input": "project input (KML / coordinates) of the parent run",
                      "regenerated": list(REGENERATED), "new": list(NEW_OUTPUTS),
                      "invalidated_for_child": [f"{n} of run {ctx['run_id']} (kept unchanged; superseded for the child version)"
                                                for n in ("site_model.json", "eligibility_result.json", "validation_results.json", "plan.json")
                                                if n in ctx["outputs"]]},
        "expected_calls": {"ai_text": 0, "foundry_vision": 0, "azure_maps": 0, "osm": 0, "strict_replay": True,
                           "note": "All external evidence is replayed from verified saved artifacts; the run fails closed "
                                   "instead of calling a provider."},
        "resume": resume,
        "versions": {"parent_site_evidence_version": (se or {}).get("site_evidence_version") or
                     f"{V._id('se', lk, 1)} (machine baseline {p['machine_site_model_id']}, recorded on confirmation)",
                     "new_site_evidence_version": V._id("se", lk, n_se) if facts_changed else None,
                     "parent_plan_version": (pv or {}).get("plan_version_id") or (V._id("tcp-plan", lk, 1) + " (automated baseline)" if ctx["plan"] else None),
                     "proposed_plan_version": V._id("tcp-plan", lk, n_pv), "proposed_status": "PROPOSED_REVISION",
                     "expected_status_after_regeneration": outcome["status"]},
        "plan_outcome": outcome,
        "rule_pack": ctx["rule_pack_ref"], "policy": pol.ref, "config_sha256": _config_sha(),
        "heads": {"site_evidence": (se or {}).get("site_evidence_version"), "plan": (pv or {}).get("plan_version_id"),
                  "head_run": ctx["run_id"]},
        "blocking": blocking,
    }
    modes = {"SAVE_SITE_FACTS_ONLY": {"available": facts_changed, "why": None if facts_changed else "no site-fact change"},
             "SAVE_PROPOSED_REVISION": {"available": not blocking and bool(staged),
                                        "why": None if not blocking and staged else "blocked or nothing staged"},
             "CONFIRM_AND_REGENERATE": {"available": not blocking and bool(staged),
                                        "why": None if not blocking and staged else "blocked or nothing staged"}}
    review["modes"] = modes
    return {"review": review, "review_sha256": obj_hash(review), "_preview": p, "_extra": extra, "_doc": doc,
            "_numbers": (n_se, n_pv), "_heads": (se, pv), "_facts_changed": facts_changed}


def _interpretations(cid, staged):
    ids = sorted({d.get("message_id") for d in staged.values() if d.get("message_id")})
    out = []
    for e in c().store.events("conversations", cid):
        if e.get("type") == "message" and e.get("message_id") in ids:
            out.append({"message_id": e["message_id"], "message_sha256": e.get("message_sha256"),
                        "canonicalization_version": e.get("canonicalization_version"), "text": e.get("text"),
                        "interpretation_id": (e.get("body") or {}).get("interpretation_id")})
    return out


def _base_run(cid):
    return c().store.get("conversations", cid)["run_id"]


def _config_sha():
    from tcp_ui.evidence import sha256_file
    from tcp_poc.app import CONFIG_PATH
    return sha256_file(CONFIG_PATH)


def _tctx(ident, cid, ctx):
    from .conversations import tool_ctx
    return tool_ctx(ident, cid, ctx["run_id"])


# ---------------------------------------------------------------- confirmation (consequential)
def confirm(ident, cid, ctx, review_sha256, mode, resume_stage=None):
    if mode not in MODES: raise AssistantError("BAD_REQUEST", f"mode must be one of {MODES}.")
    b = build(ident, cid, ctx)
    if review_sha256 != b["review_sha256"]:
        raise AssistantError("STALE_REVIEW", "The review changed after it was shown. Review again before confirming.", 409,
                             actions=["RETURN_TO_REVIEW"])
    rv = b["review"]
    if not rv["modes"][mode]["available"]:
        raise AssistantError("CONFIRMATION_BLOCKED", f"{mode} is not available: {rv['modes'][mode]['why']}", 409,
                             details={"blocking": rv["blocking"]})
    if mode == "CONFIRM_AND_REGENERATE" and (resume_stage or RESUME_STAGE) != RESUME_STAGE:
        raise AssistantError("RESUME_STEP_NOT_ALLOWED", f"Only {RESUME_STAGE} is a safe resume point for this revision.", 409)
    audit = c().audit; lk = ctx["lineage_key"]
    se_head, pv_head = b["_heads"]; n_se, n_pv = b["_numbers"]; p = b["_preview"]
    cs_id = new_id("cs")
    base = dict(conversation_id=cid, run_id=ctx["run_id"], change_set_id=cs_id, review_sha256=b["review_sha256"],
                rule_pack=ctx["rule_pack_ref"], policy=rv["policy"], selected_resume_step=resume_stage or RESUME_STAGE,
                parent_plan_version=(pv_head or {}).get("plan_version_id"),
                sme_confirmation={"mode": mode, "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False},
                exceptions=[e["exception_id"] for e in b["_extra"]["exceptions"]],
                message_refs=[{k: m[k] for k in ("message_id", "message_sha256", "canonicalization_version")} for m in rv["request"]["messages"]])
    audit.write("INTENT_TO_COMMIT", ident, consequential=True, **base)
    try:
        cs = V.create("changesets", cs_id, {"schema": "tcp-change-set-v1", "change_set_id": cs_id, "conversation_id": cid,
                                            "lineage_key": lk, "state": "CONFIRMED", "mode": mode, "created_at": now_iso(),
                                            "confirmed_by": ident.audit_fields(), "review_sha256": b["review_sha256"],
                                            "decisions": b["_doc"], "revision_parts": b["_extra"],
                                            "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False,
                                            "requested_by": ident.subject_id, "parent_heads": rv["heads"]})
        c().store.put_blob("changesets", cs_id, "final_review.json", _json(rv))
        se_id = (se_head or {}).get("site_evidence_version")
        if b["_facts_changed"]:
            if se_head is None:  # immutable machine baseline first
                base_id = V._id("se", lk, 1)
                V.create("site-evidence", base_id, {"site_evidence_version": base_id, "lineage_key": lk, "version_number": 1,
                                                    "kind": "MACHINE_BASELINE", "parent_version": None, "base_run_id": _base_run(cid),
                                                    "machine_site_model_id": p["machine_site_model_id"],
                                                    "effective_site_model_id": p["machine_site_model_id"],
                                                    "decisions": {"facts": [], "features": [], "sidewalks": []},
                                                    "decisions_sha256": content_hash({"facts": [], "features": [], "sidewalks": []}),
                                                    "created_at": now_iso(), "change_set_id": None})
                V.move_head("se", lk, None, base_id); se_head = c().store.get("site-evidence", base_id); n_se = 2
            se_id = V._id("se", lk, n_se)
            V.create("site-evidence", se_id, {"site_evidence_version": se_id, "lineage_key": lk, "version_number": n_se,
                                              "kind": "SME_DECISIONS", "parent_version": se_head["site_evidence_version"],
                                              "base_run_id": _base_run(cid), "machine_site_model_id": p["machine_site_model_id"],
                                              "effective_site_model_id": p["proposed_site_model_id"], "decisions": b["_doc"],
                                              "decisions_sha256": p["decisions_sha256"], "change_set_id": cs_id,
                                              "created_at": now_iso(), "created_by": ident.audit_fields()})
            c().store.put_blob("site-evidence", se_id, "effective_site_model.json", _json(p["_new_site"]))
            V.move_head("se", lk, se_head["site_evidence_version"], se_id)
        pv_id = None
        if mode != "SAVE_SITE_FACTS_ONLY":
            if pv_head is None and ctx["plan"] and ctx["run_id"] == _base_run(cid):
                bid = V._id("tcp-plan", lk, 1)
                V.create("versions", bid, {"plan_version_id": bid, "parent_version_id": None, "lineage_key": lk, "version_number": 1,
                                           "run_id": ctx["run_id"], "status": "DRAFT_COMPLIANT", "created_by_type": "PIPELINE_AUTOMATED",
                                           "plan_ref": {"plan_id": ctx["plan"]["plan_id"], "plan_hash": ctx["plan"]["plan_hash"]},
                                           "rule_pack": ctx["rule_pack_ref"], "created_at": now_iso(), "change_set_id": None,
                                           "site_evidence_version": None, "active_exceptions": []})
                V.move_head("pv", lk, None, bid); pv_head = c().store.get("versions", bid); n_pv = 2
            pv_id = V._id("tcp-plan", lk, n_pv)
            revision = _revision(ident, ctx, cs_id, pv_id, pv_head, n_pv, se_id, p, b["_extra"], rv)
            V.create("versions", pv_id, {
                "plan_version_id": pv_id, "parent_version_id": (pv_head or {}).get("plan_version_id"), "lineage_key": lk,
                "version_number": n_pv, "run_id": None, "status": "PROPOSED_REVISION",
                "created_by_type": "SME_CONFIRMED_ASSISTANT_CHANGE", "change_set_id": cs_id, "site_evidence_version": se_id,
                "rule_pack_version": ctx["rule_pack_ref"]["version"], "rule_pack": ctx["rule_pack_ref"], "policy": rv["policy"],
                "config_sha256": rv["config_sha256"], "revision_id": revision["revision_id"],
                "revision_sha256": revision["content_sha256"], "expected_status": p["plan_outcome"]["status"],
                "active_exceptions": [e["exception_id"] for e in b["_extra"]["exceptions"]],
                "parent_run_id": ctx["run_id"], "created_at": now_iso(), "created_by": ident.audit_fields(),
                "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False})
            c().store.put_blob("versions", pv_id, "sme_revision.json", _json(revision))
            V.move_head("pv", lk, (pv_head or {}).get("plan_version_id"), pv_id)
    except AssistantError as e:
        audit.write("COMMIT_FAILED", ident, consequential=True, error_code=e.code, **base)
        raise
    except Exception as e:
        audit.write("COMMIT_FAILED", ident, consequential=True, error_code="VERSION_WRITE_FAILED", **base)
        raise AssistantError("VERSION_WRITE_FAILED", "The version could not be saved; nothing was changed.", 500,
                             details={"reason": type(e).__name__})
    audit.write("COMMITTED", ident, consequential=True, new_plan_version=pv_id, site_evidence_version=se_id, **base)
    D.reset(cid, f"committed {cs_id}")
    from .conversations import add_message
    add_message(cid, "assistant", "COMMITTED", {"change_set_id": cs_id, "plan_version_id": pv_id, "site_evidence_version": se_id,
                                                "mode": mode, "text": f"Confirmed: change set {cs_id}"
                                                + (f", site-evidence version {se_id}" if se_id else "")
                                                + (f", proposed revision {pv_id}" if pv_id else "") + "."})
    out = {"change_set_id": cs_id, "site_evidence_version": se_id, "plan_version_id": pv_id, "mode": mode}
    if mode == "CONFIRM_AND_REGENERATE":
        from . import pipeline_controller
        try:
            out["resume_attempt"] = pipeline_controller.start(ident, cid, pv_id)
        except AssistantError as e:  # versions are committed; regeneration can be retried (new attempt record)
            out["resume_error"] = e.to_dict()
    return out


def _json(obj):
    import json
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")


def _revision(ident, ctx, cs_id, pv_id, pv_head, n_pv, se_id, p, extra, rv):
    from tcp_poc.sme_revision import SCHEMA, revision_hash
    new_plan = p["_new_derived"]["plan"]
    exp = sorted((o["object_id"], o["placement"].get("station_m"), o["placement"].get("latitude"), o["placement"].get("longitude"))
                 for o in (new_plan or {}).get("objects", []))
    doc = {"schema": SCHEMA, "revision_id": new_id("rev"), "plan_version_id": pv_id,
           "parent_version_id": (pv_head or {}).get("plan_version_id"), "version_number": n_pv, "change_set_id": cs_id,
           "site_evidence_version": se_id, "parent_run_id": ctx["run_id"], "lineage_key": ctx["lineage_key"],
           "machine_site_model_id": p["machine_site_model_id"], "rule_pack": ctx["rule_pack_ref"], "policy": rv["policy"],
           "config_sha256": rv["config_sha256"], "decisions": p["decisions"], "exceptions": extra["exceptions"],
           "placement_adjustments": extra["placement_adjustments"], "proposed_objects": extra["proposed_objects"],
           "removed_objects": extra["removed_objects"],
           "expected": {"site_model_id": p["proposed_site_model_id"], "plan_status": p["plan_outcome"]["status"],
                        "objects": [list(x) for x in exp]},
           "review_sha256": obj_hash(rv), "created_at": now_iso(), "created_by": ident.subject_id,
           "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False}
    doc["content_sha256"] = revision_hash(doc)
    return doc


def _resolutions(ident, ctx, p):
    """For each still-blocked validator check: can the SME resolve it with a plan-specific exception (deterministic policy
    check), and did the previous plan version already carry an exception for it (exceptions never carry over)."""
    from tcp_poc.sme_policy import load_policy
    try: pol = load_policy()
    except Exception: pol = None
    prev = {}
    applied = ctx.get("sme_revision_applied") or {}
    for e in applied.get("exceptions") or []:
        if e.get("check_id"): prev.setdefault(e["check_id"], []).append(e.get("exception_id"))
    out = []
    for d in (p.get("dispositions") or {}).get("dispositions") or []:
        if d["disposition"] != "BLOCKED": continue
        hard = str(d.get("reason") or "").startswith("non-overridable")
        if pol is None: ok, why = False, "SME action policy unavailable"
        elif not pol.exceptions_enabled: ok, why = False, "SME exceptions are disabled by policy"
        elif hard: ok, why = False, d["reason"]
        else:
            ok, why = pol.allowed("override_rule_conflict", ident.roles)
        out.append({"check_id": d["check_id"], "objects": d.get("objects"), "rule_status": "CONFLICT",
                    "can_request_exception": bool(ok), "why_not": None if ok else why,
                    "previous_version_exceptions": prev.get(d["check_id"], []),
                    "note": ("The previous plan version accepted this conflict with an SME exception, but exceptions apply to "
                             "one plan version only and must be confirmed again for this change." if d["check_id"] in prev else None)})
    if not out and p["plan_outcome"].get("reason") == "TA_NOT_APPLICABLE":
        out.append({"check_id": None, "kind": "TA_NOT_APPLICABLE", "can_request_exception": bool(pol and pol.exceptions_enabled
                    and pol.allowed("proceed_without_applicable_ta", ident.roles)[0]), "why_not": None})
    return out
