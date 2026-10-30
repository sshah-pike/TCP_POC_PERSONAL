# S6 STOP 5: fusion rule table and consistency checks

Status: **proposal for owner review**. Steps 0 to 6 are built and tested; the fusion rules below are what steps 8 to 11 will implement once approved. Nothing here changes a rule-pack value, a start field or a TA decision.

## Vocabulary

| Term | Meaning |
| --- | --- |
| Outcome | FOUND (source looked, thing there or a value), NOT_PRESENT (source looked, nothing there; presence fields only), UNKNOWN (could not determine; a reason code says why). Per-field meaning: `docs/references/S6_outcomes.md`. |
| Confidence class | HIGH only SME or UI. MEDIUM a data source that agrees with the imagery. LOW everything else. The AI's own number is kept as a number and compared with the floor. |
| Floor | `confidence_floors` in `config/site_understanding.json`: default entry plus optional per-profile entries. Kinds: work_location 0.85, safety_critical none (CALIBRATION_PENDING), common none (CALIBRATION_PENDING). A reading below its floor is UNKNOWN (`low_confidence`). |
| Two-source rule | For lanes per direction, divided, shoulder and one-way the AI and OSM must agree. Two AI calls or crops never count as two. |
| Registry id | A fact with a registry id can become a rule input. A fact without one is CONTEXT_ONLY: the SME sees it, no rule reads it. |

## Fusion rule table (all 18 call 1 fields)

Columns: sources used, floor kind, then what produces each outcome, then flags.

