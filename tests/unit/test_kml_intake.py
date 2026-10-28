"""S1: WorkLocation model and KML intake (parse_all), the legacy adapter, the lineage key and the subprocess network block."""
import json, math, os, random, re, subprocess, sys

import pytest

from tcp_planner.config.settings import CONFIG_DIR, PROJECT_ROOT
from tcp_planner.contracts import InputRejected
from tcp_planner.geometry.local_frame import enu
from tcp_planner.intake import kml_reader
from tcp_planner.intake.kml_reader import parse_all
from tcp_planner.intake.lineage import lineage_key, zone_geometry_hash
from tcp_planner.intake.work_location import WorkLocation

KML_DIR = os.path.join(PROJECT_ROOT, "tests", "fixtures", "kml")
GRANITE = os.path.join(KML_DIR, "1A8G8FM WPI 3159540 GRANITE1.kml")
E_SECOND = os.path.join(KML_DIR, "1A8J1KB WPI 3171586 - E Second Street.kml")
COLORADO = os.path.join(KML_DIR, "WPI 3168057 130 COLORADO.kml")
with open(os.path.join(CONFIG_DIR, "pipeline_config.json"), encoding="utf-8") as f:
    DUP_M = json.load(f)["input"]["duplicate_distance_m"]


def kml(*placemarks, wrap="{}"):
    return ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            + wrap.format("".join(placemarks)) + "</Document></kml>").encode()


def pm(geom, name="x", extra=""):
    return f"<Placemark><name>{name}</name>{extra}{geom}</Placemark>"


def pt(lon, lat): return f"<Point><coordinates>{lon},{lat},0</coordinates></Point>"
def line(*lonlat): return "<LineString><coordinates>" + " ".join(f"{a},{b},0" for a, b in lonlat) + "</coordinates></LineString>"
def ring(*lonlat): return "<LinearRing><coordinates>" + " ".join(f"{a},{b},0" for a, b in lonlat) + "</coordinates></LinearRing>"


SQUARE = [(-71.0, 41.0), (-71.0, 41.001), (-70.999, 41.001), (-70.999, 41.0), (-71.0, 41.0)]
HOLE = [(-70.9995, 41.0003), (-70.9995, 41.0006), (-70.9993, 41.0006), (-70.9993, 41.0003), (-70.9995, 41.0003)]


def parse(data): return parse_all(data, duplicate_distance_m=DUP_M)
def gap(a, b): return math.dist(enu(*a.geometry["coords"], *b.geometry["coords"]), (0.0, 0.0))


# ---- real KMLs ---------------------------------------------------------------
def test_granite_five_points_with_gaps():
    locs = parse_all(GRANITE, duplicate_distance_m=DUP_M)
    assert [l.geometry["type"] for l in locs] == ["POINT"] * 5 and all(l.usable for l in locs)
    gaps = [gap(a, b) for a, b in zip(locs, locs[1:])]
    assert gaps == pytest.approx([32.2, 39.2, 36.4, 31.7], abs=0.1)


def test_e_second_two_points_and_colorado_one():
    e = parse_all(E_SECOND, duplicate_distance_m=DUP_M)
    assert len(e) == 2 and gap(*e) == pytest.approx(102.5, abs=0.1)
    c = parse_all(COLORADO, duplicate_distance_m=DUP_M)
    assert len(c) == 1 and c[0].usable


def test_record_shape_and_round_trip():
    l = parse_all(COLORADO, duplicate_distance_m=DUP_M)[0]
    d = l.to_dict()
    assert d["schema_version"] == "1" and d["role"] == "WORK" and d["source"]["file"] == os.path.basename(COLORADO)
    assert d["source"]["input_hash"].startswith("sha256:") and d["location_id"].startswith("LOC-")
    assert WorkLocation.from_dict(json.loads(json.dumps(d))) == l
    with pytest.raises(ValueError): WorkLocation.from_dict({**d, "schema_version": "0"})


# ---- ids ---------------------------------------------------------------------
def test_ids_independent_of_placemark_order():
    pms = [pm(pt(-71 + i * 1e-3, 41), f"P{i}") for i in range(5)] + [pm(line((-71, 41.01), (-71, 41.011)), "L"),
                                                                    pm(f"<Polygon><outerBoundaryIs>{ring(*SQUARE)}</outerBoundaryIs></Polygon>", "G")]
    base = {l.location_id: (l.geometry_hash, l.reject_reasons) for l in parse(kml(*pms))}
    for seed in range(5):
        shuffled = pms[:]; random.Random(seed).shuffle(shuffled)
        got = {l.location_id: (l.geometry_hash, l.reject_reasons) for l in parse(kml(*shuffled))}
        assert got == base


