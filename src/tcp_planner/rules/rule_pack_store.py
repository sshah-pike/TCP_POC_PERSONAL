"""RulePackStore for rule pack v1: the only module that reads rule-pack files (D-30, ADR-027).

Layout under the pack root (`rule_pack/` by default): `pack.json` (manifest) plus the part files it lists
(`base/*.json`, `ta/*.json`, `jurisdiction/*.json`, `client/*.json`). The POC pack in the same folder is read only by
the legacy `rule_pack_loader.py`; the pipeline still uses it until the switch-over is approved.

Hashing: each part is hashed as canonical JSON (sorted keys, compact, UTF-8), so line endings and key order do not
matter. The pack hash covers the manifest (without its hash fields) and every part hash, so changing any record in any
part changes it.
"""
import json, os
from tcp_planner.config.settings import RULE_PACK_DIR
from tcp_planner.contracts import RulePackError, canonical_json, sha256_hex
from tcp_planner.rules.rule_pack_models import TABLES, Manifest, Part
from tcp_planner.rules.rule_pack_validator import validate
from tcp_planner.storage.interfaces import RulePackStore

MANIFEST = "pack.json"
VERSIONS_DIR = "versions"
INDEX = "INDEX.json"
NO_TA_MATCH = "NO_TA_MATCH"


def _need(cond, code, msg, **details):
    if not cond: raise RulePackError(code, msg, details)


