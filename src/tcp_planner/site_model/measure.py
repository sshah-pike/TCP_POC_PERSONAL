"""Measurement from marks (S6). Pixel geometry only: no model call, no length from the AI (D-64).

Image coordinates: x to the right, y down; north is -y. Marks are polylines in the pixels of the image as sent.

Edges (S6 STOP 1, point 1): the prompt calls the two pavement edges road_edge_left and road_edge_right "facing north",
which says nothing for a road that runs east-west or at an angle. The code therefore never uses those two names for
geometry. The two marks are an unordered pair; the road axis is found from the points themselves (principal direction), the
width is the distance between the two edges across that axis, and which compass side each edge lies on is computed here.
"""
import math
from typing import NamedTuple, Optional

COMPASS8 = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
MIN_OVERLAP_PX = 1.0       # geometry guard (not a regulatory value): edges must overlap along the axis
STATIONS = 5               # cross-sections taken across the overlap


class EdgePair(NamedTuple):
    axis_bearing_deg: float     # direction of the road, 0 = north, 90 = east, folded to [0, 180)
    width_px: float             # mean distance between the edges across the axis
    spread_px: float            # largest minus smallest width over the stations
    stations: int
    side_a: str                 # compass side of the road on which the FIRST mark lies
    side_b: str                 # ... of the second mark


class EdgeFailure(NamedTuple):
    reason: str                 # too_few_points | no_overlap | no_axis


def _bearing(vx, vy):
    """Compass bearing of an image-plane vector, in degrees from north, clockwise."""
    return math.degrees(math.atan2(vx, -vy)) % 360.0


def _compass(vx, vy):
    return COMPASS8[int(round(_bearing(vx, vy) / (360.0 / len(COMPASS8)))) % len(COMPASS8)]


def _axis(points):
    """Unit vector of the principal direction of the points (largest eigenvector of their covariance)."""
    n = len(points); mx = sum(p[0] for p in points) / n; my = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mx) ** 2 for p in points); syy = sum((p[1] - my) ** 2 for p in points)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
    if sxx + syy == 0: return None
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return math.cos(theta), math.sin(theta)


def _profile(poly, u, v):
    """[(t, s)]: position along the axis and across it, sorted along the axis, one point per distinct t."""
    pts = sorted(((p[0] * u[0] + p[1] * u[1]), (p[0] * v[0] + p[1] * v[1])) for p in poly)
    out = []
    for t, s in pts:
        if out and abs(t - out[-1][0]) < 1e-9: continue
        out.append((t, s))
    return out


def _s_at(profile, t):
    for (t0, s0), (t1, s1) in zip(profile, profile[1:]):
        if t0 <= t <= t1: return s0 + (s1 - s0) * (t - t0) / (t1 - t0)
    return profile[-1][1]


def edge_pair(a, b):
    """EdgePair for two edge polylines (sequences of (x, y)), or EdgeFailure. Label-free: swapping a and b swaps the sides
    and nothing else; the road may run in any direction."""
    if len(a) < 2 or len(b) < 2: return EdgeFailure("too_few_points")
    axis = _axis(list(a) + list(b))
    if axis is None: return EdgeFailure("no_axis")
    u = axis; v = (-u[1], u[0])                      # v: u turned 90 degrees (clockwise on screen, y down)
    pa, pb = _profile(a, u, v), _profile(b, u, v)
    if len(pa) < 2 or len(pb) < 2: return EdgeFailure("too_few_points")
    lo, hi = max(pa[0][0], pb[0][0]), min(pa[-1][0], pb[-1][0])
    if hi - lo < MIN_OVERLAP_PX: return EdgeFailure("no_overlap")
    ts = [lo + (hi - lo) * k / (STATIONS - 1) for k in range(STATIONS)]
    diffs = [_s_at(pb, t) - _s_at(pa, t) for t in ts]       # signed across the axis: b minus a
    widths = [abs(d) for d in diffs]
    mean_signed = sum(diffs) / len(diffs)
    # a lies on the -v side when b is on the +v side
    a_dir = (-v[0], -v[1]) if mean_signed > 0 else v
    b_dir = (-a_dir[0], -a_dir[1])
    return EdgePair(axis_bearing_deg=_bearing(*u) % 180.0, width_px=sum(widths) / len(widths),
                    spread_px=max(widths) - min(widths), stations=len(ts), side_a=_compass(*a_dir), side_b=_compass(*b_dir))
