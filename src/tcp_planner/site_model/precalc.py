"""Pre-calculation (S6 commit 4, plan 4C) as pure functions: no model call, no I/O, no value typed here.

Q11 A: these are called once the TA and the duration are known (S7/S8). S6 itself computes only the TA-independent ones
(vehicle width, footprint, remaining width and its decision, the freeway flag). Every regulatory number is read from the
rule pack; the only default is the work-vehicle width in config (DEFAULT_ASSUMED, optional). Work-space depth and clearance
have no source: the footprint and the remaining width stay UNKNOWN until the SME supplies them for the job.
"""
from typing import NamedTuple, Optional

from tcp_planner.rules.rule_pack_eval import eval_expr
from tcp_planner.rules.rule_pack_models import Status as PackStatus
from tcp_planner.site_model.facts import Interval, MeasuredLength, Question, SiteFact, question_id
from tcp_planner.site_model.lengths import length_fact
from tcp_planner.site_model.site_config import default_setting

IN_PER_FT = 12          # unit conversion only
EXPRESSWAY = "EXPRESSWAY_FREEWAY"        # registry enum value of road_type (checked against the registry in a test)
LANE_CLOSURE_ACTION = "LANE_CLOSURE_NEEDED"
SHADOW_SUFFIXES = ("WITH_LIT_VEHICLE", "WITH_LIT_SHADOW_VEHICLE")
ARROW_ACTION = "ARROW_BOARD_PER_CLOSED_LANE"
NINE_FT_ACTION = "NINE_FT_LANE_ALLOWED"
HOLD, HOLD_NINE, CLOSURE, UNKNOWN = "TA6_CAN_HOLD", "TA6_CAN_HOLD_NINE_FT_OPTION", "LANE_CLOSURE_NEEDED", "UNKNOWN"


def context_values(*fact_groups):
    """{registry_id: value} of the RESOLVED facts: the context the pack's conditions are evaluated with."""
    return {f.registry_id: f.value for g in fact_groups for f in g if f.registry_id and f.status == "RESOLVED"}


def _unknown(field, reason, flags=(), unit=None, evidence=""):
    return SiteFact(field=field, registry_id=field, unit=unit, source="CODE", outcome="UNKNOWN", reason_code=reason, flags=tuple(flags),
                    evidence=evidence)


# ---------------------------------------------------------------- vehicle and footprint
def work_vehicle_width(measured_ft=None, use_default=True, cfg=None):
    """work_vehicle_width_ft: the measured width when a vehicle is visible, else the cited default flagged DEFAULT_ASSUMED.
    The default is optional: use_default=False leaves the fact UNKNOWN (no_source)."""
    if measured_ft is not None:
        return SiteFact(field="work_vehicle_width_ft", registry_id="work_vehicle_width_ft", value=float(measured_ft), unit="ft",
                        source="GEOMETRY", outcome="FOUND")
    inches, flags, optional = default_setting("work_vehicle_width_in", cfg)
    if not use_default or inches is None: return _unknown("work_vehicle_width_ft", "no_source", unit="ft")
    return SiteFact(field="work_vehicle_width_ft", registry_id="work_vehicle_width_ft", value=inches / IN_PER_FT, unit="ft",
                    source="DEFAULT", outcome="FOUND", flags=flags,
                    evidence="default width from config (23 CFR 658.15); no vehicle measured")


FOOTPRINT_FORMULA = "encroachment_depth_ft = max(work_space_depth_ft, work_vehicle_width_ft if the vehicle is included) + clearance_ft"


def _depth_fact(value, source, flags, inputs, calc):
    m = MeasuredLength(name="encroachment_depth", value_ft=value, interval_ft=Interval(lo=value, hi=value, unit="ft"), method="GEOMETRY",
                       mpp=0.0, pixel_error_px=0.0, inputs=tuple(inputs), calculation=calc, flags=tuple(flags))
    return SiteFact(field="encroachment_depth_ft", registry_id="encroachment_depth_ft", value=value, unit="ft", source=source,
                    outcome="FOUND", interval=m.interval_ft, measured=m, flags=tuple(flags), evidence=calc)


