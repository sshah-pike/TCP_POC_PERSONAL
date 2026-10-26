"""New / unsupported TCP objects and device removal (deterministic; closed schema; never inferred from free text).

approval_class   APPROVED_CATALOG_DEVICE | UNAPPROVED_KNOWN_DEVICE | SME_DEFINED_OBJECT | PERSONNEL_POSITION | GEOMETRY_ZONE
category         SIGN | PCMS | CONE | CHANNELIZING_DEVICE | TAPER | BUFFER | FLAGGER | PERSONNEL | OTHER
Only approved TA-1 catalog signs (rule pack section 04) can be APPROVED_CATALOG_DEVICE; everything else is an SME
proposed object, rendered with a PROPOSED / EXCEPTION label, never presented as rule-validated, and accepted only through
an explicit SME exception (policy action per category) covering the validator VAL-PROHIBITED-OBJECTS for that object.
"""
import re

from tcp_poc.models import FT, r
from ..core.canonical import now_iso
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.tools import Tool
from . import decisions as D, geometry_tools as G

APPROVAL_CLASSES = ("APPROVED_CATALOG_DEVICE", "UNAPPROVED_KNOWN_DEVICE", "SME_DEFINED_OBJECT", "PERSONNEL_POSITION", "GEOMETRY_ZONE")
CATEGORIES = ("SIGN", "PCMS", "CONE", "CHANNELIZING_DEVICE", "TAPER", "BUFFER", "FLAGGER", "PERSONNEL", "OTHER")
ZONE_CATEGORIES = ("TAPER", "BUFFER")
ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,15}$")
GAPS_UNSUPPORTED = ["object type is not in the approved TA-1 catalog: no rule-pack rule validates it",
                    "no spacing, taper/buffer length, device spacing, visibility or crashworthiness validation",
                    "geometry validator checks only the object position (traveled way, image extent, analysed alignment); "
                    "a zone is checked at its reference point only",
                    "no approved DWT block: drawn as an SME-proposed marker"]
GAPS_APPROVED = ["additional sign outside the TA-1 template: VAL-SIGN expects exactly one advance sign per approach",
                 "position chosen by the SME: Table 6B-1 spacing is not applied (VAL-SPACING / GEO-STATION)"]
_C = {}


def register(c):
    _C["c"] = c
    c.tools.register(Tool("stage_object", _stage_object, permission="review:decide", mutates=True))
    c.tools.register(Tool("remove_object", _remove_object, permission="review:decide", mutates=True))


def c():
    return _C["c"]


def policy_action(approval_class, category):
    if approval_class == "APPROVED_CATALOG_DEVICE": return "add_approved_device"
    if category == "TAPER": return "create_taper"
    if category == "BUFFER": return "create_buffer"
    if approval_class == "PERSONNEL_POSITION" or category in ("FLAGGER", "PERSONNEL"): return "add_personnel_position"
    return "add_unsupported_device"


def _bad(msg, code="OBJECT_INVALID", **d):
    return AssistantError(code, msg, 400, details=d)


