"""Project and work-zone model (slice S3). Pure functions over plain JSON records; ProjectStore persists them.

A project is one input (KML, coordinates or an offline scenario). It holds every WorkLocation, the SME's start fields
and TA selections, the zones built from the locations, and a status (plan section 12, S3 decisions Q1 to Q16):

  project_id      "PRJ-" + hash of the sorted geometry hashes of the usable locations (Q2-B); an offline project adds
                  its scenario name, because every scenario uses the same point
  start_fields    {"project": {field: value|None}, "per_location": {location_id: {field: value}}}
                  typed by the SME (D-59). Nothing here fills, derives or defaults a value: an empty field stays None
  ta_hypothesis   {"project": "AUTO"|TA, "per_location": {location_id: TA}}; the UI default is Auto (D-73)
  zones           one zone per usable location (grouping stub; grouping is S9). A Point zone runs; a line or polygon
                  zone is NOT_SUPPORTED_UNTIL_S14 and never runs (Q7). A zone gets version + 1 when its inputs change;
                  unchanged inputs keep the version and its run, so pressing Run twice creates nothing new
  status          see roll_up()

Placemark names are display labels only (D-72): nothing below reads them.
"""
import copy

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.intake import work_location as wl
from tcp_planner.intake.lineage import lineage_key, zone_geometry_hash

SCHEMA_VERSION = "1"  # zone sub-records; the project record itself is versioned by its state record (ProjectStore)

KML, COORDINATES, OFFLINE = "KML", "COORDINATES", "OFFLINE"
START_FIELDS = ("road_type", "posted_speed_mph", "traffic_volume", "lane_closure")  # D-59
TRAFFIC_VOLUMES = ("HIGH", "LOW")  # plan section 4B, D-59
AUTO = "AUTO"
TA_CHOICES = (AUTO, "TA-1", "TA-6", "TA-10", "TA-33")  # D-73

ONE_PER_LOCATION = "ONE_PER_LOCATION"  # S3 grouping stub (S3 prompt seed); S9 replaces it
GROUPING_RULE_VERSION = "s3-stub-1"
ZONE_PENDING = "PENDING"
ZONE_NOT_SUPPORTED = "NOT_SUPPORTED_UNTIL_S14"

INPUTS_REQUIRED = "INPUTS_REQUIRED"
READY = "READY"
ZONE_CAP_APPROVAL_REQUIRED = "ZONE_CAP_APPROVAL_REQUIRED"
RUNNING = "RUNNING"
ALL_DRAFTED = "ALL_DRAFTED"
PARTIAL = "PARTIAL"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
FAILED = "FAILED"

QUEUED, ACTIVE, FINISHED = "QUEUED", "RUNNING", "FINISHED"  # zone run states, as reported to roll_up()
SUPPORTED_AUTO = "SUPPORTED_AUTO"


class ProjectInputError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message); self.code = code; self.message = message; self.details = details or {}


# ------------------------------------------------------------------ identity
def project_id_for(locations, offline_scenario=None):
    """Same usable geometry -> same project (Q2-B). Names, order, file name and file bytes never change the id."""
    hashes = sorted(l.geometry_hash for l in locations if l.usable)
    if not hashes:
        raise ProjectInputError("NO_USABLE_LOCATION", "the input has no usable work location")
    doc = {"geometry_hashes": hashes}
    if offline_scenario: doc["offline_scenario"] = offline_scenario
    return "PRJ-" + sha256_hex(canonical_json(doc))[:16]


def zone_id_for(engine_geometry_hash):
    return "ZONE-" + engine_geometry_hash.split(":", 1)[-1][:12]


