Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md; where they differ from this plan, the register wins.

# S10 plan: conflicts and exceptions, the exception ladder, the approver role

Planning only. Branch when built: `tcp-mvp/s10-conflicts`, off `tcp-mvp/s09-grouping`. The slice order runs S10 beside S12, and S10 depends only on S8. Branching off S9 avoids a merge of `projects.py` and the status roll-up (question 16). Written on `tmp/plan-base3` (S1 to S4 merged). Nothing here is approved until the owner says so. Module and file names are proposals.

Read for this plan: CLAUDE.md; slice specs S8, S10, S11; plan sections 1, 7, 8, 10, 11, 12, 15, 16 (D-13 to D-17, D-24, D-28, D-29, D-39, D-57, D-59, D-65), ADR-019, -020, -021, -022, -033; `S0_repo_report.md` items 16, 17, 18, 29; `S3_orchestrator_report.md` (named follow-ups 2 and 3); `S4_rule_pack_review.md` (deviation layer, proposal for open question 15); `docs/plans/S5_plan.md` to `S8_plan.md` (copies); code: `conflicts/sme_disposition.py`, `review/action_policy.py`, `config/assistant/SME_ACTION_POLICY.json`, `review/assistant/core/{identity,authz,audit}.py`, `review/assistant/services/{exception_tools,versions,decisions}.py`, `review/decision_overlay.py`, `review/revision_derivation.py`, `review/plan_adjustments.py`, `orchestration/project_runner.py` (cap approval), `config/assistant/users.example.json`.

Owner constraints applied here:
- **MUTCD only.** Rules come from the MUTCD Chapter 6 (December 2023) only.
- **Roles.** Roles are a dropdown with no login: **SME reviewer**, with the full chat assistant, and **Approver**, who approves changes and the zone cap. Every action is audited as "role selected, not verified". Real login comes before client use and is planned in S11.
- **Two-source rule.** Safety-critical fields need two agreeing sources or become UNKNOWN.
- **6N.11.** The Granite-type case is sourced. Broader cases go to the engineer.
- **Cap approval.** It is recorded as "approved (not verified)".
- **Decide per job.** These decisions are review-form questions with safe defaults, and the plan is "needs review" until they are answered. That is S11's form, but S10's status labels must carry it.

Legend: **[B]** can be batched with the next commit. **[STOP]** stop for owner review. **A-n** is an assumption about S6 to S9 shapes, listed again in section 9.

---

## 1. Scope and acceptance criteria

### In scope

1. **`GEO-SIGN-OBSTRUCTION` for every TA** (D-13, ADR-020). S8's plan already detects overlaps in `LAY-OBSTRUCTION` and emits a `PlacementFailure`. S10 makes that the single check under the plan's id (question 13), adds obstructions from every source S6 provides, and sends low-confidence obstructions to the SME instead of acting on them (D-17).
2. **The ladder** (plan Section 7, ADR-019), run per `PlacementFailure` and per failed validator check:
   - **Step 1, move within a sourced band.** Warning signs only. An upstream search for the nearest clear spot. The result is `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT` only when the band has an authority source (D-15).
   - **Step 2, work-fact change.** Detect computed, judged and declared changes (plan Section 7 table). Propose the new fact. The SME confirms, and the router runs again **at most once**.
   - **Step 3, SME exception.** One plan version, written reason, failure never turned into a pass.
   - **Step 4, blocked or manual.** The site understanding, conflicts and imagery are handed over. This includes **"go to the engineer"** for TA cases outside the sourced 6N.11 reading.
3. **Taper and buffer protection** (D-24, CLAUDE.md rule 8). The automatic search never moves them, and no band exists for them. An SME may move or resize them by hand. That is a one-off exception for that plan version and is never promotable.
4. **Exception records** scoped to one immutable plan version, with one-click reuse **only on an exact match**, logged as a new approval (D-29).
5. **Pre-approved deviations** (D-14, D-28, ADR-021, ADR-033). The SME proposes and a named approver role approves. Approvals are stored outside the pack as `{record id, pack hash, approver, time}` (S4 proposal for open question 15). **The owner's MUTCD-only rule collides with this** (question 10). S10 builds the workflow, and whether any deviation may enter the pack is the owner's call.
6. **Approver role.** Add `APPROVER` to the existing local identity provider (dropdown, no credentials, `users.local.json`), `authz.py`, the action policy and the API. The zone-cap approval moves from typed text to the Approver role, recorded "approved (not verified)" (S3 follow-up 3). Every action records `authentication_status = "ROLE_SELECTED_NOT_VERIFIED"`.
7. **Status labels** from plan Section 7, `DRAFT_COMPLIANT`, `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT`, `DRAFT_WITH_ENGINEERING_EXCEPTION` and `BLOCKED`, mapped onto the zone decision. Only `DRAFT_COMPLIANT` can be SUPPORTED_AUTO. A `SOURCE_REVIEW_REQUIRED` input forces REVIEW_REQUIRED (D-39). An unanswered per-job decision forces "needs review".
8. **D-59 breach 2** (S3 follow-up). The encroachment override of the SME's `lane_closure` in `site_model/fusion.py:395-399` becomes a conflict question. The value never changes.

