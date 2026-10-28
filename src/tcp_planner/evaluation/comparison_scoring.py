"""Score a comparison's child runs against the site's human label (read-only; changes nothing).

Per field: CORRECT (resolved and equals the confirmed label), FALSE_RESOLUTION (resolved but wrong - the primary
safety metric), UNRESOLVED (the pipeline did not resolve it), NO_LABEL. Scores count only when the label is
CONFIRMED; with a DRAFT label every row is shown but marked "not scored". A model is never rated by its decision.
"""
import json

from tcp_planner.storage import run_store as store
from tcp_planner.evaluation import ground_truth_labels as labels
from tcp_planner.orchestration import run_relations as relations

EVIDENCE_KEY = {"road.lane_count": "lane_count", "road.two_way": "two_way", "road.divided": "divided",
                "road.traveled_way_width_m": "road_edges", "work.side": "work_side", "work.location": "work_location",
                "work.encroaches_traveled_way": "work_location", "work.affects_pedestrian_route": "pedestrian",
                "site.complex_intersection_conflict": "intersections"}
CHECK_FOR = {"work.location": "C1_WORK_VS_DISTANCE", "work.encroaches_traveled_way": "C1_WORK_VS_DISTANCE",
             "road.traveled_way_width_m": "C2_WIDTH_VS_EDGES", "work.side": "C3_SIDE_VS_GEOMETRY",
             "site.complex_intersection_conflict": "C4_JUNCTIONS_VS_OSM"}


def predicted(run_id):
    sm = store._read_json(store.run_path(run_id, "output", "site_model.json"))
    el = store._read_json(store.run_path(run_id, "output", "eligibility_result.json"))
    if not sm: return None
    r, w = sm["road"], sm["work"]
    f = lambda x: (x.get("value"), x.get("status"), x.get("confidence"))
    edges = r["road_edges"]
    ic = ((el or {}).get("detected_facts") or {}).get("site.complex_intersection_conflict") or {}
    return {"road.lane_count": f(r["lane_count"]), "road.two_way": f(r["two_way"]), "road.divided": f(r["divided"]),
            "road.traveled_way_width_m": (edges.get("traveled_way_width_m"), edges.get("status"),
                                          next((o.get("confidence") for o in edges.get("observations", []) if o.get("source") == "AI"), None)),
            "work.side": f(w["side"]), "work.location": f(w["location"]),
            "work.encroaches_traveled_way": f(w["encroaches_traveled_way"]),
            "work.affects_pedestrian_route": f(w["affects_pedestrian_route"]),
            "site.complex_intersection_conflict": (ic.get("value"), ic.get("status"),
                                                   (sm.get("feature_confidence") or {}).get("intersection_conflict"))}


def _match(field, value, label):
    if field == "road.traveled_way_width_m":
        tol = label.get("tolerance") or 1.0
        return value is not None and abs(float(value) - float(label["value"])) <= tol
    return value == label["value"]


def evaluate_comparison(cid):
    rep = relations.comparison_state(cid)
    if rep is None: return None
    pg = store._read_json(store.run_path(rep["source_run_id"], "output", "project_geometry.json"))
    label = labels.get(labels.site_id_for(pg)) if pg else None
    confirmed = bool(label and label["status"] == "CONFIRMED")
    cols = []
    for c in rep["columns"]:
        pred = predicted(c["run_id"]) or {}
        g = c.get("grounding") or {}
        checks = {x["id"]: x for x in g.get("checks") or []}
        rows, counts = [], {"CORRECT": 0, "FALSE_RESOLUTION": 0, "UNRESOLVED": 0, "NO_LABEL": 0}
        for field in labels.FIELDS:
            value, status, conf = pred.get(field, (None, "NOT_RUN", None))
            lab = (label or {}).get("fields", {}).get(field)
            if status != "RESOLVED": outcome = "UNRESOLVED"
            elif not lab or lab.get("value") is None: outcome = "NO_LABEL"
            else: outcome = "CORRECT" if _match(field, value, lab) else "FALSE_RESOLUTION"
            counts[outcome] += 1
            ev = (g.get("evidence") or {}).get(EVIDENCE_KEY[field]) or {}
            rows.append({"field": field, "predicted": value, "status": status, "confidence": conf,
                         "label": lab.get("value") if lab else None, "outcome": outcome, "scored": confirmed,
                         "evidence": ev.get("basis"), "evidence_image": ev.get("image"),
                         "check": (checks.get(CHECK_FOR.get(field)) or {}).get("result")})
        cols.append({k: c.get(k) for k in ("run_id", "profile", "label", "vision_mode", "evidence_mode", "decision",
                                           "ai_status", "ai_error", "schema_errors", "ai_duration_ms", "usage",
                                           "estimated_cost_usd", "model")}
                    | {"rows": rows, "counts": counts, "checks": g.get("checks"), "measurements": g.get("measurements"),
                       "images": g.get("images"), "osm_claim_checks": g.get("osm_claim_checks")})
    return {"comparison_id": cid, "source_run_id": rep["source_run_id"], "complete": rep["complete"],
            "label": {k: (label or {}).get(k) for k in ("site_id", "status", "confirmed_by", "confirmed_at", "confirm_reason",
                                                        "drafted_by", "drafted_at")} if label else None,
            "scored": confirmed,
            "note": ("Scored against the CONFIRMED label." if confirmed else
                     "NOT SCORED - the site label is not confirmed by a person; outcomes are shown against the draft only.")
                    + " Primary safety metric: FALSE_RESOLUTION. Decisions (SUPPORTED_AUTO etc.) are not a score.",
            "columns": cols}
