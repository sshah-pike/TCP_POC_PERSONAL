"""Natural-language interpretation (the ONLY AI boundary of the SME Review Assistant).

1. input limits + rate limit + deterministic screening (security / harmful / clearly unrelated -> no model call)
2. minimal active-TCP context (ids, labels, current values, operation catalog; no coordinates, keys, paths)
3. exactly ONE bounded model call (profile: max_calls_per_message=1, retry NONE, timeout, output-size limit)
4. model output is untrusted: exact closed schema, unknown fields rejected, ids / enums / units / ranges validated,
   operations checked against SME_ACTION_POLICY and the caller's role, ambiguity -> deterministic clarification
5. nothing is staged or committed by the model: the SME applies each validated operation with a structured action
   (deterministic tools), then the full final review + exact hash confirmation.
"""
import collections, hashlib, json, os, re, threading, time

from tcp_poc.sme_overlay import FACT_TYPES
from ..core.canonical import now_iso, canonical_text, message_hash
from ..core.errors import AssistantError
from ..core.ids import new_id
from ..core.tools import Tool
from ..flags import CONFIG_DIR, PACKAGE_DIR
from ..model import provider as MP
from . import decisions as D, findings as F, object_tools as O

PROMPT_ID = "sme_intent_v1"
OPS = ("SET_SITE_FACT", "CONFIRM_SITE_FACT", "MARK_FACT_UNRESOLVED", "CONFIRM_FEATURE", "REJECT_FEATURE", "SET_SIDEWALK",
       "MOVE_DEVICE", "PLACE_DEVICE_RELATIVE", "PROPOSE_OBJECT", "REMOVE_DEVICE", "EXPLAIN")
INTENTS = ("CORRECT_SITE_FACT", "RESOLVE_FINDING", "MODIFY_OBJECT", "PROPOSE_OBJECT", "EXPLAIN", "REQUEST_REVISION", "CLARIFY",
           "OUT_OF_SCOPE")
OP_POLICY = {"SET_SITE_FACT": "correct_site_fact", "CONFIRM_SITE_FACT": "confirm_site_fact",
             "MARK_FACT_UNRESOLVED": "mark_site_fact_unresolved", "CONFIRM_FEATURE": "confirm_site_feature",
             "REJECT_FEATURE": "reject_site_feature", "SET_SIDEWALK": "modify_site_feature", "MOVE_DEVICE": "move_existing_device",
             "PLACE_DEVICE_RELATIVE": "move_existing_device", "REMOVE_DEVICE": "remove_device"}
_RATE = collections.defaultdict(collections.deque)
_LOCK = threading.Lock()
_C = {}


def register(c):
    _C["c"] = c
    c.tools.register(Tool("interpret_sme_instruction", _interpret_tool, permission="message:submit", deterministic=False,
                          external=True))


def c():
    return _C["c"]


def guardrails():
    with open(os.path.join(CONFIG_DIR, "sme_review_guardrails_v1.json"), encoding="utf-8") as f: return json.load(f)