def encroachment_depth(work_space_depth_ft=None, clearance_ft=None, vehicle=None, include_vehicle=False, sme_override_ft=None):
    """(SiteFact encroachment_depth_ft, Question or None). Depth into the travel lane, measured to the near face of the
    channelizing devices (TA-6 note 1).
    - sme_override_ft: the single encroachment-depth number the SME gives for the job. It WINS over everything else; the result
      is that number (source SME_OVERRIDE, no PROPOSED flag) and the other inputs are only listed in the trace.
    - otherwise the PROPOSED geometry (no source in the pack, S6 STOP 3): FOOTPRINT_FORMULA. Work-space depth and clearance
      have no source: without both the fact is UNKNOWN and one question asks for the number (or for both inputs).
    `vehicle` is a work_vehicle_width_ft fact; its DEFAULT_ASSUMED flag is carried when the vehicle sets the depth."""
    if sme_override_ft is not None:
        if isinstance(sme_override_ft, bool) or not isinstance(sme_override_ft, (int, float)) or sme_override_ft < 0:
            raise ValueError("the encroachment-depth override must be a number of feet, zero or more")
        ignored = [f"{n}={v} (not used: the override wins)" for n, v in (("work_space_depth_ft", work_space_depth_ft), ("clearance_ft", clearance_ft)) if v is not None]
        return _depth_fact(float(sme_override_ft), "SME_OVERRIDE", (), [f"sme_override_ft={sme_override_ft}", *ignored],
                           "encroachment_depth_ft = the number the SME gave for this job"), None
    if work_space_depth_ft is None or clearance_ft is None:
        q = Question(question_id=question_id("FACT_UNKNOWN", "encroachment_depth_ft"), kind="FACT_UNKNOWN",
                     reason="how far the work space and the near face of the devices reach into the lane is not known; enter the encroachment "
                            "depth in feet (or the work-space depth and the clearance to the device face)",
                     options=(), reveals=("encroachment_depth_ft", "remaining_lane_width_ft"))
        return _unknown("encroachment_depth_ft", "no_source", ("SOURCE_REVIEW_REQUIRED",), "ft"), q
    extent, flags, inputs = work_space_depth_ft, ["PROPOSED"], [f"work_space_depth_ft={work_space_depth_ft}", f"clearance_ft={clearance_ft}"]
    if include_vehicle and vehicle is not None and vehicle.status == "RESOLVED":
        inputs.append(f"work_vehicle_width_ft={vehicle.value} (included)")
        if vehicle.value > extent:
            extent = vehicle.value; flags += [f for f in vehicle.flags if f == "DEFAULT_ASSUMED"]
    else: inputs.append("work vehicle not included")
    return _depth_fact(extent + clearance_ft, "SME_FORM", flags, inputs, FOOTPRINT_FORMULA + " (PROPOSED: no source in the pack)"), None


def remaining_lane_width(pack, lane, depth, context=None):
    """(SiteFact remaining_lane_width_ft, Question or None) = lane width minus encroachment depth. UNKNOWN when either is.
    The interval is the lane width's, shifted by the depth; a pack limit inside it makes the fact UNKNOWN with a question."""
    if lane is None or lane.status != "RESOLVED": return _unknown("remaining_lane_width_ft", (lane.reason_code if lane else None) or "missing", unit="ft"), None
    if depth is None or depth.status != "RESOLVED": return _unknown("remaining_lane_width_ft", (depth.reason_code if depth else None) or "no_source", unit="ft"), None
    iv = lane.interval or Interval(lo=lane.value, hi=lane.value, unit="ft")
    value = lane.value - depth.value
    m = MeasuredLength(name="remaining_lane_width", value_ft=value, interval_ft=Interval(lo=iv.lo - depth.value, hi=iv.hi - depth.value, unit="ft"),
                       method="GEOMETRY", mpp=lane.measured.mpp if lane.measured else 0.0,
                       pixel_error_px=lane.measured.pixel_error_px if lane.measured else 0.0,
                       inputs=(f"lane_width_ft={lane.value}", f"encroachment_depth_ft={depth.value}"),
                       calculation="remaining_lane_width_ft = lane_width_ft - encroachment_depth_ft (to the near face of the devices)",
                       flags=tuple(dict.fromkeys(lane.flags + depth.flags)))
    return length_fact("remaining_lane_width_ft", m, None, pack, context)


# ---------------------------------------------------------------- the remaining-width table (plan 4C, section 2)
class Decision(NamedTuple):
    result: str                 # TA6_CAN_HOLD | TA6_CAN_HOLD_NINE_FT_OPTION | LANE_CLOSURE_NEEDED | UNKNOWN
    label: Optional[str]        # printed on the plan when the 9 ft option is used
    reason: str


def _sourced_rules(pack):
    return [r for r in pack.records("rule") if r.status == PackStatus.SOURCED and r.role == "APPLY"]


