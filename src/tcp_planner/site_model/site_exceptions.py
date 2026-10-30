"""Site exceptions (S6, owner addendum 2026-10-31): a reviewed file of named overrides for a known site.

`config/site_exceptions.json` ships EMPTY. An entry applies only to its named site (or zone, or OSM way) and only to its named
field; every use is listed in the run trace and the file's sha256 is recorded there too. A malformed file or entry fails closed:
the loader raises `SiteExceptionError` and nothing is applied (the run does not continue on a half-read file).

Entry: {entry_id, one of site_id | zone_id | osm_way_id, field, action, value (SET_VALUE only), reason, proposed_by_role,
entered_by_role, date}. Roles are SME, APPROVER and ADMIN, chosen from a dropdown and recorded as "role selected, not verified":
the SME proposes and the ADMIN enters (the admin can do everything for now; the APPROVER is for rule pack approval only and can
neither propose nor enter an exception).
Actions: SET_VALUE (the fact becomes FOUND with that value, source SITE_EXCEPTION, class HIGH as a human decision) and FORCE_UNKNOWN
(the fact becomes UNKNOWN, reason `site_exception`). The four mandatory start fields (D-59) can never be named.
"""
import datetime
import hashlib
import json
import os
from typing import NamedTuple, Optional

from tcp_planner.config import settings
from tcp_planner.contracts import TcpError
from tcp_planner.site_model.facts import SiteFact
from tcp_planner.site_model.start_fields import START_FIELDS

PATH = os.path.join(settings.CONFIG_DIR, "site_exceptions.json")
SCHEMA_VERSION = "1"
SCOPES = ("site_id", "zone_id", "osm_way_id")
ACTIONS = ("SET_VALUE", "FORCE_UNKNOWN")
ROLES = ("SME", "APPROVER", "ADMIN")                 # the dropdown
PROPOSERS, ENTERERS = ("SME", "ADMIN"), ("ADMIN",)
ROLE_NOTE = "role selected, not verified"
REQUIRED = ("entry_id", "field", "action", "reason", "proposed_by_role", "entered_by_role", "date")
SOURCE = "SITE_EXCEPTION"


class SiteExceptionError(TcpError):
    pass


class Loaded(NamedTuple):
    entries: tuple
    sha256: str            # of the file bytes: recorded in the trace of every run
    path: str


class Use(NamedTuple):
    entry_id: str
    scope: str
    scope_value: object
    field: str
    action: str
    value: object
    reason: str
    original_outcome: str
    original_value: object
    proposed_by_role: str = ""
    entered_by_role: str = ""


def _bad(msg):
    raise SiteExceptionError("SITE_EXCEPTIONS_MALFORMED", msg)


def _check_entry(e, i, seen):
    if not isinstance(e, dict): _bad(f"entry {i} is not an object")
    allowed = set(REQUIRED) | set(SCOPES) | {"value"}
    extra = set(e) - allowed
    if extra: _bad(f"entry {i}: unknown keys {sorted(extra)}")
    for k in REQUIRED:
        if not isinstance(e.get(k), str) or not e[k].strip(): _bad(f"entry {i}: {k} is missing or empty")
    if e["entry_id"] in seen: _bad(f"entry {i}: duplicate entry_id {e['entry_id']!r}")
    seen.add(e["entry_id"])
    scopes = [k for k in SCOPES if k in e]
    if len(scopes) != 1: _bad(f"entry {e['entry_id']}: exactly one of {', '.join(SCOPES)} is required, found {scopes or 'none'}")
    sv = e[scopes[0]]
    if scopes[0] == "osm_way_id":
        if not isinstance(sv, int) or isinstance(sv, bool): _bad(f"entry {e['entry_id']}: osm_way_id must be an integer")
    elif not isinstance(sv, str) or not sv.strip(): _bad(f"entry {e['entry_id']}: {scopes[0]} must be a non-empty string")
    if e["action"] not in ACTIONS: _bad(f"entry {e['entry_id']}: action must be one of {ACTIONS}")
    if e["field"] in START_FIELDS: _bad(f"entry {e['entry_id']}: {e['field']} is a mandatory start field (D-59) and cannot be overridden")
    if e["action"] == "SET_VALUE":
        if "value" not in e or e["value"] is None or isinstance(e["value"], (dict, list)): _bad(f"entry {e['entry_id']}: SET_VALUE needs a scalar value")
    elif "value" in e: _bad(f"entry {e['entry_id']}: FORCE_UNKNOWN takes no value")
    for k, allowed in (("proposed_by_role", PROPOSERS), ("entered_by_role", ENTERERS)):
        if e[k] not in ROLES: _bad(f"entry {e['entry_id']}: {k} must be one of {ROLES}")
        if e[k] not in allowed: _bad(f"entry {e['entry_id']}: {k} {e[k]} may not do this (allowed: {', '.join(allowed)}; the APPROVER is for rule pack approval only)")
    try: datetime.date.fromisoformat(e["date"])
    except ValueError: _bad(f"entry {e['entry_id']}: date must be YYYY-MM-DD")


