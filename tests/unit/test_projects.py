"""S3 commit 1: project and zone model (identity, start fields, zones, status). Pure functions, no I/O."""
import pytest

from tcp_planner.intake import kml_reader
from tcp_planner.intake.lineage import lineage_key, zone_geometry_hash
from tcp_planner.orchestration import projects as P
from tcp_planner.orchestration.pipeline import load_config
from tcp_planner.rules.rule_pack_loader import load_rule_pack
from tcp_planner.storage.rawpaths import find_raw_paths

ROAD_TYPES = load_rule_pack().road_types()
CFG = load_config()
DUP_M = CFG["input"]["duplicate_distance_m"]
FILLED = {"road_type": ROAD_TYPES[0], "posted_speed_mph": 25, "traffic_volume": "LOW", "lane_closure": False}


def kml(*placemarks):
    return ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + "".join(placemarks)
            + "</Document></kml>").encode()


def point(lon, lat, name="P"):
    return f"<Placemark><name>{name}</name><Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"


def line(coords, name="L"):
    return (f"<Placemark><name>{name}</name><LineString><coordinates>"
            + " ".join(f"{a},{b},0" for a, b in coords) + "</coordinates></LineString></Placemark>")


THREE = [point(-71.70, 41.40, "P1"), point(-71.71, 41.41, "P2"), point(-71.72, 41.42, "P3")]


def locs(*pms):
    return kml_reader.parse_all(kml(*pms), duplicate_distance_m=DUP_M)


def record(*pms, **kw):
    ls = locs(*pms)
    return P.project_id_for(ls), P.new_record(name="t.kml", source={"kind": P.KML}, locations=ls, **kw)


# ------------------------------------------------------------------ identity
def test_project_id_from_usable_geometry_only():
    a = P.project_id_for(locs(*THREE))
    renamed = [point(-71.72, 41.42, "X"), point(-71.70, 41.40, "Y"), point(-71.71, 41.41, "Z")]
    assert P.project_id_for(locs(*renamed)) == a                         # names and order never change it
    assert P.project_id_for(locs(*THREE[:2])) != a                       # geometry does
    assert P.project_id_for(locs(*THREE, point(-71.70, 41.40, "dup"))) == a       # an exact duplicate is not usable
    assert P.project_id_for(locs(*THREE), offline_scenario="supported") != a
    assert P.project_id_for(locs(*THREE), offline_scenario="supported") != P.project_id_for(locs(*THREE), offline_scenario="encroach")


def test_project_id_needs_a_usable_location():
    with pytest.raises(P.ProjectInputError) as e: P.project_id_for(locs("<Placemark><name>x</name></Placemark>"))
    assert e.value.code == "NO_USABLE_LOCATION"


def test_project_id_is_a_valid_store_id():
    from tcp_planner.storage.project_store import PROJECT_ID_RE
    assert PROJECT_ID_RE.match(P.project_id_for(locs(*THREE)))


def test_coordinates_location_matches_a_kml_point():
    k = locs(point(-71.741541, 41.4151206))[0]
    c = kml_reader.location_from_coordinates(41.4151206, -71.741541)
    assert (c.location_id, c.geometry_hash, c.geometry) == (k.location_id, k.geometry_hash, k.geometry)
    assert c.source.file is None and c.display_label is None and c.usable


# ------------------------------------------------------------------ new record and start fields
def test_new_record_starts_empty():
    _, rec = record(*THREE)
    assert rec["start_fields"] == {"project": {f: None for f in P.START_FIELDS}, "per_location": {}}
    assert rec["ta_hypothesis"] == {"project": "AUTO", "per_location": {}}
    assert rec["zones"] == [] and rec["status"] == P.INPUTS_REQUIRED and not find_raw_paths(rec)
    assert len(P.missing_fields(rec)) == 3


