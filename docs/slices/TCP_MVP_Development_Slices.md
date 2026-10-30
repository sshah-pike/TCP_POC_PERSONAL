# TCP MVP: Development Slices for Claude Code

*Companion to TCP_MVP_Architecture_Plan_v4.md. Version 3 (paths after S0a), October 28, 2026. Base branch: `tcp-mvp/base`.*

Each slice below is written so a Claude Code prompt can be generated from it directly: goal, dependencies, scope, contracts, tasks, acceptance criteria, tests and a prompt seed. Module and file names are proposals. Statements about the existing repo come from VS Code Claude's earlier analysis and are unverified until slice S0's report confirms or corrects them. Where S0 finds a different name or structure, S0's finding wins.

## How to use this file

1. Run S0 first. Its report fixes file names and any wrong assumption.
2. For each later slice, build the Claude Code prompt as: the common preamble below, then the slice's prompt seed, then its acceptance criteria and tests copied verbatim.
3. One branch per slice off the previous slice (`tcp-mvp/base` for the first), named `tcp-mvp/sNN-short-name`. Merge only when the gate passes.
4. Setup once per environment: `pip install -e . --no-build-isolation` inside `.venv`.

*Future scope that no slice builds, such as suggesting police detail instead of a flagger from the work location, is kept in the plan, Section 16.*

## Common preamble for every Claude Code prompt

```
You are working in the TCP repository on branch tcp-mvp/<slice>. Read
TCP_MVP_Architecture_Plan_v4.md and TCP_MVP_Development_Slices.md first.

Rules:
- AI only observes the site. Rules, distances, TA choice and placement
  are deterministic code driven by the rule pack. Never hardcode a
  regulatory value; read it from the rule pack with its rule_id.
- Never invent a value. A value with no source stays empty and is marked
  SOURCE_REVIEW_REQUIRED, which forces REVIEW_REQUIRED.
- Unit and integration tests use recorded fixtures and fakes. Make NO
  live Azure Maps or AI calls in tests. Live calls only in the S13
  full-pipeline test, behind the env var TCP_LIVE=1.
- All thresholds and limits live in config or the registry.
- All persisted data uses artifact references {uri, sha256, size,
  media_type}, never raw paths, and carries a schema_version.
- Every plan object carries a trace record (rule_id, pack version and
  hash, source, inputs, calculation, validator results, actor).
- If the repo differs from the plan, stop and list options with
  trade-offs and a recommendation. Do not silently pick.
- Finish with: files changed, tests added, test results, open questions.
```

## Where code lives after S0a

| Area | Folder |
| --- | --- |
| Pipeline package | `src/tcp_planner/` with `intake/`, `geometry/`, `imagery/`, `data_sources/`, `ai/`, `site_model/`, `routing/`, `rules/`, `layout/`, `validation/`, `conflicts/`, `review/` (assistant in `review/assistant/`), `sheets/`, `orchestration/`, `storage/`, `audit/`, `evaluation/`, `web_api/`, `config/settings.py`, `contracts.py`, `cli.py` |
| UI | `apps/web/` |
| Data and config | `config/`, `rule_pack/`, `assets/` (symbols, sheet, DWT) |
| Tests | `tests/unit/`, `tests/integration/pipeline/`, `tests/integration/web_api/`, `tests/integration/review_assistant/`, `tests/golden/` |
| Run data | `var/` (old POC runs tracked in `var/runs/`, new runs ignored) |
| Backups | `backup/orphans/<date>/` with `MANIFEST.json`; restore with `scripts/restore_backup.py` |
| Reports | `docs/reports/` |

Module names in the slices below are targets inside these folders. The S0 report confirms or corrects them.

## Shared contracts

These shapes are used across slices. S1 creates them; later slices extend them with a new schema_version and a migration.

```
WorkLocation { location_id, ordinal, source{file, input_hash,
  placemark_index, name}, geometry{type: POINT|LINESTRING|POLYGON,
  coords}, geometry_hash, role: WORK|REFERENCE_ONLY, display_label,
  reject_reasons[] }
WorkZone { zone_id, version, location_ids[], grouping{method:
  KML_EXPLICIT|USER|AUTO_RULE|SME, case_id, rule_version, evidence},
  ta{value, source, status}, sheet_label, inputs, engine_geometry_hash,
  run_ids[], status }
Sheet { sheet_id, number, of, label ("PHASE I"), scale_ft_per_in,
  zone_ids[], template_version, title_block{} }
SiteFact { field, value, unit, confidence, uncertainty?, source:
  KML|UI|IMAGERY|OSM|MASSDOT|SME|PROJECT, evidence_ref, status:
  RESOLVED|UNKNOWN|CONFLICT }
PlanObject { object_id, device_id, station_ft, offset_ft, side,
  orientation, trace{rule_id, pack_version, pack_hash, source_ref,
  inputs[], calculation, validators[], actors[]} }
Question { question_id, kind, reason, options[], default_if_skipped,
  parent_id?, reveals[] }
```

