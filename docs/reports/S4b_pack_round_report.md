# S4b report: rule pack extension round (pack 1.1.0)

Branch `tcp-mvp/s04b-pack-round`, from `tcp-mvp/base` at `9649481`; `origin/tcp-mvp/base` (`a498adc`) merged in before the
full suite. Owner decisions D-90 (add-ons), D-91 (6N.11) and D-99 (S4b scope), plus the stage approvals recorded below.
The value-by-value review, including the generated **S4b changes** section, is in
[S4_rule_pack_review.md](S4_rule_pack_review.md).

Source: MUTCD Chapter 6, December 2023 revision only. Dev tools PyMuPDF 1.28.2 and pdfplumber, installed in the
worktree's `.venv`, never imported from `src/`. No live calls.

## Result

| Item | Value |
| --- | --- |
| Pack | `TCP_MUTCD_CH6_RULE_PACK` version **1.1.0**, status DRAFT (unchanged) |
| Pack hash | `80c25240ab584974f40f4f17205a8490127549837a30f7b69e9d11dd95a18b0a` |
| Previous | 1.0.0, hash `98c18fb207284ae884a28d20e2a5eba56facd74dfbc2aa7aa06797afe9e53d43` |
| Unsourced records | 19 (S4: 13) |
| Interpretations | 12, all SOURCED and owner-approved or owner-accepted (S4: 2, both PROPOSED) |
| Registry fields | 53 (S4: 52; + `addon_sidewalk_closed`) |
| Records | 169 source_ref, 102 rule, 39 table_row, 6 table_def, 19 eligibility_condition, 16 device, 18 ta_device_use, 9 formula |
| Cited-page snapshot | 30 pages (S4: 18): + printed 793, 796, 798, 803, 804, 805, 806, 807, 811, 812, 826, 845 |

## Stages and approvals

| Stage | Commit | What | Owner decision |
| --- | --- | --- | --- |
| 0 | `064a4aa` | `BASELINE_REF` = merge-base, `APPROVED` emptied | brief |
| A | `8c5091e`, `8e89700` | `base/sign_sizes.json`: 21 rows from Tables 6G-1, 6H-1, 6I-1; `sign_size()` lookup | Side-variant readings approved (W20-5R/L, W4-2R/L) with a W4-2 side question; R9-11a kept; M4-8a added (row exists); M4-8P, M4-8bP, M4-10 not added; client codes M4-9AL and R9-3BR get no size and a question; no arrow-board sizes |
| B | `ccef4f5` | Device rows W21-5, W3-4, W5-1, W20-5L, W4-2L | S5 plan Q4 option B: device rows only |
| C | `378daba` | Placement anchors; W slots per taper type | Approved; TA-1 and TA-6 opposite approach marked "SME confirmation pending"; TA-33 transcription corrected after the owner checked the 400 dpi crops |
| E | `90f2018` | 6N.11 split; TA-33 eligibility and tests | Approved (D-91) |
| D | `6712b3b` | `base/sidewalk_detour.json`: Sect. 6G.10 and 6I.02 as cited rules | 6G.10 only (6G.08 not loaded); M4-9 family and M4-8a |
| merge | `e5c7b10` | `origin/tcp-mvp/base` `a498adc` merged; `BASELINE_REF` = `a498adc81ff7e5a78f72db63f603ad269aaaabf0` | brief |
| F | `fb022db` | Version 1.1.0; `addon_sidewalk_closed` gate; pinned tests; review report | Option (a): one registry field, six 6G.10 rules gated |

## Changed test assertions (before and after)

Pinned assertions that S4b content broke, in `tests/unit/rules/test_rule_pack_v1.py`:

