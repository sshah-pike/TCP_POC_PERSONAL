"""TCP POC - Pipeline 2: KML/coordinates -> SiteModel -> eligibility -> TA-1 plan -> validation -> render.

Exit codes: 0 draft exported | 3 REVIEW_REQUIRED | 4 UNSUPPORTED_POC | 2 configuration/rule-pack failure.
"""
import argparse, datetime, json, os, sys, tempfile

from . import kml_input, osm_adapter, offline
from .models import (APP_VERSION, FT, SUPPORTED_AUTO, REVIEW_REQUIRED, UNSUPPORTED_POC, UNSUPPORTED_MESSAGE,
                     REVIEW_MESSAGE, TcpError, InputRejected, RulePackError, ProviderError, MapProviderError,
                     OsmError, DwtRenderError, content_hash, write_json, r, redact)
from .foundry_provider import debug_sent_enabled, DEBUG_SENT_ENV, DEBUG_SENT_DIR, ERROR_TEXT_LIMIT
from .telemetry import Telemetry, confidence_band
from .rule_pack import load_rule_pack, PROJECT_ROOT
from .map_provider import get_map_provider
from .vision_provider import get_vision_provider
from .agent import Agent
from .site_fusion import build_site_model, reference_bearing, CRITICAL_FIELDS
from .eligibility import evaluate as evaluate_eligibility
from .rule_engine import execute as execute_rules
from .geometry import place_objects
from .validators import RuleValidator, GeometryValidator
from .renderers import DebugRenderer
from .sheet_renderer import SheetRenderer
from .dwt_renderer import DwtRenderer

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poc_config.json")
DWT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dwt_config.json")
OUTPUT_FILES = ("project_geometry.json", "site_model.json", "eligibility_result.json", "plan.json",
                "validation_results.json", "aerial_image.jpg", "debug_plan.png", "debug_plan.pdf", "run_report.txt",
                "plan.dxf", "plan.dwg", "dwt_result.json",
                "tcp_sheet.pdf", "tcp_sheet.png", "sheet_aerial.jpg")
EXIT = {SUPPORTED_AUTO: 0, REVIEW_REQUIRED: 3, UNSUPPORTED_POC: 4}


def load_env_file(path=".env"):
    for base in (PROJECT_ROOT, os.getcwd()):
        env_path = os.path.join(base, path)
        if not os.path.isfile(env_path): continue
        with open(env_path, encoding="utf-8") as env_file:
            for line in env_file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                key, value = line.split("=", 1)
                key = key.strip(); value = value.strip().strip("\"'")
                if key: os.environ.setdefault(key, value)


def load_config(path=None):
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as f: cfg = json.load(f)
    if cfg.get("regulatory_status") != "IMPLEMENTATION_GEOMETRY_NOT_MUTCD_VALUE":
        raise TcpError("CONFIG_INVALID", "implementation config must be marked non-regulatory")
    return cfg


def _blocked(decision, reason_codes, message, details=None):
    return {"decision": decision, "generate_draft": False, "reason_codes": sorted(set(reason_codes)),
            "message": message, "details": details or {}}


class Run:
    def __init__(self, out_dir, exact_coords=False):
        self.out = os.path.abspath(out_dir); os.makedirs(self.out, exist_ok=True)
        for name in OUTPUT_FILES:  # never leave stale artifacts from a previous run
            p = os.path.join(self.out, name)
            if os.path.isfile(p): os.remove(p)
        self.tel = Telemetry(); self.log = []; self.written = []; self.exact = exact_coords

    def say(self, s):
        print(s, flush=True); self.log.append(s)

    def write(self, name, obj):
        write_json(os.path.join(self.out, name), obj); self.written.append(name)

    def path(self, name):
        return os.path.join(self.out, name)

    def where(self, lat, lon):
        nd = 7 if self.exact else 3
        return f"{lat:.{nd}f}, {lon:.{nd}f}" + ("" if self.exact else " (rounded)")


