Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md; where they differ from this plan, the register wins.

# S13 plan: golden comparator and full-pipeline test

Planning only. Branch when built: `tcp-mvp/s13-golden`, off `tcp-mvp/s12-sheets` (the slices doc runs S13 after S12, beside S11). Written on `tmp/plan-base4` (S1 to S4 merged). Nothing here is approved until the owner says so.

Read for this plan: CLAUDE.md; slice specs S7, S8, S11, S12, S13; plan sections 4A, 8, 10, 14 ("Golden set", "Will the output match your drafts exactly?"), 15 (D-45, D-50, D-65, D-68, open questions 8, 9, 10) and ADR-037; `S2_storage_report.md` (LF decision); `S3_orchestrator_report.md`; `S4_rule_pack_review.md` (proposal on S8 modules and S13 known differences); the plan copies `docs/plans/S5_plan.md` to `S8_plan.md` (not final), in particular S6 Q18, S7 B-1, B-8, B-9 and S8 commit 12; `tests/golden/README.md`, `build.py`, `extract.py`, the three golden JSON files; the three reference PDFs; `src/tcp_planner/evaluation/`.

Owner constraints applied:
- Rules come from the MUTCD Chapter 6, December 2023, only. The drafts are comparison material.
- **Two scores**: a **core** score (items the tool is meant to produce from the MUTCD) and a **full** score (everything in the draft, unbuilt extras counted as misses). An add-on moves into the core score once it is built.
- Golden v0.1 is accepted, used with tolerances. Granite is compared at pole P32 (Phase I) only; the KML for WPI 3178233 has been requested. E Second St and Colorado are compared whole. Colorado's police variant is future scope.
- Known expected differences: the 100 ft buffer (Colorado), the 11 ft lane width, no-parking signs, RI double fines, detours, sidewalk-closed signs until built.
- Recordings: Colorado once after S7 merges (calls 1 and 2 together), the rest after S9; the owner runs them with `TCP_LIVE=1`.

Legend: **[B]** batchable. **[STOP]** owner review. **A-n** assumption about S5 to S12 shapes, repeated in section 9.

---

## 1. What is there today (verified by reading)

| Item | Finding |
| --- | --- |
| Golden files | v0.1, status "DRAFT - extracted automatically, needs SME check" (now accepted by the owner). Per sheet: `sheet_number`, `of`, `phase_label`, `scale` (text, `1" = 40'`), `work_points` (labels as printed, `P.13`), `approaches_on_main_road.from_sheet_left|from_sheet_right` with `advance_sequence_far_to_near`, `positions_ft [{code, dx_ft, dy_ft}]`, `spacing_ft`, `end_signs`; `side_street_devices`; `all_devices_at_posts`; `device_counts`; `callout_codes`; `arrow_board`; `dimension_labels [{label, dx_ft, dy_ft}]` (text and position, **no meaning attached**); `job_notes` |
| Golden frame | Sheet axes, x right, y down, origin at the mean centre of the work-point labels; not georeferenced; error about 5 to 15 ft; approach split automatic (main road = within 60 ft across) |
| Not captured | Taper, buffer and channelizer shapes, work-vehicle position, the meaning of each dimension label |
| Draft codes not in the pack | W20-8 (police sign; the pack has W20-7), W21-5 and W5-1 (note-only, no device record), R8-3, R2-11, RI-27.1.1, R9-9, R9-11L/R, R9-10L, R9-3BR, R3-7R, W9-2L, M4-9 series, M4-A8, G20-2 on side streets |
| Evaluation code | `evaluation/comparison_scoring.py` scores runs against human **site-fact labels** (lanes, divided, widths). It is a different comparison and stays as is |
| S8 plan | Proposes `tests/support/golden_compare_lite.py` (informational) and a reviewed `tests/golden/known_differences.json` (S8 commit 12, a STOP). S13 replaces the first and takes over the second |
| S7 plan | Only Colorado can route automatically with the S4 pack: TA-6 is UNDETERMINED (low-speed cutoff and "minor road" unsourced) and Granite's TA-33 is UNDETERMINED (undivided reading unsourced). For those two the correct router result is the TA as the single candidate plus an SME question (S7 acceptance 1) |
| Recordings | None of the three real KMLs is recorded yet. S6 plan Q18 and the owner: Colorado after S7, the rest after S9 |
| LF | S2 decision 2: "No LF normalization now; revisit in S13". Output files keep the OS line ending, so hashes of the same run differ between Windows and Linux |
| TA-1 | No reference draft (plan open question 9); the plan default is "compared with Figure 6P-1 only" |

