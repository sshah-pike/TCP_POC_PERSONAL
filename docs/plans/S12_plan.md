Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md; where they differ from this plan, the register wins.

# S12 plan: sheets and PDF

Planning only. Branch when built: `tcp-mvp/s12-sheets`, off the last merged slice of S8 to S11 (the slices doc runs S12 beside S10 and before S11; see question B-16). Written on `tmp/plan-base4` (S1 to S4 merged). Nothing here is approved until the owner says so (CLAUDE.md, "How to work", rule 2).

Read for this plan: CLAUDE.md; slice specs S8, S9, S11, S12, S13; plan sections 3, 4A, 8, 9, 10, 10A, 12, 14, 15 (D-26, D-27, D-45, D-65, D-71, D-72, open question 3) and ADR-035, ADR-046; `S0_repo_report.md` items 6, 22, 30; `S2_storage_report.md`; `S3_orchestrator_report.md`; `S4_rule_pack_review.md`; the plan copies `docs/plans/S5_plan.md` to `S8_plan.md` (not final); `tests/golden/*`; the three reference TMP PDFs (text layer, title block, notes); `src/tcp_planner/sheets/sheet_renderer.py`, `dwt_renderer.py`; `assets/sheet/sheet_layout.json`; `scripts/build_sheet_frame.py`.

Owner constraints applied: rules come from the MUTCD Chapter 6, December 2023, only; the drafts are comparison material and a style reference, never a rule source. A phase is a drawn sheet (D-45). Title block: street, city, state and ZIP; the street number only if it is in the input. Every plan waits for an SME click (D-65).

Legend: **[B]** can be batched with the next commit. **[STOP]** stop for owner review. **A-n** is an assumption about a shape from S5 to S11 that I could not verify; each is repeated in section 9.

---

## 1. What is there today (verified by reading; nothing was run except read-only text extraction from the PDFs)

| Item | Finding |
| --- | --- |
| Renderer | `sheets/sheet_renderer.py` composes one sheet per run with matplotlib on a raster frame (`assets/sheet/sheet_frame.png`), 2448 x 1584 pt (34 x 22 in), regions in `sheet_layout.json`. It picks the **smallest** scale from 20, 30, 40, 50, 60, 80, 100, 200 ft/in where objects and callouts fit (`SCALES_FT_PER_IN`, line 11), so 40 then 50 cannot be forced today. Phase label is the literal "TA-1 DRAFT"; print number is the literal "1 OF 1"; five hard-coded project notes; a draft watermark; a plan-hash strip. North-up only |
| Frame source | The frame was cut from a **fourth** drawing, `3) CADD FINAL - 1A7DS9M WPI 3160485.pdf` (sha256 recorded in `sheet_layout.json`), which is not in `docs/references/`. `build_sheet_frame.py` says the frame keeps the notes box, legend, details, Dig Safe box, utility note, **north arrow**, logos and the empty title grid. Whether its notes box holds the same 12 notes as the three references is unverified (S0 item 22) |
| References (text layer) | All three PDFs: 34 x 22 in; the same legend, the same 12 general notes, a drum and cone detail, a Type III barricade detail, a free-standing sign detail captioned "PER SEC. 6F.03 MUTCD 11th EDITION PAGE 792 DECEMBER 2023", Dig Safe box, revisions box, "PREPARED BY" Pike Telecom block, title "TRAFFIC MANAGEMENT PLAN - PHASE n", fields SURVEYED BY (PIKE TELECOM), DRAWN BY (initials), DATE, SCALE, PRINT NO (n of N), EWO (for example "1A8J1KB WPI 3171586"). Location lines: "130 COLORADO ST / MATTAPAN, MA 02126", "E SECOND ST / BOSTON, MA 02127", "GRANITE ST (US-1) / WESTERLY, RI 02891" |
| The 12 notes | Note 1 "latest edition of the MUTCD"; note 9 "distances are a guide and may be adjusted in the field by the engineer"; note 10 "maximum spacing of devices in a taper equals the speed limit in mph" (same as Sect. 6K.01 para 04, `F-6K01-TAPER-SPACING`); **note 11 "minimum lane width is to be 11 feet"**, which differs from the pack (`R-6N07-REMAINING-WIDTH`, `R-TA6-N1`: 10 ft) |
| Golden sheets | Colorado: 1 sheet, PHASE I, 1" = 40', [P.13]. E Second St: 2 sheets, PHASE I [MH 223] and PHASE II [MH FA], both 1" = 40'. Granite (drawing WPI 3178233): 6 sheets; Phase I [P.32] at 40; II [P.33, P.34, P.36] at 40; III [P.37, P.38, P.38-50] at 50; IV [P.39] at 40; V [P.40, P.41, P.42] at 50; VI [P.42-2] at 40. **This differs from plan section 4A**, which lists the phases as "P.32 / P.34, P.33, ..."; the golden is the accepted reading |
| Imagery | Each zone run fetches a 2560 px sheet aerial mosaic about the work reference (S0 item 6). It is per run, north-up |
| DWT | `dwt_renderer.py` exists; `config/dwt_config.json` has every `block_map` entry null; no ODA converter on the dev machine (S3) |
| Output index | Since S3 every output file's sha256 and size are in the run's `result.output_index` |
| Storage | `ArtifactStore` (`put`, `get`, `stat`, write-once), `StateStore` (`put_new`, `compare_and_set`, events). No sheet or sheet-set record exists; S3 report "Contradictions" item 3: the plan's `Sheet` entity and `ProjectPlan` index are not built |
| Test tiers | `pyproject.toml` declares no pytest markers. The owner's gate ("fast tier per commit plus impacted suites") assumes a tier marker; S3 proposed a `slow` marker and did not add it (B-18) |

