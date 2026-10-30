"""One-time migration of assets/symbols/device_catalog.json from v0.1 to v0.2 (S5). Review the result as a git diff.

Run once: python scripts/migrate_device_catalog_v02.py   (refuses to run on a file that is not v0.1)

What changes (owner decisions Q3, Q5, Q6, Q9, Q10):
- schema_version "1" added; each asset becomes {uri, sha256, size, media_type, status} (Q6); seal fills sha256 and size.
- `used_by_tas` is removed; "used by" is derived from the pack's ta_device_use rows (Q5).
- `size_in` is removed. Sign sizes live as sourced rows in the rule pack (S4b adds them); the v0.1 numbers stay in git
  history only and are never read by code. Non-sign devices keep their v0.1 text as `size_text`, informational (Q10).
- `size_source` is new: PACK for the 12 signs a TA uses or a TA note cites (plan Q2 option A, to be confirmed by S4b),
  NOT_IN_MVP_PACK for the other MUTCD signs, TEXT_ONLY for devices, SOURCE_REVIEW_REQUIRED for the 4 client and state codes.
- `printed_as` is new: only the comparison-only alias M4-A8 for M4-8a, status PROPOSED. No alias for police, W20-8,
  client sign codes or client modules (out of scope).
- the per-entry `version` is removed (the catalog has one catalog_version).
"""
import json, os, sys
from tcp_planner.config.settings import DEVICE_CATALOG_PATH
from tcp_planner.rules.device_catalog import seal

PACK_SIZED = {"W20-1", "W20-4", "W20-5R", "W20-5L", "W20-7", "W21-5", "W5-1", "W4-2R", "W4-2L", "W3-4", "W16-2P", "G20-2"}
ALIASES = {"M4-8a": [{"code": "M4-A8", "status": "PROPOSED"}]}


def _size_text(v):
    if isinstance(v, dict): return "; ".join(f"{k}: {x}" for k, x in v.items())
    return v


def _size_source(e):
    if e["code_status"] == "DEVICE": return "TEXT_ONLY"
    if e["size_in"] == "SOURCE_REVIEW_REQUIRED": return "SOURCE_REVIEW_REQUIRED"
    return "PACK" if e["id"] in PACK_SIZED else "NOT_IN_MVP_PACK"


def migrate(old):
    entries = []
    for e in old["entries"]:
        entries.append({
            "device_id": e["id"], "mutcd_code": e["mutcd_code"], "printed_as": ALIASES.get(e["id"], []),
            "code_status": e["code_status"], "name": e["name"], "category": e["category"],
            "size_source": _size_source(e), "size_text": _size_text(e["size_in"]) if e["code_status"] == "DEVICE" else "",
            "source": e["source"],
            "asset": {"uri": "symbols/" + e["asset"]["file"], "sha256": "0" * 64, "size": 0,
                      "media_type": "image/svg+xml", "status": e["asset"]["status"]},
            "notes": e["notes"], "observed_in_drafts": e["observed_in_drafts"]})
    return {"schema_version": "1", "catalog_version": "0.2", "status": old["status"], "sources": old["sources"],
            "catalog_hash": "", "entries": entries}


def main():
    with open(DEVICE_CATALOG_PATH, encoding="utf-8") as f: old = json.load(f)
    if old.get("catalog_version") != "0.1": print("not a v0.1 catalog; nothing done"); return 1
    with open(DEVICE_CATALOG_PATH, "w", encoding="utf-8") as f: json.dump(migrate(old), f, indent=1, ensure_ascii=False)
    print("catalog hash", seal())
    return 0


if __name__ == "__main__":
    sys.exit(main())
