"""Crop engine, owner reply B: a stored view with the same signature is reused with no request; request counts per zone run;
the information-only detail check on real recorded Rhode Island views (no gating)."""
import glob, io, json, os

import pytest
from PIL import Image

from tcp_planner.contracts import MapProviderError
from tcp_planner.geometry.local_frame import enu
from tcp_planner.imagery import crops as C
from tcp_planner.imagery.map_provider import view_metres_per_pixel
from tcp_planner.storage.interfaces import IntegrityError
from tcp_planner.storage.memory import InMemoryArtifactStore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
REC = os.path.join(ROOT, "tests", "fixtures", "recorded", "granite_p30")
LAT, LON = 41.3716649, -71.8204461
GEOM = "g" * 64


class Provider:
    name = "azure_maps"; SCALE_MODEL = "azure-static-512px-v2"; API_VERSION = "2024-04-01"

    def __init__(self, fail=False, image=None): self.calls, self.fail, self.image = [], fail, image

    def fetch_view(self, lat, lon, zoom, size_px):
        self.calls.append((lat, lon, zoom, size_px))
        if self.fail: raise MapProviderError("MAP_REQUEST_FAILED", "boom")
        img = self.image or Image.new("RGB", (size_px, size_px), (120, 120, 120))
        if self.image is None:
            for x in range(0, size_px, 8):
                for y in range(0, size_px, 8):
                    if (x // 8 + y // 8) % 2: img.paste((20, 200, 40), (x, y, x + 8, y + 8))
        return img, {"metres_per_pixel": view_metres_per_pixel(lat, zoom), "zoom": zoom}


def plan(mpp=0.448, features=("lane",)): return C.plan_close_view(LAT, LON, mpp, list(features))


# ---------------------------------------------------------------- reuse: same signature, zero requests
def test_the_second_call_with_the_same_signature_makes_zero_requests():
    store = InMemoryArtifactStore(); prov = Provider()
    d1, e1 = C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    d2, e2 = C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    assert len(prov.calls) == 1                                          # the second call read the stored view
    assert d1 == d2 and e1["reused"] is False and e2["reused"] is True
    assert e1["signature"] == e2["signature"] and e1["view_key"] == e2["view_key"] and e1["artifact"] == e2["artifact"]
    assert e2["image"]["sha256"] == e1["image"]["sha256"]


def test_a_different_signature_makes_a_new_request():
    store = InMemoryArtifactStore(); prov = Provider()
    C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    C.fetch_close_view(plan(), prov, "h" * 64, 1280, store=store)       # another geometry hash
    C.fetch_close_view(plan(features=("curb",)), prov, GEOM, 1280, store=store)     # the same zoom here, so the same signature: reused
    assert len(prov.calls) == 2


def test_the_stored_view_is_a_write_once_artifact_with_a_ref():
    store = InMemoryArtifactStore(); prov = Provider()
    _, ev = C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    ref = ev["artifact"]
    assert set(ref) == {"uri", "sha256", "size", "media_type"} and ref["media_type"] == "image/jpeg"
    assert store.exists(ev["view_key"] + ".jpg") and store.exists(ev["view_key"] + ".json")
    assert "\\" not in ref["uri"] and ":" not in ref["uri"].split("/")[0]   # a key, not a raw local path


def test_the_reuse_is_independent_of_the_profile_limit():
    store = InMemoryArtifactStore(); prov = Provider()
    big, _ = C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    small, ev = C.fetch_close_view(plan(), prov, GEOM, 512, store=store)       # another profile limit, same stored view
    assert len(prov.calls) == 1 and ev["reused"] and Image.open(io.BytesIO(small)).size == (512, 512) and Image.open(io.BytesIO(big)).size == (1024, 1024)
    assert ev["mpp_sent"] == pytest.approx(2 * view_metres_per_pixel(LAT, 19))


def test_a_changed_stored_view_is_detected_not_used():
    store = InMemoryArtifactStore(); prov = Provider()
    C.fetch_close_view(plan(), prov, GEOM, 1280, store=store)
    key = C.view_key(C.view_signature(prov, plan().spec, GEOM)) + ".jpg"
    ref = store.stat(key)
    with pytest.raises(IntegrityError): store.get(type(ref)(uri=ref.uri, sha256="0" * 64, size=ref.size, media_type=ref.media_type))


def test_no_store_means_no_reuse_and_no_error():
    prov = Provider()
    C.fetch_close_view(plan(), prov, GEOM, 1280); C.fetch_close_view(plan(), prov, GEOM, 1280)
    assert len(prov.calls) == 2


def test_a_failed_view_is_not_stored_so_the_next_call_tries_again():
    store = InMemoryArtifactStore(); bad = Provider(fail=True); good = Provider()
    _, e1 = C.fetch_close_view(plan(), bad, GEOM, 1280, store=store)
    assert "unavailable" in e1 and not store.exists(e1["view_key"] + ".jpg")          # nothing stored for a failure
    _, e2 = C.fetch_close_view(plan(), good, GEOM, 1280, store=store)
    assert len(good.calls) == 1 and e2["reused"] is False


# ---------------------------------------------------------------- requests per zone run (the close view only; the wide image is separate)
def test_close_view_requests_per_zone_run():
    """wide image sufficient: 0; insufficient: 1; failed view: 1, recorded unavailable. (The wide image is one more request per zone.)"""
    ok = Provider(); C.fetch_close_view(plan(mpp=0.10), ok, GEOM, 1280); assert len(ok.calls) == 0
    short = Provider(); C.fetch_close_view(plan(), short, GEOM, 1280); assert len(short.calls) == 1
    failed = Provider(fail=True); _, ev = C.fetch_close_view(plan(), failed, GEOM, 1280)
    assert len(failed.calls) == 1 and "unavailable" in ev


def test_one_request_serves_every_feature_that_needs_a_close_view():
    prov = Provider(); store = InMemoryArtifactStore()
    p = plan(features=("lane", "road_edge", "lane_line", "curb", "shoulder_edge"))
    C.fetch_close_view(p, prov, GEOM, 1280, store=store)
    assert len(prov.calls) == 1 and p.spec["zoom"] == 19


# ---------------------------------------------------------------- information-only detail check, on real recorded views
def _real_pair():
    wide = json.load(open(glob.glob(os.path.join(REC, "map", "*.json"))[0])); wimg = Image.open(glob.glob(os.path.join(REC, "map", "*.png"))[0]).convert("RGB")
    wm = wide["meta"]; wc = (wm["center"]["latitude"], wm["center"]["longitude"])
    for f in sorted(glob.glob(os.path.join(REC, "map_crop", "*.json"))):
        d = json.load(open(f)); m = d["meta"]
        if m["zoom"] != 19: continue
        cc = (m["center"]["latitude"], m["center"]["longitude"]); dx, dy = enu(cc[0], cc[1], *wc)
        side = m["width_pixels"] * m["metres_per_pixel"] / wm["metres_per_pixel"]
        cx, cy = wimg.size[0] / 2 + dx / wm["metres_per_pixel"], wimg.size[1] / 2 - dy / wm["metres_per_pixel"]
        if cx - side / 2 >= 0 and cy - side / 2 >= 0 and cx + side / 2 <= wimg.size[0] and cy + side / 2 <= wimg.size[1]:
            return wimg, wc, wm["metres_per_pixel"], Image.open(f[:-5] + ".png").convert("RGB"), cc, m["metres_per_pixel"]
    pytest.skip("no recorded zoom 19 view inside the wide image")


def test_real_ri_zoom_19_views_hold_native_detail_far_above_the_old_gate():
    wimg, wc, wmpp, view, vc, vmpp = _real_pair()
    info = C.detail_gain(view, vc, vmpp, wimg, wc, wmpp, 1.15)
    assert info["flag"] == "NATIVE_DETAIL" and info["ratio"] > 10 and info["gating"] is False


def test_an_upsampled_view_is_flagged_no_detail_gain_but_not_rejected():
    wimg, wc, wmpp, view, vc, vmpp = _real_pair()
    dx, dy = enu(vc[0], vc[1], *wc); side = view.size[0] * vmpp / wmpp
    cx, cy = wimg.size[0] / 2 + dx / wmpp, wimg.size[1] / 2 - dy / wmpp
    fake = wimg.crop((round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))).resize(view.size, Image.BICUBIC)
    info = C.detail_gain(fake, vc, vmpp, wimg, wc, wmpp, 1.15)
    assert info["flag"] == "NO_DETAIL_GAIN" and info["ratio"] == pytest.approx(1.0, abs=0.05)
    prov = Provider(image=fake)
    data, ev = C.fetch_close_view(C.plan_close_view(vc[0], vc[1], wmpp, ["lane"]), prov, GEOM, 1280, wide=(wimg, wc, wmpp))
    assert data is not None and ev["detail_check"]["flag"] == "NO_DETAIL_GAIN"           # information only: the view is still returned


def test_the_detail_check_is_skipped_when_the_view_is_outside_the_wide_image():
    wimg, wc, wmpp, view, vc, vmpp = _real_pair()
    assert C.detail_gain(view, (vc[0] + 0.02, vc[1]), vmpp, wimg, wc, wmpp, 1.15) is None


def test_the_detail_check_makes_no_request():
    wimg, wc, wmpp, view, vc, vmpp = _real_pair(); prov = Provider(image=view)
    C.fetch_close_view(C.plan_close_view(vc[0], vc[1], wmpp, ["lane"]), prov, GEOM, 1280, wide=(wimg, wc, wmpp))
    assert len(prov.calls) == 1