## 2. Scope and acceptance criteria

### In scope

1. **Sheet packing** per plan section 4A: order the zones, fit at 1" = 40', then 1" = 50', then a new sheet. No overlap on one sheet. Two TAs share a sheet only if both fit, and such a sheet is REVIEW_REQUIRED.
2. **Titles** "PHASE I", "PHASE II" and so on; "n OF N"; no cover page.
3. **The common template**: legend, the 12 general notes, Type III barricade detail, drum and cone detail, free-standing sign detail, title block, revisions box, Dig Safe box, job notes, scale bar, north arrow.
4. **Title-block data**: street, city, state, ZIP; street number only if it is in the input (owner); point labels from placemark names (D-72); no address typed by the SME (D-71, see B-4).
5. **Azure Maps imagery** as the base, **dimension labels** on the drawing, the **placeholder-symbols label** (S5 Q8 option B: S5 gives the flag, S12 draws it), draft and approval markings (D-65).
6. **One multi-page PDF per project sheet set**, 34 x 22 in, plus one PNG preview per sheet, all through `ArtifactStore` with artifact refs, and a versioned `SheetSet` record through `StateStore`.
7. The hooks S11 needs to reorder, merge and split sheets (a new sheet-set version per change). The S11 actions themselves are S11.

### Out of scope

Grouping (S9), placement (S8), the conflict ladder (S10), the SME form and review actions (S11), the comparator scores (S13), polygon and line footprints (S14; S12 takes the work space as an extent so S14 can draw a footprint later), DWT and DXF output unless B-15 says otherwise, the police variant (future scope).

### Acceptance criteria

The slice spec's three, then what they mean with the owner's constraints:

| # | Criterion | Reading |
| --- | --- | --- |
| 1 | For each golden job the sheet count, phase labels, work points per sheet and scale equal the golden | **Colorado**: 1 sheet, PHASE I, [P13] (label normalised to P.13 for comparison only), 40. **E Second St**: 2 sheets, PHASE I [MH 223], PHASE II [MH FA], 40 and 40. **Granite**: compared at P32, Phase I only (owner): the sheet that holds P32 is PHASE I at 40. Work points per sheet cannot match for Granite unless P32 is its own zone (S9 groups P32 with P31; B-17). Tested on S8 layouts built from recorded or synthetic facts; the real-KML end-to-end check is S13 |
| 2 | Template elements are present on every sheet | Checked on the sheet model (every element placed in its region) and, for text elements, on the PDF text layer (B-1 decides how much is text) |
| 3 | The PDF is 34 x 22 in | Every page's media box is 2448 x 1584 pt |

Two criteria the constraints add:

| # | Criterion | Reading |
| --- | --- | --- |
| 4 | Nothing on a sheet is a value the pipeline did not produce or a source did not give | Every dimension label comes from an object trace; every title-block part carries its source; an unknown part prints as blank or "VERIFY", never a guess (B-3, B-12) |
| 5 | Same inputs give the same bytes | PDF and PNG are byte-identical on the same OS for the same sheet-set inputs (metadata dates removed, fixed fonts) |

## 3. Modules touched

New (under `src/tcp_planner/`; names are proposals):

| Module | Purpose |
| --- | --- |
| `sheets/models.py` | Pydantic models: `SheetSet`, `Sheet`, `TitleBlock`, `TitlePart`, `Dimension`, `PackingTrace`, `SheetBanner` |
| `sheets/paper.py` | Paper geometry: viewport and keep-out regions (notes box, legend) from the template layout; inches to feet at a scale; rotation; bounding boxes of drawn items (symbols, callouts, dimension strings) |
| `sheets/fit.py` | `fits(zone_layouts, scale, rotation) -> FitResult` from the S8 envelope plus drawn-item margins (B-6) |
| `sheets/packing.py` | Zone order (B-8), the 40 then 50 then new sheet loop, the overlap test, two-TA flag, the single-zone-too-big policy (B-5) |
| `sheets/title_block.py` | Title-block parts with sources (street, number, city, state, ZIP, EWO, drawn by, date, print no) |
| `sheets/dimensions.py` | Which dimensions to print and their display text from traces (B-11, B-12) |
| `sheets/template.py` | Template description (regions, notes text, detail artwork refs, version, hash) loaded through `settings.py` |
| `sheets/sheet_set_renderer.py` | Multi-zone, multi-page renderer. Reuses the drawing code of `sheet_renderer.py` for imagery, signs and callouts |
| `orchestration/sheet_stage.py` | Project-level stage: runs after the zone runs settle, writes the sheet set, events |
| `web_api/project_routes.py` (extend) | `GET /api/projects/<id>/sheets`, `GET .../sheets/<version>/pdf`, PNG per sheet |
| `apps/web/src/components/SheetSetView.tsx` | Sheet list, PDF link, banners, packing reasons |