def test_ids_independent_of_names_and_file():
    a = parse(kml(pm(pt(-71, 41), "A"), pm(pt(-71.01, 41), "B")))
    b = parse(kml(pm(pt(-71, 41), "renamed 1"), pm(pt(-71.01, 41), "renamed 2")), )
    assert [l.location_id for l in a] == [l.location_id for l in b]
    assert [l.geometry_hash for l in a] == [l.geometry_hash for l in b]
    assert a[0].display_label == "A" and a[0].source.name == "A"


# ---- D-66: coordinates only ---------------------------------------------------
EXT = ('<ExtendedData><Data name="tcp:zone"><value>Z1</value></Data><Data name="tcp:ta"><value>TA-33</value></Data>'
       '<Data name="selected_ta"><value>TA-10</value></Data></ExtendedData>')


def strip_ids(locs):
    return [{k: v for k, v in l.to_dict().items() if k != "source"} for l in locs]


def test_extended_data_ignored():
    with_ext = kml(pm(pt(-71, 41), "A", EXT), pm(line((-71, 41.1), (-71, 41.101)), "B", EXT))
    without = kml(pm(pt(-71, 41), "A"), pm(line((-71, 41.1), (-71, 41.101)), "B"))
    a, b = parse(with_ext), parse(without)
    assert strip_ids(a) == strip_ids(b)
    assert a[0].source.input_hash != b[0].source.input_hash  # the only difference is the file hash


def test_geometry_inside_extended_data_is_never_read():
    poisoned = pm(pt(-71, 41), "A", f"<ExtendedData><Data name='x'>{pt(-72, 42)}</Data>{pt(-72, 42)}</ExtendedData>")
    locs = parse(kml(poisoned))
    assert len(locs) == 1 and locs[0].geometry["coords"] == [41.0, -71.0]


def test_real_kml_extended_data_equivalence():
    raw = open(GRANITE, "rb").read()
    stripped = re.sub(rb"<ExtendedData>.*?</ExtendedData>", b"", raw, flags=re.S)
    assert strip_ids(parse(raw)) == strip_ids(parse(stripped))


# ---- parse matrix ------------------------------------------------------------
def test_point_plus_line_in_one_placemark():
    locs = parse(kml(pm(f"<MultiGeometry>{pt(-71, 41)}{line((-71, 41), (-71, 41.001))}</MultiGeometry>", "both")))
    assert [l.geometry["type"] for l in locs] == ["POINT", "LINESTRING"]
    assert [(l.source.placemark_index, l.source.geometry_index) for l in locs] == [(0, 0), (0, 1)]
    assert len({l.location_id for l in locs}) == 2


def test_separate_placemarks_lone_line_and_nested_folders():
    assert len(parse(kml(pm(pt(-71, 41), "a"), wrap="<Folder><Folder>{}</Folder></Folder>"))) == 1
    assert [l.geometry["type"] for l in parse(kml(pm(line((-71, 41), (-71, 41.001))), pm(pt(-71, 42))))] == ["LINESTRING", "POINT"]
    nested = kml(pm(pt(-71, 41), "a"),
                 "<Folder><name>f</name>" + pm(line((-71, 42), (-71, 42.001)), "b")
                 + "<Folder>" + pm(pt(-71.5, 41), "c") + "</Folder></Folder>")
    locs = parse(nested)
    assert [l.geometry["type"] for l in locs] == ["POINT", "LINESTRING", "POINT"]
    assert [l.ordinal for l in locs] == [0, 1, 2]


def test_nested_multigeometry_is_flattened():
    inner = f"<MultiGeometry>{pt(-71, 41)}<MultiGeometry>{pt(-71.1, 41)}{pt(-71.2, 41)}</MultiGeometry></MultiGeometry>"
    assert [l.geometry["type"] for l in parse(kml(pm(inner)))] == ["POINT"] * 3