def run_pipeline(*, out_dir, kml=None, lat=None, lon=None, operator=None, map_provider=None, vision_provider=None,
                 osm_source=None, rule_pack_path=None, config_path=None, dwt_config=None, dwt_mode="PLAN",
                 exact_coords=False):
    """Run Pipeline 2 end-to-end. Returns a result dict; never raises for site-level outcomes."""
    run = Run(out_dir, exact_coords); tel = run.tel
    operator = operator or {}
    result = {"decision": None, "outputs": [], "plan_hash": None}
    run.say(f"TCP POC Pipeline 2  ({APP_VERSION})")
    try:
        config = load_config(config_path)

        # ---- input ----
        with tel.span("tcp.input.parse", input_type="KML" if kml else "COORDINATES") as sp:
            try:
                pg = kml_input.parse_kml(kml, config["input"]["max_work_path_m"]) if kml else kml_input.from_coordinates(lat, lon)
            except InputRejected as e:
                tel.set(sp, decision=UNSUPPORTED_POC, reason_codes=e.reason_codes)
                elig = _blocked(UNSUPPORTED_POC, e.reason_codes, f"Input rejected: {e.message}. {UNSUPPORTED_MESSAGE}", e.details)
                run.write("eligibility_result.json", elig)
                return _finish(run, result, elig)
            tel.set(sp, input_hash=pg["input_hash"][:19], features=pg["input_feature_count"])
        run.write("project_geometry.json", pg)
        ref = pg["work_reference"]
        run.say(f"1 Input: {pg['input_type']}  work reference {run.where(ref['latitude'], ref['longitude'])}  "
                f"path points {len(pg['work_path'])}")

        # ---- approved rule pack (fail closed) ----
        with tel.span("tcp.rulepack.load") as sp:
            pack = load_rule_pack(rule_pack_path)
            tel.set(sp, rule_pack_id=pack.id, rule_pack_version=pack.version, rule_pack_hash=pack.hash[:16])
        run.say(f"2 Rule pack: {pack.id} v{pack.version} {pack.status} sha256 {pack.hash[:16]}... verified")

        # ---- map / imagery ----
        a_max = max(pack.spacing_value_ft(rt, "A")[1] for rt in config["supported_road_types"])
        half = a_max * FT + config["imagery"]["analysis_margin_m"]
        mp = map_provider or get_map_provider()
        with tel.span("tcp.map.retrieve", provider=mp.name) as sp:
            try:
                image, meta = mp.fetch_context(pg, half, config["imagery"]["width_px"])
            except MapProviderError as e:
                tel.set(sp, error_code=e.code)
                elig = _blocked(REVIEW_REQUIRED, ["MAP_CONTEXT_UNAVAILABLE", e.code], REVIEW_MESSAGE)
                run.write("eligibility_result.json", elig); return _finish(run, result, elig)
            tel.set(sp, metres_per_pixel=meta["metres_per_pixel"], width_px=meta["width_pixels"])
        run.say(f"3 Imagery: {meta['provider']}  {meta['ground_extent_m']['width']:.0f} m across, "
                f"{meta['metres_per_pixel']:.3f} m/px")

        # ---- OSM ----
        with tel.span("tcp.osm.resolve") as sp:
            try:
                fetch = osm_source or osm_adapter.fetch_osm
                els = fetch(ref["latitude"], ref["longitude"], half + config["osm"]["extra_radius_m"])
                osm = osm_adapter.extract_evidence(els, pg, config)
            except OsmError as e:
                tel.set(sp, error_code=e.code)
                elig = _blocked(REVIEW_REQUIRED, ["OSM_CONTEXT_UNAVAILABLE", e.code], REVIEW_MESSAGE)
                run.write("eligibility_result.json", elig); return _finish(run, result, elig)
            tel.set(sp, way_count=len(osm["target_way_ids"]), highway=osm["highway"])
        run.say(f"4 OSM: road '{osm['name'] or '(unnamed)'}' highway={osm['highway']} lanes_tag={osm['lanes_tag']} "
                f"oneway={osm['oneway_tag']}")

        # ---- vision: two-call agent (call 1 wide + blind, compare, crops, call 2) ----
        vp = vision_provider or _safe_vision_provider()
        ai_result, ai_error, ai_error_text, agent = None, None, None, None
        if debug_sent_enabled():
            run.say(f"WARNING: {DEBUG_SENT_ENV}=1 - every model request (images, prompts, schema) is written to "
                    f"{DEBUG_SENT_DIR}")
        if meta["width_pixels"] != config["imagery"]["wide_image_px"]:
            raise TcpError("CONFIG_INVALID", "imagery.width_px must equal imagery.wide_image_px: the model receives "
                                             "the native wide image (no resize)")
        who = _provider_info(vp)
        run.say(f"5 AI vision: {who['label']} - max {config['agent']['max_model_calls']} model calls")
        with tel.span("tcp.vision.analyze", provider=who["provider"], profile=who["profile"],
                      deployment=who["deployment"], api=who["api"]) as sp:
            if isinstance(vp, ProviderError):
                ai_error, ai_error_text = vp.code, redact(vp.message, ERROR_TEXT_LIMIT)
            else:
                agent = Agent(config=config, vision_provider=vp, map_provider=mp, project_geometry=pg, osm=osm,
                              image=image, meta=meta, operator=operator, pack=pack, half_extent_m=half,
                              say=run.say, telemetry=tel).run()
                ai_result, ai_error, ai_error_text = agent.ai_result, agent.ai_error, agent.ai_error_text
            tel.set(sp, status_code=ai_error or "OK", model=(ai_result or {}).get("model"),
                    model_calls=len(agent.calls) if agent else 0, crops=len(agent.views) if agent else 0)
        run.say(f"   result: {'received from ' + ai_result['provider'] + ' (' + str(ai_result['model']) + ')' if ai_result else 'UNAVAILABLE (' + str(ai_error) + ')'}"
                f"; model calls {len(agent.calls) if agent else 0} of max {config['agent']['max_model_calls']}")
        if ai_error_text: run.say(f"   AI error text: {ai_error_text}")

        # ---- fusion ----
        with tel.span("tcp.site.fuse") as sp:
            site = build_site_model(pg, osm, ai_result, ai_error, meta, operator, config, ai_error_text=ai_error_text,
                                    agent=agent.fusion_inputs() if agent else None)
            tel.set(sp, site_model_id=site["site_model_id"], conflicts=len(site["critical_conflicts"]),
                    inputs_complete=site["eligibility_inputs_complete"])
        run.write("site_model.json", site)
        _say_fields(run, site)

        # ---- eligibility BEFORE any generation ----
        with tel.span("tcp.site.eligibility") as sp:
            elig = evaluate_eligibility(site, pack, config)
            tel.set(sp, decision=elig["decision"], reason_codes=elig["reason_codes"])
        run.write("eligibility_result.json", elig)
        run.say(f"7 Eligibility: {elig['decision']}  {', '.join(elig['reason_codes']) or '(all conditions pass)'}")
        run.agent_summary = _agent_summary(agent, site, elig, config)
        if elig["decision"] != SUPPORTED_AUTO:
            return _finish(run, result, elig)

        # ---- rules -> placement ----
        template = pack.ta1_template()
        with tel.span("tcp.rules.execute", ta_id=template["id"]) as sp:
            rules_out = execute_rules(site, elig, pack, template)
            tel.set(sp, objects=len(rules_out["objects"]), options=len(rules_out["options_applied"]))
        with tel.span("tcp.geometry.place") as sp:
            placed, issues = place_objects(rules_out["objects"], site, config)
            tel.set(sp, issues=[i["code"] for i in issues])
        run.say(f"8 Rules: {template['id']} Table {rules_out['spacing']['table']} {rules_out['spacing']['road_type']} "
                f"A = {rules_out['spacing']['value_ft']:g} ft; {len(placed)} objects placed")

        plan = _build_plan(site, pack, template, rules_out, placed, meta, ai_result, mp)

        # ---- independent validation ----
        with tel.span("tcp.plan.validate") as sp:
            rv = RuleValidator().validate(plan, site, elig, pack)
            gv = GeometryValidator().validate(plan, site, config)
            if issues:
                gv["checks"].append({"id": "GEO-PLACEMENT", "status": "FAIL", "severity": "BLOCK", "detail": issues})
                gv["status"] = "FAIL"
            tel.set(sp, rule=rv["status"], geometry=gv["status"])
        validation = {"rule_validation": rv, "geometry_validation": gv, "plan_ref": None}
        plan["validation"] = {"rule": rv["status"], "geometry": gv["status"]}
        run.say(f"9 Validation: rule {rv['status']}  geometry {gv['status']}")
        if rv["status"] != "PASS" or gv["status"] != "PASS":
            failed = [c["id"] for c in rv["checks"] + gv["checks"] if c["status"] == "FAIL"]
            run.write("validation_results.json", validation)
            final = _blocked(REVIEW_REQUIRED, ["PLAN_VALIDATION_FAILED"] + failed,
                             "Draft blocked: independent validation failed; no plan exported.")
            return _finish(run, result, final)

        plan["plan_hash"] = content_hash(plan, drop={"plan_hash", "plan_id"})
        plan["plan_id"] = "TCP-" + plan["plan_hash"][:16].upper()
        validation["plan_ref"] = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"]}
        run.write("plan.json", plan); run.write("validation_results.json", validation)
        image.save(run.path("aerial_image.jpg"), format="JPEG", quality=92); run.written.append("aerial_image.jpg")
        result["plan_hash"] = plan["plan_hash"]; result["plan_id"] = plan["plan_id"]

        with tel.span("tcp.debug.render", plan_id=plan["plan_id"]):
            DebugRenderer().render(plan, image, run.path("debug_plan.png"), run.path("debug_plan.pdf"))
        run.written += ["debug_plan.png", "debug_plan.pdf"]

        sheet = SheetRenderer()
        with tel.span("tcp.sheet.render", plan_id=plan["plan_id"]) as sp:
            if not sheet.available():
                tel.set(sp, status_code="SKIPPED_NO_SHEET_TEMPLATE")
            else:
                s_img, s_meta = image, meta
                need = sheet.view_half_extent_m(plan)
                if need > half:  # sheet view is larger than the analysis image: fetch a display-only aerial
                    try:
                        s_img, s_meta = mp.fetch_context(pg, need, config["imagery"].get("sheet_px", 2560))
                        s_img.save(run.path("sheet_aerial.jpg"), format="JPEG", quality=90); run.written.append("sheet_aerial.jpg")
                    except MapProviderError as e:
                        tel.set(sp, sheet_aerial=e.code)
                info = sheet.render(plan, s_img, run.path("tcp_sheet.pdf"), run.path("tcp_sheet.png"), image_meta=s_meta)
                run.written += ["tcp_sheet.pdf", "tcp_sheet.png"]
                tel.set(sp, status_code="RENDERED", scale_ft_per_in=info["scale_ft_per_in"])

        with tel.span("tcp.dwt.render") as sp:
            if not dwt_config:
                tel.set(sp, status_code="SKIPPED_NO_DWT_CONFIG"); result["dwt"] = {"status": "SKIPPED"}
            else:
                try:
                    info = DwtRenderer(dwt_config, pack, dwt_mode).render(plan, run.path("aerial_image.jpg"), meta, run.out)
                    run.written += info["outputs"]; result["dwt"] = info
                    tel.set(sp, status_code="RENDERED", mode=dwt_mode, dwt_version=info["dwt_version"])
                except DwtRenderError as e:
                    tel.set(sp, status_code=e.code, mode=dwt_mode); result["dwt"] = e.to_dict()
        if result.get("dwt") and result["dwt"].get("status") != "SKIPPED": run.write("dwt_result.json", result["dwt"])
        run.say(f"10 Plan {plan['plan_id']} exported (hash {plan['plan_hash'][:16]}...); DWT: "
                f"{result['dwt'].get('status') or result['dwt'].get('error_code')}")
        return _finish(run, result, elig)
    except (RulePackError, TcpError) as e:
        run.say(f"FAILED CLOSED: {e.code}: {e.message}")
        result.update(decision=None, error=e.to_dict())
        _write_report(run, result, None)
        return result


