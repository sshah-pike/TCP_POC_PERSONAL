Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

## Owner decisions applied (2026-10-30)

- Q1 B: two sessions (session 1 call 1, measurement, crops, OSM, wiring; session 2 data sources). Q2: build beside the old path; cutover in S8.
- Q3 B (prompt tuning approved except removing unit). Q4: call 1 uses gpt-5.6-sol (D-78); the owner runs the same 9-call check on claude-opus-5-5 for comparison before any recording; keep the schema and prompt provider-neutral; record the comparison in docs/reports/S6_model_comparison.md and do not pick a winner. Deployments in account TCP-Foundary-RR (East US): claude-opus-5-5 and gpt-5.6-sol each 5,000 requests and 5,000,000 tokens per minute; a claude-opus-5-5-fast deployment also exists (2,000 and 2,000,000).
- Q5 A, Q6 A, Q7 B (floors in a new config file tagged CALIBRATION_PENDING, not pipeline_config.json), Q9 A (values pending, owner reviews at a stop), Q11 A, Q13 A, Q14 A, Q15 A, Q16 A, Q17 A.
- Q8: single-source rule on lanes per direction, divided, shoulder, one-way; work_location uses confidence at least 0.85 and the SME confirms the work side. work_location emits registry values; code decides IN_LANE versus ON_SHOULDER_OR_ENCROACHING.
- Q10: default work vehicle width 102 in (23 CFR 658.15), flagged DEFAULT_ASSUMED, optional, in the same settings file; work space depth and clearance are UNKNOWN and asked per job.
- Q12: documentation first; discovery spike on MassGIS (first), RIGIS, with OSM first; live calls only with the owner's permission in chat, read-only, limited, three sites named.
- Q18: Colorado is recorded once after S7 merges (calls 1 and 2 together), the rest after S9; Granite is compared at pole P32 only. The owner runs recordings with TCP_LIVE=1.

## Owner decisions applied (2026-10-31)

Register: `docs/decisions/OWNER_DECISIONS_2026-10-31.md` (D-111 to D-156). Where this block differs from older text in this plan, this block is the active text and the older wording is kept in the "Amendments 2026-10-31" notes of sections 2, 3, 4, 5 and 9. Future items are in `docs/FUTURE_SCOPE.md`.

- **Order inside a zone run (D-119).** Call 1 runs first and **blind**: it never sees OSM or any code value. Then the code and OSM checks, then fusion with the two-source rule. Call 2 is S7. Two AI calls per zone at most. S6 session 1 resumes for the permanent design only: no agent loop, no deep mode, no call 2 (D-128, D-122, D-139).
- **Three outcomes (D-111).** FOUND (the source gives a value or the thing is there), NOT_PRESENT (the source was checked and the thing or tag is absent; presence fields only) and UNKNOWN (could not be determined: occluded, too blurry, no tag, malformed, or the source failed; a fixed reason code says why). A source that was not checked is never NOT_PRESENT. Per-field meaning: `docs/references/S6_outcomes.md`.
- **OSM rules (D-111).**
  - `lanes_per_direction`: from `lanes:forward` and `lanes:backward`; else `lanes` divided by 2 only when the total is even and the road is two-way; an odd total or a forward/backward mismatch gives no information.
  - `oneway`: a missing tag counts as "not one-way" for the OSM source at lower confidence, and the AI must also say false. A stated tag counts fully.
  - A missing `lanes` or `shoulder` tag gives no information.
  - `divided_highway` comes from geometry: a parallel, opposite-direction way (config distance and angle, CALIBRATION_PENDING).
  - Source of the even-total and forward/backward wording: S6 plan Q8 (odd total cannot be split) and `docs/reports/S6_stop5_fusion_rules.md` (on branch `tcp-mvp/s06-site-understanding`).
- **Two-source rule (D-92, D-119).** For lanes per direction, divided, shoulder and one-way the AI and OSM must agree. Two AI calls, two crops, or any code check never count as a second source. A single source gives UNKNOWN with the AI value kept as a pre-filled candidate (recommendation in D-156, owner confirmation open).
- **Bearing check and "which road?" (D-127, D-156).** The road direction of the AI marks (code, modulo 180) is compared with the nearest OSM way within 30 degrees (config, CALIBRATION_PENDING). A failure makes every road-specific fact from that call UNKNOWN with reason `wrong_road_suspected` and raises one "which road?" question. Recommendation in D-156 (2), owner confirmation open.
- **Edge rule (D-113).** Work point within 5 m of the nearest road edge, or no road near: `work_location` is UNKNOWN plus one SME question. The distance is in config, tagged CALIBRATION_PENDING. Optional exceptions file: `config/site_exceptions.json` (D-138, D-155).
- **Confidence floors per model profile (D-132).** A default entry plus optional per-profile entries; no profile entry ships until calibrated. Call 1 uses gpt-5.6-sol by default and the claude-opus-5-5 profile stays working (D-131).
- **Enhanced call-1 prompt and code snapping of marks (D-128, D-124 arm C).** Both are permanent. Code snaps each AI mark to the nearest real edge in the image; a mark with no edge nearby is rejected and gives no width. The enhanced prompt text is read by the owner at STOP 6 before any live use.
- **Code checks and consistency checks (D-128).** Code checks: lane-line detection, shadow and tree-cover share, image-to-OSM offset. Consistency checks: lane count against width, work location against edge distance, and the others listed in `docs/reports/S6_stop5_fusion_rules.md`. They only lower confidence or give UNKNOWN. None counts as a second source. Values in config, tagged CALIBRATION_PENDING; every run records the values it used and each change gets a decision-log entry (D-127).
- **Per-stage off switches (D-128).** Every stage (enhanced prompt, snapping, each code check, each consistency check) has a config switch, so the experiment arms of D-124 can be measured.
- **Prompt registry (D-129).** All prompts live in `prompts/`, one file per prompt, each with an id, version and sha256 in its header, loaded with a hash check and pinned by tests, before any prompt is enhanced. History, changelog, comparison runs and rollback are future scope (FS-05).
- **Question model and answer records (D-130).** No question log store now. The `Question` record carries kind, field, zone, project, OSM way id and context; every saved answer record keeps kind, field, zone, project, OSM way and answer time. Repeat analysis is future scope (FS-04).
- **Accuracy and probe scripts (D-114, D-118, D-134, D-136).** `scripts/s06_accuracy_report.py` (truth CSV in; wrong-and-used counted with the AI_ONLY_UNCONFIRMED flag shown beside it; zero wrong-and-used on the four safety fields with its 95% upper bound); a zoom-19 probe for E Second and Colorado (two Azure requests, run by the owner); an OSM recorder that stores Overpass responses as fixtures (public server for development; self-hosting before production, FS-08). Script names other than the accuracy report are proposals. The Overpass User-Agent is descriptive, with no company name and no contact until production (D-115).
- **8-site early check (D-125, D-133, D-140).** Granite, E Second, Colorado, Exeter Ten Rod and four new sites, 2 per TA situation, labelled by the owner. Truth files are in `docs/evaluation/` (`SITE_TRUTH_v0.md`, `site_truth_v0.json`, `site_truth_v0.csv`). It finds failures; it cannot certify an error rate. Tune on dev sites, freeze, score once; never tune on the sites used as proof. The pass bar for the UNKNOWN rate is set after the first scored test (D-135).
- **Moved out of S6.** Session 2 (the state and federal data sources) moves to after the first scored test, chosen by how many SME questions each source removes (FS-06, owner conversation 2026-10-31). No real-KML recordings in S6 (D-98: Colorado after S7 merges, the rest after S9; D-128). The agent loop and deep mode are future scope (FS-01).
- **Stops.** STOP 5 is now the fusion rule table and the list of consistency checks (`docs/reports/S6_stop5_fusion_rules.md`, S6 branch). STOP 6 is the enhanced call-1 prompt text.

