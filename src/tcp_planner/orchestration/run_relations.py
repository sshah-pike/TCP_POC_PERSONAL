"""Resumed runs and model comparisons (new runs linked to an immutable source run).

A resumed run re-executes the unchanged pipeline (tcp_planner.orchestration.pipeline.main) with the parent's input. Only external
evidence (map imagery, OSM elements, AI result) can be reused, through verified replay (src/tcp_planner/storage/evidence_store.py);
every other stage re-runs. A comparison is a set of resumed runs from the AI stage, one per Foundry profile,
all reusing the same source imagery and OSM evidence.
"""
import json, os, shutil

from tcp_planner.storage import run_store as store, run_records as records, stores, uploads
from tcp_planner.storage.evidence_store import (ANALYSIS_SPANS, KIND_STAGE, load_manifest, resolve, verify_file,
                                                sha256_file, read_bytes)
from tcp_planner.storage.interfaces import StorageError

STAGE_ORDER = [s[0] for s in store.STAGES]  # input .. render
REUSE_ORDER = ["map", "osm", "ai"]
STAGE_TITLE = {s[0]: s[1] for s in store.STAGES}
EXTERNAL_CALL = {"imagery": "map provider (imagery request)", "osm": "OpenStreetMap API", "vision": "AI provider"}


def reuse_kinds(stage):
    """Artifacts a resume from `stage` may reuse: external evidence produced before that stage."""
    if stage not in STAGE_ORDER: raise store.BadRequest(f"unknown stage {stage!r}")
    i = STAGE_ORDER.index(stage)
    return [k for k in REUSE_ORDER if STAGE_ORDER.index(KIND_STAGE[k]) < i]


def actual_stage(resume, ev_events):
    """Earliest stage whose evidence was NOT reused (recorded by the replay at run time)."""
    reused = {e["kind"] for e in ev_events if e.get("action") == "reused"
              and e.get("span") == ANALYSIS_SPANS.get(e.get("kind"))}
    for k in REUSE_ORDER:
        if k in resume.get("reuse_kinds", []) and k not in reused: return KIND_STAGE[k]
    return resume.get("requested_stage")


def _parent(parent_id):
    st = store.build_state(parent_id, with_lineage=False)
    if st is None: raise store.BadRequest("source run not found")
    if st["state"] == "RUNNING": raise store.BadRequest("source run is still running")
    return st


LEGACY = "LEGACY EVIDENCE"


def evidence_compat(run_id, state=None):
    """Whether a run's imagery evidence may be reused: OK, LEGACY (pre-scale-fix / pre-evidence Azure imagery) or NONE."""
    from tcp_planner.imagery.map_provider import AzureMapsProvider
    maps = [e for e in load_manifest(run_id)
            if e.get("kind") == "map" and e.get("producer_span") == ANALYSIS_SPANS["map"]]
    for e in maps:
        sig = e.get("signature") or {}
        if sig.get("provider") == "azure_maps" and sig.get("scale_model") != AzureMapsProvider.SCALE_MODEL:
            return {"status": "LEGACY", "reason": f"{LEGACY}: Azure imagery recorded with scale model "
                    f"{sig.get('scale_model')!r}, before the Azure scale fix ({AzureMapsProvider.SCALE_MODEL})"}
    if maps: return {"status": "OK", "reason": None}
    st = state or store.build_state(run_id, with_lineage=False) or {}
    img = next((s for s in st.get("stages", []) if s["key"] == "imagery"), {})
    used_azure = any((sp.get("attributes") or {}).get("provider") == "azure_maps" for sp in img.get("spans", []))
    if used_azure and img.get("status") == "COMPLETED":
        return {"status": "LEGACY", "reason": f"{LEGACY}: Azure imagery from before evidence persistence and the "
                                              "scale fix - nothing saved that could be verified"}
    return {"status": "NONE", "reason": "no saved imagery evidence"}


