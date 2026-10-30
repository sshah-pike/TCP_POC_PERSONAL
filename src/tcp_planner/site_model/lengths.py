"""Lengths from pixels (S6 commit 3): widths and distances with intervals, and the straddle test against the pack.

Code computes every length (D-64); the AI supplied only pixel positions. Each length keeps how it was computed
(MeasuredLength). A width stays a RESOLVED fact only when no limit of the pack lies inside its interval; otherwise it is
UNKNOWN and a question goes to the SME (D-38, ADR-032). No regulatory value is typed here: the straddle test evaluates the
pack's own conditions. The edge-error values come from config/site_understanding.json and are CALIBRATION_PENDING.
"""
from typing import NamedTuple

from tcp_planner.contracts import FT
from tcp_planner.rules.rule_pack_eval import eval_expr
from tcp_planner.rules.rule_pack_models import All, Cmp, Not
from tcp_planner.rules.rule_pack_models import Status as PackStatus
from tcp_planner.site_model.facts import Interval, MeasuredLength, Question, SiteFact, question_id
from tcp_planner.site_model.measure import EdgeFailure, EdgePair, _axis, _profile, _s_at, edge_pair
from tcp_planner.site_model.site_config import lane_width_plausible_m, measurement_setting

_EDGE_REASON = {"too_few_points": "malformed", "no_overlap": "ambiguous", "no_axis": "malformed"}


def px_to_ft(px, mpp):
    """Pixels of the image as sent -> feet. `mpp` is the metres per pixel of THAT image (mpp_sent), not of the source."""
    return px * mpp / FT


def m_to_ft(m):
    return m / FT


ERROR_SETTING = {"CROSS_SECTION": "edge_pixel_error_px_cross_section", "AI_MARKS": "edge_pixel_error_px_ai_marks"}


def interval_ft(value_ft, spread_ft, mpp, cfg=None, method="AI_MARKS"):
    """(Interval, edge pixel error, flags): value +/- (edge error x mpp x edges) plus the section spread (Q9 A). The edge
    error depends on the method (cross-section or AI marks). The values are CALIBRATION_PENDING starting points; their flag
    is returned so it travels with the number."""
    err, flags = measurement_setting(ERROR_SETTING[method], cfg)
    edges, _ = measurement_setting("edges_per_width", cfg)
    half = px_to_ft(edges * err, mpp) + spread_ft
    return Interval(lo=max(0.0, value_ft - half), hi=value_ft + half, unit="ft"), err, flags


# ---------------------------------------------------------------- marks
def usable(marks, feature):
    """Resolved marks of a feature that have at least two points (a polyline)."""
    return [m for m in marks if m.feature == feature and m.status == "RESOLVED" and len(m.points) >= 2]


def why_missing(marks, feature):
    """Fixed reason code for a feature with no usable mark."""
    same = [m for m in marks if m.feature == feature]
    if not same: return "missing"
    bad = any(m.reason_code == "malformed" or (m.status == "RESOLVED" and len(m.points) < 2) for m in same)
    return "malformed" if bad else "not_visible"


def _one(marks, feature):
    """(mark, None) when exactly one usable mark exists, else (None, reason)."""
    found = usable(marks, feature)
    if len(found) == 1: return found[0], None
    return None, ("ambiguous" if found else why_missing(marks, feature))


def _model(name, value_px, spread_px, mpp, method, inputs, calc, cfg):
    value = px_to_ft(value_px, mpp)
    iv, err, flags = interval_ft(value, px_to_ft(spread_px, mpp), mpp, cfg, method)
    return MeasuredLength(name=name, value_ft=value, interval_ft=iv, method=method, mpp=mpp, pixel_error_px=err,
                          inputs=tuple(inputs), calculation=calc, flags=flags)