Status of the work as of 2026-10-31 (checked with `git log` and `git show` on the branch, not merged into base): the branch `tcp-mvp/s06-site-understanding` (HEAD `8fc89bd`) holds the prompt registry, the three outcomes, the Overpass adapter and OSM rules, the bearing and which-road check, the edge rule, per-profile floors, `config/site_exceptions.json`, the STOP 5 report and the single-source fusion. Not yet built there (from the STOP 5 report): consistency checks 8 to 13, snapping, the enhanced prompt, and the per-stage switches.

# S6 plan: site understanding

Status: PLAN ONLY, not approved. Date: 2026-10-29. Written on `tmp/plan-base` (S2 and S4 merged). No code, config or rule-pack file was changed.
Proposed branch: `tcp-mvp/s06-site-understanding`, off S3's last commit (S6 depends on S3, which is still open). Module and file names are proposals.

Read for this plan: `CLAUDE.md`; slice spec S6 (and S3, S4, S7, S8, S9, S11); plan sections 4B, 4C, 5 and decisions D-27, D-37, D-38, D-53, D-59, D-61 to D-64, D-80, D-82; `docs/reports/S0_repo_report.md`
and `S0_prompt_tuning_proposal.md`; the schema spike report and its prompt (`git show tcp-mvp/s00-schema-spike:...`); `S2_storage_report.md`; `S4_rule_pack_review.md`;
the S4 pack registry; the current `src/tcp_planner/ai`, `site_model`, `imagery`, `data_sources` modules (signatures and config only). S3 was read from `tcp-mvp/s03-orchestrator`
(commit `cc268af`, `orchestration/projects.py`, `intake/kml_reader.py`, `pipeline.py`) with `git show`; no S3 plan or report file exists on that branch yet.

## 1. What is there today

| Area | Finding (file evidence) |
| --- | --- |
| Call 1 schema | `ai/vision_provider.py` `OBSERVATION_SCHEMA`: per-property nullable unions, `minimum`/`maximum`. Foundry rejects it (HTTP 400, 23 union parameters, limit 16; spike). It must be replaced by the facts list (D-61) |
| Agent | `ai/vision_agent.py` (812 lines) runs call 1, crops, call 2, claims, consistency in one TA-1-shaped class; `agent.max_model_calls = 2` is in `config/pipeline_config.json`. `ai/grounded_vision.py` asks the AI for `traveled_way_width_m` and `distance_to_nearest_edge_m`: a length from the AI, which D-64 forbids (S0 item 33). Call 2 belongs to S7, so this path remains until S7 |
| Fusion | `site_model/fusion.py` (517 lines): OSM, AI and cross-section only. Confidence numbers in config: OSM explicit tag 0.9, implicit 0.6, AI floor 0.7 for critical fields. D-37 says every fused geometry value is low confidence; the numbers disagree with it. `site_model_id` hashes the whole `project_geometry` |
| Width | `site_model/cross_section.py` `measure(...)`: brightness profiles across the OSM centerline, needs a verified centerline, 3 sections 6 m apart, section spread limit 0.5 m, plausible lane width 2.4 to 5.5 m. Records spread only, no pixel-size uncertainty (S0 item 23) |
| Images | One 1280 px wide image per run, half-extent from the largest `A` plus a 60 m margin; call 1 sends it unresized. Crops are new Azure Maps `fetch_view` requests (1024 px, zoom 19), not cuts of the wide image. No model limit and no resize step (S0 item 21). `config/pipeline_config.json` also has `imagery.ai_image_px` 1024 and `crops.min_px_per_lane` 15; their exact use must be confirmed in commit 2 |
| OSM | `data_sources/osm_overpass.py` calls the OSM map API `/api/0.6/map?bbox=`, not Overpass (S0 item 32). Only OSM, the AI and the cross-section feed fusion; no MassGIS, RIGIS, HPMS, Census, 3DEP, GTFS or FRA code exists |
| Registry | The S4 registry has 36 `OBSERVED_COMPUTED` fields, each with `source_type` (CODE, AI, AI_CROSSCHECKED, AI_THEN_SME, CODE_AND_AI, AI_AND_CODE, CODE_THEN_SME_REVIEW) but **no confidence floor, no safety-critical flag and no call number**. Plan section 5 says thresholds live "per field in the registry" |
| Pack gaps | Unsourced in S4 and needed here: low-speed cutoff, default work-vehicle width, default work-space lengths per work type, TMA speed threshold, "minor road", "short TTC zone" |
| Fixtures | `tests/support/` replays by request fingerprint. The seeded AI fixtures were recorded against the old call 1 prompt and schema, so they stop matching as soon as call 1 changes. The nine real facts-list responses and three wide images from the spike exist only on branch `tcp-mvp/s00-schema-spike` (`spikes/schema_spike/raw`, `inputs`), with a known scale (Colorado image: half-extent 212.4 m, 0.4419 m per pixel) |
| S3 shapes | Zone engine input (`zone_input.json`, schema_version "1"): `project_id`, `lineage_key`, `zone{zone_id, version, sheet_label, engine_geometry_hash, ta_hypothesis}`, `locations[]`, `start_fields{road_type, posted_speed_mph, traffic_volume, lane_closure}`, `advanced`. `kml_reader.from_zone` builds a `ProjectGeometry` with `work_path: []` and one Point per zone; the zone block and start fields are inside the site-model hash |
| Recorder | `python -m tests.support.record live KML SITE --road-type ...` drives the single-KML pipeline with flags. It does not know projects or zones |

## 2. Scope and acceptance criteria

Spec text kept; items marked "added" are testable readings this plan makes.