def _provider_info(vp):
    """Which AI provider / Foundry profile / deployment / API family this run uses (shown when the stage starts)."""
    if isinstance(vp, ProviderError):
        return {"provider": "none", "profile": None, "deployment": None, "api": None,
                "label": f"provider unavailable ({vp.code})"}
    info = {"provider": getattr(vp, "name", None), "profile": getattr(vp, "profile", None),
            "deployment": getattr(vp, "deployment", None) or getattr(vp, "model", None), "api": getattr(vp, "api", None)}
    parts = [f"provider {info['provider']}"] + [f"{k} {info[k]}" for k in ("profile", "deployment", "api") if info[k]]
    return {**info, "label": ", ".join(parts)}


def _safe_vision_provider():
    try: return get_vision_provider()
    except ProviderError as e: return e


def _agent_summary(agent, site, elig, config):
    """Run-report section: model calls, tokens, resolution paths, unresolved fields, crops."""
    if agent is None: return ["AGENT: not run (AI provider unavailable)"]
    lines = [f"AGENT: model calls {len(agent.calls)} (max {config['agent']['max_model_calls']})"]
    for c in agent.calls:
        lines.append(f"  call {c['call']} ({c['mode']}, {c['images']} image(s)): {c.get('status')} "
                     f"{c.get('model') or c.get('error_code') or ''}  usage {json.dumps(c.get('usage'), sort_keys=True)}")
    lines.append(f"  tokens total: {json.dumps(agent.tokens(), sort_keys=True)}")
    paths = {}
    for a in site["audit"]:
        if a["decision"] == "RESOLVED" and a.get("path"): paths.setdefault(a["path"], []).append(a["field"])
    for p in ("AGREEMENT", "NORMAL", "GEOMETRY", "CROP", "MEASURED", "DERIVED", "OPERATOR"):
        lines.append(f"  resolved by {p:<9}: {', '.join(paths.get(p, [])) or '-'}")
    left = elig["unresolved_fields"] + elig["failed_conditions"]
    lines.append("  still unresolved / failed: " + (", ".join(f"{u['field']} [{u['reason_code']}]" for u in left) or "none"))
    for c in agent.crops:
        s = c.get("sharpness") or {}
        lines.append(f"  crop {c['crop_id']} {c['kind']} for {','.join(c['purposes'])}: zoom requested {c['zoom_requested']}"
                     f" used {c['zoom_used']}" + (f" FALLBACK ({c['fallback_reason']})" if c["fallback"] else "") +
                     (f"; detail {s.get('detail_hi')} vs {s.get('detail_lo_upsampled')} ratio {s.get('ratio')} "
                      f"(min {s.get('min_detail_gain_ratio')})" if "detail_hi" in s else "") +
                     (f"; UNAVAILABLE {c['unavailable']}" if c.get("unavailable") else ""))
    for c in agent.crops_dropped: lines.append(f"  crop {c['kind']} dropped: {c['reason']}")
    for m in agent.measurements:
        lines.append(f"  measure {m['role']} station {m['station_m']}: {m['status']}" +
                     (f" width {m['width_m']} m, road centre {m['centre_offset_m']:+.2f} m from OSM ({m['centre_source']})"
                      if m["status"] == "OK" else f" ({m.get('reason')})"))
    for c in agent.consistency:
        lines.append(f"  consistency {c['field']}: call 1 {c['call1']} / call 2 {c['call2']} -> {c['result']}")
    lines.append(f"  extras (stored, never used in decisions): {len(agent.extras)}")
    return lines


