Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

## Owner decisions applied (2026-10-30)

- B-1: the anchor reading (A, B, C are consecutive gaps ending at the taper start for TA-6 and TA-33, or at the flagger station for TA-10) is accepted, with SME confirmation; it comes from S4b. B-2: the SME states W per taper type; asked per zone until then.
- B-3: buffer is a per-zone choice, default none. B-4: taper length in the 50 to 100 ft range is a per-zone choice; unset places no taper and reports a gap. B-5 A (optional devices omitted and listed). B-6: unknown work-space length gives a provisional POINT_ONLY layout marked REVIEW_REQUIRED. B-7 B (both TA-1 approaches, flagged as a reading of 6P.01 para 07). B-8 A (TA-33 downstream gap and a question). B-9 A (POC values in config, labelled). B-10 B (upper end of the width interval). B-11 A. B-15 A.
- B-12: sidewalk-closed and detour add-ons are built here from the S4b sections, optional per zone. No-parking and RI double fines wait for sources. Client modules and police are out of scope. B-13: spacing satisfies both limits (the smaller). B-14: cutover with reviewed oracles; the POC output renames happen in the same commit.
- The vehicle width default is 102 in, flagged; depth and clearance are asked per job. The 10 ft next to the work vehicle on the drafts is an SME question; make no assumption.

## Owner decisions applied (2026-10-31)

Register: `docs/decisions/OWNER_DECISIONS_2026-10-31.md`. Where this block differs from older text, this block is the active text; the older wording is kept in the "Amendments 2026-10-31" notes in section 4 and section 5. Future items are in `docs/FUTURE_SCOPE.md`.

- **TA-33 anchor (S4b, pack 1.1.0; D-107).** The TA-33 anchor text of sections 4.2 and 4.3 is superseded by the corrected reading in pack 1.1.0 (record `SR-6P33-FIG-SIGNS`): dimension A is measured from the upstream end of the merging taper (the start of L), and the shoulder taper lies inside A and ends where the merging taper begins. The owner's note reads "A ends where the merging taper begins"; both place the anchor at the start of the merging taper. The old reading (A from the upstream end of the shoulder taper) was wrong against the figure render.
- **Add-on device rows and real symbols come before the add-on commit (D-110, D-117).** Sidewalk and detour signs have catalog entries, sizes and placeholder symbols but no device rows yet. Device rows are added just before the add-on commit (commit 9 below), and the symbols are drawn for real before that commit; M4-9a must show its arrow (FS-15; Sect. 6I.02 para 11 requires it). The device-row addition is a pack change, so it is a new sealed pack version approved by the owner (D-144) and run through `scripts/seal_rule_pack_version.py`.
- **No layout for an UNDETERMINED zone.** If the final router pass leaves the zone UNDETERMINED or in `TA_SELECTION_CONFLICT`, S8 places nothing and returns the open questions. Layout runs only for a zone with a chosen TA (from owner conversation 2026-10-31; D-119 puts the SME after fusion and call 2).
- **Accuracy gate.** S8 starts after the accuracy gate between S7 and S8 (D-125, D-153). The pack store is merged (commit `69ab4c0`), so a layout recorded against a pack hash replays without a git checkout.
- Every trace also carries the device catalog hash next to the pack hash (S5 report, open question 5).

# S8 plan: layout engine per TA and add-on modules

Planning only. Branch when built: `tcp-mvp/s08-layout`, off `tcp-mvp/s07-router`. Written on `tmp/plan-base2` (S2 + S4 merged). Nothing here is approved until the owner says so (CLAUDE.md, "How to work", rule 2).

Read for this plan: CLAUDE.md; slice specs S5 to S8; plan sections 4A, 4B, 4C, 5, 6, 7, 10, 10A, 14; D-24, D-47, D-49, D-60, D-64, D-68, D-80, D-81; `S0_repo_report.md` (items 1, 6, 16, 20, 26); `S4_rule_pack_review.md`; `rule_pack/` (all parts); `rules/rule_pack_effective.py`, `rule_pack_eval.py`; `layout/rule_engine.py` and `geometry/local_frame.py` (the TA-1 POC engine); `tests/golden/*`; the four figure renders (6P-1, 6P-6, 6P-10, 6P-33); the S3 commit messages (via `git show`). The companion plan is `docs/plans/S7_plan.md`.

Rules come from the MUTCD only (S4 owner decision). The Colorado, E Second St and Granite drafts are comparison material, never a source. The client, jurisdiction and deviation layers are empty in v1.

Legend: **[B]** can be batched. **[STOP]** stop for owner review. **ASSUMPTION A-n** is a shape I rely on from S3, S5, S6, S7 or S10 and could not verify; each is repeated under "What could go stale if S6 changes".

---

## 1. Scope and acceptance criteria

### In scope

1. **One common placement core** and **four TA strategies** (TA-1, TA-6, TA-10, TA-33). A strategy emits station-relative placement requests from the pack; the core turns them into road coordinates. This keeps the existing two-stage pattern (`rule_engine` emits requests, `local_frame.place_objects` places them) and removes the TA-1 literals (`ta1_template`, `rule_engine.execute`, `validators.py:61`, `eligibility.py:140-156`, `findings.py:218`) after the cutover (question B-14).
2. **Advance signs** from Table 6B-1 A, B and C, on each approach the figure shows (section 4.3).
3. **Tapers** (Tables 6B-3 and 6B-4), **buffers** (Table 6B-2, Option), **channelizer spacing** (Sect. 6K.01 para 04 and Sect. 6B.08 paras 12 and 14), end signs, arrow board.
4. **Add-on modules**, reduced to what the MUTCD sources (section 4.7, question B-12). Their device rows and real symbols exist before the add-on commit (D-110, D-117).
5. **Validators with independent recomputation**.
6. **The layout envelope** per zone, for S9. Two forms: an exact envelope from placed objects, and a conservative estimate from the pack alone (S9 pass 1 runs before any paid call).
7. **The handoff of an unplaceable device** to the S10 ladder as a `PlacementFailure`. Nothing is dropped silently.
8. **No layout for an UNDETERMINED zone**: a zone whose final router pass is UNDETERMINED or in `TA_SELECTION_CONFLICT` gets no layout, only its open questions.

### Out of scope

- The conflict ladder itself, SME exceptions, and manual taper or buffer moves (S10). S8 marks taper and buffer `movable_by_search = false` so the automatic search can never move them (D-24, CLAUDE.md rule 8).
- Grouping (S9), the sheet and PDF (S12), the SME form (S11).
- Police detail. The layout accepts `traffic_control_method` as an input fact; the substitution is a post-draft SME action (D-68; question B-13).
- No parking, RI double fines, pedestrian module (needs Sect. 6G.10, not loaded): dropped from S8 per the S4 proposal pending question B-12.
- Any new pack value. Where S8 needs one, it is a question.

### Acceptance criteria

The slice spec's four criteria, then what they mean against the S4 pack. S4's proposal to amend the second criterion is applied here and needs the owner's approval (B-12).

| # | Criterion | Reading with the S4 pack |
| --- | --- | --- |
| 1 | For the golden jobs, the advance-sign order per approach equals the golden order | Tested on **synthetic site facts** mirroring each job (real-KML fixtures come after S6). Colorado: far to near W20-1, W20-4, then the flagger sign (the draft prints W20-8 POLICE OFFICER AHEAD; the pack has W20-7, an expected known difference, D-68). Granite: W20-1, W20-5R, W4-2R, equal to the draft. E Second St: the pack has W20-1 only; the draft also has W21-5 and W5-1 (note-only signs, no device records). That is a set difference, not an order difference (B-11) |
| 2 | Labelled spacing matches within 10 ft. For Colorado, 100 ft comes from Table 6B-1 urban low speed | Direct for A, B, C. Drawn positions that differ from labels are compared by label (golden README). Positions that depend on a buffer or taper choice are **information, not a gate**, until B-3, B-4 and the golden SME check (open question 8) are closed |
| 3 | Every PlanObject has a complete trace | Schema test over every object (section 3.4) |
| 4 | A sign with no valid spot goes to the ladder (S10) and is never dropped silently | `PlacementFailure` record; a test forces failures and checks the count of placed plus failed equals the count requested |