## 2. Scope and acceptance criteria

### In scope

1. **A comparator over the golden JSON**: exact checks (TA, sheet count, work points per sheet, scale, advance-sign order per approach, sign code set); tolerance checks (position within 15 ft and spacing within 10 ft, using the labelled value where the draft is schematic); side of road must match.
2. **Two scores per job**, core and full, driven by a versioned **scope file** that says which draft items the tool builds today.
3. **Every difference gets a category** from the spec's list (RULE_GAP, CLIENT_PRACTICE, FIELD_JUDGMENT, SCHEMATIC_DRAFT, EXTRACTION_ERROR, POST_DRAFT_VARIANT) plus the categories B-3 adds. An unexplained difference fails the gate.
4. **Replayed end-to-end comparison** of the three jobs on recorded fixtures in CI.
5. **The live full-pipeline test** on the three KMLs behind `TCP_LIVE=1`, run by the owner only.
6. **The "must not get worse" gate** from S13 on: a committed baseline of both scores.
7. **Golden v0.2 path**: when SME corrections arrive, a correction overlay builds v0.2; v0.1 stays.

### Out of scope

The police switch (future scope; Colorado is compared without it), any change to rules or layout to "fix" a score, TA-1 golden (A-2), pixel comparison of PDFs (ADR-037).

### Acceptance criteria

| # | Criterion | Reading |
| --- | --- | --- |
| 1 | The report runs on replayed fixtures in CI and live on demand | Replay test in the normal suite (slow tier); live test skipped unless `TCP_LIVE=1` |
| 2 | Every difference has a category | No item in the report has `category = null`; `UNEXPLAINED` is a category that fails the gate |
| 3 | No exact-rule failure is left unexplained | Every failed exact check has a category other than `UNEXPLAINED` |
| 4 | Two scores per job, core and full, with the scope version in the report | Owner constraint |
| 5 | Neither score gets worse against the committed baseline at the same scope version | Plan section 13 gate |

## 3. Modules touched

New:

| Module | Purpose |
| --- | --- |
| `src/tcp_planner/evaluation/golden.py` | Golden loader and normaliser: schema check of v0.1, label normalisation for matching only (`P13` vs `P.13`), scale text to a number, approach model |
| `src/tcp_planner/evaluation/golden_scope.py` | Loads `tests/golden/scope.json`; says for each draft item whether it is CORE, ADD_ON_NOT_BUILT, ADD_ON_BUILT or OUT_OF_SCOPE |
| `src/tcp_planner/evaluation/golden_match.py` | Pairs our sheets with golden sheets, our approaches with `from_sheet_left|right`, our signs with golden signs |
| `src/tcp_planner/evaluation/golden_checks.py` | Exact, tolerance and side checks |
| `src/tcp_planner/evaluation/golden_explain.py` | Assigns a category to each difference from the known-differences file, the scope file and the rules in section 5.3 |
| `src/tcp_planner/evaluation/golden_report.py` | Scores and the report (JSON artifact plus Markdown) |
| `src/tcp_planner/evaluation/golden_cli.py` | `python -m tcp_planner.evaluation.golden_cli --project <id>` |
| `tests/golden/scope.json` | Scope file, versioned (**[STOP]**) |
| `tests/golden/known_differences.json` | Taken over from S8, extended with the owner's list (**[STOP]**) |
| `tests/golden/labelled_spacing_v0_1.json` | Only if B-5 picks the curated option |
| `tests/golden/baseline_scores.json` | The gate's baseline (**[STOP]**) |
| `tests/integration/golden/test_golden_replay.py` | Replay end-to-end on the three jobs |
| `tests/live/test_full_pipeline_live.py` | Live test, `TCP_LIVE=1` only; calls `use_os_trust_store()` first |
| `tests/unit/golden/` | Synthetic-diff unit tests |