def _read_json(path, what):
    _need(os.path.isfile(path), "RULE_PACK_MISSING", f"{what} not found: {os.path.basename(path)}")
    try:
        with open(path, "rb") as f: return json.loads(f.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise RulePackError("RULE_PACK_PARSE_FAILED", f"{what} is not valid JSON: {e}")


def part_hash(part_doc):
    return sha256_hex(canonical_json(part_doc))


def pack_hash(manifest_doc, part_hashes):
    """Hash of the manifest without its hash fields plus every part's hash, keyed by path."""
    m = {k: v for k, v in manifest_doc.items() if k != "content_sha256"}
    m["parts"] = [{k: v for k, v in p.items() if k != "sha256"} for p in m.get("parts", [])]
    return sha256_hex(canonical_json({"manifest": m, "parts": dict(sorted(part_hashes.items()))}))


class RulePack:
    """A loaded, hash-checked pack. Records are frozen Pydantic models; lookups go by id."""

    def __init__(self, manifest, parts):
        self.manifest = manifest
        self._located = []   # (part path, layer, table, record)
        for path, layer, part in parts:
            for table, rows in part.tables.items():
                model = TABLES[table]
                for row in rows:
                    try: rec = model.model_validate(row)
                    except ValueError as e:
                        raise RulePackError("RULE_PACK_RECORD_INVALID", f"{path}: {table} record {row.get('id')!r} invalid",
                                            {"part": path, "table": table, "id": row.get("id"), "error": str(e)})
                    self._located.append((path, layer, table, rec))
        self.by_id = {rec.id: rec for _, _, _, rec in self._located}

    @property
    def id(self): return self.manifest.pack_id

    @property
    def version(self): return self.manifest.version

    @property
    def hash(self): return self.manifest.content_sha256

    @property
    def ref(self): return {"id": self.id, "version": self.version, "hash": self.hash}

    def located_records(self): return list(self._located)

    def all_records(self): return [(t, r) for _, _, t, r in self._located]

    def records(self, table): return [r for _, _, t, r in self._located if t == table]

    def get(self, record_id):
        _need(record_id in self.by_id, "RULE_PACK_RECORD_MISSING", f"no record {record_id}", id=record_id)
        return self.by_id[record_id]

    def ta(self, ta_id):
        """The TA record, or NO_TA_MATCH for any TA the pack does not define (only the manifest's ta_scope exist)."""
        hit = [t for t in self.records("ta") if t.id == ta_id]
        return hit[0] if hit else NO_TA_MATCH

    def trace(self, record_id):
        """Trace fields for a plan object built from this record (CLAUDE.md core rule 9)."""
        rec = self.get(record_id)
        refs = [self.get(s) for s in getattr(rec, "source_ref_ids", []) or []]
        return {"rule_id": rec.id, "pack_id": self.id, "pack_version": self.version, "pack_hash": self.hash,
                "status": getattr(getattr(rec, "status", None), "value", None),
                "source_refs": [{"source_ref_id": s.id, "source_document_id": s.source_document_id, "section": s.section,
                                 "paragraph": s.paragraph, "table": s.table, "figure": s.figure, "note": s.note,
                                 "page": s.page_printed, "strength": s.strength.value, "evidence": s.evidence.value}
                                for s in refs]}


class JsonRulePackStore(RulePackStore):
    """Local JSON adapter. A later adapter reads SQL; callers only see these methods."""

    def __init__(self, root=None):
        self.root = root or RULE_PACK_DIR

    def _manifest_doc(self):
        return _read_json(os.path.join(self.root, MANIFEST), "rule pack manifest")

    def _part_path(self, rel):
        _need(not os.path.isabs(rel) and ".." not in rel.split("/") and "\\" not in rel, "RULE_PACK_PART_PATH_INVALID",
              f"part path must be relative with forward slashes: {rel}", path=rel)
        return os.path.join(self.root, *rel.split("/"))

    def _part_docs(self, manifest_doc):
        return {p["path"]: _read_json(self._part_path(p["path"]), f"rule pack part {p['path']}")
                for p in manifest_doc.get("parts", [])}

    def _index(self):
        """Sealed versions in sealing order (rule_pack/versions/INDEX.json); empty when the pack has no versions folder."""
        path = os.path.join(self.root, VERSIONS_DIR, INDEX)
        return _read_json(path, "rule pack version index")["versions"] if os.path.isfile(path) else []

    def _store_for(self, version):
        """The store that holds `version`: this root for the current pack (None or its version), else the frozen copy."""
        current = self._manifest_doc().get("version")
        if version in (None, current): return self
        entry = next((e for e in self._index() if e["version"] == version), None)
        _need(entry is not None, "RULE_PACK_VERSION_MISSING", f"no rule pack version {version}", version=version)
        folder = os.path.join(self.root, VERSIONS_DIR, version)
        _need(os.path.isdir(folder), "RULE_PACK_VERSION_MISSING", f"sealed folder for {version} is missing", version=version)
        sub = JsonRulePackStore(folder)
        actual = sub.content_hash()
        _need(actual == entry["content_sha256"], "RULE_PACK_HASH_MISMATCH", f"sealed version {version} differs from INDEX.json",
              expected=entry["content_sha256"], actual=actual)
        return sub

    def list_versions(self):
        """Every sealed version in order, then the current pack's version if it is not sealed yet. The last is the latest."""
        if not os.path.isfile(os.path.join(self.root, MANIFEST)): return []
        versions = [e["version"] for e in self._index()]
        current = self._manifest_doc().get("version")
        return versions if current in versions else versions + [current]

    def content_hash(self, version=None):
        """The pack hash recomputed from the files on disk."""
        s = self._store_for(version)
        m = s._manifest_doc()
        return pack_hash(m, {p: part_hash(d) for p, d in s._part_docs(m).items()})

    def load(self, version=None, validate_pack=True):
        s = self._store_for(version)
        if s is not self: return s.load(validate_pack=validate_pack)
        m_doc = self._manifest_doc()
        try: manifest = Manifest.model_validate(m_doc)
        except ValueError as e: raise RulePackError("RULE_PACK_HEADER_INCOMPLETE", f"manifest invalid: {e}")
        docs = self._part_docs(m_doc)
        parts = []
        for pref in manifest.parts:
            actual = part_hash(docs[pref.path])
            _need(actual == pref.sha256, "RULE_PACK_HASH_MISMATCH", f"part {pref.path} hash mismatch",
                  part=pref.path, expected=pref.sha256, actual=actual)
            try: part = Part.model_validate(docs[pref.path])
            except ValueError as e: raise RulePackError("RULE_PACK_RECORD_INVALID", f"part {pref.path} invalid: {e}")
            _need(part.layer == pref.layer, "RULE_PACK_LAYER_MISMATCH", f"part {pref.path} layer differs from manifest")
            parts.append((pref.path, part.layer, part))
        actual = pack_hash(m_doc, {p: part_hash(d) for p, d in docs.items()})
        _need(actual == manifest.content_sha256, "RULE_PACK_HASH_MISMATCH", "pack content hash mismatch",
              expected=manifest.content_sha256, actual=actual)
        pack = RulePack(manifest, parts)
        if validate_pack:
            report = validate(pack)
            _need(report.ok, "RULE_PACK_INVALID", f"{len(report.errors)} validation errors", errors=report.errors)
        return pack


def seal(root=None):
    """Authoring helper: write every part hash and the pack hash into the manifest. Returns the pack hash."""
    store = JsonRulePackStore(root)
    m = store._manifest_doc(); docs = store._part_docs(m)
    for p in m["parts"]: p["sha256"] = part_hash(docs[p["path"]])
    m["content_sha256"] = pack_hash(m, {p: part_hash(d) for p, d in docs.items()})
    with open(os.path.join(store.root, MANIFEST), "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, ensure_ascii=False, indent=2); f.write("\n")
    return m["content_sha256"]
