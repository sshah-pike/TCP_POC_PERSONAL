"""Immutable site-evidence versions, plan versions and resume attempts with lineage heads.

Records are create-only; lifecycle is append-only events. Heads ("se:<lineage>", "pv:<lineage>") move only by
compare-and-set from the parent the SME reviewed, so a concurrent/stale confirmation fails (VERSION_CONFLICT).
Plan-version status: PROPOSED_REVISION -> DRAFT_COMPLIANT | DRAFT_WITH_ENGINEERING_EXCEPTION | DRAFT_GENERATION_FAILED.
A failed regeneration never affects the parent version; each retry is a new resume-attempt record.
"""
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..repositories.base import ImmutableExists

SUCCESS = ("DRAFT_COMPLIANT", "DRAFT_WITH_ENGINEERING_EXCEPTION")
_C = {}


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


def _head(key):
    return (c().store.head(key) or {}).get("value")


def se_head(lk):
    hid = _head(f"se-{lk}")
    return c().store.get("site-evidence", hid) if hid else None


def pv_head(lk):
    hid = _head(f"pv-{lk}")
    return c().store.get("versions", hid) if hid else None


def status(pv):
    evs = [e for e in c().store.events("versions", pv["plan_version_id"]) if e.get("type") in ("status", "resume_started")]
    if evs and evs[-1]["type"] == "resume_started": return "REGENERATING"  # an attempt is running; no result yet
    evs = [e for e in evs if e["type"] == "status"]
    return evs[-1]["status"] if evs else pv["status"]


def plan_version_view(pv):
    return {**pv, "current_status": status(pv), "events": c().store.events("versions", pv["plan_version_id"]),
            "resume_attempts": [a for a in c().store.list("resume-attempts") if a["plan_version_id"] == pv["plan_version_id"]]}


def lineage(lk):
    pvs = sorted((p for p in c().store.list("versions") if p.get("lineage_key") == lk), key=lambda p: p["version_number"])
    ses = sorted((s for s in c().store.list("site-evidence") if s.get("lineage_key") == lk), key=lambda s: s["version_number"])
    def run_of(p):
        evs = [e for e in c().store.events("versions", p["plan_version_id"]) if e.get("run_id")]
        return evs[-1]["run_id"] if evs else p.get("run_id")
    return {"plan_versions": [{**{k: p.get(k) for k in ("plan_version_id", "parent_version_id", "version_number",
                                                        "change_set_id", "site_evidence_version", "created_by_type",
                                                        "created_at", "active_exceptions")}, "run_id": run_of(p),
                               "status": status(p)} for p in pvs],
            "site_evidence_versions": [{k: s.get(k) for k in ("site_evidence_version", "parent_version", "version_number",
                                                             "kind", "effective_site_model_id", "change_set_id", "created_at")}
                                       for s in ses],
            "plan_head": _head(f"pv-{lk}"), "site_evidence_head": _head(f"se-{lk}")}


def head_run(conv):
    """Run of the newest successfully generated plan version of this lineage (else None -> base run)."""
    pvs = sorted((p for p in c().store.list("versions") if p.get("lineage_key") == conv["lineage_key"]),
                 key=lambda p: p["version_number"], reverse=True)
    for p in pvs:
        evs = [e for e in c().store.events("versions", p["plan_version_id"]) if e.get("type") == "status"]
        if evs and evs[-1]["status"] in SUCCESS and evs[-1].get("run_id"): return evs[-1]["run_id"]
        if not evs and p["status"] in SUCCESS and p.get("run_id"): return p["run_id"]
    return None


def _id(prefix, lk, n):
    return f"{prefix}-{lk[:8]}-v{n}"


def next_numbers(lk):
    se, pv = se_head(lk), pv_head(lk)
    return (se["version_number"] + 1 if se else 1), (pv["version_number"] + 1 if pv else 1)


def create(collection, rid, rec):
    try:
        return c().store.create(collection, rid, rec)
    except ImmutableExists:
        raise AssistantError("VERSION_CONFLICT", "A version with this id already exists; review again.", 409)
    except OSError as e:
        raise AssistantError("VERSION_WRITE_FAILED", "The version could not be saved; nothing was changed.", 500,
                             details={"reason": type(e).__name__})


def move_head(kind, lk, expected, new):
    if not c().store.compare_and_set_head(f"{kind}-{lk}", expected, new):
        raise AssistantError("VERSION_CONFLICT", "The lineage changed since your review (another version was created). "
                                                 "Review again.", 409)


def add_status(pv_id, status_value, **extra):
    c().store.append_event("versions", pv_id, {"type": "status", "status": status_value, "at": now_iso(), **extra}, durable=True)