def limit_rules(pack):
    """(full-limit rule, option-limit rule) or None: the shared federal rules, found by action."""
    def find(action):
        return next((r for r in _sourced_rules(pack) if r.ta_id is None and r.action == action and r.value is not None), None)
    full, opt = find(LANE_CLOSURE_ACTION), find(NINE_FT_ACTION)
    return (full, opt) if full and opt else None


def shadow_rules(pack, ta_id):
    """Rules of the TA that allow dropping signs, taper or devices only with a lit vehicle (TA-1 note 4, TA-6 note 10)."""
    return [r for r in _sourced_rules(pack) if r.ta_id == ta_id and r.condition is not None
            and (r.action or "").endswith(SHADOW_SUFFIXES)]


def arrow_rule(pack):
    return next((r for r in _sourced_rules(pack) if r.action == ARROW_ACTION and r.condition is not None), None)


def tma_rule(pack):
    """The sourced TMA speed-threshold rule, or None while the pack has none."""
    return next((r for r in _sourced_rules(pack) if r.topic == "truck_mounted_attenuator" and r.unit == "mph" and r.value is not None), None)


def _limits(pack):
    """(full limit, option limit, option condition, ids) from the shared federal rules: nothing is typed here."""
    lr = limit_rules(pack); full, opt = lr if lr else (None, None)
    return (full.value, opt.value, opt.condition, full.id, opt.id) if full and opt else None


def remaining_width_decision(pack, fact, context=None):
    """The remaining-width table:
        at or above the full limit                                         -> TA-6 can hold
        between the option limit and the full limit, option conditions met -> TA-6 can hold (9 ft option, labelled)
        between them, heavy vehicles / volume / speed / duration not met
          (or unknown)                                                      -> a lane closure is needed
        below the option limit                                              -> a lane closure is needed
        a pack limit inside the interval, or the width unknown              -> UNKNOWN (the SME confirms a measured width)
    Limits and the option's conditions come from the pack. The result never changes lane_closure (D-59)."""
    if fact is None or fact.status != "RESOLVED":
        why = "a rule limit lies inside the uncertainty band" if fact is not None and fact.reason_code == "threshold_in_interval" \
            else f"remaining lane width is unknown ({fact.reason_code if fact else 'missing'})"
        return Decision(UNKNOWN, None, why)
    lim = _limits(pack)
    if lim is None: return Decision(UNKNOWN, None, "the pack has no remaining-width rule")
    full, opt, opt_cond, full_id, opt_id = lim
    option_ok = eval_expr(opt_cond, dict(context or {})) is True

    def classify(x):
        if x >= full: return HOLD
        if x >= opt and option_ok: return HOLD_NINE
        return CLOSURE
    iv = fact.interval or Interval(lo=fact.value, hi=fact.value, unit="ft")
    seen = {classify(x) for x in (iv.lo, fact.value, (iv.lo + iv.hi) / 2, iv.hi)}
    if len(seen) > 1: return Decision(UNKNOWN, None, "the interval spans a limit")
    r = seen.pop()
    if r == HOLD: return Decision(r, None, f"remaining width at or above {full_id}")
    if r == HOLD_NINE: return Decision(r, "9 ft lane width, short-term low-volume low-speed option", f"{opt_id} conditions met")
    return Decision(r, None, f"below {full_id}" + ("" if fact.value < opt else f" and the {opt_id} conditions are not all met"))


# ---------------------------------------------------------------- TA-dependent functions (called once the TA is known)
def freeway(road_type):
    """freeway flag from the SME's road_type (read, never changed)."""
    if road_type is None: return _unknown("freeway", "missing")
    return SiteFact(field="freeway", registry_id="freeway", value=road_type == EXPRESSWAY, source="CODE", outcome="FOUND")


# What the input `layout_omits` means per TA. The two notes are the same fact (a lit vehicle replaces what the layout drops), but
# what is dropped differs: TA-1 note 4 drops the signs and the channelizing devices; TA-6 note 10 drops the taper and the devices.
OMISSION_MEANING = {"TA-1": "the layout omits signs and devices", "TA-6": "the layout omits taper and devices"}


def _quote(pack, rule):
    """The note's exact text from the pack's source reference."""
    return " ".join(getattr(pack.get(sid), "quote", "") or "" for sid in rule.source_ref_ids[:1])


def _allowed_values(expr, field="duration"):
    """Values of `field` that the rule condition allows, when it is a plain EQ or IN on that field; else None."""
    if getattr(expr, "field", None) == field and expr.op in ("EQ", "IN"):
        return list(expr.value) if isinstance(expr.value, list) else [expr.value]
    return None


