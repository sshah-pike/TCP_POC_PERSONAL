"""Freeze the current rule pack as a sealed version under rule_pack/versions/<version>/ and append it to INDEX.json.

Run after `python scripts/seal_rule_pack.py` has sealed the current pack with a NEW version number:
    python scripts/seal_rule_pack_version.py --source-commit <full hash of the commit that holds the pack>

--register-existing registers a directory that is already under rule_pack/versions/ (a backfill from git) instead of
copying the current pack. It checks the hash and appends the entry; it copies nothing.

Never overwrites: an existing version directory or INDEX entry for the version stops the script.
"""
import argparse, datetime, json, os, shutil, sys
from tcp_planner.config.settings import RULE_PACK_DIR
from tcp_planner.rules.rule_pack_store import JsonRulePackStore, MANIFEST
from tcp_planner.rules.rule_pack_store import VERSIONS_DIR, INDEX


def _fail(msg):
    print("REFUSED:", msg); return 1


def main(argv=None, root=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-commit", required=True)
    ap.add_argument("--register-existing", metavar="VERSION")
    ap.add_argument("--expect-hash", help="stop unless the recomputed hash equals this")
    ap.add_argument("--note")
    a = ap.parse_args(argv)
    root = root or RULE_PACK_DIR
    vroot = os.path.join(root, VERSIONS_DIR)
    index_path = os.path.join(vroot, INDEX)
    index = json.load(open(index_path, encoding="utf-8")) if os.path.isfile(index_path) else {"schema_version": "1", "versions": []}

    src = os.path.join(vroot, a.register_existing) if a.register_existing else root
    store = JsonRulePackStore(src)
    m = store._manifest_doc()
    version = m["version"]
    if a.register_existing and a.register_existing != version: return _fail(f"directory {a.register_existing} holds version {version}")
    if any(e["version"] == version for e in index["versions"]): return _fail(f"version {version} is already in INDEX.json")
    dest = os.path.join(vroot, version)
    if not a.register_existing and os.path.exists(dest): return _fail(f"{dest} already exists")
    h = store.content_hash()
    if h != m.get("content_sha256"): return _fail(f"manifest hash {m.get('content_sha256')} differs from recomputed {h}; run seal_rule_pack.py")
    if a.expect_hash and h != a.expect_hash: return _fail(f"hash {h} differs from expected {a.expect_hash}")
    if not a.register_existing:
        for rel in [MANIFEST] + [p["path"] for p in m["parts"]]:
            os.makedirs(os.path.dirname(os.path.join(dest, *rel.split("/"))), exist_ok=True)
            shutil.copyfile(os.path.join(root, *rel.split("/")), os.path.join(dest, *rel.split("/")))
        if JsonRulePackStore(dest).content_hash() != h: return _fail("copy does not recompute to the same hash")
    entry = {"version": version, "content_sha256": h, "sealed_on": datetime.date.today().isoformat(),
             "source_commit": a.source_commit, "status": m["status"]}
    if a.note: entry["note"] = a.note
    index["versions"].append(entry)
    os.makedirs(vroot, exist_ok=True)
    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=2); f.write("\n")
    print(f"sealed {version} hash {h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
