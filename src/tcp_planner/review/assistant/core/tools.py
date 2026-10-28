"""Tool registry. Every deterministic and AI tool runs through invoke(): profile allow-list, backend permission check,
action budget, and a TOOL_INVOCATION audit record (input/output hashes, status, latency, external indicator, model
fields). Mutating tools write a consequential TOOL_STARTED audit event first; if that cannot be written they do not run.
"""
import time

from tcp_planner.contracts import canonical_json, sha256_hex
from . import authz
from .canonical import now_iso
from .errors import AssistantError


def _hash(obj):
    import json
    try: return sha256_hex(canonical_json(obj, drop=()))
    except (TypeError, ValueError):
        return sha256_hex(json.dumps(obj, sort_keys=True, default=lambda o: f"<{type(o).__name__}>"))


class Tool:
    def __init__(self, name, fn, *, version="1", permission="review:read", deterministic=True, mutates=False,
                 requires_confirmation=False, external=False):
        self.name = name; self.fn = fn; self.version = version; self.permission = permission
        self.deterministic = deterministic; self.mutates = mutates
        self.requires_confirmation = requires_confirmation; self.external = external


class ToolContext:
    def __init__(self, identity, profile, audit, conversation_id=None, run_id=None):
        self.identity = identity; self.profile = profile; self.audit = audit
        self.conversation_id = conversation_id; self.run_id = run_id
        self.actions = 0


class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool
        return tool

    def invoke(self, ctx, name, /, **inputs):
        tool = self.tools.get(name)
        if tool is None or name not in (ctx.profile.get("allowed_tools") or ()):
            raise AssistantError("TOOL_NOT_ALLOWED", f"Tool {name!r} is not allowed for this assistant.", 403, False)
        authz.require(ctx.identity, tool.permission)
        ctx.actions += 1
        if ctx.actions > int(ctx.profile.get("max_authorized_actions_per_conversation") or 0):
            raise AssistantError("ACTION_BUDGET_EXCEEDED", "Maximum authorized actions for this request reached.", 429)
        in_hash = _hash(inputs)
        base = {"tool_name": name, "tool_version": tool.version, "conversation_id": ctx.conversation_id,
                "run_id": ctx.run_id, "permissions_used": [tool.permission], "input_sha256": in_hash,
                "deterministic": tool.deterministic, "mutates": tool.mutates, "external_call": tool.external}
        if tool.mutates:
            ctx.audit.write("TOOL_STARTED", ctx.identity, consequential=True, **base)
        started = now_iso(); t0 = time.perf_counter(); status, err, out, meta = "OK", None, None, {}
        try:
            out = tool.fn(ctx, **inputs)
            if isinstance(out, dict) and "_tool_meta" in out: meta = out.pop("_tool_meta")
            return out
        except AssistantError as e:
            status, err = "ERROR", e.code; raise
        except Exception as e:
            status, err = "ERROR", "TOOL_FAILED"
            raise AssistantError("TOOL_FAILED", f"{name} failed ({type(e).__name__}).", 500, details={"tool": name}) from e
        finally:
            ctx.audit.write("TOOL_INVOCATION", ctx.identity, consequential=tool.mutates, **base,
                            started_at=started, ended_at=now_iso(), latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                            status=status, error_code=err, output_sha256=_hash(out) if out is not None else None,
                            retry_count=0, affected_entities=meta.get("affected_entities", []),
                            artifact_refs=meta.get("artifact_refs", []),
                            model_deployment=meta.get("model_deployment", "N/A"),
                            prompt_version=meta.get("prompt_version", "N/A"),
                            guardrail_version=meta.get("guardrail_version", "N/A"),
                            token_usage=meta.get("token_usage", "N/A"),
                            estimated_cost_usd=meta.get("estimated_cost_usd", "N/A"),
                            external_calls=meta.get("external_calls", []))
