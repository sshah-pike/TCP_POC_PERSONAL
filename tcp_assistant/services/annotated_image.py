"""Static annotated site-understanding image (review artifact, NOT the source of truth).

Drawn only from saved data: the run's lossless analysis image (evidence map_N.png, never modified), the structured
site model, saved crops, plan objects and (optionally) proposed-revision overlay items. Every item carries colour AND a
text tag, a legend number, finding id, label, state, confidence, evidence source and entity id. Geometry that the
pipeline does not have is listed as NOT_ASSESSED and never drawn. Output is deterministic for identical inputs.
"""
import io, math

from tcp_planner.geometry.local_frame import enu, inv, at, cum, offset_point
from . import findings as F

RENDERER_VERSION = "annotated-site-image-v1"
COLORS = {"GREEN": (0, 150, 60), "AMBER": (235, 150, 0), "RED": (210, 30, 30), "GRAY": (150, 150, 150),
          "BLUE": (30, 100, 230), "PURPLE": (145, 60, 205)}
PATTERN = {F.DETERMINED: None, F.NEEDS_CONFIRMATION: (10, 6), F.CONFLICT: None, F.UNKNOWN: (3, 5), F.SME: None,
           F.EXCEPTION: (12, 4, 3, 4)}
KIND_CODE = {"intersections": "INT", "driveways": "DWY", "crosswalks": "XWK", "roundabouts": "RBT", "ramps": "RMP",
             "obstructions": "OBS", "sidewalks": "SDW"}
LEGEND_W = 860
WRAP = 104


def _font(size):
    from PIL import ImageFont
    try: return ImageFont.load_default(size=size)
    except TypeError: return ImageFont.load_default()


def _dash(draw, pts, color, width, pattern):
    if not pattern:
        draw.line(pts, fill=color, width=width, joint="curve"); return
    seq = list(pattern); k = 0; left = seq[0]; on = True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0); pos = 0.0
        while pos < L:
            step = min(left, L - pos)
            a = (x0 + (x1 - x0) * pos / L, y0 + (y1 - y0) * pos / L); b = (x0 + (x1 - x0) * (pos + step) / L, y0 + (y1 - y0) * (pos + step) / L)
            if on: draw.line([a, b], fill=color, width=width)
            pos += step; left -= step
            if left <= 1e-9: k = (k + 1) % len(seq); left = seq[k]; on = not on


class Canvas:
    def __init__(self, image, meta, site):
        self.img = image; self.meta = meta; self.mpp = meta["metres_per_pixel"]
        self.W, self.H = image.size
        self.c_lat, self.c_lon = meta["center"]["latitude"], meta["center"]["longitude"]
        ref = site["project_geometry"]["work_reference"]; self.lat0, self.lon0 = ref["latitude"], ref["longitude"]
        self.cl = [enu(p["latitude"], p["longitude"], self.lat0, self.lon0) for p in site["road"]["centerline"]]
        self.half = site["road"]["road_edges"].get("left_offset_m")

    def px_ll(self, lat, lon):
        x, y = enu(lat, lon, self.c_lat, self.c_lon)
        return (self.W / 2 + x / self.mpp, self.H / 2 - y / self.mpp)

    def px_local(self, x, y):
        lat, lon = inv(x, y, self.lat0, self.lon0)
        return self.px_ll(lat, lon)

    def station_pt(self, s, side=None, extra=4.0):
        s = min(max(s, 0.0), cum(self.cl)[-1])
        if side in ("LEFT", "RIGHT") and self.half:
            lat = (self.half + extra) * (1 if side == "LEFT" else -1)
            (x, y), _ = offset_point(self.cl, s, lat)
        else:
            (x, y), _ = at(self.cl, s)
        return self.px_local(x, y)

    def inside(self, p):
        return 0 <= p[0] < self.W and 0 <= p[1] < self.H


