"""Code snapping of the AI's marks to the nearest real edge (S6 step 8): synthetic images, no network."""
import io

import numpy as np
import pytest
from PIL import Image

from tcp_planner.imagery import snap as S
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Mark
from tcp_planner.site_model.site_config import load_site_config, setting

W = H = 400


def png(arr):
    buf = io.BytesIO(); Image.fromarray(arr.astype(np.uint8), "L").save(buf, "PNG"); return buf.getvalue()


def road_image(top=150, bottom=250, road=60, ground=180, x_from=0, x_to=W):
    """East-west road: dark band between rows top and bottom over a light ground."""
    a = np.full((H, W), ground, dtype=float)
    a[top:bottom, x_from:x_to] = road
    return a


def mark(feature, y0, y1=None, x0=40, x1=360):
    return Mark(feature=feature, status="RESOLVED", points=((x0, y0), (x1, y1 if y1 is not None else y0)))


def snapped(image, m, cfg=None):
    r = S.snap_marks(png(image), (m,), cfg)
    return r.marks[0], r


def ys(m): return [p[1] for p in m.points]


# ---------------------------------------------------------------- snapping
def test_a_mark_a_few_pixels_off_snaps_onto_the_edge_and_keeps_the_ai_points():
    m, r = snapped(road_image(), mark("road_edge_left", 155))             # the true edge is at row 150
    assert m.status == "RESOLVED" and all(abs(y - 150) <= 1.0 for y in ys(m))
    assert m.original_points == ((40, 155), (360, 155)) and m.snap["rejected"] is False and m.snap["accepted_fraction"] == 1.0
    assert 3.5 <= m.snap["mean_shift_px"] <= 6 and any("snapped" in n for n in r.notes)
    m2, _ = snapped(road_image(), mark("road_edge_right", 244))           # true edge at row 250
    assert all(abs(y - 250) <= 1.0 for y in ys(m2))


def test_a_mark_already_on_the_edge_barely_moves():
    m, _ = snapped(road_image(), mark("road_edge_left", 150))
    assert m.snap["max_shift_px"] <= 1.0


def test_a_diagonal_edge_is_followed():
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.where(yy > 0.5 * xx + 100, 60.0, 180.0)                         # edge line y = 0.5 x + 100
    m, _ = snapped(a, Mark(feature="road_edge_left", status="RESOLVED", points=((40, 126 - 5), (360, 286 - 5))))
    assert m.status == "RESOLVED"
    for (x, y) in m.points:
        assert abs(y - (0.5 * x + 100)) <= 1.5, (x, y)


def test_the_nearest_real_edge_wins_not_the_strongest():
    a = road_image(top=150, bottom=250, road=60, ground=180)
    a[147:150, :] = 150                                                    # a weak step (30 grey levels) 3 px above the road edge...
    a[100:150, :][:, :] = np.where(a[100:150, :] == 180, 180, a[100:150, :])
    m, _ = snapped(a, mark("road_edge_left", 144))                         # AI line 6 px above; weak step at 147, road edge at 150
    assert m.status == "RESOLVED" and all(abs(y - 147) <= 1.5 for y in ys(m))


def test_an_edge_below_the_contrast_threshold_is_not_an_edge():
    thr = setting("snapping", "min_edge_contrast", load_site_config())[0]
    m, r = snapped(road_image(road=180 - (thr - 6)), mark("road_edge_left", 152))
    assert m.status == "UNKNOWN" and m.reason_code == "no_edge_nearby" and m.points == () and m.original_points
    assert any("rejected" in n for n in r.notes)
    ok, _ = snapped(road_image(road=180 - (thr + 6)), mark("road_edge_left", 152))
    assert ok.status == "RESOLVED"


def test_a_mark_with_no_edge_nearby_is_rejected_not_guessed():
    blank = np.full((H, W), 128.0)
    m, _ = snapped(blank, mark("road_edge_left", 150))
    assert m.status == "UNKNOWN" and m.reason_code == "no_edge_nearby" and m.snap["rejected"] is True and m.snap["accepted_fraction"] == 0.0


def test_an_edge_beyond_the_search_radius_is_not_found():
    radius = setting("snapping", "search_radius_px", load_site_config())[0]
    m, _ = snapped(road_image(), mark("road_edge_left", 150 - radius - 6))
    assert m.status == "UNKNOWN" and m.reason_code == "no_edge_nearby"
    near, _ = snapped(road_image(), mark("road_edge_left", 150 - radius + 3))
    assert near.status == "RESOLVED"


def test_a_mark_whose_edge_exists_over_only_part_of_its_length_follows_the_accept_fraction():
    img = road_image(x_from=0, x_to=W // 2)                                # the edge exists on the left half only
    m, _ = snapped(img, mark("road_edge_left", 153))
    assert m.status == "UNKNOWN" and 0.3 < m.snap["accepted_fraction"] < 0.6
    cfg = load_site_config(); cfg["snapping"]["min_accepted_fraction"]["value"] = 0.4
    m2, _ = snapped(img, mark("road_edge_left", 153), cfg)
    assert m2.status == "RESOLVED"


def test_one_stray_edge_does_not_kink_the_line():
    a = road_image()
    a[140:150, 195:205] = 20                                               # a dark blob just above the edge, mid-line
    m, _ = snapped(a, mark("road_edge_left", 152))
    assert max(abs(y - 150) for y in ys(m)) <= 1.5


def test_lane_lines_the_work_point_and_unknown_marks_pass_unchanged():
    img = png(road_image())
    keep = (Mark(feature="lane_line", status="RESOLVED", points=((40, 200), (360, 200))),
            Mark(feature="work_point", status="RESOLVED", points=((200, 200),)),
            Mark(feature="road_edge_left", status="UNKNOWN", reason_code="not_stated"),
            Mark(feature="road_edge_right", status="RESOLVED", points=((10, 10),)))
    assert S.snap_marks(img, keep).marks == keep


def test_the_values_are_config_calibration_pending_and_nothing_is_typed():
    cfg = load_site_config()
    for k in ("features", "search_radius_px", "sample_step_px", "min_edge_contrast", "min_accepted_fraction", "smooth_window"):
        assert cfg["snapping"][k]["source"] == "CALIBRATION_PENDING", k
    assert S.snap_marks(png(road_image()), (mark("road_edge_left", 155),)).flags == ("CALIBRATION_PENDING",)
    cfg["snapping"]["features"]["value"] = ["curb"]
    m = mark("road_edge_left", 155)
    assert S.snap_marks(png(road_image()), (m,), cfg).marks == (m,)
    src = open(S.__file__, encoding="utf-8").read()
    for name in ("search_radius_px", "min_edge_contrast", "min_accepted_fraction", "sample_step_px", "smooth_window"):
        assert f'setting("snapping", "{name}"' in src


def test_snapping_reads_pixels_only_never_a_length():
    import inspect
    assert list(inspect.signature(S.snap_marks).parameters) == ["image_bytes", "marks", "cfg"]          # no scale, no feet


def test_a_snapped_pair_gives_the_true_width_and_a_rough_ai_pair_does_not():
    mpp = 0.5
    rough = (mark("road_edge_left", 156), mark("road_edge_right", 243))                      # AI lines 6 and 7 px inside the true edges
    r = S.snap_marks(png(road_image()), rough)
    tw_rough, _ = L.traveled_way_width(rough, mpp)
    tw_snap, _ = L.traveled_way_width(r.marks, mpp)
    true_ft = 100 * mpp / 0.3048
    assert abs(tw_snap.value_ft - true_ft) < 1.0 and abs(tw_rough.value_ft - true_ft) > 4.0