Changed:

| File | Change |
| --- | --- |
| `sheets/sheet_renderer.py` | Kept for single-run output until B-16 says the per-run sheet goes; its drawing helpers move into shared functions. Never deleted; unused code waits for S15 |
| `assets/sheet/` | New template version per B-1 (a new frame and layout file beside the current ones, never overwritten) |
| `config/pipeline_config.json` | New `sheets` section (section 4.4). Guarded file; guard updated as in S3 `f1528c5` |
| `config/settings.py` | Template paths |
| `tests/fixtures/expected/` | Only if the per-run sheet output changes (B-16), with owner review (D-83) |

## 4. Data shapes

### 4.1 Inputs (what S12 consumes)

```
ZoneLayoutInput {                                  # ASSUMPTION A-1: S8 LayoutResult and its artifact ref
  zone_id, zone_version, ta_id|null, status, layout_ref {uri, sha256, size, media_type},
  objects [PlanObject] (station_ft, offset_ft, side, latlon, device_id, extent, trace),
  gaps [LayoutGap], failures [PlacementFailure], optional_not_placed [], requirements [],
  envelope Envelope {upstream_ft, downstream_ft, lateral_ft, station_range_m, kind},
  review_reasons [], centerline [latlon], work_space {upstream_end_station_m, downstream_end_station_m, points[]} }
ZoneContext {                                      # ASSUMPTION A-2: S3 project record plus S9 zones
  zone_id, location_ids [], display_labels [], road {name, source, evidence_ref}, decision, approval_state }
PlaceholderStatus {uses_placeholder, device_ids[], reason_code, label}   # S5 (A-3)
SymbolAsset {device_id, media_type, asset_ref, status}                    # S5 (A-3)
SheetImagery {zone_id, artifact_ref, center, ground_extent_m, mpp, rotation_deg: 0}   # the zone run's recorded sheet aerial
```

### 4.2 Sheet set (persisted; `schema_version` "1")

```
SheetSet {
  schema_version, sheet_set_id, project_id, version, parent_version|null, created_by "ENGINE:sheets@<v>"|"SME:<role>",
  inputs { zones [ {zone_id, zone_version, layout_ref} ], template {id, version, hash}, catalog_hash, pack_ref {id, version, hash},
           settings_hash },
  order { method "ALONG_ROAD"|"SME", zone_ids [] },
  sheets [Sheet],
  pdf_ref ArtifactRef, png_refs [ArtifactRef],
  status "DRAFT_AWAITING_SME"|"REVIEW_REQUIRED"|"APPROVED", review_reasons [],
  trace { packing [PackingTrace], actors [] } }
Sheet {
  sheet_id, number, of, label "PHASE I", scale_ft_per_in, zone_ids [], location_ids [], point_labels [],
  view { center_latlon, rotation_deg, extent_ft {width, height} },
  imagery [ {zone_id, artifact_ref, crop_px} ],
  title_block TitleBlock, dimensions [Dimension], banners [SheetBanner], two_ta bool, page_index }
TitleBlock {
  title "TRAFFIC MANAGEMENT PLAN - PHASE I",
  location { street TitlePart, number TitlePart, city TitlePart, state TitlePart, zip TitlePart },
  ewo TitlePart, drawn_by TitlePart, surveyed_by TitlePart, date TitlePart, print_no "1 OF 2", scale_text "1\" = 40'" }
TitlePart { value|null, source "OSM"|"AZURE_MAPS"|"PROJECT_INPUT"|"TEMPLATE"|"RUN", evidence_ref|null, status RESOLVED|UNKNOWN }
Dimension { dimension_id, kind SIGN_SPACING|SIGN_TO_WORK|TAPER|BUFFER|LANE_WIDTH, from_object_id, to_object_id,
            value_ft (from the trace, unrounded), display_text, display_rule, rule_id }
PackingTrace { zone_id, tried [ {scale_ft_per_in, fits, reason, overlaps_with [zone_id]} ], placed_on sheet_id, flags [] }
SheetBanner { kind DRAFT|REVIEW_REQUIRED|PLACEHOLDER_SYMBOLS|TWO_TA_SHEET|SCALE_OUTSIDE_RULE|GAP, text, source }
```

