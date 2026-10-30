"""Lane width gate and the AI-mark error evidence (S6 STOP 2, points 2 and 3). Marks only; no model call."""
import glob, json, math, os, statistics

import pytest

from tcp_planner.ai.call1 import FIELDS, parse_call1, to_site_facts
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Mark, rule_inputs
from tcp_planner.site_model.site_config import load_site_config, measurement_setting

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SPIKE = os.path.join(ROOT, "tests", "fixtures", "site", "spike")
PX_IS_FT = 0.3048
CLEAN = {"parking_present": False, "shoulder_present": False}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def mark(feature, pts): return Mark(feature=feature, points=tuple(pts), status="RESOLVED")


def lines_at(offsets, length=300.0, cx=500.0, cy=500.0):
    """Horizontal (east-west) polylines at the given offsets (pixels) from the centre."""
    return [[(cx - length / 2, cy + o), (cx, cy + o), (cx + length / 2, cy + o)] for o in offsets]


def edges(width): a, b = lines_at([-width / 2, width / 2]); return [mark("road_edge_left", a), mark("road_edge_right", b)]


def lane(res): return next(f for f in res.facts if f.field == "lane_width_ft")


def spike(site, r):
    d = json.load(open(os.path.join(SPIKE, "raw", f"{site}_B_r{r}.response.json"), encoding="utf-8"))
    text = next(b["text"] for b in d["content"] if b.get("type") == "text")
    mpp = json.load(open(os.path.join(SPIKE, "inputs", site + ".json"), encoding="utf-8"))["metres_per_pixel"]
    return parse_call1(text, (1280, 1280)), mpp


# ---------------------------------------------------------------- point 2: the 3.0 px entry and its evidence
def test_config_has_a_separate_3px_ai_mark_entry_and_keeps_1px_for_the_cross_section():
    cfg = load_site_config()["measurement"]
    assert measurement_setting("edge_pixel_error_px_ai_marks") == (3.0, ("CALIBRATION_PENDING",))
    assert measurement_setting("edge_pixel_error_px_cross_section") == (1.0, ("CALIBRATION_PENDING",))
    note = cfg["edge_pixel_error_px_ai_marks"]["note"]
    assert "nine recorded spike widths" in note and "NOT calibrated" in note and "gpt-5.6-sol has not run" in note


def _nine_widths():
    out = {}
    for site in ("granite", "second", "colorado"):
        for r in (1, 2, 3):
            res, mpp = spike(site, r)
            tw, _ = L.traveled_way_width(res.marks, mpp)
            out.setdefault(site, []).append((tw.value_ft, mpp))
    return out


def _inside(err_px):
    """Per site: does each repetition's width lie inside the band (err_px x 2 edges at the spike scale) around the site's median?"""
    flags = []
    for ws in _nine_widths().values():
        med = statistics.median(w for w, _ in ws)
        for w, mpp in ws: flags.append(abs(w - med) <= L.px_to_ft(2 * err_px, mpp))
    return flags


def test_ai_mark_error_evidence():
    """Records why 3.0 px: at the spike scale all nine widths fall inside the band around their site's median at 3.0 px, and not
    at 1.0 or 2.0 px. This is evidence from nine claude-opus-5-5 responses (pre-tuning prompt), not a calibration."""
    assert len(_inside(3.0)) == 9 and all(_inside(3.0))
    assert not all(_inside(2.0)) and not all(_inside(1.0))
    assert sum(_inside(1.0)) < 9 and 3 <= sum(_inside(1.0))


# ---------------------------------------------------------------- point 3: the lane width rules
def test_a_clean_road_divides_the_traveled_way_by_the_lanes(pack):
    f = lane(L.measure_lengths(edges(24), PX_IS_FT, pack, total_lanes=2, gate=CLEAN))
    assert f.status == "RESOLVED" and f.value == pytest.approx(12.0) and f.reason_code is None
    assert f.measured.method == "AI_MARKS" and "AI reading, measurement gate only" in " ".join(f.measured.inputs)


@pytest.mark.parametrize("gate", [{"parking_present": True, "shoulder_present": False},
                                  {"parking_present": False, "shoulder_present": True},
                                  {"parking_present": None, "shoulder_present": False},
                                  {"parking_present": False, "shoulder_present": None}, {}, None])
def test_parking_or_shoulder_or_unknown_gives_unknown_with_a_question(pack, gate):
    res = L.measure_lengths(edges(24), PX_IS_FT, pack, total_lanes=2, gate=gate)
    f = lane(res)
    assert (f.status, f.reason_code, f.value) == ("UNKNOWN", "ambiguous", None)
    assert f.measured is None and [q.kind for q in res.questions] == ["FACT_UNKNOWN"] and res.questions[0].reveals == ("lane_width_ft",)
    assert "parking" in res.questions[0].reason and "shoulder" in res.questions[0].reason


def test_e_second_st_marks_with_parking_inside_the_edges_give_unknown(pack):
    """Real marks, parking_present true (the spike's own reading): 29 ft over 2 lanes would be 14.5 ft, which is not a lane."""
    res, mpp = spike("second", 1)
    gate = L.gate_from(res.observations)
    assert gate["parking_present"] is True
    m = L.measure_lengths(res.marks, mpp, pack, total_lanes=2, gate=gate)
    f = lane(m)
    assert (f.status, f.reason_code) == ("UNKNOWN", "ambiguous")
    assert [q.reveals for q in m.questions if q.kind == "FACT_UNKNOWN"] == [("lane_width_ft",)]
    assert m.measured["traveled_way_width"].value_ft == pytest.approx(29.0, abs=0.5)         # the road width itself is still known


