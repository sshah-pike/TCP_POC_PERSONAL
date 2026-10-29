"""S3 commit 4: the project API, the output index in the result record, the REVIEW_REQUIRED display fix and kml_key."""
import base64, hashlib, json, os, threading, time, urllib.error, urllib.request

import pytest

from tcp_planner.orchestration import offline_scenarios as offline, projects as P
from tcp_planner.orchestration import run_relations as relations
from tcp_planner.orchestration.project_runner import ProjectRunner
from tcp_planner.storage import run_records as records, run_store as store
from tcp_planner.storage.interfaces import media_type_for_key
from tcp_planner.storage.rawpaths import find_raw_paths
from tcp_planner.web_api import server
from tests.support.project_fakes import FakeLauncher, OK

FIELDS = {"road_type": "RURAL", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}


def kml(points):
    pms = "".join(f"<Placemark><name>{n}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
                  for n, lat, lon in points)
    return ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + pms
            + "</Document></kml>").encode()


def pts(n):
    return [(f"P{i + 1}", 41.40 + 0.01 * i, -71.70 - 0.01 * i) for i in range(n)]


def form(data, name="three.kml"):
    return {"input_type": "kml", "kml": {"filename": name, "content_base64": base64.b64encode(data).decode()},
            "advanced": {"no_dwt": True}}


@pytest.fixture
def web(tmp_path, monkeypatch):
    """The real HTTP server on a free port; its orchestrator launches fake runs unless a test restores the real one."""
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    fl = FakeLauncher(auto=OK)
    monkeypatch.setattr(server, "_RUNNER", ProjectRunner(fl, poll_s=0.01))
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait_status(pid, want, timeout=60):
        t0 = time.time()
        while True:
            st, v = call("GET", f"/api/projects/{pid}")
            if v["status"] in want: return v
            assert time.time() - t0 < timeout, f"status stayed {v['status']}"
            time.sleep(0.05)
    yield call, wait_status, fl, tmp_path
    srv.shutdown(); srv.server_close()


# ------------------------------------------------------------------ create, list, view
def test_meta_lists_the_form_choices(web):
    call, *_ = web
    st, meta = call("GET", "/api/meta")
    assert st == 200 and meta["start_fields"] == list(P.START_FIELDS) and meta["ta_choices"] == list(P.TA_CHOICES)
    assert meta["traffic_volumes"] == ["HIGH", "LOW"] and meta["max_zones"] == 3 and meta["max_parallel_zone_runs"] == 3
    assert "RURAL" in meta["road_types"]                     # the road types come from the rule pack


def test_create_a_project_from_a_three_point_kml(web):
    call, _w, fl, tmp = web
    st, v = call("POST", "/api/projects", form(kml(pts(3))))
    assert st == 201 and v["created"] and v["status"] == P.INPUTS_REQUIRED and fl.launched == []
    assert [r["label"] for r in v["location_rows"]] == ["P1", "P2", "P3"] and all(r["type"] == "POINT" for r in v["location_rows"])
    assert v["start_fields"] == {"project": {f: None for f in P.START_FIELDS}, "per_location": {}}   # nothing is filled
    assert v["ta_hypothesis"]["project"] == "AUTO" and len(v["missing_fields"]) == 3
    assert [i["sha256"] for i in v["inputs"]] == [hashlib.sha256(kml(pts(3))).hexdigest()]
    assert not find_raw_paths(v) and not [n for n in os.listdir(tmp / "runs") if store.RUN_ID_RE.match(n)]
    assert call("GET", "/api/projects") == (200, [{"project_id": v["project_id"], "name": "three.kml", "created_at": v["created_at"],
                                                   "status": P.INPUTS_REQUIRED, "zones": 0}])
    assert call("GET", f"/api/projects/{v['project_id']}")[1]["project_id"] == v["project_id"]
    assert call("GET", "/api/projects/PRJ-nope")[0] == 404 and call("GET", "/api/projects/..%2Fx")[0] == 400


def test_a_kml_with_no_usable_location_makes_no_project_and_shows_why(web):
    call, *_ = web
    bad = (b'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           b"<Placemark><name>nothing</name></Placemark>"
           b"<Placemark><name>bad</name><Point><coordinates>200,95,0</coordinates></Point></Placemark></Document></kml>")
    st, body = call("POST", "/api/projects", form(bad, "bad.kml"))
    assert st == 422 and body["error_code"] == "NO_USABLE_LOCATION"
    reasons = {r["label"]: r["reject_reasons"] for r in body["locations"]}
    assert reasons == {"nothing": ["EMPTY"], "bad": ["INVALID_GEOMETRY"]}
    assert call("GET", "/api/projects") == (200, [])


