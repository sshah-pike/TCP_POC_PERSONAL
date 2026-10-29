"""S3 commit 3: the project orchestrator (one run per zone, idempotent, cap, parallel limit) and the project command."""
import copy, json, os, shutil, threading, time

import pytest

from tcp_planner import cli
from tcp_planner.intake import kml_reader
from tcp_planner.orchestration import offline_scenarios as offline, projects as P, project_cli
from tcp_planner.orchestration.pipeline import load_config
from tcp_planner.orchestration.project_runner import ProjectRunner
from tcp_planner.orchestration.run_worker import resolve_argv
from tcp_planner.storage import run_records as records, run_store as store, stores
from tcp_planner.storage.rawpaths import find_raw_paths
from tests.support.rawpath_scan import scan_tree
from tests.support.project_fakes import CRASH, FakeLauncher, InProcLauncher, OK, REVIEW
from tests.integration.web_api.test_evidence_resume import env, http, LAT, LON  # noqa: F401  (fake Azure, OSM and AI)

CFG = load_config()
FIELDS = {"road_type": "RURAL", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}


def kml(points, extra=""):
    pms = "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
                  for n, lat, lon in points)
    return ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + pms + extra
            + "</Document></kml>").encode()


def pts(n, lat0=41.40, lon0=-71.70):
    return [(f"P{i + 1}", lat0 + 0.01 * i, lon0 - 0.01 * i) for i in range(n)]


@pytest.fixture
def runs_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    (tmp_path / "runs").mkdir()
    return tmp_path


def config(max_zones=3, parallel=3):
    cfg = copy.deepcopy(CFG); cfg["project"] = {"max_zones": max_zones, "max_parallel_zone_runs": parallel}
    return cfg


def make(runner, data, name="in.kml", fields=FIELDS, advanced=None):
    locs = kml_reader.parse_all(data, duplicate_distance_m=CFG["input"]["duplicate_distance_m"], file_name=name)
    view, _ = runner.open_or_create(name=name, kind=P.KML, locations=locs, upload=(name, data), advanced=advanced or {"no_dwt": True})
    pid = view["project_id"]
    if fields: runner.set_inputs(pid, project=fields, apply_to_all=True)
    return pid


def runner_for(launcher, **kw):
    return ProjectRunner(launcher, poll_s=0.01, config=config(**kw))


def run_dirs(tmp):
    return sorted(n for n in os.listdir(tmp / "runs") if store.RUN_ID_RE.match(n))


