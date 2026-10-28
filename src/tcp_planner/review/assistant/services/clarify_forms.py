"""Structured completion of partially interpreted requests (NO further AI calls).

The interpretation step stores, per operation, a closed form spec: the fields the model already extracted ("known") and
deterministic input fields for what is missing. The SME completes the form; submit() validates every value against the
stored spec (choices / ranges / required) and calls the existing deterministic services (geometry, spatial, rules, TA,
staging). The form spec is read from the stored interpretation record, never from the browser.
"""
import math

from ..core.canonical import now_iso
from ..core.errors import AssistantError
from tcp_planner.review.decision_overlay import FACT_TYPES
from . import findings as F, object_tools as O

CREATE_PREFIX = "__CREATE__:"
_C = {}


def register(c):
    _C["c"] = c


def c():
    return _C["c"]


# ---------------------------------------------------------------- field builders
def choice(name, label, options, default=None, required=True, hint=None):
    return {"name": name, "label": label, "type": "choice", "required": required, "default": default, "hint": hint,
            "options": [o if isinstance(o, dict) else {"value": o, "label": str(o)} for o in options]}


def number(name, label, lo, hi, default=None, required=True, unit=None):
    return {"name": name, "label": label, "type": "number", "required": required, "default": default, "min": lo, "max": hi,
            "unit": unit}


def text(name, label, required=True, max_len=300, hint=None):
    return {"name": name, "label": label, "type": "text", "required": required, "max_length": max_len, "hint": hint}


def entity(objects, original=None, create=False):
    opts = [{"value": o["object_id"], "label": f"{o['object_id']} - {o.get('sign_code') or o['object_type']}"
             + (f" ({o['approach'].replace('_', ' ').lower()})" if o.get("approach") else "")}
            for o in objects if o["object_id"] != "W1"]
    if create and original:
        from ..core.entity_resolution import canonical_new_id
        nid = canonical_new_id(original)
        opts.append({"value": CREATE_PREFIX + nid, "label": f"Create new {nid} (proposed object)"})
    return choice("object_id", "Object", opts)


DIRECTION = choice("direction", "Direction", [{"value": "UPSTREAM", "label": "Upstream", "hint": "against traffic on its approach"},
                                              {"value": "DOWNSTREAM", "label": "Downstream", "hint": "with traffic"}])
UNIT = choice("unit", "Unit", [{"value": "FT", "label": "feet"}, {"value": "M", "label": "metres"}], default="FT")
DISTANCE = number("distance", "Distance", 0.1, 2000, unit="unit")
PRESERVE = choice("preserve_lateral_offset", "Preserve lateral offset",
                  [{"value": True, "label": "Yes (recommended)"}, {"value": False, "label": "No"}], default=True)
RELATION = choice("relation", "Before or after", [{"value": "BEFORE", "label": "Before (reached first by traffic)"},
                                                  {"value": "AFTER", "label": "After"}])
REASON = text("reason", "Engineering reason", required=False, hint="recorded in the change set")


def features_field(fnd):
    return choice("feature_key", "Reference feature",
                  [{"value": f["subject"], "label": f"{f['label']} {f['subject']}" + (f" @ {f['station_m']} m" if f.get('station_m') is not None else "")}
                   for f in fnd if f["category"] == "FEATURE" and f["feature_kind"] != "sidewalks" and f.get("station_m") is not None][:20])


def fact_value_field(field_key, ctx):
    typ = FACT_TYPES[field_key]; label = F.FACTS[field_key][0]
    if typ == "bool": return choice("value", label, [{"value": True, "label": "Yes"}, {"value": False, "label": "No"}])
    if typ == "int": return number("value", label, *F.RANGES[field_key])
    if typ == "float": return number("value", label, *F.RANGES[field_key], unit="m")
    opts = F.ENUMS.get(field_key) or (ctx["rule_pack"].road_types() if field_key == "road.road_type" else [])
    return choice("value", label, opts)


def form(title, target, known, fields, submit_label, note=None):
    return {"title": title, "target": target, "known": known, "fields": fields, "submit_label": submit_label, "note": note,
            "ai_calls_on_submit": 0}


# ---------------------------------------------------------------- submit (deterministic)
def _check(spec, values):
    out = {}
    for f in spec["fields"]:
        v = values.get(f["name"], f.get("default"))
        if v in (None, ""):
            if f["required"]: raise AssistantError("FORM_INCOMPLETE", f"{f['label']} is required.", 400, details={"field": f["name"]})
            continue
        if f["type"] == "choice":
            allowed = [o["value"] for o in f["options"]]
            if v not in allowed: raise AssistantError("FORM_INVALID", f"{f['label']}: choose one of the listed options.", 400,
                                                     details={"field": f["name"]})
        elif f["type"] == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not f["min"] <= v <= f["max"]:
                raise AssistantError("FORM_INVALID", f"{f['label']} must be between {f['min']} and {f['max']}.", 400,
                                     details={"field": f["name"]})
        else:
            v = str(v).strip()[:f.get("max_length", 300)]
        out[f["name"]] = v
    return out


