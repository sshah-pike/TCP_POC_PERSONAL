# S5 report: device catalog and symbol library

Branch `tcp-mvp/s05-device-catalog`, from `tcp-mvp/base`; `origin/tcp-mvp/base` (`c2c0250`) merged in before commits 4 to 7.
Rule pack `TCP_MUTCD_CH6_RULE_PACK` 1.1.0, hash `80c25240ab584974f40f4f17205a8490127549837a30f7b69e9d11dd95a18b0a`,
status DRAFT, unchanged by S5. Source edition: MUTCD Chapter 6, December 2023 only. No live calls. No dependency added
(`pyproject.toml` unchanged). The value-by-value review is in [S5_device_catalog_review.md](S5_device_catalog_review.md)
(generated; a test fails when it is out of date).

## Result

| Item | Value |
| --- | --- |
| Catalog | `assets/symbols/device_catalog.json` v0.2, `schema_version` "1", 56 entries (51 + M4-9a-L, M4-9a-R, M4-9b, M4-9c-L, M4-9c-R) |
| Symbols | 56 placeholder SVGs and 56 pre-rendered PNGs (2x), each with sha256 and size in the catalog |
| Sizes | none in the catalog. `size_for()` wraps `sign_size()` (S4b rows); 20 catalog signs have a row (`size_source` PACK) |
| Column mapping (Q3 A) | URBAN_LOW_SPEED, URBAN_HIGH_SPEED, RURAL: Conventional; EXPRESSWAY_FREEWAY: Freeway; Minimum never automatic. **PROPOSED**, SME question 38 |
| Placeholder (A5, Q8 B) | `DeviceCatalog.placeholder_status()` gives flag, device list, reason `PLACEHOLDER_ASSET` and the label text; S12 draws the label |

## Commits

| # | Commit | What |
| --- | --- | --- |
| 0 | `2df1a1f` | `BASELINE_REF` = merge-base, `APPROVED` emptied |
| 1 | `cff81f7` | Catalog model, loader, hash, v0.1 to v0.2 migration, seal script |
| 2 | `6b7ee5b` | Review report and generator |
| merge | base `c2c0250` merged; `BASELINE_REF` = `c2c0250575b6bf72b516306f20535d3369267356` | |
| 4 | `eb0bc09` | `size_source` PACK for 20 signs; `sign_size_map.py`; five M4-9a/b/c entries; reports regenerated |
| 5 | `fa7f49b` | `size_for`, device validators, placeholder status and label |
| 6 | `14748f1` | Symbol library, PNG raster per entry, `render_symbols.py`, swap tests |
| 7 | this commit | Review report regenerated, this report |

(Plan commits 3 and 4 were done by S4b; the commit titled "S5 4" here is the mapping and gap-closing step.)

## Acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| A1 | Every figure and draft sign resolves | All 16 pack devices and 18 `ta_device_use` rows resolve. Every golden code resolves except W20-8 (police, out of scope, no alias); M4-A8 through the PROPOSED alias. `test_device_catalog.py` |
| A2 | CLIENT_CODE and STATE_CODE entries listed | Review report (4 entries) |
| A3 | Swapping one asset changes only that symbol and the catalog hash | SVG swap and client PNG swap tests |
| A4 | Placed device exists; size from the catalog for the road type | `validate_devices`: DEVICE_EXISTS, DEVICE_SIZE_FROM_PACK. Sizes come from the pack, not the catalog (Q1 C) |
| A5 | PLACEHOLDER_ASSET gives REVIEW_REQUIRED and a label | Function level (flag, reason, label text). Drawing is S12 |
| A6 | Sizes not altered from their tables | No size is stored in S5. Every size `size_for` can return is checked against the number in its quote (all 20 signs x 4 road types) |

## Tests

New in `tests/unit/devices/`: 44 tests (143 with parametrization, all in that folder):
`test_device_catalog.py` 15 (integrity, hash, resolution, swap, refusal, isolation, case-insensitive uniqueness),
`test_device_catalog_report.py` 2, `test_sign_size_map.py` 7 (every id resolves to one row or a stated reason; the gap
list is empty), `test_device_sizes.py` 14 (per road type, quote check, dash column, UNKNOWN, validators, placeholder),
`test_symbol_library.py` 6 (PNG hashes, pixel size, client PNG swap, no renderer imported from `src/`).

Results:
- Full suite on `HEAD` before the report commit: **839 passed, 12 skipped** in 411 s. The 12 skips are the 11 USGS-gated
  `test_diagnostics.py` tests and `test_dxf_local_paths.py` (no ODA converter), as before. S4b's full run was 696 passed.