# ------------------------------------------------------------------ one run per zone, linked to the project
def test_three_points_three_runs_linked_to_the_project(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    view = r.run(pid, background=False)
    assert view["status"] == P.ALL_DRAFTED and len(fl.launched) == 3 and len(run_dirs(runs_env)) == 3
    assert len({z["lineage_key"] for z in view["zones"]}) == 3
    for z in view["zones"]:
        rid = z["current_run_id"]; req = records.read(rid, "request")
        assert req["request"]["project"] == {"project_id": pid, "zone_id": z["zone_id"], "zone_version": 1,
                                             "lineage_key": z["lineage_key"]}
        assert req["argv"][:2] == ["--zone", f"{rid}/input/zone_input.json"] and req["argv"][-2:] == ["--out", f"{rid}/output"]
        zi = json.load(open(resolve_argv(req["argv"])[1], encoding="utf-8"))
        assert zi["project_id"] == pid and zi["zone"]["zone_id"] == z["zone_id"] and zi["start_fields"] == FIELDS
        assert os.path.isabs(resolve_argv(req["argv"])[1]) and not [a for a in req["argv"] if os.path.isabs(a)]
        assert z["run_ids"] == [rid]


def test_three_point_kml_runs_through_the_real_worker(runs_env, env, monkeypatch):
    """Three points -> three real runs (fake Azure Maps, OSM and AI), each finished and linked to its zone."""
    http(monkeypatch)
    il = InProcLauncher(); r = runner_for(il)
    data = kml([("A", LAT, LON), ("B", LAT + 0.0001, LON), ("C", LAT, LON + 0.0001)])
    pid = make(r, data, advanced={"map_provider": "azure_maps", "ai_provider": "foundry", "no_dwt": True})
    view = r.run(pid, background=False)
    assert len(il.launched) == 3 and view["status"] in (P.ALL_DRAFTED, P.REVIEW_REQUIRED, P.PARTIAL, P.FAILED)
    for z in view["zones"]:
        st = store.build_state(z["current_run_id"], with_lineage=False)
        assert st["state"] == "FINISHED" and st["request"]["project"]["zone_id"] == z["zone_id"]
        assert json.load(open(store.run_path(z["current_run_id"], "output", "project_geometry.json"), encoding="utf-8"))["zone"]["zone_id"] == z["zone_id"]


def test_one_failed_zone_gives_partial_and_keeps_the_other_drafts(runs_env):
    fl = FakeLauncher(auto=[OK, CRASH, OK]); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    view = r.run(pid, background=False)
    assert view["status"] == P.PARTIAL
    states = [view["zone_runs"][z["current_run_id"]] for z in view["zones"]]
    assert [s["drafted"] for s in states] == [True, False, True]
    for z, s in zip(view["zones"], states):
        assert os.path.isfile(store.run_path(z["current_run_id"], "output", "plan.json")) == s["drafted"]


@pytest.mark.parametrize("outcome,status", [(REVIEW, P.FAILED), (CRASH, P.FAILED)])
def test_no_draft_in_any_zone_is_failed(runs_env, outcome, status):
    r = runner_for(FakeLauncher(auto=outcome)); pid = make(r, kml(pts(2)))
    assert r.run(pid, background=False)["status"] == status


def test_point_and_line_runs_the_point_only(runs_env):
    line = ("<Placemark><name>L</name><LineString><coordinates>-71.70,41.40,0 -71.7005,41.4003,0</coordinates>"
            "</LineString></Placemark>")
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(1), extra=line))
    view = r.run(pid, background=False)
    assert len(fl.launched) == 1 and view["status"] == P.PARTIAL
    assert [z["status"] for z in view["zones"]] == [P.ZONE_PENDING, P.ZONE_NOT_SUPPORTED]


# ------------------------------------------------------------------ start fields
def test_run_refused_while_a_start_field_is_empty(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)), fields={k: v for k, v in FIELDS.items() if k != "traffic_volume"})
    with pytest.raises(P.ProjectInputError) as e: r.run(pid, background=False)
    assert e.value.code == "START_FIELDS_MISSING" and len(e.value.details["missing"]) == 3
    assert fl.launched == [] and run_dirs(runs_env) == []
    rec = r.projects.get(pid)
    assert rec["start_fields"]["project"]["traffic_volume"] is None and rec["zones"][0]["current_run_id"] is None