def build_spec(ident, ctx, site, plan, req):
    oid = str(req.get("object_id") or "").upper()
    if not ID_RE.match(oid): raise _bad("Object id must look like S3, PCMS1, CONE-1 (A-Z, 0-9, '-' '_').")
    existing = [o["object_id"] for o in (plan or {}).get("objects", [])]
    if oid in existing: raise _bad(f"{oid} already exists; choose a new id or move the existing object.", "OBJECT_EXISTS",
                                   existing_objects=existing)
    ac, cat = req.get("approval_class"), req.get("category")
    if ac not in APPROVAL_CLASSES: raise _bad(f"approval_class must be one of {APPROVAL_CLASSES}.")
    if cat not in CATEGORIES: raise _bad(f"category must be one of {CATEGORIES}.")
    purpose = str(req.get("purpose") or "").strip()[:200]
    if not purpose: raise _bad("A purpose is required for every proposed object.", "PURPOSE_REQUIRED")
    pack = ctx["rule_pack"]; catalog = pack.section("04_sign_catalog")
    if ac == "APPROVED_CATALOG_DEVICE":
        if cat != "SIGN" or req.get("sign_code") not in catalog:
            raise _bad(f"Only signs from the approved TA-1 catalog ({', '.join(catalog)}) can be APPROVED_CATALOG_DEVICE; "
                       f"{cat} is unsupported by the current approved TA-1 catalog.", "UNSUPPORTED_BY_APPROVED_CATALOG")
        if req.get("approach") not in ("INCREASING_STATION", "DECREASING_STATION"):
            raise _bad("An approved sign needs the approach it faces (INCREASING_STATION / DECREASING_STATION).")
    elif req.get("confirm_unsupported") is not True:
        raise AssistantError("UNSUPPORTED_NOT_CONFIRMED", f"{cat} is unsupported by the current approved TA-1 catalog. "
                             "Explicit SME confirmation is required.", 400)
    length = float(site["road"].get("centerline_length_m") or 0)
    st = D._num(req.get("station_m"), -1e6, 1e6)
    if st is None: raise _bad("A proposed position (station_m) is required.", "POSITION_REQUIRED")
    end = req.get("end_station_m")
    if cat in ZONE_CATEGORIES or ac == "GEOMETRY_ZONE":
        end = D._num(end, -1e6, 1e6)
        if end is None or abs(end - st) < 1.0: raise _bad("A zone needs start and end stations at least 1 m apart.", "POSITION_REQUIRED")
    else:
        end = None
    side = req.get("side")
    if side not in ("LEFT", "RIGHT"): raise _bad("side must be LEFT or RIGHT.")
    half = site["road"]["road_edges"].get("left_offset_m")
    if half is None: raise AssistantError("GEOMETRY_UNAVAILABLE", "Road edges unresolved; a position cannot be calculated.", 409, False)
    off = req.get("offset_from_centerline_m")
    off = D._num(off, 0.0, 60.0) if off is not None else half + G.run_context.config()["placement"]["sign_offset_beyond_edge_m"]
    if off is None: raise _bad("offset_from_centerline_m must be between 0 and 60 m.")
    lateral = off if side == "LEFT" else -off
    cov = G.coverage(site, [(st, lateral)] + ([(end, lateral)] if end is not None else []))
    if not cov["covered"]:
        raise AssistantError("OUTSIDE_EVIDENCE_COVERAGE", f"The proposed position is outside the saved evidence coverage "
                             f"(alignment 0-{length:.0f} m). Blocked (non-overridable in this POC).", 409, False, details=cov)
    return {"object_id": oid, "approval_class": ac, "category": cat, "purpose": purpose,
            "label": str(req.get("label") or f"{cat} {oid}")[:80], "sign_code": req.get("sign_code") if ac == "APPROVED_CATALOG_DEVICE" else None,
            "approach": req.get("approach"), "station_m": r(st, 3), "end_station_m": r(end, 3) if end is not None else None,
            "side": side, "lateral_m": r(lateral, 3), "offset_from_centerline_m": r(off, 3), "proposal_id": new_id("obj"),
            "policy_action": policy_action(ac, cat),
            "validation_coverage_gaps": GAPS_APPROVED if ac == "APPROVED_CATALOG_DEVICE" else GAPS_UNSUPPORTED,
            "unsupported_by_approved_catalog": ac != "APPROVED_CATALOG_DEVICE", "message_id": req.get("message_id")}


