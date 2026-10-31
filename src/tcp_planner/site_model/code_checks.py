"""Code checks on the image (S6 step 9, owner plan 2026-10-31): lane-line detection, shadow and canopy share, image-to-OSM offset.

Rules for every check here (STOP 6 conditions 1 and 2):
  - it returns EVIDENCE (numbers and a sentence), and its effect can only LOWER trust or give UNKNOWN, never raise confidence;
  - it is never a second source for a safety-critical field;
  - the model's own shadow_share and canopy_share are a cross-check CANDIDATE only: `compare_model_shares` records a difference as
    evidence, and no effect function takes the model's numbers as an input, so they cannot raise or lower anything on their own.
All numbers are config values (code_checks section, CALIBRATION_PENDING). Pixel geometry only; no length is read from the AI (D-64).
"""
import io
import math
from typing import NamedTuple, Optional

import numpy as np
from PIL import Image

from tcp_planner.data_sources.osm import point_to_polyline
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.measure import EdgeFailure, _axis, _profile, _s_at, edge_pair
from tcp_planner.site_model.site_config import load_site_config, setting


class CheckResult(NamedTuple):
    name: str
    ran: bool                       # False: the check could not run (no edge pair, no lines) and changes nothing
    ok: Optional[bool]              # True: no objection; False: the check objects; None: did not run
    evidence: str
    data: dict
    flags: tuple                    # CALIBRATION_PENDING while the values are not calibrated


def _rgb(image_bytes):
    return np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB"), dtype=np.float64)


def strip_geometry(marks, stations):
    """(u, v, [(t, s_a, s_b), ...]) for the road strip between the two edge marks, or None: u the road axis, v across it, each station a
    position t along the axis with the edge positions s_a and s_b across it (a pixel is t*u + s*v). Needs exactly one usable mark per edge."""
    a, b = L.usable(marks, "road_edge_left"), L.usable(marks, "road_edge_right")
    if len(a) != 1 or len(b) != 1: return None
    pair = edge_pair(a[0].points, b[0].points)
    if isinstance(pair, EdgeFailure): return None
    u = _axis(list(a[0].points) + list(b[0].points))
    if u is None: return None
    v = (-u[1], u[0])
    pa, pb = _profile(a[0].points, u, v), _profile(b[0].points, u, v)
    lo, hi = max(pa[0][0], pb[0][0]), min(pa[-1][0], pb[-1][0])
    if hi - lo <= 0: return None
    st = [lo + (hi - lo) * k / (stations - 1) for k in range(stations)]
    return u, v, [(t, _s_at(pa, t), _s_at(pb, t)) for t in st]


def _px(arr, u, v, t, s):
    x, y = int(round(t * u[0] + s * v[0])), int(round(t * u[1] + s * v[1]))
    h, w = arr.shape[:2]
    return (x, y) if 0 <= x < w and 0 <= y < h else None


# ---------------------------------------------------------------- lane lines
def _line_peaks(lum, rgb_row, cfg):
    """Lateral positions (index in the cross-section) of narrow bright runs: painted lines. White or yellow (R and G high) both count."""
    contrast = setting("code_checks", "lane_line_min_contrast", cfg)[0]; max_w = setting("code_checks", "lane_line_max_width_px", cfg)[0]
    base = np.median(lum)
    bright = lum > base + contrast
    peaks, i, n = [], 0, len(lum)
    while i < n:
        if bright[i]:
            j = i
            while j + 1 < n and bright[j + 1]: j += 1
            if j - i + 1 <= max_w: peaks.append((i + j) / 2.0)
            i = j + 1
        else: i += 1
    return peaks