Changed: `tests/golden/build.py` (v0.2 overlay path, B-9), `tests/support/golden_compare_lite.py` (from S8; replaced, kept until S15), `tests/support/record.py` (only if the recording needs a project-level mode the S6 plan does not already add), `docs/reports/`.

Not touched: `evaluation/comparison_scoring.py`, `ground_truth_labels.py`, the golden v0.1 files (read only).

## 4. Data shapes

```
Scope (tests/golden/scope.json)
{ schema_version, scope_version, approved_by, approved_at,
  items [ { item_id, module "ADVANCE_SIGNS"|"END_SIGNS"|"TAPER"|"BUFFER"|"ARROW_BOARD"|"NO_PARKING"|"RI_DOUBLE_FINES"|"DETOUR"|
                    "SIDEWALK"|"SIDE_STREET"|"POLICE"|"NOTE_ONLY_SIGNS"|"LANE_WIDTH_11FT"|...,
            codes [ "R8-3", ... ] | null, status CORE|ADD_ON_NOT_BUILT|ADD_ON_BUILT|OUT_OF_SCOPE,
            since_scope_version, reason } ] }

KnownDifference
{ id, job, golden_sheet, item_ref (code, approach, check), category, reason, decision_ref ("owner 2026-10-30", D-xx, pack rule id),
  expires_when "ADD_ON_BUILT:<module>"|"GOLDEN_V0_2"|"NEVER" }

ComparisonItem
{ item_id, job, golden_sheet, our_sheet_id, approach "LEFT"|"RIGHT"|null, check EXACT|TOLERANCE|SIDE,
  field "ta"|"sheet_count"|"work_points"|"scale"|"advance_order"|"code_set"|"position"|"spacing"|"side",
  expected, actual, tolerance_ft|null, result MATCH|MISS|EXTRA|WITHIN_TOL|OUT_OF_TOL|NOT_COMPARED,
  scope CORE|FULL_ONLY, category|null, explanation, evidence { golden_path, our_object_id, rule_id, trace_ref } }

ComparisonReport (artifact, schema_version "1")
{ report_id, created_at, mode REPLAY|LIVE, golden_version, scope_version, known_differences_hash,
  pipeline { pack_ref, catalog_hash, template_hash, code_commit }, inputs { project_id, run_ids, sheet_set_ref, fixture_fingerprints },
  jobs [ { job, compared_scope "WHOLE"|"P32_PHASE_I", scores { core {matched, total, ratio}, full {matched, total, ratio} },
           counts_by_category {}, unexplained, items [ComparisonItem] } ],
  gate { baseline_ref, baseline_scope_version, verdict PASS|FAIL, reasons [] } }
```

Scores: an item counts once; `matched` counts MATCH and WITHIN_TOL. A core item is any item whose module is CORE or ADD_ON_BUILT. The full score counts every golden item, so an ADD_ON_NOT_BUILT code is a MISS there and is not counted in core. Weighting is B-4.

## 5. How the comparison works

### 5.1 Matching

1. **Sheets**: pair by normalised work-point labels (comparison only; D-72 allows labels for display, and nothing is decided from them). Granite: only the golden Phase I and our sheet holding P32.
2. **Approaches**: the golden splits by sheet left and right. If S12 rotates the road left to right (S12 B-7), our approaches map directly. Otherwise, pair our two approaches with the golden two by the lowest total cost over sequence and position, and record the pairing (B-6).
3. **Signs**: per approach, pair by code in sequence order (far to near); unpaired golden signs are MISS, unpaired ours are EXTRA.

### 5.2 Checks

| Check | Rule | Source of "expected" |
| --- | --- | --- |
| TA | Exact | `_meta.expected_ta` (an expectation, never an engine input) |
| Sheet count, labels, work points, scale | Exact | Golden sheets (Granite: Phase I only) |
| Advance-sign order per approach | Exact | `advance_sequence_far_to_near` |
| Sign code set | Exact | `callout_codes` and `device_counts` keys, split by scope |
| Position along the road | 15 ft | `positions_ft[].dx_ft` against our distance from the same work point; skipped where the draft is schematic (5.3) |
| Spacing | 10 ft | Labelled value when B-5 links a label to the gap, else `spacing_ft` |
| Side of road | Must match | Sign of `dy_ft` against our side after the approach pairing |