Plus two criteria S4 makes necessary:

| # | Criterion | |
| --- | --- | --- |
| 5 | **No unsourced value is used.** Every input that is `SOURCE_REVIEW_REQUIRED` or UNKNOWN produces a `LayoutGap` (an open item with its SME question), never a number | Section 4.9 |
| 6 | **No regulatory number in `layout/`.** Changing a pack value changes the placement; a test re-seals a pack copy with A changed from 100 to 120 and checks the stations | Section 7, T-12 |
| 7 | **No layout for an UNDETERMINED zone.** A zone whose final routing decision is not `MATCH_ONE` (or an SME-chosen TA) produces no `PlanObject` and returns its open questions (2026-10-31) | A test feeds each non-matching outcome and checks zero objects |
| 8 | **Add-on devices have device rows and real symbols before any add-on is placed**; M4-9a shows its arrow (D-110, D-117) | Catalog and pack tests; a test fails if an add-on sign resolves to a placeholder symbol when the add-on commit runs |

---

## 2. Modules touched

New (under `src/tcp_planner/`):

| Module | Purpose |
| --- | --- |
| `layout/models.py` | Pydantic models: `LayoutInput`, `WorkSpace`, `PlanObject` (extends the shared contract), `LayoutGap`, `PlacementFailure`, `LayoutResult`, `Envelope` |
| `layout/pack_values.py` | The only place `layout/` reads pack numbers: Table 6B-1 A/B/C, Table 6B-2, Table 6B-3 ranges, Table 6B-4 L, 6K.01 spacing, device sequences. Wraps `effective_rules`, `evaluate_formula`, `advance_sign_spacing`, `buffer_length`. Returns `{status, value, unit, record_id, trace}` and never a bare number |
| `layout/core.py` | Stations on the road axis, side, offsets, orientation, polylines of channelizers, conversion between metres (internal) and feet (stored). Reuses `geometry/local_frame.py` (`SiteFrame`, `offset_point`, `at`, `cum`) |
| `layout/stack.py` | The longitudinal stack for one approach (work space, buffer, taper, signs), shared by all strategies |
| `layout/strategies/ta1.py`, `ta6.py`, `ta10.py`, `ta33.py` | One strategy each. Only stack order, which pack values to read, and which devices to emit. No numbers |
| `layout/modules/` | `registry.py`, `side_road.py`, `arrow_board.py`, `requirements.py` (rule actions that carry no number; section 4.8) |
| `layout/trace.py` | Builds the per-object trace from the pack (`RulePack.trace`) plus inputs, calculation and actor |
| `layout/envelope.py` | Exact and conservative envelopes |
| `layout/engine.py` | `build_layout(pack, layout_input, config) -> LayoutResult` |
| `validation/layout_validators.py` | Independent recomputation and geometry checks (section 6) |
| `orchestration/layout_stage.py` | Pipeline stage: reads the `RoutingDecision`, writes the layout artifacts, events |
| `tests/support/golden_compare_lite.py` | The Section 14 comparison rules for the three goldens (informational until S13) |
| `tests/golden/known_differences.json` | A reviewed list of expected differences between the pack and the drafts (**[STOP]**, section 5) |

Changed:

| File | Change |
| --- | --- |
| `config/pipeline_config.json` | New `layout` section (section 3.5). Guarded file; guard updated as in S3 `f1528c5` |
| `geometry/local_frame.py` | None, or additive helpers only. `place_objects` stays for the TA-1 POC path until cutover |
| `validation/validators.py`, `routing/eligibility.py`, `layout/rule_engine.py`, `layout/ta1_template` | Cutover only (B-14): TA-1 literals replaced by the strategy path. Never deleted; unused code goes to `backup/orphans/` in S15 with approval |
| `orchestration/pipeline.py` | Replace the rule engine and placement call by the layout stage at cutover |

---

## 3. Data shapes

### 3.1 Input

```
LayoutInput {
  zone_id, zone_version,
  routing ta_id, traffic_control_method FLAGGER|POLICE_DETAIL|null,                  # S7 RoutingDecision (A-1)
  start_fields {road_type, posted_speed_mph, traffic_volume, lane_closure},         # SME_UI, read only
  site {                                                                          # ASSUMPTION A-2: S6 site model
    centerline [ {lat, lon} ], road_edges {left_offset_m, right_offset_m, uncertainty?},
    lane_width_ft {value, lo, hi}|UNKNOWN, shoulder_width_ft, shoulder_closed_ft, median_width_ft,
    lanes_per_direction, divided_highway, oneway, work_side LEFT|RIGHT, closed_lane_side RIGHT|MEDIAN_SIDE|UNKNOWN,
    curve_or_crest_near_zone, side_roads [ {station_m, side} ], obstructions [ {id, station_m, offset_m, extent_m, confidence} ],
    features [ driveways, intersections, crosswalks, ramps ... ] },
  work_space WorkSpace,
  asked_if_needed { duration, night_work, arrow_board_wanted, heavy_vehicles, work_type, work_space_length_ft, ... },
  determinations [SmeDetermination],                                              # S7 shape; for SOURCE_REVIEW_REQUIRED inputs
  pack_ref {id, version, hash}
}
WorkSpace {
  upstream_end_station_m, downstream_end_station_m,        # along the centerline, increasing station
  side LEFT|RIGHT, lateral_near_offset_m, lateral_far_offset_m,
  length_source "MEASURED"|"SME"|"POINT_ONLY",              # POINT_ONLY: no length known (question B-6)
  points [ {location_id, station_m} ]                       # ASSUMPTION A-3: S3 zone work_path
}
```

### 3.2 Plan object (extends the shared contract)

```
PlanObject {
  object_id, device_id,                 # pack Device.id; catalog_id for S5 (A-4)
  object_type SIGN|TAPER|CHANNELIZER|BUFFER|WORK_SPACE|WORK_VEHICLE|ARROW_BOARD|FLAGGER|TMA|REQUIREMENT,
  approach "INCREASING_STATION"|"DECREASING_STATION"|"BOTH"|null,
  station_ft, offset_ft, side LEFT|RIGHT|CENTER, orientation {face_azimuth_deg, approach_bearing_deg},
  latlon {latitude, longitude},
  extent {length_ft, from_offset_ft, to_offset_ft}|null,    # tapers and buffers
  stack {sequence, dimension "A"|"B"|"C"|null, x_upstream_ft},   # distance upstream of the work space near end
  movable_by_search bool,               # false for TAPER, BUFFER, WORK_SPACE (D-24)
  status PLACED|GAP|FAILED, trace }
```

Stations are stored in feet from the centerline's start (`station_ft`); the engine works in metres internally and converts with the existing `FT` constant. One conversion point, tested.

### 3.3 Result