The sheet set is immutable per version. A change (new zone draft, S11 reorder, merge or split) writes a new version with `parent_version`; the old PDF stays. The head pointer per project uses compare-and-set. No raw path anywhere; the raw-path scan covers the new JSON.

### 4.3 Packing algorithm (proposal; D-26 is still Open in the plan)

1. Order the zones (B-8).
2. For the next zone, try the current sheet at 1" = 40'. It fits when its drawn box (B-6) and the boxes of the zones already on the sheet lie inside the viewport minus the keep-out regions, and its envelope does not overlap theirs along the road.
3. Else try the current sheet at 1" = 50' (the whole sheet changes scale).
4. Else start a new sheet with this zone and try 40, then 50.
5. A zone that does not fit alone at 50: B-5.
6. A sheet with two TAs is REVIEW_REQUIRED (plan 4A rule 4).
7. Number the sheets in order; label with Roman numerals; "n OF N" over the set.

Every try is written to `PackingTrace`, so the SME sees why a sheet broke.

### 4.4 Settings (config `sheets` section; drawing conventions, not regulatory, ADR-015)

| Key | Start value | Basis |
| --- | --- | --- |
| `scale_steps_ft_per_in` | `[40, 50]` | Plan section 4A, the golden scales |
| `fit_margin_in` | 0.35 | Existing renderer padding (`pad = 0.35 * u`) |
| `callout_offset_in`, `diamond_r_in` | 1.9, 0.75 | Existing renderer drawing symbols |
| `rotation_mode` | B-7 | |
| `order_mode` | B-8 | |
| `oversize_policy` | B-5 | |
| `template_version` | B-1 | |

## 5. What is drawn on each sheet

| Element | Source | Notes |
| --- | --- | --- |
| Aerial base | The zone run's recorded sheet aerial (Azure Maps), cropped and rotated in code | No new fetch unless B-14 says so (D-27: resize and crop in code first) |
| Work location | Zone work space (point, or extent from S8; footprint from S14) | Point labels from placemark names (D-72) |
| Devices | S8 objects; symbols from S5 by `device_id` | Placeholder label when any `PLACEHOLDER_ASSET` is used |
| Callouts | Sign code and legend, as today | Drawing convention |
| Dimensions | From object traces (B-11, B-12) | Never a value without a trace |
| Gaps | S8 `LayoutGap` and `PlacementFailure` | B-13 |
| PHASE label, title, location lines, fields | `TitleBlock` | B-2 to B-4, A-2 |
| Job notes | Generated lines (B-2) | Speed from the SME-typed start field, never observed |
| General notes, legend, details | Template | B-1, B-2, A-3 |
| Scale bar | Sheet scale | |
| North arrow | Drawn by code from `rotation_deg` (B-7) | The frame's fixed arrow is removed if the view rotates |
| Banners | Draft and approval state (B-10), REVIEW_REQUIRED, two-TA sheet, oversize | |

## 6. Commit sequence