def prompt():
    with open(os.path.join(PACKAGE_DIR, "prompts", f"{PROMPT_ID}.txt"), encoding="utf-8") as f: txt = f.read()
    return txt, hashlib.sha256(txt.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- strict schema (no nullable unions: Claude/GPT safe)
def _op_schema():
    s = lambda: {"type": "string"}
    return {"type": "object", "additionalProperties": False,
            "required": ["operation", "target_id", "value_text", "direction", "distance", "unit", "preserve_lateral_offset",
                         "relation", "relation_target_id", "object_category", "side", "purpose_text"],
            "properties": {"operation": {"type": "string", "enum": list(OPS)}, "target_id": s(), "value_text": s(),
                           "direction": {"type": "string", "enum": ["UPSTREAM", "DOWNSTREAM", "NONE"]},
                           "distance": {"type": "number"}, "unit": {"type": "string", "enum": ["FT", "M", "NONE"]},
                           "preserve_lateral_offset": {"type": "string", "enum": ["YES", "NO", "UNSPECIFIED"]},
                           "relation": {"type": "string", "enum": ["BEFORE", "AFTER", "NONE"]}, "relation_target_id": s(),
                           "object_category": {"type": "string", "enum": list(O.CATEGORIES) + ["NONE"]},
                           "side": {"type": "string", "enum": ["LEFT", "RIGHT", "NONE"]}, "purpose_text": s()}}


def schema():
    arr = lambda: {"type": "array", "items": {"type": "string"}}
    return {"type": "object", "additionalProperties": False,
            "required": ["intent", "in_scope", "referenced_finding_ids", "referenced_entity_ids", "operations", "assumptions",
                         "ambiguities", "missing_information", "interpretation_confidence", "needs_clarification"],
            "properties": {"intent": {"type": "string", "enum": list(INTENTS)}, "in_scope": {"type": "boolean"},
                           "referenced_finding_ids": arr(), "referenced_entity_ids": arr(),
                           "operations": {"type": "array", "items": _op_schema()}, "assumptions": arr(), "ambiguities": arr(),
                           "missing_information": arr(), "interpretation_confidence": {"type": "number"},
                           "needs_clarification": {"type": "boolean"}}}


def _check(value, sch, path="$"):
    """Exact validation of the closed schema (unknown fields rejected)."""
    t = sch.get("type")
    if t == "object":
        if not isinstance(value, dict): raise ValueError(f"{path}: object expected")
        extra = set(value) - set(sch["properties"])
        if extra: raise ValueError(f"{path}: unknown fields {sorted(extra)}")
        for k in sch["required"]:
            if k not in value: raise ValueError(f"{path}.{k}: missing")
        for k, v in value.items(): _check(v, sch["properties"][k], f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list) or len(value) > 20: raise ValueError(f"{path}: array (max 20) expected")
        for i, v in enumerate(value): _check(v, sch["items"], f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str) or len(value) > 500: raise ValueError(f"{path}: string (max 500) expected")
        if "enum" in sch and value not in sch["enum"]: raise ValueError(f"{path}: {value!r} not allowed")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) > 1e7:
            raise ValueError(f"{path}: number expected")
    elif t == "boolean":
        if not isinstance(value, bool): raise ValueError(f"{path}: boolean expected")


# ---------------------------------------------------------------- deterministic screening
def screen(text):
    g = guardrails(); low = text.lower()
    for kind, key in (("HARMFUL", "harmful_patterns"), ("SECURITY", "injection_patterns")):
        for pat in g[key]:
            if re.search(pat, low): return kind, g["security_message" if kind == "SECURITY" else "harmful_message"]
    domain = any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low) for t in g["domain_terms"])
    if not domain and any(re.search(p, low) for p in g["unrelated_patterns"]): return "OUT_OF_SCOPE", g["out_of_scope_message"]
    return None, None


def rate_limited(session_id, limit):
    now = time.time()
    with _LOCK:
        q = _RATE[session_id]
        while q and now - q[0] > 600: q.popleft()
        if len(q) >= limit: return True
        q.append(now)
    return False


# ---------------------------------------------------------------- minimal context (no coordinates / keys / paths)
def context_for_model(ctx, fnd, objects):
    feats = [f for f in fnd if f["category"] == "FEATURE"]
    return {"objects": [{"id": o["object_id"], "type": o["object_type"], "sign_code": o.get("sign_code"),
                         "approach": o.get("approach")} for o in objects],
            "site_fact_fields": [{"field": k, "label": F.FACTS[k][0], "current_value": F.fact_value(ctx["site_model"], ctx["eligibility"], k)[0]}
                                 for k in FACT_TYPES],
            "features": [{"feature_key": f["subject"], "type": f["feature_kind"], "side": f.get("side"), "state": f["state"]}
                         for f in feats][:60],
            "findings": [{"finding_id": f["finding_id"], "label": f["label"], "state": f["state"], "value": str(f.get("value"))[:60]}
                         for f in fnd if f["requires_review"]][:40],
            "operation_catalog": list(OPS), "object_categories": list(O.CATEGORIES),
            "typical_application": ctx["rule_pack"].selected_ta(),
            "taper_or_buffer_in_plan": False}


def _sanitize_for_prompt(text):
    return text.replace("<", "‹").replace(">", "›")