def test_polygon_with_and_without_holes():
    plain = parse(kml(pm(f"<Polygon><outerBoundaryIs>{ring(*SQUARE)}</outerBoundaryIs></Polygon>")))[0]
    holed = parse(kml(pm(f"<Polygon><outerBoundaryIs>{ring(*SQUARE)}</outerBoundaryIs>"
                         f"<innerBoundaryIs>{ring(*HOLE)}</innerBoundaryIs></Polygon>")))[0]
    assert plain.usable and holed.usable
    assert len(plain.geometry["coords"]) == 1 and len(holed.geometry["coords"]) == 2
    assert plain.geometry_hash != holed.geometry_hash


def test_long_line_is_not_rejected_by_parse_all():
    l = parse(kml(pm(line((-71, 41), (-71, 41.01)), "about 1.1 km")))[0]  # D-19 splitting happens in S9
    assert l.usable and l.geometry["type"] == "LINESTRING"


# ---- nothing is discarded ----------------------------------------------------
def test_unusable_features_keep_records_and_reasons():
    data = kml(
        pm(pt(-71, 41), "good"),
        pm("<Point><coordinates>abc,def</coordinates></Point>", "bad coords"),
        pm("<Point><coordinates>-71,95</coordinates></Point>", "out of range"),
        pm("<Point><coordinates>-71,41 -71.1,41</coordinates></Point>", "two coords in a point"),
        pm("<LineString><coordinates>-71,41</coordinates></LineString>", "one-point line"),
        pm("<Point><coordinates> </coordinates></Point>", "empty coords"),
        pm("", "no geometry"),
        pm(f"<Polygon><outerBoundaryIs>{ring(*SQUARE[:-1])}</outerBoundaryIs></Polygon>", "unclosed ring"),
        pm("<Model><Location><longitude>-71</longitude><latitude>41</latitude></Location></Model>", "model"),
        pm("<gx:Track xmlns:gx='http://www.google.com/kml/ext/2.2'><gx:coord>-71 41 0</gx:coord></gx:Track>", "track"),
        pm(ring(*SQUARE), "bare ring"),
    )
    locs = parse(data)
    assert len(locs) == 11
    assert [l.reject_reasons for l in locs] == [
        [], ["INVALID_GEOMETRY"], ["INVALID_GEOMETRY"], ["INVALID_GEOMETRY"], ["INVALID_GEOMETRY"], ["EMPTY"], ["EMPTY"],
        ["INVALID_GEOMETRY"], ["UNSUPPORTED_TYPE"], ["UNSUPPORTED_TYPE"], ["UNSUPPORTED_TYPE"]]
    assert len({l.location_id for l in locs}) == 11 and all(l.geometry is None for l in locs[1:])


def test_two_features_without_geometry_get_distinct_ids():
    a, b = parse(kml(pm("", "one"), pm("", "two")))
    assert a.location_id != b.location_id and a.reject_reasons == b.reject_reasons == ["EMPTY"]


# ---- duplicates (case 13: Points only) ----------------------------------------
def test_duplicates_under_one_metre():
    near = pt(-71.0, 41.0), pt(-71.0, 41.000005)  # about 0.56 m
    locs = parse(kml(pm(near[0], "a"), pm(near[1], "b")))
    keeper = next(l for l in locs if l.usable)
    dup = next(l for l in locs if not l.usable)
    assert dup.reject_reasons == [f"DUPLICATE_OF:{keeper.location_id}"] and dup.geometry is not None


def test_just_over_one_metre_is_not_a_duplicate():
    locs = parse(kml(pm(pt(-71.0, 41.0)), pm(pt(-71.0, 41.0000108))))  # about 1.2 m
    assert all(l.usable for l in locs)


def test_exact_duplicates_get_distinct_ids_and_the_first_is_kept():
    locs = parse(kml(pm(pt(-71, 41), "a"), pm(pt(-71, 41), "b"), pm(pt(-71, 41), "c")))
    assert len({l.location_id for l in locs}) == 3
    assert locs[0].usable and locs[1].reject_reasons == locs[2].reject_reasons == [f"DUPLICATE_OF:{locs[0].location_id}"]


def test_duplicate_choice_independent_of_order():
    a, b = pm(pt(-71.0, 41.0), "a"), pm(pt(-71.0, 41.000005), "b")
    def result(data): return {l.location_id: l.reject_reasons for l in parse(data)}
    assert result(kml(a, b)) == result(kml(b, a))