---

## S0a. Production layout (done)

Done on `tcp-mvp/s00a-restructure` (9 commits). The POC packages `tcp_poc`, `tcp_ui` and `tcp_assistant` became one package `src/tcp_planner/`; the UI moved to `apps/web/`. Every test suite, all 13 offline scenarios and all 36 saved-run replays are identical to the baseline. Report: `docs/reports/S0a_restructure_report.md`.

Follow-ups carried into later slices:
- S0: fix `test_protected_run_dir_untouched` (D-79) and make Foundry the default AI provider (D-78).
- S2: store run paths relative to the runs folder, so runs can be resumed after a move (D-77).
- S15: the symbol-level backups left out of S0a (USGS and Esri provider classes, the direct Anthropic provider and its usage wrapper, `test_diagnostics.py`).
- Later, as one commit with a replay diff: rename output codes and strings that still say POC (`UNSUPPORTED_POC`, `SELF_CONFIRMED_POC`, "TCP POC Pipeline"). The rule pack file name changes in S4.

---

## S0. Repo verification, fixtures and schema spike

**Goal.** Verify the plan against the real repo, set up the fixture harness, close the two S0a follow-ups, and run the schema spike, so every later slice can be tested without live calls.

**Depends on.** S0a merged into `tcp-mvp/base`.

**In scope.** Run the Section 18 verification prompt and save its report as `docs/reports/S0_repo_report.md`. Add a fixture harness that records Azure Maps, OSM and AI responses once and replays them. List which existing suites still apply to the MVP. Fix the protected-run test and the default AI provider. Run the schema spike.

**Out of scope.** Any other behavior change.

**Tasks.**
1. Fixture recorder and replayer. Key fixtures by a request fingerprint. Replay mode is the default in tests and fails if a fixture is missing. Fixtures go in `tests/fixtures/`.
2. Seed fixtures from saved evidence (Granite single point P30, Alton Bradford and Exeter demos) with `python -m tests.support.record seed`. Recording the three real KMLs needs live calls and the pipeline cannot take them yet (it rejects more than one Point), so it moves to the recording task in S6 (Colorado after S7, the rest after S9, D-98).
3. Verification report: answer items 1 to 34 of the Section 18 prompt with file and line evidence.
4. Fix `test_protected_run_dir_untouched` so it checks that `var/runs/20261020-214203-7f7232` is tracked and unchanged (D-79). After this, every suite is green.
5. Make Foundry the default when `TCP_AI_PROVIDER` is unset, and fail with a clear message when Foundry is not configured (D-78). This is a deliberate behavior change in its own commit.
6. Once fixtures exist, replace the git-HEAD oracle in `test_global_identity.py` with fixture replay.
7. Schema spike: run `docs/slices/schema_spike_prompt.md` (the only live calls allowed in S0, behind `TCP_LIVE=1`, at most 18 AI calls, JSON only). Its report decides the call 1 and call 2 output format (D-61). Nothing in S6 is built before it.

**Acceptance criteria.**
- `pytest` runs with no network access and no live calls, and every suite is green.
- A replayed saved run gives the same request fingerprints twice.
- The report lists every confirmed, refuted or unknown assumption, with file paths.
- `spikes/schema_spike/REPORT.md` exists with results for the current schema and the facts list, and a recommendation.

**Tests.** Fixture replay determinism; a missing fixture raises a clear error; the network is blocked in the test environment; unset `TCP_AI_PROVIDER` selects Foundry.

**Prompt seed.** "Create branch tcp-mvp/s00-setup from tcp-mvp/base. Build a fixture recorder and replayer for Azure Maps, OSM and AI calls, keyed by request fingerprint, with replay as the test default. Fix the protected-run test (D-79) and make Foundry the default provider (D-78), each in its own commit. Then run the verification prompt in Section 18 of the plan and write docs/reports/S0_repo_report.md. Stop and report. The schema spike is a separate session."

---

## S1. Domain model and KML intake

**Goal.** Read every feature of any KML into WorkLocation records. Nothing is discarded, and unusable features keep a reason.

**Depends on.** S0.

**In scope.** Parse Point, LineString, Polygon, MultiGeometry and nested Folders, reading coordinates only (D-66). All `ExtendedData`, including `tcp:` keys and `selected_ta`, is ignored (future scope). Placemark names are kept only as display labels. Assign stable location ids. Detect duplicates under 1 m (case 13).

**Contracts.** WorkLocation as above. Reject reasons include `INVALID_GEOMETRY`, `EMPTY`, `UNSUPPORTED_TYPE` and `DUPLICATE_OF:<id>`.