### Out of scope

- The question form, rendering, answering and resume (S11). S10 emits `Question` records and exposes deterministic functions.
- Role-specific pages (S11). S10 changes the backend roles and the minimum UI needed for the cap approval to keep working.
- Police detail (future scope, owner). Engineer-designed plans (D-20, future scope). S10 only builds the handover record.
- Any new pack value. Band sizes with no source stay empty (`SOURCE_REVIEW_REQUIRED`).

### Acceptance criteria

The first three rows are the slice spec. The rest are readings this plan adds.

| # | Criterion | How it is checked |
| --- | --- | --- |
| 1 | A tree on a sign spot moves the sign within a band, or raises an exception question | Two tests: with a sourced band (a test deviation record) the sign moves and the status is `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT`. With no band (the real pack: 0 deviations) a question appears with the proposed spot and the options "move as exception", "change a work fact" and "blocked" |
| 2 | The automatic search never moves taper or buffer | `LAY-IMMOVABLE` after the ladder. A forced obstruction on a taper gives a question, never a move. A property test over random obstruction sets |
| 3 | An exception never carries to a new version unless reused on an exact match | New version with identical match key: reuse is offered, and taking it writes a new approval. Any field of the match key changed: no reuse, the question is asked again |
| 4 | Approver permissions: only APPROVER approves a deviation or the zone cap. Only SME_REVIEWER records an exception. Every record says "role selected, not verified" | `authz` tests per route and tool. Audit fields checked |
| 5 | A manual taper or buffer move is an exception with `promotable = false`. A deviation proposal that cites one is refused | Unit tests |
| 6 | The router re-runs at most once per ladder pass. A second switch goes to review | Fake router that flips its result |
| 7 | Low-confidence obstructions are never acted on automatically | An obstruction under the threshold produces a confirm-or-dismiss question and no move |
| 8 | A computed check that contradicts a start field raises a conflict and leaves the field unchanged (D-59) | The S3 breach case: encroachment with `lane_closure = False` keeps False and adds a `MANDATORY_CONTRADICTION` question |
| 9 | A failure is never turned into a pass | `validation_results.json` keeps FAIL. The disposition layer adds `ACCEPTED_WITH_SME_OVERRIDE` beside it (as `sme_disposition.py` does today) |
| 10 | The cap approval is recorded as "approved (not verified)" with the Approver's subject id | S3 cap tests updated (diff reviewed) |

---

## 2. Modules touched

New (under `src/tcp_planner/`):

| Module | Purpose |
| --- | --- |
| `conflicts/models.py` | `ConflictCase`, `BandSearch`, `WorkFactChange`, `ExceptionRecord`, `ExceptionMatchKey`, `DeviationProposal`, `Handover`, `PlanStatus` (section 3) |
| `conflicts/obstruction.py` | `GEO-SIGN-OBSTRUCTION`: wraps S8's detection, adds confidence gating and the low-confidence question (question 13) |
| `conflicts/band_search.py` | Step 1: candidate stations, upstream first, same side, clear of every feature. Applies only with a sourced band. Without one it returns a *proposal* |
| `conflicts/work_fact.py` | Step 2: computed (recompute derived facts after a placement change and compare against router conditions), judged (obstruction overlaps the work area, so a question) and declared (input diff) |
| `conflicts/exceptions.py` | Step 3: exception records, scope, the match key and reuse. Wraps and extends `conflicts/sme_disposition.py` |
| `conflicts/handover.py` | Step 4: `BLOCKED` and `ENGINEER_REQUIRED` handover packages (refs to the site model, conflicts and imagery; no copies) |
| `conflicts/ladder.py` | Runs steps 1 to 4 per case, re-runs validators after any change, and stops at the first step that resolves |
| `conflicts/deviations.py` | Deviation proposals and approvals, stored outside the pack. Promotion per question 10 |
| `conflicts/status.py` | Status labels, mapping to the zone decision, and review reasons (D-39, per-job decisions, `PLACEHOLDER_ASSET`) |
| `orchestration/ladder_stage.py` | Pipeline stage after the layout and validators. Writes `conflicts.json`, `exceptions.json` and `plan_status.json` write-once, and events |

Changed:

| File | Change |
| --- | --- |
| `review/assistant/core/identity.py` | `ROLES` adds `APPROVER`. `audit_fields` sets `authentication_status = "ROLE_SELECTED_NOT_VERIFIED"` for the local provider |
| `review/assistant/core/authz.py` | `APPROVER` permissions: `deviation:approve`, `cap:approve`, `grouping:confirm` (if S9 question 11 says so), `review:read`, `audit:read`. Plus whatever question 1 adds |
| `config/assistant/users.example.json` | An Approver example identity (no credentials) |
| `config/assistant/SME_ACTION_POLICY.json` (hash-verified) | New actions `move_sign_outside_band`, `move_taper`, `move_buffer`, `accept_ta_selection`, `use_closest_ta` (question 9), each `is_exception: true`, reason required. `move_existing_device` stays non-exception for signs inside a sourced band only. `approval_mode` renamed per question 7. Rehash with `python -m tcp_planner.review.action_policy --rehash` |
| `review/action_policy.py` | New action names. `NEVER_OVERRIDABLE` unchanged |
| `conflicts/sme_disposition.py` | Uses `ExceptionRecord` and the match key. Keeps "a FAIL is never turned into PASS" |
| `review/assistant/services/exception_tools.py` | `record_exception` builds an `ExceptionRecord`. `TA_NOT_APPLICABLE` no longer assumes TA-1 (S0 item 18), and the base TA comes from the router's candidates |
| `orchestration/project_runner.py`, `web_api/project_routes.py` | `approve-cap` requires an `APPROVER` session. The record is `{approved_by subject_id, role, verified: false, label "approved (not verified)", zone_count, at}` |
| `site_model/fusion.py` (only if still on the live path after S6 to S8, A-5) | D-59 breach 2: no override, a conflict question instead |
| `orchestration/pipeline.py` | Insert the ladder stage |
| `apps/web/src/...` | Minimum: the cap banner asks for an Approver session. Role pages are S11 |

Not touched: the rule pack (empty deviation layer stays empty unless question 10 says otherwise), the S8 strategies (S10 calls the validators and the layout core, and never edits a strategy).

---

## 3. Data shapes

Every record carries `schema_version`. Persisted references are `{uri, sha256, size, media_type}`. Every actor block is the same:

```
Actor { subject_id, display_name, role SME_REVIEWER|APPROVER|ENGINE, identity_provider "LOCAL_DROPDOWN",
        authentication_status "ROLE_SELECTED_NOT_VERIFIED", verified false, session_id }
```

```
ConflictCase { conflict_id, zone_id, plan_version_id, object_ref ObjectRef, check_id GEO-SIGN-OBSTRUCTION|LAY-*|VAL-*,
  requested {station_ft, side, offset_ft}, blocker {kind TREE|POLE|WALL|PARKED_VEHICLE|DRIVEWAY|INTERSECTION|...,
  feature_id, confidence, sources [IMAGERY|OSM|...], footprint}, object_kind SIGN|TAPER|BUFFER|CHANNELIZER|...,
  ladder [ {step 1|2|3|4, result APPLIED|PROPOSED|NOT_APPLICABLE|NO_BAND|DECLINED, detail} ],
  outcome PLACED_STANDARD|MOVED_IN_BAND|WORK_FACT_PROPOSED|EXCEPTION_PENDING|EXCEPTION_ACCEPTED|BLOCKED|ENGINEER_REQUIRED,
  question_id|null, trace }

ObjectRef { device_id, object_kind, approach, sequence, zone_lineage_key }      # stable across versions (A-2)

BandSearch { object_ref, band {status SOURCED|NONE, deviation_id|null, upstream_max_ft|null, downstream_max_ft|null,
  source_ref_ids []}, search_limit_ft (config, proposal only; question 6), step_ft (config),
  candidates [ {station_ft, clear, blocked_by []} ], chosen|null, rule_distance_ft, actual_distance_ft,
  direction UPSTREAM|DOWNSTREAM, applies bool }                                   # applies only when band.status = SOURCED

WorkFactChange { change_id, kind COMPUTED|JUDGED|DECLARED, field, before, after, crosses [condition_id],
  router_rerun {count 0|1, before_ta, after_ta}, question_id|null }

ExceptionRecord { exception_id, kind SIGN_PLACEMENT|TAPER_MOVE|BUFFER_MOVE|RULE_CONFLICT|TA_SELECTION_KEPT|USE_CLOSEST_TA,
  plan_version_id, zone_id, scope "THIS_PLAN_VERSION_ONLY", object_ref, failed_check_id, rule_id, rule_value, actual_value,
  delta_ft, facts_hash, pack {id, version, hash}, reason (required), actor Actor, created_at,
  match_key, reused_from exception_id|null, promotable bool (false for TAPER_MOVE and BUFFER_MOVE), policy_ref }

ExceptionMatchKey = sha256(canonical { object_ref, failed_check_id, rule_id, requested.station_ft, actual.station_ft,
  rule_value, actual_value, facts_hash, pack.version, pack.hash })              # values as stored strings: no rounding

DeviationProposal { proposal_id, from_exception_ids [], device_class, band {upstream_max_ft, downstream_max_ft},
  conditions, justification, authority PROPOSED_SETTING, source_ref_ids [], proposed_by Actor,
  status PROPOSED|APPROVED|REJECTED|WITHDRAWN, decision {by Actor (role APPROVER), at, pack_hash, reason}|null }

Handover { handover_id, zone_id, plan_version_id, reason BLOCKED|ENGINEER_REQUIRED|NO_TA_MATCH,
  refs {site_model, routing_decision, layout, conflicts, imagery []}, failed_conditions [], message }

PlanStatus { schema_version, plan_version_id, label DRAFT_COMPLIANT|DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT|
  DRAFT_WITH_ENGINEERING_EXCEPTION|BLOCKED, zone_decision SUPPORTED_AUTO|REVIEW_REQUIRED|BLOCKED,
  needs_review bool, review_reasons [SOURCE_REVIEW_REQUIRED:<id>, PER_JOB_DECISION_PENDING:<question_id>,
  PLACEHOLDER_ASSET, GROUPING_RULE_REVIEW_REQUIRED, LOW_CONFIDENCE_OBSTRUCTION, ...],
  would_have_been_supported_auto bool }                                            # read by S11's approval gate (D-65)
```