# ------------------------------------------------------------------ new record
def new_record(*, name, source, locations, advanced=None):
    """The record ProjectStore.create stores (it adds project_id and created_at). Every start field starts empty."""
    return {"name": name, "source": source, "locations": [l.to_dict() for l in locations],
            "start_fields": {"project": {f: None for f in START_FIELDS}, "per_location": {}},
            "ta_hypothesis": {"project": AUTO, "per_location": {}},
            "advanced": dict(advanced or {}), "zones": [], "run_request": None, "cap_approval": None,
            "inputs": [],   # every upload of this project: {uri, sha256, size, media_type, uploaded_at}, newest last
            "labels": {},   # display labels by location id: {text, input_sha256, input_key} (the upload they follow)
            "status": INPUTS_REQUIRED}


def locations_of(record):
    return [wl.WorkLocation.from_dict(d) for d in record["locations"]]


def _runnable_location(loc):
    return loc.usable and loc.role == wl.WORK and loc.geometry["type"] == wl.POINT


# ------------------------------------------------------------------ start fields (typed by the SME only)
def check_start_fields(values, road_types):
    """Validate SME-typed values; None means "empty". Returns the same keys, normalised; never adds a value.
    road_types: the rule pack's road types (Q13), never a list kept in code."""
    if not isinstance(values, dict): raise ProjectInputError("START_FIELDS_INVALID", "start fields must be an object")
    out = {}
    for k, v in values.items():
        if k not in START_FIELDS: raise ProjectInputError("START_FIELDS_INVALID", f"unknown start field {k!r}")
        if v is None or v == "": out[k] = None; continue
        if k == "road_type":
            if not isinstance(v, str) or v not in road_types:
                raise ProjectInputError("START_FIELDS_INVALID", f"road_type must be one of {list(road_types)}")
        elif k == "posted_speed_mph":  # Q14: a positive whole number, no upper limit
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ProjectInputError("START_FIELDS_INVALID", "posted_speed_mph must be a positive whole number")
        elif k == "traffic_volume":
            v = v.upper() if isinstance(v, str) else v
            if v not in TRAFFIC_VOLUMES:
                raise ProjectInputError("START_FIELDS_INVALID", f"traffic_volume must be one of {list(TRAFFIC_VOLUMES)}")
        elif k == "lane_closure":
            if not isinstance(v, bool): raise ProjectInputError("START_FIELDS_INVALID", "lane_closure must be true or false")
        out[k] = v
    return out


def check_ta(value, allow_none=False):
    if value is None and allow_none: return None
    v = value.upper() if isinstance(value, str) else value
    if v not in TA_CHOICES: raise ProjectInputError("TA_SELECTION_INVALID", f"Select TA must be one of {list(TA_CHOICES)}")
    return v


def set_inputs(record, road_types, *, project=None, per_location=None, apply_to_all=False, ta_project=None,
               ta_per_location=None):
    """New record with the SME's edits. project: start fields for the whole project; apply_to_all also clears those
    fields' per-point overrides ("apply to all points"). per_location: {location_id: {field: value or None}};
    None removes that point's override. ta_per_location: {location_id: TA or None}."""
    rec = copy.deepcopy(record)
    known = {d["location_id"]: d for d in rec["locations"]}

    def check_loc(lid):
        if lid not in known: raise ProjectInputError("UNKNOWN_LOCATION", f"unknown location {lid!r}")
        if known[lid]["reject_reasons"]: raise ProjectInputError("LOCATION_NOT_USABLE", f"location {lid} is not usable")
        return lid

    sf = rec["start_fields"]
    if project is not None:
        vals = check_start_fields(project, road_types)
        sf["project"].update(vals)
        if apply_to_all:
            for over in sf["per_location"].values():
                for k in vals: over.pop(k, None)
    for lid, vals in (per_location or {}).items():
        vals = check_start_fields(vals, road_types)
        over = sf["per_location"].setdefault(check_loc(lid), {})
        for k, v in vals.items():
            if v is None: over.pop(k, None)
            else: over[k] = v
    sf["per_location"] = {k: v for k, v in sf["per_location"].items() if v}
    th = rec["ta_hypothesis"]
    if ta_project is not None: th["project"] = check_ta(ta_project)
    for lid, v in (ta_per_location or {}).items():
        v = check_ta(v, allow_none=True)
        if v is None: th["per_location"].pop(check_loc(lid), None)
        else: th["per_location"][check_loc(lid)] = v
    return rec


