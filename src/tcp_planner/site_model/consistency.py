"""Config-driven consistency checks between facts (S6 step 9, owner plan 2026-10-31 with review changes R5).

Each check reads AI observations (the values as the model gave them, before fusion), the marks and the code check results, and can only
LOWER trust: a fact becomes UNKNOWN (reason check_failed, the AI value kept as a candidate) or gets the review flag CODE_CHECK_LOWERED.
No check raises a value or confirms one, and none is a second source. Each one has its switch in config `consistency` (and the stage
`consistency`); every result is returned as a `CheckResult` for the run trace.

  lane_count_vs_width        RUNS ONLY WHEN parking_present and shoulder_present are both read false (R5): then the traveled way divided
                             by the total lanes must be a plausible lane width (pipeline_config fusion.lane_width_plausible_m). If not,
                             lanes_per_direction is UNKNOWN plus a LANES_DISAGREE question candidate.
  lane_lines_vs_lane_count   painted interior lines + 1 against the total lanes. A mismatch flags lanes_per_direction CODE_CHECK_LOWERED.
                             With no painted line detected the check does nothing (R5): worn or missing paint is not evidence.
  approaching_lanes_vs_lane_count   approaching_lanes_one against the lanes that approach the work (a contradiction makes both UNKNOWN).
  sidewalk_pair              sidewalk_present against sidewalk_side (a contradiction makes both UNKNOWN).
  work_location_vs_edges     the marks check: ROADWAY needs the work point between the edge marks; SHOULDER or BEYOND_SHOULDER needs it
                             outside. Used by `map_work_location` as AGREE, MISSING or DISAGREE.
"""
from typing import NamedTuple

from tcp_planner.contracts import FT
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model.code_checks import CheckResult
from tcp_planner.site_model.facts import Candidate, Question, question_id
from tcp_planner.site_model.site_config import lane_width_plausible_m, load_site_config, setting

AGREE, MISSING, DISAGREE = "AGREE", "MISSING", "DISAGREE"


class ConsistencyResult(NamedTuple):
    facts: tuple
    questions: tuple
    results: tuple              # CheckResult per check, in order


def _flags(cfg):
    return setting("consistency", "lane_count_vs_width", cfg)[1]


def _val(observations, name):
    o = observations.get(name)
    return o.value if o is not None and o.status == "RESOLVED" else None


def total_lanes(observations):
    """Total lanes across the road from the AI's own readings: lanes_per_direction (x2 on a two-way road) or the one-way lane count; None unless both are read."""
    lanes, ow = _val(observations, "lanes_per_direction"), _val(observations, "oneway")
    if not isinstance(lanes, int) or isinstance(lanes, bool) or not isinstance(ow, bool): return None
    return lanes if ow else 2 * lanes


def effective_lanes(observations):
    """Lanes that approach the work: lanes_per_direction on a two-way road, all lanes on a one-way road."""
    lanes, ow = _val(observations, "lanes_per_direction"), _val(observations, "oneway")
    if not isinstance(lanes, int) or isinstance(lanes, bool) or not isinstance(ow, bool): return None
    return lanes


def _lower_unknown(fact, evidence, flags):
    cand = fact.candidates + ((Candidate(source=fact.source, value=fact.value, outcome=fact.outcome),) if fact.value is not None else ())
    return fact.model_copy(update={"outcome": "UNKNOWN", "value": None, "interval": None, "reason_code": "check_failed", "candidates": cand,
                                   "flags": tuple(dict.fromkeys(tuple(x for x in fact.flags if x != "NEEDS_SECOND_SOURCE") + flags)), "evidence": evidence})


def _by(facts): return {f.field: f for f in facts}


def work_marks_check(marks, ai_value):
    """AGREE, MISSING or DISAGREE for map_work_location: where the work point lies against the edge marks, compared with the AI's reading."""
    if ai_value not in ("ROADWAY", "SHOULDER", "BEYOND_SHOULDER"): return MISSING
    m, why = L.distance_from_edge(marks, 1.0)
    if m is None: return MISSING
    inside = m.value_ft < 0
    if ai_value == "ROADWAY": return AGREE if inside else DISAGREE
    return AGREE if not inside else DISAGREE


def lane_count_vs_width(facts, observations, tw, cfg):
    name, flags = "lane_count_vs_width", _flags(cfg)
    gate = {k: _val(observations, k) for k in ("parking_present", "shoulder_present")}
    if gate.get("parking_present") is not False or gate.get("shoulder_present") is not False:
        return list(facts), (), CheckResult(name, False, None, "parking or shoulder not both read false: the traveled way is not only lanes, so the check does not run", {}, flags)
    tot = total_lanes(observations)
    if tw is None or tot is None or tot < 1:
        return list(facts), (), CheckResult(name, False, None, "no traveled way width or no lane count to compare", {}, flags)
    per_lane = tw.value_ft * FT / tot
    lo, hi = lane_width_plausible_m()
    data = {"per_lane_m": round(per_lane, 2), "total_lanes": tot, "range_m": [lo, hi]}
    if lo <= per_lane <= hi:
        return list(facts), (), CheckResult(name, True, True, f"{per_lane:.2f} m per lane over {tot} lanes is a plausible lane width", data, flags)
    ev = f"{per_lane:.2f} m per lane over {tot} lanes is outside the plausible {lo} to {hi} m"
    f = _by(facts).get("lanes_per_direction")
    qs = ()
    if f is not None and f.outcome != "UNKNOWN":
        new = _lower_unknown(f, f"code check: {ev}", flags)
        facts = [new if x.field == "lanes_per_direction" else x for x in facts]
        qs = (Question(question_id=question_id("LANES_DISAGREE", "lanes_per_direction", "width"), kind="LANES_DISAGREE", field="lanes_per_direction",
                       reveals=("lanes_per_direction",), candidate=True, suggested=f.value, reason=f"lanes_per_direction: the image reads {f.value!r}, but {ev}. Confirm or correct.",
                       context=data),)
    return list(facts), qs, CheckResult(name, True, False, ev, data, flags)