- Guard and baseline tests after the merge: 40 passed. The POC pack and `config/pipeline_config.json` are unchanged.
- Isolation tests green: `src/` imports no PDF or SVG tool; only `rules/device_catalog.py` reads the catalog.

## Files changed (against `c2c0250`)

- New: `src/tcp_planner/rules/{device_catalog,sign_size_map,device_sizes,symbol_library}.py`,
  `src/tcp_planner/validation/device_checks.py`, `scripts/{seal_device_catalog,migrate_device_catalog_v02,device_catalog_report,render_symbols}.py`,
  `tests/unit/devices/`, `assets/symbols/png/` (56 files), 5 SVGs, `docs/reports/S5_device_catalog_{review,report}.md`.
- Changed: `assets/symbols/device_catalog.json`, `src/tcp_planner/config/settings.py` (two path constants),
  `tests/support/guard_baseline.py`.
- Changed in S4b files (catalog v0.2 renamed `id` to `device_id`): `tests/unit/rules/test_sign_sizes.py` (one line),
  `scripts/rule_pack_report.py` (line 260: key; line 285: also accepts "-L" and "-R"); `docs/reports/S4_rule_pack_review.md`
  regenerated (M4-9a, M4-9b, M4-9c no longer "no entry"). Nothing deleted; `gen.py` kept, never re-run.

## Contradictions with the plan and slice spec

| Item | Note |
| --- | --- |
| Slice spec: import the catalog into the pack `device` table | Not done. Owner decision Q1 C: sizes are pack rows, assets and names stay in the catalog with their own hash |
| v0.1 `size_in` | Removed from the catalog. The v0.1 numbers are in git only; the pack rows (S4b, quoted) replace them. Signs with no row (7) now have no size, where v0.1 had an unquoted one |
| Ids M4-9a-L, M4-9a-R, M4-9c-L, M4-9c-R | Hyphen before L and R, unlike M4-9L: `M4-9aL` and the client code `M4-9AL` are one file name on Windows and OneDrive (it overwrote the client placeholder once during this work; restored from git). A test now rejects ids and URIs that differ only by case |
| M4-9a arrow | Sect. 6I.02 para 11 requires an arrow; para 12 allows it on a supplemental plaque. Modelled as L and R entries by the catalog convention. The new symbols show the legend only, no arrow |
| Placeholder label | Stored in the catalog (`placeholder_label`, covered by the catalog hash), not in `pipeline_config.json`, which is guarded |
| `pack_device_id`, `used_by_tas` | Not stored; derived from the pack |

## Open questions

1. **SME question 38**: confirm the road-type to column mapping (PROPOSED).
2. Seven MUTCD signs have no size row: W21-5a, W9-2L, R8-3, R2-10, R2-11, R3-7R, R1-1-PADDLE. R8-3 (Colorado, E Second), R2-11 (Granite, all six sheets) and R3-7R and W9-2L (Granite sheet 2) appear in the golden drafts; none is in any TA. They need rows before S8 places them.
3. Q13 (printed codes, M4-A8 alias PROPOSED), Q14 (sizes for the four client and state codes), Q16 (client CAD blocks: convert to SVG or PNG first).
4. S4b follow-up b: add-on signs (R9-9 to R9-11a, M4-8a, M4-9 family) have a catalog entry, symbol and size now, but still no device rows.
5. S8 must add the catalog hash next to the pack hash in every trace (CLAUDE.md rule 9 names only the pack).

## Proposed CLAUDE.md note (not written; for the owner to approve)

Under "Storage", after the rule pack exception:

> - **Device catalog exception (S5):** `assets/symbols/device_catalog.json` carries `schema_version` once; each entry's
>   `asset` and `raster` are `{uri, sha256, size, media_type, status}` with a `uri` relative to `assets/`. The catalog
>   holds no regulatory number: sizes come from the pack through `size_for()`. Only `rules/device_catalog.py` reads the
>   file. After any change run `scripts/seal_device_catalog.py` (and `scripts/render_symbols.py` after an SVG change).

Under "Known limits" (new "S5" heading):

> - The road-type to size-column mapping is PROPOSED until the SME answers question 38.
> - Device ids and symbol file names must not differ only by case (Windows, OneDrive).
> - PNG bytes can differ between PyMuPDF versions: the committed PNGs and their recorded hashes are authoritative.
> - Every symbol is a placeholder; a plan that uses one is REVIEW_REQUIRED and carries the label text. S12 draws it.