def effective_inputs(record, location_id):
    """The values a location runs with: its own override, else the project value. Empty stays None."""
    proj = record["start_fields"]["project"]; over = record["start_fields"]["per_location"].get(location_id, {})
    out = {f: over[f] if over.get(f) is not None else proj.get(f) for f in START_FIELDS}
    out["ta_hypothesis"] = record["ta_hypothesis"]["per_location"].get(location_id) or record["ta_hypothesis"]["project"]
    return out


def missing_fields(record):
    """{location_id: [empty start fields]} over the locations that would run. Empty dict -> Run may start."""
    out = {}
    for loc in locations_of(record):
        if not _runnable_location(loc): continue
        eff = effective_inputs(record, loc.location_id)
        miss = [f for f in START_FIELDS if eff[f] is None]
        if miss: out[loc.location_id] = miss
    return out


# ------------------------------------------------------------------ zones
def _inputs_hash(inputs):
    return "sha256:" + sha256_hex(canonical_json(inputs))


def build_zones(record, project_id):
    """Zones for the record's current inputs: one per usable location, in document order (S3 stub). A zone whose
    inputs (start fields, TA selection, advanced settings) are unchanged keeps its version and runs; a changed one that
    already has runs gets version + 1 and no current run (while it has none, edits only replace its inputs)."""
    old = {z["zone_id"]: z for z in record.get("zones") or []}
    zones = []
    for loc in sorted(locations_of(record), key=lambda l: l.ordinal):
        if not loc.usable or loc.role != wl.WORK: continue
        ghash = zone_geometry_hash([loc])
        zid = zone_id_for(ghash)
        eff = effective_inputs(record, loc.location_id)
        inputs = {**{f: eff[f] for f in START_FIELDS}, "ta_hypothesis": eff["ta_hypothesis"],
                  "advanced": record.get("advanced") or {}}
        ih = _inputs_hash(inputs)
        prev = old.get(zid)
        if prev and prev["inputs_hash"] == ih:
            zones.append(prev); continue
        runnable = loc.geometry["type"] == wl.POINT
        zones.append({
            "schema_version": SCHEMA_VERSION, "zone_id": zid, "version": (prev["version"] + (1 if prev["run_ids"] else 0)) if prev else 1,
            "location_ids": [loc.location_id],
            "grouping": {"method": ONE_PER_LOCATION, "rule_version": GROUPING_RULE_VERSION, "evidence": None},
            "ta": {"value": eff["ta_hypothesis"], "source": "UI", "status": "HYPOTHESIS"},
            "sheet_label": None, "inputs": inputs, "inputs_hash": ih, "engine_geometry_hash": ghash,
            "lineage_key": lineage_key(project_id, ghash),
            "run_ids": list(prev["run_ids"]) if prev else [], "current_run_id": None,
            "status": ZONE_PENDING if runnable else ZONE_NOT_SUPPORTED})
    return zones


def zone_engine_input(record, zone, project_id):
    """The write-once engine input of one zone run (<run_id>/input/zone_input.json). kml_reader.from_zone turns it
    into the pipeline's ProjectGeometry; project_id and lineage_key are carried for the run record only."""
    if zone["status"] == ZONE_NOT_SUPPORTED: raise ProjectInputError("ZONE_NOT_RUNNABLE", f"zone {zone['zone_id']} does not run in S3")
    by_id = {d["location_id"]: d for d in record["locations"]}
    return {"schema_version": SCHEMA_VERSION, "project_id": project_id, "lineage_key": zone["lineage_key"],
            "zone": {k: zone[k] for k in ("zone_id", "version", "sheet_label", "engine_geometry_hash")}
                    | {"ta_hypothesis": zone["inputs"]["ta_hypothesis"]},
            "locations": [by_id[i] for i in zone["location_ids"]],
            "start_fields": {f: zone["inputs"][f] for f in START_FIELDS},
            "advanced": zone["inputs"]["advanced"]}


