"""Shared records of site understanding (S6): SiteFact, Interval, Mark, Question. Shapes only; no regulatory value here.

`schema_version` is carried by every record. A fact with `registry_id` None or the flag CONTEXT_ONLY is visible to the
SME but is never a rule input: `rule_inputs` is the only reader that turns facts into rule inputs.
"""
import hashlib
from typing import Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, model_validator

from tcp_planner.site_model.outcomes import FOUND, HAS_VALUE, NOT_PRESENT, OUTCOMES, UNKNOWN

SCHEMA_VERSION = "1"
Scalar = Union[bool, int, float, str]

REASON_CODES = ("not_visible", "occluded", "low_resolution", "ambiguous", "source_disagreement", "threshold_in_interval",
                "no_source", "malformed", "missing", "duplicate", "low_confidence", "no_registry_value", "ai_conflict",
                "not_stated", "single_source", "layout_not_allowed", "source_failed", "no_tag", "check_failed", "near_edge", "no_road_near", "site_exception", "wrong_road_suspected", "no_edge_nearby")
FLAGS = ("DEFAULT_ASSUMED", "POLICY_SUGGESTED", "CALIBRATION_PENDING", "SOURCE_REVIEW_REQUIRED", "CONTEXT_ONLY",
         "AI_ONLY_UNCONFIRMED", "NEEDS_SECOND_SOURCE", "EVIDENCE_OVER_15_WORDS", "UNIT_MISMATCH", "AI_CONFLICT", "PROPOSED", "OSM_TAG_ASSUMED", "CODE_CHECK_LOWERED")
# flags that keep a fact out of every rule input (the value is shown to the SME only)
BLOCKING_FLAGS = frozenset({"CONTEXT_ONLY", "NEEDS_SECOND_SOURCE"})
QUESTION_KINDS = ("WIDTH_NEAR_THRESHOLD", "LANES_DISAGREE", "START_FIELD_CONFLICT", "FACT_UNKNOWN", "WORK_SIDE_CONFIRM",
                  "WORK_LOCATION_CONFLICT", "LAYOUT_NOT_ALLOWED", "LANES_UNSPLIT", "WHICH_ROAD",
                  "WORK_LOCATION_NEAR_EDGE")


class _Rec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Interval(_Rec):
    lo: float
    hi: float
    unit: str

    @model_validator(mode="after")
    def _ordered(self):
        if self.lo > self.hi: raise ValueError("interval lo > hi")
        return self


class Candidate(_Rec):
    source: str
    value: Optional[Scalar] = None
    confidence_class: Optional[str] = None
    outcome: Optional[str] = None            # FOUND | NOT_PRESENT | UNKNOWN as that source reported it
    evidence_ref: Optional[str] = None


class MeasuredLength(_Rec):
    """How a length was computed (D-64): the numbers behind a width or distance fact. Never read from the AI."""
    schema_version: str = SCHEMA_VERSION
    name: str
    value_ft: float
    interval_ft: Interval
    method: Literal["CROSS_SECTION", "AI_MARKS", "GEOMETRY", "ELEVATION"]
    mpp: float                       # metres per pixel of the image the pixels were read from (as sent)
    pixel_error_px: float
    inputs: tuple = ()
    calculation: str = ""
    flags: tuple = ()


class SiteFact(_Rec):
    schema_version: str = SCHEMA_VERSION
    field: str
    registry_id: Optional[str] = None       # None: not a registry field, never a rule input
    value: Optional[Scalar] = None          # None when UNKNOWN
    unit: Optional[str] = None              # from the registry, never from the model
    confidence: Optional[float] = None
    source: str
    evidence: str = ""                      # stored whole, never parsed for numbers (D-64)
    evidence_ref: Optional[str] = None
    outcome: Literal["FOUND", "NOT_PRESENT", "UNKNOWN"]      # see site_model/outcomes.py for what each means
    reason_code: Optional[str] = None
    interval: Optional[Interval] = None
    measured: Optional[MeasuredLength] = None
    flags: tuple = ()
    candidates: tuple = ()

    @property
    def status(self):
        """RESOLVED when the fact has a value (FOUND or NOT_PRESENT), else UNKNOWN. Read-only; `outcome` is what is stored."""
        return "RESOLVED" if self.outcome in HAS_VALUE else "UNKNOWN"

    @model_validator(mode="after")
    def _consistent(self):
        if self.outcome == UNKNOWN and self.value is not None: raise ValueError("UNKNOWN fact carries a value")
        if self.outcome in HAS_VALUE and self.value is None: raise ValueError(f"{self.outcome} fact has no value")
        if self.outcome == NOT_PRESENT and not (self.value is False or (isinstance(self.value, str) and self.value.upper() == "NONE")):
            raise ValueError("NOT_PRESENT needs the value False or NONE")
        if self.reason_code is not None and self.reason_code not in REASON_CODES: raise ValueError("bad reason_code")
        if any(f not in FLAGS for f in self.flags): raise ValueError("bad flag")
        if "CONTEXT_ONLY" in self.flags and self.registry_id is not None: raise ValueError("CONTEXT_ONLY has registry_id")
        return self


class Mark(_Rec):
    schema_version: str = SCHEMA_VERSION
    feature: str
    points: tuple = ()                      # ((x, y), ...) in pixels of the image as sent
    status: Literal["RESOLVED", "UNKNOWN"]
    reason_code: Optional[str] = None
    evidence: str = ""
    original_points: tuple = ()             # the AI's own points, kept when code snapped the mark to the image edge
    snap: Optional[dict] = None             # how the snapping went (accepted fraction, shifts in pixels); None when not snapped


