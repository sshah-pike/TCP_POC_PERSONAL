"""Deterministic road cross-section from a close-view image (no model involved).

At a station of the OSM centreline the image is sampled along lines perpendicular to the road (poc_config
"cross_section"): several sections a few metres apart, each a brightness profile +/- profile_half_length_m around the
OSM centreline point. Painted lines are bright, narrow runs above the profile's own median (white = low chroma,
yellow = red-minus-blue). On each section the measurement looks for two EDGE lines whose spacing fits the lane count
(per-lane width within fusion.lane_width_plausible_m) and, when present, a CENTRE line near their middle.
A measurement is accepted only when enough sections agree (width and centre spread within max_section_spread_m).

Painted lines are found as narrow peaks above a rolling local background (cross_section.line_background_window_m), so
pale shoulders, gravel or shadows next to the road are not mistaken for lines.

Outputs (metres, LEFT-positive relative to the OSM centreline digitisation direction):
  width_m             edge line to edge line
  centre_offset_m     measured road centre relative to the OSM centreline (OSM error at this station)
  status              OK | INCONCLUSIVE (+ reason); per-section details are kept for the audit.
Used for: the traveled-way width (instead of a model estimate) and shifting the OSM centreline onto the real road.
"""
import math

import numpy as np

from tcp_planner.contracts import r


def _runs(mask, t, min_gap_m):
    """Centre positions (m) of contiguous True runs in mask along the sample positions t."""
    idx = np.flatnonzero(mask)
    if idx.size == 0: return []
    groups = np.split(idx, np.flatnonzero(np.diff(t[idx]) > min_gap_m) + 1)
    return [(float(t[g].mean()), float(t[g[-1]] - t[g[0]])) for g in groups]


def _section(arr, centre_px, tangent, normal, mpp, cfg, lanes, lane_bounds):
    """One perpendicular profile. Returns dict(width_m, centre_m, centre_source) or dict(reason)."""
    H, W = arr.shape[:2]
    half = cfg["profile_half_length_m"]; step = cfg["sample_step_m"]
    t = np.arange(-half, half + step / 2, step)
    xs = centre_px[0] + normal[0] * t / mpp; ys = centre_px[1] + normal[1] * t / mpp
    ok = (xs >= 0) & (xs < W - 1) & (ys >= 0) & (ys < H - 1)
    if ok.mean() < 0.9: return {"reason": "profile leaves the image"}
    xi = np.clip(xs.round().astype(int), 0, W - 1); yi = np.clip(ys.round().astype(int), 0, H - 1)
    px = arr[yi, xi]; v = px.mean(axis=1); chroma = px.max(axis=1) - px.min(axis=1); rb = px[:, 0] - px[:, 2]
    # local background (rolling median): a painted line is a narrow peak above its surroundings on any surface
    k = max(3, int(round(cfg["line_background_window_m"] / step)) | 1)
    pad = np.pad(v, k // 2, mode="edge")
    bg = np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)
    lift = v - bg
    yellowish = rb >= cfg["yellow_min_rb"]
    bright = (lift >= cfg["line_min_contrast"]) | (yellowish & (lift >= cfg["yellow_min_contrast"]))
    lines = []
    for pos, w in _runs(bright, t, cfg["line_merge_gap_m"]):
        if w > cfg["line_max_width_m"]: continue  # a bright area (pale shoulder, concrete), not a painted line
        sel = np.abs(t - pos) <= max(w / 2, step)
        lines.append({"t": pos, "white": float(chroma[sel].mean()) <= cfg["line_max_chroma"],
                      "yellow": float(rb[sel].mean()) >= cfg["yellow_min_rb"]})
    lo, hi = lane_bounds
    best = None
    for i, a in enumerate(lines):
        for c in lines[i + 1:]:
            width = c["t"] - a["t"]
            if not (lanes * lo <= width <= lanes * hi) or a["yellow"] or c["yellow"]: continue
            mid = (a["t"] + c["t"]) / 2
            centre = [b for b in lines if a["t"] < b["t"] < c["t"] and abs(b["t"] - mid) <= cfg["symmetry_tolerance_m"]]
            # prefer a visible centre line (yellow first), then the pair closest to the OSM centreline
            score = (0 if any(b["yellow"] for b in centre) else 1 if centre else 2, abs(mid))
            if best is None or score < best[0]:
                cl = min(centre, key=lambda b: (not b["yellow"], abs(b["t"] - mid))) if centre else None
                best = (score, {"width_m": width, "centre_m": cl["t"] if cl else mid,
                                "centre_source": ("YELLOW_LINE" if cl["yellow"] else "CENTRE_LINE") if cl else "EDGE_MIDPOINT",
                                "edges_m": [a["t"], c["t"]]})
    if best is None:
        return {"reason": f"no edge-line pair fits {lanes} lane(s) ({len(lines)} line candidates)"}
    return best[1]


