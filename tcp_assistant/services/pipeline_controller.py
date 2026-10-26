"""Safe pipeline regeneration for a confirmed plan version: a strict-replay revision run via tcp_ui.relations.

Each attempt is a new immutable resume-attempt record. finalize() verifies the finished run against the reviewed
revision (revision hash, machine site model, proposed objects, plan status) before the version becomes a draft.
"""
import json, os, threading

from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from . import versions as V

_C = {}
_LOCK = threading.Lock()


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


def _default_launcher(run_id, rdir):
    from tcp_ui import server
    server.launch(run_id, rdir)


LAUNCHER = _default_launcher   # tests inject an in-process runner


def start(ident, cid, pv_id, resume_stage="fusion"):
    from tcp_ui import relations
    pv = c().store.get("versions", pv_id)
    if not pv: raise AssistantError("NOT_FOUND", "Plan version not found.", 404)
    if V.status(pv) in V.SUCCESS: raise AssistantError("ALREADY_GENERATED", "This version was already generated.", 409)
    with open(c().store.blob_path("versions", pv_id, "sme_revision.json"), encoding="utf-8") as f: revision = json.load(f)
    ra_id = new_id("ra")
    c().audit.write("RESUME_REQUESTED", ident, consequential=True, conversation_id=cid, plan_version=pv_id,
                    change_set_id=pv["change_set_id"], selected_resume_step=resume_stage, resume_attempt_id=ra_id,
                    parent_run_id=pv["parent_run_id"], strict_replay=True)
    try:
        run_id, rdir = relations.create_resume_run(pv["parent_run_id"], resume_stage, sme_revision=revision, strict_replay=True)
    except Exception as e:
        c().store.create("resume-attempts", ra_id, {"resume_attempt_id": ra_id, "plan_version_id": pv_id, "run_id": None,
                                                    "created_at": now_iso(), "error": type(e).__name__, "conversation_id": cid})
        V.add_status(pv_id, "DRAFT_GENERATION_FAILED", resume_attempt_id=ra_id, reason=f"resume run could not be created ({type(e).__name__})")
        raise AssistantError("RESUME_LAUNCH_FAILED", "The regeneration run could not be created; the parent version is unchanged.",
                             500, actions=["RETRY_REGENERATION"])
    rec = c().store.create("resume-attempts", ra_id, {
        "resume_attempt_id": ra_id, "plan_version_id": pv_id, "run_id": run_id, "parent_run_id": pv["parent_run_id"],
        "requested_stage": resume_stage, "strict_replay": True, "created_at": now_iso(), "created_by": ident.subject_id,
        "conversation_id": cid, "revision_sha256": revision["content_sha256"]})
    c().store.append_event("versions", pv_id, {"type": "resume_started", "resume_attempt_id": ra_id, "run_id": run_id, "at": now_iso()})
    try:
        LAUNCHER(run_id, rdir)
    except Exception as e:
        c().store.append_event("resume-attempts", ra_id, {"type": "result", "status": "DRAFT_GENERATION_FAILED",
                                                          "reason": f"launch failed ({type(e).__name__})", "at": now_iso()})
        V.add_status(pv_id, "DRAFT_GENERATION_FAILED", resume_attempt_id=ra_id, run_id=run_id, reason="launch failed")
        raise AssistantError("RESUME_LAUNCH_FAILED", "The regeneration run could not be started; the parent version is unchanged.",
                             500, actions=["RETRY_REGENERATION"])
    return rec


def finalize_pending(ident=None):
    """Verify finished attempts (idempotent). Returns [(pv_id, status)] newly finalized."""
    from tcp_ui import store
    done = []
    with _LOCK:
        for ra in c().store.list("resume-attempts"):
            if not ra.get("run_id") or any(e.get("type") == "result" for e in c().store.events("resume-attempts", ra["resume_attempt_id"])):
                continue
            st = store.build_state(ra["run_id"], with_lineage=False, live_ids=_live_ids())
            if st is None or st["state"] == "RUNNING": continue
            proc = _read(store.run_path(ra["run_id"], "ui", "process.json")) or {}
            if proc.get("state") != "FINISHED" and ra["run_id"] in _live_ids(): continue  # still running
            status, reason = _verify(ra, st)
            c().store.append_event("resume-attempts", ra["resume_attempt_id"], {"type": "result", "status": status,
                                                                               "reason": reason, "at": now_iso()}, durable=True)
            V.add_status(ra["plan_version_id"], status, run_id=ra["run_id"], resume_attempt_id=ra["resume_attempt_id"], reason=reason)
            c().audit.write("RESUME_RESULT", ident, consequential=True, conversation_id=ra.get("conversation_id"),
                            plan_version=ra["plan_version_id"], run_id=ra["run_id"], status=status, reason=reason)
            done.append((ra["plan_version_id"], status, ra))
    return done


def _verify(ra, st):
    from tcp_ui import store
    out = store.run_path(ra["run_id"], "output")
    read = lambda n: _read(os.path.join(out, n))
    pv = c().store.get("versions", ra["plan_version_id"])
    with open(c().store.blob_path("versions", pv["plan_version_id"], "sme_revision.json"), encoding="utf-8") as f: rev = json.load(f)
    plan, machine = read("plan.json"), read("machine_site_model.json")
    if st["state"] != "FINISHED" or not plan:
        why = (st.get("error") or {}).get("error_code") or ",".join(st.get("reason_codes") or []) or st.get("decision")
        return "DRAFT_GENERATION_FAILED", f"no draft generated ({why})"
    if (plan.get("revision") or {}).get("content_sha256") != rev["content_sha256"]: return "DRAFT_GENERATION_FAILED", "revision hash mismatch"
    if not machine or machine["site_model_id"] != rev["machine_site_model_id"]: return "DRAFT_GENERATION_FAILED", "machine site model mismatch"
    got = sorted([o["object_id"], o["placement"].get("station_m"), o["placement"].get("latitude"), o["placement"].get("longitude")]
                 for o in plan["objects"])
    if got != sorted(rev["expected"]["objects"]): return "DRAFT_GENERATION_FAILED", "generated objects differ from the reviewed proposal"
    if plan.get("status") not in V.SUCCESS: return "DRAFT_GENERATION_FAILED", f"unexpected plan status {plan.get('status')}"
    if plan.get("status") != rev["expected"]["plan_status"]: return "DRAFT_GENERATION_FAILED", "plan status differs from the reviewed proposal"
    return plan["status"], None


def _live_ids():
    """Runs the UI server is currently executing (same process). Empty when no server is loaded (tests run in-process)."""
    import sys
    srv = sys.modules.get("tcp_ui.server")
    try: return srv.live_ids() if srv else set()
    except Exception: return set()


def _read(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return None
