"""RulePackStore, models and validator on a small synthetic pack (S4). The numbers here are test data, not the pack."""
import copy, json, os
import pytest
from tcp_planner.contracts import RulePackError
from tcp_planner.rules.rule_pack_store import NO_TA_MATCH, JsonRulePackStore, seal
from tcp_planner.rules.rule_pack_validator import normalize_text, number_in_text, validate

SHA = "0" * 64
QUOTE = "Urban (low speed)* 100 feet 100 feet 100 feet"


def _ref(id_, **kw):
    r = {"id": id_, "source_document_id": "SD-1", "section": "6B.06", "paragraph": None, "table": "6B-1", "figure": None,
         "note": None, "page_printed": "773", "page_pdf": 9, "strength": "GUIDANCE", "evidence": "QUOTE", "quote": QUOTE,
         "transcription": None, "figure_render": None}
    r.update(kw); return r


def _parts():
    base = {"schema_version": "1", "layer": "FEDERAL", "tables": {
        "source_document": [{"id": "SD-1", "title": "Chapter 6", "publisher": "FHWA", "edition": "11th", "revision": "December 2023",
                             "authority_level": "FEDERAL",
                             "artifact": {"uri": "docs/x.pdf", "sha256": SHA, "size": 5, "media_type": "application/pdf"}}],
        "source_ref": [_ref("SR-1")],
        "registry_field": [{"id": "road_type", "group": "MANDATORY_START", "source_type": "UI", "value_type": "enum",
                            "unit": None, "enum_values": ["URBAN_LOW_SPEED"], "plan_ref": "4B"},
                           {"id": "posted_speed_mph", "group": "MANDATORY_START", "source_type": "UI", "value_type": "number",
                            "unit": "mph", "enum_values": None, "plan_ref": "4B"}],
        "table_def": [{"id": "T1", "table": "6B-1", "title": "spacing", "key_fields": {"road_type": None},
                       "value_fields": {"A": "ft", "B": "ft", "C": "ft"}, "source_ref_ids": ["SR-1"]}],
        "table_row": [{"id": "T1-R1", "table_def_id": "T1", "key": {"road_type": "URBAN_LOW_SPEED"},
                       "values": {"A": 100, "B": 100, "C": 100}, "status": "SOURCED", "sme_question": None,
                       "interpretation": None, "source_ref_ids": ["SR-1"]}],
        "rule": [{"id": "R-CUTOFF", "layer": "FEDERAL", "ta_id": "TA-1", "jurisdiction": None, "topic": "cutoff",
                  "strength": "GUIDANCE", "text": "low speed", "condition": None, "action": None, "value": None, "value_max": None,
                  "unit": "mph", "qualifier": None, "status": "SOURCE_REVIEW_REQUIRED", "sme_question": "What cutoff?",
                  "interpretation": None, "source_ref_ids": ["SR-1"]}],
    }}
    ta = {"schema_version": "1", "layer": "FEDERAL", "tables": {
        "ta": [{"id": "TA-1", "title": "Work Beyond the Shoulder", "figure": "6P-1", "source_ref_ids": ["SR-1"]}]}}
    return {"base/core.json": base, "ta/TA-1.json": ta}


def _write(root, parts, scope=("TA-1",)):
    for rel, doc in parts.items():
        p = os.path.join(root, *rel.split("/")); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: json.dump(doc, f, indent=1)
    m = {"schema_version": "1", "pack_id": "TEST_PACK", "version": "1.0.0", "status": "DRAFT", "source_edition_note": "test",
         "ta_scope": list(scope), "parts": [{"path": rel, "layer": doc["layer"], "sha256": SHA} for rel, doc in parts.items()],
         "content_sha256": SHA}
    with open(os.path.join(root, "pack.json"), "w", encoding="utf-8") as f: json.dump(m, f)
    return seal(str(root))


def _pack(tmp_path, parts=None, **kw):
    _write(tmp_path, parts or _parts(), **kw)
    return JsonRulePackStore(str(tmp_path)).load(validate_pack=False)


def _errors(tmp_path, parts, **kw):
    return validate(_pack(tmp_path, parts, **kw)).errors


