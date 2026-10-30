"""Bearing cross-check and the "which road?" question (S6 commit 4, owner plan 2026-10-31).

The AI draws its marks on the road it chose; the nearest OSM way is the road the data knows. The two must run the same way:
the bearing of the marks (code, from the edge marks, else the lane lines, modulo 180) is compared with the bearing of the OSM
way within `bearing.tolerance_deg` (config, CALIBRATION_PENDING).

  AGREE        within the tolerance
  MISMATCH     beyond it: every road-specific fact becomes UNKNOWN with reason wrong_road_suspected (AI values kept as candidates),
               plus the one WHICH_ROAD question (`block_road_specific`; ROAD_SPECIFIC and SCENE classify the 18 fields)
  WHICH_ROAD   several OSM ways (service ways excluded) lie within `bearing.which_road_distance_m` and their bearings differ by
               more than the tolerance: the road of the job is not clear. The marks decide only when exactly one candidate matches
               them; otherwise the SME is asked which road (the road-specific facts then wait for the answer)
  NO_MARKS     the marks give no bearing: nothing to compare
  NO_ROAD      no OSM way within the configured distance: nothing to compare (the edge rule handles "no road near")

The check can only lower trust: it never creates a value, and it is never a second source.
"""
from typing import NamedTuple, Optional

from tcp_planner.data_sources.osm import axis_diff_deg
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Question, SiteFact, question_id
from tcp_planner.site_model.measure import EdgeFailure, _axis, edge_pair
from tcp_planner.site_model.osm_rules import rank_ways
from tcp_planner.site_model.site_config import load_site_config, setting

AGREE, MISMATCH, WHICH_ROAD, NO_MARKS, NO_ROAD = "AGREE", "MISMATCH", "WHICH_ROAD", "NO_MARKS", "NO_ROAD"


class BearingCheck(NamedTuple):
    status: str
    mark_bearing: Optional[float]       # modulo 180, compass
    way_id: Optional[int]
    way_bearing: Optional[float]
    diff_deg: Optional[float]
    tolerance_deg: float
    questions: tuple
    flags: tuple                        # CALIBRATION_PENDING while the tolerance is not calibrated
    evidence: str

    @property
    def widths_ok(self):
        return self.status not in (MISMATCH, WHICH_ROAD)


def mark_bearing(marks):
    """(bearing modulo 180 in compass degrees, 'edges' or 'lane_lines') from the marks, or (None, reason). Edge marks first: the
    pair's own axis. Without a usable pair, the axis of the lane-line points."""
    a, b = L.usable(marks, "road_edge_left"), L.usable(marks, "road_edge_right")
    if len(a) == 1 and len(b) == 1:
        p = edge_pair(a[0].points, b[0].points)
        if not isinstance(p, EdgeFailure): return p.axis_bearing_deg, "edges"
    lines = [pt for m in L.usable(marks, "lane_line") for pt in m.points]
    if len(lines) >= 2:
        u = _axis(lines)
        if u is not None:
            from tcp_planner.site_model.measure import _bearing
            return _bearing(*u) % 180.0, "lane_lines"
    return None, "no usable edge or lane-line marks"


def _fmt(b): return "-" if b is None else f"{b:.0f}"


