"""Fixture recorder.  Run from the repository root:

  python -m tests.support.record seed  VAR_RUN_DIR SITE_NAME      offline: fixtures from a saved run's evidence
  python -m tests.support.record live  KML SITE_NAME --road-type RURAL [--speed N] [--lane-closure]
                                                                  LIVE Azure Maps, OSM and Foundry calls; needs TCP_LIVE=1
                                                                  and is run only by the user (CLAUDE.md, Tests)

Fixtures are written to tests/fixtures/recorded/<SITE_NAME>/ (see tests/support/fixtures.py). `seed` makes no network call.
`live` calls use_os_trust_store() first, like the pipeline CLI, and never turns certificate verification off.
The pipeline currently accepts one work Point per KML (MULTIPLE_WORK_POINTS); the three real multi-point reference KMLs
can be recorded only after S6, when intake and grouping exist.
"""
import argparse, json, os, shutil, sys, tempfile

from .fixtures import FixtureStore
from .providers import (Harness, map_request, crop_request, osm_request, ai_request, _png)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECORDED = os.path.join(ROOT, "tests", "fixtures", "recorded")


def seed(run_dir, name, out_root=RECORDED):
    """Fixtures from a saved run (evidence/manifest.json + ui/request.json). Offline."""
    from PIL import Image
    run_dir = os.path.abspath(run_dir)
    with open(os.path.join(run_dir, "evidence", "manifest.json"), encoding="utf-8") as f: manifest = json.load(f)
    with open(os.path.join(run_dir, "ui", "request.json"), encoding="utf-8") as f: req = json.load(f)["request"]
    site_dir = os.path.join(out_root, name); store = FixtureStore(site_dir)
    os.makedirs(site_dir, exist_ok=True)
    kml_src = os.path.join(run_dir, "input", req["kml_filename"])
    shutil.copyfile(kml_src, os.path.join(site_dir, "input.kml"))
    profile, counts = None, {}
    for a in manifest["artifacts"]:
        sig, kind, path = a["signature"], a["kind"], os.path.join(run_dir, "evidence", a["file"])
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("map", "map_crop"):
            with Image.open(path) as im: png = _png(im.convert("RGB"))
            meta = a["metadata"]["meta"]
            if kind == "map":
                c = meta["center"]
                r = map_request(sig["provider"], sig["scale_model"], sig["api_version"], c["latitude"], c["longitude"],
                                sig["half_extent_m"], sig["size_px"])
            else:
                r = crop_request(sig["provider"], sig["scale_model"], sig["api_version"], sig["lat"], sig["lon"],
                                 sig["zoom"], sig["size_px"])
            store.save(kind, r, {"meta": meta}, png)
        elif kind == "osm":
            with open(path, encoding="utf-8") as f: elements = json.load(f)
            store.save("osm", osm_request(sig["source"], sig["lat"], sig["lon"], sig["radius_m"]), {"elements": elements})
        elif kind == "ai":
            with open(path, encoding="utf-8") as f: doc = json.load(f)
            if doc.get("status") != "OK": continue
            profile = profile or doc.get("profile")
            store.save("ai", ai_request(doc["request"]), {"result": doc["result"]})
    op = req["operator"]
    site = {"schema_version": 1, "name": name, "source": f"seeded from saved run {os.path.basename(run_dir)}",
            "kml_file": req["kml_filename"], "ai_profile": profile,
            "operator": {"road_type": op.get("road_type"), "speed_mph": op.get("speed"),
                         "requires_lane_closure": bool(op.get("requires_lane_closure")), "options": {}}}
    with open(os.path.join(site_dir, "site.json"), "w", encoding="utf-8") as f: json.dump(site, f, indent=1, sort_keys=True)
    return site_dir, counts


def live(kml, name, road_type, speed=None, lane_closure=False, out_root=RECORDED):
    """Record one site from live providers. The caller must have set TCP_LIVE=1."""
    if os.environ.get("TCP_LIVE") != "1":
        raise SystemExit("TCP_LIVE=1 is required: recording makes live Azure Maps, OSM and AI calls "
                         "(run only by the user, CLAUDE.md Tests).")
    from tcp_planner.orchestration import pipeline as app
    app.use_os_trust_store()   # corporate proxy: verify TLS against the OS store; verification stays on
    app.load_env_file()
    from tcp_planner.imagery.map_provider import get_map_provider
    from tcp_planner.ai.vision_provider import get_vision_provider
    from tcp_planner.data_sources.osm_overpass import fetch_osm
    vision = get_vision_provider("foundry")
    site_dir = os.path.join(out_root, name); os.makedirs(site_dir, exist_ok=True)
    shutil.copyfile(kml, os.path.join(site_dir, "input.kml"))
    site = {"schema_version": 1, "name": name, "source": "recorded live", "kml_file": os.path.basename(kml),
            "ai_profile": getattr(vision, "profile", None),
            "operator": {"road_type": road_type, "speed_mph": speed, "requires_lane_closure": bool(lane_closure), "options": {}}}
    with open(os.path.join(site_dir, "site.json"), "w", encoding="utf-8") as f: json.dump(site, f, indent=1, sort_keys=True)
    h = Harness(site_dir, live={"map": get_map_provider("azure_maps"), "osm": fetch_osm, "vision": vision})
    res = app.run_pipeline(out_dir=tempfile.mkdtemp(prefix="tcp_record_"), **h.run_kwargs())
    return site_dir, res.get("decision"), h.fingerprints()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tests.support.record", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("run_dir"); s.add_argument("name")
    lv = sub.add_parser("live"); lv.add_argument("kml"); lv.add_argument("name")
    lv.add_argument("--road-type", required=True); lv.add_argument("--speed", type=int)
    lv.add_argument("--lane-closure", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "seed":
        d, counts = seed(a.run_dir, a.name); print("seeded", d, counts)
    else:
        d, decision, fps = live(a.kml, a.name, a.road_type, a.speed, a.lane_closure)
        print("recorded", d, decision, f"{len(fps)} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