# ---------- store and hash ----------
def test_load_list_versions_and_hash(tmp_path):
    h = _write(tmp_path, _parts())
    store = JsonRulePackStore(str(tmp_path))
    pack = store.load()
    assert store.list_versions() == ["1.0.0"] and store.content_hash() == h == pack.hash
    assert pack.ref == {"id": "TEST_PACK", "version": "1.0.0", "hash": h}
    assert JsonRulePackStore(str(tmp_path / "empty")).list_versions() == []


def test_hash_is_stable_across_loads_key_order_and_whitespace(tmp_path):
    h = _write(tmp_path, _parts())
    p = tmp_path / "base" / "core.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    p.write_text(json.dumps(doc, indent=4, sort_keys=True).replace("\n", "\r\n"), encoding="utf-8")
    store = JsonRulePackStore(str(tmp_path))
    assert store.content_hash() == h and store.load().hash == h and store.load().hash == h


@pytest.mark.parametrize("rel,table,field,value", [
    ("base/core.json", "table_row", "values", {"A": 100, "B": 100, "C": 101}),
    ("base/core.json", "source_ref", "section", "6B.07"),
    ("base/core.json", "registry_field", "plan_ref", "4C"),
    ("ta/TA-1.json", "ta", "title", "changed"),
])
def test_changing_any_record_breaks_the_hash_and_reseal_changes_it(tmp_path, rel, table, field, value):
    h = _write(tmp_path, _parts())
    p = tmp_path / rel; doc = json.loads(p.read_text(encoding="utf-8"))
    doc["tables"][table][0][field] = value
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RulePackError) as e: JsonRulePackStore(str(tmp_path)).load()
    assert e.value.code == "RULE_PACK_HASH_MISMATCH"
    assert seal(str(tmp_path)) != h