def build_items(ctx, site, findings, plan=None, extra_items=()):
    """Legend + drawing items (pure data; also stored in the artifact manifest)."""
    items = []
    by_subject = {(f["category"], f["subject"]): f for f in findings}

    def item(f, kind, geometry, label=None, **kw):
        items.append({"n": len(items) + 1, "finding_id": f["finding_id"] if f else kw.pop("finding_id", None),
                      "kind": kind, "label": label or (f or {}).get("label"), "state": (f or {}).get("state", kw.pop("state", F.UNKNOWN)),
                      "confidence": (f or {}).get("confidence"), "evidence_sources": (f or {}).get("evidence_sources", kw.pop("sources", [])),
                      "entity_id": (f or {}).get("entity_id", kw.pop("entity_id", None)), "geometry": geometry, **kw})

    cl_f = by_subject.get(("SITE_FACT", "road.centerline_status"))
    item(cl_f, "CENTERLINE", {"type": "centerline"}, "Road centerline")
    ed_f = by_subject.get(("SITE_FACT", "road.road_edges"))
    if site["road"]["road_edges"].get("left"):
        item(ed_f, "ROAD_EDGES", {"type": "edges"}, f"Road edges / traveled way {site['road']['road_edges'].get('traveled_way_width_m')} m")
    for key in ("road.lane_count", "road.two_way", "road.divided", "road.facility_type", "road.road_type", "work.side",
                "work.location", "work.encroaches_traveled_way", "work.affects_pedestrian_route",
                "site.complex_intersection_conflict", "work.requires_lane_closure", "work.requires_alternating_one_lane_traffic"):
        f = by_subject.get(("SITE_FACT", key))
        if f: item(f, "SITE_FACT", {"type": "fact"}, f"{f['label']} = {f['value']}")
    wf = by_subject.get(("SITE_FACT", "work.location"))
    item(wf, "WORK_AREA", {"type": "work"}, "Work location / work area")
    for f in findings:
        if f["category"] != "FEATURE": continue
        g = {"type": "sidewalk", "side": f.get("side"), "present": f.get("value")} if f["feature_kind"] == "sidewalks" else \
            {"type": "feature", "station_m": f.get("station_m"), "side": f.get("side"), "code": KIND_CODE[f["feature_kind"]]}
        item(f, "FEATURE", g, f"{f['label']} {f['entity_id']}" + (" [REJECTED_BY_SME]" if f["status"] == "REJECTED_BY_SME" else ""),
             rejected=f["status"] == "REJECTED_BY_SME")
    for o in (plan or {}).get("objects", []):
        if o["object_type"] == "WORK_LOCATION": continue
        p = o["placement"]; exc = bool(o.get("sme")); blocked = plan.get("plan_id") is None
        item(None, "PLAN_OBJECT", {"type": "object", "lat": p["latitude"], "lon": p["longitude"],
                                   "face_azimuth_deg": p.get("face_azimuth_deg")},
             f"{o['object_id']} {o.get('sign_code') or o.get('object_type')} station {p.get('station_m')} m"
             + (" (computed, not exported: validation failed)" if blocked else ""),
             state=F.EXCEPTION if exc else (F.CONFLICT if blocked else F.DETERMINED), entity_id=o["object_id"], sources=["PLAN"],
             finding_id=None)
    for c in ctx.get("crops") or []:
        bb = ((c.get("metadata") or {}).get("meta") or {}).get("bounding_box")
        if bb: item(None, "CROP_FOOTPRINT", {"type": "bbox", **bb}, f"Saved close view {c.get('origin_artifact_id')}",
                    state=F.DETERMINED, sources=["SAVED_CROP"], entity_id=c.get("origin_artifact_id"))
    item(None, "COVERAGE", {"type": "coverage"}, "Evidence coverage boundary (analysed image / alignment)",
         state=F.DETERMINED, sources=["IMAGERY_METADATA"], entity_id="evidence-coverage")
    for x in extra_items:
        items.append({"n": len(items) + 1, **x})
    return items


