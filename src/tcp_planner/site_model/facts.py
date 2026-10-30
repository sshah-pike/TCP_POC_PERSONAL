"""Shared records of site understanding (S6): SiteFact, Interval, Mark, Question. Shapes only; no regulatory value here.

`schema_version` is carried by every record. A fact with `registry_id` None or the flag CONTEXT_ONLY is visible to the
SME but is never a rule input: `rule_inputs` is the only reader that turns facts into rule inputs.
"""
import hashlib
from typing import Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, model_validator

SCHEMA_VERSION = "1"
Scalar = Union[bool, int, float, str]

REASON_CODES = ("not_visible", "occluded", "low_resolution", "ambiguous", "source_disagreement", "threshold_in_interval",
                "no_source", "malformed", "missing", "duplicate", "low_confidence", "no_registry_value", "ai_conflict",
                "not_stated", "single_source")
FLAGS = ("DEFAULT_ASSUMED", "POLICY_SUGGESTED", "CALIBRATION_PENDING", "SOURCE_REVIEW_REQUIRED", "CONTEXT_ONLY",
         "AI_ONLY_UNCONFIRMED", "NEEDS_SECOND_SOURCE", "EVIDENCE_OVER_15_WORDS", "UNIT_MISMATCH", "AI_CONFLICT")
# flags that keep a fact out of every rule input (the value is shown to the SME only)
BLOCKING_FLAGS = frozenset({"CONTEXT_ONLY", "NEEDS_SECOND_SOURCE"})
QUESTION_KINDS = ("WIDTH_NEAR_THRESHOLD", "LANES_DISAGREE", "START_FIELD_CONFLICT", "FACT_UNKNOWN", "WORK_SIDE_CONFIRM",
                  "WORK_LOCATION_CONFLICT")


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
    evidence_ref: Optional[str] = None


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
    status: Literal["RESOLVED", "UNKNOWN"]
    reason_code: Optional[str] = None
    interval: Optional[Interval] = None
    flags: tuple = ()
    candidates: tuple = ()

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "UNKNOWN" and self.value is not None: raise ValueError("UNKNOWN fact carries a value")
        if self.status == "RESOLVED" and self.value is None: raise ValueError("RESOLVED fact has no value")
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


class Question(_Rec):
    schema_version: str = SCHEMA_VERSION
    question_id: str
    kind: Literal[QUESTION_KINDS]
    reason: str
    options: tuple = ()
    default_if_skipped: str = "UNKNOWN"
    reveals: tuple = ()


def question_id(kind, *parts):
    return hashlib.sha256("|".join([kind, *map(str, parts)]).encode()).hexdigest()[:16]


def rule_inputs(facts):
    """{registry_id: SiteFact} for the facts a rule may read: RESOLVED, a registry id, no blocking flag."""
    return {f.registry_id: f for f in facts
            if f.registry_id and f.status == "RESOLVED" and not (set(f.flags) & BLOCKING_FLAGS)}