```
LayoutResult { schema_version, layout_id, zone_id, ta_id,
  objects [PlanObject], gaps [LayoutGap], failures [PlacementFailure],
  optional_not_placed [ {device_id, reason, strength "OPTION", rule_id} ],      # section 4.6
  requirements [ {action, rule_id, text} ],                                      # rule actions with no number (4.8)
  envelope Envelope, status DRAFT_COMPLIANT|REVIEW_REQUIRED|BLOCKED,
  review_reasons [ SOURCE_REVIEW_REQUIRED ids, PLACEHOLDER_ASSET, POINT_ONLY, ... ],
  inputs_hash, pack_ref, validator_results [], trace }
LayoutGap { gap_id, needed_for [object ids], record_id (pack record), status SOURCE_REVIEW_REQUIRED|UNKNOWN, question }
PlacementFailure { failure_id, object_id, device_id, requested {station_ft, side}, reason, rule_id, blocker {feature, id}, handoff "S10_LADDER" }
Envelope { upstream_ft {INCREASING, DECREASING}, downstream_ft {..}, lateral_ft {left, right}, station_range_m, derived_from [object ids]|pack_record_ids,
           kind "EXACT"|"CONSERVATIVE_ESTIMATE", assumptions [] }
```

`status` is `DRAFT_COMPLIANT` only when there is no gap, no failure, no `PLACEHOLDER_ASSET`, no `POINT_ONLY` work space and no determination. Anything else is REVIEW_REQUIRED (D-39, D-65); an unplaceable required device with no ladder outcome is BLOCKED.

### 3.4 Trace (every object)

```
trace {
  rule_id,                        # the pack record that produced the number (table_row, formula, ta_device_use, rule)
  pack_id, pack_version, pack_hash, source_refs [ {section, paragraph, table, figure, note, page, strength, evidence} ],   # from RulePack.trace
  inputs [ {field, value, unit, source, confidence, evidence_ref} ],      # e.g. road_type, posted_speed_mph, lane_width_ft
  calculation { formula, symbols, result, unit, rounding "none" },        # e.g. "x_W20-1 = buffer + taper + A + B + C"
  validators [ {check_id, result, recomputed_value} ],                    # filled by the validator pass
  actors [ "ENGINE:layout@<version>", "SME:<id>" if a determination was used ]
}
```

A test requires every key non-empty, every `rule_id` present in the pack, and the pack hash equal to the run's.

### 3.5 Settings (config `layout` section; implementation, not regulatory)

| Key | Start value | Basis |
| --- | --- | --- |
| `sign_offset_beyond_edge_m` | 2.0 | **Existing POC value** (`placement.sign_offset_beyond_edge_m`). Not regulatory, not in the pack. Labelled `IMPLEMENTATION_DEFAULT` in every trace. See B-9 |
| `sign_feature_clearance_m` | 15.0 | Existing POC value, same label |
| `distance_tolerance_ft` | 10 | The golden comparison rule (plan section 14), used only by the tests |
| `position_tolerance_ft` | 15 | Same |
| `optional_device_policy` | `OMIT` | Question B-5 |
| `taper_range_choice` | `UNSET` | Question B-4. While UNSET, no taper with a range is placed |

---

## 4. How every distance and device position is computed

### 4.1 Frame and anchors

- **Axis**: the zone centerline from the site model, in the local frame (`SiteFrame`). Stations are measured **along** the centerline, so curves are handled; no straight-road assumption.
- **Approach `d`**: `+1` for traffic moving in increasing station, `-1` for decreasing. Upstream of the work space for approach `d` means station `s_near - d*x`, where `s_near` is the work space's near end for that approach: the lower station for `d = +1` (`upstream_end_station_m`), the higher for `d = -1`.
- **`x`** is the distance upstream of `s_near`. Every longitudinal element is a number of feet `x`.
- **Side**: the right-hand roadside of the approaching driver (`RIGHT` for `d=+1`, `LEFT` for `d=-1`), as `place_objects` does today. Both-sides signs (TA-33) add the other side.
- **Lateral offset**: the road edge on that side plus `sign_offset_beyond_edge_m` (config, B-9). Not from the pack.

### 4.2 The longitudinal stack (one approach)

From the work space going upstream, the order is the same for every TA that has a taper. Each item is present only if the TA's figure and the pack say so:

```
work space near end (x = 0)
  buffer           length Bf    (optional; Option, Sect. 6B.06 para 11; Table 6B-2)              B-3
  taper            length T     (type per TA; Tables 6B-3, 6B-4)
  [shoulder taper  length Ts    (TA-33 only; note 3; TA-6 instead of the taper)]
  A  ->  sign 1
  B  ->  sign 2
  C  ->  sign 3
```

A, B and C are **consecutive** gaps, not cumulative distances. Figure 6P-10 shows A from the flagger station to the first sign, B between the first and second sign, C between the second and third. Figure 6P-33 shows A from the upstream end of the merging taper (the start of L) to W4-2R, B between W4-2R and W20-5R, C between W20-5R and W20-1; the shoulder taper lies inside A and ends where the merging taper begins (pack 1.1.0, `SR-6P33-FIG-SIGNS`). The pack stores `spacing_dimension` per sign, `sequence` (1 = nearest the work) and the Table 6B-1 values; it does **not** store what A is measured **from**. That anchor is read from the figure renders (FIGURE_TRANSCRIPTION evidence) and must be in the pack, not in code (B-1).

Formula for sign `k` of the sequence: `x_k = x_start + sum(spacing of signs 1..k)`, where `x_start` is the upstream end of the last non-sign element (taper or buffer; for TA-33, the upstream end of the merging taper, with the shoulder taper inside A). Rule ids: `TDU-<TA>-<device>` (sequence and dimension), `T-6B1-<road_type>` (the values).

### 4.3 Per-TA stacks

| TA | Elements, upstream end of the work space first | Source of each number |
| --- | --- | --- |
| **TA-1** (Fig. 6P-1) | W20-1 at `x = A` from the work space. No taper, buffer or channelizers (figure draws none). Sign on the work-side approach; **opposite approach and median left-hand sign see B-7** | `TDU-TA1-W20-1`, `T-6B1-<road_type>` (A); `R-TA1-N1` (median: a left-hand sign), `R-TA1-N3` (sign may be omitted: behind a barrier, more than 24 in behind the curb, or 15 ft or more from the edge), `R-TA1-N4` (all signs and devices may be eliminated for short-term, short-duration or mobile work with a lit vehicle) |
| **TA-6** (Fig. 6P-6) | Approach with the shoulder taper: `[Bf] + shoulder taper Ts = 0.33*L` then W20-1 at A upstream of the taper's upstream end. Opposite approach: W20-1 at A from the start of the work area (figure: "southbound: A from the start of the work area"). Work vehicle in the work space (required); TMA optional. Channelizers along the work space edge at the tangent spacing. Minimum 10 ft remaining width to the near face of the devices | `F-6B3-SHOULDER` (0.33*L, COMPUTE), `F-6B4-L`; `TDU-TA6-*`; `R-TA6-N1`, `R-TA6-FIG-BUFFER` (optional). `F-6B08-SHOULDER-THIRD` (1/3 L) is CITED_ONLY and never applied |
| **TA-10** (Fig. 6P-10) | Both ends of the one-lane section: one-lane two-way taper `T` (50 to 100 ft, Table 6B-3), a flagger at the taper's upstream end (`FLAGGER`), then W20-7 at A, W20-4 at B, W20-1 at C, on each approach. Optional W16-2P plaque below W20-7. Channelizers along the centerline between the tapers. Buffer: see B-3 and note 6 | `T-6B3-ONE_LANE_TWO_WAY`, `TDU-TA10-*`, `R-TA10-METHOD-FLAGGER`; `R-TA10-N6` (extend the buffer before a curve: **no number**, section 4.8); `R-TA10-FIG-TAPER` is CITED_ONLY |
| **TA-33** (Fig. 6P-33) | Approach with the right lane closed: `[Bf] + merging taper L`, with the arrow board at the taper's upstream end; **upstream of that, a shoulder taper only when `shoulder_closed_ft >= 8`** (note 3); then W4-2R at A from the upstream end of the merging taper (the shoulder taper, when present, lies inside A), W20-5R at B, W20-1 at C, **each on both sides of the roadway**. Work vehicle and TMA optional | `F-6B3-MERGING` (L, AT_LEAST), `F-6B4-L`; `F-6B3-SHOULDER`; `R-6N11-MERGING-TAPER` (merging taper required for a closed lane on a multi-lane road); `R-TA33-N3` (shoulder 8 ft or more); `R-TA33-N7` (arrow board, freeway); `TDU-TA33-*` |