**Acceptance criteria.**
- Granite parses to 5 Points with gaps of 32.2, 39.2, 36.4 and 31.7 m, E Second St to 2 Points 102.5 m apart, and Colorado to 1 Point.
- Location ids are the same regardless of placemark order.
- A KML with `ExtendedData` parses the same as one without it.

**Tests.** The parse matrix in plan Section 14; id stability; names never used in decisions.

**Prompt seed.** "Implement the WorkLocation model and parse_all() for KML as specified in slice S1. Keep the existing single-point parse working through the new path. Add the tests listed."

---

## S2. Storage interfaces

**Goal.** All reads and writes go through thin interfaces with local adapters, so data is content-addressed and replayable. Includes the S0a follow-up: run records store paths relative to the runs folder (D-77).

**Depends on.** S0.

**In scope.** `ArtifactStore` (blobs), `StateStore` (index, events, heads, compare-and-set) and `RulePackStore` (interface only, implemented in S4). Local filesystem adapters only, files only (D-84): artifacts as files, state as one `.state.json` file per record and one `.events.jsonl` file per stream, each run's state inside its own run folder. Artifact references, schema versions and migrations. A project store.

**Out of scope.** Cloud adapters and the migration tool (deferred, D-40). A database adapter (future scope, D-84).

**Acceptance criteria.**
- No raw path in any persisted JSON (checked by a test that scans outputs).
- Artifacts are write-once. Rewriting one with different bytes fails.
- Compare-and-set rejects a stale head.

**Tests.** A contract test suite that any adapter must pass; a no-raw-path scan; a schema migration round trip.

**Prompt seed.** "Introduce ArtifactStore, StateStore and RulePackStore interfaces with local adapters per slice S2. Route the existing run writes through them without changing outputs. Add the contract test suite."

---

## S3. Project orchestrator and per-zone runs

**Goal.** One flow for every KML: a project with work locations and zones, one child run per zone, and a project status.

**Depends on.** S1, S2.

**In scope.** Project wrapper; a single point as a one-zone project; the engine input extended with zone, TA and sheet metadata; a zone-to-engine adapter that builds a work path from ordered points; an idempotent orchestrator; project statuses including `ZONE_CAP_APPROVAL_REQUIRED` and `PARTIAL`; the max-zones cap from config; a location list in the UI for display and edit; the mandatory start fields (D-59: road type, speed, traffic volume, lane closure) entered per project with "apply to all points" and per-point edit, with Run disabled until all are filled. No code fills them. A "Select TA" dropdown (Auto, TA-1, TA-6, TA-10, TA-33), per project and per point, default Auto (D-73). Placemark names shown as point labels (D-72).

**Acceptance criteria.**
- A single-point KML runs as a one-zone project end to end on replayed fixtures.
- A multi-zone project runs every zone. One failed zone gives `PARTIAL` and keeps the others' drafts.
- Retrying the orchestrator does not duplicate runs.
- Above the max-zones cap, nothing runs until approval.
- Run cannot start while any mandatory start field is empty.

**Tests.** One-zone project; multi-zone with one forced failure; idempotent retry; cap holds before any external call.

**Prompt seed.** "Implement the project orchestrator per slice S3. Grouping is a stub for now: one zone per point unless the SME grouped points in the UI. Extend the engine input with zone context. First confirm in S0's report how the engine measures sign stations from a path, and stop if it differs from the plan."

---

## S4. Rule pack v1

**Goal.** A composed, table-shaped rule pack for TA-1, TA-6, TA-10 and TA-33, built from the supplied MUTCD 11th Edition Chapter 6 (December 2023 revision), behind `RulePackStore`. Field names must match the general and per-TA input schema in plan Section 4B.

**Replaces the POC pack (D-81).** Rule pack v1 replaces `rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json`, which is the only pack in `rule_pack/` until then. The six KMLs in `docs/references/kml/` (the three real sites and the TA-6, TA-10 and TA-33 examples) are its test inputs.

**Depends on.** S0. Can run in parallel with S1 to S3.

**In scope.**
- File layout: `rule_pack/base/*.json` (shared tables and formulas), `rule_pack/ta/TA-1.json` and the other TAs, `rule_pack/client/*.json` (client practice layer), `rule_pack/jurisdiction/RI.json` and `MA.json`.
- Records as flat arrays per table: `source_document`, `source_ref`, `ta`, `eligibility_condition`, `rule`, `formula`, `table_def`, `table_row`, `device`, `ta_device_use`, `deviation`, `registry_field`.
- Load these from Chapter 6, each with a `source_ref` to table, section and page:
  - Table 6B-1: A, B and C spacing by road type.
  - Table 6B-2: stopping sight distance by speed.
  - Table 6B-3: taper types.
  - Table 6B-4: L = WS²/60 at 40 mph or less, L = WS at 45 mph or more.
  - Section 6K.01 para 04: device spacing in a taper is 1 × speed, in a tangent 2 × speed.
  - The notes and sign sequences of Figures 6P-1, 6P-6, 6P-10 and 6P-33.
  - Section 6N.07 (minimum 10 ft lane width, 9 ft option) and 6N.11 (TA-33 on undivided four-lane roads).
