"""S3 commit 2: one zone of a project as the pipeline's engine input (--zone), and the single-location --kml path."""
import json, os

import pytest

from tcp_planner.contracts import InputRejected, UNSUPPORTED_POC
from tcp_planner.intake import kml_reader
from tcp_planner.orchestration import offline_scenarios as offline, pipeline, projects as P
from tcp_planner.orchestration.pipeline import load_config, run_pipeline, zone_operator
from tcp_planner.rules.rule_pack_loader import load_rule_pack
from tests.support.providers import Harness

CFG = load_config()
ROAD_TYPES = load_rule_pack().road_types()
RECORDED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "fixtures", "recorded")
FILLED = {"road_type": "RURAL", "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}


def kml_bytes(*pms):
    return ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + "".join(pms)
            + "</Document></kml>").encode()


def pm(lat, lon, name="P", geom=None):
    return f"<Placemark><name>{name}</name>{geom or f'<Point><coordinates>{lon},{lat},0</coordinates></Point>'}</Placemark>"


def zone_files(tmp, data, fields=FILLED, ta=None, offline_scenario=None, file_name="in.kml"):
    """parse -> project record -> zones -> one zone_input.json per runnable zone. Returns (project_id, record, paths)."""
    locs = kml_reader.parse_all(data, duplicate_distance_m=CFG["input"]["duplicate_distance_m"], file_name=file_name)
    pid = P.project_id_for(locs, offline_scenario)
    rec = P.new_record(name=file_name, source={"kind": P.KML}, locations=locs)
    rec = P.set_inputs(rec, ROAD_TYPES, project=fields, ta_project=ta)
    rec["zones"] = P.build_zones(rec, pid)
    paths = []
    for z in P.runnable_zones(rec["zones"]):
        p = tmp / f"{z['zone_id']}.json"; p.write_text(json.dumps(P.zone_engine_input(rec, z, pid)), encoding="utf-8")
        paths.append(str(p))
    return pid, rec, paths


def offline_point():
    sc = offline.build("supported")
    return sc["lat"], sc["lon"]


def run_zone_cli(out, zone_path, *extra):
    return pipeline.main(["--offline", "supported", "--zone", zone_path, "--no-dwt", "--out", str(out), *extra])


def read(out, name):
    with open(os.path.join(out, name), encoding="utf-8") as f: return json.load(f)


# ------------------------------------------------------------------ from_zone
def test_from_zone_keeps_project_ids_and_names_out_of_the_geometry(tmp_path):
    lat, lon = offline_point()
    pid, rec, [path] = zone_files(tmp_path, kml_bytes(pm(lat, lon, "Pole 7")))
    zi = json.loads(open(path, encoding="utf-8").read())
    pg = kml_reader.from_zone(zi)
    z = rec["zones"][0]
    assert pg["input_type"] == "ZONE" and pg["source_file"] is None and pg["input_feature_count"] == 1
    assert pg["work_reference"] == {"latitude": lat, "longitude": lon} and pg["work_path"] == []
    assert pg["input_hash"] == z["engine_geometry_hash"]
    assert pg["zone"] == {"zone_id": z["zone_id"], "version": 1, "ta_hypothesis": "AUTO", "sheet_label": None,
                          "start_fields": FILLED}
    text = json.dumps(pg)
    assert pid not in text and z["lineage_key"] not in text and "Pole 7" not in text and "in.kml" not in text
    assert zi["project_id"] == pid and zi["lineage_key"] == z["lineage_key"]


def test_zone_operator_takes_only_the_start_fields():
    zi = {"start_fields": {"road_type": "RURAL", "posted_speed_mph": 30, "traffic_volume": "HIGH", "lane_closure": True},
          "zone": {"ta_hypothesis": "TA-6"}}
    assert zone_operator(zi, {"behind_barrier": "true"}) == {
        "road_type": "RURAL", "speed_mph": 30, "requires_lane_closure": True, "traffic_volume": "HIGH",
        "ta_hypothesis": "TA-6", "options": {"behind_barrier": "true"}}


def test_line_zone_does_not_run(tmp_path):
    line = "<LineString><coordinates>-71.70,41.40,0 -71.7005,41.4003,0</coordinates></LineString>"
    pid, rec, paths = zone_files(tmp_path, kml_bytes(pm(41.40, -71.70, "L", geom=line)))
    assert paths == [] and rec["zones"][0]["status"] == P.ZONE_NOT_SUPPORTED
    with pytest.raises(P.ProjectInputError) as e: P.zone_engine_input(rec, rec["zones"][0], pid)
    assert e.value.code == "ZONE_NOT_RUNNABLE"
    zi = {"schema_version": "1", "locations": rec["locations"], "start_fields": FILLED,
          "zone": {"zone_id": "Z", "version": 1, "ta_hypothesis": "AUTO", "sheet_label": None, "engine_geometry_hash": "h"}}
    with pytest.raises(InputRejected) as e: kml_reader.from_zone(zi)
    assert e.value.reason_codes == ["UNSUPPORTED_ZONE_GEOMETRY"]


def test_from_zone_refuses_an_unknown_schema():
    with pytest.raises(InputRejected) as e: kml_reader.from_zone({"schema_version": "9"})
    assert e.value.reason_codes == ["INVALID_ZONE_INPUT"]