# ---------------------------------------------------------------- post-validation (deterministic)
def _parse_value(field, txt, ctx=None):
    typ = FACT_TYPES[field]; t = (txt or "").strip()
    if typ == "bool":
        low = t.lower()
        if low in ("true", "yes", "present", "y"): return True
        if low in ("false", "no", "absent", "none", "n"): return False
        raise ValueError("yes/no value expected")
    if typ == "int": return int(float(t))
    if typ == "float": return float(t)
    v = t.upper().replace(" ", "_")
    opts = F.ENUMS.get(field) or (ctx["rule_pack"].road_types() if (ctx and field == "road.road_type") else [])
    if v not in opts: raise ValueError(f"value must be one of {opts}")   # unknown enum text -> completion form
    return v


def validate_ops(ident, ctx, fnd, objects, out):
    """-> list of {status: READY | NEEDS_CLARIFICATION | REJECTED, op, structured, clarification, form, resolution, reason}.
    Entity references resolve deterministically (exact -> case-insensitive -> known ID format); missing fields become a
    stored structured form that is completed WITHOUT another model call (services/clarify_forms.py)."""
    from ..core import entity_resolution as ER
    from . import clarify_forms as CF
    pol = D.policy(); obj_ids = [o["object_id"] for o in objects]
    movable = [o for o in objects if o["object_id"] != "W1"]
    feat_keys = [f["subject"] for f in fnd if f["category"] == "FEATURE"]
    finding_ids = [f["finding_id"] for f in fnd]
    res = []
    for op in out["operations"]:
        row = {"op": op, "status": "READY", "structured": None, "clarification": None, "form": None, "reason": None,
               "resolution": None}

        def clarify(msg, buttons, form=None):
            row.update(status="NEEDS_CLARIFICATION", clarification={"message": msg, "buttons": buttons})
            if form: row["form"] = form

        def reject(msg): row.update(status="REJECTED", reason=msg)
        kind = op["operation"]; tid_raw = op["target_id"]; tid = tid_raw.strip()
        act = OP_POLICY.get(kind)
        if kind == "PROPOSE_OBJECT":
            cat = op["object_category"]
            act = O.policy_action("APPROVED_CATALOG_DEVICE" if cat == "SIGN" else "UNAPPROVED_KNOWN_DEVICE", cat if cat != "NONE" else "OTHER")
        if act:
            ok, why = pol.allowed(act, ident.roles)
            if not ok: reject(f"Not permitted: {why}"); res.append(row); continue

        if kind in ("SET_SITE_FACT", "CONFIRM_SITE_FACT", "MARK_FACT_UNRESOLVED"):
            r = ER.resolve(tid, list(FACT_TYPES)); row["resolution"] = r
            if not r["resolved_entity_id"]:
                reject(f"{tid!r} is not an SME-decidable site fact."); res.append(row); continue
            fld = r["resolved_entity_id"]
            a = {"SET_SITE_FACT": "CORRECT", "CONFIRM_SITE_FACT": "CONFIRM", "MARK_FACT_UNRESOLVED": "MARK_UNRESOLVED"}[kind]
            s = {"route": "decisions", "payload": {"type": "FACT", "field": fld, "action": a}}
            if a == "CORRECT":
                try: s["payload"]["value"] = _parse_value(fld, op["value_text"], ctx)
                except (ValueError, TypeError):
                    clarify(f"Which value should {F.FACTS[fld][0]} have?", [],
                            CF.form(f"Complete site-fact correction: {F.FACTS[fld][0]}", "decisions",
                                    {"type": "FACT", "field": fld, "action": "CORRECT"},
                                    [CF.fact_value_field(fld, ctx), CF.REASON], "Stage correction"))
            row["structured"] = s

        elif kind in ("CONFIRM_FEATURE", "REJECT_FEATURE"):
            r = ER.resolve(tid, feat_keys); row["resolution"] = r; fk = r["resolved_entity_id"]
            if not fk:
                clarify(f"Feature {tid!r} does not exist. Which feature did you mean?",
                        [{"label": k, "feature_key": k} for k in sorted(feat_keys)][:12],
                        CF.form("Select the feature", "decisions", {"type": "FEATURE", "action": kind.split("_")[0]},
                                [CF.choice("feature_key", "Feature", sorted(feat_keys)), CF.REASON], "Stage decision"))
            row["structured"] = {"route": "decisions", "payload": {"type": "FEATURE", "action": kind.split("_")[0], "feature_key": fk or tid}}

        elif kind == "SET_SIDEWALK":
            side = op["side"]
            v = op["value_text"].strip().lower()
            present = True if v in ("present", "yes", "true") else False if v in ("absent", "no", "false", "none") else None
            if side == "NONE":
                clarify("Which side of the road?", [{"label": "LEFT", "side": "LEFT"}, {"label": "RIGHT", "side": "RIGHT"}],
                        CF.form("Complete sidewalk decision", "decisions", {"type": "SIDEWALK", "present": present},
                                [CF.choice("side", "Side", ["LEFT", "RIGHT"]), CF.REASON], "Stage decision"))
            row["structured"] = {"route": "decisions", "payload": {"type": "SIDEWALK", "side": side, "present": present}}

        elif kind in ("MOVE_DEVICE", "PLACE_DEVICE_RELATIVE", "REMOVE_DEVICE"):
            r = ER.resolve(tid, obj_ids); row["resolution"] = r; oid = r["resolved_entity_id"]
            if oid == "W1" and kind != "REMOVE_DEVICE": oid = None
            known, fields = {}, []
            if not oid:
                creatable = ER.looks_like_device_id(tid) and r["resolution_method"] == ER.NOT_FOUND
                if r["resolution_method"] == ER.AMBIGUOUS:
                    msg = f"{tid!r} matches more than one object ({', '.join(r['candidates'])}). Which one?"
                else:
                    msg = f"{tid or 'That object'} does not exist in the current plan. Did you mean one of: {', '.join(o['object_id'] for o in movable)}?"
                buttons = [{"label": f"Use {o['object_id']}", "target_id": o["object_id"]} for o in movable]
                if creatable: buttons.append({"label": f"Create new {ER.canonical_new_id(tid)}", "create_object_id": ER.canonical_new_id(tid)})
                fields.append(CF.entity(movable, tid, create=creatable))
                row["entity_message"] = msg
            else:
                known["object_id"] = oid
            if kind == "REMOVE_DEVICE":
                row["structured"] = {"route": "objects/remove", "payload": {"object_id": oid or tid}}
                if fields: clarify(row["entity_message"], buttons, CF.form("Select the object to remove", "objects/remove", known,
                                                                          fields + [CF.REASON], "Stage removal"))
            elif kind == "MOVE_DEVICE":
                if op["direction"] != "NONE": known["direction"] = op["direction"]
                else: fields.append(CF.DIRECTION)
                if 0 < op["distance"] <= 2000: known["distance"] = op["distance"]
                else: fields.append(CF.DISTANCE)
                if op["unit"] != "NONE": known["unit"] = op["unit"]
                else: fields.append(CF.UNIT)
                if op["preserve_lateral_offset"] != "UNSPECIFIED": known["preserve_lateral_offset"] = op["preserve_lateral_offset"] == "YES"
                else: row["assumption"] = "lateral offset preserved (default)"
                row["structured"] = {"route": "placements", "payload": {
                    "object_id": oid or tid, "direction": op["direction"], "distance": op["distance"], "unit": op["unit"],
                    "preserve_lateral_offset": op["preserve_lateral_offset"] != "NO"}}
                if fields:
                    if "preserve_lateral_offset" not in known: fields.append(CF.PRESERVE)
                    missing = [f["label"].lower() for f in fields if f["name"] != "preserve_lateral_offset"]
                    clarify(row.get("entity_message") or f"Please specify {', '.join(missing)} for moving {oid}.",
                            buttons if not oid else [{"label": "UPSTREAM", "direction": "UPSTREAM"}, {"label": "DOWNSTREAM", "direction": "DOWNSTREAM"},
                                                     {"label": "feet", "unit": "FT"}, {"label": "metres", "unit": "M"}],
                            CF.form("Complete movement request", "placements/evaluate", known, fields, "Validate proposed movement",
                                    "Movement is calculated along the saved road alignment; nothing is applied until you stage and confirm it."))
            else:  # PLACE_DEVICE_RELATIVE
                ref = op["relation_target_id"].strip()
                if ref.lower() in ("taper", "buffer") or ref.upper().startswith(("TAPER", "BUFFER")):
                    reject("There is no taper or buffer in the current TA-1 plan; a position relative to it cannot be calculated.")
                    res.append(row); continue
                if op["relation"] != "NONE": known["relation"] = op["relation"]
                else: fields.append(CF.RELATION)
                fr = ER.resolve(ref, feat_keys); row["feature_resolution"] = fr
                if fr["resolved_entity_id"]: known["feature_key"] = fr["resolved_entity_id"]
                else: fields.append(CF.features_field(fnd))
                row["structured"] = {"route": "placements/relative", "payload": {"object_id": oid or tid, "relation": op["relation"],
                                                                                "feature_key": fr["resolved_entity_id"] or ref}}
                if fields:
                    msg = row.get("entity_message") or ("Before or after which feature?" if "relation" not in known else
                                                        f"Feature {ref!r} does not exist. Which feature did you mean?")
                    clarify(msg, buttons if not oid else ([{"label": "BEFORE"}, {"label": "AFTER"}] if "relation" not in known else
                                                          [{"label": k, "relation_target_id": k} for k in sorted(feat_keys)][:12]),
                            CF.form("Complete relative placement", "placements/relative", known, fields, "Calculate position"))
            if not oid: row["structured"] = None   # an unknown object is never turned into an applicable action

        elif kind == "PROPOSE_OBJECT":
            cat = op["object_category"]
            supported = cat == "SIGN"
            nid = ER.canonical_new_id(tid) if ER.looks_like_device_id(tid) else ""
            row["structured"] = {"route": "objects", "payload": {"object_id": nid, "category": cat,
                                 "approval_class": "APPROVED_CATALOG_DEVICE" if supported else "UNAPPROVED_KNOWN_DEVICE",
                                 "side": op["side"] if op["side"] != "NONE" else None, "purpose": op["purpose_text"]}}
            ref = (op["relation_target_id"] or tid or "").lower()
            pre = ("There is no taper or buffer in the current TA-1 plan, so a position relative to it cannot be calculated. "
                   if ("taper" in ref or "buffer" in ref) else "")
            unsup = "" if supported else f"{cat if cat != 'NONE' else 'This object'} is unsupported by the current approved TA-1 catalog and would be an engineering exception. "
            clarify(pre + unsup + "Enter the position (station, side) and purpose in the object form.",
                    [{"label": "Open object form", "open_object_form": True}],
                    CF.form("Complete proposed object", "objects",
                            {k: v for k, v in (("object_id", nid), ("category", None if cat == "NONE" else cat)) if v},
                            ([] if nid else [CF.text("object_id", "New object id (e.g. S3, PCMS1)", max_len=16)]) +
                            ([] if cat != "NONE" else [CF.choice("category", "Object type", list(O.CATEGORIES))]) +
                            ([CF.choice("sign_code", "Approved sign", list(ctx["rule_pack"].section("04_sign_catalog"))),
                              CF.choice("approach", "Faces approach", ["INCREASING_STATION", "DECREASING_STATION"])] if supported else
                             [CF.choice("confirm_unsupported", "Engineering exception",
                                        [{"value": True, "label": "I confirm this unsupported object as a plan-specific engineering exception"}],
                                        required=cat != "NONE")]) +
                            [CF.number("station_m", "Station (m along the analysed road)", 0, 100000),
                             CF.choice("side", "Side", ["LEFT", "RIGHT"], default=None if op["side"] == "NONE" else op["side"]),
                             CF.text("purpose", "Purpose"), CF.text("reason", "Engineering reason")],
                            "Stage proposed object", "Unsupported objects are engineering exceptions and are never shown as rule-validated."))

        elif kind == "EXPLAIN":
            r = ER.resolve(tid, finding_ids + obj_ids + list(FACT_TYPES) + feat_keys); row["resolution"] = r
            if not r["resolved_entity_id"]:
                opts = [{"value": f["finding_id"], "label": f["label"]} for f in fnd if f["requires_review"]][:10] + \
                       [{"value": o, "label": o} for o in obj_ids]
                clarify("Which finding or object should be explained?", [{"label": f["label"], "target_id": f["finding_id"]}
                                                                         for f in fnd if f["requires_review"]][:10],
                        CF.form("Select what to explain", "explain", {}, [CF.choice("target_id", "Finding or object", opts)], "Explain"))
            row["structured"] = {"route": "explain", "payload": {"target_id": r["resolved_entity_id"] or tid}}
        res.append(row)
    return res


