"""Local run storage and read-only state for the UI.

runs/<run_id>/input/   uploaded KML (as supplied)
runs/<run_id>/output/  the pipeline's --out directory (file names exactly as the pipeline writes them)
runs/<run_id>/ui/      UI-only metadata as state records (run_records.py): request.state.json, process.state.json,
                       events.events.jsonl, result.state.json, ...; stdout.log stays a plain log. Runs made before S2 keep
                       ui/*.json and are read-only (run_records.is_legacy).

Everything here is derived from what the pipeline recorded (telemetry spans, written files, its result
and exit code). Nothing is inferred, defaulted or re-decided.
"""
import base64, datetime, json, os, re, secrets

from tcp_planner.config import settings
from tcp_planner.config.settings import PROJECT_ROOT, CONFIG_DIR, VAR_DIR
from tcp_planner.storage import run_records as records, stores, uploads

PRICING_PATH = os.path.join(CONFIG_DIR, "pricing.json")
RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")
OPTION_KEY_RE = re.compile(r"^[A-Za-z0-9_.]+$")
MAX_KML_UPLOAD_BYTES = 6 * 1024 * 1024  # above the pipeline's own 5 MB limit, so it rejects oversize files itself

# Names accepted by tcp_planner.imagery.map_provider.get_map_provider / tcp_planner.ai.vision_provider.get_vision_provider.
MAP_PROVIDERS = ("azure_maps", "usgs_naip", "esri_demo")
AI_PROVIDERS = ("anthropic", "foundry")
# Offered in the UI form. USGS NAIP and the direct Anthropic API are not in use for this POC; their code stays
# (and the CLI still accepts them), but the form only offers the providers in use.
UI_MAP_PROVIDERS = ("azure_maps",)
UI_AI_PROVIDERS = ("foundry",)

# Pipeline stages -> the telemetry spans app.run_pipeline already emits, and the files each stage writes.
STAGES = (
    ("input", "Input", ("tcp.input.parse",), ("project_geometry.json",)),
    ("rule_pack", "Rule Pack", ("tcp.rulepack.load",), ()),
    ("imagery", "Imagery", ("tcp.map.retrieve",), ()),
    ("osm", "OSM", ("tcp.osm.resolve",), ()),
    ("vision", "AI Vision", ("tcp.vision.analyze",), ()),
    ("fusion", "Fusion", ("tcp.site.fuse",), ("site_model.json",)),
    ("eligibility", "Eligibility", ("tcp.site.eligibility",), ("eligibility_result.json",)),
    ("rules", "Rules / Placement", ("tcp.rules.execute", "tcp.geometry.place"), ()),
    ("validation", "Validation", ("tcp.plan.validate",), ("validation_results.json",)),
    ("render", "Render / Export", ("tcp.debug.render", "tcp.sheet.render", "tcp.dwt.render"),
     ("plan.json", "aerial_image.jpg", "debug_plan.png", "debug_plan.pdf", "sheet_aerial.jpg", "tcp_sheet.png",
      "tcp_sheet.pdf", "plan.dxf", "plan.dwg", "dwt_result.json")),
)
# reason codes that mean a service/API failure (not a site-fact discrepancy). They never change the decision shown
# (REVIEW_REQUIRED stays REVIEW_REQUIRED, exit 3): a run lists them as `service_error` and the UI shows a badge (S3, Q12-B)
ERROR_REASON_CODES = {"MAP_CONTEXT_UNAVAILABLE", "OSM_CONTEXT_UNAVAILABLE", "AI_OBSERVATION_UNAVAILABLE",
                      "AI_CALL2_UNAVAILABLE", "CROPS_UNAVAILABLE"}


def service_codes(codes):
    """The service/API failure codes among reason codes (sorted, no duplicates); empty when there are none."""
    return sorted({c for c in codes or () if c in ERROR_REASON_CODES})


EXIT_DECISION = {0: "SUPPORTED_AUTO", 3: "REVIEW_REQUIRED", 4: "UNSUPPORTED_POC",
                 5: "DRAFT_WITH_ENGINEERING_EXCEPTION"}  # 5: SME revision runs only
RUN_STOPPED = "RUN_STOPPED"  # error code written by the server when the user stops a run


class BadRequest(Exception):
    pass


def runs_dir():
    return settings.runs_dir()


