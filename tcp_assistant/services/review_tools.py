"""Phase 2 tools: run context, findings, annotated image, conversations with chat review cards (no AI)."""
from tcp_planner.contracts import canonical_json, sha256_hex
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.tools import Tool
from . import findings as F, run_context, annotated_image

_C = {}


def register(c):
    _C["c"] = c
    for t in (Tool("load_run_context", load_run_context), Tool("list_review_findings", list_review_findings),
              Tool("generate_annotated_image", generate_annotated_image, permission="review:read", mutates=True),
              Tool("get_annotated_image", get_annotated_image, permission="artifact:read")):
        c.tools.register(t)


def c():
    return _C["c"]


# ---------------------------------------------------------------- tools
def load_run_context(tctx, run_id):
    ctx = run_context.load(run_id)
    return {"ctx": ctx, "_tool_meta": {"affected_entities": [run_id]}}


def list_review_findings(tctx, ctx, site_model=None):
    cfg = run_context.config()
    view = dict(ctx); view["site_model"] = site_model or ctx["site_model"]
    return {"findings": F.derive(view, cfg)}


def generate_annotated_image(tctx, ctx, site_model, findings, plan=None, extra_items=(), purpose="SITE_UNDERSTANDING",
                             site_evidence_version=None, plan_version_id=None):
    """Create (or reuse an identical) immutable annotated-image artifact. The source image is never modified."""
    src = ctx["evidence"]["map"]
    inputs = {"renderer": annotated_image.RENDERER_VERSION, "source_sha256": src["sha256"],
              "site_model_id": site_model["site_model_id"], "plan_hash": (plan or {}).get("plan_hash"),
              "findings": sha256_hex(canonical_json([{k: f.get(k) for k in ("finding_id", "state", "value", "status")} for f in findings])),
              "extra": sha256_hex(canonical_json(list(extra_items), drop=())), "purpose": purpose}
    inputs_sha = sha256_hex(canonical_json(inputs))
    for a in c().store.list("artifacts"):
        if a.get("kind") == "ANNOTATED_SITE_IMAGE" and a.get("inputs_sha256") == inputs_sha:
            return {"artifact": a, "reused": True, "_tool_meta": {"artifact_refs": [a["artifact_id"]]}}
    png, items, box = annotated_image.render(ctx, site_model, findings, plan, extra_items)
    aid = new_id("art")
    try:
        blob = c().store.put_blob("artifacts", aid, "annotated.png", png)
        rec = c().store.create("artifacts", aid, {
            "schema": "tcp-annotated-image-v1", "artifact_id": aid, "kind": "ANNOTATED_SITE_IMAGE", "purpose": purpose,
            "created_at": now_iso(), "created_by": tctx.identity.subject_id, "run_id": ctx["run_id"],
            "lineage_key": ctx["lineage_key"], "renderer_version": annotated_image.RENDERER_VERSION,
            "source_image": {"run_id": src["origin_run"], "artifact_id": src["origin_artifact_id"], "sha256": src["sha256"],
                             "note": "original saved image, unchanged"},
            "inputs": inputs, "inputs_sha256": inputs_sha, "site_evidence_version": site_evidence_version,
            "plan_version_id": plan_version_id, "file": "annotated.png", "png_sha256": blob["sha256"],
            "size_bytes": blob["size_bytes"], "crop_box_px": box, "items": items, "not_assessed": list(F.NOT_ASSESSED),
            "authoritative": False, "note": "Review artifact. Structured site facts and geometry remain authoritative."})
    except Exception as e:
        raise AssistantError("ARTIFACT_WRITE_FAILED", "The review image could not be saved.", 500, details={"reason": type(e).__name__})
    return {"artifact": rec, "reused": False, "_tool_meta": {"artifact_refs": [aid]}}


def get_annotated_image(tctx, artifact_id):
    a = c().store.get("artifacts", artifact_id)
    if not a: raise AssistantError("NOT_FOUND", "Artifact not found.", 404)
    return {"artifact": a}