Gate per commit: the fast tier plus the impacted suites (sheets, pipeline, web API, Vitest when the UI changes). Full suite once at the end of the slice.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED`; `sheets` config section and guard entry | [B] with 1 | Housekeeping |
| 1 | Template audit: compare the current frame with the three references element by element; list the 12 notes, details and legend; write `docs/reports/S12_template_audit.md` with crops | **[STOP]** | B-1, B-2 and A-3 must be answered before the template is built |
| 2 | Template v2 per B-1: new frame and layout files beside the old ones, `sheets/template.py`, template hash; tests on regions and hash | **[STOP]** | The look of every sheet; the owner checks a rendered blank |
| 3 | `sheets/models.py`, persistence through `StateStore` and `ArtifactStore`, schema and migration tests | [B] with 4 | Plumbing |
| 4 | `sheets/paper.py`, `sheets/fit.py`: viewport, keep-outs, rotation, drawn boxes; synthetic envelopes | [B] with 5 | Geometry, non-regulatory |
| 5 | `sheets/packing.py`: order, 40 then 50 then new sheet, overlap, two-TA flag, oversize policy; the parametrized packing cases | **[STOP]** | D-26 is Open; B-5, B-6, B-8 decide the golden outcome |
| 6 | `sheets/title_block.py` with the sources chosen in B-3 and B-4 | **[STOP]** | A new data source or a new input field; affects the post-S9 recording (B-3) |
| 7 | `sheets/dimensions.py`: dimensions from traces, display rounding | **[STOP]** | Presentation of regulatory numbers (B-11) |
| 8 | `sheets/sheet_set_renderer.py`: multi-zone viewport, PHASE label, n OF N, notes, scale bar 40 and 50, north arrow, placeholder label, banners, gap markers, symbols | [B] with 9 | Drawing |
| 9 | PDF set and PNGs: 34 x 22 in pages, deterministic bytes, artifact refs, output index, raw-path scan of the new JSON, local-path scan of the PDF | [B] | |
| 10 | `orchestration/sheet_stage.py`; project status hooks; API routes; `SheetSetView.tsx` and Vitest; web rebuild | [B] | |
| 11 | Golden structural check for Colorado, E Second St and Granite P32 (sheet count, labels, work points, scale) on S8 layouts | **[STOP]** | The first golden numbers; B-17 |
| 12 | Regenerate stored expected outputs only if B-16 changes the per-run sheet | **[STOP]** | D-83: stored oracles change |
| 13 | `docs/reports/S12_sheets_report.md`; full suite | [B] | Required finish |

Batches: commits 0 to 1 (stop), 2 (stop), 3 to 5 (stop), 6 (stop), 7 (stop), 8 to 10, 11 (stop), 12 (stop if needed), 13.

## 7. Tests

All offline. Layouts come from S8 on synthetic roads or recorded fixtures; no live call.

| ID | Test | Covers |
| --- | --- | --- |
| T-1 | **Packing cases** (parametrized): one zone at 40; one zone needing 50; one zone too big at 50 (B-5); two non-overlapping zones on one sheet; two overlapping zones on two sheets (E Second St shape); two TAs on one sheet flagged; three zones where the third forces a new sheet; order independence of the KML placemark order | Spec "packing cases" |
| T-2 | **Scale step**: the scale is 40 when it fits, 50 only when 40 fails, never 20, 30 or 60 unless B-5 allows it | Spec "scale step" |
| T-3 | **Template presence** on every page: notes, legend, three details, title block, revisions, Dig Safe, job notes, scale bar, north arrow; text elements found on the PDF text layer (test-only PDF reader, see B-1) | Spec "template presence" |
| T-4 | **Title-block fields**: each part carries a source; an unknown part prints blank or "VERIFY"; the street number appears only when the input has it; "n OF N" correct; PHASE labels in Roman numerals | Spec "title-block fields" |
| T-5 | **Page size** 2448 x 1584 pt on every page | Acceptance 3 |
| T-6 | **Dimensions come from traces**: every printed dimension has an object and rule id; changing a pack value (a test pack copy re-sealed with A = 120) changes the printed label | Acceptance 4, CLAUDE.md rule 3 |
| T-7 | **Placeholder label** on every sheet that uses a `PLACEHOLDER_ASSET`, and REVIEW_REQUIRED | S5 A5 |
| T-8 | **Draft and approval markings** (B-10) on every page; no page without one | D-65 |
| T-9 | **Gap markers**: every `LayoutGap` and `PlacementFailure` appears on the sheet or in its notes | Never drop silently |
| T-10 | **Determinism**: same inputs, same PDF and PNG bytes; a new version leaves the old artifacts unchanged (write-once) | Acceptance 5 |
| T-11 | **No raw path** in the sheet-set JSON; no local path in the PDF bytes | S2, S3 checks |
| T-12 | **Golden structure** for the three jobs per acceptance 1 (Granite at P32 only) | Acceptance 1 |
| T-13 | **API and UI**: sheet list, PDF link, banners; Vitest | |

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S8 `LayoutResult`, `Envelope`, `PlanObject` traces | Everything drawn, fit and dimensions | Planned (A-1) |
| S9 zones and their order along the road | Packing input; Granite and E Second St zone sets | Not planned yet (A-2) |
| S5 symbols and placeholder status | Device drawing, the label | Planned (A-3; S5 Q7 and Q8) |
| S10 statuses and exceptions | Banners; the existing `sme_exception_text` lines | Not planned yet |
| S11 reorder, merge, split and approval | New sheet-set versions; approval marking | Not planned yet (B-10, B-16) |
| S6 road name and evidence | Street line | Planned (the POC prints `site_summary.road_name` today) |
| Recordings after S9 (owner, `TCP_LIVE=1`) | Real imagery on E Second St and Granite sheets | Owner task; B-3 and B-14 must be decided **before** it |

Feeds: S11 (sheet versions), S13 (sheet structure and the PDF), S14 (footprint drawing).

## 9. What could go stale if S6 to S8 change (assumptions)

| Assumption | If it changes |
| --- | --- |
| A-1: S8 writes one `LayoutResult` per zone with `objects` (station, offset, side, latlon, device id, trace), `gaps`, `failures` and an `Envelope` with `upstream_ft` per approach and `kind EXACT` | `fit.py`, `dimensions.py`, gap markers. If S8 has no exact envelope, fit must recompute boxes from objects |
| A-1b: S8 B-3 (buffer) and B-4 (taper choice) are settled | Every envelope length, hence the Colorado scale (with a 155 ft buffer and a 100 ft taper the nearest sign sits about 355 ft out and W20-1 about 555 ft out each side, about 1,110 ft plus work length and callouts, which is near the 1,141 ft a 40 ft/in viewport holds) and the E Second St one-or-two-sheet result |
| A-1c: S8 B-6 `POINT_ONLY` work spaces | The work location is drawn as a symbol, not to scale, and the downstream parts are missing |
| A-2: S9 gives zones with an order along the road and the case id; S3 keeps `display_label` per location | Packing order, point labels |
| A-3: S5 symbols are pre-rendered PNGs addressable by `device_id` (S5 Q7 option A) and `placeholder_status()` returns the label text from config | Symbol drawing; the label |
| A-4: S6 keeps the road name with a source on the site model | Street line of the title block |
| A-5: each zone run still fetches and records the 2560 px sheet aerial | If S6 drops it, S12 needs its own fetch (a new request type that the recordings must contain; B-14) |
| A-6: the S3 project status vocabulary and `approval_state` from S11 | Banners and the sheet-set status |

Not stale: the template, the page size, the scale steps, the title-block format.

## 10. Where the plan, the spec and the repo differ (stop-and-report items)

1. D-71 says "road name only, the SME types no address"; the owner now wants street, city, state and ZIP, and the number when it is in the input. D-71 and plan open question 3 need new wording (not edited here).
2. The spec wants the drafts' style; the current frame comes from a fourth drawing not in the repo (B-1).
3. Note 11 on every draft (11 ft) contradicts the pack's 10 ft (B-2). The free-standing sign detail cites Sect. 6F.03, which is not loaded in the pack.
4. Plan section 4A lists the Granite phases differently from the accepted golden (section 1).
5. D-45 is "Proposed" in the plan's decision log, but the owner treats it as decided; D-26 (packing rules) is still "Open".
6. The renderer chooses from eight scales; the spec allows two.
7. Plan open question 3's default ("road name only") is superseded by the owner's constraint.
8. The slices doc runs S12 beside S10 and before S11, but S12 needs S11's sheet actions and approval state (B-16).

## 11. OPEN QUESTIONS

### Part A: client inputs and SME questions

**A-1. The client's current sheet template.** The frame in the repo is cut from WPI 3160485, not one of the three references.
- Options: (a) the client sends its current template (DWT or PDF); (b) use one of the three reference PDFs; (c) keep the current frame.
- Effects: (a) is exact; (b) and (c) may carry stale notes or logos.
- Suggestion: ask for (a); meanwhile B-1.
- Blocks: commit 2 sign-off, not its start.

**A-2. Title-block identity fields.** SURVEYED BY (drafts: PIKE TELECOM), DRAWN BY (initials), PREPARED BY and FOR, the EWO and WPI number, and the title text "TRAFFIC MANAGEMENT PLAN".
- Options: (a) the client states what an automated draft should print in each; (b) print "AUTOMATED DRAFT" style values, as today.
- Suggestion: (a), with the role-selected actor for DRAWN BY once S16 roles exist.
- Blocks: commit 6 values, not its code.

**A-3. The 12 general notes and the three details.** Is the text in the references the current client version? Note 11 says 11 ft; the pack draws to 10 ft. The details show dimensions (36 in, 18 in, 42 in, 60 in, 4 ft, 1 ft) taken from client artwork.
- Options: (a) the SME confirms the notes and details as client template artwork; (b) the SME supplies a revised note set.
- Effects: decides what B-2 prints.
- Suggestion: (a), with the 11 ft question answered explicitly.
- Blocks: commit 2.

**A-4. Locality name.** The drafts print "MATTAPAN, MA 02126" (a Boston neighbourhood) and "BOSTON, MA 02127". Which name goes on the second line: the city, the neighbourhood, or the USPS place name of the ZIP?
- Suggestion: the SME states the rule; until then the source's value as returned, flagged.
- Blocks: commit 6 sign-off.

**A-5. Scales beyond 50.** Only 40 and 50 appear on the drafts. Does the client ever use 60 or more?
- Effects: decides B-5.
- Blocks: commit 5.

**A-6. The Granite KML for WPI 3178233** (requested). Until it arrives Granite is compared at P32 only.
- Blocks: no.

### Part B: owner decisions

**B-1. Template source and form.**
- Options: (a) keep the current raster frame; (b) rebuild the frame from one reference PDF (for example E Second St) with `build_sheet_frame.py`, new files beside the old; (c) a vector template: frame lines and details as images, all text (notes, legend words, title fields) drawn as PDF text.
- Effects: (a) is unverified against the references. (b) matches the drafts. (c) makes the notes searchable and testable on the text layer (T-3), but needs the note text stored as template data. A test-only PDF reader (`pymupdf`, already a `tools` extra and banned from `src/`) is needed for T-3 in any option.
- Suggestion: (b) for the artwork plus (c) for every text element.
- Blocks: commits 1 and 2.

**B-2. What the general notes say.**
- Options: (a) print the 12 notes verbatim as client template text, labelled "client general notes"; (b) print them but replace note 11 with the pack's 10 ft statement and its rule id; (c) print notes 1 to 10 and 12, and list note 11 as a known difference until A-3 is answered; (d) no general notes, only pack-sourced notes.
- Effects: (a) prints 11 ft on a sheet drawn to 10 ft. (b) changes client text. (d) fails the spec's template list.
- Suggestion: (c) until A-3; then (a) or (b) per the SME.
- Blocks: commit 8.

**B-3. Source for city, state and ZIP.**
- Options: (a) Azure Maps reverse geocoding (allowed source; a new request type, so it must be in the recordings); (b) OSM via Overpass (admin boundaries for city and state; ZIP is sparse in OSM); (c) Census TIGER (the allowed source is "urban areas"; ZIP tabulation areas are a different product and not on the list); (d) a typed project field (conflicts with D-71).
- Effects: (a) needs fixtures. Decide **before** the owner records after S9, or the recordings miss the call and replay fails with a missing fixture.
- Suggestion: (a), recorded with the post-S9 recording; Colorado's recording after S7 would then need one extra call later.
- Blocks: commit 6, and the post-S9 recording plan.

**B-4. "Street number only if it is in the input": which input?**
- Options: (a) an optional typed title field on the project (display only, never used in decisions); (b) the placemark name (D-72 allows display only; extracting a number is parsing); (c) the KML file name (free-text parsing is future scope); (d) the reverse-geocoded house number (not "in the input").
- Effects: (a) amends D-71 for the number only. (b) and (c) parse free text.
- Suggestion: (a), with an EWO field next to it (A-2).
- Blocks: commit 6.

**B-5. A single zone that does not fit at 1" = 50'.** A rural or high-speed TA-33 layout (Table 6B-1 rural: 500 + 500 + 500 ft plus the taper, each side) exceeds a 50 ft/in viewport (about 1,425 ft wide).
- Options: (a) the next standard scale, flagged `SCALE_OUTSIDE_RULE` and REVIEW_REQUIRED; (b) split the zone's drawing over two sheets with match lines; (c) break lines with "not to scale" advance signs, dimensions labelled (the E Second St draft is schematic); (d) BLOCKED.
- Suggestion: (a) until A-5 is answered.
- Blocks: commit 5.

**B-6. What counts toward "fit".**
- Options: (a) the S8 envelope only; (b) the envelope plus callouts, dimension strings and labels, outside the keep-out regions; (c) (b) but callouts may sit over the notes box.
- Effects: (b) makes the 40 to 50 step happen earlier; Colorado may land at 50 (A-1b).
- Suggestion: (b), as the renderer does today.
- Blocks: commit 5.

**B-7. View rotation.**
- Options: (a) north-up, as today; (b) rotate so the main road runs left to right, as the drafts do, with a drawn north arrow.
- Effects: (b) fits longer layouts at 40 and makes "from sheet left/right" in the golden comparable in S13.
- Suggestion: (b).
- Blocks: commit 4.

**B-8. Sheet order.**
- Options: (a) along the road in a fixed geometric direction (for example increasing OSM way station), independent of placemark order; (b) KML document order; (c) the router's direction of travel.
- Effects: (b) makes sheet numbers depend on placemark order. Granite's KML lists P32 to P28 while its drawing ascends by pole number, so neither (a) nor (b) is known to match; names are never used (D-72).
- Suggestion: (a), reorderable by the SME in S11.
- Blocks: commit 5.

**B-9. Zones with no draft** (NO_TA_MATCH, ERROR, a gap that stops the layout).
- Options: (a) no sheet; (b) a sheet with the imagery, the work location and a banner naming the reason; (c) list them on the first sheet's notes.
- Suggestion: (b) for NO_TA_MATCH and gaps, (a) for ERROR.
- Blocks: commit 8.

**B-10. Draft and approval marking (D-65).**
- Options: (a) every sheet carries "DRAFT - AWAITING SME APPROVAL"; S11's approval writes a new sheet-set version rendered with an approval line ("approved, role selected, not verified", date); (b) the marking never changes; approval lives in the ledger only.
- Effects: (a) gives two PDFs per approved plan; the old one stays (write-once).
- Suggestion: (a).
- Blocks: commit 8 (marking), not packing.

**B-11. Display rounding of dimensions.**
- Options: (a) round to the nearest foot; (b) round up for AT_LEAST values (taper, buffer) and to the nearest foot otherwise; (c) print one decimal.
- Effects: the trace keeps the unrounded value in every option. The Granite draft prints 115' where Table 6B-4 gives 114.583 ft.
- Suggestion: (b), with the rule recorded on each `Dimension`.
- Blocks: commit 7.

**B-12. Which dimensions are printed, and how an uncertain value prints.**
- Options: sign-to-sign spacing, work-to-first-sign, taper and buffer lengths, lane widths. For a width with an interval: (a) print the measured value; (b) print "VERIFY"; (c) do not print widths.
- Suggestion: spacing, taper and buffer always; widths (b) when the interval straddles a threshold, otherwise (a).
- Blocks: commit 7.

**B-13. Gap markers on the drawing.**
- Options: (a) a red marker and label at the gap's station and a line in the notes; (b) notes only.
- Suggestion: (a).
- Blocks: commit 8.

**B-14. Imagery for a sheet with more than one zone.**
- Options: (a) composite the zones' recorded aerials in code; (b) a new mosaic fetch per sheet (a new request type, needs recording).
- Suggestion: (a); fetch only when the composite leaves a hole (D-27 spirit), and decide before the post-S9 recording.
- Blocks: commit 8 for multi-zone sheets.

**B-15. DWT and DXF output.** The block map is empty and no ODA converter exists here.
- Options: (a) PDF only in S12; DWT stays the POC single-run path; (b) also a DXF per sheet.
- Suggestion: (a).
- Blocks: no.

**B-16. Where the sheet set lives and when it is built.**
- Options: (a) a project-level stage after all zones settle, plus the per-run sheet as today; (b) project-level only, retiring the per-run sheet (stored expected outputs change, D-83); (c) per run only.
- Effects: (b) is cleaner and changes stored oracles. S12 before S11 means approval and reorder hooks are built against an assumed S11 shape.
- Suggestion: (a) now, (b) with S15's sweep; build S12 after S11 if possible.
- Blocks: commit 10.

**B-17. Granite in acceptance 1.** S9 groups P32 with P31; the golden Phase I holds P32 alone.
- Options: (a) compare only the label and scale of the sheet holding P32; (b) a test that uses the S11 regroup action to make P32 its own zone, then compares all four items (needs a P32-only recording; S0 has spike data for P32); (c) skip Granite until A-6.
- Suggestion: (a) in S12, (b) in S13 if the recording exists.
- Blocks: commit 11.

**B-18. The fast tier.** No pytest marker exists.
- Options: (a) S12 commit 0 adds a `slow` marker (assistant and full-pipeline suites) and a fast default; (b) whichever earlier slice adds it.
- Suggestion: (b), else (a).
- Blocks: no.

**B-19. Two TAs on one sheet.** Plan 4A allows it with REVIEW_REQUIRED.
- Options: (a) allow, flagged; (b) never.
- Suggestion: (a).
- Blocks: no.

### Summary table

| # | Question | Group | Blocks S12? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | Client's current sheet template | Client input | Commit 2 sign-off | Ask; meanwhile B-1 |
| A-2 | Title-block identity fields | Client input | Commit 6 values | Client states them |
| A-3 | The 12 notes and details, note 11 | SME question | Commit 2 | Confirm, answer 11 ft explicitly |
| A-4 | Locality name rule | SME question | Commit 6 sign-off | SME states the rule |
| A-5 | Scales beyond 50 | Client input | Commit 5 | Ask |
| A-6 | Granite KML WPI 3178233 | Client input | No | Requested |
| B-1 | Template source and form | Decision | Commits 1, 2 | Rebuild from a reference; text as vector |
| B-2 | General notes wording | Decision | Commit 8 | Notes 1-10, 12; note 11 a known difference |
| B-3 | City, state, ZIP source | Decision | Commit 6 and recording timing | Azure reverse geocode, recorded after S9 |
| B-4 | Which input holds the street number | Decision | Commit 6 | Optional typed title field |
| B-5 | Zone too big at 50 | Decision | Commit 5 | Next scale, flagged |
| B-6 | What counts toward fit | Decision | Commit 5 | Envelope plus callouts and labels |
| B-7 | View rotation | Decision | Commit 4 | Road left to right, drawn north arrow |
| B-8 | Sheet order | Decision | Commit 5 | Geometric along the road, SME reorders |
| B-9 | Zones with no draft | Decision | Commit 8 | Banner sheet for NO_TA_MATCH and gaps |
| B-10 | Draft and approval marking | Decision | Commit 8 | Watermark; approved version re-rendered |
| B-11 | Display rounding | Decision | Commit 7 | Up for AT_LEAST, nearest otherwise |
| B-12 | Printed dimensions, uncertain widths | Decision | Commit 7 | Spacing, taper, buffer; VERIFY on straddle |
| B-13 | Gap markers | Decision | Commit 8 | Marker and note |
| B-14 | Imagery for multi-zone sheets | Decision | Commit 8 | Composite recorded aerials |
| B-15 | DWT and DXF | Decision | No | PDF only |
| B-16 | Sheet-set stage and per-run sheet | Decision | Commit 10 | Project stage plus per-run for now |
| B-17 | Granite in acceptance 1 | Decision | Commit 11 | Label and scale only |
| B-18 | Fast tier marker | Decision | No | Earlier slice, else commit 0 |
| B-19 | Two-TA sheets | Decision | No | Allow, flagged |
