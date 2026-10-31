"""Work-location edge rule (S6 commit 5, owner plan 2026-10-31).

Within `edge_rule.near_edge_m` of the nearest road edge, or with no road near, `work_location` is UNKNOWN plus one SME question.
The distance is computed in code from the AI's edge and work-point marks (D-64; the AI never gives a length). The rule only
lowers trust: it can turn a value into UNKNOWN and never creates one. 5 m is CALIBRATION_PENDING in config.

  NEAR_EDGE   the work point is within the configured distance of the nearest road edge (on either side, inside or outside)
  NO_ROAD     no road near: no OSM way within `edge_rule.no_road_near_m` (see `road_near`) and no usable road-edge marks. The question
              is a question CANDIDATE (informational unless S7's what-if test makes it blocking), pre-filled with the AI value.
              With a road within that distance and clear of the edge, an answer such as BEYOND_SHOULDER is FOUND.
  CLEAR       far enough from the nearest edge
  NO_DISTANCE a road is known but the marks give no distance (no work point or no edge marks): the rule does not apply, and the
              work_location fact keeps its own marks check
"""
from typing import NamedTuple, Optional

from tcp_planner.contracts import FT
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.facts import Candidate, Question, SiteFact, question_id
from tcp_planner.site_model.site_config import load_site_config, setting

NEAR_EDGE, NO_ROAD, CLEAR, NO_DISTANCE = "NEAR_EDGE", "NO_ROAD", "CLEAR", "NO_DISTANCE"


class EdgeRuleResult(NamedTuple):
    status: str
    distance_m: Optional[float]         # to the nearest road edge, unsigned
    inside_edges: Optional[bool]
    threshold_m: float
    question: Optional[Question]
    flags: tuple                        # CALIBRATION_PENDING while the distance is not calibrated
    evidence: str

    @property
    def lowers_trust(self):
        return self.status in (NEAR_EDGE, NO_ROAD)


def edge_distance_m(marks, mpp_sent, cfg=None):
    """(distance in metres to the nearest road edge, inside_edges) or (None, reason). Same geometry as the distance-from-edge fact."""
    m, why = L.distance_from_edge(marks, mpp_sent, cfg)
    if m is None: return None, why
    return abs(m.value_ft) * FT, m.value_ft < 0


def road_near(ways, point=(0.0, 0.0), cfg=None):
    """True when an OSM way (any class, service included: a road is a road) lies within `edge_rule.no_road_near_m` of the work point,
    False when none does. Pass the result as `osm_road_near`; pass None when OSM was not consulted or failed."""
    from tcp_planner.data_sources.osm import point_to_polyline
    limit, _ = setting("edge_rule", "no_road_near_m", cfg or load_site_config())
    return any(point_to_polyline(point, w.points)[0] <= limit for w in ways)


def check_edge(marks, mpp_sent, osm_road_near, cfg=None):
    """EdgeRuleResult. `osm_road_near`: True when an OSM way lies within the configured distance of the work point, False when none does,
    None when OSM was not consulted or failed (then only the edge marks can show a road)."""
    cfg = cfg or load_site_config()
    limit, flags = setting("edge_rule", "near_edge_m", cfg)
    dist, inside = edge_distance_m(marks, mpp_sent, cfg)
    has_edges = dist is not None

    def ask(kind_reason, status, ctx, candidate=False):
        q = Question(question_id=question_id("WORK_LOCATION_NEAR_EDGE", "work_location", status), kind="WORK_LOCATION_NEAR_EDGE",
                     reason=kind_reason, options=("IN_LANE", "ON_SHOULDER_OR_ENCROACHING", "BEYOND_SHOULDER"), field="work_location",
                     reveals=("work_location",), candidate=candidate,
                     context={**ctx, "threshold_m": limit, "no_road_near_m": setting("edge_rule", "no_road_near_m", cfg)[0]})
        return q
    if not has_edges and osm_road_near is not True:
        why = "no OSM road near the work point and no road edges marked" if osm_road_near is False else "no road edges marked and OSM gave no road"
        q = ask("no road is near the work point, so the work location cannot be read from the image: where is the work?", NO_ROAD, {}, candidate=True)
        return EdgeRuleResult(NO_ROAD, None, None, limit, q, flags, why)
    if not has_edges:
        return EdgeRuleResult(NO_DISTANCE, None, None, limit, None, flags, f"road known from OSM; no edge distance from the marks ({inside})")
    if dist <= limit:
        q = ask(f"the work point is {dist:.1f} m from the nearest road edge (within {limit} m): is the work in the lane, on the shoulder or beyond it?",
                NEAR_EDGE, {"distance_m": round(dist, 2), "inside_edges": inside})
        return EdgeRuleResult(NEAR_EDGE, dist, inside, limit, q, flags, f"{dist:.2f} m from the nearest road edge, within {limit} m")
    return EdgeRuleResult(CLEAR, dist, inside, limit, None, flags, f"{dist:.2f} m from the nearest road edge, beyond {limit} m")


def apply_edge_rule(fact, result):
    """(fact, question or None). When the rule lowers trust, the work_location fact becomes UNKNOWN (reason near_edge or no_road_near);
    the AI's reading stays as a candidate for the SME. A fact that is already UNKNOWN keeps its own reason; the question is still asked
    only when the fact would otherwise have a value."""
    if fact.field != "work_location" or not result.lowers_trust: return fact, None
    if fact.outcome == "UNKNOWN": return fact, None
    cand = fact.candidates + (Candidate(source="AI", value=fact.value, outcome=fact.outcome),)
    reason = "near_edge" if result.status == NEAR_EDGE else "no_road_near"
    q = result.question if result.question is None or not result.question.candidate else result.question.model_copy(update={"suggested": fact.value})
    return fact.model_copy(update={"outcome": "UNKNOWN", "value": None, "reason_code": reason, "candidates": cand,
                                   "flags": tuple(dict.fromkeys(fact.flags + result.flags)),
                                   "evidence": (fact.evidence + " | " if fact.evidence else "") + f"edge rule: {result.evidence}"}), q