@pytest.mark.parametrize("vals", [{"road_type": "MOON"}, {"posted_speed_mph": 0}, {"posted_speed_mph": -5},
                                  {"posted_speed_mph": 25.5}, {"posted_speed_mph": "25"}, {"posted_speed_mph": True},
                                  {"traffic_volume": "MEDIUM"}, {"lane_closure": "yes"}, {"colour": "red"}])
def test_bad_start_fields_are_refused(vals):
    with pytest.raises(P.ProjectInputError) as e: P.check_start_fields(vals, ROAD_TYPES)
    assert e.value.code == "START_FIELDS_INVALID"


def test_start_fields_are_never_filled():
    assert P.check_start_fields({}, ROAD_TYPES) == {}
    assert P.check_start_fields({"road_type": None, "posted_speed_mph": ""}, ROAD_TYPES) == {"road_type": None, "posted_speed_mph": None}
    assert P.check_start_fields({"traffic_volume": "high", "posted_speed_mph": 120}, ROAD_TYPES) == {"traffic_volume": "HIGH", "posted_speed_mph": 120}
    pid, rec = record(*THREE)
    rec = P.set_inputs(rec, ROAD_TYPES, project={"road_type": ROAD_TYPES[0]})
    assert rec["start_fields"]["project"] == {"road_type": ROAD_TYPES[0], "posted_speed_mph": None,
                                             "traffic_volume": None, "lane_closure": None}
    for z in P.build_zones(rec, pid):
        assert z["inputs"]["posted_speed_mph"] is None and z["inputs"]["traffic_volume"] is None and z["inputs"]["lane_closure"] is None


def test_apply_to_all_and_per_point_overrides():
    pid, rec = record(*THREE)
    ids = [d["location_id"] for d in rec["locations"]]
    rec = P.set_inputs(rec, ROAD_TYPES, project=FILLED)
    assert P.missing_fields(rec) == {}
    rec = P.set_inputs(rec, ROAD_TYPES, per_location={ids[1]: {"posted_speed_mph": 40}}, ta_per_location={ids[2]: "ta-33"})
    assert P.effective_inputs(rec, ids[1])["posted_speed_mph"] == 40 and P.effective_inputs(rec, ids[0])["posted_speed_mph"] == 25
    assert P.effective_inputs(rec, ids[2])["ta_hypothesis"] == "TA-33" and P.effective_inputs(rec, ids[0])["ta_hypothesis"] == "AUTO"
    again = P.set_inputs(rec, ROAD_TYPES, project={"posted_speed_mph": 30}, apply_to_all=True)
    assert [P.effective_inputs(again, i)["posted_speed_mph"] for i in ids] == [30, 30, 30]
    kept = P.set_inputs(rec, ROAD_TYPES, project={"posted_speed_mph": 30})
    assert P.effective_inputs(kept, ids[1])["posted_speed_mph"] == 40          # without apply-to-all the override stays
    cleared = P.set_inputs(rec, ROAD_TYPES, per_location={ids[1]: {"posted_speed_mph": None}}, ta_per_location={ids[2]: None})
    assert P.effective_inputs(cleared, ids[1])["posted_speed_mph"] == 25 and P.effective_inputs(cleared, ids[2])["ta_hypothesis"] == "AUTO"
    assert cleared["start_fields"]["per_location"] == {}


def test_per_point_edits_check_the_location():
    pid, rec = record(*THREE, point(-71.70, 41.4000001, "dup"))
    dup = next(d["location_id"] for d in rec["locations"] if d["reject_reasons"])
    for kw, code in (({"per_location": {"LOC-nope": {"posted_speed_mph": 25}}}, "UNKNOWN_LOCATION"),
                     ({"per_location": {dup: {"posted_speed_mph": 25}}}, "LOCATION_NOT_USABLE"),
                     ({"ta_project": "TA-99"}, "TA_SELECTION_INVALID")):
        with pytest.raises(P.ProjectInputError) as e: P.set_inputs(rec, ROAD_TYPES, **kw)
        assert e.value.code == code