@pytest.mark.parametrize("payload,text", [({"input_type": "x"}, "input_type"),
                                          ({"input_type": "kml", "kml": {"filename": "a.kml", "content_base64": "###"}}, "base64"),
                                          ({"input_type": "coordinates", "lat": "", "lon": "1"}, "required"),
                                          ({"input_type": "coordinates", "lat": "95", "lon": "1"}, "range"),
                                          ({"input_type": "offline", "offline_scenario": "nope"}, "scenario"),
                                          ({"input_type": "offline", "offline_scenario": "supported",
                                            "advanced": {"dwt_mode": "BAD"}}, "dwt_mode")])
def test_bad_form_is_a_400(web, payload, text):
    call, *_ = web
    st, body = call("POST", "/api/projects", payload)
    assert st == 400 and text in body["error"]


def test_same_geometry_reopens_the_project_and_labels_follow_the_latest_upload(web):
    call, *_ = web
    _, a = call("POST", "/api/projects", form(kml(pts(2)), "first.kml"))
    again = [(f"Renamed {n}", la, lo) for n, la, lo in pts(2)]
    st, b = call("POST", "/api/projects", form(kml(again), "second.kml"))
    assert st == 200 and not b["created"] and b["project_id"] == a["project_id"] and len(b["inputs"]) == 2
    assert sorted(v["text"] for v in b["labels"].values()) == ["Renamed P1", "Renamed P2"]
    assert all(v["input_sha256"] == b["inputs"][-1]["sha256"] for v in b["labels"].values())
    assert len(call("GET", "/api/projects")[1]) == 1


# ------------------------------------------------------------------ typed fields and Run
def test_run_is_refused_until_every_field_is_typed(web):
    call, _w, fl, tmp = web
    _, v = call("POST", "/api/projects", form(kml(pts(3))))
    pid = v["project_id"]
    st, body = call("POST", f"/api/projects/{pid}/run", {})
    assert st == 409 and body["error_code"] == "START_FIELDS_MISSING" and len(body["missing"]) == 3
    assert all(m == list(P.START_FIELDS) for m in body["missing"].values())
    st, v = call("POST", f"/api/projects/{pid}/inputs", {"project": {k: x for k, x in FIELDS.items() if k != "lane_closure"},
                                                         "apply_to_all": True})
    assert st == 200 and v["status"] == P.INPUTS_REQUIRED and list(v["missing_fields"].values())[0] == ["lane_closure"]
    assert call("POST", f"/api/projects/{pid}/run", {})[0] == 409
    assert fl.launched == [] and not [n for n in os.listdir(tmp / "runs") if store.RUN_ID_RE.match(n)]


@pytest.mark.parametrize("body,code", [({"project": {"posted_speed_mph": 0}}, "START_FIELDS_INVALID"),
                                       ({"project": {"road_type": "MOON"}}, "START_FIELDS_INVALID"),
                                       ({"project": {"traffic_volume": "MEDIUM"}}, "START_FIELDS_INVALID"),
                                       ({"ta_project": "TA-99"}, "TA_SELECTION_INVALID"),
                                       ({"per_location": {"LOC-x": {"posted_speed_mph": 30}}}, "UNKNOWN_LOCATION")])
def test_invalid_typed_values_are_refused(web, body, code):
    call, *_ = web
    pid = call("POST", "/api/projects", form(kml(pts(1))))[1]["project_id"]
    st, err = call("POST", f"/api/projects/{pid}/inputs", body)
    assert st == 400 and err["error_code"] == code
    assert call("POST", f"/api/projects/{pid}/inputs", {"colour": "red"})[0] == 400


def test_full_flow_three_zones_to_all_drafted(web):
    call, wait, fl, tmp = web
    pid = call("POST", "/api/projects", form(kml(pts(3))))[1]["project_id"]
    st, v = call("POST", f"/api/projects/{pid}/inputs", {"project": FIELDS, "apply_to_all": True, "ta_project": "ta-6"})
    assert st == 200 and v["status"] == P.READY and v["ta_hypothesis"]["project"] == "TA-6" and v["missing_fields"] == {}
    st, v = call("POST", f"/api/projects/{pid}/run", {})
    assert st == 200
    v = wait(pid, {P.ALL_DRAFTED})
    assert len(fl.launched) == 3 and [z["version"] for z in v["zones"]] == [1, 1, 1]
    assert call("POST", f"/api/projects/{pid}/run", {})[1]["status"] == P.ALL_DRAFTED and len(fl.launched) == 3   # retry: nothing new
    _, runs = call("GET", "/api/runs")
    assert len(runs) == 3 and {r["project_id"] for r in runs} == {pid} and {r["zone_id"] for r in runs} == {z["zone_id"] for z in v["zones"]}
    assert all(r["input"].startswith("Zone ZONE-") and r["decision"] == "SUPPORTED_AUTO" and r["service_error"] is False for r in runs)
    st, one = call("GET", f"/api/runs/{v['zones'][0]['current_run_id']}")
    assert one["request"]["project"]["zone_id"] == v["zones"][0]["zone_id"] and one["request"]["operator"]["ta_hypothesis"] == "TA-6"