| Field | Sources | Floor | FOUND | NOT_PRESENT | UNKNOWN (reason codes) | Flags |
| --- | --- | --- | --- | --- | --- | --- |
| work_location | AI, then three code checks that can only lower it: marks check, edge rule (5 m), bearing check. No OSM. | work_location (0.85) | AI ROADWAY, SHOULDER or BEYOND_SHOULDER at or above the floor, marks agree, point more than 5 m from the nearest road edge. Mapped to IN_LANE, ON_SHOULDER_OR_ENCROACHING, BEYOND_SHOULDER. | not applicable | below floor (`low_confidence`); AI says SIDEWALK (`no_registry_value`, observation kept as candidate); marks disagree (`source_disagreement` plus WORK_LOCATION_CONFLICT question); within 5 m of an edge (`near_edge` plus WORK_LOCATION_NEAR_EDGE question); no road near (`no_road_near` plus the same question) | AI_ONLY_UNCONFIRMED when the marks are missing (result is REVIEW_REQUIRED naming the fact); CALIBRATION_PENDING on edge-rule results |
| work_side | AI | common (none) | compass side N, S, E or W | not applicable | `not_visible`, `ambiguous`, `malformed`, `low_confidence` | CONTEXT_ONLY (no registry id; LEFT/RIGHT stays an SME question) |
| lanes_per_direction | AI and OSM (`lanes:forward` with `lanes:backward`, else `lanes` / 2 when even and two-way; one-way: its lanes) | safety_critical (none) | AI and OSM equal | not applicable | disagree (`source_disagreement` plus LANES_DISAGREE question, both values shown); OSM gives nothing: no tag (`no_tag`), odd total or forward differs from backward (`ambiguous` plus LANES_UNSPLIT question); AI unknown | NEEDS_SECOND_SOURCE until OSM agrees; MEDIUM class when it does |
| oneway | AI and OSM `oneway` tag (a MISSING tag counts as not one-way at lower confidence; the AI must also say false) | safety_critical (none) | AI and OSM equal (a stated tag counts fully; a missing tag counts only for AI false, class LOW) | not applicable (a two-way road is FOUND false) | stated tag contradicts the AI (`source_disagreement`); missing tag and AI true (`single_source`); reversible or unreadable tag (`ambiguous`) | NEEDS_SECOND_SOURCE until agreed |
| shoulder_present | AI and OSM `shoulder` or `shoulder:left/right/both` | safety_critical (none) | both say there is one | both say none (AI false and OSM tag no or none) | disagree; OSM has no shoulder tag (`no_tag`, no information) so the AI stands alone; AI unknown | NEEDS_SECOND_SOURCE until agreed |
| divided_highway | AI and OSM geometry (an opposite-direction, parallel, one-way way of the same name or ref within 60 m, 20 degrees) | safety_critical (none) | AI true and OSM finds the opposite carriageway | AI false and OSM chosen way is two-way (no separate carriageway) | OSM chosen way is one-way and no opposite found (`ambiguous`: the other side may be unmapped); disagree | NEEDS_SECOND_SOURCE until agreed; CALIBRATION_PENDING (60 m, 20 degrees) |
| median_work | AI | common (none) | true or false | not applicable (false means the work is not in a median) | `not_visible`, `ambiguous`, `low_confidence` | none |
| bicycle_lane_present | AI | common (none) | true | false (none seen) | `not_visible`, `occluded`, `low_resolution`, `ambiguous` | none |
| sidewalk_present | AI; OSM `sidewalk` tags read as a cross-check only | common (none) | true | false (OSM none or no, or AI false) | `not_visible`, `occluded`, `ambiguous` | CONTEXT_ONLY; an OSM disagreement is recorded in the fusion record and lowers the class to LOW, nothing more |
| sidewalk_side | AI | common (none) | N, S, E, W or BOTH | value NONE | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| parking_present | AI | common (none) | true | false | `not_visible`, `occluded`, `low_resolution` | CONTEXT_ONLY; read as a measurement gate for lane width only (lane width stays UNKNOWN when parking or shoulder is not read false) |
| bus_stop_present | AI (GTFS comes in session 2) | common (none) | true | false | `not_visible`, `occluded` | CONTEXT_ONLY |
| driveway_present | AI | common (none) | true | false | `not_visible`, `occluded` | CONTEXT_ONLY |
| crosswalk_present | AI | common (none) | true | false | `not_visible`, `occluded`, `low_resolution` | CONTEXT_ONLY |
| intersection_in_view | AI | common (none) | true | false | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| grade_crossing_present | AI (FRA inventory comes in session 2) | common (none) | true | false | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| obstructions | AI (free text, stored whole, never parsed for numbers) | common (none) | short text | value NONE | `not_visible`, `ambiguous` | CONTEXT_ONLY |
| approaching_lanes_one | AI | common (none) | true or false | not applicable | `not_visible`, `ambiguous`, `low_confidence` | none; see the lane-count consistency check |

Widths (lane, shoulder, median, distance from edge) are code measurements from marks (D-64), not call 1 facts. They come out FOUND with an interval, or UNKNOWN (`no_source`, `missing`, `malformed`, `ambiguous`, `threshold_in_interval`, `check_failed`), and are blocked to UNKNOWN (`check_failed`) when the bearing check fails.

Every outcome row also carries the source, evidence text, the AI confidence number, the candidates compared, and the fusion record (AGREE, DISAGREE, SINGLE_SOURCE or UNDECIDABLE). A data source never fills a start field.

## Consistency checks

Each check returns evidence, can only lower confidence or give UNKNOWN, and is never a second source. Values come from config, tagged CALIBRATION_PENDING. Each has an off switch (step 10).

