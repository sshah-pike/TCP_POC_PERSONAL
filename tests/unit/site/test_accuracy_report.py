"""The accuracy report (S6 accuracy tooling): synthetic truth CSV and synthetic call 1 results; offline and deterministic."""
import csv, importlib.util, json, os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PX_IS_FT = 0.3048


@pytest.fixture(scope="module")
def R():
    spec = importlib.util.spec_from_file_location("s06_accuracy_report", os.path.join(ROOT, "scripts", "s06_accuracy_report.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


FIELDS18 = ["work_location", "work_side", "lanes_per_direction", "oneway", "shoulder_present", "divided_highway", "median_work", "bicycle_lane_present",
            "sidewalk_present", "sidewalk_side", "parking_present", "bus_stop_present", "driveway_present", "crosswalk_present",
            "intersection_in_view", "grade_crossing_present", "obstructions", "approaching_lanes_one"]
DEFAULT = {"work_location": ("BEYOND_SHOULDER", 0.9), "work_side": ("W", 0.9), "lanes_per_direction": (1, 0.8), "oneway": (False, 0.8),
           "shoulder_present": (False, 0.8), "divided_highway": (False, 0.8), "sidewalk_present": (True, 0.8), "parking_present": (False, 0.8)}


def raw(values, width_px=None):
    """A call 1 response document. values: field -> (value, confidence) or None for UNKNOWN; absent fields are UNKNOWN."""
    facts = []
    for f in FIELDS18:
        v = {**DEFAULT, **values}.get(f)
        if v is None or v[0] is None:
            facts.append({"field": f, "value": "UNKNOWN", "unit": "bool", "status": "UNKNOWN", "confidence": 0.2, "evidence": "not_visible"})
        else:
            val = v[0]
            sv = str(val).lower() if isinstance(val, bool) else str(val)
            facts.append({"field": f, "value": sv, "unit": "bool", "status": "RESOLVED", "confidence": v[1], "evidence": "e"})
    marks = []
    if width_px:
        marks = [{"feature": "road_edge_left", "points": f"100,{500 - width_px / 2};400,{500 - width_px / 2}", "status": "RESOLVED", "evidence": "e"},
                 {"feature": "road_edge_right", "points": f"100,{500 + width_px / 2};400,{500 + width_px / 2}", "status": "RESOLVED", "evidence": "e"}]
    return json.dumps({"facts": facts, "marks": marks})


def write_results(folder, site, calls):
    """calls: list of (values, width_px)."""
    os.makedirs(folder, exist_ok=True)
    for i, (values, w) in enumerate(calls, start=1):
        json.dump({"site": site, "rep": i, "image": {"sent_px": [1280, 1280], "mpp_sent": PX_IS_FT}, "raw_response": raw(values, w)},
                  open(os.path.join(folder, f"{site}_r{i}.json"), "w", encoding="utf-8"))


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns); w.writeheader()
        for r in rows: w.writerow({c: r.get(c, "") for c in columns})


TRUTH = [
    {"site_id": "A", "lanes_per_direction": 1, "divided_highway": "false", "shoulder_present": "false", "oneway": "false", "parking_present": "false",
     "sidewalk_present": "true", "work_location": "BEYOND_SHOULDER", "road_width_ft": 24, "truth_source": "drawing"},
    {"site_id": "B", "lanes_per_direction": 2, "divided_highway": "true", "shoulder_present": "true", "oneway": "false", "parking_present": "true",
     "sidewalk_present": "false", "work_location": "IN_LANE", "road_width_ft": 48, "truth_source": "survey"},
    {"site_id": "C", "lanes_per_direction": 1, "divided_highway": "false", "shoulder_present": "true", "oneway": "true", "parking_present": "",
     "sidewalk_present": "", "work_location": "", "road_width_ft": "", "truth_source": "survey"},
]


@pytest.fixture
def world(tmp_path, R):
    t = tmp_path / "truth.csv"; write_csv(t, TRUTH, R.COLUMNS)
    p1 = tmp_path / "results" / "prof1"
    # site A: lanes 1,1,2 (one wrong, at 0.95), sidewalk right; width 26 px (error +2) and 40 px (error +16)
    write_results(p1, "A", [({"lanes_per_direction": (1, 0.8)}, 26), ({"lanes_per_direction": (1, 0.7)}, 40), ({"lanes_per_direction": (2, 0.95)}, 26)])
    # site B: lanes 2 right, divided wrongly false at 0.9, shoulder unknown, parking true right, work_location ROADWAY at 0.9 (IN_LANE) and 0.84 (UNKNOWN)
    write_results(p1, "B", [({"lanes_per_direction": (2, 0.8), "divided_highway": (False, 0.9), "shoulder_present": None, "parking_present": (True, 0.7),
                              "sidewalk_present": (False, 0.6), "work_location": ("ROADWAY", 0.9)}, 48),
                            ({"lanes_per_direction": (2, 0.8), "divided_highway": (True, 0.9), "shoulder_present": (True, 0.5), "parking_present": (False, 0.7),
                              "sidewalk_present": (False, 0.6), "work_location": ("ROADWAY", 0.84)}, None)])
    write_results(p1, "C", [({"lanes_per_direction": (1, 0.9), "oneway": (True, 0.9), "shoulder_present": (True, 0.9), "divided_highway": (False, 0.9)}, None)])
    sec = tmp_path / "second.csv"
    write_csv(sec, [{"site_id": "A", "lanes_per_direction": 2, "divided_highway": "false", "shoulder_present": "false", "oneway": "false"},
                    {"site_id": "B", "lanes_per_direction": 2, "divided_highway": "false", "shoulder_present": "true", "oneway": "false"},
                    {"site_id": "C", "lanes_per_direction": 1, "divided_highway": "", "shoulder_present": "true", "oneway": "true"}], R.SECOND_COLUMNS)
    return tmp_path, t, p1, sec


def run(R, world, second=True):
    tmp, t, p1, sec = world
    truth = R.read_truth(str(t)); s = R.read_second(str(sec)) if second else {}
    return R.score(truth, {"prof1": R.read_results(str(p1))}, s), truth, s


# ---------------------------------------------------------------- the counts
def test_counts_for_lanes_per_direction_without_a_second_source(R, world):
    rep, _, _ = run(R, world, second=False)
    d = rep["prof1"]["fields"]["lanes_per_direction"]
    assert (d["sites"], d["calls"], d["correct"], d["wrong"], d["unknown"]) == (["A", "B", "C"], 6, 5, 1, 0)
    assert (d["used"], d["wrong_and_used"]) == (0, 0)                      # no second source: nothing safety-critical is passed on
    assert [(x["site"], x["value"], x["confidence"]) for x in d["wrong_rows"]] == [("A", 2, 0.95)]    # the wrong answer, with its confidence


def test_with_a_second_source_only_agreeing_values_are_passed_on(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["lanes_per_direction"]
    # A: AI 1,1,2 vs OSM 2 -> only the (wrong) 2 agrees: passed on and WRONG. B: 2,2 vs 2 -> used, right. C: 1 vs 1 -> used, right.
    assert d["used"] == 4 and d["wrong_and_used"] == 1 and d["wrong_and_used_sites"] == ["A"]


def test_a_value_where_ai_and_the_second_source_disagree_is_not_passed_on(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["divided_highway"]                          # B: AI false,true vs OSM false; truth true
    rows = {x["call"]: x for x in d["wrong_rows"]}
    assert d["wrong"] == 1 and "B_r1.json" in rows and rows["B_r1.json"]["confidence"] == 0.9
    assert rows["B_r1.json"]["wrong_and_used"] is True                     # AI false = OSM false: two agreeing sources, both wrong
    assert d["correct"] == 5 and d["wrong_and_used"] == 1 and d["used"] == 4      # B_r2 says true but OSM says false: not passed on


def test_a_missing_second_source_value_blocks_passing_on(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["divided_highway"]
    # OSM has no divided value at C: C's answer is right but is not passed on. used = A x3 + B_r1 (agrees, wrong) = 4, not 5 or 6.
    assert d["used"] == 4 and d["calls"] == 6 and d["stability"]["C"]["values"] == [False]


def test_unknown_answers_are_counted_and_never_passed_on(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["shoulder_present"]
    assert d["unknown"] == 1 and d["correct"] == 5 and d["wrong"] == 0 and d["wrong_and_used"] == 0


def test_a_field_with_no_truth_at_a_site_is_not_scored_there(R, world):
    rep, _, _ = run(R, world)
    assert rep["prof1"]["fields"]["parking_present"]["sites"] == ["A", "B"]          # C has a blank truth
    assert rep["prof1"]["fields"]["work_location"]["sites"] == ["A", "B"]


def test_common_facts_are_passed_on_without_a_floor_while_it_is_pending(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["parking_present"]                           # A false (3 calls, right), B true right, false wrong
    assert d["wrong"] == 1 and d["wrong_and_used"] == 1 and d["used"] == d["calls"]
    assert d["wrong_rows"][0]["confidence"] == 0.7


def test_work_location_honours_the_floor_and_the_registry_mapping(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["work_location"]
    # A: three calls BEYOND_SHOULDER at 0.9 -> correct. B: ROADWAY 0.9 -> IN_LANE correct; ROADWAY 0.84 -> UNKNOWN (below the 0.85 floor)
    assert (d["calls"], d["correct"], d["wrong"], d["unknown"]) == (5, 4, 0, 1)
    assert d["used"] == 4 and d["wrong_and_used"] == 0


def test_a_wrong_work_location_is_flagged_as_ai_only_unconfirmed(R, tmp_path):
    t = tmp_path / "t.csv"; write_csv(t, [{"site_id": "A", "work_location": "ON_SHOULDER_OR_ENCROACHING", "truth_source": "x"}], R.COLUMNS)
    write_results(tmp_path / "r" / "p", "A", [({"work_location": ("ROADWAY", 0.95)}, None)])
    rep = R.score(R.read_truth(str(t)), {"p": R.read_results(str(tmp_path / "r" / "p"))})
    x = rep["p"]["fields"]["work_location"]["wrong_rows"][0]
    assert x["value"] == "IN_LANE" and x["wrong_and_used"] and "AI_ONLY_UNCONFIRMED" in x["flags"] and x["confidence"] == 0.95


# ---------------------------------------------------------------- stability, width, the bound
def test_repeat_stability_per_site(R, world):
    rep, _, _ = run(R, world)
    st = rep["prof1"]["fields"]["lanes_per_direction"]["stability"]
    assert st["A"] == {"values": [1, 1, 2], "stable": False} and st["B"]["stable"] and st["C"]["stable"]


def test_width_error_and_whether_the_interval_holds_the_truth(R, world):
    rep, _, _ = run(R, world)
    w = rep["prof1"]["width"]
    rows = {x["call"]: x for x in w["rows"]}
    assert rows["A_r1.json"]["error"] == pytest.approx(2.0) and rows["A_r1.json"]["contains"] is True            # 26 vs 24, interval +/- 6
    assert rows["A_r2.json"]["error"] == pytest.approx(16.0) and rows["A_r2.json"]["contains"] is False          # 40 vs 24
    assert rows["B_r1.json"]["error"] == pytest.approx(0.0) and rows["B_r2.json"]["measured"] is None            # no marks: not measured
    assert w["calls"] == 5 and w["measured"] == 4 and w["interval_contains_truth"] == 3
    assert w["max_abs_error"] == pytest.approx(16.0) and w["mean_abs_error"] == pytest.approx((2 + 16 + 2 + 0) / 4)


def test_the_upper_bound_is_three_over_n_when_nothing_is_wrong_and_used(R):
    assert R.upper_bound_95(0, 10) == pytest.approx(0.3) and R.upper_bound_95(0, 60) == pytest.approx(0.05)
    assert R.upper_bound_95(0, 2) == 1.0                                  # 3 / 2 is capped at 100 percent


def test_the_upper_bound_with_events_is_the_exact_clopper_pearson_value(R):
    assert R.upper_bound_95(1, 10) == pytest.approx(0.3942, abs=1e-3)
    assert R.upper_bound_95(2, 20) == pytest.approx(0.2826, abs=1e-3)
    assert R.upper_bound_95(5, 5) == 1.0 and R.upper_bound_95(0, 0) == 1.0


def test_the_bound_is_over_sites_not_calls(R, world):
    rep, _, _ = run(R, world)
    d = rep["prof1"]["fields"]["lanes_per_direction"]
    assert len(d["sites"]) == 3 and d["calls"] == 6 and d["wrong_and_used_sites"] == ["A"]
    assert d["upper95"] == pytest.approx(R.upper_bound_95(1, 3))
    clean = rep["prof1"]["fields"]["oneway"]
    assert clean["wrong_and_used_sites"] == [] and clean["upper95"] == pytest.approx(3 / len(clean["sites"]))


# ---------------------------------------------------------------- inputs and output
def test_truth_csv_errors_are_clear(R, tmp_path):
    p = tmp_path / "bad.csv"
    write_csv(p, [{"site_id": "A", "lanes_per_direction": "two"}], R.COLUMNS)
    with pytest.raises(R.TruthError, match="lanes_per_direction"): R.read_truth(str(p))
    write_csv(p, [{"site_id": "A", "oneway": "maybe"}], R.COLUMNS)
    with pytest.raises(R.TruthError, match="oneway"): R.read_truth(str(p))
    write_csv(p, [{"site_id": "A"}, {"site_id": "A"}], R.COLUMNS)
    with pytest.raises(R.TruthError, match="twice"): R.read_truth(str(p))
    write_csv(p, [{"site_id": "A"}], ["site_id", "oneway"])
    with pytest.raises(R.TruthError, match="lacks columns"): R.read_truth(str(p))


def test_the_report_text_has_the_asked_for_content(R, world):
    rep, truth, sec = run(R, world)
    text = R.render(rep, truth, sec)
    for s in ("## prof1", "sites scored", "wrong and used", "95% upper bound", "Wrong answers", "said 2 but truth 1", "confidence 0.95", "WRONG AND USED",
              "Repeat stability", "stated interval holds the true width", "interval holds truth"):
        assert s in text, s
    assert "3 / 3" in text and "exact, 1 of 3 sites" in text


def test_with_no_second_source_the_report_says_nothing_safety_critical_is_passed_on(R, world):
    rep, truth, _ = run(R, world, second=False)
    assert "never passed on" in R.render(rep, truth, {})


def test_the_report_is_deterministic_and_the_cli_writes_the_files(R, world, tmp_path, capsys):
    tmp, t, p1, sec = world
    args = ["--results", str(p1), "--truth", str(t), "--second-source", str(sec), "--out", str(tmp / "o1.md"), "--json", str(tmp / "o1.json")]
    assert R.main(args) == 0; first = capsys.readouterr().out
    args2 = ["--results", str(p1), "--truth", str(t), "--second-source", str(sec), "--out", str(tmp / "o2.md"), "--json", str(tmp / "o2.json")]
    assert R.main(args2) == 0; assert capsys.readouterr().out == first
    assert open(tmp / "o1.md", encoding="utf-8").read() == open(tmp / "o2.md", encoding="utf-8").read()
    assert open(tmp / "o1.json", encoding="utf-8").read() == open(tmp / "o2.json", encoding="utf-8").read()


def test_two_profiles_are_reported_separately(R, world):
    tmp, t, p1, sec = world
    p2 = tmp / "results" / "prof2"
    write_results(p2, "A", [({"lanes_per_direction": (1, 0.9)}, 24)]); write_results(p2, "B", [({"lanes_per_direction": (2, 0.9)}, 48)])
    truth = R.read_truth(str(t)); by = {"prof1": R.read_results(str(p1)), "prof2": R.read_results(str(p2))}
    rep = R.score(truth, by, R.read_second(str(sec)))
    assert list(rep) == ["prof1", "prof2"] and rep["prof2"]["fields"]["lanes_per_direction"]["calls"] == 2


def test_a_result_for_a_site_without_truth_is_skipped(R, world):
    tmp, t, p1, sec = world
    write_results(p1, "Z", [({}, None)])
    rep = R.score(R.read_truth(str(t)), {"prof1": R.read_results(str(p1))})
    assert "Z" not in rep["prof1"]["fields"]["lanes_per_direction"]["sites"] and rep["prof1"]["fields"]["lanes_per_direction"]["calls"] == 6


def test_a_truth_site_without_results_is_named(R, world, capsys):
    tmp, t, p1, sec = world
    empty = tmp / "empty"; os.makedirs(empty)
    assert R.main(["--results", str(empty), "--truth", str(t)]) == 0
    assert "Truth sites with no result in any folder: A, B, C" in capsys.readouterr().out


def test_missing_folder_or_bad_truth_gives_exit_2(R, world, tmp_path, capsys):
    tmp, t, p1, sec = world
    assert R.main(["--results", str(tmp / "nope"), "--truth", str(t)]) == 2
    bad = tmp / "bad.csv"; bad.write_text("site_id\nA\n", encoding="utf-8")
    assert R.main(["--results", str(p1), "--truth", str(bad)]) == 2


def test_it_reads_the_real_nine_saved_files_format(R, tmp_path):
    """The files the owner's script writes (call1.json ... call9.json) are readable: built from the spike responses with the same keys."""
    d = tmp_path / "gpt-x"; os.makedirs(d)
    resp = json.load(open(os.path.join(ROOT, "tests", "fixtures", "site", "spike", "raw", "granite_B_r1.response.json"), encoding="utf-8"))
    text = next(b["text"] for b in resp["content"] if b.get("type") == "text")
    json.dump({"call": 1, "site": "granite", "rep": 1, "profile": "gpt-x", "image": {"sent_px": [1280, 1280], "mpp_sent": 0.448139, "resize_scale": 1.0},
               "raw_response": text}, open(d / "call1.json", "w", encoding="utf-8"))
    t = tmp_path / "t.csv"; write_csv(t, [{"site_id": "granite", "lanes_per_direction": 2, "road_width_ft": 24, "truth_source": "x"}], R.COLUMNS)
    rep = R.score(R.read_truth(str(t)), {"gpt-x": R.read_results(str(d))})
    assert rep["gpt-x"]["fields"]["lanes_per_direction"]["calls"] == 1 and rep["gpt-x"]["width"]["calls"] == 1


# ---------------------------------------------------------------- ta_situation column (owner addendum 2026-10-31)
def test_the_optional_ta_situation_column_is_read_and_summarised_per_situation(R, world):
    tmp, _, p1, sec = world
    rows = [{**r, "ta_situation": "flagging" if r["site_id"] != "B" else "lane closure"} for r in TRUTH]
    t2 = tmp / "truth2.csv"; write_csv(t2, rows, R.COLUMNS + ("ta_situation",))
    truth = R.read_truth(str(t2))
    assert {k: v["ta_situation"] for k, v in truth.items()} == {"A": "flagging", "B": "lane closure", "C": "flagging"}
    rep = R.score(truth, {"prof1": R.read_results(str(p1))}, R.read_second(str(sec)))
    by = rep["prof1"]["by_ta_situation"]
    assert set(by) == {"flagging", "lane closure"} and by["flagging"]["sites"] == ["A", "C"] and by["lane closure"]["sites"] == ["B"]
    assert by["flagging"]["wrong"] >= 1 and by["lane closure"]["wrong"] >= 1
    text = R.render(rep, truth, R.read_second(str(sec)))
    assert "by ta_situation" in text and "| flagging | A, C |" in text


def test_a_truth_csv_without_the_column_still_works_and_shows_no_situation_table(R, world):
    rep, truth, second = run(R, world)
    assert set(rep["prof1"]["by_ta_situation"]) == {"(none)"}
    assert "by ta_situation" not in R.render(rep, truth, second)