def submit(ident, cid, ctx, tctx, interpretation_id, op_index, values):
    from . import geometry_tools as G, interpret_tools as I
    from .conversations import add_message, _objects
    rec = c().store.get("interpretations", str(interpretation_id or ""))
    if not rec or rec.get("conversation_id") != cid:
        raise AssistantError("NOT_FOUND", "Interpretation not found for this review.", 404)
    rows = (rec["result"].get("operations") or [])
    if not isinstance(op_index, int) or not 0 <= op_index < len(rows) or not rows[op_index].get("form"):
        raise AssistantError("FORM_NOT_FOUND", "There is no form to complete for this operation.", 404)
    spec = rows[op_index]["form"]
    data = {**spec["known"], **_check(spec, values if isinstance(values, dict) else {})}
    mid = rec["message_id"]; tgt = spec["target"]
    c().audit.write("FORM_SUBMITTED", ident, consequential=True, conversation_id=cid, interpretation_id=interpretation_id,
                    op_index=op_index, message_id=mid, target=tgt, model_call=False, fields=sorted(data))
    if str(data.get("object_id", "")).startswith(CREATE_PREFIX):
        nid = data["object_id"][len(CREATE_PREFIX):]
        add_message(cid, "assistant", "STRUCTURED_FORM", {"title": f"Create new {nid}", "open_object_form": nid,
                                                          "text": f"{nid} does not exist. Use the object form to propose it "
                                                                  "(type, purpose and position are required)."})
        return {"open_object_form": nid, "model_call": False}
    reason = data.pop("reason", None)
    if tgt in ("placements/evaluate", "placements/relative"):
        req = {"object_id": data["object_id"], "message_id": mid}
        if tgt == "placements/relative":
            site, plan, _, _ = G.proposal_state(ctx, cid)
            req.update(station_m=G.relative_station(site, plan, data["object_id"], data["feature_key"], data["relation"]),
                       candidate_kind=f"{data['relation']}_FEATURE")
        else:
            req.update({k: data[k] for k in ("direction", "distance", "unit", "preserve_lateral_offset")})
        ev = G.evaluate(ident, cid, ctx, req)
        msg = G.post_evaluation(cid, ev, source="form", reason=reason, message_id=mid)
        return {"evaluation": ev, "message_id": msg["message_id"], "model_call": False}
    if tgt == "decisions":
        payload = {**data, "reason": reason, "message_id": mid}
        r = c().tools.invoke(tctx, "stage_decision", ctx=ctx, cid=cid, payload=payload)
        add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": "Staged site decision",
                    "text": f"Staged {r['key']} (not committed). The impact preview was recalculated deterministically.",
                    "staged_key": r["key"]})
        return {"staged": r["key"], "model_call": False}
    if tgt == "objects":
        cat = data.get("category")
        approved = cat == "SIGN" and data.get("sign_code")
        req = {"object_id": str(data.get("object_id") or "").upper(), "category": cat, "purpose": data.get("purpose"),
               "approval_class": "APPROVED_CATALOG_DEVICE" if approved else "UNAPPROVED_KNOWN_DEVICE",
               "station_m": data.get("station_m"), "side": data.get("side"), "reason": reason, "message_id": mid,
               "sign_code": data.get("sign_code"), "approach": data.get("approach"),
               "confirm_unsupported": data.get("confirm_unsupported") is True}
        r = c().tools.invoke(tctx, "stage_object", ctx=ctx, cid=cid, req=req)
        o = r["object"]
        add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": f"Proposed object {o['object_id']} staged",
                    "text": f"{o['category']} {o['object_id']} at station {o['station_m']} m ({o['side']}), "
                            + ("unsupported by the approved TA-1 catalog - engineering exception staged; not rule-validated."
                               if o["unsupported_by_approved_catalog"] else "approved catalog sign; SME-chosen position.")})
        return {"staged": r["key"], "model_call": False}
    if tgt == "objects/remove":
        r = c().tools.invoke(tctx, "remove_object", ctx=ctx, cid=cid, req={"object_id": data["object_id"], "reason": reason})
        add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": "Removal staged", "text": f"Removal of {data['object_id']} staged (not committed)."})
        return {"staged": r.get("key"), "model_call": False}
    if tgt == "explain":
        fnd = F.derive(ctx, __import__("tcp_planner.review.assistant.services.run_context", fromlist=["x"]).config())
        txt = I.explain(ctx, fnd, _objects(ctx), data["target_id"])
        add_message(cid, "assistant", "DETERMINISTIC_RESULT", {"title": "Explanation (from saved data)", "text": txt})
        return {"explanation": txt, "model_call": False}
    raise AssistantError("FORM_NOT_FOUND", "Unsupported form target.", 400)