| # | Check | Compares | Effect | Built |
| --- | --- | --- | --- | --- |
| 1 | Bearing | road direction of the AI marks (code, mod 180) with the nearest OSM way, 30 degrees | all widths UNKNOWN (`check_failed`) plus BEARING_MISMATCH question | yes, commit 4 |
| 2 | Which road? | several OSM ways (service excluded) within 25 m whose bearings differ by more than 30 degrees | marks decide only when exactly one candidate matches, else WHICH_ROAD question and widths wait | yes, commit 4 |
| 3 | Edge rule | work point to nearest road edge, 5 m; no road near | work_location UNKNOWN plus one question | yes, commit 5 |
| 4 | Marks check | work_location against the work point and the edge marks | agree: plain; missing: AI_ONLY_UNCONFIRMED; disagree: UNKNOWN plus question | yes (S6 session 1 earlier) |
| 5 | Lane width gate | parking and shoulder both read false before a traveled way is divided by lanes | else lane width UNKNOWN plus a hint-only question | yes |
| 6 | Straddle test | width interval against the pack's own limits | UNKNOWN plus WIDTH_NEAR_THRESHOLD question | yes |
| 7 | Start-field conflict | remaining-width table against the SME's lane closure entry | START_FIELD_CONFLICT question; the SME value never changes | yes |
| 8 | Lane count against width | traveled way width divided by total lanes against the plausible lane width range (`pipeline_config` fusion.lane_width_plausible_m) | a width outside the range lowers lanes_per_direction and the width to UNKNOWN plus LANES_DISAGREE question | step 9 |
| 9 | Lane lines | number of detected lane lines (code) against lanes_per_direction | a mismatch lowers the lane count confidence; never raises it | step 9 |
| 10 | Shadow and tree cover | share of the road and edge strips covered by shadow or canopy (code) | above the configured share, edges, shoulder, parking and widths are lowered to UNKNOWN (`occluded`) | step 9 |
| 11 | Image to OSM offset | distance between the OSM centreline and the road centre seen in the marks | above the configured offset the OSM candidate is LOW and cannot confirm an AI value | step 9 |
| 12 | Approaching lanes | approaching_lanes_one against lanes_per_direction | a contradiction (true with more than one lane, false with one) lowers both to UNKNOWN plus question | step 9 |
| 13 | Sidewalk pair | sidewalk_present against sidewalk_side (false with a side named, true with NONE) | both UNKNOWN | step 9 |
| 14 | Snapping | each mark to the nearest real edge in the image (code); a mark with no edge nearby is rejected | rejected mark gives no width | step 8 |

## Owner answers (2026-10-31, provisional until the owner has read this file) and what was built

1. **Single source on a safety-critical field:** the fact is UNKNOWN (`single_source`). The AI value stays visible and pre-filled as a candidate. One question CANDIDATE is emitted (`Question.candidate = True`, `suggested` = the AI value): it is not blocking, and S7's what-if test makes it blocking only when the fact decides the TA. A code pixel check is never a second source: a reading whose source is not an enabled data source (the imagery provider excluded) is refused. Built in `site_model/fusion_apply.py`, tested in `test_fusion_apply.py`. A disagreement is UNKNOWN (`source_disagreement`) with both values kept as candidates, also as a question candidate.
2. **Bearing failure (MISMATCH or WHICH_ROAD):** every road-specific fact becomes UNKNOWN with reason `wrong_road_suspected`, the AI values stay as candidates, plus one "which road?" question (kind WHICH_ROAD; the separate BEARING_MISMATCH kind is gone). Built in `site_model/bearing_check.py` (`ROAD_SPECIFIC`, `SCENE`, `block_road_specific`), tested with E Second call 4 (0 degrees) and Colorado call 8 (140 degrees).
   - **Road-specific (12 of the 18, plus every width measured from marks):** work_location (judged against the edges and lane lines of the marked road), work_side (side of the marked road), lanes_per_direction, oneway, shoulder_present, divided_highway, median_work, bicycle_lane_present, sidewalk_present, sidewalk_side, parking_present, approaching_lanes_one (all properties of, or next to, the one road the marks followed).
   - **Scene facts (6, unchanged):** bus_stop_present, driveway_present, crosswalk_present, intersection_in_view, grade_crossing_present, obstructions (seen at the work location or in the image, not a property of one road).
3. **sidewalk_present against OSM:** record only. The OSM reading is added as a candidate (class LOW on disagreement, MEDIUM on agreement); the fact and its value do not change; no question.