def parse(raw: bytes, path=PATH):
    """Loaded from the file bytes; raises SiteExceptionError on any defect."""
    try: doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e: _bad(f"{path}: not valid JSON: {e}")
    if not isinstance(doc, dict): _bad("top level must be an object")
    if doc.get("schema_version") != SCHEMA_VERSION: _bad(f"schema_version must be {SCHEMA_VERSION!r}")
    if not isinstance(doc.get("readme"), dict): _bad("the readme block is missing")
    extra = set(doc) - {"readme", "schema_version", "entries"}
    if extra: _bad(f"unknown top-level keys {sorted(extra)}")
    if not isinstance(doc.get("entries"), list): _bad("entries must be a list")
    seen = set()
    for i, e in enumerate(doc["entries"]): _check_entry(e, i, seen)
    return Loaded(tuple(doc["entries"]), hashlib.sha256(raw).hexdigest(), path)


def load(path=None):
    path = path or PATH
    if not os.path.isfile(path): _bad(f"{path} is missing (an empty file is the way to have no exceptions)")
    with open(path, "rb") as f: return parse(f.read(), path)


def _scope_of(e):
    k = next(k for k in SCOPES if k in e)
    return k, e[k]


def apply(facts, loaded, *, site_id=None, zone_id=None, osm_way_id=None):
    """(facts, uses). An entry applies only when its scope value equals the one of this run AND its field names the fact. Nothing
    else is touched. `uses` lists each application (for the run trace)."""
    ctx = {"site_id": site_id, "zone_id": zone_id, "osm_way_id": osm_way_id}
    by_field = {}
    for e in loaded.entries:
        k, v = _scope_of(e)
        if ctx[k] is not None and ctx[k] == v: by_field.setdefault(e["field"], []).append(e)
    out, uses = [], []
    for f in facts:
        hits = by_field.get(f.field, [])
        if not hits:
            out.append(f); continue
        if len(hits) > 1: _bad(f"{len(hits)} entries apply to field {f.field} at this site: {[h['entry_id'] for h in hits]}")
        e = hits[0]; k, v = _scope_of(e)
        from tcp_planner.site_model.facts import Candidate
        cand = f.candidates + (Candidate(source=f.source, value=f.value, outcome=f.outcome),)
        if e["action"] == "SET_VALUE":
            from tcp_planner.site_model.outcomes import outcome_for
            new = f.model_copy(update={"value": e["value"], "outcome": outcome_for(f.field, e["value"]), "source": SOURCE, "reason_code": None,
                                       "confidence": None, "evidence": f"site exception {e['entry_id']}: {e['reason']}", "candidates": cand,
                                       "flags": tuple(x for x in f.flags if x not in ("NEEDS_SECOND_SOURCE", "AI_ONLY_UNCONFIRMED"))})
        else:
            new = f.model_copy(update={"value": None, "outcome": "UNKNOWN", "source": SOURCE, "reason_code": "site_exception",
                                       "evidence": f"site exception {e['entry_id']}: {e['reason']}", "candidates": cand})
        out.append(new)
        uses.append(Use(e["entry_id"], k, v, f.field, e["action"], e.get("value"), e["reason"], f.outcome, f.value, e["proposed_by_role"], e["entered_by_role"]))
    return out, uses


def trace_record(loaded, uses):
    """What the run trace stores: the file's hash, the entry count, and every use."""
    return {"file": "config/site_exceptions.json", "sha256": loaded.sha256, "entries": len(loaded.entries), "roles": ROLE_NOTE,
            "uses": [u._asdict() for u in uses]}
