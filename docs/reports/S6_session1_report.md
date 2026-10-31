# S6 session 1: final report (site understanding, call 1)

Branch `tcp-mvp/s06-site-understanding`, merged with `origin/tcp-mvp/base` at `69ab4c09d789b6db5a101bc76f66a23c30fe91b3` (BASELINE_REF set to it, APPROVED empty).
Not merged to base. No live call was made by me; every live step below is yours to run with `TCP_LIVE=1`.

## 1. Status against the plan

| Step | Result |
| --- | --- |
| 0 housekeeping | merged, BASELINE_REF set, guard and baseline tests green, branch pushed as a backup |
| 1 prompt registry | `prompts/`, hash-verified loader, version 1 hashes unchanged (system `5e731eab...`, user template `81b8f019...`, combined `58a344b4...`, Granite request `720ac0e1...`) |
| 2 outcomes | FOUND, NOT_PRESENT, UNKNOWN in the fact model, parser and fusion; per-field meaning in `docs/references/S6_outcomes.md` |
| 3 OSM | Overpass adapter (allow-listed host, bounded query, fixture replay, User-Agent with no company name and no contact) and the OSM rules |
| 4 bearing | 30 degrees modulo 180; reference way chosen by the work point only (owner review R1); tested with the E Second St and Colorado marks and the Granite P32 corner |
| 5 edge rule | within 5 m of the nearest edge, or no road near: UNKNOWN plus one question (the no-road question is a candidate, R4) |
| 6 floors | default entry plus optional per-profile entries; none set for a profile |
| 7 STOP 5 | approved with R1 to R6, all built |
| 8 enhanced prompt, snapping | prompt version 2 (new registry files), schema v2, snapping, blind-request tests; STOP 6 approved |
| 9 code checks, consistency | lane lines, shadow and canopy share computed by code, image-to-OSM offset; five consistency checks; the model's shares are a cross-check candidate only |
| 10 stage switches | `stages` in config: osm, bearing, snapping, edge_rule, lane_lines, shadow_canopy, osm_offset, consistency, site_exceptions, enhanced_prompt (off by default) |
| 11 wiring | `site_model/understanding.py` beside the old path: trace with the config values and hashes, the gate where the result is built |
| 12 question model | kind, field, zone id, project id, OSM way id, context, candidate, suggested; `AnswerRecord` keeps kind, field, zone, project, way and answer time. No log store |
| 13 owner scripts | zoom-19 probe, OSM recorder, recorded-OSM to second-source CSV |
| 14 calibration | 42 CALIBRATION_PENDING values, all in config; a test proves the code holds no other number (`docs/reports/S6_calibration_values.md`) |
| Addenda | empty `config/site_exceptions.json` with loader, schema check, roles (SME proposes, ADMIN enters, "role selected, not verified"), `ta_situation` column, default profile gpt-5.6-sol |

## 2. Files changed (mine; the S5 merge brought its own device catalog files)

