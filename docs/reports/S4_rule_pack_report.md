# S4 report: rule pack v1

Branch `tcp-mvp/s04-rule-pack`, from `tcp-mvp/s00-setup` at `13757f2` (a parallel worktree; not from S1 or S2).
The value-by-value review for SME sign-off is in [S4_rule_pack_review.md](S4_rule_pack_review.md).

Source edition: MUTCD Chapter 6, December 2023 revision (file sha256 recorded). The edition the client applies is not
yet confirmed.

## What was built

Rule pack v1 is a composed, table-shaped pack (D-30, ADR-027) for TA-1, TA-6, TA-10 and TA-33, built from the MUTCD
Chapter 6 PDF in `docs/sources/` and read only through a `RulePackStore`. It sits alongside the POC pack; the pipeline
still reads the POC pack, and switching it over is a separate step that needs the owner's approval.

| Part | Content |
| --- | --- |
| `rule_pack/pack.json` | Manifest: `TCP_MUTCD_CH6_RULE_PACK` 1.0.0, status DRAFT, `ta_scope` of four TAs, part hashes, pack hash `98c18fb2...` |
| `rule_pack/base/` | 53 source_refs, 52 registry fields, Tables 6B-1, 6B-2 and the fixed rows of 6B-3, 9 formulas (6B-4, 6B-3, 6B.08 cited only, 6K.01), shared rules (6B.04, 6B.06, 6B.08, 6N.07, 6N.08, 6N.11, 6P.01), 11 devices |
| `rule_pack/ta/` | One file per TA: every figure note as a quoted rule (6 + 14 + 13 + 7), eligibility conditions, device sequences from figure transcriptions |
| `src/tcp_planner/rules/` | `rule_pack_models.py` (Pydantic records), `rule_pack_validator.py`, `rule_pack_store.py` (`JsonRulePackStore`: `list_versions`, `load`, `content_hash`; `trace`; NO_TA_MATCH), `rule_pack_eval.py` (conditions, formulas, eligibility), `rule_pack_effective.py` (precedence view, buffer and spacing lookups) |
| `scripts/` | `seal_rule_pack.py` (writes hashes, validates), `rule_pack_report.py` (writes the review report) |
| `spikes/rule_pack_extract/` | PDF survey and the cited-page snapshot generator (PyMuPDF, dev-time only) |
| `tests/fixtures/rule_pack_sources/` | Normalised text of the 18 cited MUTCD pages and the four rendered figure pages, pinned by sha256 |

