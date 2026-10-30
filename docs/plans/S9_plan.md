Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md; where they differ from this plan, the register wins.

# S9 plan: grouping engine, zone split, duplicate merge

Planning only. Branch when built: `tcp-mvp/s09-grouping`, off `tcp-mvp/s08-layout`. Written on `tmp/plan-base3` (S1 to S4 merged). Nothing here is approved until the owner says so (CLAUDE.md, "How to work", rule 2). Module and file names are proposals.

Read for this plan: CLAUDE.md; slice specs S3, S8, S9, S11, S12, S14; plan sections 3, 4, 4A, 9, 12, 14, 15 (D-19, D-26, D-45, D-49, D-65, D-82), ADR-002, -010, -015, -026, -035, -038; `S2_storage_report.md`, `S3_orchestrator_report.md`, `S4_rule_pack_report.md`, `S4_rule_pack_review.md`; `S0_repo_report.md` items 5, 9, 10, 28; `docs/plans/S5_plan.md` to `S8_plan.md` (copies, may not be final); code: `orchestration/projects.py`, `project_runner.py`, `intake/kml_reader.py`, `intake/work_location.py`, `intake/lineage.py`, `web_api/project_routes.py`, `config/pipeline_config.json`.

Owner constraints applied here: rules come from the MUTCD Chapter 6 (December 2023) only, and the three drafts are comparison material; the grouping start values (150 ft merge gap, 3 points per zone) and the 18-case table are **proposals** that S9 must present with options and their effect on Granite, E Second St and Colorado; the test gate is the fast tier per commit plus impacted suites, and the full suite once per slice.

Legend: **[B]** can be batched with the next commit. **[STOP]** stop for owner review before the next commit. **A-n** is an assumption about a shape from S3 or S6 to S8 that I could not verify; each is listed again in section 9.

---

## 1. Scope and acceptance criteria

### In scope

1. **Pass 1 grouping** before any paid call: order the points along their road, join consecutive points while the gap is within `merge_max_gap_ft`, then split any group that has too many points or is too long. It uses geometry and the SME's inputs only.
2. **Pass 2 grouping** after routing: it reads each zone's TA (S7) and exact layout envelope (S8) and can only *propose* a regroup. A proposal is a `Question` for the S11 form. Nothing is applied automatically.
3. **Automatic split over 150 m** (D-19): cut at the largest gaps until every piece is within the engine limit, and flag each piece `ZONE_SPLIT_AUTOMATIC`.
4. **Duplicate merge** (case 13): S1 already marks a point within `input.duplicate_distance_m` (1.0 m) of another as `DUPLICATE_OF:<id>` and keeps it. S9 attaches the duplicate to the kept point's zone as `merged_location_ids`, so both records and both labels stay visible. It also raises a warning.
5. **Cases 1 to 18** from plan Section 4A, each with a test, plus the proposed **case 19** (see 4.2). **Every case is presented as a proposal** at the first stop.
6. **Per-TA grouping settings** (`merge_max_gap_ft`, `max_points_per_zone`, `max_zone_path_m`) with a status of PROPOSED or CONFIRMED. While they are PROPOSED, a multi-zone project carries `GROUPING_RULE_REVIEW_REQUIRED` and is never SUPPORTED_AUTO.
7. **SME grouping wins** (case 18). The plan says this means grouping in the UI before Run, but S3 has no such control. Question 12 covers it.
8. **Cross-zone overlap finding** (ADR-010). This is a read-only check between neighbouring zones' envelopes. It never merges, and it feeds sheet packing (S12) and the seam overlap D-19 expects. No slice names this check. Placing it in S9 is my reading (question 14).
9. **Replacing the S3 stub** (`ONE_PER_LOCATION` in `projects.build_zones`), with the zone record carrying `grouping{method, case_ids, rule_version, settings_hash, evidence}`.

### Out of scope

- Sheet packing, scale steps and phase titles (S12). S9 only orders the zones and writes the overlap finding.
- Lines and polygons (S14). Case 14 and the line half of case 15 get the data shape and a test that they stay `NOT_SUPPORTED_UNTIL_S14`. The split function is written so S14 can call it for lines over 150 m.
- Applying a pass 2 proposal, review-time regroup, merge and split, and resume (S11). S9 provides the deterministic functions S11 will call.
- Any rule-pack change. Grouping settings are system settings, not regulation (ADR-015), and never live in the pack.

### Acceptance criteria

The first five rows are the slice spec. Rows 6 to 10 are readings this plan adds. Each one is testable.