**New source:** `src/tcp_planner/ai/prompt_registry.py`, `data_sources/osm.py`, `imagery/snap.py`, `site_model/{bearing_check,code_checks,consistency,edge_rule,fusion_apply,osm_rules,outcomes,site_exceptions,understanding}.py`.
**Changed source:** `ai/call1.py` (prompt registry, version 2, floors, review flags), `site_model/{facts,fusion_v2,site_config,lengths,precalc,start_fields}.py` (outcome field, flags, question fields), `config/settings.py` (PROMPTS_DIR).
**New config and prompts:** `config/site_exceptions.json`, new sections of `config/site_understanding.json` (osm, bearing, edge_rule, confidence_floors, snapping, code_checks, consistency, stages), `config/data_sources.json` (User-Agent), `prompts/call1_{system,user}.v{1,2}.txt`, `.gitattributes`.
**New scripts:** `scripts/s06_probe_native_detail.py`, `s06_record_osm.py`, `s06_osm_second_source.py`, `s06_model_comparison.py`; changed: `s06_call1_check.py` (default profile, `--prompt-version`, ta_situation), `s06_accuracy_report.py`, `s06_measure_report.py`.
**Reports and templates:** `docs/reports/S6_stop5_fusion_rules.md`, `S6_stop6_enhanced_prompt.md`, `S6_stop6_prompt_diff.txt`, `S6_calibration_values.md`, `S6_model_comparison.md`, `S6_claude_nine_calls_measurements.md`, `docs/references/S6_outcomes.md`, templates with `ta_situation`.
**Fixtures:** `tests/fixtures/site/bearing/marks_nine_and_nine.json` (marks of the owner's nine and nine calls).
Not committed on purpose: the untracked folder `docs/references/extra_do_not_use_it/` (it is in your working tree, not mine; one commit swept it in by mistake and was redone before any push).

## 3. Tests added, and results

New test files (count): test_prompt_registry 11, test_outcomes 14, test_osm 34, test_bearing_check 29, test_edge_rule 17, test_confidence_floors 8, test_site_exceptions 49,
test_answer_records 11, test_fusion_apply 20, test_review_r2_r3_r4 13, test_snap 13, test_call1_v2 22, test_code_checks 20, test_consistency 13, test_understanding 24,
test_no_ta_ids 3, test_calibration_in_config 6, test_owner_scripts_osm_probe 12, test_model_comparison 3; extended: test_call1_check_script, test_call1_sites, test_accuracy_report, test_sources.

**Full suite, run once before the push: 1645 passed, 12 skipped in 7 min 32 s (`pytest tests`, the .venv, no live calls)**

The old path is proved unchanged by: `tests/unit/site/test_old_call_body_unchanged.py` (the old `tcp_observation` body is byte-identical to the recorded one), the global-identity and baseline guard tests (`tests/integration/review_assistant/test_global_identity.py`, `test_phase3_decisions.py`, `tests/unit/test_guard_baseline_ref.py`: no protected file differs from the baseline), the replay of the recorded Rhode Island fixtures in the integration suite, and `test_understanding.py::test_the_old_path_and_this_module_do_not_import_each_other`.
The gate test: `test_understanding.py::test_a_result_using_an_ai_only_unconfirmed_fact_is_review_required_and_names_it`.
The no-TA-id test: `tests/unit/site/test_no_ta_ids.py`.

## Fusion rule table (all 18 call 1 fields)

Columns: sources used, floor kind, then what produces each outcome, then flags.

| Field | Sources | Floor | FOUND | NOT_PRESENT | UNKNOWN (reason codes) | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| work_location | AI, then three code checks that can only lower it: marks check, edge rule (5 m), bearing check. No OSM. | work_location (0.85) | AI ROADWAY, SHOULDER or BEYOND_SHOULDER at or above the floor, marks agree, point more than 5 m from the nearest road edge. Mapped to IN_LANE, ON_SHOULDER_OR_ENCROACHING, BEYOND_SHOULDER. | not applicable | below floor (`low_confidence`); AI says SIDEWALK (`no_registry_value`, observation kept as candidate); marks disagree (`source_disagreement` plus WORK_LOCATION_CONFLICT question); within 5 m of an edge (`near_edge` plus WORK_LOCATION_NEAR_EDGE question); no road near (`no_road_near` plus the same question) | AI_ONLY_UNCONFIRMED when the marks are missing (result is REVIEW_REQUIRED naming the fact); CALIBRATION_PENDING on edge-rule results |
| work_side | AI | common (none) | compass side N, S, E or W | not applicable | `not_visible`, `ambiguous`, `malformed`, `low_confidence` | CONTEXT_ONLY (no registry id; LEFT/RIGHT stays an SME question) |
| lanes_per_direction | AI and OSM (`lanes:forward` with `lanes:backward`, else `lanes` / 2 when even and two-way; one-way: its lanes) | safety_critical (none) | AI and OSM equal | not applicable | disagree (`source_disagreement` plus LANES_DISAGREE question, both values shown); OSM gives nothing: no tag (`no_tag`), odd total or forward differs from backward (`ambiguous` plus LANES_UNSPLIT question); AI unknown | NEEDS_SECOND_SOURCE until OSM agrees; MEDIUM class when it does |
| oneway | AI and OSM `oneway` tag (a MISSING tag counts as not one-way at lower confidence; the AI must also say false) | safety_critical (none) | AI and OSM equal (a stated tag counts fully; a missing tag counts only for AI false, class LOW, and the FOUND value then carries OSM_TAG_ASSUMED) | not applicable (a two-way road is FOUND false) | stated tag contradicts the AI (`source_disagreement`); missing tag and AI true (`single_source`); reversible or unreadable tag (`ambiguous`) | NEEDS_SECOND_SOURCE until agreed; OSM_TAG_ASSUMED when the agreement rests on a missing tag (any result using it is REVIEW_REQUIRED naming the fact) |
| shoulder_present | AI and OSM `shoulder` or `shoulder:left/right/both` | safety_critical (none) | both say there is one | both say none (AI false and OSM tag no or none) | disagree; OSM has no shoulder tag (`no_tag`, no information) so the AI stands alone; AI unknown | NEEDS_SECOND_SOURCE until agreed |
| divided_highway | AI and OSM geometry (an opposite-direction, parallel, one-way way of the same name or ref within 60 m, 20 degrees) | safety_critical (none) | AI true and OSM finds the opposite carriageway | AI false and OSM chosen way is two-way (no separate carriageway) | OSM chosen way is one-way and no opposite found (`ambiguous`: the other side may be unmapped); disagree | NEEDS_SECOND_SOURCE until agreed; CALIBRATION_PENDING (60 m, 20 degrees) |
| median_work | AI | common (none) | true or false | not applicable (false means the work is not in a median) | `not_visible`, `ambiguous`, `low_confidence` | AI_ONLY_UNCONFIRMED (REVIEW_REQUIRED naming the fact when it reaches a rule input; no new floor) |
| bicycle_lane_present | AI | common (none) | true | false (none seen) | `not_visible`, `occluded`, `low_resolution`, `ambiguous` | AI_ONLY_UNCONFIRMED (as median_work) |
| sidewalk_present | AI; OSM `sidewalk` tags read as a cross-check only | common (none) | true | false (OSM none or no, or AI false) | `not_visible`, `occluded`, `ambiguous` | CONTEXT_ONLY; an OSM disagreement is recorded in the fusion record and lowers the class to LOW, nothing more |
| sidewalk_side | AI | common (none) | N, S, E, W or BOTH | value NONE | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| parking_present | AI | common (none) | true | false | `not_visible`, `occluded`, `low_resolution` | CONTEXT_ONLY; read as a measurement gate for lane width only (lane width stays UNKNOWN when parking or shoulder is not read false) |
| bus_stop_present | AI (GTFS comes in session 2) | common (none) | true | false | `not_visible`, `occluded` | CONTEXT_ONLY |
| driveway_present | AI | common (none) | true | false | `not_visible`, `occluded` | CONTEXT_ONLY |
| crosswalk_present | AI | common (none) | true | false | `not_visible`, `occluded`, `low_resolution` | CONTEXT_ONLY |
| intersection_in_view | AI | common (none) | true | false | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| grade_crossing_present | AI (FRA inventory comes in session 2) | common (none) | true | false | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| obstructions | AI (free text, stored whole, never parsed for numbers) | common (none) | short text | value NONE | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| approaching_lanes_one | AI | common (none) | true or false | not applicable | `not_visible`, `ambiguous`, `low_confidence` | AI_ONLY_UNCONFIRMED (as median_work); see the approaching-lanes consistency check |

Widths (lane, shoulder, median, distance from edge) are code measurements from marks (D-64), not call 1 facts. They come out FOUND with an interval, or UNKNOWN (`no_source`, `missing`, `malformed`, `ambiguous`, `threshold_in_interval`). A bearing failure (MISMATCH or WHICH_ROAD) blocks the 12 road-specific call 1 facts AND every width: they become UNKNOWN (`wrong_road_suspected`), the AI values stay as candidates, and one WHICH_ROAD question is raised. The BEARING_MISMATCH question kind and the reason `check_failed` for this case are gone.

Every outcome row also carries the source, evidence text, the AI confidence number, the candidates compared, and the fusion record (AGREE, DISAGREE, SINGLE_SOURCE or UNDECIDABLE). A data source never fills a start field.

## Consistency checks

Each check returns evidence, can only lower confidence or give UNKNOWN, and is never a second source. Values come from config, tagged CALIBRATION_PENDING. Each has an off switch (step 10).

| # | Check | Compares | Effect | Built |
| --- | --- | --- | --- | --- |
| 1 | Bearing | road direction of the AI marks (code, mod 180) with the OSM reference way chosen by the work point, 30 degrees; a mismatch also when the marks match a different way than the chosen one | the 12 road-specific facts and every width become UNKNOWN (`wrong_road_suspected`), AI values kept as candidates, plus one WHICH_ROAD question | yes, commit 4, reworked (R1) |
| 2 | Which road? | the OSM reference way is chosen by the work point, never by the marks: the nearest way (service excluded, within 25 m) is used only if it is at least `bearing.nearest_margin_m` (8 m, CALIBRATION_PENDING) nearer than the next road that runs a different way (bearing differs by more than 30 degrees) | otherwise one WHICH_ROAD question, whatever the marks say; the 12 road-specific facts and widths wait. A cross street traced by the AI at a corner (US-1 and Cross St at Granite P32) fails as a mismatch and does not pass on two agreeing sources | yes, reworked (R1) |
| 3 | Edge rule | work point to nearest road edge, 5 m; no road near | work_location UNKNOWN plus one question | yes, commit 5 |
| 4 | Marks check | work_location against the work point and the edge marks | agree: plain; missing: AI_ONLY_UNCONFIRMED; disagree: UNKNOWN plus question | yes (S6 session 1 earlier) |
| 5 | Lane width gate | parking and shoulder both read false before a traveled way is divided by lanes | else lane width UNKNOWN plus a hint-only question | yes |
| 6 | Straddle test | width interval against the pack's own limits | UNKNOWN plus WIDTH_NEAR_THRESHOLD question | yes |
| 7 | Start-field conflict | remaining-width table against the SME's lane closure entry | START_FIELD_CONFLICT question; the SME value never changes | yes |
| 8 | Lane count against width | traveled way width divided by total lanes against the plausible lane width range (`pipeline_config` fusion.lane_width_plausible_m). Runs ONLY when parking and shoulder are both read false (otherwise the edges include parking or a shoulder and the division means nothing) | a width outside the range lowers lanes_per_direction and the width to UNKNOWN plus LANES_DISAGREE question | step 9 (R5) |
| 9 | Lane lines | number of detected painted lane lines (code) against lanes_per_direction | a mismatch lowers the lane count confidence; never raises it. When NO painted lines are detected the check does nothing (unpainted roads and worn paint are not evidence against a count) | step 9 (R5) |
| 10 | Shadow and tree cover | share of the road and edge strips covered by shadow or canopy (code) | above the configured share, edges, shoulder, parking and widths are lowered to UNKNOWN (`occluded`) | step 9 |
| 11 | Image to OSM offset | distance between the OSM centreline and the road centre seen in the marks | above the configured offset the OSM candidate is LOW and cannot confirm an AI value | step 9 |
| 12 | Approaching lanes | approaching_lanes_one against lanes_per_direction | a contradiction (true with more than one lane, false with one) lowers both to UNKNOWN plus question | step 9 |
| 13 | Sidewalk pair | sidewalk_present against sidewalk_side (false with a side named, true with NONE) | both UNKNOWN | step 9 |
| 14 | Snapping | each mark to the nearest real edge in the image (code); a mark with no edge nearby is rejected | rejected mark gives no width | step 8 |

## 4. The two comparison tables (nine calls each, prompt version 1; no winner is picked)

Stand-in OSM bearings are used for the bearing verdicts (E Second St 90 degrees, Colorado 37 degrees); they are not recorded OSM data.

## gpt-5.6-sol

| call | site | rep | seconds | tokens in/out | schema valid | UNKNOWN facts | lanes per dir (conf.) | oneway | shoulder | parking | work location | mark bearing | bearing vs stand-in | traveled way ft | per lane m (plausible) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | granite | 1 | 90.3 | 1256/8073 | True | 1 | 2 (0.78) | False | False | False | ROADWAY | 176 | no stand-in | 90.9 | 6.93 (NO) |
| 2 | granite | 2 | 57.3 | 1256/5037 | True | 2 | 1 (0.92) | False | False | None | ROADWAY | 175 | no stand-in | 91.8 | 13.99 (NO) |
| 3 | granite | 3 | 78.3 | 1256/6788 | True | 1 | 2 (0.78) | False | False | False | ROADWAY | 176 | no stand-in | 82.2 | 6.26 (NO) |
| 4 | second | 1 | 77.6 | 1256/6917 | True | 2 | 1 (0.76) | None | False | True | BEYOND_SHOULDER | 0 | WRONG ROAD SUSPECTED | 35.8 | - |
| 5 | second | 2 | 57.1 | 1256/5061 | True | 2 | 1 (0.78) | None | False | True | SIDEWALK | 90 | agrees | 37.3 | - |
| 6 | second | 3 | 68.0 | 1256/6566 | True | 2 | 1 (0.84) | None | False | True | BEYOND_SHOULDER | 91 | agrees | 34.8 | - |
| 7 | colorado | 1 | 91.1 | 1256/7756 | True | 3 | 1 (0.82) | False | False | True | BEYOND_SHOULDER | 28 | agrees | 25.2 | 3.84 (yes) |
| 8 | colorado | 2 | 82.0 | 1256/7283 | True | 3 | 1 (0.7) | None | False | None | BEYOND_SHOULDER | 140 | WRONG ROAD SUSPECTED | 28.5 | - |
| 9 | colorado | 3 | 85.1 | 1256/6938 | True | 1 | 1 (0.88) | False | False | True | BEYOND_SHOULDER | 41 | agrees | 30.8 | 4.70 (yes) |

## claude-opus-5-5

| call | site | rep | seconds | tokens in/out | schema valid | UNKNOWN facts | lanes per dir (conf.) | oneway | shoulder | parking | work location | mark bearing | bearing vs stand-in | traveled way ft | per lane m (plausible) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | granite | 1 | 26.2 | 3508/2096 | True | 3 | 1 (0.5) | False | None | False | ROADWAY | 173 | no stand-in | 46.9 | 7.14 (NO) |
| 2 | granite | 2 | 21.9 | 3508/2045 | True | 4 | 1 (0.45) | False | None | False | ROADWAY | 173 | no stand-in | 51.4 | 7.83 (NO) |
| 3 | granite | 3 | 21.7 | 3508/2159 | True | 2 | 2 (0.45) | False | False | False | ROADWAY | 171 | no stand-in | 33.2 | 2.53 (yes) |
| 4 | second | 1 | 17.5 | 3508/1799 | True | 3 | 1 (0.6) | None | False | True | SIDEWALK | 90 | agrees | 24.6 | - |
| 5 | second | 2 | 19.2 | 3508/1865 | True | 3 | 1 (0.6) | None | False | True | SIDEWALK | 90 | agrees | 27.1 | - |
| 6 | second | 3 | 17.3 | 3508/1720 | True | 4 | 1 (0.55) | None | False | True | BEYOND_SHOULDER | 90 | agrees | 24.6 | - |
| 7 | colorado | 1 | 31.2 | 3508/2874 | True | 3 | 1 (0.7) | False | False | True | BEYOND_SHOULDER | 36 | agrees | 29.0 | 4.42 (yes) |
| 8 | colorado | 2 | 23.4 | 3508/2035 | True | 4 | 1 (0.7) | False | False | None | BEYOND_SHOULDER | 39 | agrees | 38.4 | 5.86 (NO) |
| 9 | colorado | 3 | 25.2 | 3508/2294 | True | 6 | 1 (0.7) | False | None | None | BEYOND_SHOULDER | 39 | agrees | 35.0 | 5.33 (yes) |

## Side by side per site (the three repetitions)

| site | profile | mark bearings | wrong-road suspected | traveled way ft | lanes per direction (conf.) | per-lane width plausible |
| --- | --- | --- | --- | --- | --- | --- |
| granite | gpt-5.6-sol | 176, 175, 176 | 0 of 3 | 90.9, 91.8, 82.2 | 2@0.78, 1@0.92, 2@0.78 | 0 of 3 judged |
| granite | claude-opus-5-5 | 173, 173, 171 | 0 of 3 | 46.9, 51.4, 33.2 | 1@0.5, 1@0.45, 2@0.45 | 1 of 3 judged |
| second | gpt-5.6-sol | 0, 90, 91 | 1 of 3 | 35.8, 37.3, 34.8 | 1@0.76, 1@0.78, 1@0.84 | 0 of 0 judged |
| second | claude-opus-5-5 | 90, 90, 90 | 0 of 3 | 24.6, 27.1, 24.6 | 1@0.6, 1@0.6, 1@0.55 | 0 of 0 judged |
| colorado | gpt-5.6-sol | 28, 140, 41 | 1 of 3 | 25.2, 28.5, 30.8 | 1@0.82, 1@0.7, 1@0.88 | 2 of 2 judged |
| colorado | claude-opus-5-5 | 36, 39, 39 | 0 of 3 | 29.0, 38.4, 35.0 | 1@0.7, 1@0.7, 1@0.7 | 2 of 3 judged |

## Totals

| profile | calls | schema valid | wrong-road suspected | mean seconds | mean output tokens |
| --- | --- | --- | --- | --- | --- |
| gpt-5.6-sol | 9 | 9 | 2 | 76.3 | 6713 |
| claude-opus-5-5 | 9 | 9 | 0 | 22.6 | 2099 |

Full file: `docs/reports/S6_model_comparison.md` (`python scripts/s06_model_comparison.py --out docs/reports/S6_model_comparison.md` regenerates it). Measurement tables: `S6_gpt_nine_calls_measurements.md`, `S6_claude_nine_calls_measurements.md`.

## 5. Owner commands (PowerShell; `TCP_LIVE=1` for anything that calls out)

```powershell
# the version 2 prompt: look first, then run (the first gpt call is the real strict-mode test)
python scripts/s06_call1_check.py --dry-run --only 1 --prompt-version 2
$env:TCP_LIVE = "1"
python scripts/s06_call1_check.py --profile gpt-5.6-sol --prompt-version 2 --only 1
python scripts/s06_call1_check.py --profile gpt-5.6-sol --prompt-version 2 --parallel 3
python scripts/s06_call1_check.py --profile claude-opus-5-5 --prompt-version 2 --parallel 3
# version 1 in parallel (D-104)
python scripts/s06_call1_check.py --profile gpt-5.6-sol --parallel 3
# zoom-19 native detail in Massachusetts: two requests (E Second MH 223 and Colorado P13)
python scripts/s06_probe_native_detail.py --dry-run
python scripts/s06_probe_native_detail.py
# the early check on your sites file (site_id, lat, lon, extent_m, ta_situation): call 1 on every site, three repetitions
python scripts/s06_call1_check.py --profile gpt-5.6-sol --sites sites.csv --reps 3 --parallel 3
# record the OpenStreetMap fixtures (one bounded Overpass query per site; skips what is recorded)
python scripts/s06_record_osm.py --sites sites.csv --dry-run
python scripts/s06_record_osm.py --sites sites.csv
# ONE COMMAND: recorded OSM fixtures to the --second-source CSV
python scripts/s06_osm_second_source.py --sites sites.csv --out second_source.csv
# accuracy report against your truth csv, with OSM as the second source
python scripts/s06_accuracy_report.py --results var/s06_call1_check/gpt-5.6-sol var/s06_call1_check/claude-opus-5-5 --truth truth.csv --second-source second_source.csv --out docs/reports/S6_accuracy.md
```

Notes: version 2 results go to `var/s06_call1_check_v2/<profile>/`; run the accuracy report on that folder separately (it names a profile by its folder name). If the gpt deployment rejects the version 2 schema in strict mode the script stops at the first error and prints the HTTP status and the error body; nothing is worked around.

## 6. Open items from earlier, answered

- **Azure Maps requests per zone run:** one wide-image request; the close view adds 0 when the wide image is sufficient, 1 when it is not, and 1 (recorded as unavailable) when it fails. A view stored under the same signature is reused with zero requests. `understand_site` does not call the close view (call 2 is S7).
- **`--parallel` (D-104):** `python scripts/s06_call1_check.py --profile gpt-5.6-sol --parallel 3`.
- **Recordings** (Colorado after S7, the rest after S9, owner-run with `TCP_LIVE=1`) stay deferred: the recorder must first be project and zone aware (original commit 13, session 2), and Colorado needs calls 1 and 2 together, which exist only after S7.
- **Bearing cross-check:** built (step 4), tested with the three E Second St and three Colorado marks.
- **Massachusetts zoom-19 detail:** the information-only flag is ported; `s06_probe_native_detail.py` measures it with two requests.

## 7. What I could not do

- No live run of any kind. So: prompt version 2 is untested against the real strict-mode endpoint; snapping, lane-line, shadow and canopy checks are tested on synthetic images only; the real-image behaviour of every CALIBRATION_PENDING value is unknown.
- No recorded OSM data exists yet. The OSM rules are tested on synthetic ways; the bearing tests use stand-in bearings (clearly marked in the fixture).
- No truth CSV for any site, so there is no accuracy number yet (the report tool and templates are ready).
- No confidence floor was set for any profile (nothing is calibrated), and the second-source rule will leave many shoulder and lane facts UNKNOWN plus a question candidate where OSM carries no tag.
- The site-exceptions role dropdown has no UI (the file and loader are done; the UI is S10). The question log store is not built (by decision); answer records keep what a later log needs.
- Call 2, the close-view fetch inside a run, the S7 router and the state data sources are out of scope and untouched.

## 8. Contradictions with the plan

1. The plan asked the AI for the "distance of the point to the pavement edge". CLAUDE.md rule 1 and D-64 forbid the AI returning a length. Implemented as `nearest_edge_point` (a pixel position); code computes the distance.
2. "No TA id in code you add": `site_model/precalc.py` (STOP 3, earlier) names TA-1, TA-6 and TA-33 in note texts and one label constant. It is not changed and is listed in `test_no_ta_ids.py` as pre-dating the rule, with the old `fusion.py`. Say if you want precalc cleaned.
3. The User-Agent now carries no contact, as decided. Overpass asks clients to be identifiable; if the public host throttles or blocks the recorder, a contact string is the first thing to add (`config/data_sources.json`).

## 9. Open questions

1. `enhanced_prompt` is off by default (version 1 stays the default until the version 2 live calls are read). Say when to switch it on.
2. After the early check on 8 sites: which TA situations go in `ta_situation`, and who writes the truth CSV (the report needs one).
3. Should a question candidate for a safety field become blocking in S7's what-if test only, or also when the field is unknown for a zone whose TA is already `NO_TA_MATCH`? (My reading: only when it decides the TA.)
4. Cleaning `precalc.py` of TA ids (contradiction 2).