def run_path(run_id, *parts):
    if not RUN_ID_RE.match(run_id or ""): raise BadRequest("invalid run id")
    return os.path.join(runs_dir(), run_id, *parts)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f: json.dump(obj, f, indent=2, sort_keys=True)


# ------------------------------------------------------------------ new run
def _safe_filename(name):
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip(" .")
    return base or "input.kml"


def reserve_run_id():
    """A fresh run id. Nothing is created: the project orchestrator records it first and builds the run afterwards, so a
    crash in between leaves an id that the next attempt completes (S3)."""
    while True:
        run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        if not os.path.exists(run_path(run_id)): return run_id


def ensure_run_dirs(run_id, subdirs=("input", "output", "ui")):
    rdir = run_path(run_id)
    for sub in subdirs: os.makedirs(os.path.join(rdir, sub), exist_ok=True)
    return rdir


def new_run_dirs(subdirs=("input", "output", "ui")):
    """Allocate a new, unique run directory (runs/<id>/...)."""
    while True:
        run_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        rdir = run_path(run_id)
        try: os.makedirs(rdir)
        except FileExistsError: continue
        for sub in subdirs: os.makedirs(os.path.join(rdir, sub))
        return run_id, rdir


def advanced_args(adv, online):
    """CLI flags and the request's `advanced` record for the form's advanced settings (shared by plain runs and the
    zone runs of a project). Validates the shape only; the server checks which AI profiles are available."""
    argv = []
    if online:  # the CLI ignores provider flags in offline mode; do not pretend otherwise
        if adv.get("map_provider"):
            if adv["map_provider"] not in MAP_PROVIDERS: raise BadRequest("unknown map provider")
            argv += ["--map-provider", adv["map_provider"]]
        if adv.get("ai_provider"):
            if adv["ai_provider"] not in AI_PROVIDERS: raise BadRequest("unknown AI provider")
            argv += ["--ai-provider", adv["ai_provider"]]
    if adv.get("ai_profile"):  # Foundry model profile (deployment registry entry), validated by the server
        if not online: raise BadRequest("AI profile applies to live runs only")
        argv += ["--ai-provider", "foundry"] if "--ai-provider" not in argv else []
    if adv.get("evidence_mode") not in (None, "", "single", "multi"):
        raise BadRequest("evidence_mode must be single or multi")
    if adv.get("no_dwt") is True: argv += ["--no-dwt"]
    elif adv.get("dwt_mode"):
        if adv["dwt_mode"] not in ("PLAN", "AERIAL_BASE"): raise BadRequest("dwt_mode must be PLAN or AERIAL_BASE")
        argv += ["--dwt-mode", adv["dwt_mode"]]
    return argv, {"ai_profile": (adv.get("ai_profile") or None) if online else None,
                  "evidence_mode": adv.get("evidence_mode") or "single",
                  "map_provider": (adv.get("map_provider") or None) if online else None,
                  "ai_provider": (adv.get("ai_provider") or None) if online else None,
                  "dwt_mode": None if adv.get("no_dwt") is True else (adv.get("dwt_mode") or None),
                  "no_dwt": adv.get("no_dwt") is True}


