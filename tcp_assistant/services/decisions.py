"""Structured SME decisions (buttons / forms -> deterministic backend; zero AI calls).

Staged decisions are append-only conversation events (stage / unstage / staging_reset). Nothing is committed here.
The effective decision set = decisions already applied in the reviewed head run (its sme_revision_applied.json)
overridden by the staged decisions with the same key.
"""
import math

from tcp_planner.review.decision_overlay import FACT_TYPES, FEATURE_KINDS
from tcp_planner.review.action_policy import load_policy, PolicyError
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from . import findings as F

FACT_ACTION_POLICY = {"CONFIRM": "confirm_site_fact", "CORRECT": "correct_site_fact", "MARK_UNRESOLVED": "mark_site_fact_unresolved"}
FEATURE_ACTION_POLICY = {"CONFIRM": "confirm_site_feature", "REJECT": "reject_site_feature", "MODIFY": "modify_site_feature",
                         "ADD": "add_site_feature"}
SIDES = ("LEFT", "RIGHT", "BOTH", "UNKNOWN")
_C = {}


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


def bad(msg, code="DECISION_INVALID", **details):
    return AssistantError(code, msg, 400, details=details)


def policy():
    try: return load_policy()
    except PolicyError as e:
        raise AssistantError(e.code, "SME action policy unavailable; all SME actions are disabled.", 503, False)


def authorize(ident, action_name, reason):
    pol = policy()
    ok, why = pol.allowed(action_name, ident.roles)
    if not ok: raise AssistantError("POLICY_DENIED", why, 403, False, details={"action": action_name, "policy": pol.ref})
    if pol.reason_required(action_name) and not (reason or "").strip():
        raise AssistantError("REASON_REQUIRED", f"A reason is required for {action_name}.", 400, details={"action": action_name})
    return pol


def _num(v, lo, hi, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)): return None
    if integer and int(v) != v: return None
    return v if lo <= v <= hi else None


def normalize(ident, ctx, payload):
    """Validate one structured decision against the head context. Returns (key, decision)."""
    kind = payload.get("type"); action = payload.get("action"); reason = (payload.get("reason") or "").strip()[:500] or None
    base = {"decision_id": new_id("dec"), "decided_by": ident.subject_id, "decided_at": now_iso(),
            "finding_id": payload.get("finding_id"), "reason": reason, "message_id": payload.get("message_id")}
    site, elig = ctx["site_model"], ctx["eligibility"]
    if kind == "FACT":
        fld = payload.get("field")
        if fld not in FACT_TYPES: raise bad(f"Field {fld!r} cannot be decided by the SME.")
        if action not in FACT_ACTION_POLICY: raise bad("Unknown fact action.")
        authorize(ident, FACT_ACTION_POLICY[action], reason)
        cur, _status, *_ = F.fact_value(site, elig, fld)
        d = {**base, "field": fld, "action": action}
        if action == "CONFIRM":
            if cur is None: raise bad("There is no detected value to confirm; select a value instead.")
            d["value"] = cur
        elif action == "CORRECT":
            v = payload.get("value"); typ = FACT_TYPES[fld]
            if typ == "bool" and not isinstance(v, bool): raise bad("Value must be true or false.")
            if typ == "int": v = _num(v, *F.RANGES[fld], integer=True)
            if typ == "float": v = _num(v, *F.RANGES[fld])
            if typ in ("int", "float") and v is None: raise bad(f"Value out of range {F.RANGES[fld]}.")
            if typ == "enum":
                opts = F.ENUMS.get(fld) or (ctx["rule_pack"].road_types() if fld == "road.road_type" else [])
                if v not in opts: raise bad(f"Value must be one of {opts}.")
            if fld == "site.complex_intersection_conflict" and v is False and \
                    ((elig or {}).get("intersection_analysis") or {}).get("features_in_window"):
                raise bad("Intersection features are present near the work. Reject or correct those features instead.",
                          "DECISION_CONTRADICTS_EVIDENCE")
            d["value"] = v
        return f"FACT:{fld}", d
    if kind == "FEATURE":
        if action not in FEATURE_ACTION_POLICY: raise bad("Unknown feature action.")
        authorize(ident, FEATURE_ACTION_POLICY[action], reason)
        length = float(site["road"].get("centerline_length_m") or 0)
        if action == "ADD":
            k = payload.get("kind"); st = _num(payload.get("station_m"), 0.0, length); side = payload.get("side")
            if k not in FEATURE_KINDS: raise bad(f"Feature kind must be one of {FEATURE_KINDS}.")
            if st is None: raise bad(f"Station must be within the analysed alignment 0-{length:.0f} m.", "OUTSIDE_EVIDENCE_COVERAGE")
            if side not in SIDES: raise bad("Side must be LEFT, RIGHT, BOTH or UNKNOWN.")
            d = {**base, "action": "ADD", "kind": k, "station_m": st, "side": side,
                 "description": str(payload.get("description") or "")[:200]}
            return f"FEATURE:ADD:{d['decision_id']}", d
        fk = payload.get("feature_key")
        known = {f["subject"] for f in F.derive(ctx, _cfg()) if f["category"] == "FEATURE" and f["feature_kind"] != "sidewalks"}
        if fk not in known: raise bad(f"Unknown feature {fk!r}.", "ENTITY_NOT_FOUND")
        d = {**base, "action": action, "feature_key": fk}
        if action == "MODIFY":
            st = _num(payload.get("station_m"), 0.0, length); side = payload.get("side")
            if st is None: raise bad(f"Station must be within the analysed alignment 0-{length:.0f} m.", "OUTSIDE_EVIDENCE_COVERAGE")
            if side not in SIDES: raise bad("Side must be LEFT, RIGHT, BOTH or UNKNOWN.")
            d.update(station_m=st, side=side)
        return f"FEATURE:{fk}", d
    if kind == "SIDEWALK":
        side = payload.get("side"); present = payload.get("present")
        if side not in ("LEFT", "RIGHT") or present not in (True, False, None): raise bad("Sidewalk side/presence invalid.")
        authorize(ident, "modify_site_feature", reason or "sidewalk presence decided by SME")
        return f"SIDEWALK:{side}", {**base, "side": side, "present": present, "action": "SET"}
    raise bad("Unknown decision type.")


