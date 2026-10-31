"""Code checks on the image (S6 step 9): lane lines, shadow and canopy share, image-to-OSM offset. Synthetic images, no network."""
import inspect
import io

import numpy as np
import pytest
from PIL import Image

from tcp_planner.site_model import code_checks as C
from tcp_planner.site_model.facts import Mark, SiteFact
from tcp_planner.site_model.site_config import load_site_config, setting

W = H = 400
ASPHALT, GROUND = (70, 70, 72), (150, 140, 120)


def png(arr):
    buf = io.BytesIO(); Image.fromarray(arr.astype(np.uint8), "RGB").save(buf, "PNG"); return buf.getvalue()


def scene(top=150, bottom=250):
    a = np.zeros((H, W, 3)); a[:] = GROUND; a[top:bottom, :] = ASPHALT
    return a


def edges(top=150, bottom=250, x0=40, x1=360):
    return (Mark(feature="road_edge_left", status="RESOLVED", points=((x0, top), (x1, top))),
            Mark(feature="road_edge_right", status="RESOLVED", points=((x0, bottom), (x1, bottom))))


def paint(a, y, thick=3, colour=(235, 235, 235), x_from=0, x_to=W):
    a[y - thick // 2: y - thick // 2 + thick, x_from:x_to] = colour


# ---------------------------------------------------------------- lane lines
def test_one_painted_centre_line_is_one_interior_line_and_implies_two_lanes():
    a = scene(); paint(a, 200)
    r = C.lane_lines(png(a), edges())
    assert r.ran and r.ok and r.data["interior_lines"] == 1 and r.data["implied_total_lanes"] == 2


def test_two_lane_lines_imply_three_lanes_and_yellow_paint_counts():
    a = scene(); paint(a, 183); paint(a, 217, colour=(240, 220, 60))
    r = C.lane_lines(png(a), edges())
    assert r.data["interior_lines"] == 2 and r.data["implied_total_lanes"] == 3


def test_a_double_yellow_is_one_line():
    a = scene(); paint(a, 198, 2, (240, 220, 60)); paint(a, 202, 2, (240, 220, 60))
    assert C.lane_lines(png(a), edges()).data["interior_lines"] == 1


def test_edge_lines_next_to_the_edge_marks_are_not_lane_lines():
    a = scene(); paint(a, 154); paint(a, 246); paint(a, 200)
    assert C.lane_lines(png(a), edges()).data["interior_lines"] == 1


def test_no_painted_line_means_the_check_did_not_judge_anything():
    r = C.lane_lines(png(scene()), edges())
    assert (r.ran, r.ok, r.data["interior_lines"]) == (False, None, 0) and "nothing to judge" in r.evidence           # owner review R5


def test_a_line_seen_in_too_few_stations_is_not_detected():
    a = scene(); paint(a, 200, x_from=40, x_to=40 + 90)                       # about a quarter of the length
    assert C.lane_lines(png(a), edges()).data["interior_lines"] == 0


def test_a_diagonal_road_is_handled():
    yy, xx = np.mgrid[0:H, 0:W]
    d = yy - 0.5 * xx
    a = np.zeros((H, W, 3)); a[:] = GROUND
    a[(d > 100) & (d < 200)] = ASPHALT
    a[(d > 148) & (d < 152)] = (235, 235, 235)                                 # a line down the middle of the diagonal band
    marks = (Mark(feature="road_edge_left", status="RESOLVED", points=((40, 120), (300, 250))),
             Mark(feature="road_edge_right", status="RESOLVED", points=((40, 220), (300, 350))))
    r = C.lane_lines(png(a), marks)
    assert r.ran and r.data["interior_lines"] == 1


def test_missing_edge_marks_mean_the_check_does_not_run():
    r = C.lane_lines(png(scene()), ())
    assert (r.ran, r.ok) == (False, None) and "edge marks" in r.evidence


# ---------------------------------------------------------------- shadow and canopy share (computed by code)
def test_a_clear_road_has_no_share():
    r = C.shares(png(scene()), edges())
    assert r.ran and r.ok and r.data["covered_share"] < 0.02


def test_half_canopy_is_counted_by_code():
    a = scene(); a[150:200, :] = (40, 120, 40)                                  # the upper half of the road under green foliage
    r = C.shares(png(a), edges())
    assert 0.42 <= r.data["canopy_share"] <= 0.58 and r.ok is False and r.data["shadow_share"] < 0.05


def test_cast_shadow_is_counted_by_code():
    a = scene(); a[150:250, 100:300] = (25, 25, 27)                             # a dark band across half the length
    r = C.shares(png(a), edges())
    assert 0.35 <= r.data["shadow_share"] <= 0.65 and r.data["canopy_share"] < 0.02 and r.ok is False


def test_a_small_share_does_not_object():
    a = scene(); a[150:250, 100:140] = (25, 25, 27)
    r = C.shares(png(a), edges())
    assert 0.05 < r.data["covered_share"] < 0.2 and r.ok is True


def test_the_effect_makes_edge_based_facts_unknown_occluded_and_keeps_the_ai_values():
    a = scene(); a[150:250, :] = (40, 120, 40)
    r = C.shares(png(a), edges())
    shoulder = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="FOUND", value=True)
    width = SiteFact(field="lane_width_ft", registry_id="lane_width_ft", unit="ft", source="AI_MARKS", outcome="FOUND", value=11.0)
    lanes = SiteFact(field="lanes_per_direction", registry_id="lanes_per_direction", source="AI", outcome="FOUND", value=2)
    out = C.occlusion_effect([shoulder, width, lanes], r)
    assert [f.outcome for f in out] == ["UNKNOWN", "UNKNOWN", "FOUND"] and out[0].reason_code == "occluded" and out[0].candidates[-1].value is True
    assert C.occlusion_effect([shoulder], C.shares(png(scene()), edges())) == [shoulder]                     # no objection: untouched