def create_run(payload, offline_scenarios):
    """Validate the form payload (shape only), store inputs and build the CLI argv. Returns (run_id, run_dir)."""
    if not isinstance(payload, dict): raise BadRequest("JSON object expected")
    itype = payload.get("input_type")
    if itype not in ("kml", "coordinates", "offline"): raise BadRequest("input_type must be kml, coordinates or offline")
    run_id, rdir = new_run_dirs()
    out_dir = f"{run_id}/output"  # run-relative key (D-77)
    argv, request = [], {"input_type": itype}

    if itype == "kml":
        f = payload.get("kml") or {}
        try: raw = base64.b64decode(f.get("content_base64") or "", validate=True)
        except ValueError: raise BadRequest("KML content is not valid base64")
        if not raw: raise BadRequest("KML file is empty")
        if len(raw) > MAX_KML_UPLOAD_BYTES: raise BadRequest("KML upload too large")
        name = _safe_filename(f.get("filename"))
        ref = uploads.store_upload(stores.artifacts(), run_id, name, raw)  # key <run_id>/input/<slug>.kml
        argv += ["--kml", ref.uri]  # a run-relative key; the worker resolves it under the runs folder (D-77)
        request.update(kml_filename=name, kml_size_bytes=len(raw), kml_key=ref.uri)
    elif itype == "coordinates":
        lat, lon = str(payload.get("lat", "")).strip(), str(payload.get("lon", "")).strip()
        if not lat or not lon: raise BadRequest("latitude and longitude are required")
        argv += [f"--lat={lat}", f"--lon={lon}"]  # parsed and range-checked by the pipeline itself
    else:
        sc = payload.get("offline_scenario")
        if sc not in offline_scenarios: raise BadRequest("unknown offline scenario")
        oi = payload.get("offline_input") or "coordinates"
        if oi not in ("coordinates", "kml"): raise BadRequest("offline_input must be coordinates or kml")
        argv += ["--offline", sc, "--offline-input", oi]
        request.update(offline_scenario=sc, offline_input=oi)

    op = payload.get("operator") or {}
    if op.get("road_type"): argv += ["--road-type", str(op["road_type"])]
    if op.get("speed") not in (None, ""):
        try: argv += ["--speed", str(int(op["speed"]))]
        except (TypeError, ValueError): raise BadRequest("speed must be an integer")
    if op.get("requires_lane_closure") is True: argv += ["--requires-lane-closure"]
    options = []
    for o in op.get("options") or []:
        k, v = str(o.get("key", "")).strip(), str(o.get("value", "")).strip()
        if not k and not v: continue
        if not OPTION_KEY_RE.match(k) or v == "": raise BadRequest(f"invalid option {k!r}: use KEY=VALUE")
        argv += ["--option", f"{k}={v}"]; options.append(f"{k}={v}")

    adv = payload.get("advanced") or {}
    online = itype != "offline"
    flags, adv_request = advanced_args(adv, online)
    argv += flags
    argv += ["--out", out_dir]

    request.update(operator={"road_type": op.get("road_type") or None,
                             "speed": int(op["speed"]) if op.get("speed") not in (None, "") else None,
                             "requires_lane_closure": op.get("requires_lane_closure") is True,
                             "options": options},
                   advanced=adv_request)
    records.create(run_id, "request", {"run_id": run_id, "created_at": _now(), "argv": argv, "request": request})
    return run_id, rdir


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


# ------------------------------------------------------------------ state
def _events(run_id):
    return records.events(run_id)


def _spans(events):
    spans, open_ = [], {}
    for e in events:
        if e.get("event") == "span_start":
            s = {"name": e["name"], "started_at": e["t"], "ended_at": None, "status": None, "duration_ms": None,
                 "attributes": dict(e.get("attributes") or {})}
            spans.append(s); open_[e["name"]] = s
        elif e.get("event") == "span_end" and e.get("name") in open_:
            s = open_.pop(e["name"])
            s.update(ended_at=e["t"], status=e.get("status"), duration_ms=e.get("duration_ms"))
            s["attributes"].update(e.get("attributes") or {})
    return spans


def _log_lines(ui):
    from tcp_planner.audit.provider_diagnostics import sanitize
    try:
        with open(os.path.join(ui, "stdout.log"), encoding="utf-8", errors="replace") as f:
            return [sanitize(ln) for ln in f.read().splitlines()]
    except OSError:
        return []


def _stage_messages(lines):
    """Map the pipeline's own numbered console lines ('1 Input: ...', '6 SiteModel ...') to stages."""
    msgs = {i: [] for i in range(1, len(STAGES) + 1)}; cur = None
    for ln in lines:
        m = re.match(r"^(\d{1,2}) \S", ln)
        if m and 1 <= int(m.group(1)) <= len(STAGES):
            cur = int(m.group(1)); msgs[cur].append(ln[len(m.group(1)) + 1:])
        elif cur and ln.startswith("   "):
            msgs[cur].append(ln.strip())
        else:
            cur = None
    return msgs