| # | Test | Before | After |
| --- | --- | --- | --- |
| 1 | `test_unsourced_items_are_exactly_the_known_list` | `EXPECTED_UNSOURCED`: 13 ids, including `R-6N11-TA33-UNDIVIDED-FOUR-LANE` and `E-TA33-FORM-UNDIVIDED-6N11` | 19 ids: those two replaced by `R-6N11-TA33-UNDIVIDED-OTHER` and `E-TA33-FORM-UNDIVIDED-OTHER`; added `R-6B4-W-MERGING`, `R-6B4-W-SHIFTING`, `R-6B4-W-SHOULDER`, `R-SIGN-NAMING-W4-2-SIDE`, `R-SIGN-SIZE-M4-9AL`, `R-SIGN-SIZE-R9-3BR` |
| 2 | `test_the_only_interpretations_are_the_proposed_6n11_reading_and_they_are_not_approved` | `got == {("R-6N11-TA33-UNDIVIDED-FOUR-LANE", "SOURCE_REVIEW_REQUIRED"), ("E-TA33-FORM-UNDIVIDED-6N11", "SOURCE_REVIEW_REQUIRED")}` | Renamed `test_interpretations_are_exactly_the_owner_approved_s4b_readings`: `got == {(rid, "SOURCED") for rid in EXPECTED_INTERPRETATIONS}` (12 ids), and every text starts with `INTERPRETATION` |
| 3 | `test_tables_hold_every_printed_row` | `all(r.status.value == "SOURCED" and None not in r.values.values() for r in rows)` over every table_row | The same check over Table 6B rows only (`table_def_id` starting `T-6B`); sign-size rows may print "—", covered by `test_sign_sizes.py` |
| 4 | `test_report_carries_the_required_sections` (`test_rule_pack_report.py`) | 7 required headings | Also requires `## S4b changes` and its five subsections |
| 5 | `test_committed_report_matches_the_pack`, `test_every_record_with_a_value_appears_in_the_report` | Report matched pack 1.0.0 | No code change; the report was regenerated |

Changed by the version bump (owner decision: 1.1.0):

| # | Test | Before | After |
| --- | --- | --- | --- |
| 6 | `test_stored_hash_is_the_recomputed_hash` | `list_versions() == ["1.0.0"]` | `list_versions() == ["1.1.0"]` |
| 7 | `test_trace_names_table_section_page_and_pack` | `t["pack_version"] == "1.0.0"` | `t["pack_version"] == "1.1.0"` |

Changed by stage E, in `tests/unit/rules/test_rule_pack_ta.py`:

| # | Test | Before | After |
| --- | --- | --- | --- |
| 8 | Granite undivided | `test_granite_undivided_facts_route_ta33_to_the_6n11_question`: TA-33 `UNDETERMINED`, questions `["E-TA33-FORM-UNDIVIDED-6N11"]` | `test_granite_undivided_facts_match_ta33_through_the_6n11_four_lane_reading`: TA-33 `ELIGIBLE`, no questions, the four-lane branch `True` |

