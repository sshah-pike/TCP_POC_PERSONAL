"""Runs built through the project path (S3): the only kind of run that has a lineage key (D-82, Q9-A).

zone_run          one point as a one-zone project, run in-process with the real worker -> run id
offline_zone_run  one offline scenario as a one-zone project

The offline scenarios predate the mandatory start fields: some have no speed, and `missing_road_type` has no road type.
offline_zone_run keeps each scenario's own operator values so the assistant suites see the same site facts as before, and
starts the run past the "all four fields typed" check (test only: the orchestrator's run() refuses an empty field).
"""
import copy

from tcp_planner.intake import kml_reader
from tcp_planner.orchestration import offline_scenarios as offline, projects as P
from tcp_planner.orchestration.project_runner import ProjectRunner
from tcp_planner.storage import run_store as store
from tests.support.project_fakes import InProcLauncher

FIELDS = {"road_type": "RURAL", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}


def _runner():
    return ProjectRunner(InProcLauncher(), poll_s=0.01)


def _force_run(runner, pid):
    """run() without the empty-field check: records the request, reserves ids, then drives the zone to the end."""
    def apply(cur):
        cur = copy.deepcopy(cur)
        cur["zones"] = P.build_zones(cur, pid)
        cur["run_request"] = {"zones_hash": P.zones_hash(cur["zones"]), "requested_at": "test"}
        for z in P.runnable_zones(cur["zones"]):
            if z["current_run_id"] is None:
                z["current_run_id"] = store.reserve_run_id(); z["run_ids"].append(z["current_run_id"])
        return cur
    runner.projects.update(pid, apply)
    return runner.drive(pid)


def zone_run(lat, lon, fields=None, advanced=None, scenario=None, force=False, name="coordinates"):
    r = _runner()
    loc = kml_reader.location_from_coordinates(lat, lon)
    view, _ = r.open_or_create(name=name, kind=P.OFFLINE if scenario else P.COORDINATES, locations=[loc],
                               advanced=advanced or {"no_dwt": True}, offline_scenario=scenario)
    pid = view["project_id"]
    r.set_inputs(pid, project=dict(FIELDS if fields is None else fields), apply_to_all=True)
    view = _force_run(r, pid) if force else r.run(pid, background=False)
    return view["zones"][0]["current_run_id"]


def offline_zone_run(scenario):
    sc = offline.build(scenario); op = sc["operator"]
    fields = {"road_type": op["road_type"], "posted_speed_mph": op["speed_mph"], "traffic_volume": "LOW",
              "lane_closure": bool(op["requires_lane_closure"])}
    return zone_run(sc["lat"], sc["lon"], fields=fields, scenario=scenario, force=True, name=f"offline {scenario}")