def _analysis_artifact(parent_id, kind):
    """Last artifact of this kind produced by the analysis stage of the parent (resolved through references)."""
    rdir = store.run_path(parent_id)
    if kind == "map":
        compat = evidence_compat(parent_id)
        if compat["status"] == "LEGACY": return None, compat["reason"]
    cands = [e for e in load_manifest(parent_id) if e.get("kind") == kind and e.get("producer_span") == ANALYSIS_SPANS[kind]]
    if not cands: return None, f"source run has no saved {kind} artifact from {STAGE_TITLE[KIND_STAGE[kind]]}"
    r = resolve(parent_id, cands[-1])
    problem = verify_file(r)
    if problem: return None, problem
    if kind == "ai":
        try:
            if json.loads(read_bytes(r).decode("utf-8")).get("status") != "OK":
                return None, "source AI result is a failure, nothing to reuse"
        except (StorageError, ValueError):
            return None, "source AI artifact cannot be read"
    return r, None


def _dependency_changes(parent_id, parent_state):
    """Inputs of the map/OSM requests that changed since the parent ran (conservative prediction)."""
    from tcp_planner.orchestration.pipeline import CONFIG_PATH
    from tcp_planner.rules.rule_pack_loader import load_rule_pack
    changes = []
    deps = records.read(parent_id, "deps") or {}
    if deps.get("config_sha256") and deps["config_sha256"] != sha256_file(CONFIG_PATH):
        changes.append("implementation config (poc_config.json) changed")
    pack = parent_state.get("rule_pack") or {}
    try:
        if pack.get("hash") and load_rule_pack().hash != pack["hash"]: changes.append("rule pack changed")
    except Exception:
        changes.append("current rule pack cannot be loaded")
    src = _input_file(parent_id, parent_state)
    if src is not None:
        pg = store._read_json(store.run_path(parent_id, "output", "project_geometry.json")) or {}
        if not os.path.isfile(src): changes.append("source input file missing")
        elif pg.get("input_hash") and pg["input_hash"] != "sha256:" + sha256_file(src):
            changes.append("source input file changed")
    return changes


def _input_file(parent_id, parent_state):
    r = parent_state.get("request") or {}
    saved = r.get("kml_saved_path") if r.get("input_type") == "kml" else None
    if not saved: return None
    return saved if os.path.isabs(saved) else records.resolve(saved)  # new runs hold a run-relative key (D-77)