## Tests added

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/rules/test_sign_sizes.py` | 9 | Every pack device's catalog id resolves to one size row or a stated reason; client codes have no size and a question; every value is the number in its quote; "—" is a gap with a question, never 0 or another column; trace; side-variant interpretations |
| `tests/unit/rules/test_rule_pack_addons.py` | 8 | Every add-on rule has a gate; toggle off or unset fires nothing (unset stays None); toggle on applies only the six sidewalk rules; detour rules only with their own fact; no add-on sign is a device or ta_device_use |
| `tests/unit/rules/test_rule_pack_ta.py` | 5 | Broader undivided cases (3 lanes, MEDIAN_SIDE, both) stay SOURCE_REVIEW_REQUIRED; missing `closed_lane_side` is UNDETERMINED; the 6N.11 split |

## Test results

- Full suite on `fb022db` (after the merge): **696 passed, 12 skipped** in 440 s. The skips are the 11 USGS-gated
  `test_diagnostics.py` tests (`TCP_RUN_USGS_TESTS=1`, as in S4) and `test_dxf_local_paths.py` (ODA File Converter not
  installed; CLAUDE.md). A second run with `-rs`, made only to list the skip reasons, gave the same result
  (695 passed, 12 skipped, 1 deselected).
- `tests/unit/rules/`: 113 passed (S4: 91).

- Guard and baseline tests after the merge (`test_guard_baseline_ref.py`, `test_global_identity.py`,
  `test_phase3_decisions.py`): 40 passed. The POC pack and `config/pipeline_config.json` are unchanged.
- `python spikes/rule_pack_extract/extract.py --check`: the snapshot and figure renders match the PDF.

## Files changed (against `a498adc`)

- New: `rule_pack/base/sign_sizes.json`, `rule_pack/base/sidewalk_detour.json`, `tests/unit/rules/test_sign_sizes.py`,
  `tests/unit/rules/test_rule_pack_addons.py`, this report.
- Changed: `rule_pack/pack.json`, `rule_pack/base/devices.json`, `registry.json`, `rules.json`, `rule_pack/ta/TA-1.json`,
  `TA-6.json`, `TA-10.json`, `TA-33.json`, `rule_pack/README.md`, `src/tcp_planner/rules/rule_pack_effective.py`
  (`sign_size()`), `src/tcp_planner/rules/rule_pack_models.py` (comment only), `scripts/rule_pack_report.py`,
  `docs/reports/S4_rule_pack_review.md` (regenerated), `spikes/rule_pack_extract/extract.py` (page list),
  `tests/fixtures/rule_pack_sources/cited_pages.json`, `tests/support/guard_baseline.py`,
  `tests/unit/rules/test_rule_pack_v1.py`, `test_rule_pack_ta.py`, `test_rule_pack_report.py`.
- No model, validator or evaluator change. Not touched: the POC pack, `config/pipeline_config.json`. Nothing deleted.

## Contradictions with the plan

| Item | Note |
| --- | --- |
| S4 transcription `SR-6P33-FIG-SIGNS` | Read A as ending at the upstream end of the shoulder taper; the render shows it ends at the start of the merging taper. Corrected; old wording in the review report |
| S8 plan (`docs/plans/S8_plan.md` lines 208, 219, 221) | Built on the old TA-33 reading; superseded (follow-up d) |
| S7 and S16 plans | Cite the removed 6N.11 ids (follow-up e) |
| Stage D brief | Named Sect. 6G.08 for sidewalk closed; 6G.08 is higher fines. Owner: 6G.10 only |
| Stage B brief vs S5 Q4 | Brief said device and ta_device_use rows; owner chose Q4 option B (device rows only) |
| Stage A message | Said all 20 rows match the catalog. Correct statement: the values match wherever a catalog entry exists; six rows have no entry with the same id (review report, "Size rows and the device catalog") |

## Follow-ups

a. Pack store keeps sealed versions side by side, before the first recording against pack v1. Today `load("1.0.0")`
   raises `RULE_PACK_VERSION_MISSING`; 1.0.0 is in git at `9649481`; no run is recorded against it.
b. Add-on signs need catalog entries, symbols and device rows before S8 places them.
c. S7: an unknown or unstated `closed_lane_side` never defaults to RIGHT.
d. S8 plan lines 208, 219, 221 (199, 210, 212 in the backup copy) are superseded by the corrected TA-33 reading.
e. S7 plan lines 43, 201, 383 and S16 plan line 234 cite the removed 6N.11 ids.
f. S11: the add-on toggle `ADDON:sidewalk_closed` maps onto the registry fact `addon_sidewalk_closed`; no second name.

## Open questions

1. The 19 SME questions listed in the review report, of which 6 are new in S4b (W per taper type x3, W4-2 side naming,
   the two client codes) and 1 replaces an S4 question (6N.11 broader cases).
2. The device-name flags (DV-W20-5L, DV-W4-2L, DV-W5-1) live in free text because `Device` has no note field; a later
   model change could move them.