def render(ctx, site, findings, plan=None, extra_items=()):
    """-> (png bytes, items, crop box)."""
    from PIL import Image, ImageDraw
    ev = ctx["evidence"]["map"]
    with Image.open(ev["path"]) as im: base = im.convert("RGB")
    meta = ev["metadata"]["meta"]
    cv = Canvas(base, meta, site)
    items = build_items(ctx, site, findings, plan, extra_items)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0)); d = ImageDraw.Draw(overlay)
    font = _font(13); small = _font(11)
    focus = []

    def col(state, alpha=255):
        return COLORS[F.STATE_STYLE[state]["color"]] + (alpha,)

    def tag(p, it, text=None):
        t = f"[{it['n']}] {text or F.STATE_STYLE[it['state']]['glyph']}"
        x, y = p[0] + 8, p[1] - 18
        bb = d.textbbox((x, y), t, font=small)
        d.rectangle([bb[0] - 2, bb[1] - 1, bb[2] + 2, bb[3] + 1], fill=(0, 0, 0, 170))
        d.text((x, y), t, fill=col(it["state"]), font=small)

    work_px = cv.px_ll(site["project_geometry"]["work_reference"]["latitude"], site["project_geometry"]["work_reference"]["longitude"])
    focus.append(work_px)
    for it in items:
        g = it["geometry"]; st = it["state"]; pat = PATTERN[st]
        if g["type"] == "centerline":
            pts = [cv.px_local(x, y) for x, y in cv.cl]
            _dash(d, pts, col(st), 2, pat or (14, 6)); tag(pts[len(pts) // 2], it, "CL " + F.STATE_STYLE[st]["glyph"])
        elif g["type"] == "edges":
            for k in ("left", "right"):
                pts = [cv.px_ll(p["latitude"], p["longitude"]) for p in site["road"]["road_edges"].get(k) or []]
                if len(pts) > 1: _dash(d, pts, col(st, 200), 2, pat)
            le = site["road"]["road_edges"].get("left") or []
            if le: tag(cv.px_ll(le[len(le) // 3]["latitude"], le[len(le) // 3]["longitude"]), it, "EDGE " + F.STATE_STYLE[st]["glyph"])
        elif g["type"] == "work":
            path = [work_px] + [cv.px_ll(p["latitude"], p["longitude"]) for p in site["project_geometry"].get("work_path") or []]
            if len(path) > 1: _dash(d, path, col(st), 4, pat)
            d.ellipse([work_px[0] - 7, work_px[1] - 7, work_px[0] + 7, work_px[1] + 7], outline=col(st), width=3)
            tag(work_px, it, "WORK " + F.STATE_STYLE[st]["glyph"])
        elif g["type"] == "feature":
            if g.get("station_m") is None: continue  # unplaced: legend only (position UNKNOWN)
            p = cv.station_pt(g["station_m"], g.get("side"))
            if not cv.inside(p): continue
            focus.append(p)
            r = 9; box = [p[0] - r, p[1] - r, p[0] + r, p[1] + r]
            d.rectangle(box, outline=col(st), width=3)
            if it.get("rejected"): d.line([box[0], box[1], box[2], box[3]], fill=col(st), width=2); d.line([box[0], box[3], box[2], box[1]], fill=col(st), width=2)
            tag(p, it, f"{g['code']} " + ("REJECTED" if it.get("rejected") else F.STATE_STYLE[st]["glyph"]))
        elif g["type"] == "sidewalk":
            if g.get("present") is not True or g.get("side") not in ("LEFT", "RIGHT"): continue
            s0 = site["work"]["reference_station_m"]
            pts = [cv.station_pt(s0 + ds, g["side"], extra=7.0) for ds in range(-40, 41, 8)]
            _dash(d, pts, col(st, 220), 3, pat or (6, 4)); tag(pts[-1], it, "SDW " + F.STATE_STYLE[st]["glyph"])
        elif g["type"] == "object":
            p = cv.px_ll(g["lat"], g["lon"]); focus.append(p)
            d.polygon([(p[0], p[1] - 10), (p[0] + 10, p[1]), (p[0], p[1] + 10), (p[0] - 10, p[1])], outline=col(st), fill=col(st, 90), width=2)
            tag(p, it, it["entity_id"] + " " + F.STATE_STYLE[st]["glyph"])
        elif g["type"] in ("proposed_point", "path"):
            pts = [cv.px_ll(a, b) for a, b in g["points"]]; focus += pts
            if g["type"] == "path" and len(pts) > 1: _dash(d, pts, col(st), 3, (8, 5))
            else:
                p = pts[0]; d.ellipse([p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9], outline=col(st), width=3)
            tag(pts[-1], it, it.get("tag") or F.STATE_STYLE[st]["glyph"])
        elif g["type"] == "bbox":
            a = cv.px_ll(g["max_latitude"], g["min_longitude"]); b = cv.px_ll(g["min_latitude"], g["max_longitude"])
            _dash(d, [a, (b[0], a[1]), b, (a[0], b[1]), a], col(st, 160), 1, (6, 6))
        elif g["type"] == "coverage":
            L = cum(cv.cl)[-1]
            for s in (0.0, L):
                p = cv.station_pt(s)
                if cv.inside(p): d.line([p[0] - 10, p[1] - 10, p[0] + 10, p[1] + 10], fill=col(st), width=3); tag(p, it, "END OF ANALYSED ALIGNMENT")
    img = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    # crop to the reviewed corridor (deterministic) and add the legend panel
    xs = [p[0] for p in focus]; ys = [p[1] for p in focus]; m = 120
    x0, x1 = max(0, int(min(xs) - m)), min(cv.W, int(max(xs) + m)); y0, y1 = max(0, int(min(ys) - m)), min(cv.H, int(max(ys) + m))
    if x1 - x0 < 640: c = (x0 + x1) // 2; x0, x1 = max(0, c - 320), min(cv.W, c + 320)
    if y1 - y0 < 640: c = (y0 + y1) // 2; y0, y1 = max(0, c - 320), min(cv.H, c + 320)
    crop = img.crop((x0, y0, x1, y1))
    lines = _legend_lines(items, site, ctx)
    H = max(crop.size[1], 40 + 17 * len(lines))
    out = Image.new("RGB", (crop.size[0] + LEGEND_W, H), (250, 250, 250)); out.paste(crop, (0, 0))
    dl = ImageDraw.Draw(out); y = 10
    for text, state in lines:
        if state: dl.rectangle([crop.size[0] + 8, y + 3, crop.size[0] + 18, y + 13], fill=COLORS[F.STATE_STYLE[state]["color"]])
        dl.text((crop.size[0] + (24 if state else 8), y), text, fill=(20, 20, 20), font=font if not state else small)
        y += 17
    buf = io.BytesIO(); out.save(buf, format="PNG", optimize=False)
    return buf.getvalue(), items, [x0, y0, x1, y1]


def _legend_lines(items, site, ctx):
    lines = [("SITE UNDERSTANDING REVIEW - static review artifact, not the source of truth.", None),
             ("Structured site facts and geometry remain authoritative. AUTOMATED DRAFT - NOT FOR FIELD USE.", None),
             ("OK=green determined | LOW=amber confirm | CONFLICT=red | UNKNOWN=gray | SME=blue | EXCEPTION=purple", None),
             ("", None)]
    for it in items:
        conf = "" if it.get("confidence") is None else f" conf {it['confidence']:.2f}"
        src = "+".join(str(s) for s in it.get("evidence_sources") or []) or "-"
        lines.append((f"[{it['n']}] {F.STATE_STYLE[it['state']]['glyph']} {it.get('finding_id') or ''} {it['label']}"[:WRAP], it["state"]))
        lines.append((f"      {it['state']}{conf}  source {src}  id {it.get('entity_id') or '-'}"[:WRAP], None))
    lines += [("", None), ("NOT_ASSESSED (no saved geometry; never drawn):", None)]
    na = ", ".join(F.NOT_ASSESSED)
    while na:
        cut = na[:WRAP - 6].rfind(", ") + 2 if len(na) > WRAP - 6 else len(na)
        lines.append(("      " + na[:cut].strip(), None)); na = na[cut:]
    m = ctx["evidence"]["map"]["metadata"]["meta"]
    lines.append((f"Imagery {m.get('provider')} {m['ground_extent_m']['width']:.0f} m wide, {m['metres_per_pixel']:.3f} m/px; "
                  f"analysed alignment {site['road'].get('centerline_length_m')} m", None))
    return lines