def resume_preview(parent_id, stage, ai_profile=None, ai_provider=None, evidence_mode="single"):
    st = _parent(parent_id)
    if evidence_mode not in ("single", "multi"): raise store.BadRequest("evidence_mode must be single or multi")
    kinds = reuse_kinds(stage)
    changes = _dependency_changes(parent_id, st)
    reused, moved_reason, actual = [], None, stage
    usable = {}
    for k in REUSE_ORDER:
        if k not in kinds: continue
        r, problem = _analysis_artifact(parent_id, k)
        if r is not None and k in ("map", "osm") and changes:
            r, problem = None, "; ".join(changes) + " - the request may differ, re-acquire"
        if r is not None and k == "ai" and not (usable.get("map") and usable.get("osm")):
            r, problem = None, "the AI result depends on imagery/OSM that must be re-acquired"
        if r is None:
            actual = KIND_STAGE[k]; moved_reason = f"{STAGE_TITLE[actual]}: {problem}"
            break
        usable[k] = r
        reused.append({"stage": KIND_STAGE[k], "title": STAGE_TITLE[KIND_STAGE[k]], "kind": k,
                       "source_run": r["origin_run"], "artifact": r["origin_artifact_id"], "file": r["origin_file"],
                       "sha256": r["sha256"], "api_call": False})
    if usable.get("map"):  # a saved sheet aerial is reused too when the render request matches it
        for e in load_manifest(parent_id):
            if e.get("kind") == "map" and e.get("producer_span") == "tcp.sheet.render":
                r = resolve(parent_id, e)
                if verify_file(r) is None:
                    reused.append({"stage": "render", "title": "Render / Export (sheet aerial)", "kind": "map",
                                   "source_run": r["origin_run"], "artifact": r["origin_artifact_id"],
                                   "file": r["origin_file"], "sha256": r["sha256"], "api_call": False,
                                   "conditional": True})
    ai_label = (f"AI provider {ai_provider or 'default'}" + (f", Foundry profile {ai_profile}" if ai_profile else ""))
    rerun, start = [], STAGE_ORDER.index(actual)
    reused_stages = {x["stage"] for x in reused if not x.get("conditional")}
    for i, key in enumerate(STAGE_ORDER):
        if key in ("input", "rule_pack"):
            rerun.append({"stage": key, "title": STAGE_TITLE[key], "external_call": None,
                          "reason": "re-run locally (input re-parsed, rule pack re-verified by hash)"})
        elif key in reused_stages:
            continue
        elif i >= start or key not in ("imagery", "osm", "vision"):
            ext = {"imagery": "map provider imagery request", "osm": "OpenStreetMap API",
                   "vision": ai_label}.get(key)
            if key == "render": ext = "map provider for the wider sheet aerial unless the saved one matches (SUPPORTED_AUTO only)"
            reason = ("requested re-run" if i >= STAGE_ORDER.index(stage) and key in ("imagery", "osm", "vision")
                      else moved_reason if key in ("imagery", "osm", "vision")
                      else "re-runs deterministically on the reused or new evidence")
            rerun.append({"stage": key, "title": STAGE_TITLE[key], "external_call": ext, "reason": reason})
    if evidence_mode == "multi" and "map" in kinds:
        kinds = kinds + ["map_view"]
        saved = [e for e in load_manifest(parent_id) if e.get("kind") == "map_view"]
        for x in rerun:
            if x["stage"] == "vision":
                x["external_call"] = (x["external_call"] or "") + ("; multi-resolution views reused if verified" if saved
                                                                  else "; plus 3 map requests for multi-resolution views")
    compat = evidence_compat(parent_id, st)
    return {"parent_run_id": parent_id, "requested_stage": stage, "predicted_actual_stage": actual,
            "evidence_mode": evidence_mode, "legacy": compat["status"] == "LEGACY", "legacy_reason": compat["reason"],
            "moved_earlier": actual != stage, "move_reason": moved_reason, "reuse_kinds": kinds,
            "dependency_changes": changes, "reused": reused, "rerun": rerun,
            "ai_provider": ai_provider, "ai_profile": ai_profile,
            "note": "Prediction from artifact hashes and configuration hashes. During the run every reused artifact "
                    "is validated against the exact request; any mismatch re-acquires it and is recorded."}


VISION_MODES = ("baseline", "grounded_v2")


