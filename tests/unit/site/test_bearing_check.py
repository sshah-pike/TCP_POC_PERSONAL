"""Bearing cross-check and the 'which road?' question (S6 commit 4), tested with the real E Second St and Colorado marks."""
import json
import math
import os

import pytest

from tcp_planner.data_sources.osm import OsmWay
from tcp_planner.site_model import bearing_check as BC
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Mark, SiteFact
from tcp_planner.site_model.site_config import load_site_config, setting

FX = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "site", "bearing", "marks_nine_and_nine.json")
DOC = json.load(open(FX, encoding="utf-8"))


def marks_of(c):
    return tuple(Mark(feature=m["feature"], status=m["status"], points=tuple(tuple(p) for p in m["points"])) for m in c["marks"])


def call(profile, site, rep):
    return next(c for c in DOC["calls"] if c["profile"] == profile and c["site"] == site and c["rep"] == rep)


def road(id_, bearing_deg, name="X Rd", highway="secondary", offset_m=3.0, tags=None):
    """A straight OsmWay through the work point's neighbourhood with the given compass bearing, `offset_m` to its left."""
    b = math.radians(bearing_deg); dx, dy = math.sin(b), math.cos(b)
    ox, oy = -dy * offset_m, dx * offset_m
    return OsmWay(id_, {"highway": highway, "name": name, **(tags or {})}, ((-100 * dx + ox, -100 * dy + oy), (100 * dx + ox, 100 * dy + oy)))


# ---------------------------------------------------------------- the nine gpt calls on the two Massachusetts sites
SECOND = DOC["standin_way_bearing_deg"]["second"]
COLORADO = DOC["standin_way_bearing_deg"]["colorado"]


@pytest.mark.parametrize("rep,agrees", [(1, False), (2, True), (3, True)])
def test_the_three_e_second_st_marks_of_gpt(rep, agrees):
    """Call 4 (rep 1) read the road at 0 degrees: east-west E Second St cannot run north-south."""
    chk = BC.check_bearing(marks_of(call("gpt-5.6-sol", "second", rep)), [road(1, SECOND, "East Second Street")])
    assert (chk.status == BC.AGREE) is agrees
    if not agrees:
        assert chk.status == BC.MISMATCH and chk.mark_bearing < 5 and chk.diff_deg > 80 and not chk.widths_ok
        assert chk.questions[0].kind == "BEARING_MISMATCH" and chk.questions[0].osm_way_id == 1 and chk.questions[0].field == "road"


@pytest.mark.parametrize("rep,agrees", [(1, True), (2, False), (3, True)])
def test_the_three_colorado_marks_of_gpt(rep, agrees):
    """Call 8 (rep 2) read the road at 140 degrees; the other two give 28 and 41 degrees, within 30 degrees of 37."""
    chk = BC.check_bearing(marks_of(call("gpt-5.6-sol", "colorado", rep)), [road(1, COLORADO, "Colorado Ave")])
    assert (chk.status == BC.AGREE) is agrees
    if not agrees: assert chk.status == BC.MISMATCH and 130 < chk.mark_bearing < 150 and chk.widths_ok is False


def test_the_claude_marks_agree_on_both_sites():
    for site, bearing in (("second", SECOND), ("colorado", COLORADO)):
        for rep in (1, 2, 3):
            chk = BC.check_bearing(marks_of(call("claude-opus-5-5", site, rep)), [road(1, bearing)])
            assert chk.status == BC.AGREE and chk.diff_deg <= 10 and chk.widths_ok


def test_a_mismatch_makes_every_width_unknown_and_keeps_other_facts():
    chk = BC.check_bearing(marks_of(call("gpt-5.6-sol", "second", 1)), [road(1, SECOND)])
    widths = SiteFact(field="lane_width_ft", registry_id="lane_width_ft", unit="ft", source="AI_MARKS", outcome="FOUND", value=11.2)
    near = SiteFact(field="distance_from_edge_ft", registry_id="distance_from_edge_ft", unit="ft", source="CODE", outcome="FOUND", value=4.0)
    other = SiteFact(field="lanes_per_direction", registry_id="lanes_per_direction", source="AI", outcome="FOUND", value=1)
    out = BC.block_widths([widths, near, other], chk)
    assert [f.outcome for f in out] == ["UNKNOWN", "UNKNOWN", "FOUND"] and out[0].reason_code == "check_failed" and out[0].value is None
    assert "BEARING" not in out[2].evidence and "MISMATCH" in out[0].evidence and "CALIBRATION_PENDING" in out[0].flags
    ok = BC.check_bearing(marks_of(call("gpt-5.6-sol", "second", 2)), [road(1, SECOND)])
    assert BC.block_widths([widths], ok)[0].outcome == "FOUND"


# ---------------------------------------------------------------- tolerance, modulo 180
def straight_marks(bearing_deg):
    b = math.radians(bearing_deg); dx, dy = math.sin(b), -math.cos(b)          # image y runs down
    px, py = -dy, dx
    def line(off): return tuple((640 + t * dx + off * px, 640 + t * dy + off * py) for t in (-300, -100, 100, 300))
    return (Mark(feature="road_edge_left", status="RESOLVED", points=line(-20)), Mark(feature="road_edge_right", status="RESOLVED", points=line(20)))


