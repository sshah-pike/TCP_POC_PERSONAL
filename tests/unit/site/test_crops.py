"""Crop engine (S6 commit 5): decisions on pixel counts, code crops, one recorded higher-zoom fetch. No model, no network."""
import ast, copy, hashlib, io, json, os

import pytest
from PIL import Image

from tcp_planner.contracts import MapProviderError
from tcp_planner.imagery import crops as C
from tcp_planner.imagery.map_provider import view_metres_per_pixel

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LAT, LON = 41.3710266, -71.8203533
PIPE = C._pipeline()
NEED = PIPE["crops"]["min_px_per_lane"]; NARROW = PIPE["fusion"]["lane_width_plausible_m"][0]
GEOM = "g" * 64


class Provider:
    """Counts requests; returns a textured synthetic view at the real Azure scale."""
    name = "azure_maps"; SCALE_MODEL = "azure-static-512px-v2"; API_VERSION = "2024-04-01"

    def __init__(self, uniform=False, fail=False): self.calls, self.uniform, self.fail = [], uniform, fail

    def fetch_view(self, lat, lon, zoom, size_px):
        self.calls.append((lat, lon, zoom, size_px))
        if self.fail: raise MapProviderError("MAP_REQUEST_FAILED", "boom")
        img = Image.new("RGB", (size_px, size_px), (120, 120, 120))
        if not self.uniform:
            for x in range(0, size_px, 8):
                for y in range(0, size_px, 8):
                    if (x // 8 + y // 8) % 2: img.paste((20, 200, 40), (x, y, x + 8, y + 8))
        return img, {"metres_per_pixel": view_metres_per_pixel(lat, zoom), "zoom": zoom}


def jpeg(w, h, color=(90, 120, 60)):
    b = io.BytesIO(); Image.new("RGB", (w, h), color).save(b, "JPEG"); return b.getvalue()


# ---------------------------------------------------------------- pixel sufficiency (mocked pixel counts)
def test_a_lane_is_sufficient_when_the_narrowest_lane_has_enough_pixels():
    needed = NARROW / NEED
    assert C.sufficiency("lane", needed).sufficient                       # exactly enough
    assert not C.sufficiency("lane", needed * 1.001).sufficient           # a hair coarser
    s = C.sufficiency("lane", 0.448)
    assert not s.sufficient and s.px_per_feature == pytest.approx(NARROW / 0.448) and s.needed_mpp == pytest.approx(needed)


def test_the_lane_values_are_read_from_the_pipeline_config_not_copied():
    pl = copy.deepcopy(PIPE); pl["crops"]["min_px_per_lane"] = 30
    assert C.sufficiency("lane", 0.1, PIPE).sufficient and not C.sufficiency("lane", 0.1, pl).sufficient


@pytest.mark.parametrize("feature", ["lane", "road_edge", "lane_line"])
def test_every_lane_feature_uses_the_lane_rule(feature):
    assert C.sufficiency(feature, 0.1).sufficient and not C.sufficiency(feature, 0.4).sufficient


@pytest.mark.parametrize("feature", ["shoulder_edge", "curb", "sidewalk", "bicycle_lane"])
def test_pending_features_are_never_sufficient_and_say_why(feature):
    for mpp in (0.01, 0.1, 1.0):
        s = C.sufficiency(feature, mpp)
        assert not s.sufficient and s.needed_mpp is None and s.flags == ("CALIBRATION_PENDING",)


def test_an_unknown_feature_is_an_error_not_a_guess():
    with pytest.raises(ValueError): C.sufficiency("pothole", 0.1)


def test_the_groups_do_not_overlap():
    lane, pending = C.feature_groups()
    assert lane == {"lane", "road_edge", "lane_line"} and not (lane & pending)


# ---------------------------------------------------------------- the decision and the zoom
def test_no_fetch_when_the_wide_image_has_enough_pixels():
    plan = C.plan_close_view(LAT, LON, 0.10, ["lane", "road_edge"])
    assert not plan.fetch and plan.spec is None and plan.insufficient == () and not plan.at_ceiling
    prov = Provider(); data, ev = C.fetch_close_view(plan, prov, GEOM, 1280)
    assert prov.calls == [] and data is None and ev["fetched"] is False                  # zero requests above the threshold


def test_a_fetch_is_planned_when_pixels_are_short_at_the_spike_scale():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    assert plan.fetch and plan.insufficient == ("lane",)
    z = plan.spec["zoom"]
    assert z == 19 and view_metres_per_pixel(LAT, z) <= NARROW / NEED < view_metres_per_pixel(LAT, z - 1)   # the coarsest zoom that is enough
    assert plan.spec["size_px"] == PIPE["crops"]["image_px"] and plan.spec["plan"] == "close-view-v1"
    assert (plan.spec["lat"], plan.spec["lon"]) == (round(LAT, 7), round(LON, 7))         # centred on the work reference


def test_the_zoom_is_never_above_the_ceiling():
    ceiling = PIPE["crops"]["primary_zoom"]
    for lat in (0.0, 41.37, 60.0):
        assert C.zoom_for(lat, 1e-6, ceiling) == ceiling
        assert C.zoom_for(lat, None, ceiling) == ceiling


def test_a_coarser_need_gives_a_lower_zoom():
    ceiling = PIPE["crops"]["primary_zoom"]
    assert C.zoom_for(LAT, 0.5, ceiling) < C.zoom_for(LAT, 0.05, ceiling)
    assert view_metres_per_pixel(LAT, C.zoom_for(LAT, 0.5, ceiling)) <= 0.5


def test_a_pending_feature_always_asks_for_the_ceiling_zoom_and_flags_it():
    plan = C.plan_close_view(LAT, LON, 0.05, ["shoulder_edge"])           # even a very fine wide image does not satisfy it
    assert plan.fetch and plan.spec["zoom"] == PIPE["crops"]["primary_zoom"] and plan.at_ceiling
    assert "CALIBRATION_PENDING" in plan.flags and plan.insufficient == ("shoulder_edge",)


def test_the_strictest_feature_drives_the_zoom_and_sufficient_ones_do_not_count():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane", "curb"])
    assert plan.insufficient == ("curb", "lane") and plan.spec["zoom"] == PIPE["crops"]["primary_zoom"]
    only_curb = C.plan_close_view(LAT, LON, 0.10, ["lane", "curb"])
    assert only_curb.insufficient == ("curb",)                           # the lane was fine at 0.10 m per pixel


def test_the_plan_is_deterministic_and_independent_of_the_order_of_features():
    a = C.plan_close_view(LAT, LON, 0.448, ["lane", "curb", "road_edge"]); b = C.plan_close_view(LAT, LON, 0.448, ["road_edge", "lane", "curb"])
    assert a == b


def test_no_features_is_an_error():
    with pytest.raises(ValueError): C.plan_close_view(LAT, LON, 0.4, [])


# ---------------------------------------------------------------- the fetch is recorded as evidence
def test_one_request_with_a_signature_and_a_resize_record():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"]); prov = Provider()
    data, ev = C.fetch_close_view(plan, prov, GEOM, 1280)
    assert len(prov.calls) == 1 and prov.calls[0][2:] == (19, 1024) and data is not None
    sig = ev["signature"]
    assert sig["kind"] == "map_view" and sig["role"] == "close_view" and sig["provider"] == "azure_maps" and sig["scale_model"] == "azure-static-512px-v2"
    assert sig["geometry_hash"] == GEOM and sig["zoom"] == 19 and sig["size_px"] == 1024 and (sig["lat"], sig["lon"]) == (round(LAT, 7), round(LON, 7))
    assert ev["purpose"] == ("lane",) and ev["parent_crop_spec"] == plan.spec and ev["fetched"] is True
    rec = ev["image"]
    assert rec["sha256"] == hashlib.sha256(data).hexdigest() and rec["size"] == len(data) and rec["resize_scale"] == 1.0
    assert ev["mpp_sent"] == pytest.approx(view_metres_per_pixel(LAT, 19)) and "unavailable" not in ev


def test_the_signature_changes_with_the_geometry_hash_and_the_zoom():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    s1 = C.fetch_close_view(plan, Provider(), "a" * 64, 1280)[1]["signature"]
    s2 = C.fetch_close_view(plan, Provider(), "b" * 64, 1280)[1]["signature"]
    assert s1 != s2 and s1["zoom"] == s2["zoom"]


def test_the_fetched_view_is_resized_to_the_profile_limit_and_the_scale_follows():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    data, ev = C.fetch_close_view(plan, Provider(), GEOM, 512)
    assert Image.open(io.BytesIO(data)).size == (512, 512) and ev["image"]["resize_scale"] == 0.5
    assert ev["mpp_sent"] == pytest.approx(2 * view_metres_per_pixel(LAT, 19))


def test_a_failed_request_is_recorded_not_raised_and_no_image_is_invented():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    data, ev = C.fetch_close_view(plan, Provider(fail=True), GEOM, 1280)
    assert data is None and "MAP_REQUEST_FAILED" in ev["unavailable"] and ev["signature"]["zoom"] == 19


def test_a_blank_view_is_unavailable():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    data, ev = C.fetch_close_view(plan, Provider(uniform=True), GEOM, 1280)
    assert data is None and ev["unavailable"] == "blank or near-uniform image"


# ---------------------------------------------------------------- the code crop
def textured(w, h):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for x in range(w):
        for y in range(h): px[x, y] = (x * 255 // w, y * 255 // h, 100)      # smooth: JPEG keeps it within a few levels
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def test_the_crop_is_cut_at_native_pixels_around_a_centre_computed_by_code():
    data = textured(1280, 1280)
    out, rec = C.crop_from_image(data, (640, 640), 400)
    assert rec["box"] == [440, 440, 840, 840] and rec["crop_px"] == [400, 400] and rec["resize_scale"] == 1.0
    crop = Image.open(io.BytesIO(out)); src = Image.open(io.BytesIO(data)).convert("RGB")
    assert crop.size == (400, 400)
    # native pixels: the crop's centre pixel is the source's centre pixel (JPEG tolerance), no resampling
    a, b = crop.getpixel((200, 200)), src.getpixel((640, 640))
    assert max(abs(x - y) for x, y in zip(a, b)) < 8


def test_the_crop_stays_inside_the_image_and_keeps_its_size():
    out, rec = C.crop_from_image(textured(1280, 1280), (20, 1270), 400)
    assert rec["box"] == [0, 880, 400, 1280] and Image.open(io.BytesIO(out)).size == (400, 400)


def test_a_crop_larger_than_the_image_is_the_whole_image_never_upscaled():
    out, rec = C.crop_from_image(textured(300, 200), (150, 100), 1024)
    assert rec["crop_px"] == [200, 200] and Image.open(io.BytesIO(out)).size == (200, 200)


def test_crop_points_map_back_to_the_source_image():
    _, rec = C.crop_from_image(textured(1280, 1280), (640, 640), 400)
    assert C.crop_point_to_source((200, 200), rec) == (640, 640) and C.crop_point_to_source((0, 0), rec) == (440, 440)


def test_the_crop_record_hashes_the_bytes_and_is_deterministic():
    d = textured(800, 800)
    (a, ra), (b, rb) = C.crop_from_image(d, (400, 400), 300), C.crop_from_image(d, (400, 400), 300)
    assert a == b and ra == rb and ra["sha256"] == hashlib.sha256(a).hexdigest() and ra["size"] == len(a)


# ---------------------------------------------------------------- never chosen by the model
def test_the_crop_engine_takes_no_model_output():
    src = open(os.path.join(ROOT, "src", "tcp_planner", "imagery", "crops.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {"call1", "Mark", "parse_call1", "Observation"} & imported and "tcp_planner.ai" not in " ".join(m for m in imported if m)
    import inspect
    for fn in (C.plan_close_view, C.crop_from_image, C.fetch_close_view):
        assert not {"marks", "observations", "facts"} & set(inspect.signature(fn).parameters)


def test_the_crop_centre_is_the_work_reference_in_the_plan():
    plan = C.plan_close_view(LAT, LON, 0.448, ["lane"])
    assert (plan.spec["lat"], plan.spec["lon"]) == (round(LAT, 7), round(LON, 7))