def _stage_outcome(key, attrs):
    """(status, problems) from the attributes the pipeline recorded on the stage's spans."""
    a = attrs
    if key == "input" and a.get("decision") == "UNSUPPORTED_POC":
        return "UNSUPPORTED", [f"decision={a['decision']}", f"reason_codes={a.get('reason_codes')}"]
    if key in ("imagery", "osm") and a.get("error_code"):
        return "ERROR", [f"error_code={a['error_code']}"]
    if key == "vision" and a.get("status_code") not in (None, "OK"):
        return "ERROR", [f"status_code={a['status_code']}"]
    if key == "fusion" and (a.get("conflicts") or a.get("inputs_complete") is False):
        return "WARNING", [f"conflicts={a.get('conflicts')}", f"inputs_complete={a.get('inputs_complete')}"]
    if key == "eligibility" and a.get("decision") in ("REVIEW_REQUIRED", "UNSUPPORTED_POC"):
        svc = service_codes(str(a.get("reason_codes") or "").split(","))
        problems = [f"decision={a['decision']}", f"reason_codes={a.get('reason_codes')}"]
        if svc: problems.append(f"service_error={','.join(svc)}")
        return ("REVIEW" if a["decision"] == "REVIEW_REQUIRED" else "UNSUPPORTED"), problems
    if key == "rules" and a.get("issues"):
        return "WARNING", [f"placement issues={a['issues']}"]
    if key == "validation" and (a.get("rule") != "PASS" or a.get("geometry") != "PASS"):
        return "REVIEW", [f"rule={a.get('rule')}", f"geometry={a.get('geometry')}"]
    if key == "render":
        probs = []
        if a.get("dwt") not in (None, "RENDERED", "SKIPPED_NO_DWT_CONFIG"): probs.append(f"DWT: {a['dwt']}")
        if a.get("sheet") == "SKIPPED_NO_SHEET_TEMPLATE": probs.append("TCP sheet: SKIPPED_NO_SHEET_TEMPLATE")
        if a.get("sheet_aerial"): probs.append(f"sheet aerial: {a['sheet_aerial']}")
        if probs: return "WARNING", probs
    return "COMPLETED", []


def _outputs(out_dir):
    try: names = sorted(os.listdir(out_dir))
    except OSError: return []
    return [{"name": n, "size_bytes": os.path.getsize(os.path.join(out_dir, n))}
            for n in names if os.path.isfile(os.path.join(out_dir, n))]


