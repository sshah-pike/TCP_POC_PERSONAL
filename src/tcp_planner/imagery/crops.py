"""Crop engine (S6 commit 5): code crops first, a higher-zoom fetch only when there are too few pixels.

The crop is computed by code and never chosen by the model: its centre is always the work reference (the centre of the wide
image, which is the KML point), its size comes from config. The decision is on pixel counts only; no model reads an image here.

1. `sufficiency(feature, mpp)`: pixels per feature at a given ground scale against the minimum for that feature.
   Lane features use the existing crops.min_px_per_lane against the narrowest plausible lane; the other features have no value
   yet (CALIBRATION_PENDING) and are never judged sufficient, so a higher-zoom view is always requested for them.
2. `plan_close_view(...)`: sufficient everywhere -> only a code crop of the wide image (no request). Otherwise the zoom that
   meets the strictest feature, capped at the zoom ceiling (crops.primary_zoom, the tileset maximum).
3. `fetch_close_view(...)`: the one map request, recorded as evidence with a signature (imagery.evidence_views.view_signature).
   A view already stored under the same signature is reused with no request (write-once ArtifactStore, key = hash of the
   signature). A failed or blank fetch is recorded as unavailable; it never raises and never invents an image.
4. Information only, never gating: the fetched view's detail (variance of the Laplacian, the old sharpness measure) is compared
   with the same ground area of the wide image enlarged to the view's scale. A ratio below sharpness.min_detail_gain_ratio sets
   the flag NO_DETAIL_GAIN in the evidence (the view may be upsampled). It costs no request: the wide image is already held.
"""
import hashlib, io, json, math, os
from typing import NamedTuple, Optional

from PIL import Image, ImageStat

from tcp_planner.config.settings import CONFIG_DIR
from tcp_planner.contracts import MapProviderError, canonical_json, sha256_hex
from tcp_planner.imagery.evidence_views import view_signature
from tcp_planner.imagery.map_provider import view_metres_per_pixel
from tcp_planner.imagery.prepare import JPEG_QUALITY, resize_for_model
from tcp_planner.site_model.site_config import load_site_config

PLAN_VERSION = "close-view-v1"


def _pipeline():
    with open(os.path.join(CONFIG_DIR, "pipeline_config.json"), encoding="utf-8") as f: return json.load(f)


class Sufficiency(NamedTuple):
    feature: str
    sufficient: bool
    px_per_feature: Optional[float]    # at the scale asked about; None when the feature has no value yet
    needed_mpp: Optional[float]        # coarsest metres per pixel that would be enough; None while CALIBRATION_PENDING
    flags: tuple
    reason: str


def feature_groups(cfg=None):
    c = (cfg or load_site_config())["crops"]
    return set(c["lane_group"]["value"]), set(c["pending_features"]["value"])


def sufficiency(feature, mpp, pipeline=None, cfg=None):
    """Is `mpp` metres per pixel enough for this feature? Lane features: narrowest plausible lane / mpp >= crops.min_px_per_lane.
    Pending features: never sufficient (conservative default). An unknown feature name is an error, not a guess."""
    lane, pending = feature_groups(cfg); pl = pipeline or _pipeline()
    if feature in lane:
        lane_m = pl["fusion"]["lane_width_plausible_m"][0]; need = pl["crops"]["min_px_per_lane"]
        px = lane_m / mpp
        return Sufficiency(feature, px >= need, px, lane_m / need, (), f"{px:.1f} px per narrowest lane vs {need} needed")
    if feature in pending:
        return Sufficiency(feature, False, None, None, ("CALIBRATION_PENDING",), "no pixels-per-feature value yet: a higher-zoom view is always requested")
    raise ValueError(f"unknown crop feature {feature!r}")


def zoom_for(lat, needed_mpp, ceiling):
    """Smallest zoom whose ground scale at `lat` is at most needed_mpp, never above the ceiling. With no value (None) the ceiling."""
    if needed_mpp is None: return ceiling
    z = 1
    while z < ceiling and view_metres_per_pixel(lat, z) > needed_mpp: z += 1
    return z