**Status mapping.** The plan says only `DRAFT_COMPLIANT` can be SUPPORTED_AUTO. A `DRAFT_COMPLIANT` plan with any review reason is still REVIEW_REQUIRED. `BLOCKED` maps to the zone decision BLOCKED, which S3's roll-up counts as NONE (question 15).

---

## 4. How the ladder runs

### 4.1 Order and inputs

The ladder runs per zone, after S8's layout and validators, on the `PlacementFailure` list and on every failed validator check. Cases are processed in a fixed order: by approach, then sequence, then check id. That makes the result deterministic. After every applied change, every validator re-runs, including the cross-zone and image-extent checks (plan Section 7, last paragraph).

### 4.2 Step 1: move within a sourced band

- **Applies to warning signs only.** `movable_by_search = true` in S8's objects. TAPER, BUFFER and WORK_SPACE are never candidates. CHANNELIZER, FLAGGER and ARROW_BOARD follow question 4.
- **Band.** It comes only from an approved deviation record (section 4.6). The real pack has **0 deviations**, and no MUTCD text gives a number. Sect. 6B.04 para 07 says Table 6B-1 distances "should be adjusted for field conditions, if necessary, by increasing or decreasing", and Sect. 6P.01 para 04 says "device spacing may be adjusted", both without a limit. So **with the v1 pack, step 1 never applies a move** (question 3).
- **Search.** The search still runs, to *propose* a spot:
  - It steps from the requested station, upstream first, so warning distance is not reduced.
  - It keeps the same side and checks every feature and obstruction with S8's clearance.
  - It checks the consecutive sign order and the spacing to the next sign (`LAY-ORDER`, `LAY-SPACING` recomputed).
  - It is bounded by `search_limit_ft`, a non-regulatory config value that limits only what is *proposed* (question 6).
- **Result.** With a sourced band and a spot inside it, the sign moves and the status label is `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT`. The trace logs the rule distance and the actual distance. Otherwise the proposal goes to step 2.

### 4.3 Step 2: did a work fact change?

| Kind | Detection | Who confirms | Re-run |
| --- | --- | --- | --- |
| Computed | After any placement or work-area change, recompute S6's derived facts (remaining lane width, encroachment) with S6's functions. A change counts if it crosses a limit in some TA's eligibility condition (evaluated by `rule_pack_eval`, no number in code) | Nobody (arithmetic). The new fact is recorded with source CODE | Router once |
| Judged | An obstruction's footprint overlaps the work area or the work-vehicle footprint (plan example: a tree on the shoulder forces the crew into the lane) | SME question: "Does the work move into the lane?" | Router once after the answer |
| Declared | An SME or user input edit: the reuse signature changes | The person who edited it | Resume (S11) |