| # | Criterion | Check |
| --- | --- | --- |
| A1 | Call 1 returns the facts list (JSON only, every property required, no nullable union, no min/max); parsed with Pydantic; a missing or malformed fact becomes UNKNOWN; enums compared without case | Schema inspection test (0 optional, 0 union parameters, counted by script as in the spike); parser tests on the nine real spike responses and on corrupted copies |
| A2 | On replayed fixtures every deciding fact is RESOLVED with evidence or UNKNOWN with a fixed reason; none is guessed | Parametrized over the three sites; a CONFLICT from fusion is stored as a flag and the fact is UNKNOWN (added, Q8) |
| A3 | The AI never reports a length (D-64) | Test fails if a registry field with a length unit appears in the AI facts, or if code reads a number from an evidence string (added: evidence is stored, never parsed) |
| A4 | Code computes every length from pixel positions or geometry | Length tests against fixtures with a known scale: lane, shoulder and median width, distance from edge, gaps, path length, side-road distance |
| A5 | A width interval that contains a TA threshold makes the fact UNKNOWN and raises a question | Test with the thresholds read from the pack (never typed in code), see Q9 |
| A6 | Mandatory start fields are never written by code | Test: zone input before and after is byte-identical; the four facts carry `source UI`; a computed contradiction creates a conflict question and leaves the value unchanged |
| A7 | A higher-zoom fetch happens only when the pixel threshold fails, and is recorded as evidence with a signature | Mocked pixel counts; the fetch is called zero times above the threshold; the signature is stored |
| A8 | Only approved sources are called | A guard that fails any request to a host outside the allow list; mock fails the test otherwise |
| A9 | For `lanes_per_direction`, `divided_highway`, `shoulder_present` and `oneway`, a disagreement between AI and OSM gives UNKNOWN (`source_disagreement`) with both values kept as candidates; a single source gives UNKNOWN (`single_source`) with the AI value kept as a pre-filled candidate; each raises a question candidate (D-80, D-92, D-111, D-119; single-source treatment per D-156, open) | Synthetic disagreement and single-source cases, including odd OSM lane totals, a missing `oneway` tag with AI true and with AI false, and a missing `lanes` or `shoulder` tag (Q8) |
| A10 | Marks missing or invalid make the width UNKNOWN; width comes from `cross_section` first, AI marks second (D-80) | Cases: section OK and marks bad; section failed and marks good; both bad |
| A11 | Each evidence string is at most 15 words and UNKNOWN facts carry a short fixed reason (D-80) | The cap is an instruction, not a constraint: a longer string is stored whole and flagged in the trace, never cut (tuning proposal section 3, point 4) |
| A12 | Every image sent is resized in code to the limit, and the bytes hashed are the bytes sent | Test on hash equality, no upscale, the scale factor recorded (Q5) |
| A13 | Pre-calculation: footprint, remaining-width table, shadow vehicle, TMA suggestion, arrow board, with default values flagged `DEFAULT_ASSUMED` or `POLICY_SUGGESTED` | Parametrized remaining-width table; defaults stay UNKNOWN while the pack has no source (Q10, Q11, Q22) |
| A14 | At most two AI calls per zone | S6 makes call 1 only; the budget test keeps the cap |
| A15 | Replay: the same request fingerprints twice | For the fixture sites. Real-KML recordings are not part of S6 (D-98, D-128) |
| A16 | Call 1 is blind: its request holds no OSM value and no code-derived value (D-119) | Request-content test: the request builder has no parameter that accepts one |
| A17 | Every fact has one of three outcomes, FOUND, NOT_PRESENT or UNKNOWN, with a reason code on UNKNOWN; a source that was not checked is never NOT_PRESENT (D-111) | Parser and fusion tests per field against `docs/references/S6_outcomes.md`; the generated file stays in step with the field table |
| A18 | The OSM rules of D-111 hold: lanes from forward and backward, else half of an even two-way total; missing `oneway` is "not one-way" at lower confidence and the AI must also say false; missing `lanes` or `shoulder` gives no information; divided from geometry | Table-driven OSM tests on recorded Overpass fixtures |
| A19 | A bearing failure (30 degrees modulo 180) makes every road-specific fact UNKNOWN (`wrong_road_suspected`) and raises one "which road?" question (D-127, D-156) | Tests with the E Second and Colorado marks |
| A20 | A work point within 5 m of the nearest road edge, or with no road near, gives `work_location` UNKNOWN plus one question; the distance is read from config (D-113) | Boundary tests at 4.9, 5.0 and 5.1 m; no road near |
| A21 | Confidence floors are read per model profile: the profile entry if present, else the default; no profile entry ships uncalibrated (D-132) | Floor lookup tests for both shipped profiles |
| A22 | Code checks and consistency checks only lower confidence or give UNKNOWN, never raise it, and never count as a second source; each has an off switch (D-128) | Property test over every check; switch tests |
| A23 | Code snaps each mark to the nearest real edge; a mark with no edge nearby is rejected and gives no width (D-128) | Synthetic image tests with and without an edge |
| A24 | Every prompt is loaded from `prompts/` with a hash check; a changed prompt file fails the pin test (D-129) | Registry tests: id, version, sha256 header, pinned hash |
| A25 | Every run records the calibration values it used (D-127), and every saved answer record keeps kind, field, zone, project, OSM way and answer time (D-130) | Run-record and answer-record schema tests |
| A26 | `config/site_exceptions.json` exists, is empty and documented, and a loaded entry appears in the trace of the fact it changed (D-138, D-155) | Loader, schema and trace tests |
| A27 | The accuracy report counts a wrong value passed on with AI_ONLY_UNCONFIRMED as wrong-and-used, with the flag shown beside it, and reports the 95% upper bound for zero wrong-and-used on the four safety fields (D-118, D-134) | Report tests on a synthetic truth CSV; the exit code 2 on a bad cell |

Out of scope: the router and call 2 (S7), placement (S8), grouping (S9), the question form (S11), polygon and line geometry (S14), the agent loop and deep mode (FS-01), the state and federal data sources (FS-06) and real-KML recordings. Anything the pack cannot source stays empty and marked.

**Amendments 2026-10-31 (section 2).** A9 read: "`lanes_per_direction` disagreement between AI and OSM or state data gives UNKNOWN plus an SME question (D-80)"; now it covers the four safety fields, the single-source case and the candidate (D-92, D-111, D-119). A15 read: "For the fixture sites now, and for the three real KMLs after the user records them"; recordings left S6 (D-98, D-128). A16 to A27 are new (D-111 to D-138).

## 3. Files and modules (proposals)