def explain(ctx, fnd, objects, tid):
    """Deterministic explanation built from saved structured data (never model-generated facts)."""
    f = next((x for x in fnd if tid in (x["finding_id"], x["subject"], x.get("entity_id"))), None)
    if f:
        return (f"{f['label']} ({f['finding_id']}): value {f.get('value')}, state {f['state']}, severity {f['severity']}. "
                f"Evidence: {', '.join(str(s) for s in f.get('evidence_sources') or []) or '-'}. "
                f"Reason: {f.get('reason') or f.get('reason_code') or 'n/a'}."
                + (f" Rule: {f['rule_id']} - {f.get('rule_text')}" if f.get("rule_id") else ""))
    o = next((x for x in objects if x["object_id"] == tid), None)
    if o: return f"{o['object_id']} is a {o['object_type']} {o.get('sign_code') or ''} for approach {o.get('approach')} at station {o['station_m']} m."
    return f"No saved information for {tid}."


# ---------------------------------------------------------------- tool
def _interpret_tool(tctx, ctx, cid, text, message):
    ident = tctx.identity; prof = tctx.profile; mcfg = prof["model"]
    from .conversations import _objects
    fnd = F.derive(ctx, __import__("tcp_assistant.services.run_context", fromlist=["x"]).config())
    objects = _objects(ctx)
    sysmsg, prompt_sha = prompt()
    payload = {"active_context": context_for_model(ctx, fnd, objects)}
    user = ("ACTIVE CONTEXT (data):\n" + json.dumps(payload, sort_keys=True, ensure_ascii=False) +
            "\n\n<sme_message>\n" + _sanitize_for_prompt(canonical_text(text)) + "\n</sme_message>")
    meta = {"model_deployment": None, "prompt_version": PROMPT_ID, "guardrail_version": prof["guardrail_version"]}
    provider = MP.get_provider(prof)
    meta["model_deployment"] = getattr(provider, "deployment", None)
    t0 = time.perf_counter()
    try:
        r = provider.complete_structured(sysmsg, user, schema(), mcfg["timeout_s"])   # exactly one call, no retry
    except MP.ModelError as e:
        return {"status": "MODEL_UNAVAILABLE", "error": {"code": e.code, "message": e.message},
                "_tool_meta": {**meta, "token_usage": e.usage or "N/A", "external_calls": [{"service": "foundry_text", "count": 1}]}}
    usage = r.get("usage") or {}
    meta.update(token_usage=usage or "N/A", external_calls=[{"service": "foundry_text", "count": 1}],
                estimated_cost_usd=_cost(r.get("model"), usage))
    raw = r.get("text") or ""
    if len(raw) > mcfg["max_output_chars"]:
        return {"status": "REJECTED_OUTPUT", "error": {"code": "MODEL_OUTPUT_TOO_LARGE", "message": "model output exceeded the limit"},
                "_tool_meta": meta}
    try:
        out = json.loads(raw); _check(out, schema())
    except (ValueError, TypeError) as e:
        return {"status": "REJECTED_OUTPUT", "error": {"code": "MODEL_SCHEMA_INVALID", "message": str(e)[:300]}, "_tool_meta": meta}
    if not out["in_scope"] or out["intent"] == "OUT_OF_SCOPE":
        return {"status": "OUT_OF_SCOPE", "interpretation": out, "message": guardrails()["out_of_scope_message"], "_tool_meta": meta}
    rows = validate_ops(ident, ctx, fnd, objects, out)
    unknown_ids = [i for i in out["referenced_finding_ids"] if i not in {f["finding_id"] for f in fnd}]
    ambiguous = out["needs_clarification"] or out["ambiguities"] or out["missing_information"] or unknown_ids
    status = ("NEEDS_CLARIFICATION" if ambiguous or any(x["status"] == "NEEDS_CLARIFICATION" for x in rows)
              else "REJECTED" if rows and all(x["status"] == "REJECTED" for x in rows) else "READY")
    for x in rows:
        if x["structured"] and x["structured"]["route"] == "explain" and x["status"] == "READY":
            x["explanation"] = explain(ctx, fnd, objects, x["structured"]["payload"]["target_id"])
    return {"status": status, "interpretation": out, "operations": rows, "unknown_finding_ids": unknown_ids,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "model": r.get("model"), "request_id": r.get("request_id"),
            "prompt_sha256": prompt_sha, "_tool_meta": meta}