**Where the figures leave the anchor undefined** (all in B-1): TA-6 for the opposite approach (marked "SME confirmation pending" in pack 1.1.0); whether A starts at the taper's upstream end or at the flagger station for TA-10 (the figure shows the flagger at the taper start, so these coincide). The TA-33 case is no longer open: A is measured from the upstream end of the merging taper whether or not a shoulder taper is present.

**Amendments 2026-10-31 (sections 4.2, 4.3).** Section 4.2 read "Figure 6P-33 shows A from the upstream end of the shoulder taper to W4-2R" and defined `x_start` as the upstream end of the last non-sign element "(taper or shoulder taper or buffer)". The TA-33 row of 4.3 read "W4-2R at A from the upstream end of the last taper". The paragraph above read "TA-33 A when there is no shoulder taper (the plan says Granite is 'used where there is no shoulder')" as an open anchor. All three are superseded by the pack 1.1.0 reading (S4b report, "Contradictions with the plan" and follow-up d).

### 4.4 Taper length

`L = W*S^2/60` for `S <= 40` mph and `L = W*S` for `S >= 45` mph (`F-6B4-L`, Table 6B-4, evaluated with `evaluate_formula`, never rounded). Check values from the S4 acceptance: W = 11 ft, S = 25 mph gives 114.583 ft; W = 12 ft, S = 45 mph gives 540 ft. For `S` from 41 to 44 mph the pack gives `SOURCE_REVIEW_REQUIRED`; the layout then has a `LayoutGap` and **no taper** (B-15).

| Taper | Length | Rule id | Open |
| --- | --- | --- | --- |
| Merging (TA-33) | at least `L` (use `L`) | `F-6B3-MERGING` | `W` = ? (B-2) |
| Shoulder (TA-6; TA-33 note 3) | at least `0.33*L` | `F-6B3-SHOULDER` | `W` = ? (B-2) |
| Shifting | at least `0.5*L` | `F-6B3-SHIFTING` | no TA in the four uses one |
| One-lane two-way (TA-10) | 50 to 100 ft | `T-6B3-ONE_LANE_TWO_WAY` | which value in the range (B-4) |
| Downstream | 50 to 100 ft (6B.08 para 12); TA-33 panel A shows 100 ft (optional, SRR) | `T-6B3-DOWNSTREAM`, `R-TA33-FIG-DOWNSTREAM-100FT` | B-8 |

`W` (Table 6B-4: "width of offset in feet") has no per-taper definition in the source. For the merging taper it is naturally the width of the closed lane (`lane_width_ft`, with the D-38 interval), but that is an interpretation, and the shoulder-taper offset is not obvious at all. B-2 and B-10.

### 4.5 Buffer, device spacing, end signs

- **Buffer**: `buffer_length(pack, posted_speed_mph, ta_id)` returns Table 6B-2 by **exact speed row** (e.g. 155 ft at 25 mph). A speed with no row gives SOURCE_REVIEW_REQUIRED and no interpolation. It is an Option (Sect. 6B.06 para 11: "may be used"), so whether to include it is B-3. Rule id `R-6B06-BUFFER-OPTION` plus `T-6B2-<speed>`. Taper and buffer objects carry `movable_by_search = false`.
- **Channelizer spacing**: taper: not more than `1*S` ft (`F-6K01-TAPER-SPACING`, AT_MOST); tangent: not more than `2*S` ft (`F-6K01-TANGENT-SPACING`, AT_MOST); one-lane two-way and downstream tapers: approximately 20 ft (`R-6B08-ONE-LANE-TWO-WAY-DEVICE-SPACING`, `R-6B08-DOWNSTREAM-DEVICE-SPACING`, APPROXIMATE). Number of devices over a length `T` at a limit `s`: `n = ceil(T/s) + 1`, actual spacing `T/(n-1)`, which is at most `s`. Where two sourced limits apply, the layout satisfies both (the smaller). Whether that is the intended reading is B-13. `F-6K01-EXTENSION` (2*S beyond the downstream end of the transition when devices could lead traffic out, Fig. 6P-39) applies only where its condition is set; the figures here do not set it.
- **End signs (G20-2)**: optional in all four figures. TA-33 shows 500 ft from the end of the closure (`R-TA33-FIG-G20-2-500FT`, SRR). TA-6 and TA-10 show **no dimension**. So there is **no sourced distance** for G20-2 anywhere, and under the default policy it is not placed (B-5, B-8).

### 4.6 Optional devices

Every Option in the pack is listed in `optional_not_placed` with its rule id, unless the owner's policy (B-5) or a fact enables it: buffer, W16-2P plaque, G20-2, TMA, shadow vehicle, BE PREPARED TO STOP (`R-TA10-N4`, no device record), ROAD NARROWS and SHOULDER WORK (`R-TA6-N6`, `R-TA1-N2`; no device records). The arrow board is placed when `freeway` is true with a closed lane (mandatory, `R-TA33-N7`, one per closed lane) or when `arrow_board_wanted` is true. The SME form (S11) offers each listed item as "add".

### 4.7 Add-on modules

A module is `{id, applies(facts via a pack rule condition), place(core, ctx)}`; there is no module without a pack rule.

| Module | In S8 | Position | Source |
| --- | --- | --- | --- |
| Arrow board | Yes | At the merging taper's upstream end, in the closed lane (figure) | `TDU-TA33-ARROW-BOARD`, `R-TA33-N7` |
| Side road | **Requirement only** | `R-TA33-N2` is a Standard ("additional TTC devices shall be placed as needed") with no device list and no distance. The module emits a `REQUIREMENT` object per side road in the zone (from `side_road_in_zone` and the side-road stations) and marks the plan REVIEW_REQUIRED. It places nothing. The drafts' W20-1 and G20-2 on side streets are client practice, which is not in v1 | `R-TA33-N2` |
| Median work | Requirement | A second left-hand sign for TA-1 (`R-TA1-N1`, Guidance); TA-33 note 1 (`R-TA33-N1`) substitutes LEFT LANE CLOSED and the left Lane Ends signs, **but the pack has no devices for them** (only W20-5R and W4-2R). `closed_lane_side = MEDIAN_SIDE` therefore yields a `LayoutGap` (device not in the pack), never a right-lane layout | `R-TA1-N1`, `R-TA33-N1` |
| Police detail | No (B-13) | Accept `traffic_control_method`; the substitution is S11 | `R-TA10-METHOD-FLAGGER` |
| No parking, RI double fines, pedestrian | No (B-12) | Not in v1 | — |

### 4.8 Rule actions that carry no number

These become `REQUIREMENT` objects with the rule id and quote, not positions, and force REVIEW_REQUIRED: `R-TA10-N6` (extend the buffer before a curve), `R-TA10-N9` (extend the zone before a grade crossing), `R-TA33-N2` (side road), `R-6N08-MEDIAN-15FT`, `R-TA10-N7` (light the flagger stations at night, Standard), `R-TA6-N3` and the other "positive protection may be used" notes. Each is listed so the SME sees it.

### 4.9 Work space and unsourced inputs

