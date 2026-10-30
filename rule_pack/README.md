# rule_pack/

| Path | What it is |
| --- | --- |
| `APPROVED_TWO_LANE_POC_RULE_PACK.json` | The POC pack. Still used by the pipeline through `rules/rule_pack_loader.py`. Protected: never edited. Switching the pipeline to pack v1 is a separate step that needs the owner's approval |
| `pack.json` | Rule pack v1 manifest: id, version, status `DRAFT`, `ta_scope`, the parts with their sha256, and the pack hash |
| `base/*.json` | Federal layer, shared by every TA: sources, registry fields, Tables 6B-1 to 6B-3, formulas (6B-4, 6B-3, 6K.01), shared rules, devices; sign sizes from Tables 6G-1, 6H-1 and 6I-1 (`sign_sizes.json`, S4b); the optional sidewalk-closed and detour add-ons, Sect. 6G.10 and 6I.02 (`sidewalk_detour.json`, S4b) |
| `ta/TA-1.json`, `TA-6`, `TA-10`, `TA-33` | Federal layer, one file per TA: figure notes, eligibility conditions, device sequences |
| `jurisdiction/`, `client/` | Not created. Layers stay in the schema but are empty in v1 (S4 scope change: rules come from the MUTCD only) |

Rule pack v1 is read only through `src/tcp_planner/rules/rule_pack_store.py` (`JsonRulePackStore`). No other module
opens these files; `tests/unit/rules/test_rule_pack_isolation.py` enforces it.

## Records

Each part is `{"schema_version", "layer", "tables": {table: [records]}}`. Tables are flat arrays, one per future database
table, and records refer to each other by id. Rows inherit the part's `schema_version`. Every value has a `source_ref`
(table, section, paragraph, figure, note, printed and PDF page, strength, and a verbatim quote or a figure
transcription). A value with no source has no value: status `SOURCE_REVIEW_REQUIRED` or `UNKNOWN` plus an SME question.

## Layers and precedence

Effective rules are resolved in this order, later layers overriding earlier ones only where they apply: federal,
jurisdiction, client, deviation (`rules/rule_pack_effective.py`). In v1 only the federal layer has records. Records
with `role: CITED_ONLY` are kept for the record and never applied; `overlaps` names the record that applies instead.

## Editing

1. Edit or add a part file. A new part must also be listed in `pack.json`.
2. Run `python scripts/seal_rule_pack.py`: it writes every part hash and the pack hash, then validates the pack.
3. Run `pytest tests/unit/rules`. It checks every quote against the cited-page snapshot in
   `tests/fixtures/rule_pack_sources/` and every number against its quote.