def test_lane_line_spacing_wins_when_two_or_more_lane_lines_exist(pack):
    a, b = edges(40)                                                    # 40 px road
    lines = [mark("lane_line", p) for p in lines_at([-8.0, 4.0])]       # two lane lines 12 px apart
    marks = [a, b] + lines
    for gate in (CLEAN, {"parking_present": True, "shoulder_present": True}, None):    # the gate does not matter
        f = lane(L.measure_lengths(marks, PX_IS_FT, pack, total_lanes=2, gate=gate))
        assert f.status == "RESOLVED" and f.value == pytest.approx(12.0)
        assert "2 lane line marks" in f.measured.inputs and "lane_line" not in f.measured.calculation.replace("lane lines", "")


def test_lane_line_spacing_is_the_median_gap_of_several_lines(pack):
    marks = edges(60) + [mark("lane_line", p) for p in lines_at([-18.0, -6.0, 6.0, 20.0])]    # gaps 12, 12, 14
    f = lane(L.measure_lengths(marks, PX_IS_FT, pack))
    assert f.value == pytest.approx(12.0)


def test_lane_line_spacing_works_on_a_north_south_road(pack):
    pts = lambda x: [(x, 350.0), (x, 500.0), (x, 650.0)]
    marks = [mark("lane_line", pts(488.0)), mark("lane_line", pts(500.0))]
    assert lane(L.measure_lengths(marks, PX_IS_FT, pack)).value == pytest.approx(12.0)


def test_implausible_lane_line_spacing_is_not_accepted(pack):
    marks = [mark("lane_line", p) for p in lines_at([-40.0, 40.0])]     # 80 ft between two lines
    res = L.measure_lengths(marks, PX_IS_FT, pack)
    assert (lane(res).status, lane(res).reason_code) == ("UNKNOWN", "ambiguous") and res.questions


def test_a_single_lane_line_is_not_enough(pack):
    marks = edges(24) + [mark("lane_line", lines_at([0.0])[0])]
    f = lane(L.measure_lengths(marks, PX_IS_FT, pack, total_lanes=2, gate={"parking_present": True, "shoulder_present": False}))
    assert f.status == "UNKNOWN"                                         # falls through to the gate, which fails here


def test_a_clean_road_without_a_lane_count_is_unknown_with_a_question(pack):
    res = L.measure_lengths(edges(24), PX_IS_FT, pack, gate=CLEAN)
    assert (lane(res).reason_code, len(res.questions)) == ("missing", 1)


# ---------------------------------------------------------------- the gate readings never reach rule_inputs
def test_gate_from_returns_plain_values_only():
    res, _ = spike("second", 1)
    g = L.gate_from(res.observations)
    assert set(g) == {"parking_present", "shoulder_present"} and all(v is None or isinstance(v, bool) for v in g.values())


def test_the_gate_readings_never_reach_rule_inputs(pack):
    res, mpp = spike("second", 1)
    facts, _ = to_site_facts(res)
    m = L.measure_lengths(res.marks, mpp, pack, total_lanes=2, gate=L.gate_from(res.observations))
    names = {f.field for f in m.facts}
    assert "parking_present" not in names and "shoulder_present" not in names     # measurement makes no fact from them
    inputs = rule_inputs([*facts, *m.facts])
    assert "parking_present" not in inputs and "shoulder_present" not in inputs
    assert next(f for f in facts if f.field == "parking_present").flags and "CONTEXT_ONLY" in next(f for f in facts if f.field == "parking_present").flags
    assert "NEEDS_SECOND_SOURCE" in next(f for f in facts if f.field == "shoulder_present").flags or \
        next(f for f in facts if f.field == "shoulder_present").status == "UNKNOWN"


def test_the_measurement_module_does_not_import_the_rule_input_reader():
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "src", "tcp_planner", "site_model", "lengths.py"), encoding="utf-8").read())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not ({"rule_inputs", "RuleInputs"} & imported)


# ---------------------------------------------------------------- what the nine spike responses give now
EXPECTED_NINE = {   # (site, repetition): (lane_width_ft status before STOP 2 point 3, after)
    ("granite", 1): ("UNKNOWN", "UNKNOWN"), ("granite", 2): ("RESOLVED", "UNKNOWN"), ("granite", 3): ("UNKNOWN", "UNKNOWN"),
    ("second", 1): ("RESOLVED", "UNKNOWN"), ("second", 2): ("RESOLVED", "UNKNOWN"), ("second", 3): ("RESOLVED", "UNKNOWN"),
    ("colorado", 1): ("RESOLVED", "UNKNOWN"), ("colorado", 2): ("UNKNOWN", "UNKNOWN"), ("colorado", 3): ("RESOLVED", "UNKNOWN"),
}


@pytest.mark.parametrize("site,r", list(EXPECTED_NINE))
def test_the_nine_spike_responses_after_the_gate(pack, site, r):
    res, mpp = spike(site, r); o = res.observations
    lanes = o["lanes_per_direction"]
    total = None if lanes.status != "RESOLVED" else (lanes.value if o["oneway"].value else 2 * lanes.value)   # stand-in for the fused lane facts
    after = lane(L.measure_lengths(res.marks, mpp, pack, total_lanes=total, gate=L.gate_from(o))).status
    before = lane(L.measure_lengths(res.marks, mpp, pack, total_lanes=total, gate=CLEAN)).status     # the rule without the parking/shoulder check
    assert (before, after) == EXPECTED_NINE[(site, r)]