def _cfg():
    from . import run_context
    return run_context.config()


def stage(ident, cid, ctx, payload):
    key, d = normalize(ident, ctx, payload)
    c().audit.write("DECISION_STAGED", ident, conversation_id=cid, decision_key=key, decision_id=d["decision_id"],
                    action=d.get("action"), finding_id=d.get("finding_id"), run_id=ctx["run_id"], consequential=True)
    c().store.append_event("conversations", cid, {"type": "stage", "key": key, "decision": d, "at": now_iso()}, durable=True)
    return key, d


def unstage(ident, cid, key):
    c().store.append_event("conversations", cid, {"type": "unstage", "key": key, "at": now_iso()}, durable=True)
    c().audit.write("DECISION_UNSTAGED", ident, conversation_id=cid, decision_key=key)


def reset(cid, reason):
    c().store.append_event("conversations", cid, {"type": "staging_reset", "reason": reason, "at": now_iso()}, durable=True)


def staged(cid):
    cur = {}
    for e in c().store.events("conversations", cid):
        if e.get("type") == "staging_reset": cur = {}
        elif e.get("type") == "stage": cur[e["key"]] = e["decision"]
        elif e.get("type") == "unstage": cur.pop(e["key"], None)
    return cur


def base_decisions(ctx):
    """Decisions already applied in the reviewed head run (cumulative), keyed like staged ones."""
    applied = ((ctx.get("sme_revision_applied") or {}).get("decisions")) or {}
    out = {}
    for d in applied.get("facts") or []: out[f"FACT:{d['field']}"] = d
    for d in applied.get("features") or []:
        out[f"FEATURE:ADD:{d['decision_id']}" if d["action"] == "ADD" else f"FEATURE:{d['feature_key']}"] = d
    for d in applied.get("sidewalks") or []: out[f"SIDEWALK:{d['side']}"] = d
    return out


def to_doc(by_key):
    facts = sorted((d for k, d in by_key.items() if k.startswith("FACT:")), key=lambda d: d["field"])
    feats = sorted((d for k, d in by_key.items() if k.startswith("FEATURE:")), key=lambda d: (d.get("feature_key") or "", d["decision_id"]))
    sws = sorted((d for k, d in by_key.items() if k.startswith("SIDEWALK:")), key=lambda d: d["side"])
    return {"facts": facts, "features": feats, "sidewalks": sws}


def effective(ctx, cid):
    """(combined decision doc, staged-only dict)."""
    st = staged(cid)
    combined = dict(base_decisions(ctx)); combined.update(st)
    return to_doc(combined), st