def lane_lines(image_bytes, marks, cfg=None):
    """CheckResult with data {"interior_lines": n, "implied_total_lanes": n+1, ...}. Painted lines are found in the strip between the road
    edges: narrow bright runs seen at the same lateral position in at least `lane_line_min_station_fraction` of the stations; two closer
    than `lane_line_merge_px` (a double yellow) count as one; runs within `lane_line_edge_margin_px` of an edge are edge lines and do not
    count. When fewer than `min_lines_to_judge` interior lines are found the check did not judge anything (ran False, ok None)."""
    cfg = cfg or load_site_config()
    flags = setting("code_checks", "stations", cfg)[1]
    geo = strip_geometry(marks, int(setting("code_checks", "stations", cfg)[0]))
    if geo is None: return CheckResult("lane_lines", False, None, "no usable pair of edge marks", {}, flags)
    arr = _rgb(image_bytes); lum = arr @ np.array([0.299, 0.587, 0.114])
    u, v, stations = geo
    margin = setting("code_checks", "lane_line_edge_margin_px", cfg)[0]; tol = setting("code_checks", "lane_line_position_tolerance_px", cfg)[0]
    merge = setting("code_checks", "lane_line_merge_px", cfg)[0]; need = setting("code_checks", "lane_line_min_station_fraction", cfg)[0]
    found = []                                      # per station: lateral positions measured from edge a, in pixels
    for t, sa, sb in stations:
        lo, hi = (sa, sb) if sa <= sb else (sb, sa)
        samples = [_px(lum, u, v, t, s) for s in np.arange(lo, hi + 0.5, 1.0)]
        if any(p is None for p in samples) or len(samples) < setting("code_checks", "min_cross_section_px", cfg)[0]: continue
        cross = np.array([lum[y, x] for x, y in samples])
        pos = [p for p in _line_peaks(cross, None, cfg) if margin <= p <= len(cross) - 1 - margin]
        found.append(pos)
    if not found: return CheckResult("lane_lines", False, None, "the road strip lies outside the image", {}, flags)
    # cluster lateral positions across stations
    allp = sorted(p for ps in found for p in ps)
    clusters = []
    for p in allp:
        if clusters and p - clusters[-1][-1] <= tol: clusters[-1].append(p)
        else: clusters.append([p])
    lines = []
    for c in clusters:
        centre = sum(c) / len(c)
        seen = sum(any(abs(p - centre) <= tol for p in ps) for ps in found)
        if seen / len(found) >= need: lines.append(centre)
    merged = []
    for c in sorted(lines):
        if merged and c - merged[-1] < merge: merged[-1] = (merged[-1] + c) / 2
        else: merged.append(c)
    n = len(merged)
    need_lines = setting("code_checks", "min_lines_to_judge", cfg)[0]
    data = {"interior_lines": n, "implied_total_lanes": n + 1, "stations_used": len(found)}
    if n < need_lines:
        return CheckResult("lane_lines", False, None, f"{n} painted interior line(s) detected: nothing to judge", data, flags)
    return CheckResult("lane_lines", True, True, f"{n} painted interior line(s) detected; they imply {n + 1} lanes across the road", data, flags)


# ---------------------------------------------------------------- shadow and canopy share
def shares(image_bytes, marks, cfg=None):
    """CheckResult with data {"canopy_share", "shadow_share", "covered_share", "pixels"} computed by code over the road strip between the
    edge marks. Canopy: green exceeds red and blue by `green_margin`. Shadow: a non-canopy pixel darker than `shadow_luminance_ratio` of
    the `reference_percentile` luminance of the non-canopy strip. ok is False when canopy plus shadow exceed `occlusion_share_max`."""
    cfg = cfg or load_site_config()
    flags = setting("code_checks", "occlusion_share_max", cfg)[1]
    geo = strip_geometry(marks, int(setting("code_checks", "stations", cfg)[0]))
    if geo is None: return CheckResult("shadow_canopy", False, None, "no usable pair of edge marks", {}, flags)
    arr = _rgb(image_bytes); u, v, stations = geo
    margin = setting("code_checks", "green_margin", cfg)[0]; ratio = setting("code_checks", "shadow_luminance_ratio", cfg)[0]
    pct = setting("code_checks", "reference_percentile", cfg)[0]; limit = setting("code_checks", "occlusion_share_max", cfg)[0]
    px = []
    for t, sa, sb in stations:
        lo, hi = (sa, sb) if sa <= sb else (sb, sa)
        for s in np.arange(lo, hi + 0.5, 1.0):
            p = _px(arr, u, v, t, s)
            if p is not None: px.append(arr[p[1], p[0]])
    if not px: return CheckResult("shadow_canopy", False, None, "the road strip lies outside the image", {}, flags)
    px = np.array(px); r, g, b = px[:, 0], px[:, 1], px[:, 2]
    canopy = (g - np.maximum(r, b)) >= margin
    lum = px @ np.array([0.299, 0.587, 0.114])
    rest = lum[~canopy]
    shadow = np.zeros(len(px), dtype=bool)
    if len(rest):
        ref = np.percentile(rest, pct)
        shadow = (~canopy) & (lum < ratio * ref)
    c, sh = float(canopy.mean()), float(shadow.mean())
    data = {"canopy_share": round(c, 4), "shadow_share": round(sh, 4), "covered_share": round(c + sh, 4), "pixels": int(len(px))}
    ok = (c + sh) <= limit
    return CheckResult("shadow_canopy", True, ok, f"canopy {c:.0%}, shadow {sh:.0%} of the road strip (limit {limit:.0%} together)", data, flags)