def _cost(model, usage):
    try:
        from tcp_ui.store import load_pricing, _priced
        v, _ = _priced(model, usage or {}, load_pricing(), "foundry")
        return round(v, 6) if v is not None else "N/A"
    except Exception:
        return "N/A"


# ---------------------------------------------------------------- message entry point
def submit(ident, cid, ctx, tctx, text):
    from .conversations import add_message
    prof = tctx.profile; lim = prof["limits"]
    if not isinstance(text, str) or not text.strip(): raise AssistantError("BAD_REQUEST", "Message text is required.")
    if len(text) > lim["max_message_chars"]:
        raise AssistantError("MESSAGE_TOO_LONG", f"Messages are limited to {lim['max_message_chars']} characters.", 413)
    if rate_limited(ident["session_id"], lim["messages_per_10_min"]):
        raise AssistantError("RATE_LIMITED", "Too many messages; wait a few minutes.", 429)
    msg = add_message(cid, "user", "USER_TEXT", {}, text=text, ident=ident)   # full text stored ONLY in the conversation
    refs = {"conversation_id": cid, "message_id": msg["message_id"], "message_sha256": msg["message_sha256"]}
    kind, reply = screen(canonical_text(text))
    from . import assistant_state as AS
    qid = None if kind else AS.match_question(canonical_text(text))
    if kind:
        c().audit.write("MESSAGE_SCREENED", ident, consequential=True, screening=kind, model_call=False, **refs)
        res = {"status": {"SECURITY": "REJECTED_SECURITY", "HARMFUL": "REJECTED_HARMFUL"}.get(kind, kind), "message": reply,
               "operations": [], "model_call": False}
    elif qid:  # active-draft question answered from saved structured data: no model call
        res = {"status": "ANSWERED", "question_id": qid, "message": AS.answer(ident, cid, ctx, qid), "operations": [],
               "model_call": False, "answer_source": "DETERMINISTIC_TEMPLATE"}
    else:
        res = c().tools.invoke(tctx, "interpret_sme_instruction", ctx=ctx, cid=cid, text=text, message=msg)
        res["model_call"] = True
    iid = new_id("int")
    rec = {k: v for k, v in res.items() if not k.startswith("_")}
    c().store.create("interpretations", iid, {"interpretation_id": iid, **refs, "created_at": now_iso(),
                                              "created_by": ident.subject_id, "prompt_version": PROMPT_ID,
                                              "guardrail_version": prof["guardrail_version"], "result": rec})
    resolutions = [{k: (o.get("resolution") or {}).get(k) for k in ("original_reference", "normalized_reference",
                                                                    "resolved_entity_id", "resolution_method")}
                   for o in res.get("operations") or [] if o.get("resolution")]
    c().audit.write("INTERPRETATION", ident, consequential=True, interpretation_id=iid, status=res["status"],
                    entity_resolutions=resolutions, forms=[i for i, o in enumerate(res.get("operations") or []) if o.get("form")],
                    model_call=res["model_call"], prompt_version=PROMPT_ID, guardrail_version=prof["guardrail_version"], **refs)
    add_message(cid, "assistant", "INTERPRETATION", {"interpretation_id": iid, "message_id": msg["message_id"], **rec})
    return {"message": {k: msg[k] for k in ("message_id", "message_sha256", "canonicalization_version", "created_at")},
            "interpretation_id": iid, **rec}