def _say_fields(run, site):
    run.say("6 SiteModel " + site["site_model_id"] + " critical fields:")
    road, work = site["road"], site["work"]
    rows = [("lane_count", road["lane_count"]), ("two_way", road["two_way"]), ("divided", road["divided"]),
            ("facility_type", road["facility_type"]), ("road_type", road["road_type"]), ("work.side", work["side"]),
            ("work.location", work["location"]), ("work.encroaches", work["encroaches_traveled_way"]),
            ("work.lane_closure", work["requires_lane_closure"]), ("work.pedestrian", work["affects_pedestrian_route"])]
    for name, f in rows:
        run.say(f"   {name:<18} {str(f['value']):<18} {f['status']:<15} confidence {confidence_band(f['confidence'])}")
    run.say(f"   {'road_edges':<18} {str(road['road_edges']['traveled_way_width_m']) + ' m':<18} {road['road_edges']['status']}")
    for c in site["critical_conflicts"]:
        run.say(f"   CONFLICT {c['field']}: OSM={c['osm']} AI={c['ai']}")


def _build_plan(site, pack, template, rules_out, placed, meta, ai_result, mp):
    road, work = site["road"], site["work"]
    return {
        "plan_id": None, "version": 1, "status": "AUTOMATED_DRAFT",
        "disclaimer": "AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE",
        "site_model": {"id": site["site_model_id"], "version": site["version"]},
        "rule_pack": pack.ref,
        "template": {k: template[k] for k in ("id", "version", "figure", "title")},
        "objects": placed,
        "options_applied": rules_out["options_applied"], "standard_notes": rules_out["standard_notes"],
        "spacing": rules_out["spacing"], "not_generated": rules_out["not_generated"],
        "site_summary": {"road_name": road["name"], "road_type": road["road_type"]["value"],
                         "lane_count": road["lane_count"]["value"], "traffic_direction": road["traffic_direction"]["value"],
                         "work_side": work["side"]["value"], "work_location": work["location"]["value"]},
        "site_geometry": {"centerline": road["centerline"],
                          "road_edges": {"left": road["road_edges"].get("left"), "right": road["road_edges"].get("right"),
                                         "traveled_way_width_m": road["road_edges"]["traveled_way_width_m"]},
                          "work_station_m": work["reference_station_m"]},
        "imagery": meta,
        "validation": None,
        "versions": {"application": APP_VERSION, "ai_provider": (ai_result or {}).get("provider"),
                     "ai_model": (ai_result or {}).get("model"), "map_provider": mp.name, "dwt": None},
        "generated_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "plan_hash": None,
    }