def test_cap_over_http(web):
    call, wait, fl, tmp = web
    pid = call("POST", "/api/projects", form(kml(pts(4))))[1]["project_id"]
    call("POST", f"/api/projects/{pid}/inputs", {"project": FIELDS, "apply_to_all": True})
    st, v = call("POST", f"/api/projects/{pid}/run", {})
    assert st == 200 and v["status"] == P.ZONE_CAP_APPROVAL_REQUIRED and v["max_zones"] == 3 and not v["cap_cleared"]
    assert fl.launched == [] and call("GET", "/api/runs") == (200, [])
    st, v = call("POST", f"/api/projects/{pid}/approve-cap", {"approved_by": "Jane SME"})
    assert st == 200 and v["cap_approval"]["approved_by"] == "Jane SME" and v["cap_approval"]["zone_count"] == 4
    assert v["cap_approval"]["verified"] is False                                   # typed text, not an identity (S10 follow-up)
    wait(pid, {P.ALL_DRAFTED}); assert len(fl.launched) == 4
    assert call("POST", f"/api/projects/{pid}/approve-cap", {})[0] == 200 and len(fl.launched) == 4   # approving again starts nothing
    within = call("POST", "/api/projects", form(kml(pts(3)), "three.kml"))[1]["project_id"]
    st, err = call("POST", f"/api/projects/{within}/approve-cap", {})
    assert st == 409 and err["error_code"] == "CAP_NOT_EXCEEDED"                                    # nothing to approve within the cap


def test_a_project_is_only_reachable_through_its_routes(web):
    call, *_ = web
    pid = call("POST", "/api/projects", form(kml(pts(1))))[1]["project_id"]
    assert call("GET", f"/api/projects/{pid}/run")[0] == 404 and call("POST", f"/api/projects/{pid}/nothing", {})[0] == 404
    assert call("POST", "/api/projects/PRJ-nope/run", {})[0] == 404


# ------------------------------------------------------------------ the real worker, the output index, the status
def test_offline_project_end_to_end_with_the_output_index(web, monkeypatch):
    """One offline scenario as a one-zone project: the real runner subprocess, then the output index in the result record."""
    call, wait, fl, tmp = web
    monkeypatch.setattr(server, "_RUNNER", ProjectRunner(server._ServerLauncher(), poll_s=0.2))
    st, v = call("POST", "/api/projects", {"input_type": "offline", "offline_scenario": "supported", "advanced": {"no_dwt": True}})
    assert st == 201; pid = v["project_id"]
    call("POST", f"/api/projects/{pid}/inputs", {"project": FIELDS, "apply_to_all": True})
    assert call("POST", f"/api/projects/{pid}/run", {})[0] == 200
    v = wait(pid, {P.ALL_DRAFTED, P.REVIEW_REQUIRED, P.PARTIAL, P.FAILED}, timeout=240)
    rid = v["zones"][0]["current_run_id"]
    result = records.read(rid, "result")
    out = store.run_path(rid, "output"); files = sorted(n for n in os.listdir(out) if os.path.isfile(os.path.join(out, n)))
    index = result["output_index"]
    assert [x["name"] for x in index] == files                                          # every output file, rendered files too
    assert {"aerial_image.jpg", "debug_plan.png", "debug_plan.pdf", "run_report.txt"} <= set(files)   # rendered files are in it
    for x in index:
        data = open(os.path.join(out, x["name"]), "rb").read()
        assert x["uri"] == f"{rid}/output/{x['name']}" and x["sha256"] == hashlib.sha256(data).hexdigest() and x["size"] == len(data)
        assert x["media_type"] == media_type_for_key(x["name"])
    # the run record keeps the exact start values that were used (typed -> request record -> zone input -> geometry)
    req = records.read(rid, "request")
    assert req["request"]["operator"] == {"road_type": "RURAL", "speed": 25, "requires_lane_closure": False, "traffic_volume": "LOW",
                                          "ta_hypothesis": "AUTO", "options": []}
    zi = json.load(open(records.resolve(req["argv"][1]), encoding="utf-8"))
    assert zi["start_fields"] == FIELDS
    assert json.load(open(os.path.join(out, "project_geometry.json"), encoding="utf-8"))["zone"]["start_fields"] == FIELDS
    sm = json.load(open(os.path.join(out, "site_model.json"), encoding="utf-8"))
    assert sm["road"]["road_type"]["value"] == "RURAL" and sm["road"]["road_type"]["source"] == "OPERATOR"
    assert "output_refs" not in result and "out_dir" not in result and not find_raw_paths(result)
    st, run = call("GET", f"/api/runs/{rid}")
    assert {o["name"]: o["sha256"] for o in run["outputs"]} == {x["name"]: x["sha256"] for x in index}   # shown with the files
    assert run["request"]["project"]["project_id"] == pid