Where our zone has more than one work point (Granite P32 with P31), positions are measured from the golden's work point, P32, not from the zone's end (B-7).

### 5.3 Category rules (deterministic, in this order)

1. The item matches an entry in `known_differences.json`: that entry's category.
2. The code belongs to a module with status ADD_ON_NOT_BUILT: `NOT_BUILT` (B-3).
3. Position out of tolerance but the labelled spacing matches: `SCHEMATIC_DRAFT`.
4. The golden item is outside the extraction's stated limits (near an intersection on Granite I, II, III, V; approach split doubtful): `EXTRACTION_ERROR` only if a known-differences entry says so; never assigned automatically.
5. Otherwise `UNEXPLAINED`, which fails the gate until the owner or SME adds an entry (FIELD_JUDGMENT, RULE_GAP, CLIENT_PRACTICE or EXTRACTION_ERROR) in a reviewed commit.

The owner's list becomes these starting entries (each `CLIENT_PRACTICE` or `NOT_BUILT`, B-3):

| Difference | Job | Category | Expires when |
| --- | --- | --- | --- |
| Buffer label 100 ft vs Table 6B-2 (155 ft at 25 mph) or no buffer (S8 B-3) | Colorado | CLIENT_PRACTICE | Never (MUTCD only) |
| Note 11, 11 ft lane width vs 10 ft (pack) | All | CLIENT_PRACTICE | Never |
| R8-3 TEMPORARY NO PARKING | Colorado, E Second St | NOT_BUILT | No-parking module built |
| R2-11, RI-27.1.1 double fines | Granite | NOT_BUILT | RI module built from a state source |
| M4-9 series, M4-A8 detours | Granite (Phase V; outside P32) | NOT_BUILT | Detour module built |
| R9-9, R9-10L, R9-11L/R, R9-3BR sidewalk closed | E Second St II, Granite | NOT_BUILT | Pedestrian module (needs Sect. 6G.10) |
| W20-8 POLICE OFFICER AHEAD vs W20-7 | Colorado | POST_DRAFT_VARIANT | Police variant built (future scope) |
| W21-5, W5-1 (note-only signs) | E Second St | B-8 | |
| G20-2 and side-street W20-1 | All | B-8 | |

## 6. Commit sequence