def build_state(run_id, live_ids=(), with_lineage=True):
    rdir = run_path(run_id); ui = os.path.join(rdir, "ui")
    req = records.read(run_id, "request")
    if req is None: return None
    proc = records.read(run_id, "process") or {}
    result = records.read(run_id, "result")
    pack = records.read(run_id, "rule_pack")
    finished = proc.get("state") == "FINISHED"
    state = "FINISHED" if finished else "RUNNING" if run_id in live_ids else "INTERRUPTED"
    done = state != "RUNNING"

    events = _events(run_id); spans = _spans(events)
    ev_events = [e for e in events if e.get("event") == "evidence"]
    calls = records.read(run_id, "calls")
    if calls is None and records.read(run_id, "deps") is not None:
        calls = []  # call tracking was active and no provider call was made (e.g. everything reused)
    lines = _log_lines(ui); msgs = _stage_messages(lines)
    diags = records.read(run_id, "diagnostics", []) or []
    index = {x["name"]: x for x in (result or {}).get("output_index") or []}  # SHA-256 of each output file (S3)
    outputs = [dict(o, sha256=(index.get(o["name"]) or {}).get("sha256")) for o in _outputs(os.path.join(rdir, "output"))]
    have = {o["name"] for o in outputs}

    stages, claimed, last_started = [], set(), None
    for i, (key, title, span_names, files) in enumerate(STAGES, start=1):
        ss = [s for s in spans if s["name"] in span_names]
        attrs = {}
        for s in ss:  # sheet and DWT spans both use status_code; keep them apart
            rename = {"tcp.sheet.render": "sheet", "tcp.dwt.render": "dwt"}.get(s["name"])
            for k, v in s["attributes"].items():
                attrs[rename if (rename and k == "status_code") else k] = v
        problems = []
        if not ss:
            status = "NOT_RUN" if done else "WAITING"
        elif any(s["ended_at"] is None for s in ss) or (not done and len(ss) < len(span_names)):
            status = "FAILED" if done else "RUNNING"
            if done: problems.append("stage did not complete (process ended)")
        elif any(s["status"] == "ERROR" for s in ss):
            status = "FAILED"; problems += [f"error.code={s['attributes'].get('error.code')}" for s in ss if s["status"] == "ERROR"]
        else:
            status, problems = _stage_outcome(key, attrs)
        if ss: last_started = i - 1
        arts = [f for f in files if f in have] if ss else []
        claimed.update(arts)
        started = [s["started_at"] for s in ss]; ended = [s["ended_at"] for s in ss if s["ended_at"]]
        durs = [s["duration_ms"] for s in ss if s["duration_ms"] is not None]
        stages.append({"index": i, "key": key, "title": title, "status": status,
                       "started_at": min(started) if started else None,
                       "ended_at": max(ended) if ended and len(ended) == len(ss) else None,
                       "duration_ms": round(sum(durs), 1) if ss and len(durs) == len(ss) else None,
                       "spans": ss, "messages": msgs.get(i, []), "problems": problems, "artifacts": arts,
                       "diagnostics": [d for d in diags if d.get("span") in span_names],
                       "reuse": [{"kind": e["kind"], "artifact_id": e.get("source_artifact_id"), "source_run": e.get("source_run"),
                                  "sha256": e.get("sha256"), "api_call": False} for e in ev_events
                                 if e.get("action") == "reused" and e.get("span") in span_names],
                       "reuse_rejected": [{"kind": e["kind"], "reason": e.get("reason"), "source_run": e.get("source_run")}
                                          for e in ev_events if e.get("action") == "reuse_rejected" and e.get("span") in span_names],
                       "new_calls": [c for c in (calls or []) if c.get("span") in span_names and c.get("external")],
                       # AI Vision only: the two-call agent's steps (tcp.agent.* spans), live while they run
                       "steps": [sp for sp in spans if key == "vision" and sp["name"].startswith("tcp.agent.")]})
    # files written by a stage that stopped the run early (e.g. eligibility_result.json from Input) belong to it
    orphans = sorted(have - claimed - {"run_report.txt"})
    if orphans and last_started is not None: stages[last_started]["artifacts"] += orphans

    exit_code = proc.get("exit_code")
    error = None
    if result and result.get("error"): error = result["error"]
    elif proc.get("unhandled_error"): error = proc["unhandled_error"]
    if finished:
        decision = (result or {}).get("decision") or EXIT_DECISION.get(exit_code) or "FAILED"
        if error or exit_code not in EXIT_DECISION: decision = "FAILED"
        if (error or {}).get("error_code") == RUN_STOPPED: decision = "STOPPED"
        if error is None and decision == "FAILED":
            # argparse usage errors print the usage banner first; its own "error:" line is the message
            shown = [ln for ln in lines if ": error: " in ln] or [ln for ln in lines if ln.strip()][-3:]
            error = {"error_code": f"EXIT_CODE_{exit_code}", "message": "\n".join(shown) or "no output"}
    elif state == "INTERRUPTED":
        decision = "FAILED"; error = {"error_code": "RUN_INTERRUPTED", "message": "runner stopped without finishing (UI server restarted?)"}
    else:
        decision = None
    elig = (result or {}).get("eligibility") or _read_json(os.path.join(rdir, "output", "eligibility_result.json"))
    reason_codes = (result or {}).get("reason_codes") or (elig or {}).get("reason_codes") or []
    service_error = service_codes(reason_codes) or None  # a badge, never a different decision (Q12-B)
    draft = decision == "SUPPORTED_AUTO" and exit_code == 0 and "plan.json" in have
    plan_status = (result or {}).get("plan_status")  # SME revision runs only
    if plan_status == "DRAFT_WITH_ENGINEERING_EXCEPTION" and exit_code == 5 and "plan.json" in have and not error:
        decision, draft = plan_status, True

    span_total = round(sum(s["duration_ms"] or 0 for s in spans), 1)
    return {
        "run_id": run_id, "created_at": req.get("created_at"), "request": req.get("request"),
        "state": state, "started_at": proc.get("started_at"), "ended_at": proc.get("ended_at"),
        "runtime_ms": proc.get("runtime_ms"), "exit_code": exit_code,
        "decision": decision,
        "reason_codes": reason_codes, "service_error": service_error,
        "message": (elig or {}).get("message"), "error": error,
        "stages": stages, "span_total_ms": span_total,
        "rule_pack": pack, "plan": {"plan_id": (result or {}).get("plan_id"), "plan_hash": (result or {}).get("plan_hash")},
        "selected_ta": (elig or {}).get("selected_typical_application"),
        "dwt": (result or {}).get("dwt"),
        "draft_generated": draft, "outputs": outputs, "log": lines,
        "tls": records.read(run_id, "tls"),
        "cost": cost_summary(req, spans, records.read(run_id, "usage", []), have, calls, ev_events),
        "evidence": _evidence_list(run_id),
        "evidence_compat": _compat(run_id, {"stages": stages}),
        "lineage": _lineage(run_id, ev_events, done) if with_lineage else None,
        "sme_revision": _sme_revision(run_id, rdir, plan_status),
    }