def traveled_way_width(marks, mpp_sent, cross_section=None, cfg=None):
    """(MeasuredLength, None) or (None, reason). The cross-section (deterministic, from the image) comes first when its
    status is OK; the AI's two road-edge marks come second (D-80). Missing or invalid marks give no width."""
    note = ""
    if cross_section and cross_section.get("status") == "OK" and cross_section.get("width_m") is not None:
        mpp = cross_section["metres_per_pixel"]; spread = cross_section.get("spread_m") or 0.0
        value = m_to_ft(cross_section["width_m"]); iv, err, flags = interval_ft(value, m_to_ft(spread), mpp, cfg, "CROSS_SECTION")
        return MeasuredLength(
            name="traveled_way_width", value_ft=value, interval_ft=iv, method="CROSS_SECTION", mpp=mpp, pixel_error_px=err,
            inputs=(f"cross_section.width_m={cross_section['width_m']}", f"spread_m={spread}", f"mpp={mpp}"),
            calculation="width_ft = width_m / 0.3048; interval = +/- (edge error x mpp x edges) + spread", flags=flags), None
    if cross_section: note = f"cross-section {cross_section.get('status')}: {cross_section.get('reason')}; "
    a, ra = _one(marks, "road_edge_left"); b, rb = _one(marks, "road_edge_right")
    if a is None or b is None: return None, ra or rb
    pair = edge_pair(a.points, b.points)
    if isinstance(pair, EdgeFailure): return None, _EDGE_REASON[pair.reason]
    inputs = (f"road edge marks: {len(a.points)} and {len(b.points)} points", f"width_px={pair.width_px:.3f}",
              f"spread_px={pair.spread_px:.3f}", f"mpp_sent={mpp_sent}")
    return _model("traveled_way_width", pair.width_px, pair.spread_px, mpp_sent, "AI_MARKS", inputs,
                  note + "width_ft = width_px x mpp_sent / 0.3048; the two edges are an unordered pair across the road axis", cfg), None


def shoulder_width(marks, mpp_sent, cfg=None):
    """Distance between the shoulder-edge mark and the nearer road-edge mark, across the road axis."""
    s, rs = _one(marks, "shoulder_edge")
    if s is None: return None, rs
    best = None
    for feat in ("road_edge_left", "road_edge_right"):
        for e in usable(marks, feat):
            p = edge_pair(e.points, s.points)
            if isinstance(p, EdgePair) and (best is None or p.width_px < best.width_px): best = p
    if best is None:
        has_edge = usable(marks, "road_edge_left") or usable(marks, "road_edge_right")
        return None, "ambiguous" if has_edge else "missing"
    inputs = (f"shoulder_edge {len(s.points)} points", f"width_px={best.width_px:.3f}", f"mpp_sent={mpp_sent}")
    return _model("shoulder_width", best.width_px, best.spread_px, mpp_sent, "AI_MARKS", inputs,
                  "width_ft = distance(shoulder edge, nearer road edge) x mpp_sent / 0.3048", cfg), None


def distance_from_edge(marks, mpp_sent, cfg=None):
    """(MeasuredLength, None) or (None, reason). value_ft is SIGNED: positive outside the traveled way, negative when the
    work point lies between the road edges."""
    w = next((m for m in marks if m.feature == "work_point" and m.status == "RESOLVED" and m.points), None)
    if w is None: return None, why_missing(marks, "work_point")
    edges = [m for f in ("road_edge_left", "road_edge_right") for m in usable(marks, f)]
    if not edges: return None, why_missing(marks, "road_edge_left")
    u = _axis([p for e in edges for p in e.points])
    if u is None: return None, "malformed"
    v = (-u[1], u[0]); px, py = w.points[0]
    t = px * u[0] + py * u[1]; s = px * v[0] + py * v[1]
    d = [s - _s_at(_profile(e.points, u, v), t) for e in edges]
    inside = len(d) >= 2 and min(d) < 0 < max(d)
    nearest = min(abs(x) for x in d)
    m = _model("distance_from_edge", nearest, 0.0, mpp_sent, "AI_MARKS",
               (f"work_point ({px:.1f},{py:.1f})", f"{len(edges)} road edge mark(s)", f"nearest_px={nearest:.3f}", f"inside_edges={inside}", f"mpp_sent={mpp_sent}"),
               "distance_ft = perpendicular distance(work point, nearest road edge) x mpp_sent / 0.3048; negative between the edges", cfg)
    return (m.model_copy(update={"value_ft": -m.value_ft}) if inside else m), None


# ---------------------------------------------------------------- straddle test against the pack
def _reads(e):
    if isinstance(e, Cmp): return {e.field}
    if isinstance(e, Not): return _reads(e.not_)
    return set().union(*[_reads(x) for x in (e.all if isinstance(e, All) else e.any)])