def runnable_zones(zones):
    return [z for z in zones if z["status"] != ZONE_NOT_SUPPORTED]


def cap_exceeded(zones, max_zones):
    return len(runnable_zones(zones)) > max_zones


def cap_cleared(record, max_zones):
    """Within the cap, or approved for at least as many zones as there are now (an approval does not cover a bigger set)."""
    zones = record.get("zones") or []
    if not cap_exceeded(zones, max_zones): return True
    appr = record.get("cap_approval")
    return bool(appr) and appr.get("zone_count", 0) >= len(runnable_zones(zones))


def zones_hash(zones):
    """Identity of a zone set and its inputs: a Run request is for exactly this set."""
    return _inputs_hash(sorted([z["zone_id"], z["version"], z["inputs_hash"]] for z in zones))


# ------------------------------------------------------------------ status
DRAFT, REVIEW, NONE = "DRAFT", "REVIEW", "NONE"


def zone_outcome(state):
    """DRAFT, REVIEW or NONE for a finished zone run (see roll_up). draft_available is kept apart from the decision."""
    if state.get("draft_available") and state.get("decision") == SUPPORTED_AUTO: return DRAFT
    if state.get("decision") == REVIEW_REQUIRED or state.get("draft_available"): return REVIEW
    return NONE


def roll_up(record, zone_states, max_zones):
    """Project status (plan section 12; S3 Q6 as changed by the owner after commit 4).
    zone_states: {run_id: {"state": QUEUED|RUNNING|FINISHED, "draft_available": bool, "decision": str|None}} for the
    zones' current runs. Each finished zone is one of three outcomes (zone_outcome): DRAFT (a draft exists and the zone
    is SUPPORTED_AUTO), REVIEW (it finished REVIEW_REQUIRED, or has a draft that is not SUPPORTED_AUTO) or NONE (the run
    errored, was stopped or UNSUPPORTED_POC, or the zone never runs: a line or polygon zone in S3).

    INPUTS_REQUIRED  a location that would run lacks a start field
    READY            all fields typed; a zone has no run for its current inputs and no Run was asked for them
    ZONE_CAP_APPROVAL_REQUIRED  Run asked, more zones than max_zones, not approved: nothing runs
    RUNNING          Run asked and a zone is not finished (or not yet started)
    FAILED           every zone is NONE: all of them errored or never ran
    PARTIAL          some zones are DRAFT or REVIEW and some are NONE
    REVIEW_REQUIRED  no zone is NONE and at least one is REVIEW
    ALL_DRAFTED      every zone is DRAFT
    """
    if missing_fields(record): return INPUTS_REQUIRED
    zones = record.get("zones") or []
    runnable = runnable_zones(zones)
    requested = bool(record.get("run_request")) and record["run_request"].get("zones_hash") == zones_hash(zones)
    if not zones or any(z["current_run_id"] is None for z in runnable):
        if not requested: return READY
        if not cap_cleared(record, max_zones): return ZONE_CAP_APPROVAL_REQUIRED
        return RUNNING
    states = [zone_states.get(z["current_run_id"]) or {"state": QUEUED} for z in runnable]
    if any(s["state"] != FINISHED for s in states): return RUNNING
    outcomes = [zone_outcome(s) for s in states] + [NONE] * (len(zones) - len(runnable))   # lines and polygons never run
    if all(o == DRAFT for o in outcomes): return ALL_DRAFTED
    if all(o == NONE for o in outcomes): return FAILED
    if NONE in outcomes: return PARTIAL
    return REVIEW_REQUIRED