def test_manifest_change_changes_the_hash(tmp_path):
    h = _write(tmp_path, _parts())
    m = json.loads((tmp_path / "pack.json").read_text(encoding="utf-8")); m["version"] = "1.0.1"
    (tmp_path / "pack.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(RulePackError): JsonRulePackStore(str(tmp_path)).load()
    assert seal(str(tmp_path)) != h


def test_unknown_version_and_bad_part_path_fail(tmp_path):
    _write(tmp_path, _parts())
    with pytest.raises(RulePackError) as e: JsonRulePackStore(str(tmp_path)).load("9.9.9")
    assert e.value.code == "RULE_PACK_VERSION_MISSING"
    m = json.loads((tmp_path / "pack.json").read_text(encoding="utf-8")); m["parts"][0]["path"] = "../outside.json"
    (tmp_path / "pack.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(RulePackError) as e: JsonRulePackStore(str(tmp_path)).load()
    assert e.value.code == "RULE_PACK_PART_PATH_INVALID"


def test_valid_pack_loads_with_validation_and_reports_unsourced(tmp_path):
    _write(tmp_path, _parts())
    pack = JsonRulePackStore(str(tmp_path)).load()
    rep = validate(pack)
    assert rep.ok and rep.unsourced == [{"id": "R-CUTOFF", "table": "rule", "status": "SOURCE_REVIEW_REQUIRED",
                                         "question": "What cutoff?"}]


def test_only_scoped_tas_exist(tmp_path):
    pack = _pack(tmp_path)
    assert pack.ta("TA-1").figure == "6P-1" and pack.ta("TA-99") == NO_TA_MATCH
    parts = _parts(); parts["ta/TA-1.json"]["tables"]["ta"][0]["id"] = "TA-99"
    assert any("ta_scope" in e for e in _errors(tmp_path / "b", parts))


def test_trace_carries_rule_pack_and_source(tmp_path):
    pack = _pack(tmp_path)
    t = pack.trace("T1-R1")
    assert t["rule_id"] == "T1-R1" and t["pack_hash"] == pack.hash and t["pack_version"] == "1.0.0"
    assert t["source_refs"][0] == {"source_ref_id": "SR-1", "source_document_id": "SD-1", "section": "6B.06",
                                        "paragraph": None, "table": "6B-1", "figure": None, "note": None, "page": "773",
                                        "strength": "GUIDANCE", "evidence": "QUOTE"}


# ---------- validator ----------
def test_duplicate_ids_and_dangling_references(tmp_path):
    parts = _parts(); base = parts["base/core.json"]["tables"]
    base["table_row"].append(copy.deepcopy(base["table_row"][0]))
    base["rule"][0]["source_ref_ids"] = ["SR-NOPE"]
    errs = _errors(tmp_path, parts)
    assert any("duplicate id T1-R1" in e for e in errs) and any("SR-NOPE" in e for e in errs)


def test_number_not_in_its_quote_is_rejected(tmp_path):
    parts = _parts(); parts["base/core.json"]["tables"]["table_row"][0]["values"]["C"] = 150
    assert any("[150]" in e for e in _errors(tmp_path, parts))


def test_interpretation_allows_a_number_and_is_reported(tmp_path):
    parts = _parts(); row = parts["base/core.json"]["tables"]["table_row"][0]
    row["values"]["C"] = 150; row["interpretation"] = "owner-approved reading"
    rep = validate(_pack(tmp_path, parts))
    assert rep.ok and rep.interpretations == [{"id": "T1-R1", "table": "table_row", "status": "SOURCED",
                                               "interpretation": "owner-approved reading"}]


def test_interpretation_on_an_unsourced_record_exempts_nothing(tmp_path):
    parts = _parts(); r = parts["base/core.json"]["tables"]["rule"][0]
    r.update(interpretation="proposed reading", condition={"field": "posted_speed_mph", "op": "LE", "value": 30})
    rep = validate(_pack(tmp_path, parts))
    assert any("SOURCE_REVIEW_REQUIRED record holds numbers [30]" in e for e in rep.errors)
    assert rep.interpretations[0]["status"] == "SOURCE_REVIEW_REQUIRED"


def test_unsourced_record_cannot_hold_a_value(tmp_path):
    parts = _parts(); parts["base/core.json"]["tables"]["rule"][0]["value"] = 30
    with pytest.raises(RulePackError) as e: _pack(tmp_path, parts)
    assert e.value.code == "RULE_PACK_RECORD_INVALID"


def test_unsourced_record_needs_an_sme_question(tmp_path):
    parts = _parts(); parts["base/core.json"]["tables"]["rule"][0]["sme_question"] = None
    with pytest.raises(RulePackError): _pack(tmp_path, parts)


def test_condition_fields_must_be_registry_fields(tmp_path):
    parts = _parts(); r = parts["base/core.json"]["tables"]["rule"][0]
    r.update(status="SOURCED", sme_question=None, condition={"field": "nope", "op": "EQ", "value": True})
    assert any("'nope' is not a registry_field" in e for e in _errors(tmp_path, parts))


def test_part_layer_must_match_its_folder(tmp_path):
    parts = _parts(); parts["client/x.json"] = parts.pop("ta/TA-1.json")
    assert any("does not match folder client/" in e for e in _errors(tmp_path, parts))


def test_figure_transcription_needs_a_render(tmp_path):
    parts = _parts()
    parts["base/core.json"]["tables"]["source_ref"].append(_ref("SR-F", evidence="FIGURE_TRANSCRIPTION", quote=None,
                                                                 figure="6P-1", transcription="W20-1 at A"))
    with pytest.raises(RulePackError): _pack(tmp_path, parts)


def test_quotes_are_checked_against_the_page_snapshot(tmp_path):
    pack = _pack(tmp_path)
    page = {"printed_page": "773", "text": "Table 6B-1 Road Type " + QUOTE + " Urban (high speed)*"}
    assert validate(pack, page_texts={("SD-1", 9): page}).ok
    assert any("quote not found" in e for e in validate(pack, page_texts={("SD-1", 9): dict(page, text="other")}).errors)
    assert any("printed page" in e for e in validate(pack, page_texts={("SD-1", 9): dict(page, printed_page="774")}).errors)
    assert any("not in the snapshot" in e for e in validate(pack, page_texts={}).errors)


@pytest.mark.parametrize("n,text,hit", [(2640, "2,640 feet", True), (2640, "2640 feet", True), (0.33, "at least 0.33 L", True),
                                        (10, "100 feet", False), (1, "1,000 feet", False), (100.0, "100 feet", True),
                                        (0.5, "at least 0.5 L", True), (5, "0.5 L", False)])
def test_number_in_text(n, text, hit):
    assert number_in_text(n, text) is hit


def test_normalize_text_matches_the_snapshot_rule():
    assert normalize_text("Table 6B‑1.\n  Recommended  Advance") == "Table 6B-1. Recommended Advance"