New:
- `src/tcp_planner/ai/call1.py`: facts-list schema, prompt text, request builder, Pydantic response models, parser; replaces `OBSERVATION_SCHEMA` for the new path.
- `src/tcp_planner/imagery/prepare.py`: `resize_for_model`, `crop_from_image`, pixel-sufficiency decision, higher-zoom request with a signature (reuses `imagery/evidence_views.py` signature helpers).
- `src/tcp_planner/site_model/measure.py`: ground scale, pixel to feet, mark validation, widths with intervals, straddle test.
- `src/tcp_planner/site_model/precalc.py`: footprint, remaining-width table, shadow vehicle, TMA, arrow board as pure functions.
- `src/tcp_planner/site_model/facts.py`: `SiteFact`, `Interval`, `Question` records, schema_version, migration entry in `storage/migrations.py`.
- `src/tcp_planner/data_sources/`: `base.py` (allow-listed client, fingerprint, fixture hook, license note), then one module per source: `osm_overpass.py` (changed), `massgis.py`, `rigis.py`, `hpms.py`, `census_urban.py`, `usgs_3dep.py`, `gtfs.py`, `fra_crossings.py`.
- `src/tcp_planner/site_model/fusion_v2.py` (or a rewrite of `fusion.py`, Q2): candidates per field, agreement, disagreement record, confidence class.
- `config/site_understanding.json` (or a section of `pipeline_config.json`, which is protected; Q7): every threshold with a `source` or `CALIBRATION_PENDING` tag.
- Tests under `tests/unit/site/` and `tests/integration/pipeline/`; fixtures under `tests/fixtures/site/`.

Changed: `config/settings.py` (paths), `ai/foundry_provider.py` (structured-output request for the facts list; fallback "retry once without strict on a 'too complex' 400", plan section 5), `tests/support/record.py` (project and zone aware live mode), the pack registry if Q7 = registry (hash changes), `CLAUDE.md` only if you approve a note.
Protected, not to be edited: the POC rule pack and `config/pipeline_config.json` (guards against `BASELINE_REF`; an edit needs an `APPROVED` entry).