def _sme_revision(run_id, rdir, plan_status):
    """SME revision lineage (revision runs only; None otherwise)."""
    resume = records.read(run_id, "resume") or {}
    if not resume.get("sme_revision"): return None
    return {**resume["sme_revision"], "strict_replay": resume.get("strict_replay"), "plan_status": plan_status,
            "machine_site_model": os.path.isfile(os.path.join(rdir, "output", "machine_site_model.json"))}


def _compat(run_id, partial_state):
    """partial_state carries the stages already built here, so evidence_compat never re-enters build_state."""
    from tcp_planner.orchestration.run_relations import evidence_compat
    try: return evidence_compat(run_id, partial_state)
    except Exception: return None


def _evidence_list(run_id):
    from tcp_planner.storage.evidence_store import load_manifest
    return [{k: e.get(k) for k in ("artifact_id", "kind", "mode", "file", "sha256", "size_bytes", "producer_span",
                                   "produced_by_run", "source_run", "source_artifact_id", "created_at")}
            for e in load_manifest(run_id)]


def _lineage(run_id, ev_events, done):
    resume = records.read(run_id, "resume")
    if not resume: return None
    from tcp_planner.orchestration.run_relations import actual_stage
    parent = build_state(resume["parent_run_id"], with_lineage=False) if os.path.isdir(run_path(resume["parent_run_id"])) else None
    return {**{k: resume.get(k) for k in ("parent_run_id", "requested_stage", "reuse_kinds", "ai_provider", "ai_profile",
                                         "comparison_id", "preview")},
            "actual_stage": actual_stage(resume, ev_events) if done else None,
            "parent_cost": parent["cost"] if parent else None,
            "parent_decision": parent["decision"] if parent else None}


# ------------------------------------------------------------------ cost / usage
def load_pricing():
    return _read_json(PRICING_PATH, {}) or {}


def _priced(model, usage, pricing, provider="anthropic"):
    """Estimated USD for one call from configured per-million-token prices, or (None, reason)."""
    p = ((pricing.get(provider) or {}).get(model or "")) or {}
    need = {"input_tokens": "input_per_mtok", "output_tokens": "output_per_mtok",
            "cache_creation_input_tokens": "cache_write_per_mtok", "cache_read_input_tokens": "cache_read_per_mtok"}
    total = 0.0
    for tok_key, price_key in need.items():
        n = usage.get(tok_key) or 0
        if not n: continue
        if p.get(price_key) is None: return None, f"no configured price '{price_key}' for {model}"
        total += n * float(p[price_key]) / 1_000_000
    return total, None