- Client layer from plan Section 10 (D-51): 100 ft buffer at urban 25 mph, police variant of TA-10, the no-parking, side-street, pedestrian and RI double-fines modules, and the 11 ft note. Each entry cites its draft and is marked PROPOSED until your SME confirms.
- `RulePackStore` JSON implementation, pack hash over all parts, a validator for ids, references, units and sources, and an effective-rules view in precedence order: federal, jurisdiction, client, deviations.

**Acceptance criteria.**
- Every value has a `source_ref`. A value with none is `SOURCE_REVIEW_REQUIRED` and is reported.
- Pack hash is stable, and changing any record changes it.
- Unit tests reproduce Table 6B-4 for sample inputs: W = 11 ft, S = 25 mph gives L ≈ 114.6 ft; W = 12 ft, S = 45 mph gives L = 540 ft.
- Precedence works: the client 100 ft buffer overrides the optional Table 6B-2 value only where the client layer applies.

**Tests.** Loader and validator; formula tests; precedence tests; a test that the engine reads no rule file directly.

**Prompt seed.** "Build rule pack v1 per slice S4 from the supplied Chapter 6 PDF in docs/sources. Use AI-assisted extraction only to draft records. Every record must quote its table, section and page. Mark client-layer rules PROPOSED. Produce a review report listing every value and its source for SME sign-off."

**Amendment 2026-10-30.** The S4 scope lines above are kept as merged. The client layer (`rule_pack/client/*.json`, the client 100 ft buffer, the police variant of TA-10, the add-on modules and the 11 ft note) is withdrawn by D-51 and was not built; the buffer is a per-zone choice (D-94) and add-ons come from sourced sections (D-90). The line on 6N.11 ("TA-33 on undivided four-lane roads") is narrowed to a Granite-type case by D-91.

---

## S4b. Pack extension round

**Goal.** Close the pack gaps that S5 commits 3 and 4 and S8 depend on, as quoted, sourced pack rows (owner decisions D-91 and D-99, added 2026-10-30).

**Depends on.** S4.

**In scope.**
- Sign sizes as quoted pack rows (the work S5 commit 3 was to do).
- Device rows for note-only signs (the work S5 commit 4 was to do).
- Placement anchors: what A, B and C are measured from (consecutive gaps ending at the taper start for TA-6 and TA-33, or at the flagger station for TA-10; SME confirms).
- Add-on sections: sidewalk closed (R9-9, R9-11 family) and detour (M4-9 family). No-parking (R8-3) and RI double fines wait for sources.
- The 6N.11 split: Granite-type case sourced, broader cases an engineer question.

**Acceptance criteria.** To be set when S4b is planned. Every value is quoted with page and rule id; a value with no source stays `SOURCE_REVIEW_REQUIRED`. The manifest stays DRAFT. The pack hash change is recorded.

**Runs.** Before S5 commit 3 and before S8. S5 resumes after S4b is merged.

---

## S5. Device catalog and symbol library

**Goal.** Every device a plan can place exists in the catalog, with a symbol, and the renderer can draw it.

**Depends on.** S4.

**Changed 2026-10-30 (D-99):** commits 3 and 4 of the S5 plan (sign sizes as quoted pack rows; device rows for note-only signs) move to slice S4b. S5 resumes after S4b is merged.

**In scope.**
- Import `assets/symbols/device_catalog.json` (v0.1, 51 entries) into the pack's `device` table.
- Link `ta_device_use` for the four TAs.
- Validators: every placed device exists, and its size comes from the catalog for the road type.
- Renderer lookup by `device_id`, with the visible "placeholder symbols" label and REVIEW\_REQUIRED when any `PLACEHOLDER_ASSET` is used.
- A loader for your CAD blocks later: drop-in replacement by `device_id`.

**Acceptance criteria.**
- All signs on the four MUTCD figures and the three drafts resolve to catalog entries.
- CLIENT\_CODE and STATE\_CODE entries are listed in the review report.
- Swapping one SVG for a client asset changes only that symbol and the catalog hash.

**Tests.** Catalog integrity; size lookup per road type; placeholder labelling; asset swap.

**Prompt seed.** "Integrate the device catalog and symbols per slice S5. Do not alter sizes from their cited tables. Add the placeholder label to rendered sheets."

---

## S6. Site understanding

**Goal.** Call 1 returns the common and deciding facts with confidence and evidence, and geometry, width and crops follow the plan.