def test_the_tcp_sheet_files_are_in_the_output_index(web, monkeypatch):
    """With sheet rendering enabled, tcp_sheet.png and tcp_sheet.pdf are registered after the renderer wrote them and are
    in the output index with the right hash and size."""
    call, wait, fl, tmp = web
    monkeypatch.setenv("TCP_RENDER_SHEET", "1")                       # the runner subprocess inherits it
    monkeypatch.setattr(server, "_RUNNER", ProjectRunner(server._ServerLauncher(), poll_s=0.2))
    pid = call("POST", "/api/projects", {"input_type": "offline", "offline_scenario": "supported",
                                         "advanced": {"no_dwt": True}})[1]["project_id"]
    call("POST", f"/api/projects/{pid}/inputs", {"project": FIELDS, "apply_to_all": True})
    assert call("POST", f"/api/projects/{pid}/run", {})[0] == 200
    v = wait(pid, {P.ALL_DRAFTED, P.REVIEW_REQUIRED, P.PARTIAL, P.FAILED}, timeout=420)
    assert v["status"] == P.ALL_DRAFTED
    rid = v["zones"][0]["current_run_id"]
    index = {x["name"]: x for x in records.read(rid, "result")["output_index"]}
    out = store.run_path(rid, "output")
    for name, media in (("tcp_sheet.png", "image/png"), ("tcp_sheet.pdf", "application/pdf")):
        data = open(os.path.join(out, name), "rb").read()
        x = index[name]
        assert x["uri"] == f"{rid}/output/{name}" and x["media_type"] == media
        assert x["sha256"] == hashlib.sha256(data).hexdigest() and x["size"] == len(data) > 0
    assert sorted(index) == sorted(n for n in os.listdir(out) if os.path.isfile(os.path.join(out, n)))


# ------------------------------------------------------------------ status fix and kml_key
def test_service_codes_never_change_the_decision():
    assert store.service_codes(["AI_CALL2_UNAVAILABLE", "ROAD_TYPE_UNRESOLVED", "AI_CALL2_UNAVAILABLE"]) == ["AI_CALL2_UNAVAILABLE"]
    assert store.service_codes(["ROAD_TYPE_UNRESOLVED"]) == [] and store.service_codes(None) == []


def test_review_required_with_a_service_code_is_shown_as_review_required(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    sc = offline.build("supported")
    rid = store.reserve_run_id(); store.ensure_run_dirs(rid)
    records.create(rid, "request", {"run_id": rid, "created_at": "t", "argv": [], "request": {"input_type": "coordinates"}})
    records.write(rid, "process", {"state": "FINISHED", "exit_code": 3})
    records.write(rid, "result", {"decision": "REVIEW_REQUIRED", "reason_codes": ["AI_CALL2_UNAVAILABLE", "ROAD_TYPE_UNRESOLVED"]})
    st = store.build_state(rid)
    assert st["decision"] == "REVIEW_REQUIRED" and st["exit_code"] == 3 and st["service_error"] == ["AI_CALL2_UNAVAILABLE"]
    assert store.list_runs()[0]["decision"] == "REVIEW_REQUIRED" and store.list_runs()[0]["service_error"] is True
    records.write(rid, "result", {"decision": "REVIEW_REQUIRED", "reason_codes": ["ROAD_TYPE_UNRESOLVED"]})
    assert store.build_state(rid)["service_error"] is None


def test_kml_key_has_a_fallback_reader_for_runs_made_before_s3(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    new = {"request": {"input_type": "kml", "kml_key": "r1/input/site.kml"}}
    old = {"request": {"input_type": "kml", "kml_saved_path": "r1/input/site.kml"}}   # a run made in S2
    assert relations._input_file("r1", new) == records.resolve("r1/input/site.kml")
    assert relations._input_file("r1", old) == records.resolve("r1/input/site.kml")
    assert relations._input_file("r1", {"request": {"input_type": "kml"}}) is None