def _finish(run, result, elig):
    result["decision"] = elig["decision"]; result["reason_codes"] = elig["reason_codes"]
    result["eligibility"] = elig
    _write_report(run, result, elig)
    result["outputs"] = sorted(set(run.written)); result["out_dir"] = run.out
    return result


def _write_report(run, result, elig):
    lines = list(run.log)
    lines += ["", "=" * 60, f"FINAL DECISION: {result.get('decision') or 'ERROR'}"]
    if elig:
        lines.append(f"Reason codes: {', '.join(elig['reason_codes']) or '-'}")
        lines.append(f"Message: {elig['message']}")
    if result.get("error"): lines.append(f"Error: {result['error']['error_code']} - {result['error']['message']}")
    if result.get("plan_id"): lines.append(f"Plan: {result['plan_id']}  hash {result['plan_hash']}")
    if result.get("dwt"): lines.append(f"DWT: {json.dumps(result['dwt'], sort_keys=True)}")
    if getattr(run, "agent_summary", None): lines += [""] + run.agent_summary
    lines += ["", "Telemetry spans (no keys, coordinates, images, prompts or completions are logged):"]
    lines += run.tel.summary_lines()
    if debug_sent_enabled():
        lines += ["", f"PRIVACY: request debug dump was ON for this run ({DEBUG_SENT_ENV}=1). The exact images, prompt "
                      f"text and schemas sent to the model were written to {DEBUG_SENT_DIR} (request data only; no "
                      "responses, no keys). Delete that folder when no longer needed."]
    else:
        lines += ["", f"Privacy: request debug dump was OFF ({DEBUG_SENT_ENV} not set to 1); no request images or "
                      "prompts were written to disk by the pipeline."]
    lines += ["", "Outputs: " + ", ".join(sorted(set(run.written + ["run_report.txt"])))]
    with open(run.path("run_report.txt"), "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    run.written.append("run_report.txt")


def _parse_option(text):
    if "=" not in text: raise argparse.ArgumentTypeError("use KEY=VALUE")
    k, v = text.split("=", 1); v = v.strip()
    low = v.lower()
    if low in ("true", "false"): return k.strip(), low == "true"
    try: return k.strip(), float(v) if "." in v else int(v)
    except ValueError: return k.strip(), v


def use_os_trust_store():
    """Verify TLS against the Windows/OS certificate store (needed behind corporate TLS inspection).
    Verification stays on; only the trust anchors change."""
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def main(argv=None):
    load_env_file(); use_os_trust_store()
    ap = argparse.ArgumentParser(description="TCP POC Pipeline 2 (TA-1, two-lane two-way, work beyond shoulder)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--kml", help="KML with one work Point and optionally one LineString work path")
    src.add_argument("--offline", help=f"synthetic self-test scenario: {', '.join(offline.SCENARIOS)} (aliases: easy, hard)")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--offline-input", choices=["coordinates", "kml"], default="coordinates")
    ap.add_argument("--road-type", help="operator-confirmed Table 6B-1 road type (e.g. URBAN_LOW_SPEED, URBAN_HIGH_SPEED, RURAL)")
    ap.add_argument("--speed", type=int, help="posted speed, mph (informational)")
    ap.add_argument("--requires-lane-closure", action="store_true", help="operator declares the work needs a lane closure")
    ap.add_argument("--option", action="append", type=_parse_option, default=[],
                    help="confirmed TA-1 option fact, e.g. behind_barrier=true, distance_from_edge_of_roadway_ft=20")
    ap.add_argument("--out", default="output"); ap.add_argument("--rule-pack"); ap.add_argument("--config")
    ap.add_argument("--dwt-config", default=DWT_CONFIG_PATH if os.path.isfile(DWT_CONFIG_PATH) else None,
                    help="DWT renderer configuration JSON (default: tcp_poc/dwt_config.json)")
    ap.add_argument("--dwt-mode", choices=["PLAN", "AERIAL_BASE"], default="PLAN",
                    help="PLAN = full plan in the DWT template (needs approved blocks); AERIAL_BASE = aerial + linework only")
    ap.add_argument("--no-dwt", action="store_true", help="skip the DWT renderer")
    ap.add_argument("--map-provider"); ap.add_argument("--ai-provider")
    ap.add_argument("--log-exact-coordinates", action="store_true")
    a = ap.parse_args(argv)

    operator = {"road_type": a.road_type, "speed_mph": a.speed, "requires_lane_closure": a.requires_lane_closure,
                "options": dict(a.option)}
    kw = dict(out_dir=a.out, rule_pack_path=a.rule_pack, config_path=a.config,
              dwt_config=None if a.no_dwt else a.dwt_config, dwt_mode=a.dwt_mode,
              exact_coords=a.log_exact_coordinates)
    if a.offline:
        sc = offline.build(a.offline)
        op = dict(sc["operator"]); op.update({k: v for k, v in operator.items() if v not in (None, False, {})})
        kw.update(operator=op, map_provider=sc["map_provider"], vision_provider=sc["vision_provider"],
                  osm_source=lambda lat, lon, radius: sc["osm_elements"])
        if a.offline_input == "kml":
            kw["kml"] = offline.write_kml(os.path.join(tempfile.mkdtemp(), "offline_work_point.kml"), sc["lat"], sc["lon"])
        else:
            kw.update(lat=sc["lat"], lon=sc["lon"])
        print(f"OFFLINE scenario '{sc['name']}' - simulated road, imagery, OSM and AI observation (not real data)")
    else:
        if not a.kml and (a.lat is None or a.lon is None):
            ap.error("give --kml PATH, or --lat and --lon, or --offline SCENARIO")
        if a.ai_provider:
            try: kw["vision_provider"] = get_vision_provider(a.ai_provider)
            except ProviderError as e: kw["vision_provider"] = e
        if a.map_provider: kw["map_provider"] = get_map_provider(a.map_provider)
        kw.update(operator=operator, kml=a.kml, lat=a.lat, lon=a.lon)
    res = run_pipeline(**kw)
    if res.get("error"): return 2
    return EXIT[res["decision"]]


if __name__ == "__main__":
    sys.exit(main())
