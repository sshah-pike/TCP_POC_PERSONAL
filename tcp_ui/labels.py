"""Human ground-truth labels for evaluation sites (draft -> confirmed by a person).

labels/<site_id>.json   site_id = first 16 hex chars of the work-reference geometry hash
Only CONFIRMED labels count as evaluation ground truth. A draft (for example prepared from evidence by an
assistant) is shown but never scored. Confirmation requires a reviewer name and a reason; every change is
appended to the label's history with a timestamp. No credentials or URLs are stored.
"""
import datetime, json, os, re

from . import store

FIELDS = {  # label field -> (type, allowed values) ; compared against the pipeline's resolved site facts
    "road.lane_count": (int, None),
    "road.two_way": (bool, None),
    "road.divided": (bool, None),
    "road.traveled_way_width_m": (float, None),
    "work.side": (str, ("LEFT", "RIGHT")),
    "work.location": (str, ("TRAVELED_WAY", "SHOULDER", "BEYOND_SHOULDER")),
    "work.encroaches_traveled_way": (bool, None),
    "work.affects_pedestrian_route": (bool, None),
    "site.complex_intersection_conflict": (bool, None),
}
SITE_RE = re.compile(r"^[0-9a-f]{16}$")


def labels_dir():
    return os.environ.get("TCP_UI_LABELS_DIR") or os.path.join(store.PROJECT_ROOT, "labels")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def site_id_for(project_geometry):
    from .evidence import geometry_hash
    return geometry_hash(project_geometry)[:16]


def _path(site_id):
    if not SITE_RE.match(site_id or ""): raise store.BadRequest("invalid site id")
    return os.path.join(labels_dir(), f"{site_id}.json")


def get(site_id):
    try:
        with open(_path(site_id), encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return None


def list_labels():
    d = labels_dir()
    try: names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except OSError: return []
    return [x for x in (get(n[:-5]) for n in names) if x]


def _check_value(field, value):
    if field not in FIELDS: raise store.BadRequest(f"unknown label field {field!r}")
    typ, allowed = FIELDS[field]
    if value is None: return None
    if typ is float and isinstance(value, (int, float)) and not isinstance(value, bool): value = float(value)
    if typ is int and isinstance(value, bool) or not isinstance(value, typ):
        raise store.BadRequest(f"{field} must be {typ.__name__}")
    if allowed and value not in allowed: raise store.BadRequest(f"{field} must be one of {allowed}")
    return value


def _write(doc):
    os.makedirs(labels_dir(), exist_ok=True)
    tmp = _path(doc["site_id"]) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(doc, f, indent=2, sort_keys=True)
    os.replace(tmp, _path(doc["site_id"]))


def save_draft(project_geometry, fields, drafted_by, reason, source_run_id, name=None):
    """Create or replace a DRAFT label. A confirmed label is never overwritten by a draft."""
    sid = site_id_for(project_geometry)
    existing = get(sid)
    if existing and existing["status"] == "CONFIRMED":
        raise store.BadRequest("label is already confirmed; drafts cannot overwrite it")
    if not drafted_by or not reason: raise store.BadRequest("drafted_by and reason are required")
    out = {}
    for k, f in fields.items():
        out[k] = {"value": _check_value(k, f.get("value")), "tolerance": f.get("tolerance"), "note": f.get("note"),
                  "evidence": f.get("evidence") or []}
    doc = {"site_id": sid, "name": name, "work_reference": project_geometry["work_reference"],
           "work_path": project_geometry.get("work_path") or [], "source_run_id": source_run_id,
           "status": "DRAFT", "fields": out, "drafted_by": drafted_by, "drafted_at": _now(),
           "confirmed_by": None, "confirmed_at": None, "confirm_reason": None,
           "history": (existing or {}).get("history", []) + [{"action": "draft", "by": drafted_by, "at": _now(), "reason": reason}]}
    _write(doc)
    return doc


def confirm(site_id, reviewer, reason, edits=None):
    """A PERSON confirms (optionally correcting values first). Required: reviewer and reason."""
    doc = get(site_id)
    if not doc: raise store.BadRequest("label not found")
    reviewer, reason = (reviewer or "").strip(), (reason or "").strip()
    if not reviewer or not reason: raise store.BadRequest("reviewer and reason are required to confirm a label")
    changes = []
    for k, v in (edits or {}).items():
        v = _check_value(k, v)
        old = doc["fields"].get(k, {}).get("value")
        if old != v:
            doc["fields"].setdefault(k, {"tolerance": None, "note": None, "evidence": []})["value"] = v
            changes.append({"field": k, "from": old, "to": v})
    doc.update(status="CONFIRMED", confirmed_by=reviewer, confirmed_at=_now(), confirm_reason=reason)
    doc["history"].append({"action": "confirm", "by": reviewer, "at": doc["confirmed_at"], "reason": reason, "changes": changes})
    _write(doc)
    return doc


def revoke(site_id, reviewer, reason):
    doc = get(site_id)
    if not doc: raise store.BadRequest("label not found")
    if not (reviewer or "").strip() or not (reason or "").strip(): raise store.BadRequest("reviewer and reason are required")
    doc.update(status="DRAFT", confirmed_by=None, confirmed_at=None, confirm_reason=None)
    doc["history"].append({"action": "revoke", "by": reviewer.strip(), "at": _now(), "reason": reason.strip()})
    _write(doc)
    return doc
