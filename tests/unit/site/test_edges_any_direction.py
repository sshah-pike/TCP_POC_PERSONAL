"""Edge marks for a road in any direction (S6 STOP 1, point 1). Marks only: no model call, no image.

The prompt says left/right "facing north"; the code ignores those two names for geometry. These tests use synthetic roads
running north-south, east-west and at angles, and the real marks of the spike's east-west (E Second St) and diagonal
(Colorado) sites, to show that width, axis and compass sides come out right whatever the road direction or the labels.
"""
import glob, json, math, os

import pytest

from tcp_planner.ai.call1 import parse_call1
from tcp_planner.site_model.measure import EdgeFailure, EdgePair, edge_pair

RAW = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "site", "spike", "raw")


def road(angle_deg, width, length=400.0, cx=640.0, cy=640.0, n=4):
    """Two edge polylines of a straight road of the given width (pixels) whose axis has the compass bearing angle_deg."""
    b = math.radians(angle_deg)
    u = (math.sin(b), -math.cos(b))                    # along the road (image coordinates, north is -y)
    v = (-u[1], u[0])
    mk = lambda off: [(cx + u[0] * (-length / 2 + length * k / (n - 1)) + v[0] * off,
                       cy + u[1] * (-length / 2 + length * k / (n - 1)) + v[1] * off) for k in range(n)]
    return mk(-width / 2), mk(width / 2)


@pytest.mark.parametrize("angle", [0, 15, 30, 45, 60, 90, 120, 135, 150, 179])
@pytest.mark.parametrize("width", [18.0, 30.0])
def test_width_and_axis_for_any_direction(angle, width):
    a, b = road(angle, width)
    r = edge_pair(a, b)
    assert isinstance(r, EdgePair)
    assert r.width_px == pytest.approx(width, abs=1e-6) and r.spread_px == pytest.approx(0, abs=1e-6)
    d = abs(r.axis_bearing_deg - angle); assert min(d, 180 - d) == pytest.approx(0, abs=1e-6)


def test_labels_and_point_order_do_not_matter():
    a, b = road(90, 20)
    r1, r2, r3 = edge_pair(a, b), edge_pair(b, a), edge_pair(a[::-1], b[::-1])
    assert r1.width_px == pytest.approx(r2.width_px) == pytest.approx(r3.width_px)
    assert (r1.side_a, r1.side_b) == (r2.side_b, r2.side_a)


def test_synthetic_east_west_road_north_edge_and_south_edge():
    north = [(100.0, 600.0), (400.0, 600.0), (900.0, 600.0)]
    south = [(100.0, 620.0), (400.0, 620.0), (900.0, 620.0)]
    for left, right in ((north, south), (south, north)):           # either labelling, same geometry
        r = edge_pair(left, right)
        assert r.width_px == pytest.approx(20.0) and r.axis_bearing_deg == pytest.approx(90.0)
        assert {r.side_a, r.side_b} == {"N", "S"}
    r = edge_pair(north, south); assert (r.side_a, r.side_b) == ("N", "S")


def test_synthetic_north_south_road():
    west = [(600.0, 100.0), (600.0, 900.0)]; east = [(625.0, 100.0), (625.0, 900.0)]
    r = edge_pair(east, west)
    assert r.width_px == pytest.approx(25.0) and r.axis_bearing_deg == pytest.approx(0.0, abs=1e-6)
    assert (r.side_a, r.side_b) == ("E", "W")


def test_diagonal_road_sides_are_diagonal_compass_points():
    a, b = road(45, 20)                                              # runs north-east; edges lie NW and SE of the centre
    r = edge_pair(a, b)
    assert {r.side_a, r.side_b} == {"NW", "SE"} and r.width_px == pytest.approx(20.0)


def test_edges_that_do_not_overlap_along_the_road_fail():
    a = [(100.0, 600.0), (200.0, 600.0)]; b = [(500.0, 620.0), (700.0, 620.0)]
    assert edge_pair(a, b) == EdgeFailure("no_overlap")


def test_too_few_points_and_degenerate_marks_fail():
    assert edge_pair([(1.0, 1.0)], [(2.0, 2.0), (3.0, 3.0)]) == EdgeFailure("too_few_points")
    assert edge_pair([(5.0, 5.0), (5.0, 5.0)], [(5.0, 5.0), (5.0, 5.0)]) == EdgeFailure("no_axis")
    assert edge_pair([(5.0, 1.0), (5.0, 1.0)], [(9.0, 4.0), (9.0, 4.0)]) == EdgeFailure("too_few_points")


def test_a_tapering_pair_gives_a_spread():
    a = [(0.0, 0.0), (400.0, 0.0)]; b = [(0.0, 20.0), (400.0, 28.0)]
    r = edge_pair(a, b)
    assert r.width_px == pytest.approx(24.0, abs=0.05) and r.spread_px == pytest.approx(8.0, abs=0.05)   # across the principal axis


def _edges(path, size=(1280, 1280)):
    d = json.load(open(path, encoding="utf-8")); text = next(b["text"] for b in d["content"] if b.get("type") == "text")
    m = {x.feature: x for x in parse_call1(text, size).marks if x.status == "RESOLVED" and x.feature.startswith("road_edge")}
    return m["road_edge_left"].points, m["road_edge_right"].points


@pytest.mark.parametrize("r", [1, 2, 3])
def test_real_east_west_marks_e_second_st(r):
    """E Second St: the model's own 'left' and 'right' are the north and south edges; the code reads them as an unordered pair."""
    left, right = _edges(os.path.join(RAW, f"second_B_r{r}.response.json"))
    res = edge_pair(left, right)
    assert isinstance(res, EdgePair) and abs(res.axis_bearing_deg - 90) < 2 and {res.side_a, res.side_b} == {"N", "S"}
    assert 15 < res.width_px < 25                                       # about 20 px, from the model's marks (pixels only)
    assert edge_pair(right, left).width_px == pytest.approx(res.width_px)


@pytest.mark.parametrize("r", [1, 2, 3])
def test_real_diagonal_marks_colorado(r):
    left, right = _edges(os.path.join(RAW, f"colorado_B_r{r}.response.json"))
    res = edge_pair(left, right)
    assert isinstance(res, EdgePair) and (20 < res.axis_bearing_deg < 60 or 120 < res.axis_bearing_deg < 160)
    assert {res.side_a, res.side_b} <= {"NE", "SW", "NW", "SE"}