def test_one_empty_point_field_blocks_run():
    pid, rec = record(*THREE)
    ids = [d["location_id"] for d in rec["locations"]]
    rec = P.set_inputs(rec, ROAD_TYPES, project={k: v for k, v in FILLED.items() if k != "traffic_volume"},
                       per_location={ids[0]: {"traffic_volume": "HIGH"}})
    assert P.missing_fields(rec) == {ids[1]: ["traffic_volume"], ids[2]: ["traffic_volume"]}
    assert P.roll_up(rec, {}, CFG["project"]["max_zones"]) == P.INPUTS_REQUIRED


# ------------------------------------------------------------------ zones
def test_three_points_three_zones():
    pid, rec = record(*THREE)
    rec = P.set_inputs(rec, ROAD_TYPES, project=FILLED)
    zones = P.build_zones(rec, pid)
    assert len(zones) == 3 and len({z["zone_id"] for z in zones}) == 3 and len({z["lineage_key"] for z in zones}) == 3
    ls = P.locations_of(rec)
    for z, l in zip(zones, sorted(ls, key=lambda l: l.ordinal)):
        assert z["location_ids"] == [l.location_id] and z["status"] == P.ZONE_PENDING and z["version"] == 1
        assert z["engine_geometry_hash"] == zone_geometry_hash([l]) and z["lineage_key"] == lineage_key(pid, z["engine_geometry_hash"])
        assert z["grouping"]["method"] == P.ONE_PER_LOCATION and z["ta"] == {"value": "AUTO", "source": "UI", "status": "HYPOTHESIS"}
        assert z["sheet_label"] is None and z["current_run_id"] is None and z["schema_version"] == "1"


def test_zone_ids_ignore_names_and_project():
    pid, rec = record(*THREE)
    _, rec2 = record(point(-71.70, 41.40, "other name"))
    z1 = P.build_zones(P.set_inputs(rec, ROAD_TYPES, project=FILLED), pid)[0]
    z2 = P.build_zones(P.set_inputs(rec2, ROAD_TYPES, project=FILLED), "PRJ-other")[0]
    assert z1["zone_id"] == z2["zone_id"] and z1["lineage_key"] != z2["lineage_key"]


def test_point_and_line_runs_the_point_only():
    pid, rec = record(point(-71.70, 41.40), line([(-71.70, 41.40), (-71.7005, 41.4003)]))
    rec = P.set_inputs(rec, ROAD_TYPES, project=FILLED)
    zones = P.build_zones(rec, pid)
    assert [z["status"] for z in zones] == [P.ZONE_PENDING, P.ZONE_NOT_SUPPORTED]
    assert len(P.runnable_zones(zones)) == 1


def test_lines_do_not_need_start_fields():
    pid, rec = record(line([(-71.70, 41.40), (-71.7005, 41.4003)]))
    assert P.missing_fields(rec) == {}


def test_zone_version_changes_only_with_inputs():
    pid, rec = record(*THREE)
    rec = P.set_inputs(rec, ROAD_TYPES, project=FILLED)
    rec["zones"] = P.build_zones(rec, pid)
    for i, z in enumerate(rec["zones"]): z["current_run_id"] = f"run-{i}"; z["run_ids"] = [f"run-{i}"]
    assert P.build_zones(rec, pid) == rec["zones"]                    # unchanged: same versions and runs
    lid = rec["locations"][0]["location_id"]
    changed = P.set_inputs(rec, ROAD_TYPES, per_location={lid: {"lane_closure": True}})
    z = P.build_zones(changed, pid)
    assert z[0]["version"] == 2 and z[0]["current_run_id"] is None and z[0]["run_ids"] == ["run-0"]
    assert z[1:] == rec["zones"][1:]
    adv = dict(rec, advanced={"no_dwt": True})
    assert all(z["version"] == 2 for z in P.build_zones(adv, pid))   # advanced settings are inputs too
    ta = P.set_inputs(rec, ROAD_TYPES, ta_project="TA-10")
    assert all(z["version"] == 2 and z["ta"]["value"] == "TA-10" for z in P.build_zones(ta, pid))