**Changed 2026-10-30 (D-96, S6 plan Q1 B):** S6 runs in two sessions (session 1: call 1, measurement, crops, OSM, wiring; session 2: data sources). Cutover chain: S6 builds beside the old path, S7 adds a non-gating route stage, S8 cuts over once with regenerated oracles the owner reviews.

**Depends on.** S3.

**In scope.**
- Call 1 output in the format chosen by the S0 spike (D-61; the expected result is the flat facts list). Fields from plan Section 4B observed and computed groups. The AI returns positions; it never reports a length in feet (D-64).
- Code computes every length: lane, shoulder and median width, distance from edge, encroachment to the device face, remaining width, gaps, path length, side-road distance, curves and crests (USGS 3DEP).
- Mandatory start fields (D-59) are read from the project and never calculated, pre-filled or overwritten. A computed check that contradicts one creates a conflict question.
- Data sources (D-53, D-62, D-63): Azure Maps, OSM via Overpass (the tag list in plan Section 5), MassGIS, RIGIS, HPMS, Census urban areas, USGS 3DEP, MBTA and RIPTA GTFS, FRA crossings. All fused values are low confidence, imagery decides, disagreements are recorded (D-37).
- Width with uncertainty (D-38).
- Every image resized in code to the model limit (from S0's report).
- Spike requirements (D-80): `lanes_per_direction` is cross-checked against OSM lanes and state data, and a disagreement makes it UNKNOWN with an SME question; width comes from `cross_section.py` first and AI marks second, and an invalid or missing mark makes the width UNKNOWN; each evidence string is capped at 15 words and UNKNOWN facts carry a short fixed reason, per `docs/reports/S0_prompt_tuning_proposal.md` once approved.
- Hybrid crops: code crop first, a higher-zoom fetch only when pixels are insufficient.
- Pre-calculation per plan Section 4C: vehicle width and footprint (measured, else cited default flagged `DEFAULT_ASSUMED`), the remaining-width table, shadow vehicle, TMA suggestion and arrow board.

**Acceptance criteria.**
- On replayed fixtures, every deciding fact is RESOLVED with evidence or UNKNOWN. None is guessed.
- A width interval that contains a TA threshold makes the fact UNKNOWN and raises a question.
- A higher-zoom fetch happens only when the pixel threshold fails, and it is recorded as evidence with a signature.

**Tests.** Mandatory fields are never written by code; a computed remaining width that contradicts `lane_closure` creates a conflict, not a change; no length comes from the AI (a test fails if a length field appears in AI output); length computations against fixtures with known pixel scale; every observed field resolves to RESOLVED or UNKNOWN; fusion disagreement recorded; only the approved sources are called (a mock fails the test otherwise); the remaining-width table as a parametrized test; crop decision with mocked pixel counts.

**Recording task (run by the owner, `TCP_LIVE=1`; changed 2026-10-30, D-97, D-98).** The 9-call check on gpt-5.6-sol and on claude-opus-5-5 comes before any recording. Colorado is recorded once after S7 merges (calls 1 and 2 together); E Second St and Granite after S9. Granite is compared at pole P32 (Phase I) only. Record with `python -m tests.support.record live`, which calls `use_os_trust_store()` first. This is the third live-call exception in CLAUDE.md. Then add replay tests for them: the same request fingerprints twice.

**Prompt seed.** "Extend call 1 and fusion per slice S6. Use only recorded fixtures in tests. Keep the two-AI-call budget per zone."

---

## S7. Router and call 2

**Goal.** Code chooses the TA from facts and the pack. Call 2 fills only the chosen TA's missing fields.

**Depends on.** S4, S6.

**In scope.**
- Router over pack TAs only, with the five outcomes, near match ("did you mean", at most 1 failed condition, at most 2 suggestions) and thresholds (D-33).
- `TA_SELECTION_CONFLICT` against a TA hypothesis entered in the UI.
- The routing tree and explicit eligibility (D-60): TA-6 requires `shoulder_present` and a low-speed minor road (note 2; cutoff `SOURCE_REVIEW_REQUIRED` until set) with width to the device face; TA-33 is one OR'd rule citing 6P-33 and 6N.11, so a Granite-type case (undivided, two lanes each way, right lane closed; D-91) qualifies. Broader undivided cases are an engineer question.
- `traffic_control_method` set by code to Flagger when TA-10 is chosen (D-68). Police details are not applied by the router.
- Call 2 with crops for unresolved TA fields. It never overwrites a resolved fact, and safety-critical facts go through the cross-view check.
- Spike requirements (D-80): call 2 re-asks `lanes_per_direction` with a lane-marking crop; it requests lane lines, shoulder edge and curb marks from crops; and it resolves `sidewalk_present` and `sidewalk_side` with a crop plus OSM sidewalk tags.

**Acceptance criteria.**
- On golden fixtures the router returns TA-10 for Colorado, TA-6 for E Second St and TA-33 for Granite, or a question when a deciding fact is unknown. It never returns a wrong TA silently.
- With no fitting TA it returns `NO_TA_MATCH` with failed conditions per pack TA and names no TA outside the pack.

**Tests.** All router outcomes; each branch of the routing tree; TA-6 rejected without a shoulder and on a high-speed road; TA-33 never double-matches; TA-10 always drafts with flaggers; near match; conflict with the Select TA choice; call 2 non-overwrite.

**Prompt seed.** "Implement the deterministic router and call 2 per slice S7. Every decision must carry the rule ids it used."

---

## S8. Layout engine per TA

**Goal.** Place every device for a zone from the effective rules, in road coordinates, with a trace for each object.

**Depends on.** S4, S5, S7.

**In scope.**
- Strategies for TA-1, TA-6, TA-10 and TA-33 on one common placement core. Advance signs come from Table 6B-1 A, B and C spacing on both approaches where the figure shows them.
- Tapers from Tables 6B-3 and 6B-4, buffers from Table 6B-2 when chosen per zone (client layer withdrawn, D-51), channelizer spacing from 6K.01, and end signs.
- Add-on modules, optional per zone (changed 2026-10-30, D-90, D-51 withdrawn, D-68 deferred): sidewalk closed and detour, built from the S4b sections. No-parking and RI double fines wait for sources. Client modules and police detail are out of scope.
- Validators with independent recomputation.
- The layout envelope per zone, used by S9.

**Acceptance criteria.**
- For the golden jobs, the advance-sign order per approach equals the golden order.
- Labelled spacing matches within 10 ft. For Colorado, 100 ft spacing comes from Table 6B-1 urban low speed.
- Every PlanObject has a complete trace.
- A sign with no valid spot goes to the ladder (S10) and is never dropped silently.

**Tests.** Per-TA placement on synthetic straight roads; spacing and taper math; modules on and off; envelope length.

**Prompt seed.** "Implement the layout engine per slice S8 with one shared placement core and four TA strategies. Read all distances from the effective rules."

---

## S9. Grouping engine and zone split

**Goal.** Group points into zones using the case table in plan Section 4A, in two passes.

**Depends on.** S3, S8.

**In scope.**
- Cases 1 to 18. Per-TA settings `merge_max_gap_ft`, `max_points_per_zone` and `max_zone_path_m` in the registry.
- First pass on geometry and a conservative envelope. Second pass after routing, which may propose a regroup.
- Automatic split over 150 m with `ZONE_SPLIT_AUTOMATIC` (D-19).
- `GROUPING_RULE_REVIEW_REQUIRED` until your SME confirms the settings.

**Acceptance criteria.**
- Granite KML: with the start value `max_points_per_zone` = 3, two zones, P32 to P31 and P30 to P28, split at the largest gap (39.2 m).
- E Second St: two zones.
- Colorado: one zone.
- The result is identical for any placemark order. Every case 1 to 18 has a test.

**Tests.** The case table as a parametrized test; order independence; split at the largest gap.

**Prompt seed.** "Implement grouping per slice S9 and the case table in plan Section 4A. Each zone records the case id that formed it."

---

## S10. Conflicts and exceptions

**Goal.** Handle obstructions and rule failures through the ladder, with exceptions recorded correctly.

**Depends on.** S8.

**In scope.**
- `GEO-SIGN-OBSTRUCTION` for all TAs.
- The ladder: move within a sourced band, work-fact change, SME exception, blocked.
- Taper and buffer have no pre-approved band. An SME may move them manually as a one-off exception that is never promoted.
- Exception scoped to one plan version, with one-click reuse only on an exact match (D-29).
- Pre-approved deviations with a named approver role from a config list (D-28).
- Status labels as in Section 7.

**Acceptance criteria.**
- A tree on a sign spot moves the sign within a band, or raises an exception question.
- The automatic search never moves taper or buffer.
- An exception never carries to a new version unless reused on an exact match.

**Tests.** The ladder cases; taper and buffer protection; exact-match reuse and mismatch; approver permissions.

**Prompt seed.** "Implement the conflict ladder and exception records per slice S10. Follow the plan's Section 7 exactly for taper and buffer."

---

## S11. Question form and SME review

**Goal.** All blocking questions appear on one form with sub-questions, and every SME action resumes at the earliest affected stage.

**Depends on.** S9, S10.

**In scope.**
- The batched form, including the questions listed in plan Section 8.
- Regroup, merge, split and reorder sheets.
- The TA-change flow with impact preview.
- Zone-level reuse keys (D-09).
- Per-zone review with project-scoped history and "inherit" (D-10).
- The append-only ledger.
- The SME approval gate `require_sme_approval_for_all_plans`, default true (D-65): every plan waits for a click and shows whether it would have been SUPPORTED_AUTO.
- Asked-if-needed fields (duration, night work, heavy vehicles and the rest, plan Section 4B) appear only when a rule needs them. `work_side` always appears as an AI suggestion for the SME to confirm (D-69).

**Acceptance criteria.**
- Answering a question resumes with zero new external calls when signatures match.
- A TA change reruns from the router and makes one new call 2 at most.
- Editing one placemark reruns only its zone.

**Tests.** Replay with zero calls; regroup resume; TA change; ledger is append-only.

**Prompt seed.** "Implement the question form and review actions per slice S11. Every action is a deterministic function and writes a ledger entry."

---

## S12. Sheets and PDF

**Goal.** Produce the sheet set exactly in the style of your drafts.

**Depends on.** S8, S9.

**In scope.**
- Sheet packing per plan Section 4A: fit at 1 in = 40 ft, then 50 ft, then a new sheet. No overlap on one sheet. Two TAs share a sheet only if both fit.
- Titles "PHASE I" and so on, numbered "n OF N", no cover page.
- The common template: legend, the 12 general notes, Type III barricade detail, drum and cone detail, free-standing sign detail, title block, revisions box, DigSafe box, job notes, scale bar and north arrow.
- Title-block data: the location line uses the road name the POC already prints (D-71); point labels from placemark names (D-72); no address typed by the SME.
- Azure Maps imagery as the base and dimension labels on the drawing.

**Acceptance criteria.**
- For each golden job the sheet count, phase labels, work points per sheet and scale equal the golden.
- Template elements are present on every sheet.
- The PDF is 34 x 22 in.

**Tests.** Packing cases; scale step; template presence; title-block fields.

**Prompt seed.** "Implement sheet packing and the PDF sheet template per slice S12. Match the layout of the three reference PDFs in docs/references."

---

## S13. Golden comparator and full-pipeline test

**Goal.** Measure how close the output is to your drafts and explain every difference.

**Depends on.** S12.

**In scope.**
- A comparator over the golden JSON:
  - Exact: TA, sheet count, work points per sheet, scale, advance-sign order and code set.
  - Tolerance: position within 15 ft and spacing within 10 ft, using the labelled value where the draft is schematic.
  - Side of road must match.
- Report categories: RULE\_GAP, CLIENT\_PRACTICE, FIELD\_JUDGMENT, SCHEMATIC\_DRAFT, EXTRACTION\_ERROR; no post-draft variant category: police detail is future scope (D-68), so the Colorado difference is reported as a known difference.
- The live full-pipeline test on the three KMLs behind `TCP_LIVE=1`.
- Golden v0.2 after your SME's corrections.

**Acceptance criteria.**
- The report runs on replayed fixtures in CI and live on demand.
- Every difference has a category.
- No exact-rule failure is left unexplained.

**Tests.** Comparator unit tests on synthetic diffs; replayed end-to-end on the three jobs.

**Prompt seed.** "Implement the golden comparator and the live full-pipeline test per slice S13. Never run live calls unless TCP_LIVE=1."

---

## S14. Polygon and line normalization

**Goal.** Work areas drawn as lines or polygons run through the same pipeline.

**Depends on.** S9.

**In scope.**
- Validate, orient and project geometry, rejecting it with reasons when unusable.
- Map each geometry type to an engine work path.
- Lines over 150 m are split (case 5).
- Polygon effects on fusion, validators and the SME image.

**Acceptance criteria.**
- A polygon with a hole and a concave polygon map to a valid work path.
- An invalid ring is rejected with a reason.

**Tests.** Polygon and path fixtures; invalid rings; split of long lines.

**Prompt seed.** "Implement the geometry normalization layer per slice S14 without changing point behavior."

---

## Order and parallel work

S0, then S1 and S2 in parallel, then S3. S4 and S5 can run beside S1 to S3 (changed 2026-10-30: S4b runs after S4 and before S5 commit 3 and before S8; S5 resumes after S4b). Cutover chain across S6, S7 and S8: S6 builds beside the old path, S7 adds a non-gating route stage, S8 cuts over once (D-96). Then S6, S7, S8, S9, then S10 and S12 in parallel, then S11 and S13. S14 can follow S9 at any time. S15 runs once after S3 and again after S14. S16 (rule management UI) is last.

---

## S15. Orphan sweep: unused files and code to backup

**Goal.** Find files and code the MVP no longer uses and move them to `backup/`, with a manifest, so the codebase stays clean and nothing is lost. Nothing is ever deleted.

**Depends on.** S0 for the repo report. S0a already moved 16 whole files to `backup/orphans/2026-10-28/`. The first S15 run comes after S3 and starts with the symbol-level items S0a left behind (USGS and Esri provider classes, the direct Anthropic provider and its usage wrapper, `test_diagnostics.py`). The final run comes after S14.

**Two kinds of orphan.**
1. **Orphaned files:** modules, scripts, configs, assets, data files and tests that nothing reaches.
2. **Orphaned code:** functions, classes, constants and branches inside live files that nothing calls.

The known candidates from earlier work are the USGS imagery code and the direct-Anthropic client, which the POC already marked unused. The old single-TA-1 path is another candidate once the new pipeline replaces it.

**How candidates are found.** Use several methods. A file is an orphan only when every method agrees.
- **Static reachability:**
  - Python: build an import graph from every entry point (CLI, app server, workers, tests of live code) using an AST walk.
  - TypeScript in `apps/web`: use `knip` or `ts-prune` and `unimported`.
  - Unused dependencies: `depcheck` for npm, and an import scan for `requirements` and `pyproject`.
- **Dead-code scan:** `vulture` for Python at 80 % confidence or more, and the TypeScript tools above for unused exports.
- **Runtime evidence:** coverage from the full test suite plus one replayed full-pipeline run of each real KML. Code never executed is a suspect, not a proof.
- **String references:** search the repo, configs, `pyproject` scripts, Dockerfiles, CI files, HTML templates and JSON for the file or symbol name. This catches dynamic imports, plugin registries and entry points that static analysis misses.
- **Git history:** last commit date and author, recorded in the manifest for context.

**Classification.** Every candidate gets one label with its evidence.

| Label | Meaning | Action |
| --- | --- | --- |
| `CONFIRMED_ORPHAN` | Unreachable statically, never executed, no string reference, not an entry point | Moved after your approval |
| `SUSPECT` | Some evidence of use, such as a string reference, a dynamic import or an allowlisted entry point | Listed only, never moved |
| `KEEP` | On the allowlist: entry points, migrations, fixtures, golden files, the symbol library, docs, the backed-up POC | Never moved |

**How files move.**
1. Stop and show the full candidate list (`docs/S15_orphan_report.md`). Move nothing until you approve it.
2. Move approved files with `git mv` into `backup/orphans/<YYYY-MM-DD>/<original path>`, so history is kept.
3. Exclude `backup/` from imports, packaging, linting, type checks, test discovery and coverage (`pytest` `norecursedirs`, `tsconfig` `exclude`, linter ignores, packaging excludes).
4. Write `backup/orphans/<date>/MANIFEST.json`. Per item it records:
   - original path and new path, kind (file or code), symbol name for code;
   - label, evidence from each method, and the `sha256` of the moved bytes;
   - the commit before the move, last commit date and author;
   - the restore command.

**How orphaned code moves.** Only for `CONFIRMED_ORPHAN` symbols inside live files.
- Cut the symbol into `backup/orphans/<date>/snippets/<module_path>__<symbol>.py` (or `.ts`). A header records the original file, line range and commit.
- Remove it from the live file, and remove imports that become unused.
- Tests that only test moved code move with it, into `backup/orphans/<date>/tests/`.
- Symbols listed in `__all__`, exported from a package `__init__`, or used through `getattr` or registries are never moved.

**Restore.** `scripts/restore_orphan.py <manifest-id>` moves an item back to its original path and checks its `sha256`.

**Acceptance criteria.**
- All suites are green after the move.
- One replayed full-pipeline run of each real KML gives the same request fingerprints and the same plan outputs as before the move.
- The UI builds.
- No file is deleted. Every moved item is in the manifest, and restoring a sample item reproduces the original bytes.
- `backup/` is not imported by anything (a test checks this).

**Tests.**
- An import-graph test proving live code does not reach `backup/`.
- A restore round trip.
- Before and after comparison of replayed fixtures.
- A check that every allowlisted path still exists.

**Prompt seed.** "Run the orphan sweep per slice S15. Build the candidate list using import graphs from all entry points, vulture, knip or ts-prune, depcheck, coverage from the test suite plus one replayed run per real KML, and a repo-wide string search including configs and CI. Classify each item as CONFIRMED_ORPHAN, SUSPECT or KEEP with its evidence. Write docs/S15_orphan_report.md and STOP for my approval. After approval, git mv approved files and cut approved symbols into backup/orphans/<date>/ with MANIFEST.json and a restore script. Delete nothing. Then rerun all tests and the replayed pipeline and show that outputs are unchanged."

---

## S16. Rule management UI (last slice)

**Goal.** A read-only browser for the rule pack first, then approval of rule changes as an append-only record (owner decision D-102, added 2026-10-30).

**Depends on.** All earlier slices. Planned last. Scope and acceptance criteria are set when S16 is planned (see docs/plans/S16_plan.md).
