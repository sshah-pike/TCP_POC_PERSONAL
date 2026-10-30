"""`python -m tcp_planner.cli project ...`: run a multi-point KML (or one point) as a project, one run per zone (S3 Q11-B).

The start fields are typed on the command line, exactly as in the UI: nothing here fills, derives or defaults one. A
project that is missing a field stops with INPUTS_REQUIRED and runs nothing.

Exit codes: 0 ALL_DRAFTED | 3 REVIEW_REQUIRED or PARTIAL | 1 FAILED | 2 the input, a start field or the zone cap needs
the user (nothing ran)
"""
import argparse, os, sys

from tcp_planner.config import settings
from tcp_planner.contracts import InputRejected
from tcp_planner.intake import kml_reader
from tcp_planner.orchestration import projects as P
from tcp_planner.orchestration.project_runner import ProjectRunner, SubprocessLauncher

EXIT_BY_STATUS = {P.ALL_DRAFTED: 0, P.REVIEW_REQUIRED: 3, P.PARTIAL: 3, P.FAILED: 1}
YES_NO = {"yes": True, "no": False}


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m tcp_planner.cli project", description=__doc__.split("\n\n")[0],
                                 epilog=__doc__.split("\n\n", 1)[1].strip(), formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--kml", help="KML of work locations (every Point becomes a zone)")
    src.add_argument("--offline", help="synthetic self-test scenario (an offline project: one point, simulated providers)")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--road-type", help="Table 6B-1 road type from the rule pack; typed by you, never inferred")
    ap.add_argument("--speed", type=int, help="posted speed in mph (a positive whole number)")
    ap.add_argument("--traffic-volume", choices=["HIGH", "LOW", "high", "low"])
    ap.add_argument("--lane-closure", choices=sorted(YES_NO), help="does the work need a lane closure")
    ap.add_argument("--ta", default=None, help="Select TA: AUTO, TA-1, TA-6, TA-10 or TA-33 (default AUTO)")
    ap.add_argument("--approve-cap", action="store_true", help="approve running more zones than project.max_zones")
    ap.add_argument("--no-dwt", action="store_true"); ap.add_argument("--map-provider"); ap.add_argument("--ai-provider")
    return ap


def _locations(a, cfg_dup):
    if a.offline:
        from tcp_planner.orchestration import offline_scenarios as offline
        sc = offline.build(a.offline)
        return [kml_reader.location_from_coordinates(sc["lat"], sc["lon"])], None, ("OFFLINE", sc["name"])
    with open(a.kml, "rb") as f: data = f.read()
    locs = kml_reader.parse_all(data, duplicate_distance_m=cfg_dup, file_name=os.path.basename(a.kml))
    return locs, (os.path.basename(a.kml), data), ("KML", None)


def main(argv=None, launcher=None, runner=None):
    a = build_parser().parse_args(argv)
    from tcp_planner.orchestration.pipeline import load_config, load_env_file, use_os_trust_store
    load_env_file(); use_os_trust_store()
    cfg = load_config()
    try: locs, upload, (kind, scenario) = _locations(a, cfg["input"]["duplicate_distance_m"])
    except (InputRejected, OSError) as e:
        print(f"error: {getattr(e, 'message', e)}", file=sys.stderr); return 2
    for l in locs:
        if l.reject_reasons: print(f"  location {l.ordinal + 1} ({l.display_label or 'no name'}): not used - {', '.join(l.reject_reasons)}")
    runner = runner or ProjectRunner(launcher or SubprocessLauncher(), poll_s=1.0, config=cfg)
    adv = {"no_dwt": True} if a.no_dwt else {}
    if a.map_provider and not a.offline: adv["map_provider"] = a.map_provider
    if a.ai_provider and not a.offline: adv["ai_provider"] = a.ai_provider
    try:
        view, created = runner.open_or_create(name=(upload[0] if upload else f"offline {scenario}"), kind=kind,
                                              locations=locs, upload=upload, advanced=adv, offline_scenario=scenario)
        pid = view["project_id"]
        print(f"Project {pid} ({'created' if created else 'reopened'}): {len([l for l in locs if l.usable])} usable location(s)")
        project_fields = {k: v for k, v in (("road_type", a.road_type), ("posted_speed_mph", a.speed),
                                            ("traffic_volume", a.traffic_volume), ("lane_closure", YES_NO.get(a.lane_closure))) if v is not None}
        runner.set_inputs(pid, project=project_fields or None, apply_to_all=bool(project_fields), ta_project=a.ta)
        view = runner.run(pid, background=False) if not a.approve_cap else runner.approve_cap(pid, "CLI --approve-cap", background=False)
    except P.ProjectInputError as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        for lid, fields in (e.details.get("missing") or {}).items(): print(f"  location {lid}: {', '.join(fields)}", file=sys.stderr)
        return 2
    if view["status"] == P.ZONE_CAP_APPROVAL_REQUIRED:
        n = len(P.runnable_zones(view["zones"]))
        print(f"{P.ZONE_CAP_APPROVAL_REQUIRED}: {n} zones, the cap is {view['max_zones']}. Nothing ran. Add --approve-cap to run them.")
        return 2
    print(f"Project status: {view['status']}")
    for z in view["zones"]:
        st = view["zone_runs"].get(z["current_run_id"]) or {}
        print(f"  {z['zone_id']} v{z['version']}  {z['status'] if z['status'] == P.ZONE_NOT_SUPPORTED else st.get('decision') or st.get('state')}"
              f"  run {z['current_run_id'] or '-'}")
    return EXIT_BY_STATUS.get(view["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