def test_lines_are_not_duplicate_checked():
    l = line((-71, 41), (-71, 41.001))
    assert all(x.usable for x in parse(kml(pm(l), pm(l))))


# ---- file level --------------------------------------------------------------
@pytest.mark.parametrize("data", [b"<kml><Document>", b'<!DOCTYPE kml [<!ENTITY x "y">]><kml/>', b"<other/>",
                                  b"x" * (5 * 1024 * 1024 + 1)],
                         ids=["truncated", "entity", "not-kml", "too-large"])
def test_file_level_rejection(data):
    with pytest.raises(InputRejected) as e: parse(data)
    assert e.value.reason_codes == ["INVALID_KML"]


def test_missing_file_rejected():
    with pytest.raises(InputRejected): parse_all("no/such.kml", duplicate_distance_m=DUP_M)


# ---- legacy adapter ----------------------------------------------------------
def test_legacy_single_point_matches_parse_all():
    pg = kml_reader.parse_kml(COLORADO, 150)
    l = parse_all(COLORADO, duplicate_distance_m=DUP_M)[0]
    assert pg["work_reference"] == {"latitude": l.geometry["coords"][0], "longitude": l.geometry["coords"][1]}
    assert pg["input_feature_count"] == 1 and pg["work_path"] == [] and pg["source_file"] == os.path.basename(COLORADO)


@pytest.mark.parametrize("path,code", [(GRANITE, "MULTIPLE_WORK_POINTS"), (E_SECOND, "MULTIPLE_WORK_POINTS")])
def test_legacy_still_rejects_multi_point(path, code):
    with pytest.raises(InputRejected) as e: kml_reader.parse_kml(path, 150)
    assert code in e.value.reason_codes


def test_legacy_line_limit_and_polygon(tmp_path):
    p = tmp_path / "long.kml"
    p.write_bytes(kml(pm(pt(-71, 41)), pm(line((-71, 41), (-71, 41.01)))))
    with pytest.raises(InputRejected) as e: kml_reader.parse_kml(str(p), 150)
    assert e.value.reason_codes == ["WORK_PATH_TOO_LONG"]
    p.write_bytes(kml(pm(pt(-71, 41)), pm(f"<Polygon><outerBoundaryIs>{ring(*SQUARE)}</outerBoundaryIs></Polygon>")))
    with pytest.raises(InputRejected) as e: kml_reader.parse_kml(str(p), 150)
    assert e.value.reason_codes == ["UNSUPPORTED_GEOMETRY"]


# ---- lineage key (wired in S3) ------------------------------------------------
def test_lineage_key():
    locs = parse_all(GRANITE, duplicate_distance_m=DUP_M)
    zh = zone_geometry_hash(locs)
    assert zone_geometry_hash(list(reversed(locs))) == zh and zone_geometry_hash(locs[:2]) != zh
    k = lineage_key("PRJ-1", zh)
    assert k == lineage_key("PRJ-1", zh) and len(k) == 16
    assert k != lineage_key("PRJ-2", zh) and k != lineage_key("PRJ-1", zone_geometry_hash(locs[:2]))
    with pytest.raises(ValueError): lineage_key("", zh)
    with pytest.raises(ValueError): zone_geometry_hash([])


# ---- network block reaches subprocesses --------------------------------------
PROBE = ("import socket,sys\n"
         "try: socket.socket().connect(('203.0.113.10', 80))\n"
         "except Exception as e: print(type(e).__name__); sys.exit(0)\n"
         "print('CONNECTED')\n")


def run_probe(env=None):
    return subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, timeout=60,
                          cwd=PROJECT_ROOT)


def test_subprocess_network_is_blocked():
    assert run_probe().stdout.strip() == "NetworkBlockedError"


def test_subprocess_with_explicit_env_needs_subprocess_env():
    from tests.support.netblock import subprocess_env
    bare = {k: v for k, v in os.environ.items() if k not in ("TCP_NETBLOCK", "PYTHONPATH")}
    assert run_probe(subprocess_env(bare)).stdout.strip() == "NetworkBlockedError"


def test_subprocess_loopback_stays_open():
    code = ("import socket\ns=socket.socket();s.bind(('127.0.0.1',0));s.listen(1)\n"
            "c=socket.create_connection(s.getsockname(),timeout=2);print('OK')\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT)
    assert r.stdout.strip() == "OK", r.stderr