def create_resume_run(parent_id, stage, ai_profile=None, ai_provider=None, comparison_id=None, evidence_mode="single",
                      extra_sources=(), vision_mode="baseline", osm_claims=False, centerline_views=False,
                      sme_revision=None, strict_replay=False):
    """sme_revision (SME Review Assistant only): revision dict written create-only to input/sme_revision.json and passed
    as --sme-revision; strict_replay: every external artifact must replay from verified evidence or the run fails closed."""
    if vision_mode not in VISION_MODES: raise store.BadRequest("vision_mode must be baseline or grounded_v2")
    if records.is_legacy(parent_id): raise records.LegacyRunReadOnly(parent_id)
    st = _parent(parent_id)
    preview = resume_preview(parent_id, stage, ai_profile, ai_provider, evidence_mode)
    if preview["legacy"] and "map" in preview["reuse_kinds"]:
        raise store.BadRequest(str(preview["legacy_reason"]) + " - not eligible for resume; re-run from Imagery "
                               "to acquire new evidence")
    parent_req = records.read(parent_id, "request")
    run_id, rdir = store.new_run_dirs()
    out_dir = f"{run_id}/output"  # run-relative key (D-77)
    argv, src_argv, i = [], list(parent_req["argv"]), 0
    request = json.loads(json.dumps(parent_req.get("request") or {}))
    while i < len(src_argv):
        a = src_argv[i]
        if a in ("--out", "--kml", "--ai-provider", "--sme-revision") and i + 1 < len(src_argv):
            if a == "--kml":
                src = records.resolve(src_argv[i + 1])
                if not os.path.isfile(src): raise store.BadRequest("source input file is missing")
                with open(src, "rb") as f: data = f.read()
                ref = uploads.store_upload(stores.artifacts(), run_id, request.get("kml_filename") or os.path.basename(src), data)
                argv += ["--kml", ref.uri]; request["kml_saved_path"] = ref.uri
            i += 2; continue
        argv.append(a); i += 1
    offline = request.get("input_type") == "offline"
    # keep the parent's AI provider unless another is chosen (the AI evidence signature includes model + profile)
    ai_provider = ai_provider or (request.get("advanced") or {}).get("ai_provider")
    if ai_provider and not offline: argv += ["--ai-provider", ai_provider]
    if sme_revision is not None:
        import json as _json
        rev = stores.artifacts().put(f"{run_id}/input/sme_revision.json",
                                     _json.dumps(sme_revision, indent=2, sort_keys=True).encode("utf-8"), "application/json")
        argv += ["--sme-revision", rev.uri]
        request["sme_revision"] = {k: sme_revision.get(k) for k in ("plan_version_id", "change_set_id", "content_sha256")}
    argv += ["--out", out_dir]
    request.setdefault("advanced", {})["ai_provider"] = ai_provider or request.get("advanced", {}).get("ai_provider")
    request["advanced"]["ai_profile"] = ai_profile or request["advanced"].get("ai_profile")
    request["advanced"]["evidence_mode"] = evidence_mode
    request["advanced"].update(vision_mode=vision_mode, osm_claims=bool(osm_claims), centerline_views=bool(centerline_views))
    request["resume"] = {"parent_run_id": parent_id, "requested_stage": stage, "ai_profile": ai_profile,
                         "comparison_id": comparison_id}
    resume = {"parent_run_id": parent_id, "requested_stage": stage, "reuse_kinds": preview["reuse_kinds"],
              "ai_provider": ai_provider, "ai_profile": ai_profile, "comparison_id": comparison_id,
              "evidence_mode": evidence_mode, "extra_sources": list(extra_sources), "vision_mode": vision_mode,
              "osm_claims": bool(osm_claims), "centerline_views": bool(centerline_views),
              "preview": preview, "parent_decision": st["decision"]}
    if sme_revision is not None or strict_replay:
        resume.update(strict_replay=bool(strict_replay), sme_revision={k: sme_revision.get(k) for k in (
            "plan_version_id", "change_set_id", "content_sha256", "site_evidence_version")} if sme_revision else None)
    records.create(run_id, "resume", resume)
    records.create(run_id, "request", {"run_id": run_id, "created_at": store._now(), "argv": argv, "request": request})
    return run_id, rdir


# ---------------------------------------------------------------- model comparison
def _variant(v):
    v = {"evidence_mode": v.get("evidence_mode", "single"), "vision_mode": v.get("vision_mode", "baseline"),
         "osm_claims": bool(v.get("osm_claims")), "centerline_views": bool(v.get("centerline_views"))}
    if v["evidence_mode"] not in ("single", "multi"): raise store.BadRequest("evidence_mode must be single/multi")
    if v["vision_mode"] not in VISION_MODES: raise store.BadRequest("vision_mode must be baseline/grounded_v2")
    if v["osm_claims"] and v["vision_mode"] != "grounded_v2": raise store.BadRequest("OSM claims require grounded_v2")
    if v["centerline_views"] and v["evidence_mode"] != "multi": raise store.BadRequest("centerline views require multi")
    return v


def variant_label(v):
    parts = ["multi-resolution" if v["evidence_mode"] == "multi" else "single-resolution", v["vision_mode"]]
    if v["osm_claims"]: parts.append("OSM claims")
    if v["centerline_views"]: parts.append("centerline views")
    return ", ".join(parts)