**Rules for this step:**
- Moving a sign is never a work-fact change (`plan_adjustments.py` already holds to this).
- A mandatory start field is never changed here. A contradiction is a `MANDATORY_CONTRADICTION` question (D-59).
- **Two-source rule.** A judged change to a safety-critical fact needs two agreeing sources or stays UNKNOWN with a question. Imagery alone does not resolve `work_location`.
- If the router's TA changes, the change is **proposed**, never applied (ADR-022). The SME confirms in S11's TA-change flow.
- If the result would switch again after one re-run, it goes to review with both results shown (question 8 covers S7's confirm pass).

### 4.4 Step 3: SME exception

The SME accepts a named failure for this plan version, with a reason. The SME may also move the sign to the proposed spot, which is an exception when there is no sourced band. The record:
- keeps the failed check id, the rule value and the actual value;
- carries a match key and the scope `THIS_PLAN_VERSION_ONLY`;
- carries the actor, with role SME_REVIEWER and "not verified";
- sets the label `DRAFT_WITH_ENGINEERING_EXCEPTION`.

**Manual taper or buffer moves** use the same record with `kind TAPER_MOVE` or `BUFFER_MOVE` and `promotable = false`, and they are never offered as a deviation (D-24).

**Reuse (D-29).** For a new plan version, the ladder computes each case's match key. If a previous version of the same lineage has an exception with the same key, the question offers "Same as version N, reuse?". Taking it writes a **new** `ExceptionRecord` with `reused_from`. If any key field differs, there is no offer.

### 4.5 Step 4: blocked, manual or engineer

Step 4 is reached in three ways:
- the SME declines the exception;
- the failure is a `NEVER_OVERRIDABLE` condition;
- the router result is a TA case **outside the sourced 6N.11 reading**, such as an undivided road with more than two lanes each way, or a median-side closure on an undivided road. Per the owner, that case goes to the engineer.

It writes a `Handover` with references to the saved site model, routing decision, layout, conflicts and imagery. The plan's label is `BLOCKED` with reason `BLOCKED` or `ENGINEER_REQUIRED`. Engineer-designed plans stay future scope (D-20). Whether a `NO_TA_MATCH` site may use the closest TA as an exception is question 9.

### 4.6 Pre-approved deviations and the approver role

1. **Reporting.** A report groups exceptions by reason, failed check and device class. A recurring pattern may become a `DeviationProposal`. The SME proposes it with conditions, a justification and any source.
2. **Approval.** An Approver approves or rejects it. The decision is stored as a state record with `{record id, pack hash, approver, time}`, and "not verified" is shown. The SME who proposed cannot approve the same proposal (question 2).
3. **Effect.** This depends on question 10:
   - (a) an approved deviation becomes a record in `rule_pack/deviation/` with `authority PROPOSED_SETTING`, and the pack is resealed;
   - (b) it stays outside the pack as a config band read by `band_search`;
   - (c) the workflow exists and nothing can be approved until a MUTCD or client source is supplied.
4. **Exclusions.** A taper or buffer exception is never promotable. Nothing is ever promoted into the federal layer (plan Section 7). An approval voids itself if the pack hash changes (S4 proposal).

### 4.7 Status labels

| Condition (first that matches) | Label | Zone decision |
| --- | --- | --- |
| Any handover | `BLOCKED` | BLOCKED |
| Any accepted SME exception | `DRAFT_WITH_ENGINEERING_EXCEPTION` | REVIEW_REQUIRED |
| Any move within a sourced band | `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT` | REVIEW_REQUIRED |
| Otherwise | `DRAFT_COMPLIANT` | SUPPORTED_AUTO only if `review_reasons` is empty, else REVIEW_REQUIRED |

`review_reasons` collects:
- `SOURCE_REVIEW_REQUIRED` inputs (D-39);
- unanswered per-job decisions ("needs review": buffer, taper choice, optional devices, add-ons);
- `PLACEHOLDER_ASSET` (S5);
- `GROUPING_RULE_REVIEW_REQUIRED` (S9);
- open low-confidence obstructions;
- an unconfirmed `work_side` (D-69).

`would_have_been_supported_auto` is computed with the same rules, ignoring only the D-65 gate. S11 shows it.

---

## 5. Commit sequence

Branch `tcp-mvp/s10-conflicts` off `tcp-mvp/s09-grouping`. Fast tier plus impacted suites per commit. Full suite once, at commit 11.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF` to the S9 tip, empty `APPROVED` | [B] with 1 | Housekeeping |
| 1 | `conflicts/models.py`, `Actor`, schema versions, migrations | [B] | Plumbing |
| 2 | Approver role: `identity.py`, `authz.py`, `users.example.json`, audit fields "ROLE_SELECTED_NOT_VERIFIED"; cap approval needs an APPROVER session and records "approved (not verified)"; S3 cap tests updated | **[STOP 1]** | Authorization changes and S3 test diffs. Needs questions 1, 2 and 12 |
| 3 | `conflicts/obstruction.py` on S8's detection, confidence gating, low-confidence question; one new offline scenario with a tree on a sign spot | **[STOP 2]** | Adds a scenario and a check id to stored outputs (S0 item 16: new expected files, regenerated with `make_expected` and reviewed) |
| 4 | `conflicts/band_search.py`: candidates, upstream-first, order and spacing re-check, proposal-only without a sourced band; `LAY-IMMOVABLE` property test | **[STOP 3]** | Safety-critical: where a warning sign may go. Needs questions 3, 4 and 6 |
| 5 | `conflicts/work_fact.py`: computed, judged, declared; re-run limit; D-59 breach 2 fix (or regression test if the old path is gone) | **[STOP 4]** | Safety-critical facts and the start-field rule |
| 6 | `conflicts/exceptions.py`, `sme_disposition.py`, `exception_tools.py`, policy file actions and rehash; match key and reuse | **[STOP 5]** | Changes a hash-verified policy file and the exception semantics |
| 7 | `conflicts/handover.py`: BLOCKED and ENGINEER_REQUIRED; base-TA exception per question 9 | [B] with 6 for review | Small, same review |
| 8 | `conflicts/deviations.py`: proposal, approval, refusal of non-promotable sources, voiding on pack hash change; effect per question 10 | **[STOP 6]** | Touches the MUTCD-only rule |
| 9 | `conflicts/status.py`: labels, mapping, review reasons, `would_have_been_supported_auto` | [B] with 10 | Pure mapping |
| 10 | `conflicts/ladder.py`, `orchestration/ladder_stage.py`, pipeline insertion, validators re-run after each change; regenerated expected outputs if any change | **[STOP 7]** | Changes stored oracles (D-83). Diff review of every changed expected file |
| 11 | Full suite once, `docs/reports/S10_conflicts_report.md` | [B] | Required finish |

---

## 6. Tests

All offline, with fakes and recorded fixtures.

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | Ladder cases: sourced band and clear spot (moved); sourced band and no spot (exception question); no band (proposal and exception question); judged work-fact change (question); computed change crossing a TA-6 width condition (router once); exception declined (BLOCKED); never-overridable (BLOCKED) | Acceptance 1 |
| T-2 | Taper and buffer protection: random obstruction sets never move a TAPER or BUFFER; a manual move is a `TAPER_MOVE` exception with `promotable = false`; a deviation proposal citing it is refused | Acceptance 2, 5 |
| T-3 | Exact-match reuse: identical key offers reuse and writes a new record; each key field changed alone gives no offer (one parametrized case per field); a new pack hash gives no offer | Acceptance 3 |
| T-4 | Approver permissions: every route and tool against SME_REVIEWER, APPROVER, AUDITOR, ADMIN; self-approval refused per question 2 | Acceptance 4 |
| T-5 | Audit: every record holds `ROLE_SELECTED_NOT_VERIFIED` and `verified: false`; the audit chain stays intact | |
| T-6 | Re-run limit: a flipping fake router re-runs once, then review | Acceptance 6 |
| T-7 | Low-confidence obstruction: no move, a confirm-or-dismiss question; dismiss records the actor | Acceptance 7 |
| T-8 | D-59: encroachment with `lane_closure = False` keeps False and raises the question; start fields byte-identical after the ladder | Acceptance 8 |
| T-9 | FAIL never becomes PASS: `validation_results.json` unchanged by any disposition | Acceptance 9 |
| T-10 | Cap approval: APPROVER session required; record holds subject id, role, "approved (not verified)", zone count; a bigger zone set needs a new approval (S3 rule kept) | Acceptance 10 |
| T-11 | Status mapping: every row of 4.7; `would_have_been_supported_auto` | |
| T-12 | Determinism: same inputs give the same conflicts, exceptions and status bytes | |
| T-13 | No regulatory number in `conflicts/`: grep for pack numbers; a test deviation band changes the result | CLAUDE.md rule 3 |
| T-14 | Engineer handover for an undivided road with three lanes each way and for a median-side closure on an undivided road (synthetic facts) | Owner rule on 6N.11 |
| T-15 | Policy file: hash verifies; a tampered file disables every SME action (fail closed, as today) | |

---

## 7. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S8 `PlacementFailure`, `LayoutResult`, `PlanObject` with `movable_by_search`, validators incl. `LAY-OBSTRUCTION`, `LAY-IMMOVABLE`, the layout core | Every ladder step | Planned. A-1, A-2 |
| S7 `RoutingDecision`, `route()` as a pure function, `SmeDetermination` | Step 2 re-run; base TA candidates | Planned. A-3 |
| S6 derived facts (`remaining_lane_width_ft`, encroachment) as pure functions; obstruction list with confidence and sources | Step 2 computed changes; obstruction gating | Planned. A-4 |
| S9 zone and status roll-up shape | Status mapping into the project | Planned. A-6 |
| S5 `PLACEHOLDER_ASSET` flag | Review reasons | Planned |
| Existing assistant identity, authz, audit, action policy, disposition | Roles and exceptions | In the repo (S0 items 18, 29) |

Feeds: S11 (questions, exceptions, reuse offers, status, approver role), S12 (status label on the sheet), S13 (exception counts in the comparator report).

---

## 8. Client inputs and decisions S10 consumes

- **Client inputs:** who holds the Approver role (R21, plan open question 15), and any document that sets a sign-shift band.
- **SME questions at run time:** low-confidence obstruction (confirm or dismiss), "does the work move into the lane?", the exception question (move, accept, change a fact, blocked), reuse offers, start-field contradictions.
- **Owner decisions:** section 10, part C.

---

## 9. What could go stale if S6 to S8 change

| Assumption | Shape I rely on | What breaks in S10 if it changes |
| --- | --- | --- |
| A-1 (S8) | `PlacementFailure {failure_id, object_id, device_id, requested {station_ft, side}, reason, rule_id, blocker {feature, id}, handoff "S10_LADDER"}` and `PlanObject.movable_by_search`, `status PLACED|GAP|FAILED` (S8 plan 3.2 and 3.3) | `ConflictCase` construction and the taper and buffer guard |
| A-2 (S8) | An object's identity is stable across plan versions when its device, approach and sequence are the same. If S8's `object_id` includes the station, `ObjectRef` is computed by S10 from `{device_id, approach, sequence, lineage}` instead | Exact-match reuse (D-29) would never match |
| A-3 (S7) | `route(pack, zone_ctx, config, stage)` is pure and cheap; `RoutingDecision.inputs_hash` and `stage` exist so a re-run can be counted (S7 plan 4) | The re-run limit and question 8 |
| A-4 (S6) | Obstructions carry `{id, station_m, offset_m, extent_m, confidence, sources}`; derived facts are pure functions callable after a placement change; the two-source rule is applied by S6 and visible on each fact | Gating, judged changes, computed changes |
| A-5 (S6/S8) | After S8's cutover the POC `fusion.py` lane-closure override is either gone or still reachable | Whether commit 5 fixes code or only adds a regression test |
| A-6 (S9) | Zone decisions and roll-up from S3, extended by S9 with `GROUPING_RULE_REVIEW_REQUIRED` | Status mapping and the BLOCKED outcome in the roll-up (question 15) |
| A-7 (S8) | Optional add-ons (sidewalk closed, detours) are objects with the same trace and `movable_by_search` rules; their signs can enter the ladder | Ladder coverage of add-on signs |
| A-8 (S8) | The assistant's preview and revision path (`revision_derivation.derive`) was adapted to S8's strategies at the cutover | `exception_tools` and `sme_disposition` reuse; if not adapted, S10 must adapt them (larger commit 6) |

---

## 10. OPEN QUESTIONS

Three groups: **A. Client inputs**, **B. SME questions**, **C. Owner decisions**. I have decided none.

### A. Client inputs

**1. Who holds the Approver role, and what does "approves changes" cover?** (R21, plan open question 15, owner's role description)
- Options for scope: (a) deviation promotions and the zone cap only; (b) plus grouping settings (S9 question 11); (c) plus every SME exception (a two-person rule); (d) plus the final plan approval (D-65 says an SME click).
- Effects: (c) and (d) put a second click on every non-compliant plan; with no login the second person is not verified either. (a) keeps D-29 ("only an SME accepts an exception") and D-65 as written.
- Suggestion: (a) plus (b); names come from the client.
- Blocks: **commit 2** (permission table).

### B. SME questions

**2. May one person hold both roles, or approve what they proposed?**
- Options: (a) allowed; (b) one identity cannot hold both roles; (c) both roles allowed, but the same subject id cannot approve its own proposal.
- Effects: without login none of these is enforceable against a determined user; they prevent accidents only.
- Suggestion: (c).
- Blocks: commit 2.

**3. The size of the allowed sign shift** (D-24 "still unset"; R8).
- Options: (a) none until a document gives one: every blocked sign is an exception question with a proposed spot; (b) the SME sets a band per job on the form (a decide-per-job question, saved with the plan, one-off); (c) a client document provides a band that becomes a deviation (question 10).
- Effects: (a) makes every obstruction an exception; (b) records a per-job number with no source, which is an exception in all but name.
- Suggestion: (a), with (c) when a document arrives.
- Blocks: commit 4 (the "applies" branch is tested with a test-only band either way).

**4. Which objects the automatic search may move** besides warning signs.
- Options: (a) warning signs only (plan text); (b) plus flagger stations and the arrow board along their own element; (c) plus channelizers along a tangent.
- Effects: channelizers and flaggers sit inside the taper and work space geometry, which rule 8 protects.
- Suggestion: (a).
- Blocks: commit 4.

**5. Low-confidence obstruction threshold and the two-source rule for obstructions.**
- Options: (a) an obstruction acts automatically only when imagery and another source agree (OSM `natural=tree`, `power=pole`); else it is a question; (b) a confidence threshold in config (start value from the router's 0.80 safety-critical class, PROPOSED); (c) always a question.
- Effects: (a) follows the owner's two-source rule but OSM rarely maps trees; most obstructions become questions. (c) asks most.
- Suggestion: (a).
- Blocks: commit 3.

### C. Owner decisions

**6. Search limit for proposals with no band.** A non-regulatory config value that limits how far the search looks for a spot to propose (it never applies a move).
- Options: (a) a config value (for example the spacing to the next sign, so order is kept), labelled `IMPLEMENTATION_DEFAULT`; (b) the next sign's station on each side (no number at all); (c) no proposal, just the question.
- Suggestion: (b).
- Blocks: commit 4.

**7. The approval mode name and what the record says.** Today `approval_mode = "SELF_CONFIRMED_POC"`, `independent_approval false`.
- Options: (a) rename to `SME_CONFIRMED_ROLE_NOT_VERIFIED`; (b) keep the POC name until real login.
- Effects: (a) changes the policy hash and every stored exception's text; (b) keeps "POC" in a production record (S0a follow-up wants POC strings renamed in one commit).
- Suggestion: (a).
- Blocks: commit 6.

**8. Does S7's confirm pass (after call 2) count toward "the router may re-run at most once"?**
- Options: (a) no, the limit counts ladder re-runs only; (b) yes, one re-run per plan version in total.
- Effects: (b) means a zone whose call 2 changed a fact can never re-route after a work-fact change without review.
- Suggestion: (a).
- Blocks: commit 5.

**9. `NO_TA_MATCH` and TA cases outside the sourced 6N.11 reading: closest TA as an exception, or engineer only?**
- Options: (a) engineer handover only (owner: "broader cases go to the engineer"); (b) the SME may draft with the closest TA as an exception (plan Section 7), except for the 6N.11 broader cases, which always go to the engineer; (c) the closest TA as an exception everywhere.
- Effects: (a) leaves more zones without a draft; (c) contradicts the owner's rule.
- Suggestion: (b).
- Blocks: commit 7.

**10. Pre-approved deviations under "MUTCD only".** D-14, D-28 and ADR-021 put SME-proposed, approver-approved bands into the pack's deviation layer; the S4 owner decision keeps the pack MUTCD-only.
- Options: (a) deviations enter `rule_pack/deviation/` with authority `PROPOSED_SETTING` (amends the MUTCD-only rule for that layer); (b) approved bands live in config outside the pack, read by `band_search`, and the plan status stays `DRAFT_WITH_ENGINEERING_EXCEPTION` (no authority source, D-15); (c) build the workflow, allow no approval until a MUTCD or client document is the source.
- Effects: (a) makes `DRAFT_COMPLIANT_WITH_FIELD_ADJUSTMENT` reachable; (b) and (c) mean that label is never produced in the MVP.
- Suggestion: (c), keeping the label for later.
- Blocks: **commit 8**.

**11. Exception reuse key: exact values or rounded?** D-29 says exact match of "object, failed check, distance, facts and pack version".
- Options: (a) exact stored strings; (b) distances rounded to 0.1 ft.
- Effects: (a) can miss a match after a tiny recomputation difference (float drift across machines); (b) is a tolerance D-29 does not give.
- Suggestion: (a), with S8's numbers stored as decimal strings so the same inputs give the same text.
- Blocks: commit 6.

**12. What happens to AUDITOR and ADMIN?** The owner names two roles; the repo has three.
- Options: (a) keep them, read only, not in the default dropdown; (b) keep them in the dropdown; (c) move them to backup in S15.
- Suggestion: (a).
- Blocks: no.

**13. One obstruction check id.** S8's plan already has `LAY-OBSTRUCTION`; the slice and plan name `GEO-SIGN-OBSTRUCTION`.
- Options: (a) S10 renames S8's check to `GEO-SIGN-OBSTRUCTION` (stored outputs change once); (b) keep both, `GEO-SIGN-OBSTRUCTION` as an alias; (c) if S8 did not build it, S10 builds it under the plan's id.
- Suggestion: (a), or (c) if absent.
- Blocks: commit 3.

**14. Where the per-job "needs review" state lives.** The owner defined per-job questions with safe defaults (buffer none, taper unset places no taper, optional devices omitted and listed). They are S8 inputs and S11 form questions.
- Options: (a) S10's `PlanStatus.review_reasons` carries `PER_JOB_DECISION_PENDING` from S8's `LayoutGap` and optional lists; (b) S11 computes it alone.
- Suggestion: (a), so the status is correct before the form exists.
- Blocks: commit 9.

**15. BLOCKED in the project roll-up.** S3 counts a zone as DRAFT, REVIEW or NONE.
- Options: (a) BLOCKED is REVIEW (a draft exists with a handover); (b) BLOCKED is NONE (no usable draft); (c) a fourth outcome and a new project status.
- Effects: (b) makes a project with one blocked zone PARTIAL; (a) keeps it REVIEW_REQUIRED.
- Suggestion: (a): the SME still reviews it.
- Blocks: commit 9.

**16. Branch parent.** Spec order: S10 beside S12, after S8.
- Options: (a) off S9 (this plan); (b) off S8, merge later.
- Effects: (b) runs in parallel with S9 but conflicts in `projects.py`, the roll-up and the cap approval.
- Suggestion: (a).
- Blocks: no.

### Summary

| # | Question | Group | Blocks S10? | Suggestion |
| --- | --- | --- | --- | --- |
| 1 | Approver holder and scope of "approves changes" | Client input | **Commit 2** | Deviations, cap and grouping settings |
| 2 | Both roles in one person, self-approval | SME | Commit 2 | Allowed, no self-approval |
| 3 | Size of the sign-shift band | SME | Commit 4 | None until a document; exception question |
| 4 | What the search may move | SME | Commit 4 | Warning signs only |
| 5 | Obstruction confidence and two sources | SME | Commit 3 | Two agreeing sources, else a question |
| 6 | Proposal search limit | Owner | Commit 4 | Next sign's station |
| 7 | Approval mode name | Owner | Commit 6 | `SME_CONFIRMED_ROLE_NOT_VERIFIED` |
| 8 | S7 confirm pass and the re-run limit | Owner | Commit 5 | Not counted |
| 9 | Closest TA as an exception | Owner | Commit 7 | Yes, except broader 6N.11 cases |
| 10 | Deviations under MUTCD only | Owner | **Commit 8** | Workflow only, no approval until a source |
| 11 | Reuse key exact or rounded | Owner | Commit 6 | Exact decimal strings |
| 12 | AUDITOR and ADMIN | Owner | No | Keep, read only, hidden |
| 13 | One obstruction check id | Owner | Commit 3 | Rename to `GEO-SIGN-OBSTRUCTION` |
| 14 | Where "needs review" lives | Owner | Commit 9 | In `PlanStatus` |
| 15 | BLOCKED in the roll-up | Owner | Commit 9 | Counts as REVIEW |
| 16 | Branch parent | Owner | No | Off S9 |