# ---------------------------------------------------------------- code crop of the image already held
def crop_from_image(data, center_px, size_px):
    """(JPEG bytes, record): a square window of the wide image at native pixels (no resampling, no upscale), centred on
    center_px (computed by code) and kept inside the image. record['offset'] maps a crop pixel back to the source image."""
    with Image.open(io.BytesIO(data)) as im:
        im.load(); w, h = im.size; s = min(int(size_px), w, h)
        x0 = int(round(min(max(center_px[0] - s / 2, 0), w - s))); y0 = int(round(min(max(center_px[1] - s / 2, 0), h - s)))
        out = io.BytesIO(); im.crop((x0, y0, x0 + s, y0 + s)).convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY)
    b = out.getvalue()
    return b, {"source_px": [w, h], "box": [x0, y0, x0 + s, y0 + s], "offset": [x0, y0], "crop_px": [s, s], "resize_scale": 1.0,
               "center_px": [float(center_px[0]), float(center_px[1])], "sha256": hashlib.sha256(b).hexdigest(), "size": len(b),
               "media_type": "image/jpeg"}


def crop_point_to_source(point, record):
    return (point[0] + record["offset"][0], point[1] + record["offset"][1])


# ---------------------------------------------------------------- the decision
class ClosePlan(NamedTuple):
    version: str
    fetch: bool
    spec: Optional[dict]               # role, zoom, lat, lon, size_px, plan: the request, when one is needed
    decisions: tuple                   # Sufficiency per feature at the wide scale
    insufficient: tuple                # features that drove the request
    at_ceiling: bool                   # the zoom ceiling is reached: even this view may not be enough
    mpp_wide: float
    flags: tuple


def plan_close_view(lat, lon, mpp_wide, features, pipeline=None, cfg=None):
    """Decide from pixel counts whether the wide image is enough for the features. No fetch above the threshold."""
    pl = pipeline or _pipeline(); feats = sorted(set(features))
    if not feats: raise ValueError("no feature asked about")
    decisions = tuple(sufficiency(f, mpp_wide, pl, cfg) for f in feats)
    bad = tuple(d for d in decisions if not d.sufficient)
    flags = tuple(sorted({f for d in decisions for f in d.flags}))
    if not bad: return ClosePlan(PLAN_VERSION, False, None, decisions, (), False, mpp_wide, flags)
    ceiling = pl["crops"]["primary_zoom"]
    z = max(zoom_for(lat, d.needed_mpp, ceiling) for d in bad)
    mpp_z = view_metres_per_pixel(lat, z)
    still = any(d.needed_mpp is None or mpp_z > d.needed_mpp for d in bad)
    spec = {"role": "close_view", "label": "close view for " + ", ".join(d.feature for d in bad), "zoom": z, "size_px": pl["crops"]["image_px"],
            "lat": round(lat, 7), "lon": round(lon, 7), "plan": PLAN_VERSION}
    return ClosePlan(PLAN_VERSION, True, spec, decisions, tuple(d.feature for d in bad), still and z >= ceiling, mpp_wide, flags)


# ---------------------------------------------------------------- information only: does the view hold native detail?
def _detail(img):
    """Variance of the 4-neighbour Laplacian of the grey image (the measure of the old sharpness check)."""
    import numpy as np
    a = np.asarray(img.convert("L"), dtype=np.float64)
    lap = a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1]
    return float(lap.var())


