"""Applying the fusion rules to facts (S6, owner answers to STOP 5, 2026-10-31).

Safety-critical fields (config call1.safety_critical_fields: lanes per direction, divided, shoulder, one-way): the AI and one data
source must agree.
  agree            the fact stands (FOUND or NOT_PRESENT), the NEEDS_SECOND_SOURCE flag goes, source AI+<data source>
  disagree         UNKNOWN (source_disagreement); both values stay as candidates
  single source    UNKNOWN (single_source): no second source, or the source gave nothing (no tag, failed, ambiguous). The AI value stays
                   visible and pre-filled as a candidate and ONE question CANDIDATE is emitted (Question.candidate, suggested = the AI
                   value). A candidate is not a blocking question: S7's what-if test makes it blocking only when the fact decides the TA.
A FOUND value whose OSM side is a stand-in for a missing tag (one-way read as "not one-way") carries OSM_TAG_ASSUMED: any result using
it is REVIEW_REQUIRED naming the fact (RuleInputs.gate).
A second source is a DATA source only (an enabled source of config/data_sources.json other than the imagery provider). A code check
on the image (lane lines, snapping, shadow share, offsets) can lower trust or give UNKNOWN, and is never a second source: a reading
from any other source id is refused.

sidewalk_present is record only: OSM's reading is added as a candidate (class LOW when it disagrees, MEDIUM when it agrees), the
fact and its value do not change, and no question is asked.
"""
from typing import NamedTuple

from tcp_planner.data_sources.base import load_sources
from tcp_planner.site_model.facts import Candidate, Question, question_id
from tcp_planner.site_model.fusion_v2 import AGREE, DISAGREE, FusionRecord, SourceReading, compare
from tcp_planner.site_model.site_config import call1_setting, load_site_config

RECORD_ONLY = ("sidewalk_present",)
IMAGERY_SOURCES = frozenset({"azure_maps"})


class FusionResult(NamedTuple):
    facts: tuple
    records: dict            # field -> FusionRecord
    questions: tuple         # question candidates


def second_sources(sources=None):
    """Ids a reading may carry to count as a second source: the enabled data sources, without the imagery provider."""
    cfg = sources or load_sources()
    return frozenset(k for k, v in cfg["sources"].items() if v.get("enabled") and v.get("hosts")) - IMAGERY_SOURCES


def _check_sources(readings, allowed):
    for r in readings:
        if r.source not in allowed:
            raise ValueError(f"{r.source!r} is not a data source: a code check on the image is never a second source")


def _cands(fact, readings):
    ai = Candidate(source=fact.source, value=fact.value, outcome=fact.outcome, confidence_class=None)
    return fact.candidates + (ai,) + tuple(Candidate(source=r.source, value=r.value, outcome=r.outcome) for r in readings)


def _unknown(fact, reason, readings, evidence):
    flags = tuple(x for x in fact.flags if x != "NEEDS_SECOND_SOURCE")
    return fact.model_copy(update={"outcome": "UNKNOWN", "value": None, "reason_code": reason, "flags": flags, "candidates": _cands(fact, readings),
                                   "evidence": (fact.evidence + " | " if fact.evidence else "") + evidence})


def _question(fact, record, osm_questions):
    """The one question candidate for an UNKNOWN safety field: OSM's own question for the field when it raised one, else a generic one."""
    for q in osm_questions:
        if q.field == fact.field: return q.model_copy(update={"candidate": True, "suggested": _ai_value(fact)})
    kind = "LANES_DISAGREE" if fact.field == "lanes_per_direction" and record.agreement == DISAGREE else "FACT_UNKNOWN"
    ai = _ai_value(fact)
    return Question(question_id=question_id(kind, fact.field, "candidate"), kind=kind, field=fact.field, reveals=(fact.field,), candidate=True,
                    suggested=ai, reason=f"{fact.field}: the image reads {ai!r}; {record.note}. Confirm or correct.", options=() if ai is None else (str(ai),),
                    context={"agreement": record.agreement, "candidates": [c.model_dump() for c in record.candidates]})


def _ai_value(fact):
    ai = [c for c in fact.candidates if c.source == "AI" and c.value is not None]
    return ai[-1].value if ai else None


def fuse_fields(facts, osm=None, cfg=None, sources=None):
    """FusionResult for all facts. `osm`: an OsmRead (readings per field and its own questions) or None when OSM was not consulted
    (every safety field then has a single source). Facts of other fields pass unchanged."""
    cfg = cfg or load_site_config()
    critical = set(call1_setting("safety_critical_fields", cfg))
    allowed = second_sources(sources)
    out, records, questions = [], {}, []
    for f in facts:
        reading = (osm.readings.get(f.field) if osm is not None else None)
        readings = [reading] if reading is not None else []
        _check_sources(readings, allowed)
        if f.field in RECORD_ONLY:
            if not readings or f.outcome == "UNKNOWN":
                out.append(f); continue
            rec = compare(f.field, f.value, readings)
            records[f.field] = rec
            out.append(f.model_copy(update={"candidates": f.candidates + tuple(c for c in rec.candidates if c.source != "AI")}))
            continue
        if f.field not in critical:
            out.append(f); continue
        rec = compare(f.field, f.value, readings)
        records[f.field] = rec
        if f.outcome == "UNKNOWN":                                    # nothing to confirm; the fact keeps its own reason
            out.append(f); continue
        if rec.agreement == AGREE:
            src = readings[0].source
            flags = tuple(x for x in f.flags if x != "NEEDS_SECOND_SOURCE")
            if readings[0].lower_confidence: flags += ("OSM_TAG_ASSUMED",)      # the OSM side is a stand-in for a missing tag: REVIEW_REQUIRED
            out.append(f.model_copy(update={"source": f"AI+{src}", "candidates": _cands(f, readings), "flags": flags}))
            continue
        reason = "source_disagreement" if rec.agreement == DISAGREE else "single_source"
        nf = _unknown(f, reason, readings, rec.note)
        out.append(nf)
        questions.append(_question(nf, rec, osm.questions if osm is not None else ()))
    return FusionResult(tuple(out), records, tuple(questions))