def _expressions(pack):
    """(record id, expression) of every condition the pack applies: eligibility conditions, APPLY rules, COMPUTE formula cases."""
    for c in pack.records("eligibility_condition"):
        if c.status == PackStatus.SOURCED and c.expr is not None: yield c.id, c.expr
    for r in pack.records("rule"):
        if r.status == PackStatus.SOURCED and r.role == "APPLY" and r.condition is not None: yield r.id, r.condition
    for f in pack.records("formula"):
        if f.role == "COMPUTE":
            for i, case in enumerate(f.cases):
                if case.when is not None: yield f"{f.id}#{i}", case.when


def thresholds_inside(pack, field, interval, context=None):
    """Ids of pack conditions that read `field` and give a different result at the low end, the middle and the high end of
    the interval. No threshold value is typed here: the pack's own conditions are evaluated (S6 Q9 A). Empty list: no limit
    lies inside the interval."""
    if interval.lo == interval.hi: return []
    pts = (interval.lo, (interval.lo + interval.hi) / 2, interval.hi); ctx = dict(context or {})
    return sorted(rid for rid, expr in _expressions(pack)
                  if field in _reads(expr) and len({eval_expr(expr, {**ctx, field: x}) for x in pts}) > 1)


# ---------------------------------------------------------------- facts
class MeasureResult(NamedTuple):
    facts: tuple          # SiteFact per length: lane, shoulder, median, distance from edge
    questions: tuple
    measured: dict        # name -> MeasuredLength (includes the traveled way width, which is not a registry field)


def length_fact(field, m, reason, pack, context=None):
    """(SiteFact, Question or None). RESOLVED with its interval when no pack limit lies inside it; UNKNOWN with a fixed
    reason otherwise."""
    if m is None:
        return SiteFact(field=field, registry_id=field, unit="ft", source="CODE", status="UNKNOWN", reason_code=reason), None
    base = dict(field=field, registry_id=field, unit="ft", source=m.method, interval=m.interval_ft, measured=m, flags=m.flags)
    hit = thresholds_inside(pack, field, m.interval_ft, context)
    if hit:
        text = (f"{field} is between {m.interval_ft.lo:.2f} and {m.interval_ft.hi:.2f} ft and a rule limit lies inside: "
                + ", ".join(hit))
        q = Question(question_id=question_id("WIDTH_NEAR_THRESHOLD", field), kind="WIDTH_NEAR_THRESHOLD", reason=text,
                     options=(), reveals=(field,))
        return SiteFact(**base, status="UNKNOWN", reason_code="threshold_in_interval"), q
    return SiteFact(**base, value=m.value_ft, status="RESOLVED"), None


