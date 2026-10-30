"""Fusion records and confidence classes (S6 commit 6; Q14 A, D-37, D-80, D-92).

All fused geometry and data-source values are LOW confidence; imagery decides, and disagreements are recorded, never hidden.
Numbers are kept only for the AI's own confidence. The classes:
  HIGH    only the SME or the UI (a typed start field, an SME answer, an SME override)
  MEDIUM  a data source whose value agrees with the imagery reading
  LOW     any other data-source value (it disagrees, or imagery gave nothing to agree with), and every fused geometry value
No source of this module fills a mandatory start field (D-59): `fuse` refuses those fields.

`compare` is the single-source rule input (D-92): for lanes per direction, divided, shoulder and one-way the AI reading plus one data
source are the two sources; two AI calls or crops never count as two.
"""
from typing import NamedTuple, Optional

from pydantic import BaseModel, ConfigDict

from tcp_planner.site_model.facts import Candidate, SCHEMA_VERSION
from tcp_planner.site_model.start_fields import START_FIELDS

HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"
CLASSES = (LOW, MEDIUM, HIGH)
AGREE, DISAGREE, SINGLE_SOURCE, UNDECIDABLE = "AGREE", "DISAGREE", "SINGLE_SOURCE", "UNDECIDABLE"
HUMAN_ORIGINS = frozenset({"SME", "UI", "SME_OVERRIDE", "SME_FORM"})


def confidence_class(origin, agrees_with_imagery=None):
    """Class of a value from `origin`: a human origin is HIGH; a data source is MEDIUM when it agrees with the imagery reading,
    else LOW (including when there is nothing to compare). Never HIGH for a data source."""
    if origin in HUMAN_ORIGINS: return HIGH
    return MEDIUM if agrees_with_imagery is True else LOW


class FusionRecord(BaseModel):
    """How the candidates for one field were compared. Stored with the field; a disagreement is recorded here."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = SCHEMA_VERSION
    field: str
    candidates: tuple = ()                  # Candidate records: imagery first, then each data source
    agreement: str                          # AGREE | DISAGREE | SINGLE_SOURCE | UNDECIDABLE
    note: str = ""


def compare(field, ai_value, source_candidates, same=None):
    """FusionRecord for the AI reading against data-source candidates (each a (source_id, value) pair; value None = the source
    cannot decide, for example an odd OSM lane total that cannot be split between directions).
      no source candidates                   -> SINGLE_SOURCE (the AI alone is not enough for a safety-critical field)
      every source undecidable               -> UNDECIDABLE   (no agreement and no disagreement)
      all decidable sources equal the AI     -> AGREE
      any decidable source differs           -> DISAGREE      (recorded; imagery does not win silently)
    `same(ai, source)` overrides equality. Refuses a mandatory start field: no data source fills one (D-59)."""
    if field in START_FIELDS: raise ValueError(f"{field} is a mandatory start field: no data source may supply it")
    same = same or (lambda a, b: a == b)
    cands = [Candidate(source="AI", value=ai_value, confidence_class=None)]
    decided = [(sid, v) for sid, v in source_candidates if v is not None]
    for sid, v in source_candidates:
        agree = None if v is None or ai_value is None else same(ai_value, v)
        cands.append(Candidate(source=sid, value=v, confidence_class=confidence_class(sid, agree)))
    if not source_candidates: return FusionRecord(field=field, candidates=tuple(cands), agreement=SINGLE_SOURCE, note="only the imagery reading exists")
    if not decided: return FusionRecord(field=field, candidates=tuple(cands), agreement=UNDECIDABLE, note="no source could decide the value")
    if ai_value is None: return FusionRecord(field=field, candidates=tuple(cands), agreement=UNDECIDABLE, note="the imagery reading is unknown")
    bad = [sid for sid, v in decided if not same(ai_value, v)]
    if bad: return FusionRecord(field=field, candidates=tuple(cands), agreement=DISAGREE, note="imagery and " + ", ".join(bad) + " disagree")
    return FusionRecord(field=field, candidates=tuple(cands), agreement=AGREE, note="imagery and " + ", ".join(sid for sid, _ in decided) + " agree")