def test_the_bearing_of_straight_marks_is_read_in_every_direction():
    for b in (0, 10, 45, 90, 135, 170):
        got, how = BC.mark_bearing(straight_marks(b))
        assert how == "edges" and min(abs(got - b), 180 - abs(got - b)) < 1.0, (b, got)


def test_a_road_drawn_the_other_way_still_agrees_modulo_180():
    assert BC.check_bearing(straight_marks(10), [road(1, 190)]).status == BC.AGREE
    assert BC.check_bearing(straight_marks(175), [road(1, 5)]).status == BC.AGREE        # across the 0/180 wrap


def test_the_tolerance_is_30_degrees_from_config_and_calibration_pending():
    cfg = load_site_config()
    assert setting("bearing", "tolerance_deg", cfg) == (30, ("CALIBRATION_PENDING",))
    assert BC.check_bearing(straight_marks(0), [road(1, 29)]).status == BC.AGREE
    assert BC.check_bearing(straight_marks(0), [road(1, 31)]).status == BC.MISMATCH
    assert BC.check_bearing(straight_marks(0), [road(1, 31)]).flags == ("CALIBRATION_PENDING",)
    cfg["bearing"]["tolerance_deg"]["value"] = 45
    assert BC.check_bearing(straight_marks(0), [road(1, 31)], cfg=cfg).status == BC.AGREE


def test_lane_lines_give_the_bearing_when_the_edges_do_not():
    lines = tuple(Mark(feature="lane_line", status="RESOLVED", points=((100 + i * 40, 900), (100 + i * 40 + 300, 100))) for i in range(2))
    got, how = BC.mark_bearing(lines)
    assert how == "lane_lines" and 20 < got < 25


def test_no_marks_gives_no_bearing_and_no_mismatch():
    chk = BC.check_bearing((), [road(1, 90)])
    assert chk.status == BC.NO_MARKS and chk.widths_ok and chk.way_bearing == 90.0


def test_no_road_near_gives_no_comparison():
    far = road(1, 90, offset_m=80.0)
    chk = BC.check_bearing(straight_marks(90), [far])
    assert chk.status == BC.NO_ROAD and chk.widths_ok and chk.way_id is None
    assert BC.check_bearing(straight_marks(90), []).status == BC.NO_ROAD


# ---------------------------------------------------------------- which road?
def test_roads_that_differ_by_more_than_the_tolerance_raise_a_which_road_question_when_the_marks_do_not_decide():
    a, b = road(1, 90, "Main St", offset_m=3), road(2, 0, "Side St", offset_m=4)
    q = BC.check_bearing((), [a, b])
    assert q.status == BC.WHICH_ROAD and q.questions[0].kind == "WHICH_ROAD" and not q.widths_ok
    assert {w["id"] for w in q.questions[0].context["ways"]} == {1, 2} and len(q.questions[0].options) == 2
    assert q.questions[0].field == "road"


def test_the_marks_choose_when_exactly_one_candidate_matches():
    a, b = road(1, 90, "Main St"), road(2, 0, "Side St", offset_m=4)
    chk = BC.check_bearing(straight_marks(85), [a, b])
    assert chk.status == BC.AGREE and chk.way_id == 1 and chk.questions == ()
    chk2 = BC.check_bearing(straight_marks(10), [a, b])
    assert chk2.status == BC.AGREE and chk2.way_id == 2


def test_marks_that_match_neither_candidate_ask_which_road():
    a, b = road(1, 90, "Main St"), road(2, 0, "Side St", offset_m=4)
    chk = BC.check_bearing(straight_marks(45), [a, b])
    assert chk.status == BC.WHICH_ROAD and chk.questions[0].kind == "WHICH_ROAD" and chk.widths_ok is False


def test_roads_that_differ_by_less_than_the_tolerance_are_one_road():
    a, b = road(1, 90, "Main St"), road(2, 100, "Main St", offset_m=6)
    chk = BC.check_bearing(straight_marks(92), [a, b])
    assert chk.status == BC.AGREE and chk.way_id == 1 and chk.questions == ()


def test_a_service_way_is_never_a_candidate_for_which_road():
    main, drive = road(1, 90, "Main St"), road(2, 0, "Driveway", highway="service", offset_m=1)
    chk = BC.check_bearing(straight_marks(88), [main, drive])
    assert chk.status == BC.AGREE and chk.way_id == 1


def test_which_road_candidates_beyond_the_configured_distance_do_not_count():
    a, b = road(1, 90, "Main St", offset_m=3), road(2, 0, "Far St", offset_m=24)
    cfg = load_site_config(); cfg["bearing"]["which_road_distance_m"]["value"] = 10
    chk = BC.check_bearing(straight_marks(88), [a, b], cfg=cfg)
    assert chk.status == BC.AGREE and chk.way_id == 1


def test_the_tolerance_and_distance_are_read_from_config_by_name_not_typed():
    src = open(BC.__file__, encoding="utf-8").read()
    assert 'setting("bearing", "tolerance_deg"' in src and 'setting("bearing", "which_road_distance_m"' in src
    assert "tol = 30" not in src and "> 30" not in src and "<= 30" not in src