def test_the_models_shares_are_a_cross_check_candidate_only():
    clear = C.shares(png(scene()), edges())
    ev = C.compare_model_shares(clear, 0.9, 0.9)                                # the model claims heavy cover; the code sees none
    assert ev["compared"] and ev["shadow_share"]["differs"] is True and ev["canopy_share"]["differs"] is True
    shoulder = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="FOUND", value=True)
    assert C.occlusion_effect([shoulder], clear) == [shoulder]                  # the model's 0.9 neither lowered anything...
    heavy = C.shares(png(np.where(scene() == 0, 0, (40, 120, 40)).astype(float)), edges())
    assert C.compare_model_shares(heavy, 0.0, 0.0)["canopy_share"]["differs"] is True
    assert C.occlusion_effect([shoulder], heavy)[0].outcome == "UNKNOWN"        # ...and the model's 0.0 did not stop the code's finding


def test_no_effect_function_can_take_the_models_numbers():
    for fn in (C.occlusion_effect, C.shares, C.lane_lines, C.osm_offset):
        names = set(inspect.signature(fn).parameters)
        assert not {"model_shadow", "model_canopy", "shadow_share", "canopy_share", "observations"} & names, fn.__name__
    src = inspect.getsource(C.occlusion_effect)
    assert "model_shadow" not in src and "model_canopy" not in src and "shadow_share" not in src


# ---------------------------------------------------------------- image to OSM offset
MPP = 0.5


def ref(north_m): return ((-100.0, north_m), (100.0, north_m))              # an east-west OSM way `north_m` north of the work point


def test_a_road_centre_on_the_osm_way_has_no_offset():
    r = C.osm_offset(edges(), (W, H), MPP, ref(0.0))
    assert r.ran and r.ok and r.data["mean_offset_m"] < 0.6


def test_the_offset_is_measured_in_metres_with_north_up():
    r = C.osm_offset(edges(), (W, H), MPP, ref(5.0))                            # road centre is at the work point row 200: the way is 5 m north
    assert abs(r.data["mean_offset_m"] - 5.0) < 0.6 and r.ok is True
    far = C.osm_offset(edges(), (W, H), MPP, ref(20.0))
    assert far.ok is False and 19 < far.data["mean_offset_m"] < 21 and "limit 10" in far.evidence


def test_the_limit_is_config_and_calibration_pending():
    cfg = load_site_config()
    assert setting("code_checks", "max_osm_offset_m", cfg) == (10, ("CALIBRATION_PENDING",))
    cfg["code_checks"]["max_osm_offset_m"]["value"] = 30
    assert C.osm_offset(edges(), (W, H), MPP, ref(20.0), cfg).ok is True


def test_no_pair_or_no_way_means_the_check_does_not_run():
    assert C.osm_offset((), (W, H), MPP, ref(0.0)).ran is False and C.osm_offset(edges(), (W, H), MPP, ()).ran is False


def test_all_code_check_numbers_are_calibration_pending_config():
    cfg = load_site_config()
    for k, v in cfg["code_checks"].items():
        if k != "note": assert v["source"] == "CALIBRATION_PENDING", k