Totals: 112 source_refs (48 after commit 3, 112 after commit 4; commit 3's message said 57 in error), 18 table rows,
9 formulas, 73 rules, 18 eligibility conditions, 11 devices, 18 device uses, 0 deviations. 13 records are unsourced,
each with an SME question.

## Acceptance criteria

| Criterion | Result |
| --- | --- |
| Every value has a `source_ref`; a value with none is SOURCE_REVIEW_REQUIRED and reported | Met. The validator rejects any number that is not in its record's quote or figure transcription; unsourced records carry no value. 13 unsourced records are listed with their SME questions |
| Pack hash is stable, and changing any record changes it | Met. Canonical-JSON hash per part plus a pack hash over the manifest and part hashes; tested for key order, line endings and a change in every part |
| Table 6B-4: W = 11 ft, S = 25 mph gives L ≈ 114.6 ft; W = 12 ft, S = 45 mph gives L = 540 ft | Met. 114.583... ft (unrounded) and 540 ft. 41 to 44 mph gives SOURCE_REVIEW_REQUIRED (owner decision Q5) |
| Precedence: the client 100 ft buffer overrides Table 6B-2 only where the client layer applies | Changed by the owner (scope change): no client layer. The precedence test covers the federal layer; at 25 mph urban the buffer is 155 ft from Table 6B-2 (Option) |
| Tests: loader and validator, formulas, precedence, the engine reads no rule file directly | Met (see Tests added) |

## Commits

| Commit | What |
| --- | --- |
| `1ff69a0` | Cherry-pick of S1 `71eb43d`: protected-file guards compare with `BASELINE_REF` |
| `a0ffc89` | `APPROVED` emptied; `BASELINE_REF` stays `13757f2` |
| `a1162b0` | Commit 1: extraction spike and cited-page snapshot |
| `2817bf6` | Snapshot holds MUTCD pages only (TMP text and CAD path removed; scope change) |
| `29e4c58` | Rendered figure pages committed as FIGURE_TRANSCRIPTION evidence |
| `89dce88` | Commit 2: models, validator, store |
| `e6ad7d5` | Commit 3: base tables |
| `e36225b` | Commit 4: TA files and eligibility |
| `3e8b21f` | Commit 5: empty jurisdiction, client and deviation layers; `rule_pack/README.md` |
| `9137880` | Commit 6: effective-rules view |
| `43f5f46` | Commit 7: review report |
| this commit | Commit 8: this report |

## Files changed (against `13757f2`)

- New: everything under `rule_pack/` except the POC pack, the five `src/tcp_planner/rules/rule_pack_*.py` modules,
  `scripts/seal_rule_pack.py`, `scripts/rule_pack_report.py`, `spikes/rule_pack_extract/`,
  `tests/fixtures/rule_pack_sources/`, `tests/unit/rules/`, `tests/support/guard_baseline.py` (from S1),
  `docs/reports/S4_rule_pack_review.md`, this report.
- Changed: `pyproject.toml` (`pydantic>=2` added to dependencies, owner decision Q4; PyMuPDF and pdfplumber are not
  added), `CLAUDE.md` (rule-pack `schema_version` sits on the manifest and every part file; rows inherit it),
  `tests/integration/review_assistant/test_global_identity.py` and `test_phase3_decisions.py` (S1 cherry-pick).
- Unchanged and protected: `rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json`, `config/pipeline_config.json`.
- Nothing was deleted.

## Tests added (91, all in `tests/unit/rules/`)

| File | Covers |
| --- | --- |
| `test_rule_pack_store.py` | Store and hash on a synthetic pack; duplicate ids, dangling references, layer and folder, numbers not in their quote, unsourced records holding values, interpretations, quote and page checks, number matching |
| `test_rule_pack_isolation.py` | No `src/` module reads rule-pack files except the store (and the legacy POC loader, until the switch); `src/` never imports PDF tools |
| `test_rule_pack_v1.py` | The committed pack: every quote on its cited page, every figure render and the PDF sha256, every part listed, the exact unsourced list, Table 6B-4 values, 6B-3 tapers, 6K.01 spacing, traces, only the federal layer populated |
| `test_rule_pack_ta.py` | All figure notes loaded, figure-only values never applied, sign sequences, eligibility on synthetic fact sets (Colorado, E Second St, Granite undivided and divided, beyond shoulder, one-way NO_TA_MATCH, missing facts) |
| `test_rule_pack_effective.py` | Layer order, 25 mph buffer = 155 ft, no interpolation, Table 6B-1 spacing, cited-only never applied, TA notes superseding the shared section they restate |
| `test_rule_pack_report.py` | The committed review report matches the pack and carries the required sections |

## Test results

- Full suite on the commit 7 tree (commit 8 adds only this report): **363 passed, 11 skipped** in 617 s. The 11 skips
  are the existing USGS-gated `test_diagnostics.py` (`TCP_RUN_USGS_TESTS=1`), unchanged since S0.
- Protected-file guards: the 26 tests in `test_global_identity.py` and `test_phase3_decisions.py` pass. The POC pack
  and `config/pipeline_config.json` show no diff against `13757f2`.
- `tests/unit/rules/`: 91 passed.
- No live calls: the root `conftest.py` blocks the network unless `TCP_LIVE=1`, which was not set.
- `python spikes/rule_pack_extract/extract.py --check`: the snapshot and figure renders match the PDF.
- Suite growth across S4: 303 (after commit 2), 327 (commit 3), 342 (commit 4), 363 (commit 7).

## Contradictions with the plan

| Item | Note |
| --- | --- |
| D-81 and the S4 spec: v1 "replaces" the POC pack | Added alongside, per the owner; the switch-over is a separate approved step |
| POC pack edition | Its header cites "MUTCD 11th Edition with Revision 1", December 2025; v1 cites the December 2023 file. The POC header is unchanged |
| D-60, TA-33 on undivided roads | D-60 says "undivided, 2+ lanes each way"; Sect. 6N.11 para 06 says right-hand lane closed on four-lane roads. Amendment proposed in the review report |
| S4 spec: client layer, RI and MA jurisdiction files, 6G.08 and 6G.10 | Not built: owner scope change (MUTCD only). The layers stay in the schema, empty. 6G.08 and 6G.10 text is in the snapshot but no records were made, since their modules were removed |
| Plan section 4B field names | Four new registry fields and the duration split; listed as proposals in the review report |
| `schema_version` on every persisted record (CLAUDE.md) | Rule pack: on the manifest and every part file, rows inherit it (owner decision; CLAUDE.md updated) |

## Merge notes

- `RulePackStore`: S2 defines the interface. `rules/rule_pack_store.py` uses the same method names and must be
  reconciled with S2's interface at merge.
- `tests/support/guard_baseline.py` comes from S1's commit; at merge with S1 only the `APPROVED` dict differs.
- At the next slice start, move `BASELINE_REF` to the last commit of the slice it starts from and empty `APPROVED`.

## Open questions

1. External inputs (each is an SME question in the pack): the low-speed cutoff, "minor road", the "short TTC zone"
   length, the 6N.11 undivided reading, the two figure-only TA-33 values, the TMA threshold, the default work-vehicle
   width, default work lengths, and the edition the client applies.
2. The D-60 amendment and the proposals for D-51, D-68, open questions 15, 17 and 18 and the S8 client modules (review
   report).
3. When to switch the pipeline from the POC pack to v1 (needs the owner's approval; the engine reads the POC section
   layout, so the switch is a code change in S7/S8, not a file swap).
4. Sect. 6G.10 (sidewalk closure) would have to be loaded if a pedestrian module comes back.