def create_comparison(source_id, profiles, modes=("single",), variants=None):
    """Plan a comparison. Children are created by create_children() after any evidence preparation."""
    from tcp_planner.ai.foundry_provider import profile_catalog
    if records.is_legacy(source_id): raise records.LegacyRunReadOnly(source_id)
    available = {p["name"]: p for p in profile_catalog() if p["available"]}
    modes = list(dict.fromkeys(modes or ["single"]))
    if not profiles: raise store.BadRequest("select at least one model profile")
    bad = [p for p in profiles if p not in available]
    if bad: raise store.BadRequest(f"profile(s) not available: {', '.join(bad)}")
    if any(m not in ("single", "multi") for m in modes): raise store.BadRequest("evidence modes must be single/multi")
    variants = [_variant(v) for v in variants] if variants else [_variant({"evidence_mode": m}) for m in modes]
    columns = [{"profile": p, **v} for v in variants for p in profiles]
    if len(columns) < 2: raise store.BadRequest("select at least two model/evidence combinations to compare")
    preview = resume_preview(source_id, "vision", None, "foundry")
    if preview["legacy"]: raise store.BadRequest(str(preview["legacy_reason"]) + " - not eligible for comparison")
    if preview["moved_earlier"]:
        raise store.BadRequest("source run has no reusable imagery/OSM evidence: " + str(preview["move_reason"]))
    cid, cdir = store.new_run_dirs(subdirs=("ui",))
    records.create(cid, "comparison",
                   {"type": "comparison", "comparison_id": cid, "source_run_id": source_id, "created_at": store._now(),
                       "profiles": list(profiles), "modes": modes, "columns": columns, "children": [], "skipped": [],
                       "reused": preview["reused"], "needs_views": any(v["evidence_mode"] == "multi" for v in variants),
                       "variants": variants,
                       "view_plans": sorted({v["centerline_views"] for v in variants if v["evidence_mode"] == "multi"}),
                       "profile_info": {p: available[p] for p in profiles}})
    return cid


def create_children(cid):
    """One resumed child run per column; multi-resolution columns only when the shared views were prepared."""
    doc = records.read(cid, "comparison")
    prep = records.read(cid, "prep") or {}
    children, skipped = [], []
    for col in doc["columns"]:
        multi = col["evidence_mode"] == "multi"
        if multi and not prep.get("ok"):
            skipped.append({**col, "reason": "multi-resolution evidence could not be prepared: " + str(prep.get("error"))})
            continue
        rid, _ = create_resume_run(doc["source_run_id"], "vision", ai_profile=col["profile"], ai_provider="foundry",
                                   comparison_id=cid, evidence_mode=col["evidence_mode"],
                                   extra_sources=[cid] if multi else [], vision_mode=col.get("vision_mode", "baseline"),
                                   osm_claims=col.get("osm_claims", False), centerline_views=col.get("centerline_views", False))
        children.append({**col, "run_id": rid})
    doc.update(children=children, skipped=skipped); records.write(cid, "comparison", doc)
    return [c["run_id"] for c in children]


def _ai_doc(run_id):
    for e in reversed(load_manifest(run_id)):
        if e.get("kind") == "ai" and e.get("mode") == "saved":
            r = resolve(run_id, e)
            try: return json.loads(read_bytes(r).decode("utf-8")), e
            except (StorageError, ValueError, TypeError): return None, e
    return None, None


def _flatten(obj, prefix=""):
    out = {}
    for k, v in obj.items():
        p = f"{prefix}{k}"
        if isinstance(v, dict): out.update(_flatten(v, p + "."))
        else: out[p] = v
    return out


