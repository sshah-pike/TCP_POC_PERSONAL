"""Schema migrations for persisted records. One function per (kind, from_version) step, each producing from_version + 1.

A migration is pure: the same input gives the same output. migrate() returns the migrated value and a report with the
canonical sha256 of the input and of the output, so a migration can be re-run and compared (hash-verified).
"""
import copy

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.storage.interfaces import SchemaVersionError

_STEPS = {}  # (kind, from_version) -> function(value: dict) -> dict


def register(kind, from_version):
    def deco(fn):
        key = (kind, int(from_version))
        if key in _STEPS: raise SchemaVersionError(f"migration {key} registered twice")
        _STEPS[key] = fn
        return fn
    return deco


def migrate(kind, value, from_version, to_version):
    """(migrated value, report). Raises SchemaVersionError for a downgrade or a gap in the chain."""
    from_version, to_version = int(from_version), int(to_version)
    if from_version > to_version:
        raise SchemaVersionError(f"{kind}: record schema_version {from_version} is newer than supported {to_version}")
    report = {"kind": kind, "from_version": from_version, "to_version": to_version,
              "input_sha256": sha256_hex(canonical_json(value)), "steps": []}
    cur = copy.deepcopy(value)
    for v in range(from_version, to_version):
        fn = _STEPS.get((kind, v))
        if fn is None: raise SchemaVersionError(f"{kind}: no migration from schema_version {v} to {v + 1}")
        out = fn(copy.deepcopy(cur))
        if not isinstance(out, dict): raise SchemaVersionError(f"{kind}: migration {v} to {v + 1} did not return an object")
        report["steps"].append({"from": v, "to": v + 1, "output_sha256": sha256_hex(canonical_json(out))})
        cur = out
    report["output_sha256"] = sha256_hex(canonical_json(cur))
    return cur, report


def read_current(state, key, kind, current_version):
    """The record's value at current_version (migrated in memory; the stored record is not changed), or None."""
    rec = state.get(key)
    if rec is None: return None
    if rec.schema_version == current_version: return rec.value
    return migrate(kind, rec.value, rec.schema_version, current_version)[0]