| Input | If unsourced or unknown | Rule or record |
| --- | --- | --- |
| Work space length | `LayoutGap`; question B-6 | `R-DEFAULT-WORK-LENGTH-*` (UNKNOWN), `work_space_length_ft` (asked per point) |
| Work-vehicle width | Not used by the layout; symbol size comes from the catalog (S5) | `R-DEFAULT-WORK-VEHICLE-WIDTH` (UNKNOWN) |
| TMA | Not suggested by speed (no threshold) | `R-TMA-SPEED-THRESHOLD` (UNKNOWN) |
| Posted speed 41 to 44 mph | No taper, `LayoutGap` | `F-6B4-L` (SRR in that range) |
| Posted speed with no Table 6B-2 row | No buffer, `LayoutGap` | `R-6B06-BUFFER-OPTION` |
| TA-33 500 ft and 100 ft | Not used (B-8) | `R-TA33-FIG-G20-2-500FT`, `R-TA33-FIG-DOWNSTREAM-100FT` |
| Low-speed cutoff, minor road, short zone | Not used by the layout | S7 |
| Lane width UNKNOWN | No merging or shoulder taper; gap | `lane_width_ft` |
| Road type with no Table 6B-1 row | No sign stack; gap | `advance_sign_spacing` returns UNKNOWN |

### 4.10 Worked numbers (information only; every input is a test value, not a default)

Colorado-like case: TA-10, `URBAN_LOW_SPEED`, 25 mph. A = B = C = 100 ft (`T-6B1-URBAN_LOW_SPEED`). Taper 50 to 100 ft (`T-6B3-ONE_LANE_TWO_WAY`). Buffer 155 ft if used (`T-6B2-25`). The nearest sign (W20-7) sits at `x = [Bf] + T + A` from the work space.

| Buffer | Taper | `x` of W20-7 | `x` of W20-1 |
| --- | --- | --- | --- |
| none | 100 | 200 | 400 |
| none | 50 | 150 | 350 |
| 155 | 50 | 305 | 505 |
| 155 | 100 | 355 | 555 |