def detail_gain(view_img, view_center, view_mpp, wide_img, wide_center, wide_mpp, min_ratio):
    """Information record, or None when the view's footprint is not inside the wide image. Compares the view with the same ground area
    of the wide image enlarged to the view's size (bicubic): a real higher zoom holds far more detail than the enlargement."""
    from tcp_planner.geometry.local_frame import enu
    dx, dy = enu(view_center[0], view_center[1], wide_center[0], wide_center[1])
    cx, cy = wide_img.size[0] / 2 + dx / wide_mpp, wide_img.size[1] / 2 - dy / wide_mpp
    side = view_img.size[0] * view_mpp / wide_mpp
    box = (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))
    if box[0] < 0 or box[1] < 0 or box[2] > wide_img.size[0] or box[3] > wide_img.size[1] or side < 8: return None
    d_hi = _detail(view_img); d_lo = _detail(wide_img.crop(box).resize(view_img.size, Image.BICUBIC))
    ratio = d_hi / d_lo if d_lo > 0 else float("inf")
    return {"measure": "laplacian_variance", "view": round(d_hi, 3), "wide_enlarged": round(d_lo, 3),
            "ratio": None if math.isinf(ratio) else round(ratio, 3), "min_ratio": min_ratio,
            "flag": "NO_DETAIL_GAIN" if ratio < min_ratio else "NATIVE_DETAIL", "gating": False}


# ---------------------------------------------------------------- the one request, recorded as evidence
def view_key(signature):
    """ArtifactStore key of a view: the hash of its signature (provider, scale model, geometry hash, zoom, centre, size)."""
    return "views/" + sha256_hex(canonical_json(signature))


def fetch_close_view(plan, provider, geometry_hash, max_px, pipeline=None, store=None, wide=None):
    """(image bytes or None, evidence record). Calls provider.fetch_view only when the plan says so AND no view is stored under the
    same signature. `store` is an ArtifactStore: the fetched JPEG and its small metadata record are written once, and the next call
    with the same signature reads them back (evidence 'reused': True, zero requests). The evidence holds the view signature, the
    resize record and the purpose; a failed or near-uniform image gives bytes None and 'unavailable' (not stored). Never raises
    for a provider failure. `wide` = (PIL image, centre (lat, lon), metres per pixel) enables the information-only detail check."""
    if not plan.fetch: return None, {"fetched": False, "reason": "enough pixels in the wide image", "plan": plan.version, "mpp_wide": plan.mpp_wide}
    spec = plan.spec; pl = pipeline or _pipeline()
    sig = view_signature(provider, spec, geometry_hash); key = view_key(sig)
    ev = {"fetched": True, "plan": plan.version, "purpose": plan.insufficient, "signature": sig, "view_key": key,
          "parent_crop_spec": dict(spec), "at_zoom_ceiling": plan.at_ceiling, "reused": False}
    if store is not None and store.exists(key + ".jpg"):
        ref = store.stat(key + ".jpg"); raw = store.get(ref); meta = json.loads(store.get(key + ".json"))
        ev.update(reused=True, artifact={"uri": ref.uri, "sha256": ref.sha256, "size": ref.size, "media_type": ref.media_type})
        img = Image.open(io.BytesIO(raw)); img.load()
    else:
        try: img, meta = provider.fetch_view(spec["lat"], spec["lon"], spec["zoom"], spec["size_px"])
        except MapProviderError as e:
            return None, {**ev, "unavailable": f"{e.code}: {e.message}"}
        if ImageStat.Stat(img.convert("L")).stddev[0] < pl["sharpness"]["uniform_max_std"]:
            return None, {**ev, "unavailable": "blank or near-uniform image"}
        buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY); raw = buf.getvalue()
        if store is not None:
            ref = store.put(key + ".jpg", raw, "image/jpeg")
            store.put(key + ".json", json.dumps({"metres_per_pixel": meta["metres_per_pixel"], "signature": sig}, sort_keys=True).encode(), "application/json")
            ev["artifact"] = {"uri": ref.uri, "sha256": ref.sha256, "size": ref.size, "media_type": ref.media_type}
    sent, rec = resize_for_model(raw, max_px, meta["metres_per_pixel"])
    ev.update(image=rec, mpp_view=meta["metres_per_pixel"], mpp_sent=rec["mpp_sent"], center=[spec["lat"], spec["lon"]])
    if wide is not None:
        info = detail_gain(img.convert("RGB"), (spec["lat"], spec["lon"]), meta["metres_per_pixel"], wide[0].convert("RGB"), wide[1], wide[2],
                           pl["sharpness"]["min_detail_gain_ratio"])
        if info: ev["detail_check"] = info
    return sent, ev
