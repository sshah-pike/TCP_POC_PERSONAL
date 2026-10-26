"""Load a finished UI run as the review context (read-only). Fails closed when the run is not eligible.

Eligible: UI-created run (runs/<id>/ui/request.json), finished, evidence manifest with verified analysis imagery, OSM
and AI artifacts, not LEGACY evidence, site_model.json present, and the current approved rule pack / implementation
config identical to the ones the run used. CLI runs (no evidence manifest) are not eligible.
"""
import json, os

from ..core.errors import AssistantError

ANALYSIS = {"map": "tcp.map.retrieve", "osm": "tcp.osm.resolve", "ai": "tcp.vision.analyze"}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return None


def not_eligible(reasons):
    return AssistantError("RUN_NOT_ELIGIBLE", "This run is not eligible for SME review: " + "; ".join(r["message"] for r in reasons),
                          409, recoverable=False, details={"reasons": reasons})


def eligibility(run_id):
    """(context dict | None, reasons[])."""
    from tcp_ui import store
    from tcp_ui.evidence import load_manifest, resolve, verify_file, sha256_file
    from tcp_ui.relations import evidence_compat
    from tcp_poc.rule_pack import load_rule_pack
    from tcp_poc.app import CONFIG_PATH
    reasons = []
    try:
        rdir = store.run_path(run_id)
    except store.BadRequest:
        raise AssistantError("NOT_FOUND", "Run not found.", 404)
    st = store.build_state(run_id, with_lineage=False)
    if st is None: raise AssistantError("NOT_FOUND", "Run not found.", 404)
    add = lambda code, msg: reasons.append({"code": code, "message": msg})
    if st["state"] != "FINISHED": add("RUN_NOT_FINISHED", "the run has not finished")
    manifest = load_manifest(rdir)
    if not manifest: add("EVIDENCE_MANIFEST_MISSING", "no saved evidence manifest (CLI or pre-evidence runs are not eligible)")
    compat = evidence_compat(run_id, st)
    if compat["status"] == "LEGACY": add("EVIDENCE_LEGACY", compat["reason"])
    resolved = {}
    for kind, span in ANALYSIS.items():
        cands = [e for e in manifest if e.get("kind") == kind and e.get("producer_span") == span]
        if not cands:
            if manifest: add("EVIDENCE_MISSING", f"no saved {kind} evidence"); continue
            continue
        r = resolve(store.runs_dir(), run_id, cands[-1]); problem = verify_file(r)
        if problem: add("EVIDENCE_CORRUPT_OR_MISSING", f"{kind} evidence: {problem}"); continue
        resolved[kind] = r
    out = os.path.join(rdir, "output")
    site = _read(os.path.join(out, "site_model.json"))
    if site is None: add("SITE_MODEL_MISSING", "the run did not produce a site model (stopped before fusion)")
    pack_ref = st.get("rule_pack") or {}
    try:
        pack = load_rule_pack()
        if pack_ref.get("hash") and pack_ref["hash"] != pack.hash: add("RULE_PACK_CHANGED", "the approved rule pack changed since this run")
    except Exception as e:
        add("RULE_PACK_UNAVAILABLE", f"approved rule pack cannot be loaded ({getattr(e, 'code', type(e).__name__)})"); pack = None
    deps = _read(os.path.join(rdir, "ui", "deps.json")) or {}
    if deps.get("config_sha256") and deps["config_sha256"] != sha256_file(CONFIG_PATH):
        add("CONFIG_CHANGED", "the implementation configuration changed since this run")
    if reasons: return None, reasons
    crops = []
    for e in manifest:
        if e.get("kind") == "map_crop":
            r = resolve(store.runs_dir(), run_id, e)
            if r is not None and verify_file(r) is None: crops.append(r)
    pg = _read(os.path.join(out, "project_geometry.json"))
    from tcp_ui.labels import site_id_for
    ctx = {"run_id": run_id, "run_state": {k: st.get(k) for k in ("decision", "reason_codes", "message", "draft_generated")},
           "request": st.get("request"), "project_geometry": pg, "site_model": site,
           "machine_site_model": _read(os.path.join(out, "machine_site_model.json")) or site,
           "eligibility": _read(os.path.join(out, "eligibility_result.json")),
           "validation": _read(os.path.join(out, "validation_results.json")),
           "plan": _read(os.path.join(out, "plan.json")),
           "sme_revision_applied": _read(os.path.join(out, "sme_revision_applied.json")),
           "evidence": resolved, "crops": crops, "rule_pack": pack, "rule_pack_ref": pack.ref,
           "lineage_key": site_id_for(pg), "outputs": [o["name"] for o in st.get("outputs") or []]}
    return ctx, []


def load(run_id):
    ctx, reasons = eligibility(run_id)
    if ctx is None: raise not_eligible(reasons)
    return ctx


def config():
    from tcp_poc.app import load_config
    return load_config()