# ------------------------------------------------------------------ status
def _ready(n=3, cap=3):
    pms = [point(-71.70 - 0.01 * i, 41.40 + 0.01 * i, f"P{i}") for i in range(n)]
    pid, rec = record(*pms)
    rec = P.set_inputs(rec, ROAD_TYPES, project=FILLED)
    return pid, rec


def _request(rec, pid):
    rec["zones"] = P.build_zones(rec, pid)
    rec["run_request"] = {"zones_hash": P.zones_hash(rec["zones"])}
    return rec


def _start(rec):
    for i, z in enumerate(rec["zones"]): z["current_run_id"] = f"r{i}"
    return rec


def done(drafted=True, decision="REVIEW_REQUIRED"):
    return {"state": P.FINISHED, "drafted": drafted, "decision": decision}


def test_status_before_and_at_run():
    pid, rec = _ready()
    assert P.roll_up(rec, {}, 3) == P.READY
    rec = _request(rec, pid)
    assert P.roll_up(rec, {}, 3) == P.RUNNING                         # asked, runs not yet reserved
    rec2 = P.set_inputs(rec, ROAD_TYPES, project={"posted_speed_mph": 35}); rec2["zones"] = P.build_zones(rec2, pid)
    assert P.roll_up(rec2, {}, 3) == P.READY                          # changed inputs need a new Run


def test_status_cap():
    pid, rec = _ready(4)
    rec = _request(rec, pid)
    assert P.cap_exceeded(rec["zones"], 3) and P.roll_up(rec, {}, 3) == P.ZONE_CAP_APPROVAL_REQUIRED
    rec["cap_approval"] = {"actor": "sme", "approved_at": "t"}                    # no zone count: covers nothing
    assert P.roll_up(rec, {}, 3) == P.ZONE_CAP_APPROVAL_REQUIRED
    rec["cap_approval"] = {"actor": "sme", "approved_at": "t", "zone_count": 3}   # approved for 3, there are 4
    assert P.roll_up(rec, {}, 3) == P.ZONE_CAP_APPROVAL_REQUIRED
    rec["cap_approval"] = {"actor": "sme", "approved_at": "t", "zone_count": 4}
    assert P.roll_up(rec, {}, 3) == P.RUNNING and P.cap_cleared(rec, 3)
    pid, rec3 = _ready(3)
    assert not P.cap_exceeded(_request(rec3, pid)["zones"], 3)


def test_status_after_runs():
    pid, rec = _ready()
    rec = _start(_request(rec, pid))
    assert P.roll_up(rec, {"r0": done(), "r1": {"state": P.ACTIVE}, "r2": {"state": P.QUEUED}}, 3) == P.RUNNING
    assert P.roll_up(rec, {"r0": done(), "r1": done(), "r2": done()}, 3) == P.REVIEW_REQUIRED
    auto = {f"r{i}": done(decision="SUPPORTED_AUTO") for i in range(3)}
    assert P.roll_up(rec, auto, 3) == P.ALL_DRAFTED
    assert P.roll_up(rec, {"r0": done(), "r1": done(False, None), "r2": done()}, 3) == P.PARTIAL
    assert P.roll_up(rec, {f"r{i}": done(False, "UNSUPPORTED_POC") for i in range(3)}, 3) == P.FAILED


def test_status_with_a_line_zone_is_partial():
    pid, rec = record(point(-71.70, 41.40), line([(-71.70, 41.40), (-71.7005, 41.4003)]))
    rec = _start(_request(P.set_inputs(rec, ROAD_TYPES, project=FILLED), pid))
    rec["zones"][1]["current_run_id"] = None
    assert P.roll_up(rec, {"r0": done(decision="SUPPORTED_AUTO")}, 3) == P.PARTIAL
