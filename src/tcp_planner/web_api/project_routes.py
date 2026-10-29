"""Project routes of the local HTTP API (slice S3). dispatch() returns (status, body) like the assistant routes.

GET  /api/projects                          project list (id, name, status, zone count)
POST /api/projects                          one KML, point or offline scenario -> the project (201 new, 200 reopened)
GET  /api/projects/<id>                     the project: locations, labels, start fields, Select TA, zones, runs, status
POST /api/projects/<id>/inputs              the SME's typed start fields and Select TA (never filled by the server)
POST /api/projects/<id>/run                 start the zone runs; 409 START_FIELDS_MISSING until every field is typed
POST /api/projects/<id>/approve-cap         one click: run more zones than project.max_zones; approved_by is the typed
                                            name or "UI click" and is recorded as unverified (no user model before S10)

Errors: {"error": message, "error_code": code, ...details}. A KML with no usable location creates no project and answers
422 NO_USABLE_LOCATION with every location's rejection reasons.
"""
import base64, binascii

from tcp_planner.contracts import InputRejected
from tcp_planner.intake import kml_reader
from tcp_planner.orchestration import offline_scenarios as offline, projects as P
from tcp_planner.orchestration.pipeline import load_config
from tcp_planner.storage import run_store as store
from tcp_planner.storage.interfaces import StorageError

STATUS_BY_CODE = {"START_FIELDS_MISSING": 409, "CAP_NOT_EXCEEDED": 409, "NO_RUNNABLE_ZONE": 409,
                  "NO_USABLE_LOCATION": 422}  # anything else a ProjectInputError raises is a 400
ADVANCED_KEYS = ("map_provider", "ai_provider", "ai_profile", "evidence_mode", "dwt_mode", "no_dwt")


class NoUsableLocation(Exception):
    """The file itself was rejected (not XML, not KML, too large): there is nothing to list per location."""
    def __init__(self, reason_codes, message):
        super().__init__(message); self.reason_codes = list(reason_codes); self.message = message


def _err(status, code, message, **details):
    return status, {"error": message, "error_code": code, **details}


def location_rows(locations):
    return [{"location_id": l.location_id, "ordinal": l.ordinal, "label": l.display_label,
             "type": (l.geometry or {}).get("type"), "reject_reasons": list(l.reject_reasons)} for l in locations]


def _advanced(payload, online, check_ai):
    adv = payload.get("advanced") or {}
    if not isinstance(adv, dict): raise store.BadRequest("advanced must be an object")
    adv = {k: adv[k] for k in ADVANCED_KEYS if adv.get(k) not in (None, "", False)}
    if adv.get("ai_profile"): check_ai(adv)           # a configured, available Foundry profile (the server decides)
    store.advanced_args(adv, online)                   # shape checks, same as a plain run
    return adv


def _locations_of(payload):
    """(kind, display name, locations, upload or None, offline scenario or None) from the form payload."""
    itype = payload.get("input_type")
    if itype == "kml":
        f = payload.get("kml") or {}
        try: raw = base64.b64decode(f.get("content_base64") or "", validate=True)
        except (ValueError, binascii.Error): raise store.BadRequest("KML content is not valid base64")
        if not raw: raise store.BadRequest("KML file is empty")
        if len(raw) > store.MAX_KML_UPLOAD_BYTES: raise store.BadRequest("KML upload too large")
        name = store._safe_filename(f.get("filename"))
        try: locs = kml_reader.parse_all(raw, duplicate_distance_m=load_config()["input"]["duplicate_distance_m"], file_name=name)
        except InputRejected as e: raise NoUsableLocation(e.reason_codes, e.message)  # the file could not be read at all
        return P.KML, name, locs, (name, raw), None
    if itype == "coordinates":
        lat, lon = str(payload.get("lat", "")).strip(), str(payload.get("lon", "")).strip()
        if not lat or not lon: raise store.BadRequest("latitude and longitude are required")
        try: loc = kml_reader.location_from_coordinates(lat, lon)
        except InputRejected as e: raise store.BadRequest(e.message)
        return P.COORDINATES, "Coordinates", [loc], None, None
    if itype == "offline":
        sc = payload.get("offline_scenario")
        if sc not in set(offline.SCENARIOS) | set(offline.ALIASES): raise store.BadRequest("unknown offline scenario")
        sc = offline.ALIASES.get(sc, sc)
        o = offline.build(sc)
        return P.OFFLINE, f"Offline: {sc}", [kml_reader.location_from_coordinates(o["lat"], o["lon"])], None, sc
    raise store.BadRequest("input_type must be kml, coordinates or offline")


def dispatch(method, parts, payload, runner, check_ai=lambda adv: None):
    """parts: the path after /api/projects. -> (status, body)."""
    try:
        if not parts:
            if method == "GET": return 200, runner.list()
            kind, name, locs, upload, scenario = _locations_of(payload)
            adv = _advanced(payload, kind != P.OFFLINE, check_ai)
            try: view, created = runner.open_or_create(name=name, kind=kind, locations=locs, upload=upload,
                                                       advanced=adv, offline_scenario=scenario)
            except P.ProjectInputError as e:
                if e.code != "NO_USABLE_LOCATION": raise
                return _err(422, e.code, "no usable work location in the input; every location was rejected",
                            locations=location_rows(locs), file_reasons=[])
            return (201 if created else 200), {**view, "created": created, "location_rows": location_rows(locs)}
        pid = parts[0]
        view = runner.view(pid)
        if view is None: return _err(404, "PROJECT_NOT_FOUND", "project not found")
        if len(parts) == 1 and method == "GET": return 200, view
        if len(parts) == 2 and method == "POST":
            if parts[1] == "inputs":
                allowed = ("project", "apply_to_all", "per_location", "ta_project", "ta_per_location")
                bad = [k for k in payload if k not in allowed]
                if bad: raise store.BadRequest(f"unknown field {bad[0]!r}")
                runner.set_inputs(pid, **{k: payload[k] for k in allowed if k in payload})
                return 200, runner.view(pid)
            if parts[1] == "run": return 200, runner.run(pid)
            if parts[1] == "approve-cap":
                return 200, runner.approve_cap(pid, str(payload.get("approved_by") or "").strip() or None)
        return _err(404, "NOT_FOUND", "not found")
    except NoUsableLocation as e:
        return _err(422, "NO_USABLE_LOCATION", e.message, locations=[], file_reasons=e.reason_codes)
    except P.ProjectInputError as e:
        return _err(STATUS_BY_CODE.get(e.code, 400), e.code, e.message, **e.details)
    except (store.BadRequest, StorageError) as e:
        return _err(400, "BAD_REQUEST", str(e))