Gate per commit: fast tier plus `tests/unit/golden/` and the impacted suites; full suite once at the end.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED` | [B] with 1 | Housekeeping |
| 1 | `golden.py`: loader, schema check of v0.1, label and scale normalisation; tests | [B] with 2 | Plumbing |
| 2 | `scope.json` and `known_differences.json` (owner's list, S8's entries), `golden_scope.py` | **[STOP]** | The scope defines the core score; each known difference is an accepted mismatch |
| 3 | `golden_match.py` and `golden_checks.py`; synthetic-diff unit tests | **[STOP]** | The matching rules decide every score (B-5, B-6, B-7) |
| 4 | `golden_explain.py`, `golden_report.py`, `golden_cli.py`; Markdown and JSON report | [B] | |
| 5 | Replay end-to-end on Colorado (recorded after S7) | **[STOP]** | First real numbers; B-2 decides what "drafted" means |
| 6 | Replay end-to-end on E Second St and Granite P32 (recorded after S9) | **[STOP]** | Needs the post-S9 recording and B-2 |
| 7 | `baseline_scores.json` and the gate test | **[STOP]** | Owner approves the baseline |
| 8 | Live test `tests/live/test_full_pipeline_live.py`, budget guard, run notes; the owner runs it | **[STOP]**, live by the owner | Live calls (CLAUDE.md) |
| 9 | Golden v0.2 overlay path in `build.py` (only when SME corrections exist) | [B] | |
| 10 | `docs/reports/S13_golden_report.md`; full suite | [B] | |

If the post-S9 recording is not ready, commits 0 to 5 and 7 (Colorado only) can merge, and 6 follows as a small slice.

## 7. Tests

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | **Synthetic diffs**: one per check (wrong TA, missing sheet, extra sheet, wrong scale, swapped order, missing code, extra code, position 14 ft and 16 ft off, spacing 9 ft and 11 ft off, wrong side) give the right result | Spec "comparator unit tests on synthetic diffs" |
| T-2 | **Labelled value wins** where the draft is schematic (E Second St 40 ft drawn, 100 ft labelled) | |
| T-3 | **Categories**: every item has one; an unknown difference is `UNEXPLAINED` and fails the gate; an entry in the known-differences file removes it | Acceptance 2, 3 |
| T-4 | **Two scores**: an ADD_ON_NOT_BUILT code lowers full and not core; switching its status to ADD_ON_BUILT moves it into core | Owner constraint |
| T-5 | **Gate**: a lower score at the same scope version fails; a scope-version change asks for a new approved baseline | Plan section 13 |
| T-6 | **Replay end-to-end** on the three jobs: same report twice (deterministic), zero live calls, fingerprints equal to the recording | Spec "replayed end-to-end" |
| T-7 | **Golden is never an engine input**: a test fails if any `src/` module outside `evaluation/` reads `tests/golden/` | |
| T-8 | **Live test** is skipped without `TCP_LIVE=1`; with it, it calls `use_os_trust_store()` before the first request and stops at the per-zone call budget | CLAUDE.md |
| T-9 | **Cross-OS stability**: the report compares parsed values, so the same run gives the same report on Windows and Linux (B-10) | |

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S12 sheet set | Sheets, labels, scale, work points | Planned (A-1) |
| S8 layout objects and traces | Signs, positions, spacing, side | Planned (A-2) |
| S7 routing decision | TA, questions | Planned (A-3) |
| S9 zones | E Second St and Granite zone sets | Not planned yet |
| S11 answer mechanism | B-2 option (b) | Not planned yet |
| S5 alias table (`printed_as`) | W20-8 and M4-A8 matching | Planned (S5 Q9) |
| Recordings by the owner | Replay end-to-end | Colorado after S7, the rest after S9 |
| A-6 (client) | Full Granite comparison | Requested |

## 9. What could go stale if S6 to S8 change (assumptions)

| Assumption | If it changes |
| --- | --- |
| A-1: S12 writes a `SheetSet` with `point_labels`, `scale_ft_per_in`, `label`, `rotation_deg` per sheet | `golden_match.py` sheet pairing and approach mapping |
| A-2: S8 objects carry `device_id`, `approach`, `station_ft`, `side`, `stack.sequence` and a trace | Every sign check |
| A-3: S7 writes `routing_decision.json` with `outcome`, `ta.value` and questions | The TA check and B-2 |
| A-4: S6's recorded fixtures are keyed by request fingerprint and replay with zero calls | Replay test; any request type added after the recordings (S12 B-3, B-14) needs a re-record |
| A-5: S8 B-3 and B-4 (buffer, taper choice) | Positions of every advance sign: Colorado's nearest sign is about 300 ft from P.13 in the draft; S8's options give 150 to 355 ft (S8 plan 4.10) |
| A-6: S8 B-12 keeps side roads as requirements only | Side-street signs stay NOT_BUILT |
| A-7: S5 maps `W20-8` and `M4-A8` through `printed_as` | Code-set checks for Colorado and Granite |

## 10. Where the plan, the spec and the repo differ

1. The spec asks to compare Colorado **after** applying the police switch (POST_DRAFT_VARIANT, D-68); the owner now makes the police variant future scope. Colorado is compared without the switch and W20-8 is a known difference.
2. The spec says "Golden v0.2 after your SME's corrections"; the owner accepts v0.1. v0.2 becomes optional (B-9).
3. The spec's category list has no category for "not built yet" or "different job"; the owner's two scores need the first (B-3).
4. Plan section 14 says a correct discrepancy report is a pass whether or not a plan is produced; the spec's tolerance checks need a plan. With the S4 pack, E Second St and Granite produce no automatic TA (B-2).
5. Plan open question 10 assumed the Granite drawing is "used for sheet rules only"; the owner now compares Granite at P32, Phase I.
6. S2 deferred the LF decision to S13 (B-10).

## 11. OPEN QUESTIONS

### Part A: client inputs and SME questions

**A-1. SME corrections to golden v0.1.** Plan open question 8; the owner accepts v0.1 with tolerances.
- Options: (a) none now; (b) the SME checks the items near intersections (Granite I, II, III, V) and the approach split.
- Effects: (b) gives v0.2 and may turn some `UNEXPLAINED` items into matches.
- Suggestion: (a) now; (b) when the SME reviews the first report.
- Blocks: no.

**A-2. A TA-1 reference draft** (plan open question 9).
- Options: (a) none: TA-1 is not compared; S8's per-TA tests cover it; (b) the client supplies one.
- Suggestion: (a).
- Blocks: no.

**A-3. Classification of differences the rules cannot explain** (FIELD_JUDGMENT versus RULE_GAP, for example Granite Phase IV's 90 ft dimensions).
- Options: the SME classifies each `UNEXPLAINED` item in the first report.
- Blocks: the gate (commit 7) until the first report is triaged.

**A-4. Client inputs that decide whether E Second St and Granite draft at all**: the low-speed cutoff and "minor road" (TA-6), and the 6N.11 undivided four-lane reading (TA-33). S7 plan A-1, A-2, A-4.
- Effects: without them B-2 decides what is compared.
- Blocks: commit 6 in practice.

**A-5. Labelled spacing on E Second St and Granite.** The golden keeps dimension labels as text without saying which gap each measures.
- Options: the SME marks, per approach, which label belongs to which gap (a short table), or B-5 (a) applies.
- Blocks: commit 3 if B-5 (b) is chosen.

**A-6. The Granite KML for WPI 3178233** (requested). With it, Granite is compared whole and needs its own recording.
- Blocks: no.

### Part B: owner decisions

**B-1. Where an item counts: the scope file.**
- Options: (a) a versioned `tests/golden/scope.json`, approved per version, as section 4; (b) scope inferred from the pack (any code with a `device` record is core); (c) scope per known-differences entry only.
- Effects: (b) puts W21-5 and W5-1 out of core by accident of the pack, and a new device record would silently change the score. (a) makes every move into core an explicit, dated decision.
- Suggestion: (a).
- Blocks: commit 2.

**B-2. E Second St and Granite while their TAs are UNDETERMINED.**
- Options: (a) compare what exists: TA as "candidate plus SME question" counts as a TA match when the single candidate equals the golden TA; layout items are `NOT_COMPARED` with reason "no draft: SME question open"; (b) inject recorded SME answers (S7 B-1 determinations, S11 answer path) as labelled test inputs, then draft and compare fully; (c) a test-only pack variant (S7 B-9).
- Effects: (a) gives low core scores for two jobs until the client answers A-4. (b) compares full layouts, but the answers are test inputs, not client facts, and must never reach a real plan. (c) tests a pack that is not the real one.
- Suggestion: (a) for the gate, plus (b) as a separately reported "what-if" section that is not part of the gate.
- Blocks: commit 6.

**B-3. Categories beyond the spec's six.**
- Options: add `NOT_BUILT` (add-on not yet built), `INPUT_MISMATCH` (Granite KML is a different job), `UNEXPLAINED` (fails the gate); or fold them into CLIENT_PRACTICE and EXTRACTION_ERROR.
- Suggestion: add all three.
- Blocks: commit 2.

**B-4. Score weighting.**
- Options: (a) every item counts 1; (b) exact checks weigh more than tolerance checks; (c) report per check family with no single number.
- Suggestion: (a) for the headline, with (c) shown beside it.
- Blocks: commit 4.

**B-5. Labelled spacing association.**
- Options: (a) heuristic: the dimension label nearest the midpoint between two consecutive signs of an approach, within a set distance; (b) a curated file filled from A-5; (c) labels ignored, drawn spacing only.
- Effects: (c) fails E Second St by design (drawn 40 ft, labelled 100 ft). (a) can mis-assign near intersections.
- Suggestion: (a) with every association written into the report, and (b) overriding where present.
- Blocks: commit 3.

**B-6. Approach pairing.**
- Options: (a) direct when S12 rotates the road left to right; (b) lowest-cost assignment over the two approaches; (c) both, (a) when available.
- Suggestion: (c), the pairing recorded per job.
- Blocks: commit 3.

**B-7. Position anchor for a zone with several points.**
- Options: (a) measure from the golden's work point (P32), so P31 in our zone does not shift the numbers; (b) from the zone's near end; (c) skip positions when the zone sets differ, keep order, codes and spacing.
- Suggestion: (a), and (c) for Granite until A-6.
- Blocks: commit 3.

**B-8. Optional and note-only signs in the core score**: G20-2, side-street W20-1, W21-5, W5-1, W16-2P.
- Options: (a) ADD_ON_NOT_BUILT until S8's optional-device policy places them; (b) CORE, so their absence counts against core; (c) OUT_OF_SCOPE.
- Effects: S8's suggestions omit G20-2 (no sourced distance) and leave W21-5 and W5-1 as note actions.
- Suggestion: (a), so core measures what the pack sources.
- Blocks: commit 2.

**B-9. Golden v0.2.**
- Options: (a) an overlay file of corrections applied by `build.py`, v0.1 kept unchanged; (b) hand-edit the v0.1 files; (c) no v0.2 in the MVP.
- Suggestion: (a), only when A-1 brings corrections.
- Blocks: no.

**B-10. Line endings (S2 deferred decision).**
- Options: (a) leave output files as they are; the comparator and its tests compare parsed values, never bytes; (b) write every pipeline JSON with LF (all stored expected outputs change, D-83); (c) normalise only the comparison report.
- Suggestion: (a) plus (c).
- Blocks: no.

**B-11. Live test pass rule.**
- Options: (a) pass when the report is produced and every difference has a category (plan section 14); (b) pass also requires the scores not to fall below the replay baseline.
- Effects: live imagery and model answers vary; (b) may fail on noise.
- Suggestion: (a); the live report is saved under `var/` and summarised in a dated report the owner commits if wanted.
- Blocks: commit 8.

**B-12. Gate when an add-on moves into core.**
- Options: (a) a scope-version change requires a newly approved baseline in the same commit; (b) the gate compares only items present in both scope versions.
- Suggestion: (a).
- Blocks: commit 7.

**B-13. Example KMLs** (`ta-6_example.kml`, `ta-10_example.kml`, `ta-33_example.kml`). No drafts exist for them.
- Options: (a) not compared; (b) recorded and run as smoke tests (TA and "draft produced" only).
- Suggestion: (a) in S13; (b) if the owner adds them to a recording.
- Blocks: no.

**B-14. Where the report lives.**
- Options: (a) an artifact in `ArtifactStore` per run of the comparator, plus a Markdown copy under `var/`; (b) also committed under `docs/reports/` for the baseline run.
- Suggestion: (b) for the baseline only.
- Blocks: no.

### Summary table

| # | Question | Group | Blocks S13? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | SME corrections to v0.1 | SME question | No | None now; after the first report |
| A-2 | TA-1 reference draft | Client input | No | Not compared |
| A-3 | Classifying unexplained differences | SME question | Gate, until triaged | SME classifies the first report |
| A-4 | TA-6 and TA-33 unsourced conditions | Client input | Commit 6 in practice | See B-2 |
| A-5 | Which label measures which gap | SME question | Commit 3 if B-5 (b) | Short table per approach |
| A-6 | Granite KML WPI 3178233 | Client input | No | Requested |
| B-1 | Scope file | Decision | Commit 2 | Versioned `scope.json` |
| B-2 | Jobs with UNDETERMINED TA | Decision | Commit 6 | Compare what exists; what-if section outside the gate |
| B-3 | Extra categories | Decision | Commit 2 | NOT_BUILT, INPUT_MISMATCH, UNEXPLAINED |
| B-4 | Score weighting | Decision | Commit 4 | Equal weights plus per-family view |
| B-5 | Labelled spacing association | Decision | Commit 3 | Heuristic, curated overrides |
| B-6 | Approach pairing | Decision | Commit 3 | Direct when rotated, else lowest cost |
| B-7 | Position anchor | Decision | Commit 3 | Golden work point; Granite positions skipped |
| B-8 | Optional and note-only signs | Decision | Commit 2 | ADD_ON_NOT_BUILT |
| B-9 | Golden v0.2 | Decision | No | Overlay, only with corrections |
| B-10 | Line endings | Decision | No | Compare parsed values |
| B-11 | Live test pass rule | Decision | Commit 8 | Report produced and fully categorised |
| B-12 | Gate on scope change | Decision | Commit 7 | New approved baseline |
| B-13 | Example KMLs | Decision | No | Not compared |
| B-14 | Report location | Decision | No | Artifact; baseline also in docs |