def check_bearing(marks, ways, point=(0.0, 0.0), cfg=None):
    """BearingCheck of the marks against the OSM ways near the work point (local frame, metres)."""
    cfg = cfg or load_site_config()
    tol, flags = setting("bearing", "tolerance_deg", cfg)
    near, _ = setting("bearing", "which_road_distance_m", cfg)
    ranked = rank_ways(ways, point, cfg)
    mb, how = mark_bearing(marks)
    if not ranked:
        return BearingCheck(NO_ROAD, mb, None, None, None, tol, (), flags, "no OSM road within the configured distance of the work point")
    cands = [c for c in ranked if c.way.tags.get("highway") != "service" and c.distance_m <= near] or ranked[:1]
    bearings = [c.bearing_deg % 180 for c in cands]
    ambiguous = any(axis_diff_deg(x, y) > tol for i, x in enumerate(bearings) for y in bearings[i + 1:])

    def which_road(reason):
        opts = tuple(f"way {c.way.id} {c.way.tags.get('name') or c.way.tags.get('ref') or ''} bearing {c.bearing_deg % 180:.0f}".replace("  ", " ")
                     for c in cands)
        q = Question(question_id=question_id("WHICH_ROAD", "road", *[c.way.id for c in cands]), kind="WHICH_ROAD", reason=reason, options=opts,
                     field="road", osm_way_id=cands[0].way.id, reveals=("road",),
                     context={"ways": [{"id": c.way.id, "name": c.way.tags.get("name"), "bearing": round(c.bearing_deg % 180, 1),
                                        "distance_m": round(c.distance_m, 1)} for c in cands], "mark_bearing": mb, "tolerance_deg": tol})
        return q

    if ambiguous:
        if mb is None:
            q = which_road("several roads with different directions are near the work point and the marks give no direction")
            return BearingCheck(WHICH_ROAD, None, None, None, None, tol, (q,), flags, "several roads near; no mark bearing to choose one")
        match = [c for c in cands if axis_diff_deg(mb, c.bearing_deg) <= tol]
        if len(match) == 1:
            c = match[0]; d = axis_diff_deg(mb, c.bearing_deg)
            return BearingCheck(AGREE, mb, c.way.id, c.bearing_deg % 180, d, tol, (), flags,
                                f"several roads near; the marks ({_fmt(mb)} deg, {how}) match only way {c.way.id} ({_fmt(c.bearing_deg % 180)} deg)")
        q = which_road("several roads with different directions are near the work point and the marks do not single one out")
        return BearingCheck(WHICH_ROAD, mb, None, None, None, tol, (q,), flags, f"several roads near; {len(match)} match the marks ({_fmt(mb)} deg)")
    c = ranked[0] if ranked[0] in cands else cands[0]
    wb = c.bearing_deg % 180
    if mb is None:
        return BearingCheck(NO_MARKS, None, c.way.id, wb, None, tol, (), flags, f"no mark bearing ({how}); way {c.way.id} runs {_fmt(wb)} deg")
    d = axis_diff_deg(mb, wb)
    if d <= tol:
        return BearingCheck(AGREE, mb, c.way.id, wb, d, tol, (), flags, f"marks {_fmt(mb)} deg ({how}), way {c.way.id} {_fmt(wb)} deg, difference {d:.0f} deg")
    name = c.way.tags.get("name") or c.way.tags.get("ref") or ""
    q = Question(question_id=question_id("WHICH_ROAD", "road", c.way.id), kind="WHICH_ROAD", field="road", osm_way_id=c.way.id,
                 reason=(f"the marks run {_fmt(mb)} degrees but the nearest OSM road (way {c.way.id}) runs {_fmt(wb)} degrees: the AI may have marked "
                         "another road. Which road is the work on?"),
                 options=(f"way {c.way.id} {name} bearing {_fmt(wb)}".replace("  ", " "), f"the road the AI marked (bearing {_fmt(mb)})"),
                 reveals=("road",), context={"mark_bearing": round(mb, 1), "way_bearing": round(wb, 1), "diff_deg": round(d, 1), "tolerance_deg": tol,
                                             "marks_from": how, "ways": [{"id": c.way.id, "name": c.way.tags.get("name"), "bearing": round(wb, 1),
                                                                          "distance_m": round(c.distance_m, 1)}]})
    return BearingCheck(MISMATCH, mb, c.way.id, wb, d, tol, (q,), flags, f"marks {_fmt(mb)} deg ({how}), way {c.way.id} {_fmt(wb)} deg, difference {d:.0f} deg beyond {tol}")


# Which of the 18 call 1 fields describe THE road (so a wrong road makes them wrong) and which describe the scene at the work point.
# A road-specific fact is read against one road's edges, lanes or sides; a scene fact is something seen at the work location whichever
# road the marks followed. Owner answer to STOP 5, 2026-10-31.
ROAD_SPECIFIC = {
    "work_location": "judged against the edges and lane lines of the marked road",
    "work_side": "the side of the marked road the work is on",
    "lanes_per_direction": "a count for the marked road",
    "oneway": "a property of the marked road",
    "shoulder_present": "next to the marked road's lanes",
    "divided_highway": "a property of the marked road",
    "median_work": "a median of the marked road",
    "bicycle_lane_present": "next to the marked road's lanes",
    "sidewalk_present": "along the marked road",
    "sidewalk_side": "a side of the marked road",
    "parking_present": "along the marked road",
    "approaching_lanes_one": "approaching lanes of the marked road",
}
SCENE = {
    "bus_stop_present": "seen at the work location, not a property of one road",
    "driveway_present": "seen at the work location, not a property of one road",
    "crosswalk_present": "seen at the work location, not a property of one road",
    "intersection_in_view": "seen in the image, not a property of one road",
    "grade_crossing_present": "seen in the image, not a property of one road",
    "obstructions": "what blocks the view, not a property of one road",
}


def is_road_specific(fact):
    """A call 1 field from ROAD_SPECIFIC, or any width computed from marks (unit ft, source CODE or AI_MARKS)."""
    return fact.field in ROAD_SPECIFIC or (fact.unit == "ft" and fact.source in ("CODE", "AI_MARKS"))


def block_road_specific(facts, check):
    """When the check says the marks may follow another road (MISMATCH or WHICH_ROAD), every road-specific fact becomes UNKNOWN with
    reason wrong_road_suspected; the AI's value stays as a candidate for the SME. Scene facts and an OK check pass unchanged. The check's one
    'which road?' question is in `check.questions`."""
    if check.widths_ok: return list(facts)
    from tcp_planner.site_model.facts import Candidate
    out = []
    for f in facts:
        if not is_road_specific(f):
            out.append(f); continue
        cand = f.candidates + ((Candidate(source=f.source, value=f.value, outcome=f.outcome),) if f.value is not None else ())
        out.append(f.model_copy(update={"outcome": "UNKNOWN", "value": None, "interval": None, "reason_code": "wrong_road_suspected", "candidates": cand,
                                        "evidence": f"bearing check {check.status}: {check.evidence}",
                                        "flags": tuple(dict.fromkeys(f.flags + check.flags))}))
    return out