def test_one_point_missing_a_field_blocks_the_whole_project(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    lid = r.projects.get(pid)["locations"][1]["location_id"]
    r.set_inputs(pid, project={"traffic_volume": None}, per_location={lid: {"traffic_volume": "HIGH"}})
    with pytest.raises(P.ProjectInputError) as e: r.run(pid, background=False)
    assert len(e.value.details["missing"]) == 2 and lid not in e.value.details["missing"] and fl.launched == []


# ------------------------------------------------------------------ idempotent retry
def test_running_twice_creates_no_second_run(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    first = r.run(pid, background=False)
    second = r.run(pid, background=False)
    assert [z["current_run_id"] for z in first["zones"]] == [z["current_run_id"] for z in second["zones"]]
    assert len(fl.launched) == 3 and len(run_dirs(runs_env)) == 3 and all(len(z["run_ids"]) == 1 for z in second["zones"])


def test_crash_between_reserve_and_build_is_completed_by_the_retry(runs_env, monkeypatch):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    real = ProjectRunner._materialize
    calls = []

    def flaky(self, project_id, rec, zone):
        calls.append(zone["zone_id"])
        if len(calls) == 2: raise RuntimeError("crash after the ids were reserved")
        return real(self, project_id, rec, zone)
    monkeypatch.setattr(ProjectRunner, "_materialize", flaky)
    with pytest.raises(RuntimeError): r.run(pid, background=False)
    reserved = [z["current_run_id"] for z in r.projects.get(pid)["zones"]]
    assert all(reserved) and len(run_dirs(runs_env)) == 1               # three ids reserved, one run built
    monkeypatch.setattr(ProjectRunner, "_materialize", real)
    view = r.run(pid, background=False)
    assert [z["current_run_id"] for z in view["zones"]] == reserved      # the same ids were built, none new
    assert len(run_dirs(runs_env)) == 3 and sorted(fl.launched) == sorted(reserved) and view["status"] == P.ALL_DRAFTED


def test_a_built_run_that_never_started_is_started_by_the_retry(runs_env):
    class Flaky(FakeLauncher):
        def launch(self, run_id):
            if not self.launched and not getattr(self, "failed", False):
                self.failed = True; raise OSError("cannot start the worker")
            super().launch(run_id)
    fl = Flaky(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    with pytest.raises(OSError): r.run(pid, background=False)
    assert fl.launched == [] and len(run_dirs(runs_env)) == 3            # all built, none started
    view = r.run(pid, background=False)
    assert len(fl.launched) == 3 and len(set(fl.launched)) == 3 and len(run_dirs(runs_env)) == 3
    assert view["status"] == P.ALL_DRAFTED


def test_two_concurrent_run_calls_make_one_set_of_runs(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    errors, barrier = [], threading.Barrier(2)

    def go():
        try: barrier.wait(); r.run(pid, background=False)
        except Exception as e: errors.append(e)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]; [t.join(30) for t in ts]
    assert errors == [] and len(fl.launched) == 3 and len(set(fl.launched)) == 3 and len(run_dirs(runs_env)) == 3
    assert all(len(z["run_ids"]) == 1 for z in r.projects.get(pid)["zones"])


def test_changed_inputs_give_a_new_version_and_a_new_run_only_for_that_zone(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl)
    pid = make(r, kml(pts(3)))
    first = r.run(pid, background=False)
    lid = r.projects.get(pid)["locations"][0]["location_id"]
    assert r.set_inputs(pid, per_location={lid: {"lane_closure": True}}) == P.READY
    second = r.run(pid, background=False)
    assert len(fl.launched) == 4
    z1, z2 = first["zones"], second["zones"]
    assert z2[0]["version"] == 2 and z2[0]["current_run_id"] != z1[0]["current_run_id"] and len(z2[0]["run_ids"]) == 2
    assert [z["current_run_id"] for z in z2[1:]] == [z["current_run_id"] for z in z1[1:]]


# ------------------------------------------------------------------ cap and parallel limit
def test_cap_holds_before_any_run_or_call(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl, max_zones=3)
    pid = make(r, kml(pts(4)))
    view = r.run(pid, background=False)
    assert view["status"] == P.ZONE_CAP_APPROVAL_REQUIRED and not view["cap_cleared"]
    assert fl.launched == [] and run_dirs(runs_env) == [] and all(z["current_run_id"] is None for z in view["zones"])
    assert r.run(pid, background=False)["status"] == P.ZONE_CAP_APPROVAL_REQUIRED   # asking again changes nothing
    done = r.approve_cap(pid, "SME", background=False)
    assert done["status"] == P.ALL_DRAFTED and len(fl.launched) == 4 and done["cap_approval"]["zone_count"] == 4


def test_at_the_cap_runs_without_approval_and_approval_needs_an_excess(runs_env):
    fl = FakeLauncher(auto=OK); r = runner_for(fl, max_zones=3)
    pid = make(r, kml(pts(3)))
    assert r.run(pid, background=False)["status"] == P.ALL_DRAFTED
    with pytest.raises(P.ProjectInputError) as e: r.approve_cap(pid, "SME")
    assert e.value.code == "CAP_NOT_EXCEEDED"


def test_five_zones_never_more_than_three_runs_active(runs_env):
    fl = FakeLauncher(); r = runner_for(fl, max_zones=10, parallel=3)
    pid = make(r, kml(pts(5)))
    r.run(pid, background=True)

    def wait(cond, what):
        end = time.time() + 20
        while not cond():
            assert time.time() < end, what; time.sleep(0.01)
    wait(lambda: len(fl.launched) == 3, "three runs start")
    time.sleep(0.2)
    assert len(fl.launched) == 3 and len(fl.live_ids()) == 3               # the other two queue
    finished = 0
    while finished < 5:
        wait(lambda: fl.live_ids(), "a run is active")
        fl.finish(sorted(fl.live_ids())[0], OK); finished += 1
        wait(lambda: len(fl.launched) == min(5, finished + 3) , "the next queued run starts")
        assert len(fl.live_ids()) <= 3
    wait(lambda: r.view(pid)["status"] == P.ALL_DRAFTED, "all drafted")
    assert fl.max_active == 3 and len(fl.launched) == 5 and len(set(fl.launched)) == 5


def test_zone_order_is_imagery_then_osm_then_ai(runs_env):
    """Inside one zone the pipeline order is unchanged (a zone run is one pipeline run)."""
    from tcp_planner.orchestration import pipeline
    import io, contextlib
    sc = offline.build("supported")
    kml_data = kml([("A", sc["lat"], sc["lon"])])
    r = runner_for(FakeLauncher(auto=OK)); pid = make(r, kml_data); r.run(pid, background=False)
    zone = r.projects.get(pid)["zones"][0]
    zpath = resolve_argv(records.read(zone["current_run_id"], "request")["argv"])[1]
    out = runs_env / "ord"
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        pipeline.main(["--offline", "supported", "--zone", zpath, "--no-dwt", "--out", str(out)])
    text = buf.getvalue()
    assert text.index("3 Imagery") < text.index("4 OSM") < text.index("5 AI vision")


# ------------------------------------------------------------------ create / reopen / re-upload
def test_same_geometry_reopens_the_project_and_labels_follow_the_latest_upload(runs_env):
    r = runner_for(FakeLauncher(auto=OK))
    first = kml(pts(3)); second = kml([(f"Renamed {i}", la, lo) for i, (_, la, lo) in enumerate(pts(3))])
    pid = make(r, first, name="first.kml")
    ids = [d["location_id"] for d in r.projects.get(pid)["locations"]]
    locs2 = kml_reader.parse_all(second, duplicate_distance_m=1.0, file_name="second.kml")
    view, created = r.open_or_create(name="second.kml", kind=P.KML, locations=locs2, upload=("second.kml", second))
    assert not created and view["project_id"] == pid and view["start_fields"]["project"] == FIELDS    # nothing reset
    assert len(view["inputs"]) == 2 and view["name"] == "second.kml"
    sha2 = view["inputs"][-1]["sha256"]
    assert set(view["labels"]) == set(ids)
    assert sorted(v["text"] for v in view["labels"].values()) == ["Renamed 0", "Renamed 1", "Renamed 2"]
    assert all(v["input_sha256"] == sha2 and v["input_key"] == view["inputs"][-1]["uri"] for v in view["labels"].values())
    assert view["inputs"][0]["sha256"] != sha2 and all(os.path.isfile(stores_path(i["uri"])) for i in view["inputs"])
    again, _ = r.open_or_create(name="second.kml", kind=P.KML, locations=locs2, upload=("second.kml", second))
    assert len(again["inputs"]) == 2                                                  # the same file is kept once


def stores_path(key):
    return os.path.join(os.path.abspath(stores.settings.runs_dir()), *key.split("/"))


def test_offline_scenarios_are_separate_projects(runs_env):
    r = runner_for(FakeLauncher(auto=OK))
    ids = set()
    for sc in ("supported", "encroach"):
        o = offline.build(sc)
        view, _ = r.open_or_create(name=f"offline {sc}", kind=P.OFFLINE, offline_scenario=sc,
                                   locations=[kml_reader.location_from_coordinates(o["lat"], o["lon"])])
        ids.add(view["project_id"])
    assert len(ids) == 2


def test_no_usable_location_makes_no_project(runs_env):
    r = runner_for(FakeLauncher(auto=OK))
    locs = kml_reader.parse_all(kml([]) .replace(b"</Document>", b"<Placemark><name>x</name></Placemark></Document>"),
                                duplicate_distance_m=1.0)
    with pytest.raises(P.ProjectInputError) as e: r.open_or_create(name="x.kml", kind=P.KML, locations=locs)
    assert e.value.code == "NO_USABLE_LOCATION" and r.projects.list() == []


# ------------------------------------------------------------------ moved runs folder
def test_moved_runs_folder_keeps_the_project_and_its_runs(runs_env, env, monkeypatch):
    """Run a project, move the whole runs folder, point the app at the new place: the project opens, a retry creates
    nothing, a zone run resumes with its project link, and no record or input names the old folder."""
    from tcp_planner.orchestration import run_relations as relations
    from tests.integration.web_api import inproc
    http(monkeypatch)
    r = runner_for(InProcLauncher())
    pid = make(r, kml([("A", LAT, LON), ("B", LAT + 0.0001, LON)]),
               advanced={"map_provider": "azure_maps", "ai_provider": "foundry", "no_dwt": True})
    before = r.run(pid, background=False)
    rids = [z["current_run_id"] for z in before["zones"]]
    old, new = runs_env / "runs", runs_env / "moved" / "elsewhere"
    new.parent.mkdir(); shutil.move(str(old), str(new)); assert not old.exists()
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(new))
    http(monkeypatch)
    il = InProcLauncher(); r2 = runner_for(il)
    after = r2.run(pid, background=False)
    assert [z["current_run_id"] for z in after["zones"]] == rids and il.launched == []
    child, cdir = relations.create_resume_run(rids[0], "vision", ai_profile="fake-a", ai_provider="foundry")
    inproc.run(cdir)
    cst = store.build_state(child, with_lineage=False)
    assert cst["state"] == "FINISHED" and cst["request"]["project"] == records.read(rids[0], "request")["request"]["project"]
    assert os.path.isfile(resolve_argv(records.read(child, "request")["argv"])[1])
    assert {f: h for f, h in scan_tree(str(new)).items() if h} == {}
    for base, _d, names in os.walk(str(new)):
        for n in names:
            if n.endswith((".json", ".jsonl")):
                with open(os.path.join(base, n), "rb") as f: assert str(old).encode() not in f.read(), n


# ------------------------------------------------------------------ the project command
def test_the_command_named_in_the_kml_message_exists(capsys):
    cmd = "python -m tcp_planner.cli project"
    assert cmd in kml_reader.MULTIPLE_POINTS_MESSAGE
    with pytest.raises(SystemExit) as e: cli.main(["project", "--help"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "usage: python -m tcp_planner.cli project" in out and "--kml" in out and "--road-type" in out


def test_project_command_needs_every_start_field(runs_env, capsys):
    kml_path = runs_env / "three.kml"; kml_path.write_bytes(kml(pts(3)))
    fl = FakeLauncher(auto=OK)
    code = project_cli.main(["--kml", str(kml_path), "--road-type", "RURAL", "--speed", "25", "--lane-closure", "no"],
                            runner=runner_for(fl))
    err = capsys.readouterr().err
    assert code == 2 and "START_FIELDS_MISSING" in err and err.count("traffic_volume") == 3 and fl.launched == []


def test_project_command_runs_a_three_point_kml(runs_env, capsys):
    kml_path = runs_env / "three.kml"; kml_path.write_bytes(kml(pts(3)))
    fl = FakeLauncher(auto=OK)
    code = project_cli.main(["--kml", str(kml_path), "--road-type", "RURAL", "--speed", "25", "--traffic-volume", "low",
                             "--lane-closure", "no", "--no-dwt"], runner=runner_for(fl))
    out = capsys.readouterr().out
    assert code == 0 and "created" in out and "ALL_DRAFTED" in out and len(fl.launched) == 3


def test_project_command_cap_message_and_exit(runs_env, capsys):
    kml_path = runs_env / "four.kml"; kml_path.write_bytes(kml(pts(4)))
    fl = FakeLauncher(auto=OK)
    args = ["--kml", str(kml_path), "--road-type", "RURAL", "--speed", "25", "--traffic-volume", "LOW", "--lane-closure", "no"]
    assert project_cli.main(args, runner=runner_for(fl)) == 2 and fl.launched == []
    assert "ZONE_CAP_APPROVAL_REQUIRED" in capsys.readouterr().out
    assert project_cli.main(args + ["--approve-cap"], runner=runner_for(fl)) == 0 and len(fl.launched) == 4
