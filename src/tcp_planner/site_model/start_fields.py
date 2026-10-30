"""Mandatory start fields in site understanding (S6 commit 4, D-59): read-only.

road_type, posted_speed_mph, traffic_volume and lane_closure are typed by the SME in the UI. This module only READS them
from the zone input: it returns facts with source "UI" that equal the input, never computes, pre-fills or overwrites a value,
and never mutates the zone input. A computed check that contradicts one raises a conflict question and leaves the value alone.
"""
import copy

from tcp_planner.site_model.facts import Question, SiteFact, question_id

START_FIELDS = ("road_type", "posted_speed_mph", "traffic_volume", "lane_closure")
SOURCE_UI = "UI"
UNITS = {"posted_speed_mph": "mph"}


def start_facts(zone_input):
    """Facts for the four start fields, equal to zone_input["start_fields"]. A missing value (the UI keeps Run disabled, so this
    should not happen) is UNKNOWN with SOURCE_REVIEW_REQUIRED. The zone input is read, not changed."""
    sf = copy.deepcopy(zone_input["start_fields"])
    out = []
    for name in START_FIELDS:
        v = sf.get(name)
        if v is None or v == "":
            out.append(SiteFact(field=name, registry_id=name, unit=UNITS.get(name), source=SOURCE_UI, status="UNKNOWN",
                                reason_code="missing", flags=("SOURCE_REVIEW_REQUIRED",)))
        else:
            out.append(SiteFact(field=name, registry_id=name, unit=UNITS.get(name), value=v, source=SOURCE_UI, status="RESOLVED"))
    return tuple(out)


def lane_closure_conflict(decision, facts):
    """Question or None. The remaining-width table says a lane closure is needed (LANE_CLOSURE_NEEDED) but the SME entered
    lane_closure = No. The value is never changed; the SME is asked, and skipping keeps the entry as it is. Any other result
    (including UNKNOWN) raises nothing: only the defined case is checked (S6 Q13 A)."""
    lc = next((f for f in facts if f.field == "lane_closure"), None)
    if decision.result != "LANE_CLOSURE_NEEDED" or lc is None or lc.status != "RESOLVED" or lc.value is not False: return None
    return Question(question_id=question_id("START_FIELD_CONFLICT", "lane_closure"), kind="START_FIELD_CONFLICT",
                    reason=("the computed remaining lane width needs a lane closure (%s) but lane_closure was entered as No; "
                            "the entry is kept until the SME confirms or changes it" % decision.reason),
                    options=("KEEP_AS_ENTERED", "SME_WILL_CHANGE_IT"), default_if_skipped="KEEP_AS_ENTERED", reveals=("lane_closure",))