def lane_spacing(marks, mpp_sent, cfg=None):
    """(MeasuredLength, None), (None, reason), or (None, None) when fewer than two lane-line marks exist. Lane width as the
    spacing between adjacent lane lines (median of the gaps), measured across the road axis like the edges."""
    lines = usable(marks, "lane_line")
    if len(lines) < 2: return None, None
    u = _axis([p for m in lines for p in m.points])
    if u is None: return None, "malformed"
    v = (-u[1], u[0])
    order = sorted(lines, key=lambda m: sum(p[0] * v[0] + p[1] * v[1] for p in m.points) / len(m.points))
    pairs = [edge_pair(x.points, y.points) for x, y in zip(order, order[1:])]
    if any(isinstance(p, EdgeFailure) for p in pairs): return None, "ambiguous"
    widths = sorted(p.width_px for p in pairs)
    mid = widths[len(widths) // 2] if len(widths) % 2 else (widths[len(widths) // 2 - 1] + widths[len(widths) // 2]) / 2
    spread = max(max(widths) - min(widths), max(p.spread_px for p in pairs))
    inputs = (f"{len(lines)} lane line marks", f"gaps_px={[round(w, 3) for w in widths]}", f"mpp_sent={mpp_sent}")
    return _model("lane_width", mid, spread, mpp_sent, "AI_MARKS", inputs,
                  "lane_width_ft = median gap between adjacent lane lines x mpp_sent / 0.3048", cfg), None


def gate_from(observations):
    """The two AI readings the lane width gate may use: {"parking_present": bool|None, "shoulder_present": bool|None}, None
    unless RESOLVED. A plain dict of values: no SiteFact is made from it and nothing here reaches rule_inputs. After OSM
    fusion the caller may pass the fused value instead."""
    return {k: (observations[k].value if observations[k].status == "RESOLVED" else None) for k in ("parking_present", "shoulder_present")}


def _lane_question(reason):
    return Question(question_id=question_id("FACT_UNKNOWN", "lane_width_ft"), kind="FACT_UNKNOWN", reason=reason,
                    options=(), reveals=("lane_width_ft",))


def lane_width(marks, tw, total_lanes, gate, mpp_sent, cfg=None):
    """(MeasuredLength or None, reason or None, Question or None). Order (S6 STOP 2, point 3):
    1. two or more lane-line marks: their spacing; 2. no parking and no shoulder inside the edges (both read false) and a lane
    count: traveled way / total lanes; 3. otherwise UNKNOWN with a question."""
    gate = gate or {}
    lines, why = lane_spacing(marks, mpp_sent, cfg)
    lo, hi = lane_width_plausible_m()
    if lines is not None:
        if lo <= lines.value_ft * FT <= hi: return lines, None, None
        return None, "ambiguous", _lane_question("the lane-line spacing is not a plausible lane width; enter the lane width")
    if why is not None: return None, why, _lane_question("the lane lines could not be measured; enter the lane width")
    if tw is None: return None, None, _lane_question("the road edges could not be measured; enter the lane width")
    if gate.get("parking_present") is not False or gate.get("shoulder_present") is not False:
        return None, "ambiguous", _lane_question(
            "parking or a shoulder may lie between the road edges (read: parking_present=%s, shoulder_present=%s), so the traveled way "
            "cannot be divided into lanes; enter the lane width" % (gate.get("parking_present"), gate.get("shoulder_present")))
    if not isinstance(total_lanes, int) or isinstance(total_lanes, bool) or total_lanes < 1:
        return None, "missing", _lane_question("the lane count is not decided, so the traveled way cannot be divided; enter the lane width")
    per_lane = tw.value_ft / total_lanes
    if not lo <= per_lane * FT <= hi: return None, "ambiguous", _lane_question("the divided width is not a plausible lane width; enter the lane width")
    iv = Interval(lo=tw.interval_ft.lo / total_lanes, hi=tw.interval_ft.hi / total_lanes, unit="ft")
    notes = (f"total_lanes={total_lanes}", "parking_present=False and shoulder_present=False (AI reading, measurement gate only)")
    return tw.model_copy(update={"name": "lane_width", "value_ft": per_lane, "interval_ft": iv, "inputs": tw.inputs + notes,
                                 "calculation": "lane_width_ft = traveled_way_width_ft / total_lanes; the interval is divided the same way"}), None, None


def measure_lengths(marks, mpp_sent, pack, *, total_lanes=None, gate=None, cross_section=None, context=None, cfg=None):
    """Code-computed lengths from marks and the optional cross-section. Never writes a start field; never reads a length from
    the AI. `total_lanes` (both directions) comes from the lane facts once decided; `gate` is gate_from(observations)."""
    facts, questions, measured = [], [], {}

    def add(field, m, reason):
        if m is not None: measured[m.name] = m
        f, q = length_fact(field, m, reason, pack, context)
        facts.append(f)
        if q: questions.append(q)

    tw, reason = traveled_way_width(marks, mpp_sent, cross_section, cfg)
    if tw is not None: measured[tw.name] = tw
    lane, lreason, lq = lane_width(marks, tw, total_lanes, gate, mpp_sent, cfg)
    if lq: questions.append(lq)
    add("lane_width_ft", lane, lreason or reason)
    sw, rsw = shoulder_width(marks, mpp_sent, cfg); add("shoulder_width_ft", sw, rsw)
    facts.append(SiteFact(field="median_width_ft", registry_id="median_width_ft", unit="ft", source="CODE", status="UNKNOWN",
                          reason_code="no_source"))        # call 1 has no median mark: nothing to measure
    de, rde = distance_from_edge(marks, mpp_sent, cfg)
    if de is not None and de.value_ft < 0:                 # between the road edges: work_location decides, not this distance
        measured[de.name] = de
        facts.append(SiteFact(field="distance_from_edge_ft", registry_id="distance_from_edge_ft", unit="ft", source="AI_MARKS",
                              status="UNKNOWN", reason_code="ambiguous", measured=de, flags=de.flags))
    else: add("distance_from_edge_ft", de, rde)
    return MeasureResult(tuple(facts), tuple(questions), measured)