def comparison_state(cid, live_ids=()):
    from tcp_planner.orchestration.pipeline import load_config
    doc = records.read(cid, "comparison")
    if not doc: return None
    threshold = load_config()["fusion"]["min_critical_confidence"]
    cols = []
    for c in doc["children"]:
        st = store.build_state(c["run_id"], live_ids)
        ai, entry = _ai_doc(c["run_id"])
        sm = store._read_json(store.run_path(c["run_id"], "output", "site_model.json"))
        el = store._read_json(store.run_path(c["run_id"], "output", "eligibility_result.json"))
        obs = ((ai or {}).get("result") or {}).get("observation")
        vision = next((s for s in (st or {}).get("stages", []) if s["key"] == "vision"), {})
        statuses = (sm or {}).get("critical_field_status") or {}
        conf = (obs or {}).get("attribute_confidence") or {}
        cols.append({
            "run_id": c["run_id"], "profile": c["profile"], "state": (st or {}).get("state"),
            "evidence_mode": c.get("evidence_mode", "single"), "vision_mode": c.get("vision_mode", "baseline"),
            "osm_claims": c.get("osm_claims", False), "centerline_views": c.get("centerline_views", False),
            "label": f"{c['profile']} - {variant_label(_variant(c))}",
            "grounding": ((ai or {}).get("result") or {}).get("grounding"),
            "views": [v["role"] + " " + v["pixel_sha256"][:12] for v in ((ai or {}).get("views") or [])],
            "backend": (ai or {}).get("backend") or doc.get("profile_info", {}).get(c["profile"], {}).get("backend"),
            "deployment": (ai or {}).get("deployment"), "model": ((ai or {}).get("result") or {}).get("model"),
            "decision": (st or {}).get("decision"), "reason_codes": (st or {}).get("reason_codes", []),
            "ai_status": (ai or {}).get("status") or ("NOT_RUN" if st and st["state"] != "RUNNING" else None),
            "ai_error": None if not ai or ai.get("status") == "OK" else {k: ai.get(k) for k in ("error_code", "message")},
            "schema_errors": ((ai or {}).get("details") or {}).get("errors"),
            "raw_response": ((ai or {}).get("result") or {}).get("raw_response") or ((ai or {}).get("details") or {}).get("raw_response"),
            "observation": obs, "ai_artifact": entry and {"artifact_id": entry["artifact_id"], "sha256": entry["sha256"]},
            "ai_duration_ms": vision.get("duration_ms"), "usage": ((st or {}).get("cost") or {}).get("ai", {}).get("usage"),
            "estimated_cost_usd": ((st or {}).get("cost") or {}).get("ai", {}).get("estimated_cost_usd"),
            "image_quality": (obs or {}).get("image_quality"),
            "reused": [r for s in (st or {}).get("stages", []) for r in s.get("reuse", [])],
            "new_external_calls": [c2 for s in (st or {}).get("stages", []) for c2 in s.get("new_calls", [])],
            "fusion": {"inputs_complete": (sm or {}).get("eligibility_inputs_complete"),
                       "conflicts": len((sm or {}).get("critical_conflicts") or []), "site_model_id": (sm or {}).get("site_model_id")} if sm else None,
            "eligibility": {"decision": (el or {}).get("decision"), "reason_codes": (el or {}).get("reason_codes")} if el else None,
            "draft_generated": (st or {}).get("draft_generated"), "plan_id": ((st or {}).get("plan") or {}).get("plan_id"),
            "metrics": {"resolved": sum(1 for v in statuses.values() if v == "RESOLVED"),
                        "unresolved": sum(1 for v in statuses.values() if v in ("UNRESOLVED", "CONFLICT")),
                        "low_confidence": sum(1 for v in statuses.values() if v == "LOW_CONFIDENCE"),
                        "below_threshold": sorted(k for k, v in conf.items() if isinstance(v, (int, float)) and v < threshold)},
            "_site": sm})
    rows = []

    def add(section, field, values, extra=None):
        present = [v for v, c in zip(values, cols) if c["observation"] is not None or section == "decision"]
        rows.append({"section": section, "field": field, "values": values,
                     "differs": len({json.dumps(v, sort_keys=True, default=str) for v in present}) > 1,
                     "unknown_vs_resolved": any(v is None for v in present) and any(v is not None for v in present),
                     **(extra or {})})
    add("decision", "final decision", [c["decision"] for c in cols])
    add("decision", "eligibility", [(c["eligibility"] or {}).get("decision") for c in cols])
    add("decision", "AI status", [c["ai_status"] for c in cols])
    flat = [(_flatten({k: v for k, v in (c["observation"] or {}).items()
                       if k not in ("features", "attribute_confidence", "osm_conflicts", "notes")})) for c in cols]
    for f in sorted({k for d in flat for k in d}):
        add("observation", f, [d.get(f) if c["observation"] is not None else None for d, c in zip(flat, cols)])
    feat = sorted({k for c in cols for k in ((c["observation"] or {}).get("features") or {})})
    for f in feat:
        add("observation", f"features.{f} (count)", [len(c["observation"]["features"][f]) if c["observation"] else None for c in cols])
    for f in sorted({k for c in cols for k in ((c["observation"] or {}).get("attribute_confidence") or {})}):
        vals = [((c["observation"] or {}).get("attribute_confidence") or {}).get(f) for c in cols]
        add("confidence", f, vals, {"below_threshold": [isinstance(v, (int, float)) and v < threshold for v in vals]})
    for f in sorted({k for c in cols for k in (((c["_site"] or {}).get("critical_field_status")) or {})}):
        add("site_model", f, [((c["_site"] or {}).get("critical_field_status") or {}).get(f) for c in cols])
    for c in cols: c.pop("_site")
    costs = [c["estimated_cost_usd"] for c in cols]
    tokens = {}
    for c in cols:
        for k, v in (c["usage"] or {}).items():
            if isinstance(v, int): tokens[k] = tokens.get(k, 0) + v
    done = all(c["state"] in ("FINISHED", "INTERRUPTED") for c in cols)
    prep = records.read(cid, "prep")
    started = bool(doc["children"]) or bool(doc.get("skipped"))
    done = done and started
    report = {**{k: doc[k] for k in ("comparison_id", "source_run_id", "created_at", "profiles", "reused")},
              "modes": doc.get("modes", ["single"]), "planned_columns": doc.get("columns"), "skipped": doc.get("skipped", []),
              "prep": prep, "phase": ("preparing evidence" if doc.get("needs_views") and not prep or (prep or {}).get("state") == "RUNNING"
                                      else "running models" if not done else "complete"),
              "complete": done, "confidence_threshold": threshold, "columns": cols, "rows": rows,
              "totals": {"tokens": tokens or None,
                         "estimated_cost_usd": round(sum(costs), 6) if costs and all(x is not None for x in costs) else None,
                         "cost_note": None if costs and all(x is not None for x in costs)
                         else "Not Available - at least one model's price is not configured or its call failed",
                         "new_map_calls": sum(x.get("requests", 1) for c in cols for x in c["new_external_calls"] if x.get("service") == "map"),
                         "new_osm_calls": sum(x.get("requests", 1) for c in cols for x in c["new_external_calls"] if x.get("service") == "osm"),
                         "evidence_prep_map_requests": sum(x.get("requests", 1) for x in (records.read(cid, "calls") or [])),
                         "analysis_map_calls_in_children": sum(x.get("requests", 1) for c in cols for x in c["new_external_calls"]
                                                               if x.get("service") == "map" and x.get("span") == "tcp.map.retrieve")},
              "note": "Factual per-model metrics; no model is ranked or selected."}
    if done and not records.is_legacy(cid): records.write(cid, "report", report)
    return report


def list_comparisons():
    out = []
    try: ids = sorted((n for n in os.listdir(store.runs_dir()) if store.RUN_ID_RE.match(n)), reverse=True)
    except OSError: return out
    for i in ids:
        d = records.read(i, "comparison")
        if d: out.append({"comparison_id": i, "source_run_id": d["source_run_id"], "created_at": d["created_at"],
                          "profiles": d["profiles"], "children": d["children"]})
    return out


def evidence_holders(source_id):
    """Comparisons of this source whose shared views were prepared (their views may be reused by hash)."""
    return [c["comparison_id"] for c in list_comparisons() if c["source_run_id"] == source_id
            and (records.read(c["comparison_id"], "prep") or {}).get("ok")]