def measure(image, meta, offset_m, centerline, station_m, lanes, config):
    """Cross-section at station_m of the (OSM) centreline, from a north-up image whose centre is offset_m
    (east, north) from the work reference. Returns the measurement dict (see module docstring)."""
    from tcp_planner.geometry.local_frame import at
    cfg = config["cross_section"]; lane_bounds = config["fusion"]["lane_width_plausible_m"]
    mpp = meta["metres_per_pixel"]; W, H = meta["width_pixels"], meta["height_pixels"]
    out = {"station_m": r(station_m, 2), "metres_per_pixel": mpp, "lanes_assumed": lanes, "sections": []}
    if mpp > config["fusion"]["width_max_measure_mpp"]:
        return {**out, "status": "INCONCLUSIVE", "reason": f"image too coarse ({mpp:.3f} m/px)"}
    arr = np.asarray(image.convert("RGB"), dtype=np.float64)
    n = cfg["sections"]; spacing = cfg["section_spacing_m"]
    for k in range(n):
        s = station_m + (k - (n - 1) / 2) * spacing
        (x, y), (tx, ty) = at(centerline, s)
        normal_en = (-ty, tx)  # LEFT of the digitisation direction, east/north
        cpx = (W / 2 + (x - offset_m[0]) / mpp, H / 2 - (y - offset_m[1]) / mpp)
        res = _section(arr, cpx, (tx, -ty), (normal_en[0], -normal_en[1]), mpp, cfg, lanes, lane_bounds)
        out["sections"].append({"station_m": r(s, 2), **{k2: (r(v, 3) if isinstance(v, float) else v) for k2, v in res.items()}})
    good = [s for s in out["sections"] if "width_m" in s]
    if len(good) < cfg["min_valid_sections"]:
        return {**out, "status": "INCONCLUSIVE",
                "reason": f"{len(good)} of {n} sections measured (need {cfg['min_valid_sections']}): " +
                          "; ".join(s.get("reason", "") for s in out["sections"] if "reason" in s)}
    widths = [s["width_m"] for s in good]; centres = [s["centre_m"] for s in good]
    spread = max(max(widths) - min(widths), max(centres) - min(centres))
    if spread > cfg["max_section_spread_m"]:
        return {**out, "status": "INCONCLUSIVE", "reason": f"sections disagree by {spread:.2f} m"}
    centre = float(np.median(centres))
    if abs(centre) > cfg["max_centerline_correction_m"]:
        return {**out, "status": "INCONCLUSIVE",
                "reason": f"measured centre {centre:+.2f} m from OSM exceeds cross_section.max_centerline_correction_m"}
    return {**out, "status": "OK", "width_m": r(float(np.median(widths)), 3), "centre_offset_m": r(centre, 3),
            "spread_m": r(spread, 3), "centre_source": good[len(good) // 2]["centre_source"]}


def corrected_centerline(centerline, offsets, step_m):
    """OSM centreline shifted onto the measured road centre: offsets [(station, LEFT-positive offset)] are linearly
    interpolated along the road (constant beyond the first / last measurement) and applied perpendicular to it."""
    from tcp_planner.geometry.local_frame import cum, offset_point
    pts = sorted(offsets)
    total = cum(centerline)[-1]
    n = max(2, int(math.ceil(total / step_m)) + 1)
    out = []
    for i in range(n):
        s = total * i / (n - 1)
        if s <= pts[0][0]: off = pts[0][1]
        elif s >= pts[-1][0]: off = pts[-1][1]
        else:
            j = max(k for k in range(len(pts)) if pts[k][0] <= s)
            (s0, o0), (s1, o1) = pts[j], pts[j + 1]
            off = o0 + (o1 - o0) * (s - s0) / ((s1 - s0) or 1)
        out.append(offset_point(centerline, s, off)[0])
    return out