# ------------------------------------------------------------------ zone runs (offline providers)
def test_zone_run_end_to_end(tmp_path):
    lat, lon = offline_point()
    _, _, [path] = zone_files(tmp_path, kml_bytes(pm(lat, lon)), offline_scenario="supported")
    out = tmp_path / "o"
    code = run_zone_cli(out, path)
    pg = read(out, "project_geometry.json")
    assert code in (0, 3) and pg["input_type"] == "ZONE" and os.path.isfile(out / "plan.json")
    sm = read(out, "site_model.json")
    assert sm["road"]["road_type"]["value"] == "RURAL" and sm["road"]["road_type"]["source"] == "OPERATOR"
    report = open(out / "run_report.txt", encoding="utf-8").read()
    assert "Select TA AUTO" in report and "25 mph" in report and "volume LOW" in report


def test_same_zone_same_site_model_in_any_project_or_upload(tmp_path):
    """Names, file name and project never reach the site model; the zone's geometry and inputs do (Q8-A)."""
    lat, lon = offline_point()
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir(); (tmp_path / "c").mkdir(); (tmp_path / "d").mkdir()
    pa, _, [a] = zone_files(tmp_path / "a", kml_bytes(pm(lat, lon, "Pole 1")), file_name="first.kml")
    pb, _, paths = zone_files(tmp_path / "b", kml_bytes(pm(lat, lon, "renamed"), pm(lat + 0.01, lon, "other")),
                              file_name="second.kml")
    assert pa != pb
    b = next(p for p in paths if os.path.basename(p) == os.path.basename(a))   # the same zone in another project
    _, _, [c] = zone_files(tmp_path / "c", kml_bytes(pm(lat, lon)), ta="TA-10")
    _, _, [d] = zone_files(tmp_path / "d", kml_bytes(pm(lat, lon)), fields=dict(FILLED, posted_speed_mph=35))
    ids = {}
    for k, p in (("a", a), ("b", b), ("c", c), ("d", d)):
        run_zone_cli(tmp_path / f"o{k}", p)
        ids[k] = read(tmp_path / f"o{k}", "site_model.json")["site_model_id"]
    assert ids["a"] == ids["b"]                                   # same zone, other project and upload
    assert ids["c"] != ids["a"] and ids["d"] != ids["a"]          # a TA selection or start field change is a new model


@pytest.mark.parametrize("extra", [("--road-type", "RURAL"), ("--speed", "30"), ("--requires-lane-closure",),
                                   ("--lat", "41", "--lon", "-71")])
def test_zone_refuses_other_start_field_sources(tmp_path, extra):
    lat, lon = offline_point()
    _, _, [path] = zone_files(tmp_path, kml_bytes(pm(lat, lon)))
    with pytest.raises(SystemExit) as e: run_zone_cli(tmp_path / "o", path, *extra)
    assert e.value.code == 2 and not (tmp_path / "o").exists()


# ------------------------------------------------------------------ single-location --kml path (Q11-B)
def test_kml_with_several_points_points_to_the_project_command(tmp_path):
    kml = offline.write_kml(str(tmp_path / "multi.kml"), extra_points=2)
    res = run_pipeline(out_dir=str(tmp_path / "o"), kml=kml)
    assert res["decision"] == UNSUPPORTED_POC and res["reason_codes"] == ["MULTIPLE_WORK_POINTS"]
    elig = read(tmp_path / "o", "eligibility_result.json")
    assert "3 usable work Points" in elig["message"] and "tcp_planner.cli project" in elig["message"]


def test_kml_with_an_exact_duplicate_is_one_location(tmp_path):
    lat, lon = offline_point()
    p = tmp_path / "dup.kml"; p.write_bytes(kml_bytes(pm(lat, lon, "a"), pm(lat, lon, "b")))
    pg = kml_reader.parse_kml(str(p), CFG["input"]["max_work_path_m"], CFG["input"]["duplicate_distance_m"])
    assert pg["work_reference"] == {"latitude": lat, "longitude": lon} and pg["input_feature_count"] == 1
    with pytest.raises(InputRejected): kml_reader.parse_kml(str(p), CFG["input"]["max_work_path_m"])  # old count


# ------------------------------------------------------------------ recorded fixtures
def test_one_zone_replays_the_recorded_single_point(tmp_path):
    """The recorded granite_p30 run, as a zone: every call is served by an existing fixture, with the same request
    fingerprints as the plain --kml replay."""
    h0 = Harness(os.path.join(RECORDED, "granite_p30"))
    r0 = run_pipeline(out_dir=str(tmp_path / "plain"), **h0.run_kwargs())
    h = Harness(os.path.join(RECORDED, "granite_p30"))
    with open(h.kml, "rb") as f: data = f.read()
    _, _, [path] = zone_files(tmp_path, data, fields=dict(FILLED, road_type=h.operator()["road_type"],
                                                          lane_closure=bool(h.operator()["requires_lane_closure"])))
    kw = h.run_kwargs(); kw.pop("kml")
    kw["operator"] = zone_operator(json.loads(open(path, encoding="utf-8").read()))
    r = run_pipeline(out_dir=str(tmp_path / "zone"), zone=path, **kw)
    assert h.fingerprints() == h0.fingerprints() and r["decision"] == r0["decision"]
