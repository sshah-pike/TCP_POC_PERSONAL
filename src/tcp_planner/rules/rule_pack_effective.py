"""Effective-rules view over rule pack v1 (plan section 10): federal, jurisdiction, client, deviation, in that order.

For a TA and a topic, the records that apply come from the latest layer that has any; earlier layers' records are
listed as overridden, with every source still visible. Inside one layer a record replaces the records named in its
`overlaps` (a TA note over the shared section it restates), so nothing is applied twice. CITED_ONLY records are never
applied. In v1 only the federal layer is populated (S4 scope change), so overrides cannot occur yet.

The lookups return values with their trace and never invent one: a key the source table does not print (a speed
between Table 6B-2 rows, an unknown road type) gives SOURCE_REVIEW_REQUIRED or UNKNOWN, not an interpolation.
"""
from tcp_planner.rules.rule_pack_eval import eval_expr
from tcp_planner.rules.rule_pack_models import Layer, Status

LAYER_ORDER = (Layer.FEDERAL, Layer.JURISDICTION, Layer.CLIENT, Layer.DEVIATION)
_RANK = {layer: i for i, layer in enumerate(LAYER_ORDER)}


def effective_rules(pack, topic, ta_id=None, facts=None):
    """{topic, ta_id, applied: [...], superseded: [...], overridden: [...], cited_only: [...]} for one topic.

    Each applied entry is {rule_id, layer, strength, status, applies, trace}; `applies` is the rule's condition on the
    given facts (True, False, or None when a fact is missing; True for a rule without a condition).
    """
    rules = [r for r in pack.records("rule") if r.topic == topic and r.ta_id in (None, ta_id)]
    cited = [r for r in rules if r.role == "CITED_ONLY"]
    live = [r for r in rules if r.role == "APPLY"]
    top = max((_RANK[r.layer] for r in live), default=None)
    winners = [r for r in live if _RANK[r.layer] == top]
    overridden = [r for r in live if _RANK[r.layer] != top]
    replaced = {o for r in winners for o in r.overlaps}
    applied = [r for r in winners if r.id not in replaced]
    superseded = [r for r in winners if r.id in replaced]

    def entry(r):
        cond = r.condition
        return {"rule_id": r.id, "layer": r.layer.value, "strength": r.strength.value if r.strength else None,
                "status": r.status.value, "applies": True if cond is None else eval_expr(cond, facts or {}),
                "trace": pack.trace(r.id)}

    return {"topic": topic, "ta_id": ta_id, "applied": [entry(r) for r in applied],
            "superseded": [{"rule_id": r.id, "by": [w.id for w in applied if r.id in w.overlaps]} for r in superseded],
            "overridden": [{"rule_id": r.id, "layer": r.layer.value} for r in overridden],
            "cited_only": [{"rule_id": r.id, "overlaps": list(r.overlaps)} for r in cited]}


def _row(pack, table_def_id, key):
    hits = [r for r in pack.records("table_row") if r.table_def_id == table_def_id and r.key == key]
    return hits[0] if hits else None


def _value(pack, row, field, unit, **extra):
    return {"status": row.status.value, "value": row.values[field], "unit": unit, "record_id": row.id,
            "layer": Layer.FEDERAL.value, "trace": pack.trace(row.id), **extra}


def advance_sign_spacing(pack, road_type, dimension):
    """Table 6B-1 distance for the SME's road type and dimension A, B or C (Guidance, per Sect. 6B.04 para 07)."""
    row = _row(pack, "T-6B1", {"road_type": road_type})
    if row is None or dimension not in row.values:
        return {"status": Status.UNKNOWN.value, "value": None, "unit": "ft", "record_id": None,
                "reason": f"Table 6B-1 has no row for road type {road_type!r} and dimension {dimension!r}"}
    return _value(pack, row, dimension, "ft", strength="GUIDANCE")


def buffer_length(pack, posted_speed_mph, ta_id=None):
    """Longitudinal buffer length from the effective rules for the speed.

    The applicable rule decides the source. In v1 that is the federal Option (Sect. 6B.06 para 11): Table 6B-2, read
    by exact speed row. A higher layer with a buffer value would win where its condition holds; none exists in v1.
    """
    view = effective_rules(pack, "longitudinal_buffer", ta_id, {"posted_speed_mph": posted_speed_mph})
    for e in view["applied"]:
        rule = pack.get(e["rule_id"])
        if e["applies"] is not True: continue
        if rule.value is not None and rule.unit == "ft":
            return {"status": rule.status.value, "value": rule.value, "unit": "ft", "record_id": rule.id,
                    "layer": rule.layer.value, "strength": e["strength"], "trace": e["trace"], "rule": rule.id}
        if rule.action == "BUFFER_LENGTH_FROM_T-6B2":
            row = _row(pack, "T-6B2", {"speed_mph": posted_speed_mph})
            if row is None:
                return {"status": Status.SOURCE_REVIEW_REQUIRED.value, "value": None, "unit": "ft", "record_id": None,
                        "rule": rule.id, "reason": f"Table 6B-2 has no row for {posted_speed_mph} mph; no value is interpolated"}
            return _value(pack, row, "distance_ft", "ft", strength=e["strength"], rule=rule.id)
    return {"status": Status.UNKNOWN.value, "value": None, "unit": "ft", "record_id": None,
            "reason": "no applicable buffer rule"}