class Question(_Rec):
    schema_version: str = SCHEMA_VERSION
    question_id: str
    kind: Literal[QUESTION_KINDS]
    reason: str
    options: tuple = ()
    default_if_skipped: str = "UNKNOWN"
    reveals: tuple = ()
    # what S7 logs with each question and answer (there is no log store yet): which field, which zone and project, which OSM
    # way, and the numbers or tags that raised it
    field: Optional[str] = None
    zone_id: Optional[str] = None
    project_id: Optional[str] = None
    osm_way_id: Optional[int] = None
    context: dict = {}
    # A question CANDIDATE is not a blocking question: S7's what-if test makes it blocking only when the fact decides the TA.
    # `suggested` is the AI value, pre-filled for the SME to confirm.
    candidate: bool = False
    suggested: Optional[Scalar] = None


class AnswerRecord(_Rec):
    """A stored SME answer. There is no question log store in S6 or S7; whatever stores an answer keeps these keys, so a later log
    can be built from the stored records alone: kind, field, zone id, project id, OSM way id and the time of the answer."""
    schema_version: str = SCHEMA_VERSION
    question_id: str
    kind: Literal[QUESTION_KINDS]
    field: str
    zone_id: Optional[str] = None
    project_id: Optional[str] = None
    osm_way_id: Optional[int] = None
    answer: str
    answered_by: str
    answered_at: str                        # ISO 8601 with a time zone

    @model_validator(mode="after")
    def _complete(self):
        import datetime
        if not self.field.strip(): raise ValueError("answer record has no field")
        if not self.answer.strip() or not self.answered_by.strip(): raise ValueError("answer record has no answer or no actor")
        try: t = datetime.datetime.fromisoformat(self.answered_at)
        except ValueError: raise ValueError("answered_at is not an ISO 8601 time")
        if t.tzinfo is None: raise ValueError("answered_at has no time zone")
        return self


def question_scope(q, zone_id=None, project_id=None):
    """The question with its zone and project ids filled in (a question is built before it is known which zone it belongs to)."""
    return q.model_copy(update={"zone_id": zone_id or q.zone_id, "project_id": project_id or q.project_id})


def answer_record(q, answer, answered_by, answered_at, zone_id=None, project_id=None):
    """AnswerRecord for a question. The field is the question's own, else its only `reveals` entry; a question with neither cannot
    be stored (it would be lost to the log)."""
    field = q.field or (q.reveals[0] if len(q.reveals) == 1 else None)
    if not field: raise ValueError(f"question {q.question_id} ({q.kind}) names no single field: set Question.field")
    return AnswerRecord(question_id=q.question_id, kind=q.kind, field=field, zone_id=zone_id or q.zone_id, project_id=project_id or q.project_id,
                        osm_way_id=q.osm_way_id, answer=str(answer), answered_by=answered_by, answered_at=answered_at)


def question_id(kind, *parts):
    return hashlib.sha256("|".join([kind, *map(str, parts)]).encode()).hexdigest()[:16]


# flags that make any result using the fact REVIEW_REQUIRED, with the fact named (STOP 1 point 2; D-93 for the default vehicle width)
REVIEW_FLAGS = {
    "AI_ONLY_UNCONFIRMED": "was read from the image only and is not confirmed (marks missing); the SME must confirm it",
    "CODE_CHECK_LOWERED": "was lowered by a code check on the image (the painted lane lines disagree with it); the SME must confirm it",
    "OSM_TAG_ASSUMED": "rests on a missing OSM oneway tag counted as not one-way (a stand-in, not a stated tag); the SME must confirm it",
    "DEFAULT_ASSUMED": "uses a default value (not measured, not entered); the SME must confirm or override it",
    "PROPOSED": "uses the proposed footprint (a geometry with no source in the rule pack); the SME must confirm it or enter the encroachment depth",
}


class RuleInputs(dict):
    """{registry_id: SiteFact} that a rule may read. The facts keep their flags, so a result built from them can be gated:
    `gate` is how a decision learns that it used an AI-only unconfirmed fact or a default value."""

    def flagged(self, flag):
        return sorted(k for k, f in self.items() if flag in f.flags)

    @property
    def unconfirmed(self):
        return self.flagged("AI_ONLY_UNCONFIRMED")

    def gate(self, decision, used=None):
        """(decision, reasons). Any used fact flagged AI_ONLY_UNCONFIRMED, DEFAULT_ASSUMED or PROPOSED turns SUPPORTED_AUTO into
        REVIEW_REQUIRED, and each such fact is named in a reason. `used`: registry ids the result read (default: all)."""
        from tcp_planner.contracts import REVIEW_REQUIRED, SUPPORTED_AUTO
        reasons = [{"fact": k, "flag": flag, "reason": f"{k} {text}"} for flag, text in REVIEW_FLAGS.items()
                   for k in self.flagged(flag) if used is None or k in set(used)]
        return (REVIEW_REQUIRED if reasons and decision == SUPPORTED_AUTO else decision), reasons


def rule_inputs(facts):
    """RuleInputs for the facts a rule may read: RESOLVED, a registry id, no blocking flag. AI_ONLY_UNCONFIRMED facts are
    included (the value stands until the SME confirms) and stay visible through `RuleInputs.gate`."""
    return RuleInputs((f.registry_id, f) for f in facts
                      if f.registry_id and f.status == "RESOLVED" and not (set(f.flags) & BLOCKING_FLAGS))