def compare_model_shares(code_result, model_shadow, model_canopy, cfg=None):
    """Evidence only: the model's shares against the code's. Returns a dict for the trace. It is deliberately NOT an input of
    `occlusion_effect`: the model's values may never raise or lower confidence on their own."""
    cfg = cfg or load_site_config()
    tol = setting("code_checks", "model_share_tolerance", cfg)[0]
    if not code_result.ran: return {"compared": False, "reason": "the code did not compute shares"}
    out = {"compared": True, "tolerance": tol}
    for name, model in (("shadow_share", model_shadow), ("canopy_share", model_canopy)):
        code = code_result.data[name]
        out[name] = {"model": model, "code": code, "differs": None if model is None else abs(model - code) > tol}
    return out


OCCLUSION_AFFECTED = ("shoulder_present", "parking_present", "bicycle_lane_present", "sidewalk_present", "sidewalk_side")


def occlusion_effect(facts, code_result):
    """Facts with the edge-based ones made UNKNOWN (occluded) when the code share check objects; widths from marks too. Only the code's
    result is read. Candidates keep the AI value."""
    if code_result.ok is not False: return list(facts)
    from tcp_planner.site_model.facts import Candidate
    out = []
    for f in facts:
        hit = f.field in OCCLUSION_AFFECTED or (f.unit == "ft" and f.source in ("CODE", "AI_MARKS"))
        if not hit or f.outcome == "UNKNOWN":
            out.append(f); continue
        cand = f.candidates + (Candidate(source=f.source, value=f.value, outcome=f.outcome),)
        out.append(f.model_copy(update={"outcome": "UNKNOWN", "value": None, "interval": None, "reason_code": "occluded", "candidates": cand,
                                        "flags": tuple(dict.fromkeys(f.flags + code_result.flags)),
                                        "evidence": f"code check: {code_result.evidence}"}))
    return out


# ---------------------------------------------------------------- image to OSM offset
def osm_offset(marks, image_size, mpp_sent, reference_points, cfg=None):
    """CheckResult: mean distance in metres between the road centre seen in the marks (the middle of the edge pair, at each station) and the
    OSM reference way. The image is north-up with the work point at its centre, so a pixel (x, y) is (x - cx) * mpp metres east and
    (cy - y) * mpp metres north of the work point. ok is False when the offset exceeds `max_osm_offset_m`: OSM cannot confirm an AI value."""
    cfg = cfg or load_site_config()
    limit, flags = setting("code_checks", "max_osm_offset_m", cfg)
    geo = strip_geometry(marks, int(setting("code_checks", "stations", cfg)[0]))
    if geo is None or not reference_points: return CheckResult("osm_offset", False, None, "no edge pair or no reference way", {}, flags)
    u, v, stations = geo; cx, cy = image_size[0] / 2, image_size[1] / 2
    ds = []
    for t, sa, sb in stations:
        s = (sa + sb) / 2
        x, y = t * u[0] + s * v[0], t * u[1] + s * v[1]
        ds.append(point_to_polyline(((x - cx) * mpp_sent, (cy - y) * mpp_sent), reference_points)[0])
    mean = sum(ds) / len(ds)
    return CheckResult("osm_offset", True, mean <= limit, f"road centre seen in the marks is {mean:.1f} m from the OSM way (limit {limit} m)",
                       {"mean_offset_m": round(mean, 2), "max_offset_m": round(max(ds), 2)}, flags)