def lane_lines_vs_lane_count(facts, observations, line_result, cfg):
    name, flags = "lane_lines_vs_lane_count", setting("consistency", "lane_lines_vs_lane_count", cfg)[1]
    if not line_result.ran:
        return list(facts), CheckResult(name, False, None, f"no judgement: {line_result.evidence}", dict(line_result.data), flags)
    tot = total_lanes(observations)
    if tot is None: return list(facts), CheckResult(name, False, None, "no lane count to compare", dict(line_result.data), flags)
    implied = line_result.data["implied_total_lanes"]
    data = {**line_result.data, "total_lanes": tot}
    if implied == tot: return list(facts), CheckResult(name, True, True, f"{implied} lanes implied by the painted lines, {tot} read", data, flags)
    f = _by(facts).get("lanes_per_direction")
    ev = f"the painted lines imply {implied} lanes, the AI read {tot}"
    if f is not None and f.outcome != "UNKNOWN":
        facts = [f.model_copy(update={"flags": tuple(dict.fromkeys(f.flags + ("CODE_CHECK_LOWERED",) + flags)), "evidence": (f.evidence + " | " if f.evidence else "") + f"code check: {ev}"})
                 if x.field == "lanes_per_direction" else x for x in facts]
    return list(facts), CheckResult(name, True, False, ev, data, flags)


def approaching_lanes_vs_lane_count(facts, observations, cfg):
    name, flags = "approaching_lanes_vs_lane_count", setting("consistency", "approaching_lanes_vs_lane_count", cfg)[1]
    eff, app = effective_lanes(observations), _val(observations, "approaching_lanes_one")
    if eff is None or not isinstance(app, bool): return list(facts), (), CheckResult(name, False, None, "lanes or approaching_lanes_one not both read", {}, flags)
    expect = eff == 1
    if app == expect: return list(facts), (), CheckResult(name, True, True, f"approaching_lanes_one={app} agrees with {eff} lane(s)", {"lanes": eff}, flags)
    ev = f"approaching_lanes_one={app} contradicts lanes_per_direction={eff}"
    by, out, qs = _by(facts), list(facts), []
    for field in ("approaching_lanes_one", "lanes_per_direction"):
        f = by.get(field)
        if f is not None and f.outcome != "UNKNOWN":
            new = _lower_unknown(f, f"code check: {ev}", flags)
            out = [new if x.field == field else x for x in out]
            qs.append(Question(question_id=question_id("FACT_UNKNOWN", field, "approaching"), kind="FACT_UNKNOWN", field=field, reveals=(field,), candidate=True,
                               suggested=f.value, reason=f"{field}: the image reads {f.value!r}, but {ev}. Confirm or correct.", context={"lanes": eff, "approaching_lanes_one": app}))
    return out, tuple(qs), CheckResult(name, True, False, ev, {"lanes": eff, "approaching_lanes_one": app}, flags)


def sidewalk_pair(facts, observations, cfg):
    name, flags = "sidewalk_pair", setting("consistency", "sidewalk_pair", cfg)[1]
    present, side = _val(observations, "sidewalk_present"), _val(observations, "sidewalk_side")
    if not isinstance(present, bool) or not isinstance(side, str): return list(facts), CheckResult(name, False, None, "sidewalk_present or sidewalk_side not read", {}, flags)
    bad = (present is False and side != "NONE") or (present is True and side == "NONE")
    if not bad: return list(facts), CheckResult(name, True, True, f"sidewalk_present={present} agrees with sidewalk_side={side}", {}, flags)
    ev = f"sidewalk_present={present} contradicts sidewalk_side={side}"
    by, out = _by(facts), list(facts)
    for field in ("sidewalk_present", "sidewalk_side"):
        f = by.get(field)
        if f is not None and f.outcome != "UNKNOWN": out = [_lower_unknown(f, f"code check: {ev}", flags) if x.field == field else x for x in out]
    return out, CheckResult(name, True, False, ev, {}, flags)


def run_consistency(facts, observations, tw=None, line_result=None, cfg=None):
    """ConsistencyResult: the facts after every enabled check, the question candidates raised, and one CheckResult per check."""
    cfg = cfg or load_site_config()
    out, qs, results = list(facts), [], []
    on = lambda n: bool(cfg["consistency"][n]["value"])
    if on("lane_count_vs_width"):
        out, q, r = lane_count_vs_width(out, observations, tw, cfg); qs += q; results.append(r)
    if on("lane_lines_vs_lane_count") and line_result is not None:
        out, r = lane_lines_vs_lane_count(out, observations, line_result, cfg); results.append(r)
    if on("approaching_lanes_vs_lane_count"):
        out, q, r = approaching_lanes_vs_lane_count(out, observations, cfg); qs += q; results.append(r)
    if on("sidewalk_pair"):
        out, r = sidewalk_pair(out, observations, cfg); results.append(r)
    return ConsistencyResult(tuple(out), tuple(qs), tuple(results))