def shadow_vehicle(pack, ta_id, context, layout_omits):
    """(SiteFact shadow_vehicle_present, Question or None). `layout_omits` is whether the layout drops what the TA's note lets a lit
    vehicle replace (OMISSION_MEANING: TA-1 signs and devices, TA-6 taper and devices); S8 supplies it.
      None                                 -> UNKNOWN (missing)
      False                                -> False: optional and off by default
      True, duration allows it             -> True, required; the trace quotes the note
      True, duration unknown               -> UNKNOWN (missing)
      True, duration does NOT allow it, or no note of the TA allows it
                                           -> UNKNOWN (layout_not_allowed, SOURCE_REVIEW_REQUIRED) and one question naming the note
                                              and the allowed durations; never True or False."""
    if layout_omits is None: return _unknown("shadow_vehicle_present", "missing"), None
    if layout_omits is False:
        return SiteFact(field="shadow_vehicle_present", registry_id="shadow_vehicle_present", value=False, source="CODE", outcome="FOUND",
                        evidence="optional and off by default" + (" (TA-6 note 8)" if ta_id == "TA-6" else "")), None
    rules = shadow_rules(pack, ta_id)
    res = [(r, eval_expr(r.condition, dict(context or {}))) for r in rules]
    ok = [r for r, v in res if v is True]
    if ok:
        r = ok[0]
        return SiteFact(field="shadow_vehicle_present", registry_id="shadow_vehicle_present", value=True, source="CODE", outcome="FOUND",
                        evidence=f"required: {r.id}: \"{_quote(pack, r)}\"; {OMISSION_MEANING.get(ta_id, 'the layout omits what the note allows')}"), None
    if any(v is None for _, v in res): return _unknown("shadow_vehicle_present", "missing"), None
    if rules:
        r = rules[0]; allowed = _allowed_values(r.condition)
        why = (f"{r.id} says: \"{_quote(pack, r)}\" It allows this only for duration {' or '.join(allowed)}; "
               f"the duration is {(context or {}).get('duration')}." if allowed else f"{r.id} says: \"{_quote(pack, r)}\" The conditions are not met.")
    else:
        why = f"no note of {ta_id} allows a lit vehicle to replace omitted devices."
    q = Question(question_id=question_id("LAYOUT_NOT_ALLOWED", ta_id, "shadow_vehicle_present"), kind="LAYOUT_NOT_ALLOWED",
                 reason=f"{OMISSION_MEANING.get(ta_id, 'The layout omits devices')}, which is not allowed here. {why} Change the layout or change the duration.",
                 options=("change the layout", "change the duration"), reveals=("shadow_vehicle_present",))
    return _unknown("shadow_vehicle_present", "layout_not_allowed", ("SOURCE_REVIEW_REQUIRED",)), q


def tma_suggestion(pack, posted_speed_mph):
    """tma_present as a labelled client policy suggestion (POLICY_SUGGESTED). Off while the pack has no sourced speed threshold
    (R-TMA-SPEED-THRESHOLD is UNKNOWN): the fact stays UNKNOWN and nothing is suggested."""
    rule = tma_rule(pack)
    if rule is None: return _unknown("tma_present", "no_source", ("SOURCE_REVIEW_REQUIRED",))
    if posted_speed_mph is None: return _unknown("tma_present", "missing")
    return SiteFact(field="tma_present", registry_id="tma_present", value=posted_speed_mph >= rule.value, source="CODE", outcome="FOUND",
                    flags=("POLICY_SUGGESTED",), evidence=f"suggested by {rule.id}; always optional (the SME can override)")


def arrow_board(pack, context):
    """arrow_board_present. Where the pack makes it required (TA-33 note 7: a closed freeway or expressway lane; one per closed
    lane, the count stays UNKNOWN with lanes_closed_count) the answer is REQUIRED, whatever arrow_board_wanted says. Only when it is
    optional does arrow_board_wanted decide, and an unasked answer means not wanted."""
    rule = arrow_rule(pack)
    ctx = dict(context or {})
    req = eval_expr(rule.condition, ctx) if rule else None
    if req is True:
        return SiteFact(field="arrow_board_present", registry_id="arrow_board_present", value=True, source="CODE", outcome="FOUND",
                        evidence=f"REQUIRED by {rule.id}: one per closed lane, count not known")
    if req is None: return _unknown("arrow_board_present", "missing")
    wanted = ctx.get("arrow_board_wanted") is True
    return SiteFact(field="arrow_board_present", registry_id="arrow_board_present", value=wanted, source="CODE", outcome="FOUND",
                    evidence="OPTIONAL_WANTED" if wanted else "OPTIONAL_NOT_WANTED (not asked or not wanted)")
