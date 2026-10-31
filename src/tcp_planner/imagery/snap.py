"""Snapping the AI's marks to the nearest real edge in the image (S6 step 8, owner plan 2026-10-31).

The AI draws roughly and in pixels; code decides where the edge really is (D-64, AI observes and code decides). For each mark of an
edge-like feature (config snapping.features) the polyline is sampled every `sample_step_px`; at each sample the grey profile across the
line is read over +/- `search_radius_px`; the NEAREST real step edge (a local maximum of the grey-level gradient whose step is at
least `min_edge_contrast`) becomes the snapped point. Offsets are median-filtered along the line so one stray edge cannot kink the
mark. A mark with fewer than `min_accepted_fraction` of its samples on an edge, or no edge at all, is REJECTED: it becomes an
UNKNOWN mark (reason no_edge_nearby), never a guessed line. The AI's own points are kept in `original_points`.

Snapping can only move a mark to an edge that exists in the image or reject it; it never invents a mark and never reads a length.
All numbers are config values (CALIBRATION_PENDING).
"""
import io
import math
from typing import NamedTuple

import numpy as np
from PIL import Image

from tcp_planner.site_model.facts import Mark
from tcp_planner.site_model.site_config import load_site_config, setting

REJECTED = "no_edge_nearby"


class SnapResult(NamedTuple):
    marks: tuple
    notes: tuple
    flags: tuple          # CALIBRATION_PENDING while the values are not calibrated


def _gray(image_bytes):
    return np.asarray(Image.open(io.BytesIO(image_bytes)).convert("L"), dtype=np.float64)


def _densify(points, step):
    """Sample points along the polyline every `step` pixels, with the unit direction of the segment each lies on."""
    out = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        if L == 0: continue
        n = max(1, int(round(L / step)))
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
        for k in range(n if (x2, y2) != points[-1] else n + 1):
            t = L * k / n
            out.append((x1 + ux * t, y1 + uy * t, ux, uy))
    return out


def _profile(g, x, y, nx, ny, radius):
    """Grey values along the normal at integer offsets -radius..radius (bilinear); None where the profile leaves the image."""
    h, w = g.shape
    vals = []
    for o in range(-radius, radius + 1):
        px, py = x + nx * o, y + ny * o
        if not (0 <= px <= w - 1 and 0 <= py <= h - 1): return None
        x0, y0 = int(px), int(py); x1, y1 = min(x0 + 1, w - 1), min(y0 + 1, h - 1); fx, fy = px - x0, py - y0
        vals.append(g[y0, x0] * (1 - fx) * (1 - fy) + g[y0, x1] * fx * (1 - fy) + g[y1, x0] * (1 - fx) * fy + g[y1, x1] * fx * fy)
    return np.array(vals)


def nearest_edge_offset(profile, radius, min_contrast, arm):
    """Offset (pixels, signed along the normal) of the nearest step edge in the profile, or None. A step at offset o has contrast
    |mean of `arm` samples after o - mean of `arm` samples before o|; it counts when the contrast reaches `min_contrast` and the
    gradient there is a local maximum. The nearest to the AI's point wins; a tie goes to the larger step."""
    best = None
    n = len(profile)
    grad = np.abs(np.diff(profile))                       # grad[i] sits between samples i and i+1: position i + 0.5
    for i in range(n - 1):
        if grad[i] < min_contrast / arm: continue                      # a step spread over `arm` samples still has this slope
        if grad[i] < grad[max(i - 1, 0)] or grad[i] < grad[min(i + 1, n - 2)]: continue
        before = profile[max(0, i - arm + 1): i + 1].mean(); after = profile[i + 1: i + 1 + arm].mean()
        contrast = abs(after - before)
        if contrast < min_contrast: continue
        off = (i + 0.5) - radius
        key = (abs(off), -contrast)
        if best is None or key < best[0]: best = (key, off, contrast)
    return None if best is None else (best[1], best[2])


def _median_filter(vals, window):
    h = window // 2
    return [float(np.median(vals[max(0, i - h): i + h + 1])) for i in range(len(vals))]


def snap_mark(g, mark, cfg):
    """Snapped copy of one mark, or the mark rejected (UNKNOWN, no_edge_nearby)."""
    radius = int(setting("snapping", "search_radius_px", cfg)[0]); step = setting("snapping", "sample_step_px", cfg)[0]
    contrast = setting("snapping", "min_edge_contrast", cfg)[0]; need = setting("snapping", "min_accepted_fraction", cfg)[0]
    window = int(setting("snapping", "smooth_window", cfg)[0]); arm = int(setting("snapping", "edge_arm_px", cfg)[0])
    samples = _densify(mark.points, step)
    offs = []
    for x, y, ux, uy in samples:
        prof = _profile(g, x, y, -uy, ux, radius)
        offs.append(None if prof is None else nearest_edge_offset(prof, radius, contrast, arm))
    found = [o for o in offs if o is not None]
    frac = len(found) / len(samples) if samples else 0.0
    if not samples or frac < need:
        return mark.model_copy(update={"status": "UNKNOWN", "points": (), "reason_code": REJECTED, "original_points": mark.points,
                                       "snap": {"accepted_fraction": round(frac, 3), "samples": len(samples), "rejected": True}})
    # fill the samples that found no edge with the median of the others, then median-filter along the line
    fill = float(np.median([o[0] for o in found]))
    raw = [fill if o is None else o[0] for o in offs]
    sm = _median_filter(raw, window)
    pts = tuple((round(x - uy * o, 2), round(y + ux * o, 2)) for (x, y, ux, uy), o in zip(samples, sm))
    shifts = [abs(o) for o in sm]
    return mark.model_copy(update={"points": pts, "original_points": mark.points,
                                   "snap": {"accepted_fraction": round(frac, 3), "samples": len(samples), "rejected": False,
                                            "mean_shift_px": round(float(np.mean(shifts)), 2), "max_shift_px": round(float(max(shifts)), 2)}})


def snap_marks(image_bytes, marks, cfg=None):
    """SnapResult: every mark of a snapped feature is snapped or rejected; other marks (lane lines, the work point) pass unchanged.
    `image_bytes` are the bytes sent to the model, so pixel positions match."""
    cfg = cfg or load_site_config()
    features, flags = setting("snapping", "features", cfg)
    g = _gray(image_bytes)
    out, notes = [], []
    for m in marks:
        if m.feature not in features or m.status != "RESOLVED" or len(m.points) < 2:
            out.append(m); continue
        s = snap_mark(g, m, cfg)
        out.append(s)
        if s.status == "UNKNOWN":
            notes.append(f"{m.feature}: no real edge near the AI's line ({s.snap['accepted_fraction']:.0%} of the samples), mark rejected")
        elif s.snap["max_shift_px"] > 0:
            notes.append(f"{m.feature}: snapped, mean shift {s.snap['mean_shift_px']} px, largest {s.snap['max_shift_px']} px")
    return SnapResult(tuple(out), tuple(notes), flags)