Added 2026-10-31 (names are proposals except those the owner's files already use):
- `prompts/`: one file per prompt with id, version and sha256 in the header; a loader with a hash check (D-129). Tests pin the hashes.
- `config/site_understanding.json`: the confidence floors per profile, the 5 m edge distance, the 30 degree bearing, the divided-geometry distance and angle, the check switches and thresholds, each tagged `source` or `CALIBRATION_PENDING` (D-113, D-127, D-128, D-132).
- `config/site_exceptions.json`: empty and documented, with a README and a loader; an entry is proposed by the SME, entered by the admin, and gets a decision-log entry; roles are recorded as "role selected, not verified" (D-138, D-155).
- `site_model/` modules for the outcomes, the fusion with the two-source rule, the bearing and which-road check, the edge rule, mark snapping and the code and consistency checks.
- `scripts/s06_accuracy_report.py` (truth CSV in), a zoom-19 probe script and an OSM recorder script, run by the owner; a call-1 check script that defaults to the gpt-5.6-sol profile (D-114, D-131).
- `docs/evaluation/`: the site truth files for the 8-site early check (D-125). `docs/templates/`: the truth, sites and second-source CSV templates the scripts check against.
- Dropped from this slice: the adapters for MassGIS, RIGIS, HPMS, Census, 3DEP, GTFS and FRA (FS-06) and `tests.support.record live` made project and zone aware (recordings are not in S6).

**Amendments 2026-10-31 (section 3).** The list under "New" above named adapter modules `massgis.py`, `rigis.py`, `hpms.py`, `census_urban.py`, `usgs_3dep.py`, `gtfs.py`, `fra_crossings.py`, and changed `tests/support/record.py` to be project and zone aware. Both moved out of S6 (FS-06; D-98, D-128). `config/site_understanding.json` was already the answer to Q7 B.

## 4. Data shapes (proposed; each new field bumps a `schema_version` and needs a migration)

```
Fact (AI wire, one list item)   {field (enum from registry), value (string), status RESOLVED|UNKNOWN|CONFLICT, confidence, evidence}
                                 # after parsing, the stored fact has outcome FOUND|NOT_PRESENT|UNKNOWN (D-111); the wire status is mapped by code
                                 # unit is removed if the tuning proposal P5 is approved (Q3); code fills unit from the registry
Mark (AI wire)                  {feature: road_edge_left|road_edge_right|lane_line|shoulder_edge|work_point|curb, points "x1,y1;x2,y2", status, evidence}
ImageEvidence                   {artifact_ref{uri,sha256,size,media_type}, source_px, sent_px, resize_scale, mpp_sent, center, signature, parent_crop_spec, purpose}
SiteFact (shared contract)      {field, value, unit, confidence, uncertainty?, source, evidence_ref, status}
   + proposed                   interval{lo, hi, unit}, reason_code (not_visible|occluded|low_resolution|ambiguous|source_disagreement|threshold_in_interval|no_source),
                                flags[] (DEFAULT_ASSUMED, POLICY_SUGGESTED, CALIBRATION_PENDING, SOURCE_REVIEW_REQUIRED), candidates[{source, value, confidence_class, evidence_ref}]
MeasuredLength                  {name, value_ft, interval_ft, method CROSS_SECTION|AI_MARKS|GEOMETRY|ELEVATION, mpp, pixel_error_px, inputs[], calculation, flags[]}
Question (shared contract)      {question_id, kind WIDTH_NEAR_THRESHOLD|LANES_DISAGREE|LANES_UNSPLIT|START_FIELD_CONFLICT|FACT_UNKNOWN|WORK_SIDE_CONFIRM|WHICH_ROAD|WORK_LOCATION_NEAR_EDGE|WORK_LOCATION_CONFLICT,
                                 field, zone, project, osm_way_id|null, context, reason, options[], default_if_skipped, reveals[], candidate bool, suggested|null}
                                 # candidate = a non-blocking question prefilled with the AI value; S7 makes it blocking only when the what-if test shows the fact decides the TA (D-156, open)
                                 # the saved answer keeps kind, field, zone, project, OSM way and answer time (D-130)
SourceCall                      {source_id, host, request_fingerprint, retrieved_at, license_note, attribute_names[], artifact_ref}
```
Mandatory start fields enter S6 as a read-only mapping and come out as facts with `source UI`, equal to the input. All persisted artifacts use refs and carry `schema_version`; nothing holds a raw path (the S2 raw-path scan covers the new JSON).

**Amendments 2026-10-31 (section 4).** The `Question.kind` list read `WIDTH_NEAR_THRESHOLD|LANES_DISAGREE|START_FIELD_CONFLICT|FACT_UNKNOWN|WORK_SIDE_CONFIRM` and had no `field`, `zone`, `project`, `osm_way_id`, `context`, `candidate` or `suggested` (D-130, D-111, D-113, D-156). The wire `status` is unchanged; the stored three-valued outcome is new (D-111).

Pixel coordinates from the AI refer to the image as sent. A resize changes the ground scale, so every conversion uses `mpp_sent`, not the scale of the source image.

## 5. Commit sequence

Branch off S3's last commit once S3 is merged or declared stable. Session 1 is commits 0 to 12, offline. Session 2 (the state and federal data sources) is not part of this sequence: it moves to after the first scored test (FS-06). There is no recording in S6.
Live calls: only the checks the owner runs: the nine-call check on both profiles (D-97), the zoom-19 probe (D-114), and the 8-site early check (D-125). Everything else runs on fakes.

| # | Commit | Batch | Stop |
| --- | --- | --- | --- |
| 0 | S6 0: move `BASELINE_REF`, empty `APPROVED` | A | no |
| 1 | S6 1: facts, marks, `SiteFact`, `Question`, `Interval` models; parser with UNKNOWN fallback; registry-driven field list; tests on the nine spike responses (Q16) | A | no |
| 2 | S6 2: call 1 schema, prompt, request builder, `resize_for_model`, fingerprint, fallback on "too complex"; fake provider tests | A (needs Q3, Q5, Q6 answered) | **STOP 1**: you read the final prompt text and schema before any live call is possible |
| 3 | S6 3: measurement core: scale, pixel to feet, mark validation, widths from cross-section then marks, intervals, straddle test against pack thresholds, questions | B | **STOP 2, safety-critical**: the width numbers and the UNKNOWN rule on synthetic cases, with the starting error values (Q9) |
| 4 | S6 4: start-field protection, conflict questions, pre-calculation functions, remaining-width table | B | **STOP 3, safety-critical**: the remaining-width table and what stays UNKNOWN for lack of a source (Q10, Q11) |
| 5 | S6 5: crop engine: code crop, pixel sufficiency, higher-zoom decision with signature evidence | C | no (decisions are on pixel counts; no model reads an image in a test) |
| 6 | S6 6: source framework: allow list, fingerprinted client, fixture hook, `SourceCall`, fusion record, confidence classes (Q14) | C | no |
| 7 | S6 7: OSM adapter (Overpass, D-136), the OSM rules of D-111 for lanes, one-way, shoulder, sidewalk and divided, the OSM recorder script | C | no |
| 8 | S6 8: fusion with the three outcomes and the two-source rule; the bearing check and "which road?" question; the 5 m edge rule; per-profile floors; the fusion rule table for all 18 call 1 fields and the list of consistency checks | C | **STOP 5**: the fusion rule table and the consistency checks (`docs/reports/S6_stop5_fusion_rules.md`), including the three D-156 questions |
| 9 | S6 9: wire into the pipeline as decided in Q2; D-80 checks; replay determinism | D | **STOP 4** if Q2 = replace the old call 1: stored expected outputs of the 13 offline scenarios change and need your approval to regenerate |
| 10 | S6 10: code checks and consistency checks 8 to 13 (lane count against width, lane lines, shadow and tree-cover share, image-to-OSM offset, approaching lanes, sidewalk pair), code snapping of marks; each with a config switch, values tagged CALIBRATION_PENDING | D | no |
| 11 | S6 11: the enhanced call-1 prompt in `prompts/` as a new version (the first version stays and stays pinned); arm switches for D-124 | D | **STOP 6**: you read the enhanced prompt text before any live use |
| 12 | S6 12: accuracy tooling (truth CSV check, report with the 95% upper bound, wrong-and-used with the flag shown), zoom-19 probe script, `docs/evaluation/` truth files, the early-check procedure; slice report and full suite | D | end. **You run** the nine-call check, the probe and the 8-site check (`TCP_LIVE=1`) |

Batches: A (0 to 2), B (3 to 4), C (5 to 8), D (9 to 12). One run per batch, stopping where marked. Anything that reads an image with a model happens only in the checks you run (commit 12).

**Amendments 2026-10-31 (section 5).** The table ran to commit 15 with two sessions. Old commits 10 to 12 (source discovery with its STOP 5, then the MassGIS, RIGIS, HPMS, Census, USGS 3DEP, GTFS and FRA adapters) moved out of S6 (FS-06, owner conversation 2026-10-31). Old commits 13 and 14 (the project-aware recorder and the owner's recording of Granite, E Second St and Colorado, with STOP 6) left S6; recording stays as D-98 says: Colorado after S7 merges, the rest after S9 (D-128). The old STOP 5 (source endpoints) and STOP 6 (live recording) are replaced by the fusion rule table and the enhanced prompt text. Old commit 9 allowed an optional live prompt check; the checks are now listed under "Live calls". Old commit 7 allowed "Overpass or the map API"; D-136 chose Overpass.

## 6. Tests

All offline; the root `conftest.py` blocks the network unless `TCP_LIVE=1`.

| Test | Covers |
| --- | --- |
| Schema | 0 optional and 0 union parameters; every property required; no min or max; the field enum equals the registry fields assigned to call 1 |
| Parser | Nine real spike responses parse; case-insensitive enums; missing fact becomes UNKNOWN; malformed mark becomes UNKNOWN width; extra fields rejected; evidence over 15 words kept and flagged |
| No AI length | No length-unit field in AI output; no module parses a number from evidence |
| Start fields | Never written; contradiction gives a question and no change; per-point override preserved |
| Measurement | Known-scale fixtures: pixel to feet, resize rescale, interval from pixel error, section spread, marks invalid |
| Straddle | Remaining width and lane width across the pack's thresholds, parametrized; thresholds read from the pack only (a test greps S6 modules for the numbers 9 and 10 used as limits) |
| Remaining-width table | Every row of plan section 4C including the band row; defaults UNKNOWN when unsourced |
| Lane cross-check | AI vs OSM: forward/backward tags, even total, odd total, missing; disagreement gives UNKNOWN and one question |
| Crops | Mocked pixel counts above and below the threshold; zero higher-zoom fetches above it; signature recorded |
| Sources | Allow list; each adapter parses its recorded fixture; disagreement recorded; fused values carry a confidence class; none writes a start field |
| Budget | Never more than two AI calls per zone |
| Replay | Same fingerprints twice; same facts hash twice |
| Storage | No raw path in any new JSON (S2 scan); every record has `schema_version`; migration round trip |
| Regression | Existing suites unchanged (last full runs: 363 passed on S4, 468 on S2, both with 11 skips), protected-file guards green |

## 7. Blocks and is blocked by

- Blocked by: S3 (zone input, projects, start fields), S4 (registry, pack, done), S0 spike (done), S2 stores (done).
- Blocks: S7 (facts, crops and `Question` records; router thresholds), S8 (lengths, intervals), S9 (second-pass geometry and envelope inputs), S11 (question records), S13 (recorded fixtures).
- Not blocked by S5.

## 8. What could go stale if S3, S6 or S7 changes a data shape

| If this changes | Goes stale |
| --- | --- |
| S3 changes the zone input (`start_fields` names or enums, `ta_hypothesis`, `engine_geometry_hash`, `work_path`, `lineage_key`) | The measurement and start-field tests, `fusion` inputs, `ProjectGeometry` hashing; every recorded fixture whose key includes the zone block. S3 gives one Point per zone and `work_path: []`; S9 will give several points per zone, so "gaps" and "path length" are tested only on synthetic paths until then |
| S3 changes the project or run record layout | Where S6 writes facts and images (run folder keys) and the recorder |
| S6 itself changes the fact or mark shape after S7 starts | S7 router conditions, call 2 prompts and crop requests, S8 inputs, S11 forms. Freeze `SiteFact`, `Interval`, `Question` before S7 starts; version them |
| S6 changes the prompt, schema or resize rule | **Every recorded AI fixture** (the fingerprint includes prompt, schema and image bytes); the three real recordings must come after these are final (Q3, Q5, Q18) |
| S7 changes the TA-field split between call 1 and call 2 | The call 1 field enum, the precalc functions that depend on a TA (Q11), `lanes_per_direction` re-ask |
| S7 or S9 changes the zone extent | Imagery extent and the evaluation radius (Q17); per-point zone fixtures recorded after S6 become stale after S9 (Q18) |
| S4 pack edit after S6 | Straddle thresholds (read from the pack, so they follow), registry-held floors (Q7), pinned pack hash in tests |

## 9. Open questions

Part A: decisions you make. Part B: inputs to obtain from the client or another owner. "Blocks" says what cannot start or finish without the answer.

### Part A: decisions

**Q1. Split S6 into two sessions?** (Decision) ANSWERED (see decisions section)
- A. One session for everything. Effect: ten external sources whose endpoints, keys and attribute names are all UNKNOWN (S0 item 32) sit in the same slice as the call 1 rewrite; a stall on one source stalls the slice.
- B. Session 1 = call 1, measurement, crops, OSM, wiring (commits 0 to 9). Session 2 = sources and recording (10 to 15). Effect: S7 can start after session 1 for fields that need only OSM; the state data cross-check (D-80) arrives later.
- Suggestion: B. Blocks: planning only.

**Q2. Replace the old call 1 in the pipeline, or build the new path beside it?** (Decision) ANSWERED (see decisions section)
- A. Build beside it, switch in S7 when the router exists. Effect: the TA-1 pipeline, the 13 offline scenarios and the protected tests stay byte-identical until S7; the AI-length path (D-64) stays until S7; `record live` needs a second entry point.
- B. Replace now. Effect: the old observation schema and `grounded_vision` call 2 stop working together; stored expected outputs change (approval needed) and S6 must also adapt call 2 or disable it.
- C. Replace call 1 now and keep call 2 on an adapter. Effect: most work, least wasted.
- Suggestion: A. Blocks: commit 8, and the recorder design.

**Q3. Approve the prompt tuning proposal, and run the live check?** (Decision; D-80 point 4 says "once approved") ANSWERED (see decisions section)
Proposal: P1 (evidence at most 15 words) + P2' (UNKNOWN evidence is one fixed code: `not_visible`, `occluded`, `low_resolution`, `ambiguous`) + P5 (remove `unit` from facts, filled from the registry) + shorter instructions; keep `approaching_lanes_one`; skip the 10-word cap and the 6-point cap. Estimated saving 218 output tokens per call (9.5%) with P5, 115 without; this is a simulation on saved answers.
- A. Approve all four. Effect: changes the D-61 schema (one property fewer) and every fixture; one live check of 9 calls, plus 3 calls at `effort=medium` on Granite to see whether the lane count moves.
- B. Approve all but P5. Effect: schema stays as the spike validated; saving 115 tokens.
- C. Keep the spike prompt unchanged except the 15-word instruction. Effect: no tuning risk, no saving.
- Suggestion: B, then the 9-call check; take P5 later if the check is clean. Blocks: commit 2 (prompt text), and every recording.

**Q4. Which AI profile does call 1 run on, and at what effort?** (Decision; S0 open question 1) ANSWERED (see decisions section)
`config/foundry_profiles.json` defaults to `gpt-5.6-sol`; the spike measured `claude-opus-5-5` only, at effort `high`. The facts list has never been run on `gpt-5.6-sol`, and the file records that its call 2 schema exceeded the Claude grammar limit.
- A. Claude deployment for call 1 and call 2. B. Keep `gpt-5.6-sol` and run the 9-call check on it first. C. Two profiles, one per call.
- Effect: A uses the measured profile (22 s per call, 3,597 input and 2,305 output tokens); B needs live calls before any fixture is recorded; C adds a second fingerprint family.
- Suggestion: A. Blocks: commit 2 (provider code), the live check and the recordings.

**Q5. Resize policy.** (Decision; the limit value itself is Q19) ANSWERED (see decisions section)
- A. Limit per Foundry profile in `config/foundry_profiles.json`; Lanczos downscale only, never upscale, fixed JPEG quality, the sent bytes hashed and stored, `mpp_sent` recorded. B. One global limit in the pipeline config. C. Do not resize; rely on the provider.
- Effect: C breaks D-27 (the model may shrink the image and the hash would not match what it saw). B is wrong if two profiles differ.
- Suggestion: A, with the current 1280 px kept as the default until Q19 answers. Blocks: commit 2.

**Q6. What is in call 1, and what waits for call 2?** (Decision; plan open question 18) ANSWERED (see decisions section)
The spike asked 18 fields. Plan section 4B lists more AI observations (`behind_barrier`, `opposite_shoulder_suitable`, `closed_lane_side`, `lanes_closed_count`, `positive_barrier_present`, `ramp_present`, `work_type`) and marks `source_type` AI or AI_THEN_SME for some.
- A. Call 1 = the 18 spike fields plus marks. Everything TA-specific waits for call 2. B. Add the TA-specific fields to call 1 too (more tokens, more UNKNOWN). C. Add a `call` attribute per field in the registry and let it drive the enum.
- Effect: B raises output beyond 2,300 tokens; C changes the pack and its hash but keeps one source of truth.
- Suggestion: A now; C when S7 shows which fields move. Blocks: commit 1 (the field enum). Your SME's check of section 4B (open question 18) covers this.

**Q7. Where do confidence floors, safety-critical flags and pixel thresholds live, and with which starting values?** (Decision) ANSWERED (see decisions section)
Plan section 5: 0.70 for common facts (carried from the POC), 0.80 for safety-critical facts in new TAs, 0.85 for router auto-select (S7). The registry has no place for them.
- A. New attributes in the registry (pack hash changes, S4 tests re-pinned). B. A new `config/site_understanding.json`. C. A section in `pipeline_config.json` (protected; needs an `APPROVED` entry).
- Effect: A keeps the rule that thresholds sit "in config or the registry" and follows the field; B is simplest and keeps the pack MUTCD-only (it holds implementation settings, not regulation); C breaks the guard flow.
- Suggestion: B, every entry tagged `source` or `CALIBRATION_PENDING`. Which fields are safety-critical is your SME's call (Q22). Blocks: commit 2.

**Q8. Disagreement and single-source rules for safety-critical facts.** (Decision; D-80 point 1) ANSWERED (see decisions section)
- A. AI and OSM or state data disagree: UNKNOWN plus a question. Only one source available (no OSM `lanes`, no state value): keep the AI value as RESOLVED at its confidence. B. Same, but with one source only the fact is UNKNOWN. C. Same as A, plus a second AI read from a lane-marking crop in S7 before deciding.
- Effect: the spike saw Granite at 2, 1, 1 across three identical calls, so with A a single-source wrong lane count could reach the router. B asks more questions. OSM `lanes` is a two-way total or per direction (`lanes:forward`, `lanes:backward`): an odd total (a centre turn lane) cannot be split, so the cross-check cannot decide (no agreement, no disagreement).
- Also decide here: the wire status CONFLICT is stored as a flag and the fact is UNKNOWN (this plan's reading of "RESOLVED or UNKNOWN").
- Suggestion: B for `lanes_per_direction`, `divided_highway`, `shoulder_present`, `oneway`; A for the rest. Blocks: commit 7.

**Q9. Width uncertainty model and the straddle test.** (Decision; D-38 says "to be calibrated") ANSWERED (see decisions section)
Proposal: interval = measured width plus or minus (edge pixel error x `mpp_sent` x 2), plus the cross-section spread when that method was used; straddle = evaluate the pack's conditions at the low end, the high end and the middle, and treat a change of result as "a threshold is inside" (no threshold values copied into code; valid because the TA-6 conditions are monotone comparisons).
- Starting values: edge pixel error 1.0 px per edge (D-38's example) at 0.44 m per pixel (spike scale) gives about 0.88 m (2.9 ft); at the plan's 0.33 m per pixel about 0.66 m (2.2 ft).
- A. Adopt as proposed, values `CALIBRATION_PENDING`. B. Fixed interval in feet per method, set by your SME. C. Always UNKNOWN for any width from the wide image, widths only from a close view.
- Effect: with A the 10 ft limit will often sit inside the interval, so TA-6 questions will be common; C is safest and asks most.
- Suggestion: A, and the SME reviews the numbers on the synthetic cases (STOP 2). Blocks: commit 3.

**Q10. Footprint and encroachment have no source.** (Decision; needs Q22 values) ANSWERED (see decisions section)
`remaining_lane_width_ft = lane_width - encroachment_depth`, measured to the near face of the channelizing devices (TA-6 note 1). The pack has no default work-vehicle width, no default work-space size per work type, and no clearance between the work space and the device face (all UNKNOWN in S4).
- A. In real runs `remaining_lane_width_ft` stays UNKNOWN unless the SME supplies the footprint (asked-if-needed `work_type` and size on the form, S11). Effect: the lane-closure conflict check (A6) cannot fire for most real zones; tests use supplied footprints.
- B. Measure the footprint from the work-point mark and the visible vehicle in the image. Effect: depends on the weak marks (34 of 51 valid in the spike).
- C. Use client-supplied defaults when they arrive (Q22), flagged `DEFAULT_ASSUMED`.
- Suggestion: A now, C when values arrive. Blocks: commit 4 (the table is built either way).

**Q11. Where do TA-dependent pre-calculations run?** (Decision) ANSWERED (see decisions section)
Shadow vehicle, TMA suggestion and arrow board depend on the TA and `duration`, which S7 and S11 produce; S6 runs before S7. TMA threshold (45 mph proposed as client policy, default "no automatic suggestion", open question 6) has no source.
- A. S6 ships them as pure functions with tests; S7 or S8 calls them once the TA is known; S6 computes only the TA-independent ones (vehicle width, footprint, remaining width, freeway flag). B. Move them to S8. C. Run them in S6 for every candidate TA.
- Suggestion: A, TMA suggestion off until you confirm a threshold. Blocks: no.

**Q12. Data sources: how are they accessed, and may I read them live to find attribute names?** (Decision) ANSWERED (see decisions section)
- Access: (a) live REST per run with recorded fixtures for tests; (b) local extracts committed or downloaded once with a hash; (c) mixed. Effect: (a) needs endpoints and keys and is subject to rate limits; (b) is deterministic but large and can go stale; the licence of each must be checked.
- Discovery: CLAUDE.md allows live calls only in S13, the spike and the post-S6 recording, and only for Azure Maps and the AI. Learning MassGIS, RIGIS, HPMS, Census, 3DEP, RIPTA and FRA attribute names needs reading those services. Options: public documentation only (S0 did this); or a one-time spike under `spikes/` with `TCP_LIVE=1` run by you; or you supply the schemas.
- OSM: the code uses the map API `/api/0.6/map`, the plan says Overpass (urban boundary, land use, filtered tags). Switching changes the fixture format and the usage policy (fair use, descriptive User-Agent).
- Suggestion: (a) for the MVP, documentation first, then a small `TCP_LIVE` discovery spike that you run, Overpass for OSM. Blocks: commits 7 and 10 to 12.

**Q13. Which checks of the mandatory start fields are in S6?** (Decision) ANSWERED (see decisions section)
Spec: a computed check that contradicts one raises a conflict question. Defined case: remaining width versus `lane_closure`.
- A. Only that case. B. Also posted speed against OSM `maxspeed` and `road_type` against Census urban area or HPMS class. 
- Effect: B uses sources the plan keeps as "future automation candidates" and adds noisy questions; with A, Census urban areas and HPMS have no S6 consumer and their adapters can wait.
- Suggestion: A. Blocks: scope of commit 11.

**Q14. Confidence of fused values.** (Decision) ANSWERED (see decisions section)
D-37 and CLAUDE.md: fused geometry is low confidence, imagery decides, disagreements are recorded. `fusion.py` currently gives OSM tags 0.9 and implicit 0.6.
- A. Replace numbers with classes (LOW for fused geometry, MEDIUM for imagery-agreeing, HIGH only for SME or UI) and keep numbers only for AI confidence. B. Keep the numbers and add a `source_class` flag. C. Keep as is.
- Effect: C contradicts D-37; A changes what S7 compares against 0.85.
- Suggestion: A. Blocks: commit 6.

**Q15. Crop sufficiency thresholds and the zoom ceiling.** (Decision; plan: "enough pixels per feature type is a setting to calibrate") ANSWERED (see decisions section)
Existing: `min_px_per_lane` 15, sharpness gain ratio 1.15, zoom 19. No values exist for edges, markings, curbs, sidewalks.
- A. Start with the existing two values for lane features, and tag the rest `CALIBRATION_PENDING` with a conservative default that always asks for a higher-zoom fetch. B. Leave the others out until calibrated (crop only what has a value).
- Effect: A may cost extra Azure Maps requests; B leaves features unresolved.
- Suggestion: A. Blocks: commit 5.

**Q16. Test fixtures for call 1.** (Decision) ANSWERED (see decisions section)
- A. Cherry-pick the spike inputs (three wide images, scale files) and the nine raw responses into `tests/fixtures/site/` as parser and measurement inputs, marked "real model output, pre-tuning prompt"; replay fixtures for the new request are hand-built with fakes. B. Synthetic only. C. Wait for the live recording.
- Effect: B cannot test marks or scale on real imagery; C delays all tests. A stores Azure Maps imagery in the repo (D-46 dropped the terms check).
- Suggestion: A. Blocks: commit 1.

**Q17. Image extent and evaluation radius for a single-point zone.** (Decision) ANSWERED (see decisions section)
The wide image extent today follows the largest `A`. Under the v1 pack Table 6B-1 gives A, B and C up to 1,000, 1,500 and 2,640 ft (freeway), a 1.6 km corridor, which at 1280 px is more than 1 m per pixel and useless for width. The zone length of a single Point is unknown (S0 item 6; open question 2).
- A. Wide read at a fixed extent from config (current 60 m margin plus a per-road-type distance), widths only from close views and the cross-section; side roads, crossings and curves searched within a configured radius. B. Extent from the pack's A, B, C per road type. 
- Effect: B gives poor pixels on rural and freeway sites; A needs a value for the radius (Q22).
- Suggestion: A. Blocks: commits 3 and 12.

**Q18. When are the real KMLs recorded?** (Decision) ANSWERED (see decisions section)
Spec: after S6. S3 gives one zone per Point (Granite = 5 zones, E Second St = 2, Colorado = 1); S9 will regroup them (Granite to 2 zones), and the request fingerprint includes the zone geometry, so the per-Point recordings go stale at S9, and any prompt change (Q3) stales them at once.
- A. Record after S6 as specified (about 8 call 1 requests plus Azure images; call 2 only if the old call 2 is still wired), accept a re-record after S9. B. Record after S9, so one recording serves S7 to S13. C. Record Colorado only after S6 (single zone, unaffected by grouping).
- Suggestion: C, then the rest after S9. Blocks: commit 14.

### Part B: inputs to obtain

**Q19. Deployment facts for the AI profile.** Maximum image size of the deployed model, rate limit and quota (a 429 gives `AI_RATE_LIMITED` with no retry today), allowed concurrency, and the owner of the deployment (S0 open questions 1 and 6).
- If not supplied: the resize limit stays at the current 1280 px and no concurrency cap beyond the config `max_parallel_zone_runs`. Blocks: commit 2 value only.

**Q20. Calibration data for width uncertainty.** Widths labelled on the reference drawings (lane widths, shoulder widths, the 11 ft note) for the three sites, and your SME's acceptable error. D-38: "calibrate against the widths on your reference drawings".
- If not supplied: values stay `CALIBRATION_PENDING` and tests use synthetic ground truth. Blocks: nothing, but acceptance of Q9 values.

**Q21. Source access facts.** For MassGIS, RIGIS, HPMS, Census TIGER urban areas, USGS 3DEP, RIPTA GTFS and FRA: endpoint or download, key, rate limit, attribute names, licence. MBTA: the static feed URL and a key. Which jurisdiction first (Granite is Rhode Island; E Second St and Colorado are Massachusetts). Who registers any key.
- If not supplied: I research public documentation (read-only, as in S0) and the rest of the sources stay stubs behind the allow list. Blocks: commits 10 to 12.

**Q22. Values and definitions with no source.** All stay empty and `SOURCE_REVIEW_REQUIRED` or UNKNOWN until supplied:
- the low-speed cutoff and "minor road" (S4), which keep `low_speed_road` UNKNOWN;
- default work-vehicle width, default work-space length per work type (pole, manhole, excavation, trench), and the clearance from work space to the device face (Q10);
- the definition of "curve or crest near the zone": a curvature or sight-distance test and a distance (TA-10 note 6 says only "before a horizontal or crest vertical curve"); `curve_or_crest_near_zone` stays UNKNOWN without it;
- TMA speed threshold (45 mph proposed), the length of a "short TTC zone" (S4);
- which fields are safety-critical for the confidence floor (Q7).
- Blocks: no commit; each affects only its own fact.

**Amendments 2026-10-31 (section 9).** The answers recorded as "see decisions section" stand, with these changes from the 2026-10-31 register:
- Q4: call 1 uses gpt-5.6-sol by default and the claude-opus-5-5 profile stays working; revisit after measurement (D-131, FS-12). Q7 floors are keyed per profile (D-132).
- Q8: the single-source rule on the four safety fields becomes UNKNOWN with the AI value kept as a candidate (D-156 recommendation 1, owner confirmation open); the missing `oneway` tag rule is D-111.
- Q12: the discovery spike for MassGIS and RIGIS moves with session 2 to after the first scored test (FS-06); Overpass is the OSM source, public server for development, self-hosted before production (D-136, FS-08); the User-Agent has no company name or contact until production (D-115).
- Q17 and Q19: the hybrid zoom (wide image in call 1, fine zoom-19 view in call 2) is D-112; the zoom-19 probe for E Second and Colorado is D-114.
- Q18: no recording in S6 (D-98, D-128). The three-recordings-after-S6 wording of the original question is superseded.

## 10. Summary of questions

| # | Question | Type | Blocks | Suggestion |
| --- | --- | --- | --- | --- |
| 1 | Split S6 in two sessions | Decision | Planning | B: two sessions |
| 2 | Replace old call 1 or build beside | Decision | Commit 8, recorder | A: beside, switch in S7 |
| 3 | Approve prompt tuning, run live check | Decision | Commit 2, all recordings | B: all but P5, then 9-call check |
| 4 | AI profile and effort | Decision | Commit 2, live check | A: Claude deployment |
| 5 | Resize policy | Decision | Commit 2 | A: per profile, no upscale |
| 6 | Call 1 field list | Decision | Commit 1 | A: the 18 fields plus marks |
| 7 | Where thresholds live, start values | Decision | Commit 2 | B: new config file, tagged |
| 8 | Disagreement and single-source rule | Decision | Commit 7 | B for the four critical fields |
| 9 | Width uncertainty and straddle test | Decision | Commit 3 | A, SME checks numbers |
| 10 | Footprint and encroachment without source | Decision | Commit 4 | A now, C when values arrive |
| 11 | Where TA-dependent pre-calc runs | Decision | No | A: pure functions, called later |
| 12 | Source access mode, discovery permission, Overpass | Decision | Commit 7; the rest moved to FS-06 (2026-10-31) | Overpass now; MassGIS and RIGIS discovery after the first scored test |
| 13 | Start-field checks in scope | Decision | Scope of the data-source adapters (FS-06) | A: remaining width only |
| 14 | Confidence classes | Decision | Commit 6 | A: classes for fused values |
| 15 | Crop thresholds and zoom ceiling | Decision | Commit 5 | A: two known values, rest pending |
| 16 | Call 1 test fixtures | Decision | Commit 1 | A: cherry-pick spike data |
| 17 | Image extent and evaluation radius | Decision | Commits 3, 12 | A: fixed extent, close views for width |
| 18 | Recording timing | Decision | None in S6 (D-98, D-128) | Colorado after S7 merges, the rest after S9 |
| 19 | Deployment facts (image limit, quota) | Client input | Commit 2 value | Default 1280 px |
| 20 | Calibration widths from the drafts | Client input | Acceptance of Q9 | Stay `CALIBRATION_PENDING` |
| 21 | Source endpoints, keys, attributes, order | Client input | FS-06 (after the first scored test) | Docs research, stubs |
| 22 | Values and definitions with no source | Client input | No | Stay UNKNOWN |