def cost_summary(req, spans, usage_calls, have, calls=None, ev_events=()):
    pricing = load_pricing(); offline = (req.get("request") or {}).get("input_type") == "offline"
    by = {s["name"]: s for s in spans}
    ai_calls = [c for c in usage_calls if c.get("usage")]
    tokens = {}
    for c in ai_calls:
        for k, v in c["usage"].items():
            if isinstance(v, int): tokens[k] = tokens.get(k, 0) + v
    est, reasons = 0.0, []
    for c in ai_calls:
        v, why = _priced(c.get("response_model"), c["usage"], pricing, c.get("provider") or "anthropic")
        if v is None: reasons.append(why); est = None; break
        est += v
    vision = by.get("tcp.vision.analyze")
    if ai_calls:
        ai_note = None if est is not None else "; ".join(reasons)
    elif usage_calls:
        ai_note = "AI call failed before usage was reported (" + ", ".join(c.get("error") or "?" for c in usage_calls) + ")"
    elif vision:
        ai_note = f"no AI API call was made (vision status {vision['attributes'].get('status_code')}, " \
                  f"provider {vision['attributes'].get('provider')})"
    else:
        ai_note = "vision stage did not run"
    ai = {"calls": len(usage_calls),
          "models": sorted({c.get("response_model") or c.get("requested_model") for c in usage_calls} - {None}),
          "usage": tokens or None, "provider_reported_cost_usd": None,
          "estimated_cost_usd": round(est, 6) if (ai_calls and est is not None) else None,
          "note": ai_note}

    map_span = by.get("tcp.map.retrieve")
    reused = {}
    for e in ev_events:
        if e.get("action") == "reused": reused.setdefault(e["kind"], set()).add(e.get("source_run"))
    if calls is not None:  # recorded provider calls (runs with evidence tracking): reused artifacts are not calls
        map_requests = sum(c.get("requests", 1) for c in calls if c.get("service") == "map" and c.get("external"))
        osm_requests = sum(c.get("requests", 1) for c in calls if c.get("service") == "osm" and c.get("external"))
    else:
        map_requests = 0 if offline else (1 if map_span else 0) + (1 if ("sheet_aerial.jpg" in have or (
            by.get("tcp.sheet.render") or {}).get("attributes", {}).get("sheet_aerial")) else 0)
        osm_requests = 1 if (by.get("tcp.osm.resolve") and not offline) else 0

    map_breakdown = ", ".join(f"{c.get('purpose') or c.get('span')}: {c.get('requests', 1)}" for c in (calls or [])
                              if c.get("service") == "map" and c.get("external"))

    def note(kind, offline_note, live_note, n):
        if kind in reused and not n:
            return "reused artifact from run " + ", ".join(sorted(x for x in reused[kind] if x)) + " - no new provider call"
        return offline_note if offline else live_note
    services = [
        {"service": "Imagery", "provider": (map_span or {}).get("attributes", {}).get("provider"),
         "requests": map_requests, "new_api_call": map_requests > 0, "reused_from": sorted(reused.get("map", ())),
         "cost_usd": None, "note": note("map", "offline synthetic image, no external call",
                                        "provider does not report usage cost to the pipeline" +
                                        (f" - requests: {map_breakdown}" if map_breakdown else ""), map_requests)},
        {"service": "OpenStreetMap", "provider": "OSM API", "requests": osm_requests, "new_api_call": osm_requests > 0,
         "reused_from": sorted(reused.get("osm", ())), "cost_usd": None,
         "note": note("osm", "offline synthetic data, no external call", "public API; no cost reported", osm_requests)},
    ]
    ai["reused_from"] = sorted(reused.get("ai", ()))
    ai["new_api_call"] = bool(usage_calls)
    if offline:
        total_note = "offline synthetic run: no external services were called"
    elif ai["estimated_cost_usd"] is not None:
        total_note = f"AI estimate only (USD {ai['estimated_cost_usd']:.6f}); imagery/OSM cost not reported"
    else:
        total_note = "no reliable cost data recorded"
    return {"ai": ai, "services": services, "total_cost_usd": None, "total_note": total_note,
            "pricing_source": pricing.get("source")}


def list_runs(live_ids=()):
    d = runs_dir()
    try: ids = sorted((n for n in os.listdir(d) if RUN_ID_RE.match(n)), reverse=True)
    except OSError: return []
    out = []
    for rid in ids:
        st = build_state(rid, live_ids)
        if not st: continue
        r = st["request"] or {}
        proj = r.get("project") or {}
        label = {"kml": f"KML: {r.get('kml_filename')}", "coordinates": "Coordinates",
                 "offline": f"Offline: {r.get('offline_scenario')}",
                 "zone": f"Zone {proj.get('zone_id')}"}.get(r.get("input_type"), "?")
        out.append({"run_id": rid, "created_at": st["created_at"], "input": label, "state": st["state"],
                    "decision": st["decision"], "service_error": bool(st["service_error"]), "runtime_ms": st["runtime_ms"],
                    "project_id": proj.get("project_id"), "zone_id": proj.get("zone_id"),
                    "zone_version": proj.get("zone_version"),
                    "rule_pack": f"{st['rule_pack']['id']} v{st['rule_pack']['version']}" if st["rule_pack"] else None,
                    "estimated_cost_usd": st["cost"]["ai"]["estimated_cost_usd"],
                    "parent_run_id": (st["lineage"] or {}).get("parent_run_id"),
                    "requested_stage": (st["lineage"] or {}).get("requested_stage"),
                    "comparison_id": (st["lineage"] or {}).get("comparison_id")})
    return out
