"""Work-location edge rule (S6 commit 5): within 5 m of the nearest road edge, or no road near, work_location is UNKNOWN plus one question."""
import pytest

from tcp_planner.ai import call1
from tcp_planner.site_model import edge_rule as E
from tcp_planner.site_model.facts import Mark, SiteFact
from tcp_planner.site_model.site_config import load_site_config, setting

MPP = 0.5                       # metres per pixel as sent: 5 m = 10 px


def marks(work_y, left_y=600, right_y=700, with_edges=True, with_work=True):
    """East-west road: edges are horizontal lines at image rows left_y and right_y; the work point is at (640, work_y)."""
    out = []
    if with_edges:
        out += [Mark(feature="road_edge_left", status="RESOLVED", points=((100, left_y), (1200, left_y))),
                Mark(feature="road_edge_right", status="RESOLVED", points=((100, right_y), (1200, right_y)))]
    if with_work: out.append(Mark(feature="work_point", status="RESOLVED", points=((640, work_y),)))
    return tuple(out)


def work_fact(value="IN_LANE", flags=()):
    return SiteFact(field="work_location", registry_id="work_location", source="AI", outcome="FOUND", value=value, confidence=0.95,
                    evidence="paved lane", flags=flags)


def test_the_threshold_is_5_m_from_config_and_calibration_pending():
    cfg = load_site_config()
    assert setting("edge_rule", "near_edge_m", cfg) == (5, ("CALIBRATION_PENDING",))


@pytest.mark.parametrize("work_y", [605, 590, 689, 650, 560])
def test_distance_to_the_nearest_edge(work_y):
    """Edges at rows 600 and 700, 0.5 m per pixel: 10 px is 5 m, and exactly 5 m counts as near."""
    r = E.check_edge(marks(work_y), MPP, True)
    d_px = min(abs(work_y - 600), abs(work_y - 700))
    assert r.status == (E.NEAR_EDGE if d_px * MPP <= 5 else E.CLEAR), (work_y, d_px, r.distance_m)
    assert abs(r.distance_m - d_px * MPP) < 0.05


def test_inside_and_outside_are_both_measured_from_the_nearest_edge():
    inside = E.check_edge(marks(703), MPP, True)               # 3 px from the right edge, outside
    on = E.check_edge(marks(695), MPP, True)                   # 5 px inside
    assert inside.status == on.status == E.NEAR_EDGE and on.inside_edges is True and inside.inside_edges is False


def test_near_edge_turns_work_location_unknown_and_asks_one_question():
    r = E.check_edge(marks(595), MPP, True)
    f, q = E.apply_edge_rule(work_fact(), r)
    assert f.outcome == "UNKNOWN" and f.value is None and f.reason_code == "near_edge" and "CALIBRATION_PENDING" in f.flags
    assert q.kind == "WORK_LOCATION_NEAR_EDGE" and q.field == "work_location" and q.context["threshold_m"] == 5
    assert set(q.options) == {"IN_LANE", "ON_SHOULDER_OR_ENCROACHING", "BEYOND_SHOULDER"} and q.context["distance_m"] <= 5
    assert [c.value for c in f.candidates] == ["IN_LANE"] and "edge rule" in f.evidence      # the AI reading is kept for the SME


def test_clear_of_the_edge_leaves_the_fact_alone():
    r = E.check_edge(marks(650), MPP, True)
    f, q = E.apply_edge_rule(work_fact(), r)
    assert r.status == E.CLEAR and f.outcome == "FOUND" and f.value == "IN_LANE" and q is None


def test_no_road_near_is_unknown_plus_one_question():
    r = E.check_edge(marks(650, with_edges=False), MPP, False)
    assert r.status == E.NO_ROAD
    f, q = E.apply_edge_rule(work_fact("BEYOND_SHOULDER"), r)
    assert f.outcome == "UNKNOWN" and f.reason_code == "no_road_near" and q.kind == "WORK_LOCATION_NEAR_EDGE"


def test_no_edge_marks_but_osm_road_near_does_not_apply_the_rule():
    r = E.check_edge(marks(650, with_edges=False), MPP, True)
    f, q = E.apply_edge_rule(work_fact(), r)
    assert r.status == E.NO_DISTANCE and f.outcome == "FOUND" and q is None


def test_osm_unavailable_and_no_edge_marks_counts_as_no_road():
    assert E.check_edge(marks(650, with_edges=False), MPP, None).status == E.NO_ROAD


def test_edge_marks_without_osm_still_give_a_distance():
    assert E.check_edge(marks(650), MPP, False).status == E.CLEAR


def test_an_already_unknown_fact_is_not_asked_twice():
    unknown = SiteFact(field="work_location", registry_id="work_location", source="AI", outcome="UNKNOWN", reason_code="low_confidence")
    f, q = E.apply_edge_rule(unknown, E.check_edge(marks(595), MPP, True))
    assert f is unknown and q is None


def test_other_fields_are_never_touched():
    other = SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="FOUND", value=True)
    f, q = E.apply_edge_rule(other, E.check_edge(marks(595), MPP, True))
    assert f is other and q is None


def test_the_threshold_follows_config():
    cfg = load_site_config(); cfg["edge_rule"]["near_edge_m"]["value"] = 30
    assert E.check_edge(marks(650), MPP, True, cfg=cfg).status == E.NEAR_EDGE            # 25 m from both edges is now near
    cfg["edge_rule"]["near_edge_m"]["value"] = 1
    assert E.check_edge(marks(595), MPP, True, cfg=cfg).status == E.CLEAR


def test_the_rule_never_creates_a_value_for_a_start_field():
    from tcp_planner.site_model.start_fields import START_FIELDS
    assert "work_location" not in START_FIELDS