| # | Criterion | How it is checked |
| --- | --- | --- |
| 1 | Granite KML with `max_points_per_zone` = 3 gives two zones, P32 to P31 and P30 to P28, split at the largest gap (39.2 m) | Integration test on the real KML (geometry only, no external call). **Holds only for a merge gap from 120 ft to 335 ft with a point cap of 3 or 4** (table 4.4) |
| 2 | E Second St gives two zones | Real KML. Holds for any merge gap below 336 ft |
| 3 | Colorado gives one zone | Real KML (case 1) |
| 4 | The result is identical for any placemark order | Property test: every permutation of each real KML (5! = 120 for Granite) and of synthetic sets gives the same zones, the same zone ids and the same bytes of `grouping.json` |
| 5 | Every case 1 to 18 has a test | A parametrized case table. Each row names its case id, and a meta-test fails if a case id has no row |
| 6 | Each zone records the case ids that formed it (prompt seed) | Schema test over `zone.grouping.case_ids` |
| 7 | Pass 1 makes no external call, or only the calls the owner allows in question 7 | The network guard plus a call counter: zero Azure Maps and zero AI calls before the cap check |
| 8 | Pass 2 never changes a zone, only proposes | The zone set before and after pass 2 is byte-identical. Proposals appear as `Question` records |
| 9 | While settings are PROPOSED, a project with more than one zone is never SUPPORTED_AUTO and shows `GROUPING_RULE_REVIEW_REQUIRED`. A one-zone project is not affected | Status tests |
| 10 | A group over `max_zone_path_m` is split at the largest gaps and each piece is flagged `ZONE_SPLIT_AUTOMATIC` | Synthetic 7-point line, 30 m apart (180 m, the plan's example) |

---

## 2. Modules touched

New (under `src/tcp_planner/`). The S0a folder list has no grouping folder, so this is a proposal. The alternative is `orchestration/grouping/`.

| Module | Purpose |
| --- | --- |
| `grouping/models.py` | Pydantic models: `GroupingSettings`, `PointOnRoad`, `ZoneGrouping`, `GroupingResult`, `RegroupProposal`, `OverlapFinding` (section 3) |
| `grouping/settings.py` | Loads `config/grouping.json`. Returns the settings with status and hash. This is the only place grouping numbers are read |
| `grouping/road_index.py` | Snaps each point to a road, orders points along it, measures gaps and path length, and reads side of road, carriageway and intersections between points. Reuses `data_sources/osm_overpass._join_chain` (S0 item 5) if question 7 allows OSM in pass 1. Otherwise it is geometry only |
| `grouping/pass1.py` | Cases 1 to 9, 12, 13, 16, 18 and 19 on geometry and inputs. Largest-gap split (cases 4 and 5) |
| `grouping/split.py` | `split_at_largest_gaps(points, max_points, max_path_m)`. A pure function, also for S14 lines |
| `grouping/pass2.py` | Cases 8, 10, 11 and 17 after routing. Envelope recheck. Proposals only |
| `grouping/overlap.py` | The cross-zone envelope overlap finding (read only) |
| `grouping/cases.py` | The case table as data (id, name, outcome, flag), so tests and reports enumerate it |
| `orchestration/grouping_stage.py` | Calls pass 1 inside `build_zones` and pass 2 after the zone runs. Writes `grouping.<pass>.json` write-once through `ArtifactStore` and project events |
| `spikes/grouping_effects/effects.py` | Dev script, never imported by `src/`. It computes the effect tables in 4.4 from the three real KMLs, for the owner's first review |
| `config/grouping.json` | Per-TA settings with status PROPOSED, `rule_version` and the per-case outcome options chosen by the owner (question 3) |

Changed:

| File | Change |
| --- | --- |
| `orchestration/projects.py` | `build_zones` calls pass 1 instead of one zone per location. `zone_id_for` and `lineage_key` stay derived from the zone geometry hash (question 9). New zone fields and `SCHEMA_VERSION` "2", with a migration of S3 zone records (`grouping.method ONE_PER_LOCATION` is read as a legacy value) |
| `orchestration/project_runner.py` | The cap counts zones after pass 1. Pass 2 runs when all zone runs finish |
| `web_api/project_routes.py` | `GET .../grouping` (both passes, proposals, overlap findings). `POST .../grouping` only if question 12 puts pre-run SME grouping in S9 |
| `storage/migrations.py` | Zone record "1" to "2" |
| `apps/web/src/...` (`ProjectView.tsx`) | Zone list shows the members, case ids and flags. Grouping controls only per question 12 |
| Tests from S3 that assume one zone per point | Rewritten so each test keeps its intent: points spread beyond the merge gap. This is a **[STOP]** diff review (commit 5) |

Not touched: the rule pack, `config/pipeline_config.json` (guarded; grouping settings live in their own file, question 8), the S8 layout code (S9 reads its envelope).

---

## 3. Data shapes

Every record carries `schema_version`. Persisted references are `{uri, sha256, size, media_type}`.

```
GroupingSettings {                                   # config/grouping.json
  schema_version, rule_version, status PROPOSED|CONFIRMED,
  confirmed {by, role, verified false, at}|null,     # filled by S10's approver role (question 11)
  per_ta { "TA-1"|"TA-6"|"TA-10"|"TA-33": {merge_max_gap_ft, max_points_per_zone|null, basis, status} },
  unknown_ta_policy "SMALLEST_OF_PACK_TAS",          # plan 4A step 3.2
  max_zone_path_m_ref "input.max_work_path_m",       # the engine limit, not repeated (question 10)
  not_on_road_distance_m|null, same_point_distance_m_ref "input.duplicate_distance_m",
  case_options { "8": ..., "10": ..., "16": ..., "19": ... },   # owner's choices (question 3)
  settings_hash }

PointOnRoad { location_id, road_ref {source OSM|GEOMETRY_ONLY|SME, way_ids[], name_hash}, station_m,
  lateral_offset_m, side LEFT|RIGHT|ON_CENTERLINE|UNKNOWN, carriageway_id|null, snap_distance_m, confidence_class }

ZoneGrouping {                                       # inside each zone record (S3 shape + grouping)
  method AUTO_RULE|USER|SME|ONE_PER_LOCATION(legacy), case_ids [int], rule_version, settings_hash,
  ordered_location_ids [], merged_location_ids [ {kept, duplicate} ],
  evidence { road_ref, stations_m [], gaps_ft [], path_m, split_at [ {between [id,id], gap_ft, reason MAX_POINTS|MAX_PATH} ],
             assumed_ta {value, source UI_HYPOTHESIS|SMALLEST_OF_PACK_TAS}, settings_used {...} },
  flags [ GROUPING_RULE_REVIEW_REQUIRED, ZONE_SPLIT_AUTOMATIC, DUPLICATE_MERGED, NOT_ON_ROAD, ... ] }

GroupingResult { schema_version, project_id, pass 1|2, inputs_hash, settings_hash, zones [zone_id + ZoneGrouping],
  proposals [RegroupProposal], findings [OverlapFinding], questions [Question], trace {actor "ENGINE:grouping@<v>", inputs, calculation} }

RegroupProposal { proposal_id, case_id, kind SPLIT|MERGE|MOVE_POINT|SAME_TA_FOR_ALL, zone_ids [], location_ids [],
  reason, evidence {ta per zone, envelopes, gaps}, question_id }
OverlapFinding { finding_id, zone_ids [a, b], overlap_ft, envelope_kind EXACT|CONSERVATIVE_ESTIMATE, consequence "SEPARATE_SHEETS" }
Question  (shared contract) { question_id, kind GROUPING_PROPOSAL|ZONE_SPLIT_CONFIRM|SAME_TA_FOR_ALL|NOT_ON_ROAD|SIDE_UNKNOWN|WHICH_ROAD,
  reason, options [], default_if_skipped, parent_id?, reveals [] }
```

Identity rules:
- `zone_id` stays `ZONE-` plus the zone geometry hash, as in S3. Membership changes the id (question 9).
- Order of members comes from `station_m`, never placemark order. Ties break on `geometry_hash`.
- `grouping.json` bytes depend only on the usable geometry, the per-location inputs, the settings and the S8 envelope (pass 2). They never depend on names, file order or the file hash.

---

## 4. How grouping is computed

### 4.1 Pass 1 (before any paid call)

1. **Clean up.** Usable WORK points only. Duplicates are attached to their kept point (case 13). A line or polygon is a work location that stays `NOT_SUPPORTED_UNTIL_S14` (case 14).
2. **SME grouping wins.** Points the SME grouped (case 18, method USER) are fixed groups. The rule runs on the rest. If an SME group breaks a never-merge case (6, 7 or 9), a conflict question is raised and the SME group is kept.
3. **Never-merge splits.** Points on different roads (6), with an intersection between them (7), or on opposite carriageways (9) go to different groups. Points with different start fields or Select TA (proposed case 19) do too. Opposite sides of an undivided road (8) are separate unless the assumed TA is TA-10 and the owner picks that option.
4. **Order and join.** Order by station along the road. Join consecutive points while the gap is at most `merge_max_gap_ft` of the assumed TA. The assumed TA is the Select TA if every point in the run has the same one, otherwise the smallest gap of all pack TAs (plan 4A step 3.2).
5. **Cap the size.** While a group has more than `max_points_per_zone` points or a path over `max_zone_path_m`, split it at its largest gap and repeat. Equal gaps break on the lower station. A split for path length adds `ZONE_SPLIT_AUTOMATIC` (case 5, D-19). A split for point count adds the case 4 proposal flag.
6. **Flag.** Each zone records its case ids. Every zone of a multi-zone project gets `GROUPING_RULE_REVIEW_REQUIRED` while the settings are PROPOSED.

The gap is the distance between consecutive work points along the road (station difference). With geometry only (question 7, option (b)) it is the straight-line distance, which is what the plan's worked numbers use.

### 4.2 The case table: proposal with options (decided at STOP 1)

| # | Case | Proposed outcome (plan 4A) | Alternative to decide | Effect on the three jobs |
| --- | --- | --- | --- | --- |
| 1 | One point | One zone | none | Colorado: 1 zone |
| 2 | Same road and side, gaps within the merge gap, count within the cap | One zone, `GROUPING_RULE_REVIEW_REQUIRED` | none (values in 4.4) | Granite: 5 points join at 150 ft |
| 3 | A gap larger than the merge gap | Separate zones. If envelopes overlap, separate sheets | none | E Second St: 2 zones, overlap finding decides sheets |
| 4 | More points than the cap | Split at the largest gaps. Proposal flag | (a) recursive largest gap; (b) fewest equal groups | Granite with cap 3: (a) and (b) both give P32–P31 / P30–P28 |
| 5 | Path over 150 m | Split at the largest gaps, `ZONE_SPLIT_AUTOMATIC` (D-19, decided) | none | Granite 139.5 m: no split for length |
| 6 | Different roads | Never one zone | how a road is identified (question 7) | none of the three |
| 7 | Intersection between two points | Never one zone. Side-street signs per zone | what counts as an intersection: any OSM junction with another named way, or only a public road (`highway` class list in config) | Granite on US-1 may have side streets between poles; unknown until OSM is read |
| 8 | Opposite sides of an undivided road | One zone only for TA-10, else separate. Question if TA unknown | (a) as proposed; (b) always separate in pass 1, pass 2 proposes a merge for TA-10; (c) always ask | Unknown: side needs a road centerline |
| 9 | Opposite carriageways of a divided road | Never one zone | none | none of the three |
| 10 | Neighbouring points need different TAs | Separate zones. A shared sheet only if both fit, REVIEW_REQUIRED | How "need different TAs" is known before routing: only from different Select TA per point (case 19). After routing a zone has one TA, so per-point TA is not observed (A-1) | none |
| 11 | TA unknown for some points | Assume one TA, ask "same TA for all points?" | (a) ask only when the Select TA differs or is AUTO for a multi-point zone; (b) ask for every multi-point zone | Granite (AUTO): one question per multi-point zone with (b) |
| 12 | Point at an intersection, work on the crossing road | Its own zone on the crossing road | which road the work is on cannot be read from a point. Proposal: `WHICH_ROAD` question when a point is within the junction distance | Unknown |
| 13 | Duplicates under 1 m | One work point, both kept, warning | none (S1 already marks them) | none in the three KMLs (S1 found 5, 2 and 1 distinct points) |
| 14 | A line or polygon | One work location. A line over 150 m is case 5 | none, built in S14 | none |
| 15 | A point and a line that overlap | Same zone if case 2 holds | waits for S14 | none |
| 16 | A point off any road | Kept, flagged, `NOT_ON_ROAD` question | the distance that means "off road" has no source (question 5) | Granite poles and the Colorado pole stand at the roadside. Too small a distance flags them. E Second St manholes are in the road |
| 17 | A zone changes TA after routing | Pass 2 proposes a regroup | none | With equal start values for every TA (150 ft, 3), a TA change alters no grouping, so pass 2 proposes nothing |
| 18 | SME grouping in the UI | Wins over all cases. Conflicts flagged | where the SME groups before Run (question 12) | none |
| **19** (new) | Points with different start fields or Select TA | Never one zone: a zone has one set of start fields (S3 `effective_inputs`) | (a) add as a case; (b) fold into case 10 | none in the three KMLs unless the SME types per-point values |

### 4.3 Pass 2 (after routing, proposals only)

For each zone it reads the routed TA from S7, the exact envelope from S8, and the start fields. The steps are:

1. **TA versus assumed TA (case 17).** If the routed TA differs from pass 1's assumed TA, it regroups the affected stretch with the routed TA's settings. If the result differs, it writes a `RegroupProposal` and a question.
2. **Same TA for all points (case 11).** If the routed outcome is not `MATCH_ONE` for a multi-point zone, it writes the `SAME_TA_FOR_ALL` question. A "No" answer reveals one TA choice per point (plan Section 8).
3. **Neighbours that now qualify to merge (plan 4A step 5.2).** These get a MERGE proposal.
4. **Overlap.** Neighbouring zones whose exact envelopes overlap get an `OverlapFinding` with consequence `SEPARATE_SHEETS`. A finding is never a merge. A seam from a D-19 split is expected to overlap, and that is reported too.

Pass 2 is idempotent: same inputs, same proposals, same ids. Answering a proposal is S11.

### 4.4 Effect of the start values and their options on the three jobs

All distances come from the KML coordinates and are straight-line distances.

- **Granite:** gaps P32–P31 32.2 m (106 ft), P31–P30 39.2 m (129 ft), P30–P29 36.4 m (119 ft), P29–P28 31.7 m (104 ft); 139.5 m end to end.
- **E Second St:** 102.5 m (336 ft).
- **Colorado:** one point.
- **Zone cap:** `project.max_zones` = 3.

| `merge_max_gap_ft` | `max_points_per_zone` | Granite | E Second St | Colorado |
| --- | --- | --- | --- | --- |
| 100 | any | 5 zones (every gap over 100 ft). **Over the cap of 3: approval needed** | 2 | 1 |
| 110 | 3 | 3 zones: P32–P31, P30, P29–P28 | 2 | 1 |
| 120 | 3 | 2 zones by gap alone: P32–P31, P30–P28 | 2 | 1 |
| **150 (start)** | **3 (start)** | **2 zones: P32–P31 and P30–P28** (one group of 5, split at 129 ft). Meets acceptance 1 | **2** | **1** |
| 150 | 2 | 3 zones: P32–P31, P30, P29–P28 | 2 | 1 |
| 150 | 4 | 2 zones (same as 3) | 2 | 1 |
| 150 | none (path cap only) | 1 zone, 139.5 m (under 150 m) | 2 | 1 |
| 336 or more | any | as the 150 rows | **1 zone: contradicts the draft (two sheets)** | 1 |
| Table 6B-1 A of the road type (100 ft urban low speed; a pack number reused for a purpose the MUTCD does not give it) | 3 | 5 zones, over the cap | 2 | 1 |

What this shows:
- The Granite acceptance holds for any merge gap from 129 ft to 335 ft with a cap of 3 or 4, and for 120 to 128 ft by gap alone.
- E Second St bounds the merge gap below 336 ft.
- No value is supported by a source. The 3-point cap comes from the Granite **drawing**, WPI 3178233. That is a different job from the Granite KML, WPI 3159540: only P32 is in both (R19).

The exact table is regenerated by `spikes/grouping_effects/effects.py` at STOP 1, so the owner sees computed numbers, not mine.

---

## 5. Commit sequence

Branch `tcp-mvp/s09-grouping` off `tcp-mvp/s08-layout`. Each commit runs the fast tier plus the impacted suites. The full suite runs once, at commit 9.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF` to the S8 tip, empty `APPROVED` | [B] with 1 | Housekeeping (as S3 `9d43f8f`) |
| 1 | `spikes/grouping_effects/effects.py` and `docs/reports/S9_grouping_proposal.md`: the case table (4.2), the settings options with computed effects on the three KMLs (4.4), and the question list below. No `src/` change | **[STOP 1]** | The owner confirms or picks the case outcomes and start values. Nothing after this commit is built on an unconfirmed reading |
| 2 | `grouping/models.py`, `grouping/settings.py`, `config/grouping.json` (status PROPOSED), `grouping/cases.py`, zone record "2" and its migration | [B] with 3 | Plumbing |
| 3 | `grouping/road_index.py`: snapping, order, gaps, sides, carriageways, intersections, per question 7. Synthetic roads, plus the real KMLs geometry-only | **[STOP 2]** | Decides which points can ever share a plan (cases 6, 7, 9). Reads geometry, not images |
| 4 | `grouping/split.py`, `grouping/pass1.py`: every pass 1 case, flags, D-19 split; parametrized case table; order-independence property test | **[STOP 3]** | The core rule. Review the case table tests against STOP 1 |
| 5 | Wire pass 1 into `projects.build_zones` and the cap count; S3 tests rewritten to keep their intent; web zone list shows members and flags | **[STOP 4]** | Changes S3 behaviour and S3 tests (one zone per point). Diff review of every changed test. Offline scenarios are single-point, so stored expected outputs should not change; a test asserts `tests/fixtures/expected/` is unchanged |
| 6 | `grouping/pass2.py`, `grouping/overlap.py`, `orchestration/grouping_stage.py`: proposals and findings as questions; idempotence | **[STOP 5]** | Reads S7 and S8 outputs (A-1 to A-4). Review that nothing is applied |
| 7 | Status: `GROUPING_RULE_REVIEW_REQUIRED` in zone and project roll-up; settings confirmation hook (records who confirmed, "approved (not verified)") | [B] with 8 | Small; depends on question 11 for who may confirm |
| 8 | Pre-run SME grouping (case 18): API and minimal UI, only if question 12 puts it in S9; Vitest; web rebuild | [B] | UI |
| 9 | Replay determinism on the real KMLs (geometry only), full suite once, `docs/reports/S9_grouping_report.md` | [B] | Required finish (CLAUDE.md) |

---

## 6. Tests

All offline. No live call. The network stays blocked.

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | Case table, one parametrized row per case 1 to 19, each asserting zones, case ids, flags and questions | A meta-test fails if a case in `grouping/cases.py` has no row |
| T-2 | Real KMLs: Granite 2 zones (P32–P31, P30–P28), E Second St 2, Colorado 1, with the confirmed settings | Expectations are test values. The golden TA is never an input |
| T-3 | Order independence: all 120 permutations of Granite, both orders of E Second St, shuffled synthetic sets; same zone ids and same `grouping.json` bytes | Acceptance 4 |
| T-4 | Split at the largest gap: ties, recursion, cap of 1, cap equal to the count, a gap exactly at `merge_max_gap_ft` (joins: "within" means at most) | |
| T-5 | D-19: 7 points 30 m apart (180 m) split into pieces of 150 m or less, each `ZONE_SPLIT_AUTOMATIC`; the seam overlap finding appears | Plan's own example |
| T-6 | Duplicates: a point 0.5 m from another joins its zone as `merged_location_ids`; both labels kept; warning; zone geometry hash uses the kept point only (same as S1) | Case 13 |
| T-7 | Never-merge: different roads, intersection between, opposite carriageways, different start fields or Select TA (case 19) | Synthetic OSM fixtures if question 7 allows OSM |
| T-8 | Pass 2 changes nothing: zone set byte-identical before and after; proposals carry questions; rerun gives identical proposal ids | Acceptance 8 |
| T-9 | Pass 2 cases 11 and 17 with fake `RoutingDecision`s; overlap from fake exact envelopes | A-1, A-2 |
| T-10 | Status: settings PROPOSED, a multi-zone project is never SUPPORTED_AUTO and shows the flag; one-zone project unaffected; CONFIRMED clears the flag | Acceptance 9 |
| T-11 | Cap: the cap counts zones after pass 1 (Granite 5 points, 2 zones, under the cap) and still holds before any paid call | S3 acceptance kept |
| T-12 | No grouping number in code: grep `grouping/` for 150, 3, 45.72 and the like; a settings file with other values changes the result | CLAUDE.md rule 3 (thresholds in config) |
| T-13 | Names never decide: renaming every placemark changes no zone | D-72 |
| T-14 | Migration: an S3 zone record ("1", `ONE_PER_LOCATION`) reads as version "2"; no raw path in any new JSON (S2 scan) | |
| T-15 | Re-upload of the same geometry reopens the project with the same zones; settings change bumps `rule_version` and gives new zone versions, old runs untouched | |

---

## 7. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S1 `WorkLocation`, duplicate marking, `parse_all` | Input points | Merged |
| S2 stores | `grouping.json`, events, CAS project updates | Merged |
| S3 project record, `build_zones`, `effective_inputs`, cap, roll-up | Where grouping plugs in | Merged |
| S6 OSM adapter (Overpass or map API, S6 Q12) and road geometry | Snapping in pass 1 if question 7 allows it | Planned. A-3 |
| S7 `RoutingDecision` | Pass 2 cases 11 and 17 | Planned. A-1 |
| S8 `Envelope` (`EXACT` and `CONSERVATIVE_ESTIMATE`) | Pass 2 overlap and merge recheck | Planned. A-2 |
| S10 approver role | Who confirms the grouping settings (question 11) | Planned after S9. Until then a confirmation records a typed name, unverified, as the S3 cap did |
| The fast test tier | The per-commit gate | A-6 |

Feeds: S11 (regroup functions, proposals, questions), S12 (zone order, overlap findings, sheet labels), S14 (the split function for lines).

---

## 8. Client inputs and decisions S9 consumes

- **Client inputs:** the start fields and Select TA per point, which decide case 19. Nothing else. Grouping needs no client number once the owner confirms the settings.
- **SME questions at run time:** `NOT_ON_ROAD`, `SIDE_UNKNOWN`, `WHICH_ROAD`, `SAME_TA_FOR_ALL`, `ZONE_SPLIT_CONFIRM`, `GROUPING_PROPOSAL`. They are rendered by S11.
- **Owner decisions:** questions in section 10, part C.

---

## 9. What could go stale if S6 to S8 change

| Assumption | Shape I rely on | What breaks in S9 if it changes |
| --- | --- | --- |
| A-1 (S7) | `RoutingDecision` per zone with `outcome`, `ta{value, source, status}`, `candidates[]`, written as `routing_decision.<stage>.json` (S7 plan 3.3). Routing is per zone, not per point | Pass 2 cases 11 and 17. If S7 routes per point, case 10 becomes detectable after routing and pass 2 grows |
| A-2 (S8) | `Envelope {upstream_ft{INCREASING, DECREASING}, downstream_ft, lateral_ft, station_range_m, kind EXACT|CONSERVATIVE_ESTIMATE}` in `LayoutResult` (S8 plan 3.3); stations along the zone centerline | `overlap.py` and the pass 2 merge recheck. Station frames must be comparable across zones: if each zone's stations start at its own centerline start, overlap needs a project-level frame (lat/lon of envelope ends) |
| A-3 (S6) | OSM ways with `name`, `ref`, `highway`, `oneway`, `dual_carriageway`, geometry, through one adapter with recorded fixtures; Overpass or the map API per S6 Q12 | `road_index.py` (cases 6, 7, 9, 12, 16). If S6 records real-KML OSM fixtures only after S9 (S6 Q18 suggestion C), S9 tests snapping on synthetic fixtures and the real KMLs geometry-only |
| A-4 (S8) | Add-ons (sidewalk closed, detours) built in S8 as optional per zone and part of the exact envelope when switched on | A detour can lengthen an envelope a lot; overlap findings and S12 sheets change when the SME switches one on (S11 resume must rerun pass 2) |
| A-5 (S3/S6) | Zone engine input `zone_input.json` takes several ordered `locations[]` and S6/S8 build a work path from them (S3 `kml_reader.from_zone` builds one Point and `work_path: []` today) | A multi-point zone cannot run until the adapter builds a path. **If S6 to S8 keep one Point per zone, S9's multi-point zones cannot run at all**; this must be checked at S9 start |
| A-6 (gate) | A fast test tier exists (for example a `slow` marker; S3 proposed it, not done) | If absent, S9 commit 0 defines it (question 16) |
| A-7 (S7) | The `Question` shared contract extended by S7 (`kind`, `default_if_skipped`, `parent_id`, `reveals`) | S9 question kinds; S11 renders them |

Not stale: the case table, the split function, the settings file, and the identity rules.

---

## 10. OPEN QUESTIONS

Three groups: **A. Client inputs** (facts or numbers only the client can supply), **B. SME questions** (engineering readings the SME answers), **C. Owner decisions** (design choices). I have decided none. "Blocks" says what cannot be finished without the answer.

### A. Client inputs

**1. The Granite drawing that matches the KML (WPI 3159540)** (plan open question 10, R19).
- Options: (a) the client sends it; (b) the client confirms the two are neighbouring jobs drawn the same way; (c) neither.
- Effects: the 3-point cap is read from a different job. With (a), the cap and merge gap can be checked against the same poles.
- Suggestion: (a) or (b) before the settings are CONFIRMED.
- Blocks: no. It blocks moving the settings from PROPOSED to CONFIRMED with any basis.

**2. Any client grouping practice in writing** (how many poles or manholes their drafters put on one plan, and why).
- Options: (a) a written rule; (b) none, use the drafts only.
- Effects: (a) gives the settings a source, which a client document can be (they are system settings, not MUTCD rules, ADR-015).
- Suggestion: ask with STOP 1.
- Blocks: no.

### B. SME questions

**3. The 18 cases plus case 19: confirm each outcome or pick an alternative** (table 4.2: cases 4, 7, 8, 10, 11, 12, 19 have alternatives).
- Options per case as in 4.2.
- Effects: per row of 4.2. Cases 8 and 11 change the number of questions; case 19 can split points the rule would join.
- Suggestion: the plan's outcomes, with 4 (a), 7 public roads only, 8 (b), 11 (a), 12 a `WHICH_ROAD` question, 19 (a).
- Blocks: **yes, commit 4** (pass 1 implements the confirmed table).

**4. Start values: `merge_max_gap_ft` and `max_points_per_zone` per TA** (table 4.4).
- Options: (a) 150 ft and 3 for every TA (plan); (b) 120 ft and 3 (Granite splits by gap alone, cap rarely used); (c) 150 ft and no point cap (Granite one zone of 139.5 m); (d) a Table 6B-1 distance (reuses a pack number for a purpose it does not have; Granite 5 zones over the cap).
- Effects: see 4.4. Every option keeps E Second St at 2 and Colorado at 1. Only (a) and (b) meet acceptance 1.
- Suggestion: (a), status PROPOSED, flagged until the SME confirms.
- Blocks: **yes, commit 4 tests**.

**5. `NOT_ON_ROAD` distance** (case 16; no source).
- Options: (a) no automatic flag: every snap distance is shown, the SME flags; (b) a distance in config, PROPOSED, with the SME confirming; (c) a distance relative to the observed road edge (needs S6 widths, so pass 2 only).
- Effects: poles (Granite, Colorado) stand beside the road; manholes (E Second St) are in it. Too small a value flags every pole; too large misses a yard.
- Suggestion: (a) in pass 1, (c) as a pass 2 proposal.
- Blocks: no (case 16 test uses whichever is chosen).

**6. Which TAs "close both sides' traffic in one layout"** (case 8).
- Options: (a) TA-10 only (plan); (b) TA-10 and TA-6 (the figure shows signs on both approaches, but the work is on one shoulder); (c) none, always separate.
- Effects: (b) merges opposite-side manholes on a TA-6 street.
- Suggestion: (a).
- Blocks: commit 4 (case 8 row only).

### C. Owner decisions

**7. Road identity and order in pass 1.** S0 item 5: only a one-road chain exists. Pass 1 runs before the cap check, and S3's acceptance says the cap holds "before any external call".
- Options: (a) one project-level OSM fetch (free, allowed source, recorded fixtures) before the cap check, so cases 6, 7, 9 work in pass 1; the S3 wording becomes "before any paid call"; (b) geometry only in pass 1 (straight-line gaps, order along the principal axis of the points); cases 6, 7, 9 become pass 2 proposals after each zone's own OSM fetch; (c) as (b) plus an SME "same road?" question for every multi-point group.
- Effects: (a) changes an S3 acceptance wording and adds a network call before approval. (b) can run one wrong merged zone across two roads (cost of one zone run) before pass 2 catches it, and fails on curved roads where the principal axis misorders points. (c) adds a question to every multi-point project.
- Suggestion: (a), with the call counted and recorded.
- Blocks: **yes, commit 3**.

**8. Where the grouping settings live.** The slice spec says "in the registry"; ADR-015 says grouping settings are never rules, and the owner's S4 decision keeps the pack MUTCD-only.
- Options: (a) `config/grouping.json` with status and confirmation; (b) a `grouping` section in `config/pipeline_config.json` (guarded, needs an `APPROVED` entry each change); (c) the pack registry (contradicts ADR-015 and MUTCD-only).
- Effects: (a) keeps the pack clean and the guard untouched. (c) changes the pack hash on every tuning.
- Suggestion: (a). This is a contradiction with the slice text; the slice doc wording needs the owner's edit.
- Blocks: **yes, commit 2**.

**9. Zone identity after a regroup.** S3 derives `zone_id` and `lineage_key` from the zone geometry hash, so a different membership is a new zone with a new SME lineage. ADR-009 says regroup creates "new zone versions under a stable zone_id".
- Options: (a) keep geometry-derived ids; a regroup makes new zones and S11's "inherit" (D-10) carries history explicitly; (b) stable ids (for example the lowest-station member's location id) with versions; (c) (a) plus a `derived_from` link on the new zone.
- Effects: (a) contradicts ADR-009's wording but keeps D-82 and S3 intact. (b) changes D-82 and the S3 lineage tests; SME history would follow a zone whose geometry changed.
- Suggestion: (c), and amend ADR-009's wording.
- Blocks: commit 2 (record shape); S11 depends on it.

**10. Single `max_zone_path_m` or per TA.** The slice lists it per TA; the plan calls 150 m the engine limit (`input.max_work_path_m`, D-19).
- Options: (a) one value, the existing `input.max_work_path_m`; (b) per TA in `grouping.json`.
- Effects: (b) creates a second copy of the engine limit that can disagree with it.
- Suggestion: (a).
- Blocks: no.

**11. Who confirms the grouping settings, and how it is recorded.**
- Options: (a) the Approver role (S10), recorded "approved (not verified)"; (b) the SME reviewer; (c) the owner by editing the file (status CONFIRMED in a commit).
- Effects: (a) cannot happen before S10 merges, so S9 ships PROPOSED. (c) needs no role but leaves no in-app audit.
- Suggestion: (c) for the MVP start values, (a) for later changes.
- Blocks: commit 7.

**12. Pre-run SME grouping in the UI (case 18).** The S3 prompt seed mentions it; S3 built none; S11 has review-time regroup.
- Options: (a) S9 adds API and a minimal "group these points" control in the location list; (b) S9 adds the API only, UI in S11; (c) S11 only (case 18 tested at API level in S9).
- Effects: (c) means the SME can only correct grouping after a run has spent calls.
- Suggestion: (a).
- Blocks: commit 8.

**13. Rewriting the S3 tests that assume one zone per point** ("three points give three runs", "five zones never more than three active").
- Options: (a) rewrite their KMLs so points are farther apart than the merge gap (intent kept); (b) a config switch `grouping.mode = ONE_PER_LOCATION` for tests (a second path, D-32 spirit); (c) delete and replace (not allowed: nothing is deleted).
- Suggestion: (a), reviewed at STOP 4.
- Blocks: commit 5.

**14. Is the cross-zone overlap check in S9?** No slice names it; plan step 12 and ADR-010 describe it; D-19 relies on it.
- Options: (a) S9, read only, findings feed S12; (b) S12 with sheet packing; (c) S13.
- Suggestion: (a).
- Blocks: commit 6.

**15. Does the two-source rule apply to road identity?** The owner's rule: safety-critical fields need two agreeing sources or become UNKNOWN. Road identity in pass 1 comes from OSM alone.
- Options: (a) grouping is not safety-critical because every multi-zone grouping is flagged and reviewed; (b) road identity needs imagery agreement in pass 2 and a disagreement becomes a question.
- Suggestion: (a), with (b) as a later improvement.
- Blocks: no.

**16. Fast test tier definition** if none exists at S9 start (A-6).
- Options: (a) a `slow` marker on the assistant and replay suites, fast tier = `-m "not slow"`; (b) a folder list.
- Suggestion: (a), added in commit 0 if missing.
- Blocks: no.

**17. Multi-point zone runs** (A-5). If S6 to S8 still give the engine one Point per zone, S9 zones of several points cannot run.
- Options: (a) S9 adds the work-path adapter (zone points ordered by station into `work_path`); (b) stop S9 until S8 provides it; (c) S9 groups but runs each point's layout inside one zone (not one closure).
- Suggestion: (a) if S8 has not done it; check at S9 start and stop if the repo differs.
- Blocks: commit 5 end to end.

### Summary

| # | Question | Group | Blocks S9? | Suggestion |
| --- | --- | --- | --- | --- |
| 1 | Matching Granite drawing (WPI 3159540) | Client input | No (blocks CONFIRMED) | Ask the client |
| 2 | Client grouping practice in writing | Client input | No | Ask at STOP 1 |
| 3 | Case table outcomes 1 to 19 | SME | **Commit 4** | Plan outcomes; 8 (b), 11 (a), 19 added |
| 4 | Merge gap and point cap per TA | SME | **Commit 4 tests** | 150 ft and 3, PROPOSED |
| 5 | `NOT_ON_ROAD` distance | SME | No | No auto flag in pass 1; pass 2 proposal |
| 6 | TAs that join opposite sides | SME | Case 8 row | TA-10 only |
| 7 | Road identity in pass 1 (OSM before the cap) | Owner | **Commit 3** | One project-level OSM fetch |
| 8 | Where grouping settings live | Owner | **Commit 2** | `config/grouping.json` |
| 9 | Zone identity after a regroup | Owner | Commit 2 | Geometry ids plus `derived_from` |
| 10 | One path limit or per TA | Owner | No | One, the engine limit |
| 11 | Who confirms the settings | Owner | Commit 7 | Owner edit now, Approver later |
| 12 | Pre-run SME grouping UI | Owner | Commit 8 | In S9 |
| 13 | Rewriting S3 one-zone tests | Owner | Commit 5 | Spread the points, review the diff |
| 14 | Cross-zone overlap check in S9 | Owner | Commit 6 | Yes, read only |
| 15 | Two-source rule for road identity | Owner | No | Not safety-critical; reviewed |
| 16 | Fast tier definition | Owner | No | `slow` marker |
| 17 | Multi-point zones can run | Owner | Commit 5 | Adapter in S9 if S8 lacks it |