def _stage_object(tctx, ctx, cid, req):
    ident = tctx.identity
    site, plan, _, _ = G.proposal_state(ctx, cid)
    spec = build_spec(ident, ctx, site, plan, req)
    reason = (req.get("reason") or "").strip()[:500]
    D.authorize(ident, spec["policy_action"], reason)
    mv = {"object_id": spec["object_id"], "current": {"station_m": spec["station_m"]},
          "proposed": {"station_m": spec["station_m"], "offset_m": spec["lateral_m"], "side": spec["side"]},
          "lateral_offset_preserved": True}
    spec["spatial_conflicts"] = [x for x in G.spatial(site, plan, mv) if x["severity"] != "INFORMATIONAL"
                                 and x["relationship"] not in ("FEATURE_BETWEEN_CURRENT_AND_PROPOSED", "PATH_CROSSES_FEATURE")]
    now = now_iso()
    events = [{"type": "stage", "key": f"OBJECT:{spec['object_id']}", "decision": {
        "object": spec, "action": "PROPOSE_OBJECT", "object_id": spec["object_id"], "decision_id": spec["proposal_id"],
        "reason": reason, "decided_by": ident.subject_id, "decided_at": now, "message_id": req.get("message_id"),
        "value": f"{spec['approval_class']}/{spec['category']} @ {spec['station_m']} m"}}]
    if spec["unsupported_by_approved_catalog"]:
        ex = {"exception_id": new_id("exc"), "type": "UNSUPPORTED_OBJECT", "action": spec["policy_action"],
              "check_id": "VAL-PROHIBITED-OBJECTS", "object_ids": [spec["object_id"]], "rule_status": "CONFLICT",
              "requested_by": ident.subject_id, "confirmed_by": ident.subject_id, "confirmed_by_roles": list(ident.roles),
              "approval_mode": "SELF_CONFIRMED_POC", "independent_approval": False, "confirmed_at": now, "scope": "THIS_PLAN_VERSION_ONLY",
              "reason": reason, "rule_pack": ctx["rule_pack_ref"], "validation_coverage_gaps": spec["validation_coverage_gaps"],
              "summary": f"{spec['category']} {spec['object_id']} unsupported by the approved TA-1 catalog",
              "engineering_impact": "The object is not validated by the approved rule pack; VAL-PROHIBITED-OBJECTS stays CONFLICT."}
        events.append({"type": "stage", "key": f"EXCEPTION:OBJECT:{spec['object_id']}", "decision": {
            "exception": ex, "action": "UNSUPPORTED_OBJECT", "decision_id": ex["exception_id"], "reason": reason,
            "decided_by": ident.subject_id, "decided_at": now, "object_id": spec["object_id"]}})
    for e in events: c().store.append_event("conversations", cid, e, durable=True)
    c().audit.write("OBJECT_STAGED", ident, consequential=True, conversation_id=cid, object_id=spec["object_id"],
                    approval_class=spec["approval_class"], category=spec["category"], policy_action=spec["policy_action"],
                    unsupported=spec["unsupported_by_approved_catalog"], approval_mode="SELF_CONFIRMED_POC")
    return {"key": f"OBJECT:{spec['object_id']}", "object": spec, "_tool_meta": {"affected_entities": [spec["object_id"]]}}


def _remove_object(tctx, ctx, cid, req):
    ident = tctx.identity
    site, plan, _, _ = G.proposal_state(ctx, cid)
    oid = str(req.get("object_id") or "")
    G._obj(plan, oid)
    if oid == "W1": raise _bad("W1 (work location from the project input) cannot be removed.", "OBJECT_NOT_REMOVABLE")
    reason = (req.get("reason") or "").strip()[:500]
    D.authorize(ident, "remove_device", reason)
    rec = {"object_id": oid, "reason": reason, "removal_id": new_id("rem")}
    if f"OBJECT:{oid}" in D.staged(cid):  # a staged (uncommitted) proposal is simply withdrawn
        D.unstage(ident, cid, f"OBJECT:{oid}"); D.unstage(ident, cid, f"EXCEPTION:OBJECT:{oid}")
        return {"key": None, "removed_staged_proposal": oid}
    c().store.append_event("conversations", cid, {"type": "stage", "key": f"REMOVE:{oid}", "decision": {
        "removal": rec, "action": "REMOVE_DEVICE", "object_id": oid, "decision_id": rec["removal_id"], "reason": reason,
        "decided_by": ident.subject_id, "decided_at": now_iso()}}, durable=True)
    c().audit.write("OBJECT_REMOVAL_STAGED", ident, consequential=True, conversation_id=cid, object_id=oid)
    return {"key": f"REMOVE:{oid}", "removal": rec}
