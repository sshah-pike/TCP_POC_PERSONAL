"""Phase 3 tools: stage structured SME decisions and preview their complete deterministic impact (no AI)."""
from ..core.tools import Tool
from . import decisions, preview

_C = {}


def register(c):
    _C["c"] = c
    c.tools.register(Tool("stage_decision", _stage, permission="review:decide", mutates=True))
    c.tools.register(Tool("preview_site_decisions", _preview, permission="review:read"))


def _stage(tctx, ctx, cid, payload):
    key, d = decisions.stage(tctx.identity, cid, ctx, payload)
    return {"key": key, "decision": d, "_tool_meta": {"affected_entities": [d.get("field") or d.get("feature_key") or key]}}


def _preview(tctx, ctx, decision_doc, revision_extra=None):
    return {"preview": preview.compute(ctx, decision_doc, revision_extra)}