The Colorado draft (comparison material, ±15 ft) shows the nearest sign about 300 ft from the work-point label and 100 ft between signs. It matches "155 + 50" (305) or a 100 ft buffer (the draft's label, a client practice not in v1) plus a taper of about 100 ft (not captured in the golden) plus 100 (300). This is shown only so the owner sees what B-3 and B-4 change. It is not a source.

Granite-like case: TA-33, 25 mph, `lane_width_ft` 11 (test value): `L = 11*25^2/60 = 114.583 ft`. Without a shoulder taper, `x` of W4-2R is `[Bf] + L + A` (B-1 for the anchor), W20-5R `+ B`, W20-1 `+ C`.

---

## 5. Commit sequence

Branch `tcp-mvp/s08-layout`, off `tcp-mvp/s07-router`. S8 starts only after the **S4 pack amendment** below, because strategies cannot read an anchor that is not in the pack.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF` and empty `APPROVED`; `layout` config section and guard update | [B] with 1 | Housekeeping |
| 0a | **Pack amendment (a small S4 follow-up, on the S4 branch or its own commit)**: add a `placement_anchor` to `ta_device_use` and any taper and buffer element the figures define (what A is measured from; which element follows which), each with a FIGURE_TRANSCRIPTION source_ref, then reseal. Pack hash changes | **[STOP]** | Figure readings are read from images and are regulatory geometry. Needs B-1 first |
| 1 | `layout/models.py`, `layout/trace.py`; schema and trace-completeness tests | [B] | Plumbing |
| 2 | `layout/pack_values.py`: all pack reads, with `status` handling; tests against the S4 values (114.583, 540, Table 6B-1, 155 ft) | **[STOP]** | The single door to every safety-critical number |
| 3 | `layout/core.py`, `layout/stack.py`: stations, sides, offsets, curve handling, unit conversion; synthetic straight and curved roads | **[STOP]** | Layout geometry. Includes the A/B/C consecutive-gap formula and the approach convention |
| 4 | `layout/strategies/ta1.py` and its tests | **[STOP]** | Layout geometry. First strategy; the smallest, so it proves the core |
| 5 | `layout/strategies/ta10.py` (tapers, flaggers, both ends) and tests | **[STOP]** | Layout geometry. Needs B-3, B-4, B-6 |
| 6 | `layout/strategies/ta33.py` (merging taper, shoulder taper, arrow board, both-side signs) and tests | **[STOP]** | Layout geometry. Needs B-2, B-1 |
| 7 | `layout/strategies/ta6.py` and tests | **[STOP]** | Layout geometry. Needs B-2 |
| 8 | Channelizer spacing and counts (4.5) | **[STOP]** | Safety-critical number (B-13) |
| 8a | **Before the add-on commit (D-110, D-117):** device rows for the sidewalk and detour signs (a new sealed pack version, owner-approved) and real symbols for them, M4-9a with its arrow; catalog hash resealed | **[STOP]** | A pack change and new artwork; the owner reviews the rows and the symbols |
| 9 | `layout/modules/`: registry, arrow board, side-road and median requirements, optional-device policy, and the sidewalk and detour add-ons (after 8a) | [B] with the review of 8 | The module scope (B-12) |

**Amendments 2026-10-31 (section 5).** The table had no step for add-on device rows or real symbols, and the add-on modules of commit 9 were planned on placeholder symbols with the "device rows only" outcome of S4b Stage B (D-110, D-117). Commit 0a (the pack amendment for placement anchors) was done by S4b (stage C) and the corrected TA-33 reading by the owner's check of the 400 dpi crops (S4b report).
| 10 | `validation/layout_validators.py`: independent recomputation, ordering, clearance, device existence, PlacementFailure creation, obstruction check for every TA | **[STOP]** | The independence of the recomputation is what makes it a check; the owner reviews that it does not call the engine's code |
| 11 | `layout/envelope.py` (exact and conservative) | [B] | Feeds S9; reviewed with S9 |
| 12 | `tests/golden/known_differences.json` and `golden_compare_lite.py`; the three-job comparison report | **[STOP]** | The list of "accepted" differences is a decision about what counts as correct |
| 13 | `orchestration/layout_stage.py`, cutover from `rule_engine` to the strategies (B-14), regenerated expected outputs if the owner chooses that option | **[STOP]** | Changes stored oracles (D-83). Needs a diff review of every changed expected file |
| 14 | `docs/reports/S8_layout_report.md` | [B] | Required finish (CLAUDE.md) |

Each strategy commit adds its own tests and runs the existing suites. The slice gate: suites green, new tests green, replay deterministic.

---

## 6. Validators with independent recomputation

`validation/layout_validators.py` recomputes from the pack **without** importing `layout/` code. It uses `RulePackStore` and `rule_pack_eval` only, and its own station arithmetic.

| Check id | Recomputes | Fails when |
| --- | --- | --- |
| `LAY-SPACING` | `x_k` for each sign from `ta_device_use`, Table 6B-1 and the anchors | Any `x_k` differs from the engine by more than 0.01 ft |
| `LAY-TAPER` | `L` from `F-6B4-L` and the taper length from the table row | Taper shorter than its AT_LEAST value, or outside a 50 to 100 range |
| `LAY-BUFFER` | Table 6B-2 by exact speed | Buffer length differs from the row |
| `LAY-DEVICE-SPACING` | Device spacing against 6K.01 and 6B.08 | Spacing above `1*S` (taper) or `2*S` (tangent), or devices fewer than the formula |
| `LAY-ORDER` | Sequence monotonic by `sequence` | Out of order |
| `LAY-SIDE` | Side and orientation per approach | A sign on the wrong side or facing away |
| `LAY-DEVICE-EXISTS` | Every `device_id` is in the pack and (when S5 lands) in the catalog for the road type | Missing |
| `LAY-WIDTH` | Remaining lane width to the near face of the devices against 10 ft (`R-6N07-REMAINING-WIDTH`) with the interval | Below 10 ft, or straddling: raises a question, never changes `lane_closure` |
| `LAY-IMMOVABLE` | Taper and buffer unchanged by any search step | A search moved one |
| `LAY-OBSTRUCTION` | Every placed sign against `obstructions` and `features` within `sign_feature_clearance_m`, for every TA (plan section 7, D-13) | Overlap: creates a `PlacementFailure` for S10, never moves the sign |
| `VAL-TRACE` | Trace completeness (3.4) | Any key empty |

Results are written into each object's `trace.validators`. A failed check is never turned into a pass.

---

## 7. Tests

All with synthetic roads, recorded fixtures or fakes. No live call. Start-field values in tests are labelled test inputs; none appears as a code default.

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | **Per-TA placement on a synthetic straight road** for each of TA-1, TA-6, TA-10, TA-33: stations, sides, orientation, counts, order | Hand-computed expected stations, each shown with its formula |
| T-2 | **Curved road**: the same stack along a polyline; stations measured along the curve; the figure's curved TA-10 | |
| T-3 | **Spacing and taper math**: Table 6B-4 (114.583 at 11 ft and 25 mph; 540 at 12 ft and 45 mph); 41 to 44 mph gives a gap and no taper; Table 6B-2 by exact row; no row gives a gap | Matches S4's own acceptance values |
| T-4 | **Channelizer counts and spacing** for each taper type, with both sourced limits | |
| T-5 | **Both approaches and both sides**: TA-33 signs on both sides; TA-10 on both approaches; TA-6 opposite approach anchor (B-1) | |
| T-6 | **Modules on and off**: arrow board by `freeway` and by `arrow_board_wanted`; side road requirement; median requirement; `MEDIAN_SIDE` gives a gap | |
| T-7 | **Optional-device policy**: every Option listed in `optional_not_placed`; enabling each places it with a trace | |
| T-8 | **Unsourced inputs never become numbers**: every row of 4.9; status REVIEW_REQUIRED; the SME question present | Includes the exact S4 unsourced list |
| T-9 | **Immovable taper and buffer**: the search step leaves them untouched (`LAY-IMMOVABLE`) | CLAUDE.md rule 8 |
| T-10 | **Placement failure**: a forced obstruction gives a `PlacementFailure`; placed plus failed plus gaps equals requested | Acceptance 4 |
| T-11 | **Trace completeness** over every object of every TA | Acceptance 3 |
| T-12 | **No hardcoded regulatory value**: (a) a source scan of `layout/` for pack numbers (5, 8, 9, 10, 15, 20, 50, 100, 500, and so on) with a short allow-list for 0, 1, 2 and unit constants; (b) a pack copy with A changed from 100 to 120 re-sealed in the test and the stations recomputed | The strongest check on rule 3 |
| T-13 | **Independent validator**: break the engine on purpose (off by 5 ft) and confirm `LAY-SPACING` fails; the validator module imports nothing from `layout/` | |
| T-14 | **Envelope**: exact length equals the largest `x` plus the downstream elements; the conservative estimate is at least the exact one for every case; with a TA unknown it is the maximum over pack TAs | |
| T-15 | **Determinism**: same input gives the same `layout_id` and bytes; placemark order never changes the result | |
| T-16 | **Store-only access**: the engine reads the pack only through `RulePackStore` (extend the S4 isolation test) | |
| T-17 | **Mandatory fields never written**; the `LAY-WIDTH` contradiction produces a question | CLAUDE.md rule 4 |

### Comparison with the three reference jobs

Informational report until S13 and the SME check of the golden set (open question 8). The report lists each difference and its cause, so each is fixed in the pack, accepted as field judgment, or listed in `known_differences.json`. Only the first two rows are a hard check.

| Compare | Rule (plan section 14) | Colorado (TA-10) | E Second St (TA-6) | Granite (TA-33) |
| --- | --- | --- | --- | --- |
| Advance-sign order per approach | Exact | W20-1, W20-4, flagger sign. Known difference: draft prints W20-8 POLICE OFFICER AHEAD where the pack draws W20-7 | W20-1 only. Draft also has W21-5 and W5-1 | W20-1, W20-5R, W4-2R: exact |
| Sign code set | Exact | Known difference: W20-7 vs W20-8; G20-2 not placed (B-5); side-street W20-1 and G20-2 not placed (module is requirement-only) | Known differences: W21-5, W5-1, R8-3 (no parking), G20-2 | Known differences: R2-11 and RI 27.1.1 (double fines), R9-11L (pedestrian), G20-2, side-street signs |
| Labelled spacing | Within 10 ft | 100 ft from Table 6B-1 | 100 ft MIN label vs A = 100 ft | 100 ft |
| Position along the road | Within 15 ft, same side; labelled value where the draft is schematic | Depends on B-3 and B-4: see 4.10 | The draft draws 40 ft gaps but labels 100 ft MIN: compare the label | Depends on B-1, B-2 |
| Taper and buffer | Not in the golden (shapes, not text) | Dimension labels only (100 ft buffer label vs 155 ft): known difference | not compared | not compared |
| Sheets, scale, work points | Exact | S9 and S12, not S8 | S9, S12 | S9, S12 |

Facts for each job are synthetic and hand-written from the drafts' own notes (road type, speed, geometry), marked as test inputs. Real-KML fixtures are recorded after S6 (CLAUDE.md); until then the comparison cannot use real imagery, and the lane width and edge offsets are test values. The golden file's TA is the **expectation**, never an input to the engine. The Granite KML (WPI 3159540) and the Granite drawing (WPI 3178233) are not the same job (R19); only P32 is in both, so the Granite comparison is for sign order and spacing only.

---

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S4 pack and `RulePackStore` | Every number | Merged here. **Needs the anchor amendment (commit 0a)** |
| S7 `RoutingDecision`, derived facts, `SmeDetermination` | TA, FLAGGER, determinations | Planned. ASSUMPTION A-1 |
| S6 site model | Centerline, edges, widths and uncertainty, work station, side, features | Planned elsewhere. ASSUMPTION A-2 |
| S3 zone `work_path` and engine input | Work space points | In progress. ASSUMPTION A-3 |
| S5 device catalog | `LAY-DEVICE-EXISTS` by road type, symbol sizes. Not needed for stations | ASSUMPTION A-4: `lookup(device_id, road_type) -> size or SOURCE_REVIEW_REQUIRED` and a placeholder flag |
| S10 ladder | Receives `PlacementFailure` | ASSUMPTION A-5: S10 consumes the record as defined in 3.3 |

Feeds: S9 (envelope), S10 (failures and gaps), S11 (gaps and optional items as questions), S12 (objects, trace, envelope), S13 (the comparison).

---

## 9. What could go stale if S6 changes

| S6 change | What breaks in S8 |
| --- | --- |
| The site-model shape: centerline, `road_edges`, side roads, obstructions and features (A-2) | `LayoutInput`, `core.py` (`SiteFrame` reads `road.centerline`, `road_edges.left_offset_m`, `work.reference_station_m` today), `LAY-OBSTRUCTION` |
| Width uncertainty representation (interval or value plus or minus) | `W` in Table 6B-4 (B-10), `LAY-WIDTH` |
| Which of `lane_width_ft`, `shoulder_width_ft`, `shoulder_closed_ft`, `median_width_ft` exist and in what unit | Taper inputs; the TA-33 note 3 test (8 ft) |
| `work_side` and `closed_lane_side` vocabulary | Side of signs; `MEDIAN_SIDE` gap |
| How the work reference and work path become stations (A-3; S0 item 1: signs are anchored at one reference point today) | `WorkSpace`, every `x` |
| Centerline coverage: OSM chain length versus the envelope (Table 6B-1 up to 2,640 ft for freeways; imagery half-extent about 365 m, S0 item 6) | `PLACEMENT_OUTSIDE_ANALYZED_GEOMETRY`; sheets in S12; the envelope in S9 |
| Ground scale and crop signature (evidence refs on facts) | `inputs[].evidence_ref` in the trace |
| Obstruction list shape and confidence | `LAY-OBSTRUCTION` |
| `curve_or_crest_near_zone` form (flag versus location) | `R-TA10-N6` requirement text |
| The S7 vocabulary for `work_location` | Strategy selection is by `ta_id`, so little; the work-space side only |

Not stale: the pack values, the stack formulas, the validators' arithmetic.

---

## 10. OPEN QUESTIONS

**A. Client inputs** are facts or numbers only the client or its SME can supply, and the pack already lists them as unsourced. **B. Decisions** are design choices that are the owner's. I have decided none. "Blocks" says what cannot be finished without the answer. Where a default applies, it keeps the value unsourced.

### A. Client inputs

**A-1. TA-33 figure values: 500 ft (end of closure to the END ROAD WORK sign) and 100 ft (optional downstream taper).** `R-TA33-FIG-G20-2-500FT`, `R-TA33-FIG-DOWNSTREAM-100FT`, read only from the figure render.
- Options: (a) confirm both readings; (b) confirm one; (c) decline.
- Effects: until confirmed, no downstream taper and no G20-2 on TA-33.
- Suggestion: the SME confirms against the printed figure.
- Blocks: not S8. Blocks a complete TA-33 downstream layout and the G20-2 comparison.

**A-2. TMA speed threshold.** `R-TMA-SPEED-THRESHOLD` (plan open question 6; proposal 45 mph, a client policy).
- Options: (a) none, no automatic TMA; (b) a speed.
- Effects: (a) a TMA appears only if the SME adds it.
- Suggestion: (a) until the client states a policy.
- Blocks: no.

**A-3. Default work-vehicle width and its source.** `R-DEFAULT-WORK-VEHICLE-WIDTH` (open question 7).
- Options: (a) none, UNKNOWN, asked on the form; (b) a value with a source.
- Effects: the layout does not need it. It matters to S6's remaining-width figure.
- Suggestion: (a).
- Blocks: no.

**A-4. Default work-space length per work type** (pole, manhole, excavation, trench). `R-DEFAULT-WORK-LENGTH-*` (open question 2; default "asked per point").
- Options: (a) none, always asked; (b) values with a source.
- Effects: see B-6. Without a length, the downstream elements cannot be placed.
- Suggestion: (a), the plan's own default.
- Blocks: the downstream half of TA-6, TA-10 and TA-33, until B-6.

**A-5. Which numbers Table 6B-4 `W` means for each taper (B-2) and the choice inside the 50 to 100 ft taper range (B-4) are engineering readings.** Listed under B because the owner decides; the SME is the source of the answer.

**A-6. MUTCD edition the client applies** (same as S7 A-5). A different edition changes every cited number.
- Suggestion: confirm before S8 commit 2.
- Blocks: commit 2 in practice (the pack is the input).

### B. Decisions

**B-1. Pack amendment for placement anchors.** The pack has no field for what A, B and C are measured from, nor for the order of taper, buffer and arrow board. These are read from the four figure renders. ANSWERED (see decisions section)
- Options: (a) amend the pack (new `placement_anchor` data on `ta_device_use` and taper elements, FIGURE_TRANSCRIPTION sources, reseal; pack hash changes); (b) hold the anchors in a code table; (c) hold them in `config`.
- Effects: (b) and (c) put figure geometry outside the pack and break rule 3 ("no hardcoded regulatory values"). (a) is a small S4 follow-up.
- Suggestion: (a), with the SME confirming each reading against the render, including the three undefined cases in 4.3 (TA-33 with no shoulder taper; TA-6 opposite approach).
- Blocks: S8 (commit 0a).

**B-2. `W` in Table 6B-4 for each taper type.** ANSWERED (see decisions section)
- Options: (a) merging taper: `lane_width_ft` of the closed lane; shoulder taper: the offset the SME defines; (b) an SME-typed value per taper per plan; (c) both, with (a) computed and (b) as an override.
- Effects: `L = W*S^2/60` or `W*S`, so `W` moves every taper, every sign downstream of it, and the envelope. The shoulder-taper offset is not defined in the source text I have.
- Suggestion: the SME states the definition per taper type; I would then encode it as (a) in the pack.
- Blocks: TA-6 and TA-33 tapers.

**B-3. Include the optional buffer?** Sect. 6B.06 para 11 makes Table 6B-2 an Option. The figures mark the buffer "optional" (TA-6, TA-33) or do not draw it (TA-10, only note 6). The client's 100 ft at 25 mph (Colorado) is client practice and the client layer is empty (D-51 withdrawn proposal). ANSWERED (see decisions section)
- Options: (a) never; (b) always, from Table 6B-2 (155 ft at 25 mph); (c) per TA in config; (d) an SME choice per zone on the form.
- Effects: a buffer moves **every** sign upstream by its length (4.10). Against the Colorado draft (comparison only) the nearest sign differs by 5 to 55 ft with (b), depending on B-4.
- Suggestion: (d), default (a) until answered, so the plan states what was not included.
- Blocks: signs' stations in all four TAs.

**B-4. Taper length inside a sourced range.** Table 6B-3 gives 50 to 100 ft for the one-lane two-way and downstream tapers and no rule for choosing. ANSWERED (see decisions section)
- Options: (a) 100 ft; (b) 50 ft; (c) an SME choice per zone; (d) a config value per TA.
- Effects: moves the sign stack by up to 50 ft. The Colorado draft's total (about 300 ft to the nearest sign) fits 50 ft with a 155 ft buffer, or 100 ft with a 100 ft buffer.
- Suggestion: (c), with `taper_range_choice = UNSET` meaning no taper is placed and a gap is reported.
- Blocks: TA-10.

**B-5. Optional-device policy.** Options in the pack and figures: G20-2, W16-2P plaque, TMA, shadow vehicle, BE PREPARED TO STOP, arrow board when not on a freeway. ANSWERED (see decisions section)
- Options: (a) omit all and list them for the SME to add; (b) place those the figures draw as optional (G20-2, W16-2P), if a sourced distance exists; (c) per TA in config.
- Effects: G20-2 has no sourced distance in any figure but TA-33's SRR 500 ft, so (b) cannot place it without inventing one. The Colorado and E Second St drafts include G20-2.
- Suggestion: (a).
- Blocks: no.

**B-6. Work space when its length is unknown.** The KML gives a point. Today the engine measures from the reference point (S0 item 1). ANSWERED (see decisions section)
- Options: (a) ask the SME (the plan's default, `work_space_length_ft` on the form) and place nothing downstream until answered; (b) a provisional layout in `POINT_ONLY` mode: upstream stacks measured from the point, downstream elements omitted, REVIEW_REQUIRED, with the question; (c) a default length by work type (not allowed: unsourced).
- Effects: (b) is safe for the upstream warning (it errs long on the near side if the point is the middle of the work), but the one-lane length for TA-10 and every downstream element are missing. (a) leaves the zone without a draft until answered.
- Suggestion: (b), with `default_if_skipped` = POINT_ONLY and the status REVIEW_REQUIRED.
- Blocks: commits 5 to 7 (their downstream parts).

**B-7. Which approaches and sides get signs** where the figure shows one direction only (Sect. 6P.01 para 07: "Most of the typical applications show TTC devices for only one direction"). ANSWERED (see decisions section)
- Options: TA-1: (a) the work-side approach only; (b) both approaches of a two-way road, as the POC does. TA-6: both approaches (the figure shows both). TA-33: the closed-lane approach, both sides of the roadway (the figure). TA-10: both approaches (figure).
- Effects: only TA-1 is open. No TA-1 reference draft exists.
- Suggestion: TA-1 (b), marked as a reading of para 07 and flagged.
- Blocks: TA-1 only.

**B-8. TA-33 downstream elements and G20-2 until A-1 is answered.** ANSWERED (see decisions section)
- Options: (a) do not place; list as `LayoutGap` with the SME question; (b) place with the figure values flagged SOURCE_REVIEW_REQUIRED and REVIEW_REQUIRED.
- Effects: (b) draws numbers the pack calls unsourced.
- Suggestion: (a).
- Blocks: no.

**B-9. Lateral offset and feature clearance.** `sign_offset_beyond_edge_m = 2.0` and `sign_feature_clearance_m = 15.0` are POC implementation values, not in the pack, not regulatory. ANSWERED (see decisions section)
- Options: (a) keep them in config, labelled `IMPLEMENTATION_DEFAULT` in every trace; (b) source them from Sect. 6F.03 (not loaded) and add pack records; (c) make them SME settings per client.
- Effects: (a) is a drawing and conflict-check convention, but a sign 2 m beyond the edge is also a safety geometry.
- Suggestion: (a) now, (b) in a later pack round.
- Blocks: no.

**B-10. How a width interval enters a taper.** `lane_width_ft` has an uncertainty (D-38). L is at least `W*S^2/60`. ANSWERED (see decisions section)
- Options: (a) the measured value; (b) the upper end of the interval (the longer taper); (c) UNKNOWN when the interval straddles a TA threshold, otherwise the measured value; (d) an SME-typed width.
- Effects: (b) is conservative, (a) may draw a short taper.
- Suggestion: (b), with the interval shown in the trace.
- Blocks: TA-6 and TA-33 tapers.

**B-11. Note-only signs with no device record** (W21-5 SHOULDER WORK, W5-1 ROAD NARROWS, BE PREPARED TO STOP). The E Second St draft uses W21-5 and W5-1; the pack lists them as note actions only. ANSWERED (see decisions section)
- Options: (a) leave as `optional_not_placed` and a known difference; (b) add device records (a small S4 and S5 follow-up) with sizes from the catalog and no placement distance until sourced.
- Effects: (b) alone does not place them; no distance is sourced.
- Suggestion: (a).
- Blocks: no.

**B-12. Add-on module scope.** The S8 spec lists no parking, side streets, pedestrian, RI double fines, police and arrow board. The S4 review proposes keeping side roads (TA-33 note 2), the arrow board and Table 6B-2 buffers, and dropping the rest or making them SME-added. ANSWERED (see decisions section)
- Options: (a) accept the S4 proposal, and amend the S8 acceptance to list the comparator's known differences; (b) keep the client modules and revive the client layer first (every entry cites its draft and waits for SME confirmation); (c) accept (a) now and add modules later.
- Effects: with (a), side roads are a **requirement only** (no device or distance is sourced), so the Granite and Colorado side-street signs are known differences.
- Suggestion: (a)/(c).
- Blocks: commit 9.

**B-13. Channelizer spacing when two sourced limits apply, and where police detail is applied.** ANSWERED (see decisions section)
Spacing options: (a) satisfy both: use the smaller of "approximately 20 ft" and `1*S` in the one-lane two-way and downstream tapers, `1*S` in other tapers, `2*S` in tangents; (b) 6B.08 only where it applies, 6K.01 elsewhere. Count rule `n = ceil(T/s)+1`.
Police options: (a) S11 substitutes W20-7 with POLICE OFFICER AHEAD and re-runs the layout and checks; S8 only accepts `traffic_control_method` as an input; (b) S8 builds the substitution; (c) not at all in the MVP. `CLIENT-POLICE-OFFICER-AHEAD` has no size source (plan section 10A).
- Suggestion: spacing (a); police (a).
- Blocks: commit 8 (spacing). Not police.

**B-14. Cutover from the POC TA-1 path.** The pipeline still runs `rule_engine`, `eligibility`, `validators` and the POC pack. The 13 offline scenarios and the KML case have byte-exact stored outputs (D-83). Moving to the strategies changes them. ANSWERED (see decisions section)
- Options: (a) cut over in this slice, regenerate the expected outputs with `python -m tests.support.make_expected`, and review every diff; (b) keep the POC path for the offline scenarios until S13 and add the strategies as a second path (D-32 forbids two paths); (c) cut over, and re-record the offline scenarios as new-pack scenarios.
- Effects: (a) is the plan's route. The POC pack is edition-different (Dec 2025 header).
- Suggestion: (a), with the owner reviewing the changed files at commit 13. It depends on S7 B-4.
- Blocks: commit 13.

**B-15. A speed with no sourced row (41 to 44 mph for L; any speed without a Table 6B-2 row).** ANSWERED (see decisions section)
- Options: (a) a gap and an SME question; the SME may type a value as a recorded determination (S7 B-1) for that plan version; (b) round to the nearest or the next higher sourced row (that is an interpolation or an invention); (c) block the zone.
- Suggestion: (a).
- Blocks: no (the gap is the designed behaviour).

### Summary table

| # | Question | Group | Blocks S8? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | TA-33 500 ft and 100 ft readings | Client input | No (TA-33 downstream only) | SME confirms against the figure |
| A-2 | TMA speed threshold | Client input | No | None until the client states a policy |
| A-3 | Default work-vehicle width | Client input | No | None; asked on the form |
| A-4 | Default work-space length by work type | Client input | Downstream elements, until B-6 | None; asked per point |
| A-5 | Readings of `W` and of the taper range choice | Client input (see B-2, B-4) | See B-2, B-4 | SME states them |
| A-6 | MUTCD edition applied | Client input | Commit 2 in practice | Confirm first |
| B-1 | Pack amendment for placement anchors | Decision | **Yes (commit 0a)** | Amend the pack with SME-confirmed readings |
| B-2 | `W` per taper | Decision | TA-6, TA-33 tapers | SME defines; encode in the pack |
| B-3 | Include the optional buffer | Decision | Sign stations, all TAs | Per-zone SME choice; default none |
| B-4 | Taper length within 50 to 100 ft | Decision | TA-10 | Per-zone SME choice; UNSET places no taper |
| B-5 | Optional-device policy | Decision | No | Omit and list |
| B-6 | Work space with unknown length | Decision | Downstream parts of strategies | Provisional `POINT_ONLY` layout, REVIEW_REQUIRED |
| B-7 | Approaches for TA-1 | Decision | TA-1 | Both approaches, flagged |
| B-8 | TA-33 downstream and G20-2 before A-1 | Decision | No | Gap, not placed |
| B-9 | Lateral offset and feature clearance | Decision | No | Keep POC config, labelled |
| B-10 | Width interval into a taper | Decision | TA-6, TA-33 tapers | Upper end of the interval |
| B-11 | Note-only signs with no device record | Decision | No | Leave as known differences |
| B-12 | Add-on module scope | Decision | Commit 9 | Accept the S4 proposal; side roads as requirement |
| B-13 | Channelizer spacing rule; police variant timing | Decision | Commit 8 (spacing) | Satisfy both limits; police in S11 |
| B-14 | Cutover and regenerated oracles | Decision | Commit 13 | Cut over here with diff review |
| B-15 | Speeds with no sourced row | Decision | No | Gap and SME question |
