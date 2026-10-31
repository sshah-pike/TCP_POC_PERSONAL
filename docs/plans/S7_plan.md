Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

## Owner decisions applied (2026-10-30)

- B-1: an SME determination record for the plan, plus a proposal to promote it into the pack. B-2 B. B-3: thresholds 0.85 and 0.80; strict cross-check only on lanes per direction, divided, shoulder, one-way; work_location by confidence plus SME confirmation. B-4 A (non-gating route stage; S8 cuts over). B-5 A. B-6 A. B-7 B (wait for 6G.10 in the pack). B-8: record call 2 after S7 with call 1. B-9 C (SME determination).
- The 6N.11 Granite-type case is sourced, so Granite routes to TA-33 automatically; broader cases go to the engineer. E Second stays UNDETERMINED until the SME answers the low-speed and minor-road questions. Colorado routes to TA-10. TA-6 never auto-selects without an answer.

## Owner decisions applied (2026-10-31)

Register: `docs/decisions/OWNER_DECISIONS_2026-10-31.md`. Where this block differs from older text, this block is the active text; the older wording is kept in the "Amendments 2026-10-31" notes at the end of sections 1, 3, 4, 7 and 10. Future items are in `docs/FUTURE_SCOPE.md`.

- **Two-pass router (D-128).** A provisional pass runs before call 2 and a final pass after the second fusion. A **what-if test** marks each unresolved fact as *deciding* or *not deciding* for routing: the router is re-run with the fact set to each value of its registry domain, and the fact is deciding when the outcome set changes (the owner's wording is "marks each unresolved fact as deciding or not deciding"; this mechanism is proposed here for approval). It reads the pack only.
- **Call 2 rewritten (D-119, D-120, D-121, D-123).**
  - Call 2 is a **blind re-observation**: it is never shown the OSM value, the call-1 value or any code value for lanes, divided, shoulder or one-way.
  - Before the call, code re-measures at fine zoom (the zoom-19 view, D-112).
  - Call 2 fields are the deciding facts (from the what-if test), the chosen TA's fields and the conflicts.
  - Lane count is a field whenever call 2 runs; it never forces a call (D-121); a config switch turns it off.
  - If call 1 and call 2 disagree on a field, the field becomes UNKNOWN and goes to the SME (D-123).
  - Two AI reads never count as two sources (D-92, D-119; `docs/reports/S6_stop5_fusion_rules.md` on branch `tcp-mvp/s06-site-understanding`): call 2 can lower a resolved safety fact to UNKNOWN; it cannot raise a single-source one.
  - At most two AI calls per zone.
- **Generality tests (D-128, FS-11).** A made-up TA added to a test pack works with no code change. No TA id appears in the router, the fusion or the call-2 code (a string-scan test).
- **Blocking and informational questions (D-156 recommendation 1, owner confirmation open).** A single-source safety field is UNKNOWN with the AI value kept as a pre-filled candidate. The question candidate S6 emits is informational; S7 makes it blocking only when the what-if test shows the fact decides the TA.
- **New 6N.11 ids (S4b follow-up e).** `E-TA33-FORM-UNDIVIDED-6N11` and `R-6N11-TA33-UNDIVIDED-FOUR-LANE` no longer exist in pack 1.1.0. The sourced Granite-type branch is `E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT` with rule `R-6N11-TA33-UNDIVIDED-FOUR-LANE-RIGHT`; the broader undivided cases are `E-TA33-FORM-UNDIVIDED-OTHER` with rule `R-6N11-TA33-UNDIVIDED-OTHER` (unsourced, an engineer question). The old ids exist only in the sealed version 1.0.0.
- **Unknown `closed_lane_side` never defaults to RIGHT (S4b follow-up c).** A missing or unstated side keeps TA-33 UNDETERMINED with a question.
- **D-59 fixes (CLAUDE.md, "D-59 breaches still in the engine").** Remove the OSM `maxspeed` fallback and the encroachment override of the SME's lane closure in `site_model/fusion.py`; a computed disagreement raises a conflict question and never changes the value.
- **Pack store merged.** Sealed pack versions are stored side by side (commit `69ab4c0`), so a decision recorded against a pack hash replays without a git checkout (D-116).
- **Gate after S7.** The accuracy gate (8-site early check) sits between S7 and S8 (D-125).

# S7 plan: router and call 2 TA fields

Planning only. Branch when built: `tcp-mvp/s07-router`, off the S6 branch (S6 is being planned elsewhere). Written on `tmp/plan-base2` (S2 + S4 merged). Nothing here is approved until the owner says so (CLAUDE.md, "How to work", rule 2).

Read for this plan: CLAUDE.md; slice spec S7; plan sections 4B, 4C, 5, 6, 7, 10, 14; D-24, D-47, D-49, D-60, D-64, D-68, D-80, D-81; `S0_repo_report.md`; `S0_prompt_tuning_proposal.md`; `S4_rule_pack_review.md`; `rule_pack/`; `rules/rule_pack_eval.py`, `rule_pack_effective.py`, `rule_pack_store.py`; the four figure renders; the S3 commit messages and `projects.py` (via `git show`, no checkout).

Rules come from the MUTCD only (S4 owner decision). The Colorado, E Second St and Granite drafts are comparison material.

Legend used below: **[B]** commits that can be batched. **[STOP]** stop for owner review before the next commit. **ASSUMPTION A-n** is a shape or behaviour I rely on from S3 or S6 that I could not verify; each is listed again under "What could go stale if S6 changes".

---

## 1. Scope and acceptance criteria

### In scope

1. A **router** that reads only the rule pack (through `RulePackStore`) and the zone's facts, and returns exactly one of five outcomes (section 3.2). It names only TAs in the pack (D-35). It runs twice: a provisional pass before call 2 and a final pass after the second fusion (D-128), with a what-if test that marks each unresolved fact as deciding or not deciding.
2. **Near match** ("did you mean"): at most 1 failed condition, at most 2 suggestions (D-33).
3. **`TA_SELECTION_CONFLICT`** against the UI "Select TA" hypothesis (D-73), and never trusting the hypothesis alone (CLAUDE.md rule 7).
4. **Derived facts that depend on the pack or on the start fields**: `low_speed_road`, `freeway`, `traffic_control_method` (code sets FLAGGER when TA-10 is chosen, D-68), `single_flagger_eligible`, and the remaining-width verdict. Each stays UNKNOWN while its pack record is unsourced.
5. **Consistency checks against the four mandatory start fields.** A contradiction raises a conflict question. It never changes the field (CLAUDE.md rule 4).
6. **Call 2** (rewritten 2026-10-31): the request builder, the output schema and validation, a code re-measurement at fine zoom before the call, the blind re-observation (no OSM, call-1 or code value for lanes, divided, shoulder or one-way), and the disagreement rule (call 1 and call 2 disagreeing gives UNKNOWN). Its fields are the deciding facts, the chosen TA's fields and the conflicts; lane count is a field whenever call 2 runs and never forces a call (D-120, D-121, D-123). The D-80 re-asks that remain: lane lines, shoulder edge and curb marks from crops; the sidewalk pair (see question B-7: no rule uses sidewalk in v1).
7. A **pipeline stage** that writes the routing decision as a write-once artifact. Whether it gates the pipeline is question B-4.
8. **Generality**: a made-up TA in a test pack works with no code change, and no TA id appears in the router, the fusion or the call-2 code (D-128).
9. **Blocking and informational questions**: each `Question` says whether it blocks, using the what-if test (D-156 recommendation 1).
10. **Fixes**: an unknown `closed_lane_side` never defaults to RIGHT (S4b follow-up c); the D-59 breaches in `site_model/fusion.py` (the OSM `maxspeed` fallback and the encroachment override of the SME's lane closure).

### Out of scope

- The layout itself (S8), grouping (S9), the conflict ladder (S10), the question form (S11). S7 emits `Question` records; S11 renders them.
- Police detail. The router never applies it (D-68). The SME switches it after the draft.
- Any new rule-pack value. S7 does not edit the pack. Where S7 needs a pack change, it is listed as a question.
- Any change to the four mandatory start fields.

### Acceptance criteria (the slice spec, restated against what S4 actually encoded)

| # | Criterion | What it means with the S4 pack |
| --- | --- | --- |
| 1 | On golden fixtures the router returns TA-10 for Colorado, TA-6 for E Second St and TA-33 for Granite, **or a question when a deciding fact is unknown**. Never a wrong TA silently. | **Colorado and Granite can auto-route** with pack 1.1.0 when their facts pass the gates: Granite matches TA-33 through the sourced branch `E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT` (D-91). Broader undivided cases are `E-TA33-FORM-UNDIVIDED-OTHER` (unsourced) and stay UNDETERMINED with an engineer question. TA-6 stays UNDETERMINED because `E-TA6-LOW-SPEED` (cutoff) and `E-TA6-MINOR-ROAD` are unsourced; for E Second St the passing result is TA-6 as the single candidate plus the SME question. This is the honest consequence of S4; I recommend the owner reads it before approving. |
| 2 | With no fitting TA, `NO_TA_MATCH` with failed conditions per pack TA, and no TA outside the pack named. | Direct. |
| 3 | TA-6 rejected without a shoulder, and on a high-speed road. | "Without a shoulder" works with the real pack. "High-speed road" **cannot** work with the real pack: the cutoff is unsourced, so a high speed gives UNKNOWN, not rejected. It is tested only with a test-only pack variant (section 7, T-9; question B-9). |
| 4 | TA-33 never double-matches. | Pack-driven: the divided and undivided branches share one `any_group` (`ROAD_FORM`). Test enumerates every fact combination in the small domain. |
| 5 | TA-10 always drafts with flaggers. | `traffic_control_method` is set to FLAGGER by code from `R-TA10-METHOD-FLAGGER` when TA-10 is chosen. |
| 6 | Call 2 re-observes blind: its request holds no OSM, call-1 or code value for lanes, divided, shoulder or one-way. A field on which call 1 and call 2 disagree becomes UNKNOWN. Two AI reads never count as two sources. | Section 4 (merge table). |
| 7 | At most two AI calls per zone. | Counted and asserted per zone. Call 2 runs when the field list, not counting the lane count, holds at least one deciding fact, chosen-TA field or conflict; the lane count is added when call 2 runs and never causes it (D-121). |
| 8 | Every decision carries the rule ids it used. | Condition ids, rule ids, pack id, version and hash on every `RoutingDecision` (section 3.3). |
| 9 | A made-up TA in a test pack routes with no code change; no TA id appears in the router, the fusion or the call-2 code. | Generality tests (T-16, T-17). |

---

## 2. Modules touched

New (under `src/tcp_planner/`):

| Module | Purpose |
| --- | --- |
| `routing/models.py` | Pydantic models: `RoutingDecision`, `CandidateTA`, `NearMatch`, `SelectionConflict`, `SmeDetermination`, `Question` (extends the S1 shared contract), `Call2Request`, `Call2Result` |
| `routing/facts_view.py` | Turns the zone's `SiteFact` list and start fields into the registry-keyed facts dict the pack evaluator reads. Applies status, confidence and uncertainty gating. Derives the "deciding fields" from the pack (every field named in an eligibility expression). Nothing is hardcoded |
| `routing/derived_facts.py` | The derived facts in scope item 4 |
| `routing/router.py` | `route(pack, zone_ctx, config, stage) -> RoutingDecision`. Pure function of its inputs; same inputs give the same decision and the same hash |
| `routing/consistency.py` | Contradictions with the mandatory fields. Produces conflict `Question`s only |
| `routing/call2_plan.py` | Pack-driven list of the chosen TA's fields, classified by registry `source_type`, with crop specs |
| `ai/call2.py` | Call 2 prompt, flat-facts-list schema (D-61), Pydantic validation, provider call through the existing Foundry provider |
| `routing/merge.py` | Merge, the call 1 and call 2 disagreement rule (UNKNOWN), and the second fusion (was: "Non-overwrite merge and the cross-view check", amended 2026-10-31, D-123) |
| `orchestration/route_stage.py` | The pipeline stage, artifact writes, event log, zone `ta` update |

Changed:

| File | Change |
| --- | --- |
| `rules/rule_pack_eval.py` | One additive parameter, `evaluate_eligibility(..., determinations=None)`, so an SME determination can resolve an unsourced condition for one plan version (question B-1). Default behaviour unchanged; the S4 tests must stay green unchanged |
| `config/pipeline_config.json` | New section `router` (settings, section 3.4). The file is guarded by `tests/support/guard_baseline.py`; S3 updated the guard the same way (commit `f1528c5`) |
| `orchestration/pipeline.py` | Insert the route stage and the call 2 stage (B-4 decides gating) |
| `contracts.py` | Add routing outcome constants |

Not touched: `routing/eligibility.py` and `layout/rule_engine.py` (TA-1 literals, POC pack). They stay until S8 cuts over (question B-4).

Existing code reused: `rules/rule_pack_eval.py` (`evaluate_eligibility`, `screen_tas`, three-valued `eval_expr`, `evaluate_formula`), `rules/rule_pack_store.py` (`RulePack.trace`, `ta`), `rules/rule_pack_effective.py` (`effective_rules`), the Foundry provider, `config.crops.field_map`.

---

## 3. Data shapes

### 3.1 Inputs the router reads

```
ZoneRoutingContext {
  zone_id, zone_version, project_id,
  start_fields {road_type, posted_speed_mph, traffic_volume, lane_closure},   # SME_UI, from S3 zone input; never written here
  ta_hypothesis "AUTO"|"TA-1"|"TA-6"|"TA-10"|"TA-33",                         # S3 zone.inputs
  facts [SiteFact],             # ASSUMPTION A-1: S6 output, shared-contract SiteFact
  determinations [SmeDetermination],   # empty until S11; see B-1
  pack_ref {id, version, hash}
}
SiteFact (shared contract) { field, value, unit, confidence, uncertainty?, source, evidence_ref, status RESOLVED|UNKNOWN|CONFLICT }
```

ASSUMPTION A-1 also requires from S6: (a) `field` uses the registry ids of `rule_pack/base/registry.json`; (b) enum values use the registry vocabulary (for `work_location`: `BEYOND_SHOULDER`, `ON_SHOULDER_OR_ENCROACHING`, `IN_LANE`); (c) a numeric fact with an uncertainty carries `{lo, hi}` in the same unit; (d) `lanes_per_direction` is already UNKNOWN (or CONFLICT) when the OSM and state data disagree (D-80). The S0 spike's call 1 enum for `work_location` was `ROADWAY|SHOULDER|BEYOND_SHOULDER|SIDEWALK|UNKNOWN`, which is not the registry's. See question B-6.

### 3.2 The five outcomes

| Outcome | When | Carries |
| --- | --- | --- |
| `MATCH_ONE` | Exactly one pack TA is ELIGIBLE and every other pack TA is NOT_ELIGIBLE (none UNDETERMINED), every deciding fact of the matched TA passes the gates in 3.5, and the hypothesis (if not AUTO) equals the match | `ta`, evidence, rule ids |
| `MATCH_MULTIPLE` | More than one TA ELIGIBLE | The TAs, the conditions that did not separate them, a question. The hypothesis, if it is one of them, is offered as the default option, never auto-chosen |
| `NO_TA_MATCH` | Every pack TA is NOT_ELIGIBLE | Per-TA failed conditions; `near_matches` (at most 2) |
| `TA_SELECTION_CONFLICT` | Hypothesis is a TA and that TA is NOT_ELIGIBLE | Hypothesis, the router's own view, failed conditions with the facts that failed them, a question with options: switch, keep as recorded exception, mark undetermined (plan section 6) |
| `DECIDING_FACT_UNKNOWN` | Anything else: a TA is UNDETERMINED (a fact missing, gated out, straddling a threshold, or an unsourced condition), or one TA is ELIGIBLE while another is UNDETERMINED | `candidate_tas`, the missing facts or unsourced conditions, one question per item, the SME question text from the pack |

The plan's list is "one matches, several match, none fits, user conflicts, a deciding fact is unknown". Near match is not a sixth outcome; it is an annotation on `NO_TA_MATCH` (and on `DECIDING_FACT_UNKNOWN` when a TA is one condition short). It never selects a TA.

Rule for hypothesis `H` (not AUTO):

| Router's own result for `H` | Outcome |
| --- | --- |
| NOT_ELIGIBLE | `TA_SELECTION_CONFLICT` |
| UNDETERMINED | `DECIDING_FACT_UNKNOWN`, with `H` first among candidates; if another TA is ELIGIBLE the decision says so |
| ELIGIBLE | as AUTO, and the source is recorded as `UI_VERIFIED` |

### 3.3 `RoutingDecision`

```
RoutingDecision {
  schema_version, decision_id, zone_id, zone_version, stage "PROVISIONAL"|"FINAL",
  outcome, ta {value|null, source "ROUTER"|"UI_VERIFIED"|"SME", status},
  hypothesis, candidates [ {ta_id, result ELIGIBLE|NOT_ELIGIBLE|UNDETERMINED,
      conditions [ {condition_id, any_group, result true|false|null, status SOURCED|SOURCE_REVIEW_REQUIRED|UNKNOWN,
                    fact_inputs [ {field, value, source, confidence, gate PASS|FAIL_CONFIDENCE|UNKNOWN|STRADDLES_THRESHOLD|CONFLICT} ] } ],
      failed [..], unknown [..] } ],
  near_matches [ {ta_id, failed_condition_id, unknown_condition_ids, message} ],
  conflict {hypothesis, router_ta, failed_conditions, facts} | null,
  derived_facts [ SiteFact ],           # low_speed_road, freeway, traffic_control_method, ...
  questions [ Question ],
  settings_used {...3.4...}, pack_ref, inputs_hash,
  trace {rule_ids [], pack_id, pack_version, pack_hash, source_refs [], inputs [], calculation "per-condition table", validators [], actors ["ENGINE:router@<v>", "UI:<hypothesis source>"]}
}
Question { question_id, kind DECIDING_FACT|UNSOURCED_CONDITION|TA_CONFLICT|NEAR_MATCH|FACT_CONFLICT|MANDATORY_CONTRADICTION|WHICH_ROAD|WORK_LOCATION_NEAR_EDGE,
           field, zone, project, osm_way_id|null, context, reason, options [], default_if_skipped, parent_id?, reveals [],
           blocking bool (what-if test), candidate bool, suggested|null }
```

`default_if_skipped` is never a value for an unsourced item. For an unsourced condition it is "stay UNDETERMINED; plan is REVIEW_REQUIRED". Written write-once through `ArtifactStore` (`routing_decision.<stage>.json`) with an artifact reference, `schema_version`, and the decision id derived from the inputs hash. Same inputs, same file.

### 3.4 Settings (config, `router` section; not regulatory, ADR-015)

| Key | Start value | Basis |
| --- | --- | --- |
| `auto_select_min_confidence` | 0.85 | D-33, package suggestion |
| `safety_critical_min_confidence` | 0.80 | D-33, brief |
| `common_min_confidence` | 0.70 | D-33, POC value |
| `near_match_max_failed` | 1 | D-33 |
| `near_match_max_suggestions` | 2 | D-33 |
| `uncertainty_corner_limit` | 3 | engineering limit on corner evaluation (3.5); not regulatory |
| `ai_calls_per_zone_max` | 2 | CLAUDE.md |

No regulatory number is in this table or in code. Interaction of 0.85 and 0.80: question B-3.

### 3.5 Fact gating (deterministic)

The **deciding fields** are computed from the pack: every `field` appearing in any `eligibility_condition.expr` of a pack TA. A fact reaches the evaluator only if:

1. `status == RESOLVED`. UNKNOWN and CONFLICT become missing (None) with the reason kept.
2. Its source is the SME UI (the four start fields), or `confidence >=` the threshold for its class (3.4): auto-select threshold for a deciding field of the matched TA, safety-critical for other deciding fields, common for the rest.
3. If it has an uncertainty `{lo, hi}` and a condition compares it with a number, the condition is evaluated at the interval ends (corners when several facts are uncertain, up to `uncertainty_corner_limit`); if the results differ the condition is None with gate `STRADDLES_THRESHOLD` (D-38). No pack change is needed: `eval_expr` already takes scalars.

A fact the router cannot use is recorded with its reason, so the SME form can say why it asks.

### 3.6 `SmeDetermination` (shape only; mechanism is question B-1)

```
SmeDetermination { determination_id, record_id (condition or rule id), answer true|false|value, actor, reason, plan_version, created_at,
                   trace {rule_id, pack_hash, pack_status "SOURCE_REVIEW_REQUIRED", ...} }
```

Applies to one plan version only (D-29 spirit). A plan that uses one is REVIEW_REQUIRED (D-39) and the trace shows actor SME.

### 3.7 Call 2

```
Call2Request { zone_id, ta_id, budget {calls_used, calls_max},
  fields [ {field, class AI_OBSERVE|AI_THEN_SME|CODE_AND_AI, reason DECIDING_UNKNOWN|DECIDING_CONFLICT|TA_FIELD|LANE_COUNT|MARKS_REQUIRED,
            crop {purpose, center {lat, lon}|{station_m, offset_m}, extent_m, min_px, kind FINE_ZOOM_FETCH|WIDE_CUT}} ],
  known_facts [ {field, value, status} ] }            # never holds lanes_per_direction, divided_highway, shoulder_present or oneway (blind re-observation, D-120)
Call2Result  = flat facts list, same schema as call 1 (D-61): facts [ {field, value, status, confidence, evidence} ] + marks [ {feature, points, status, evidence} ]
```

Facts list only (D-61). Every property required, no nullable unions, no `minimum`/`maximum`. Validated in code with Pydantic, enums case-insensitive. A missing or malformed fact becomes UNKNOWN. No field in the result may be a length: a test fails if one appears (D-64). Evidence is capped at 15 words in the prompt and flagged (not cut) in the trace when longer; UNKNOWN carries one of the fixed reason codes `not_visible`, `occluded`, `low_resolution`, `ambiguous` (D-80 item 4). `unit` is filled by code from the registry if the owner approves the S0 tuning proposal change (ASSUMPTION A-2).

---

## 4. How every decision is computed and traced

S7 produces no distance. It produces TA decisions and derived facts. Each is traced to a rule id.

| Output | Computation | Rule or record id | Notes |
| --- | --- | --- | --- |
| Per-TA eligibility | `evaluate_eligibility(pack, ta, facts, determinations)`; conditions with the same `any_group` OR'd; any False gives NOT_ELIGIBLE; else any None gives UNDETERMINED | `E-TA1-*`, `E-TA6-*`, `E-TA10-*`, `E-TA33-*` | Unsourced conditions are None and add the pack's `sme_question` |
| Routing tree (D-60) | **Not coded.** The tree is a picture of what the pack conditions already say (work_location, lane_closure, shoulder, road form) | the same | Tests walk each branch by facts, not by code path |
| TA-33 road form | One OR group `ROAD_FORM`: divided, or an undivided branch (the Granite-type case, or the broader cases) | `E-TA33-FORM-DIVIDED`, `E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT` (SOURCED, D-91), `E-TA33-FORM-UNDIVIDED-OTHER` | The Granite-type branch (two lanes each way, right lane closed) is SOURCED in pack 1.1.0 (rule `R-6N11-TA33-UNDIVIDED-FOUR-LANE-RIGHT`). The broader undivided branch is SOURCE_REVIEW_REQUIRED (rule `R-6N11-TA33-UNDIVIDED-OTHER`), so such a site is UNDETERMINED with a question, never ELIGIBLE, until B-1 or the pack changes |
| `low_speed_road` | `posted_speed_mph` against `R-LOW-SPEED-CUTOFF` | `R-LOW-SPEED-CUTOFF` | The record has no value, so the fact is UNKNOWN. The code has no number |
| `freeway` | `road_type == EXPRESSWAY_FREEWAY` | registry `freeway` (source_type CODE) | A mapping of the SME's own answer. No new value |
| `traffic_control_method` | Set to FLAGGER when the decision selects TA-10 | `R-TA10-METHOD-FLAGGER` (Sect. 6N.09 para 07, 6P-10) | Fact source CODE, actor router. POLICE_DETAIL never set here |
| `single_flagger_eligible` | Needs a "short zone" length | `R-TA10-SHORT-ZONE` (SRR) | UNKNOWN. Router unaffected; S8 draws two flaggers |
| Remaining-width verdict | `remaining_lane_width_ft` interval against 10 ft (`R-6N07-REMAINING-WIDTH`, `R-TA6-N1`) and 9 ft option (`R-6N07-NINE-FT-OPTION`, `R-TA6-N4`); the 9 ft option needs `low_speed_road`, so it is UNKNOWN today | those ids | Feeds the TA-6 condition `E-TA6-REMAINING-WIDTH` and the contradiction check |
| Contradictions with start fields | `lane_closure = False` with remaining width below 10 ft, or with `work_location = IN_LANE`; `lane_closure = True` with `work_location = BEYOND_SHOULDER` | `R-6N07-REMAINING-WIDTH`, `E-TA10-IN-LANE`, `E-TA1-NO-LANE-CLOSURE`, `E-TA1-BEYOND-SHOULDER` | A `MANDATORY_CONTRADICTION` question. The field is never changed |

The router does not read `ta_hypothesis` to decide eligibility. It reads it only afterward, to compare (CLAUDE.md rule 7).

### Call 2 field set (pack-driven)

Call 2 is built after the provisional router pass. Its fields are the union of (0) the deciding facts that the what-if test marks as deciding and that are unresolved or in conflict, (a) fields in the eligibility expressions of the chosen TA `T` (when no TA is chosen yet, of the still-UNDETERMINED TAs, at most two), (b) fields in the conditions of rules with `ta_id == T` or `ta_id is None` that the effective-rules view marks as applying to `T`, (c) fields the sequence devices need (`arrow_board_present`, `shoulder_closed_ft`). Remove fields already RESOLVED **unless they are in conflict**. The lane count is added whenever the list is not empty and never makes it non-empty (D-121). Classify each by registry `source_type`:

| source_type | Resolved by |
| --- | --- |
| `SME_UI`, `SME_FORM` | The SME form. Not asked of the AI |
| `CODE` | Code (S6 or S7 derived). Not asked of the AI |
| `AI`, `AI_CROSSCHECKED` | Call 2 |
| `AI_THEN_SME` | Call 2, then the SME confirms (D-69 pattern) |
| `CODE_AND_AI` | Call 2 for marks, then code |
| `CODE_THEN_SME_REVIEW` | Code now; the SME review action later (`traffic_control_method`) |

Expected content (derived from the pack today, not hardcoded):

| TA | Call 2 fields | Code or SME fields (not call 2) |
| --- | --- | --- |
| TA-1 | `behind_barrier`; marks for `distance_from_edge_ft` and `distance_behind_curb_in` | `median_work` is AI_CROSSCHECKED, so also call 2; `duration` from the form |
| TA-6 | `opposite_shoulder_suitable`; marks for `shoulder_width_ft` | `heavy_vehicles`, `duration` from the form |
| TA-10 | `approaching_lanes_one` | `curve_or_crest_near_zone`, `grade_crossing_present`, `single_flagger_eligible` are CODE; `night_work`, `duration` from the form |
| TA-33 | `closed_lane_side`, `lanes_closed_count`, `positive_barrier_present`, `ramp_present` | `side_road_in_zone`, `shoulder_closed_ft`, `median_width_ft` are CODE (marks from crops); `arrow_board_wanted` from the form |

Also asked: the weak marks (`lane_line`, `shoulder_edge`, `curb`) when the width is UNKNOWN, and the sidewalk pair when UNKNOWN (B-7). `lanes_per_direction` is no longer a separate re-ask with a lane-marking crop: it is the lane-count field of D-121, observed blind at fine zoom whenever call 2 runs. A config switch turns it off (FS-02 decides later whether to keep it).

**Blind rule (D-120).** The request builder has no parameter that carries the OSM value, the call-1 value or any code value for `lanes_per_direction`, `divided_highway`, `shoulder_present` or `oneway`. Before the call, code re-measures the views at fine zoom (D-112); the measurements are not shown to the model either.

Budget: the request builder refuses to build a second call 2, and the stage asserts `calls_used <= 2`. When the list of AI fields, not counting the lane count, is empty, **no call is made** and the stage records "call 2 not needed" (D-121).

### Merge and disagreement check

| Situation | Result |
| --- | --- |
| Field UNKNOWN before, call 2 RESOLVED | Filled, except for `lanes_per_direction`, `divided_highway`, `shoulder_present` and `oneway`: two AI reads never count as two sources, so a single-source safety fact stays UNKNOWN until OSM agrees (D-92, D-119). Source IMAGERY_CALL2, evidence kept |
| Field UNKNOWN before, call 2 UNKNOWN | Stays UNKNOWN; reason updated |
| Field RESOLVED before, call 2 gives the same value | Unchanged. Agreement recorded |
| Field RESOLVED before, call 2 gives a different value (call 1 and call 2 disagree) | The field becomes UNKNOWN with reason `CROSS_VIEW_DISAGREEMENT` (or CONFLICT, per S6's vocabulary) and goes to the SME (D-123). Both values and evidence are kept as candidates. A resolved value is never silently replaced |
| Field RESOLVED before, call 2 says UNKNOWN | Unchanged. Silence does not un-resolve |
| Mandatory start field in the result | Ignored and logged. Never written |

After the merge, the second fusion runs and then `route(stage="FINAL")` on the merged facts. If its outcome differs from the PROVISIONAL outcome, **the TA does not switch automatically** (ADR-022): the decision becomes `DECIDING_FACT_UNKNOWN` or `TA_SELECTION_CONFLICT` with a question for the SME (B-5). Whether this confirm pass counts toward the "router may re-run at most once" limit in plan section 7 is for S10; S7 stores `inputs_hash` and `stage` so S10 can count.

---

## 5. Commit sequence

Branch `tcp-mvp/s07-router`, off the S6 branch. Commits are small; **[B]** marks groups that can go in one commit or be reviewed together.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF` to the last S6 commit, empty `APPROVED` (as S3 commit `9d43f8f`) | [B] with 1 | Housekeeping |
| 1 | `router` config section and guard update; outcome constants | [B] with 0 and 2 | Non-regulatory D-33 values already approved |
| 2 | `routing/models.py`: Pydantic models, `schema_version`, JSON schema check, `Question` extension | [B] | Plumbing; no behaviour |
| 3 | `routing/facts_view.py`: deciding-field derivation from the pack, status, confidence and uncertainty gating, enum normalisation | **[STOP]** | Decides which facts the router may believe. Safety-critical. Also fixes the `work_location` vocabulary (A-1, B-6), which is read from images |
| 4 | `routing/derived_facts.py` | **[STOP]** | The remaining-width interval test and the `low_speed_road` UNKNOWN behaviour are safety-critical numbers |
| 5 | `routing/router.py` plus `rule_pack_eval` `determinations` parameter, near match, hypothesis rules, the five outcomes, the two passes (PROVISIONAL, FINAL) and the what-if test (`routing/whatif.py`, name proposed) | **[STOP]** | The router is the safety gate. Review the outcome table, the "strict MATCH_ONE" rule and the thresholds |
| 6 | `routing/consistency.py`: mandatory-field contradictions | [B] with 5 for review | Questions only; no write |
| 7 | TA-10 sets FLAGGER (code) with trace | [B] with 5 | One rule id |
| 8 | `routing/call2_plan.py`: pack-driven field set (deciding facts from the what-if test, chosen-TA fields, conflicts, lane count when call 2 runs), class split, fine-zoom crop specs, budget guard, the blind-request rule. **No AI call** | **[STOP]** | Crop specs and which facts are asked of an image |
| 9 | `ai/call2.py`: prompt, schema, Pydantic validation, fake-provider tests, replay through the fixture harness | **[STOP]** | The prompt and the schema are the contract with the model; the owner reads the exact text |
| 10 | `routing/merge.py`: merge, the call 1 and call 2 disagreement rule, the second fusion, the FINAL pass | **[STOP]** | The un-resolve rules for safety-critical facts |
| 11 | `orchestration/route_stage.py` and the `pipeline.py` insertion; artifacts, events, zone `ta` update | **[STOP]** | Any change to the 13 offline scenarios' stored expected outputs (D-83) needs a diff review. See B-4: with option A there is no such change |
| 12 | Tests not yet added: golden-fixture router tests, property test, replay determinism, no-live-call guard, the generality tests (T-16, T-17) | [B] | Tests follow each commit; this one only completes the set |
| 12a | `closed_lane_side` never defaults to RIGHT; the D-59 fixes in `site_model/fusion.py` (the OSM `maxspeed` fallback; the encroachment override of the SME's lane closure) | **[STOP]** | The fixes change engine behaviour that CLAUDE.md lists as breaches; diff review |
| 13 | `docs/reports/S7_router_report.md` (files changed, tests, results, contradictions, open questions) | [B] | Required finish (CLAUDE.md) |

Every commit runs the applicable suites. The gate for the slice: the suites green, the new tests green, replay deterministic. The golden comparator is not part of the gate until S13.

---

## 6. Client inputs and decisions: what S7 consumes

**Client inputs** (facts only the client or its SME can supply; at run time or by answering a pack question):

| Input | Where it enters | Status |
| --- | --- | --- |
| `road_type`, `posted_speed_mph`, `traffic_volume`, `lane_closure` | UI, per project or per point (D-59) | Never filled by code |
| `ta_hypothesis` | UI "Select TA" | Optional, default AUTO |
| Low-speed cutoff; "minor road"; short TTC zone; 6N.11 undivided reading; edition applied | Answers to pack questions | UNKNOWN or SOURCE_REVIEW_REQUIRED today (A-1 to A-5 below) |

**Decisions** (design choices that are the owner's): B-1 to B-9 below. I have not decided any of them.

**Amendments 2026-10-31 (sections 1, 3, 4, 7 and 10).** Section 1: scope item 1 read "returns exactly one of five outcomes" with one router pass; item 6 read "the merge (never overwrites a resolved fact), and the cross-view check (can only un-resolve)" and listed the `lanes_per_direction` lane-marking re-ask; acceptance 1 read "Only Colorado can auto-route today ... Granite stays UNDETERMINED on `E-TA33-FORM-UNDIVIDED-6N11`"; acceptance 6 read "Call 2 never overwrites a resolved fact"; acceptance 7 read "Call 2 is skipped when nothing AI-observable is missing" (D-119 to D-123, D-91, D-128). Section 3: the stage names were INITIAL and CONFIRM; `known_facts` read "resolved facts the model must not contradict silently" (D-120, D-128). Section 4: the call 2 field set was the chosen TA's missing fields plus the D-80 re-asks, the budget line read "When the list of AI fields is empty, no call is made", and the merge table kept the original value on a disagreement for non-deciding fields (D-121, D-123). Section 7: T-10 and T-13 are reworded; T-16 to T-19 are new; the Granite row read "`DECIDING_FACT_UNKNOWN`, TA-33 the only candidate, question on 6N.11" (D-91). Section 10: A-4 and B-2 are annotated (D-91, D-119).
---

## 7. Tests

All with recorded fixtures or fakes. No live call. The network stays blocked.

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | **Outcome matrix**: all five outcomes, the hypothesis table (3.2) and near match | Facts built from synthetic fact sets |
| T-2 | **Pack-driven branches**: each branch of the plan's routing tree reproduced by facts alone: beyond shoulder gives TA-1; on shoulder with a shoulder gives TA-6 candidate; in lane with one lane each way gives TA-10; in lane with divided or undivided multi-lane gives TA-33 candidate; anything else gives NO_TA_MATCH | A test also asserts the router source holds no TA ids and no regulatory numbers (string scan) |
| T-3 | **Exhaustive small-domain property test**: enumerate every combination of the deciding facts over their enum values plus missing; assert (a) `MATCH_ONE(t)` implies `evaluate_eligibility(t)` is ELIGIBLE and no other TA is ELIGIBLE or UNDETERMINED, (b) never two ELIGIBLE with `MATCH_ONE`, (c) `NO_TA_MATCH` names only pack TAs | Covers "never a wrong TA silently" and "TA-33 never double-matches" |
| T-4 | **Gating**: low confidence, UNKNOWN, CONFLICT, straddling interval, SME-source fact skipping the confidence check | Includes the D-38 interval case at exactly 10 ft and 9 ft |
| T-5 | **Unsourced conditions stay questions**: TA-6 with every other condition true is UNDETERMINED with the pack's SME questions; undivided TA-33 likewise; neither becomes ELIGIBLE by default | Checks the exact unsourced list from the S4 test |
| T-6 | **Mandatory fields never written**: after `route`, the start fields are byte-identical; contradictions produce questions | CLAUDE.md rule 4 |
| T-7 | **TA-10 sets FLAGGER**; no other TA sets a method; POLICE_DETAIL never produced | D-68 |
| T-8 | **Hypothesis**: each of the four TAs against facts that fit, fail, or are unknown; the hypothesis never changes eligibility | CLAUDE.md rule 7 |
| T-9 | **Test-only pack variant** for TA-6 on a high-speed road and the 9 ft option: a copy of the pack under `tests/fixtures/` with a clearly labelled placeholder cutoff, never under `rule_pack/` | Needed because the real pack has no cutoff (B-9). The variant is re-sealed in the test and named `TEST_ONLY` |
| T-10 | **Call 2 request builder**: for each TA the field list equals the pack-derived set (deciding facts from the what-if test, chosen-TA fields, conflicts); fields with `SME_*` or `CODE` classes never reach the AI; no mandatory field; an empty list, not counting the lane count, means no call; the lane count never causes a call | |
| T-11 | **Budget**: a second call 2, or a third call in a zone, raises; counted from the zone run record | |
| T-12 | **Schema**: flat facts list; every property required; no union, no `minimum`/`maximum`; a result with a length-like field fails (D-64); case-insensitive enums; malformed fact becomes UNKNOWN | |
| T-13 | **Merge and disagreement**: every row of the merge table; mandatory field in the result ignored; call 1 and call 2 disagreeing gives UNKNOWN; a FINAL pass that changes the outcome never switches the TA | |
| T-14 | **Determinism and replay**: same inputs give the same decision hash; fixture replay gives the same call 2 request fingerprints twice | |
| T-15 | **Store-only access**: the router reads the pack only through `RulePackStore` (extend the S4 isolation test) | |
| T-16 | **What-if test**: each unresolved fact is marked deciding when changing it over its registry domain changes the outcome set, otherwise not deciding; a not-deciding candidate question is informational, a deciding one is blocking | D-128, D-156 |
| T-17 | **Generality**: (a) a made-up TA added to a test pack under `tests/fixtures/` routes, plans call 2 fields and runs the what-if test with no code change; (b) a string scan finds no TA id in the router, the fusion or the call-2 code | D-128, FS-11 |
| T-18 | **Blind call 2**: the built request holds no OSM, call-1 or code value for lanes, divided, shoulder or one-way, on every path that builds it | D-120 |
| T-19 | **`closed_lane_side` and D-59**: an unknown side keeps TA-33 UNDETERMINED and never becomes RIGHT; with the `maxspeed` fallback and the encroachment override removed, the SME's start fields are byte-identical after a run | S4b follow-up c; CLAUDE.md rule 4 |

### Comparison with the three reference jobs

The reference jobs are comparison material. The expected TA is a test expectation, never an input.

| Job | Fact set used | Expected router result with the real pack | What is compared |
| --- | --- | --- | --- |
| Colorado St (TA-10 in the draft) | Start fields `URBAN_LOW_SPEED`, 25 mph, volume and `lane_closure = True` typed as test inputs from the draft's notes; facts: `IN_LANE`, `lanes_per_direction = 1`, `oneway = False`, `divided_highway = False` | `MATCH_ONE`, TA-10, `traffic_control_method = FLAGGER` | TA equals the golden TA. No W20-7 versus W20-8 comparison here (S8/S13) |
| E Second St (TA-6) | `ON_SHOULDER_OR_ENCROACHING`, `shoulder_present = True`, `lane_closure = False`, remaining width interval | `DECIDING_FACT_UNKNOWN` with TA-6 as the single candidate and two open items: `E-TA6-MINOR-ROAD` (an unsourced condition, with its SME question) and `low_speed_road` (a fact that is UNKNOWN because `R-LOW-SPEED-CUTOFF` has no value) | TA-6 is the only candidate; the open items equal the S4 unsourced list |
| Granite St (TA-33) | `IN_LANE`, `lanes_per_direction = 2`, `divided_highway = False`, `lane_closure = True`, `closed_lane_side = RIGHT` (stated, never defaulted) | `MATCH_ONE`, TA-33, through the sourced `E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT` branch, when the lane count is two-source; **TA-10 must be NOT_ELIGIBLE**. With the lane count single-source, `DECIDING_FACT_UNKNOWN` with TA-33 as the only candidate | The unstable-lane case: feed the three spike responses (Granite 2, 1, 1). With `lanes_per_direction = 1` from the model alone, TA-10 would match. The router must not auto-select unless S6 passes a cross-checked fact (A-1(d), B-3). The test shows both behaviours and fails if a lone `1` auto-routes |

Fact sets are hand-written and marked synthetic, or taken from the saved spike responses in `tcp-mvp/s00-schema-spike` (`git show`, copied into `tests/fixtures/` with their sha256). Real-KML recordings come after S6 (CLAUDE.md); call 2 fixtures are question B-8.

---

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S4 rule pack, `RulePackStore`, `rule_pack_eval` | Everything | Merged in this worktree |
| S2 stores | Artifact and state writes | Merged here |
| S3 zone input (`zone.inputs`, `ta_hypothesis`, `start_fields`) | Context | In progress. ASSUMPTION A-3: `projects.zone_engine_input` shape as in commit `cc268af` |
| S6 facts | The whole input | Planned elsewhere. ASSUMPTIONS A-1, A-2, A-4, A-5 |
| S5 | Not needed by the router | Call 2 does not need device ids |

Feeds: S8 (the `RoutingDecision`, derived facts), S9 (`ta` for pass 2), S10 (decision and its `inputs_hash`), S11 (questions).

---

## 9. What could go stale if S6 changes

| S6 change | What breaks in S7 |
| --- | --- |
| `SiteFact` field names, vocabulary or enum values (A-1) | `facts_view` normalisation; T-2 and T-3 fact sets; the `work_location` mapping (B-6). Most likely break |
| Uncertainty representation (`{lo, hi}` versus value plus or minus) (A-1c) | Gating in 3.5 step 3 and the straddle test T-4 |
| The `lanes_per_direction` cross-check policy (A-1d), or a new `cross_check` attribute on facts | The strictness rule in B-3 and the Granite test |
| Facts list schema: `unit` removed, evidence cap, UNKNOWN reason codes (A-2) | `ai/call2.py` schema and T-12 |
| The crop service API (cut, higher-zoom fetch, signature) (A-4) | `call2_plan` crop specs and `route_stage` |
| Where `remaining_lane_width_ft`, `encroachment_depth_ft` and `lane_width_ft` are computed (A-5) | `derived_facts` and the contradiction check |
| Where the "derived facts" live (if S6 already computes `freeway` or `low_speed_road`) | Duplicate computation; one must go |
| Whether call 1 already asks fields that S7 plans for call 2 (`approaching_lanes_one`, `closed_lane_side`) | The call 2 field list (it is subtractive, so a change is cheap) |
| The model and provider (Foundry profile, D-78) | Schema size limits for call 2 |

Not stale: the pack, the eligibility evaluator, the router logic and the outcome contract. They depend on the registry vocabulary only.

---

## 10. OPEN QUESTIONS

Two groups. **A. Client inputs** are facts only the client or its SME can supply; I cannot decide them and the owner may not be the source. **B. Decisions** are design choices that are the owner's. "Blocks" says whether the slice can finish without an answer. All defaults keep the pack unsourced items unsourced.

### A. Client inputs

**A-1. Low-speed cutoff (mph).** `R-LOW-SPEED-CUTOFF`, TA-6 note 2, Sect. 6N.07 para 04.
- Options: (a) the client gives a number and its source; (b) the cutoff is always an SME yes/no per plan; (c) tie it to the SME's `road_type` (URBAN_LOW_SPEED only), which the pack does not say.
- Effects: until answered, `low_speed_road` is UNKNOWN, TA-6 is never ELIGIBLE and the 9 ft option never applies. E Second St cannot route without a question.
- Suggestion: (a) with a cited document; until then leave UNKNOWN.
- Blocks: not S7. Blocks any automatic TA-6 result and the TA-6 golden comparison.

**A-2. Definition of "minor road".** `E-TA6-MINOR-ROAD`.
- Options: (a) a rule from the SME's `road_type`; (b) a later HPMS functional-class lookup (not a start field source, CLAUDE.md); (c) a per-plan SME yes/no.
- Effects: same as A-1.
- Suggestion: (c), recorded as a determination (B-1).
- Blocks: not S7. Blocks automatic TA-6.

**A-3. Longest "short TTC zone" for a single flagger.** `R-TA10-SHORT-ZONE`, TA-10 note 2.
- Options: (a) a length; (b) always an SME choice.
- Effects: `single_flagger_eligible` stays UNKNOWN; the draft shows two flaggers either way.
- Suggestion: (b).
- Blocks: no.

**A-4. Does an undivided road with two lanes each way and the right lane closed qualify for TA-33 (Sect. 6N.11 para 06)?** ANSWERED for the Granite-type case by D-91: `E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT`, `R-6N11-TA33-UNDIVIDED-FOUR-LANE-RIGHT`. Broader undivided cases: `E-TA33-FORM-UNDIVIDED-OTHER`, `R-6N11-TA33-UNDIVIDED-OTHER` (unsourced, an engineer question).
- Options: (a) yes, as read; (b) no; (c) per-plan SME answer.
- Effects: (a) needs a pack change (hash changes) so Granite can auto-route; (b) Granite is NO_TA_MATCH with TA-33 as a near match; (c) Granite is a question each time.
- Suggestion: (c) until the SME has answered the question in the review report; then (a) if confirmed.
- Blocks: not S7. Blocks automatic TA-33 on undivided roads and the Granite golden.

**A-5. MUTCD edition the client applies.** The pack cites the December 2023 file; the POC pack header cites "11th Edition with Revision 1", December 2025.
- Options: (a) December 2023 stands; (b) another edition, with a pack re-extraction.
- Effects: every cited value and page could move. S7 uses only conditions, so the effect is small here and large in S8.
- Suggestion: confirm before S8 starts.
- Blocks: no for S7.

### B. Decisions

**B-1. How an SME answers an unsourced pack question (mechanism).** Affects A-1, A-2, A-4 here and every SOURCE_REVIEW_REQUIRED value in S8. ANSWERED (see decisions section)
- Options: (a) a per-plan `SmeDetermination` record, one plan version only, plan REVIEW_REQUIRED (D-39), with the one-line `determinations` parameter on `evaluate_eligibility`; (b) wait for pack approval (status moves to SOURCED, hash changes); (c) both, with (a) for the plan and a proposal to promote to the pack (D-28).
- Effects: with (b) alone no TA-6 or undivided TA-33 plan can be drafted until the pack is updated.
- Suggestion: (c).
- Blocks: not S7's router commits. Blocks drafting E Second St and Granite end to end (S8 and S13).

**B-2. Should call 2 run when no TA is chosen yet?** CLAUDE.md says call 2 covers only the chosen TA's missing fields. D-80 says call 2 re-asks `lanes_per_direction`, which is a deciding fact when it is UNKNOWN. ANSWERED (see decisions section; reworked by D-119 to D-123 and D-128: call 2 follows the provisional pass and covers the deciding facts, the chosen TA's fields and the conflicts)
- Options: (a) skip call 2 and ask the SME; (b) run call 2 for the deciding AI-observable unknowns of the still-UNDETERMINED TAs (at most two TAs), then route again; (c) run call 2 for the lane count only.
- Effects: (a) means a disagreeing lane count always reaches the form; no AI help. (b) uses the one call 2 before the TA is known, so TA-specific fields may stay unresolved and go to the form. (c) is a subset of (b).
- Suggestion: (b), recorded as an interpretation of CLAUDE.md that the owner approves.
- Blocks: commit 8 (field-set rules). Not the router.

**B-3. Auto-select confidence and cross-check strictness.** ANSWERED (see decisions section)
- Options on thresholds: (a) 0.85 for every deciding fact of the matched TA, 0.80 for other safety-critical facts; (b) 0.85 for all deciding facts; (c) 0.80 for all.
- Options on cross-check: (a) a deciding fact that is safety-critical (every deciding field: lane count, divided, oneway, work location) auto-selects only if S6 marks it cross-checked (two sources agree); (b) a single-source value auto-selects if it passes confidence.
- Effects: (b) allows the Granite `lanes_per_direction = 1` case to route to TA-10 when OSM is silent.
- Suggestion: thresholds (a); cross-check (a) strict. A wrong automatic TA costs more than one extra question (plan section 6).
- Blocks: commit 5.

**B-4. Pipeline integration and cutover.** The pipeline still runs the POC TA-1 path on the POC pack (`routing/eligibility.py`, `layout/rule_engine.py`). The S4 report says the switch is a code change in S7 or S8. ANSWERED (see decisions section)
- Options: (a) S7 adds a **non-gating** route stage that writes `routing_decision.json` and updates the zone `ta`; the pipeline decision and all stored expected outputs are unchanged; S8 does the cutover; (b) S7 gates the pipeline on the router, so a zone that routes to TA-6, TA-10 or TA-33 stops with "layout not yet built" until S8; (c) keep the POC path until S13.
- Effects: (a) lets S7 land without touching the byte-exact oracles (D-83). (b) changes stored outputs now. (c) leaves two paths, which D-32 forbids.
- Suggestion: (a).
- Blocks: commit 11.

**B-5. Hypothesis and TA stability.** ANSWERED (see decisions section)
- Options: (a) as 3.2: conflict only when the hypothesis is NOT_ELIGIBLE; the TA never switches after call 2 without the SME; (b) also raise a conflict when the hypothesis is UNDETERMINED and another TA is ELIGIBLE.
- Effects: (b) adds a question earlier but treats a missing fact as a conflict.
- Suggestion: (a).
- Blocks: commit 5.

**B-6. `work_location` vocabulary and who maps it.** The spike's call 1 enum (`ROADWAY|SHOULDER|BEYOND_SHOULDER|SIDEWALK`) is not the registry's (`BEYOND_SHOULDER|ON_SHOULDER_OR_ENCROACHING|IN_LANE`). "Encroaching" needs the remaining width. ANSWERED (see decisions section)
- Options: (a) S6 emits registry values (code decides IN_LANE versus ON_SHOULDER_OR_ENCROACHING from marks and widths; the AI only observes); (b) S7 maps in `facts_view`; (c) change the registry.
- Effects: (b) puts a safety-critical mapping in two places. A SIDEWALK value has no pack meaning.
- Suggestion: (a). SIDEWALK or anything else not in the registry becomes UNKNOWN.
- Blocks: commit 3 (needs an S6 contract).

**B-7. Sidewalk fields in call 2 (D-80 item 3).** No v1 rule uses `sidewalk_present` or `sidewalk_side`, and the pedestrian module needs Sect. 6G.10, which is not loaded (S4 review). ANSWERED (see decisions section)
- Options: (a) implement the request and merge now, store the facts unused; (b) defer until 6G.10 is loaded; (c) implement now but only as context for the SME form.
- Effects: (a) costs crop area and tokens for no rule.
- Suggestion: (b).
- Blocks: no.

**B-8. Call 2 fixtures.** CLAUDE.md allows live calls only in S13, the S0 spike and the one post-S6 recording. Call 2 did not exist at that point. ANSWERED (see decisions section)
- Options: (a) S7 uses hand-written fake responses only; the real-KML recording is run after S7 merges so call 1 and call 2 are recorded together; (b) record now as a separate live task; (c) fakes only until S13.
- Effects: (a) changes the timing of the "once, after S6" recording; the owner must confirm that is still one recording. (c) means no real call 2 until S13.
- Suggestion: (a).
- Blocks: the replay-on-real-fixtures part of T-14 only.

**B-9. Test-only pack variant for TA-6 high-speed and the 9 ft option.** The slice criterion cannot be tested on the real pack (A-1). ANSWERED (see decisions section)
- Options: (a) a test pack variant under `tests/fixtures/` with a clearly labelled placeholder cutoff; (b) drop the criterion until A-1 is answered; (c) test it with an SME determination (B-1).
- Effects: (a) risks someone reading the placeholder as a value; mitigated by its name, location and a test that the real pack still has no cutoff.
- Suggestion: (c) if B-1 is approved, else (a).
- Blocks: no.

### Summary table

| # | Question | Group | Blocks S7? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | Low-speed cutoff (mph) | Client input | No (blocks auto TA-6) | A number with a source; UNKNOWN until then |
| A-2 | "Minor road" definition | Client input | No (blocks auto TA-6) | Per-plan SME yes/no |
| A-3 | Short TTC zone length | Client input | No | Always an SME choice |
| A-4 | 6N.11 undivided four-lane reading | Client input | No (answered for the Granite-type case, D-91; broader cases stay an engineer question) | Per-plan answer for the broader cases |
| A-5 | MUTCD edition applied | Client input | No | Confirm before S8 |
| B-1 | How an SME answers an unsourced question | Decision | Not the router; blocks end-to-end drafts of E Second St and Granite | Per-plan determination plus a promotion proposal |
| B-2 | Run call 2 when no TA is chosen | Decision | Commit 8 | Deciding AI unknowns of the undetermined TAs |
| B-3 | Confidence and cross-check strictness | Decision | Commit 5 | 0.85 / 0.80; strict cross-check |
| B-4 | Pipeline integration and cutover | Decision | Commit 11 | Non-gating stage; S8 cuts over |
| B-5 | Hypothesis and TA stability | Decision | Commit 5 | Conflict only when NOT_ELIGIBLE; never auto-switch |
| B-6 | `work_location` vocabulary owner | Decision | Commit 3 | S6 emits registry values |
| B-7 | Sidewalk fields in call 2 | Decision | No | Defer until 6G.10 is loaded |
| B-8 | Call 2 fixtures and recording timing | Decision | Part of T-14 | Fakes now; record after S7 |
| B-9 | Test-only pack variant for TA-6 | Decision | No | SME determination if B-1, else variant |
