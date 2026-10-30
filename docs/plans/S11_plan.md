Status: PLANNED. Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md; where they differ from this plan, the register wins.

# S11 plan: question form, SME review, approval gate (no police switch)

Planning only. Branch when built: `tcp-mvp/s11-review`, off the merge of `tcp-mvp/s10-conflicts` and `tcp-mvp/s12-sheets` (question 16). Written on `tmp/plan-base3` (S1 to S4 merged). Nothing here is approved until the owner says so. Module and file names are proposals.

Read for this plan: CLAUDE.md; slice specs S3, S9 to S13; plan sections 3, 4A, 4B, 7, 8, 9, 11, 12, 15, 16 (D-09, D-10, D-16, D-18, D-29, D-39, D-45, D-55, D-65, D-68, D-69, D-82), ADR-008, -009, -022, -023, -046, -048; `S0_repo_report.md` items 9, 10, 17, 19, 29; `S2_storage_report.md`; `S3_orchestrator_report.md`; `S4_rule_pack_review.md`; `docs/plans/S5_plan.md` to `S8_plan.md` (copies) and `S9_plan.md`, `S10_plan.md` (this round); code: `orchestration/projects.py`, `project_runner.py`, `run_relations.py`, `web_api/project_routes.py`, `review/assistant/services/{clarify_forms,decisions,versions,proposals,review_tools}.py`, `review/assistant/core/{identity,authz,audit}.py`, `review/revision_derivation.py`.

Owner constraints applied here:
- **No police switch.** Flagger is the default, and police detail instead of flagger is future scope.
- **Decide per job.** These decisions are a review-form question for that zone with a safe default, saved with the plan. Until answered, the plan is "needs review". The defaults are:
  - buffer: none;
  - taper unset: no taper is placed;
  - optional devices: omitted and listed.
- **Add-ons.** Sidewalk closed and detours are optional per zone and built in S8. No-parking and RI double fines wait for sources.
- **Roles.** Roles are a dropdown with no login: SME reviewer, with the full chat assistant, and Approver, who approves changes and the zone cap. Every action is audited "role selected, not verified". Real login before client use is **planned in S11**. Pages and components are role-specific.
- **Two-source rule.** Safety-critical fields need two agreeing sources or become UNKNOWN. The 6N.11 Granite-type case is sourced, and broader cases go to the engineer.
- **S3 follow-ups.** A REVIEW_REQUIRED zone gets a draft in S7. Projects get an archive flag later and are never deleted. The cap approval is "approved (not verified)".
- **Test gate.** Fast tier per commit plus impacted suites. The full suite once.

Legend: **[B]** can be batched with the next commit. **[STOP]** stop for owner review. **A-n** is an assumption about S6 to S10 shapes, listed again in section 9.

---

## 0. Contradictions found while planning (stop and report)

| # | Item | What disagrees | Proposed handling (owner decides, question 1) |
| --- | --- | --- | --- |
| C-1 | Police switch | The owner removed it from S11. Still describing it: CLAUDE.md core rule 5 ("Police details are a post-draft SME review action: W20-7 becomes POLICE OFFICER AHEAD"), D-68 and ADR-048, plan Section 4B and Section 8 bullets, slice S11 in scope, slice S13 (`POST_DRAFT_VARIANT`, "compare after applying the police switch") | S11 builds no switch. The owner edits CLAUDE.md, D-68, ADR-048, the S11 and S13 slice text. S13 lists Colorado's W20-7 against POLICE OFFICER AHEAD as a known difference |
| C-2 | "Editing one placemark reruns only its zone" | S3: `project_id` = hash of the usable geometry, so a re-upload with one moved point is a **new project**, and every zone runs again | Question 4: an "edit a placemark" or "replace input" action that keeps the project id |
| C-3 | Sheet reorder, merge and split | The S11 spec lists them, but sheets are S12. The S11 spec's "Depends on" omits S12. The slice order ("S10 and S12 in parallel, then S11") already puts S11 after S12 | S11 branches off S10 + S12 (question 16) |
| C-4 | AI-call budget on a TA change | CLAUDE.md: "at most two AI calls per zone". A TA change after a run that already made call 1 and call 2 makes one more call 2 | Question 7: count per zone run (replayed calls not counted) or per zone lifetime |
| C-5 | Who clicks the approval gate | D-65: "every plan waits for an SME click". The owner's roles: the Approver "approves changes and the zone cap" | Question 5 |

---

## 1. Scope and acceptance criteria

### In scope

1. **One batched form** per project (D-18, ADR-023), with one section per zone and a project section for grouping. It gathers every blocking question from S6 (facts, widths, lanes, start-field conflicts, `work_side`), S7 (deciding facts, unsourced conditions, TA conflict, near match), S8 (layout gaps), S9 (grouping proposals, automatic splits, same TA for all points, `NOT_ON_ROAD`), and S10 (obstructions, exceptions, reuse offers, work-fact changes). It has conditional sub-questions (`show_if`, `reveals`), a reason, and a default if skipped. The questions in plan Section 8 are all present (table 4.2).
2. **Per-job decisions** as form questions with the owner's safe defaults, saved with the plan version:
   - buffer: none;
   - taper length within a range: unset, so no taper;
   - optional devices: omitted and listed with "add";
   - add-ons per zone (sidewalk closed, detour): off.

   While any is unanswered, the plan is "needs review" (REVIEW_REQUIRED with `PER_JOB_DECISION_PENDING`).
3. **Asked-if-needed fields** appear only when a rule of the chosen TA needs them and nothing else determines them. Examples are `duration`, `night_work`, `heavy_vehicles`, `arrow_board_wanted`, `work_type` and `work_space_length_ft`. The fields come from the pack, never a list in code. **`work_side` always appears** as the AI suggestion for the SME to confirm (D-69).
4. **Resume at the earliest affected stage** (plan Section 9). Each answer or review action maps to a stage. The zone reruns from there as a new immutable child run with verified evidence reuse. That means zero external calls when the signatures match.
5. **Review actions**, each a deterministic function with a ledger entry:
   - correct or confirm a fact;
   - resolve a conflict;
   - change the TA (proposed, then confirmed);
   - mark the TA undetermined;
   - regroup: move a point, merge or split zones;
   - reorder, merge or split sheets;
   - adjust placement, or add or remove an approved device, through S10's ladder and exception rules;
   - switch an add-on on or off.

   There is **no police switch** (C-1).
6. **The TA-change flow with an impact preview** (plan Section 8). Before anything changes, the preview shows:
   - the old and new TA;
   - the eligibility difference and the schema difference;
   - the rules affected and the artifacts invalidated;
   - the earliest stage that reruns;
   - the expected AI and map calls;
   - `ANALYSIS_EXTENT_INSUFFICIENT` before any refetch.

   After confirmation, a new immutable version is written.
7. **Zone-level reuse keys** (D-09, ADR-008). A zone's key is its geometry hash plus:
   - the TA and the schema hash;
   - the pack, registry and config hashes;
   - the known facts and inputs;
   - the image context.

   The whole-file KML hash stays for audit only, which addresses S0 item 9's `_dependency_changes`.
8. **Per-zone review with project-scoped history and "inherit"** (D-10, ADR-009). A regroup makes new zones (S9 question 9). An explicit inherit action carries chosen SME decisions from the old lineages, with a ledger entry.
9. **The append-only decision ledger** (plan Section 11): one hash-chained event stream per project. Entries are:
   - input received;
   - grouping decided;
   - TA proposed and confirmed;
   - question asked and answer given;
   - deviation applied and exception granted;
   - version created and plan produced;
   - approval.

   Each entry records the actor ("role selected, not verified"), time, reason, object, and before and after hashes.
10. **The approval gate** `require_sme_approval_for_all_plans`, default `true` (D-65). Every plan version waits for a click and shows whether it would have been SUPPORTED_AUTO. With `false`, only a genuine SUPPORTED_AUTO plan finishes without a click. An approved version is immutable, and any change makes a new version that needs a new approval.
11. **Role-specific pages.**
    - **The SME reviewer page** has the project form, zone review, TA change, regroup, sheets, and the full chat assistant (its tools call the same deterministic functions).
    - **The Approver page** has the zone-cap approval, deviation proposals (S10) and grouping settings (S9 question 11, if chosen).

    The role dropdown has no login, and every action is audited "role selected, not verified".
12. **The real-login plan**, written in this slice (`docs/plans/S11_real_login_plan.md`). It covers the identity provider (the existing `EntraIdentityProvider` placeholder), role mapping, how unverified records stay marked, and a gate that blocks client use while the provider is local. Building it is question 9.

### Out of scope

- The police switch (owner: future scope). Engineer-designed plans (D-20). The pipeline Q&A chatbot (future scope). The SME assistant chat stays as it is, with its tools extended to the new actions.
- Real login itself (question 9). The project archive flag (question 10).
- New pack values. New AI calls beyond call 2 for a TA change. Sheet packing rules (S12).

### Acceptance criteria

Rows 1 to 4 are the slice spec. The rest are readings this plan adds.

| # | Criterion | How it is checked |
| --- | --- | --- |
| 1 | Answering a question resumes with zero new external calls when signatures match | Strict replay (`run_relations` strict mode: every external artifact replays from verified evidence or the run fails closed) with the network blocked and a call counter at 0, for one answer per stage in table 4.3 |
| 2 | A TA change reruns from the router and makes one new call 2 at most | Call counter: 0 map calls, 0 call 1, at most 1 call 2. The preview's predicted counts equal the actual ones |
| 3 | Editing one placemark reruns only its zone | **Depends on question 4 (C-2).** With the chosen action, a 3-zone project with one moved point: one new zone run, the other two zones keep version and run, 0 external calls for them |
| 4 | Regroup resumes only the changed zones; the ledger is append-only | Regroup test with call counts. Ledger tamper test: an edited or removed entry breaks the chain and the reader refuses it |
| 5 | Every blocking question of S6 to S10 appears on the one form with a reason and a default; sub-questions are revealed by their parent's answer | Fixture project with one question of each kind; snapshot of the form spec |
| 6 | Per-job decisions show the owner's defaults; the plan is "needs review" until each is answered; the answer is saved with the plan version | Unit and integration tests |
| 7 | Asked-if-needed fields appear only when a pack rule of the chosen TA needs them; `work_side` always appears | Parametrized over the four TAs |
| 8 | No plan leaves draft without an approval click while the flag is true; the page shows "would have been SUPPORTED_AUTO" | Gate tests for true and false |
| 9 | Each page shows only its role's actions; the backend refuses actions outside the role; every ledger entry says "role selected, not verified" | API and Vitest tests |
| 10 | No code path or UI offers a police switch | Grep test and UI test |

---

## 2. Modules touched

New (under `src/tcp_planner/`):

| Module | Purpose |
| --- | --- |
| `review/form/models.py` | `FormQuestion`, `FormSection`, `FormSpec`, `Answer`, `PerJobDecision` (section 3) |
| `review/form/collect.py` | Gathers and normalises questions from each zone's current artifacts (S6 facts, S7 routing decision, S8 layout gaps and optional lists, S9 grouping, S10 conflicts). Deterministic question ids |
| `review/form/visibility.py` | Asked-if-needed fields from the pack (fields in conditions of rules that apply to the chosen TA, with `source_type` `SME_FORM`, still UNKNOWN). `work_side` always |
| `review/form/answers.py` | Validates an answer against the stored spec (the browser never supplies the spec, as in `clarify_forms.py`), turns it into a declared change |
| `review/resume.py` | The earliest-affected-stage map (4.3), the resume plan per zone, the predicted call counts |
| `review/ta_change.py` | Impact preview and confirmation (4.5) |
| `review/regroup.py` | Move point, merge, split (calling S9's pure functions), new zones, `derived_from`, inherit (D-10) |
| `review/sheets_actions.py` | Reorder, merge, split sheets (calling S12's packer with SME constraints) |
| `review/ledger.py` | Project ledger stream, hash chain (the `AuditService` pattern on a state stream), reader that refuses a broken chain |
| `review/approval.py` | The D-65 gate: approve a plan version, project approval roll-up |
| `review/addons.py` | Per-zone add-on toggles (sidewalk closed, detour) feeding S8 as inputs |
| `web_api/review_api.py` | `GET /api/projects/<id>/form`, `POST .../answers`, `POST .../actions/<action>`, `GET .../ledger`, `POST .../zones/<zid>/versions/<v>/approve`, `GET .../ta-change/preview` |
| `apps/web/src/review/` | `RoleSelect.tsx`, `SmeReviewPage.tsx`, `QuestionForm.tsx` (field types reused from the clarify forms), `ZoneReview.tsx`, `TaChangePreview.tsx`, `RegroupPanel.tsx`, `SheetPanel.tsx`, `ApproverPage.tsx`, `LedgerView.tsx` |
| `docs/plans/S11_real_login_plan.md` | The real-login plan (scope item 12) |

Changed:

| File | Change |
| --- | --- |
| `orchestration/run_relations.py` | Zone-level input hash; `_dependency_changes` and `_input_file` zone-aware (S0 item 9); resume from a named stage |
| `orchestration/projects.py`, `project_runner.py` | Zone versions from review actions; project status `APPROVED` and `PARTIALLY_APPROVED` (question 6); the placemark-edit action (question 4) |
| `review/revision_derivation.py`, `review/decision_overlay.py` | Re-run from the stage the change affects, on S8's strategies and S10's ladder (A-6) |
| `review/assistant/services/*` (tools registry) | SME chat tools for answering form questions and calling review actions; no AI decides; every tool writes a ledger entry |
| `review/assistant/core/authz.py` | Permissions for the new actions per role |
| `config/pipeline_config.json` (guarded) or a project-level config | `review.require_sme_approval_for_all_plans: true` (question 8 on where it lives) |
| `apps/web/src/App.tsx`, `api.ts`, `types.ts` | Role routing; web rebuild |

Not touched: the rule pack, the S8 strategies, S10's ladder logic (S11 calls them).

---

## 3. Data shapes

Every record carries `schema_version`. Persisted references are `{uri, sha256, size, media_type}`. The `Actor` block is S10's:

```
Actor { subject_id, display_name, role SME_REVIEWER|APPROVER|ENGINE, identity_provider "LOCAL_DROPDOWN",
        authentication_status "ROLE_SELECTED_NOT_VERIFIED", verified false, session_id }
```

```
FormQuestion {                                            # extends the shared Question contract
  question_id,                                            # sha256(kind, scope, subject, inputs_hash)[:16]: same question, same id
  scope {project_id, zone_id|null, plan_version_id|null}, kind, source_stage S6|S7|S8|S9|S10|S11,
  reason, answer_type CHOICE|NUMBER|BOOLEAN|TEXT|POINT_SET|TA, options [ {value, label, effect} ],
  default_if_skipped {value|null, label, consequence},    # never a value for an unsourced item
  blocking bool, safety_critical bool, parent_id|null, show_if {question_id, equals}|null, reveals [question_id],
  earliest_affected_stage, evidence_refs [], status OPEN|ANSWERED|SKIPPED|SUPERSEDED }

PerJobDecision { decision_id, zone_id, plan_version_id, item BUFFER|TAPER_LENGTH|OPTIONAL_DEVICE:<device_id>|ADDON:<id>,
  default {value, label}, answer {value, actor Actor, at, reason}|null, rule_ids [], status DEFAULT_PENDING|ANSWERED }

Answer { answer_id, question_id, value, reason|null, actor Actor, at, form_spec_hash, ledger_entry_id }

ResumePlan { zone_id, from_stage, reused [stage + artifact ref], rerun [stage], predicted_calls {map, osm, ai_call1, ai_call2},
  new_zone_version, reasons [] }

TaChangePreview { zone_id, plan_version_id, old_ta, new_ta, router_view {old, new}, eligibility_diff [], schema_diff {added, removed},
  rules_affected [rule_id], artifacts_invalidated [], earliest_stage "ROUTER", predicted_calls, extent_check OK|ANALYSIS_EXTENT_INSUFFICIENT,
  needs_exception bool }                                   # new TA NOT_ELIGIBLE: keeping it is S10's TA_SELECTION_KEPT exception

LedgerEntry { seq, schema_version, entry_id, prev_hash, entry_hash, project_id, zone_id|null, type, actor Actor, at, reason|null,
  object {kind, id}, before_hash|null, after_hash|null, refs [] }

Approval { approval_id, plan_version_id, zone_id, plan_hash, pack_hash, status_label, would_have_been_supported_auto,
  actor Actor, at, gate_flag_value }

ProjectRecord additions { approval_status, archived false (question 10), input_revisions [] (question 4) }
```

Question ids are stable across reruns while their inputs are unchanged, so an answer is not asked again. A changed input supersedes the old question.

---

## 4. How it works

### 4.1 The form

`collect.py` reads the **current** version of every zone and the project's grouping. It normalises each source question into a `FormQuestion` and orders them: project questions first, then zones in sheet order, then each zone's questions in pipeline-stage order. It hides children whose `show_if` is false. The SME answers everything on one screen. Submitting validates every answer against the stored spec. Each answer is a ledger entry, and each answer becomes a declared change. The resume planner groups the changes per zone and runs each zone once from its earliest affected stage. New questions revealed by that run join the same form (plan Section 8 loop).

### 4.2 Questions on the form (plan Section 8 and the slices)

| Question | Source | Default if skipped |
| --- | --- | --- |
| Sheet grouping unclear; grouping proposal; zone split automatically | S9 | Proposed grouping used; REVIEW_REQUIRED |
| Same TA for all points? (reveals one TA per point) | S9 | One TA assumed; REVIEW_REQUIRED |
| Will a travel lane be closed? (a start-field contradiction; the field changes only by the SME) | S6, S7 | Field unchanged; REVIEW_REQUIRED |
| Duration, night work, heavy vehicles, arrow board, work type, work length | Pack rules of the chosen TA | UNKNOWN, flagged; full layout |
| Which TA? (two match); TA contradicts facts; near match | S7 | REVIEW_REQUIRED |
| Unsourced condition (for example the low-speed cutoff, "minor road") | S7 | Stays UNDETERMINED; REVIEW_REQUIRED |
| Width near a threshold; lanes disagree (two-source rule) | S6 | UNKNOWN; REVIEW_REQUIRED |
| `work_side` confirm (always) | S6 | AI suggestion kept, flagged; REVIEW_REQUIRED |
| Buffer (per job) | S8 | None; "needs review" |
| Taper length within 50 to 100 ft (per job) | S8 | Unset, no taper placed; "needs review" |
| Optional devices (per job, one line each, "add") | S8 | Omitted and listed; "needs review" |
| Add-ons: sidewalk closed, detour (per zone) | S8 | Off; "needs review" |
| Sign blocked, no sourced band; reuse offer | S10 | BLOCKED |
| Low-confidence obstruction | S10 | Left flagged |
| Does the work move into the lane? | S10 | Unchanged; REVIEW_REQUIRED |
| `NOT_ON_ROAD`, which road | S9 | Kept and flagged |

### 4.3 Earliest affected stage (plan Section 9)

| Change | Reruns from | Reused (verified evidence, zero calls) |
| --- | --- | --- |
| Zone geometry or grouping | Fetch map and OSM, changed zones only | Other zones entirely |
| Common fact corrected | Fusion | Imagery, map, OSM, call 1 |
| TA changed (confirmed) | Router, then call 2 with the new schema | Imagery, fused common facts, map, call 1 |
| TA-specific fact corrected | Fusion for that TA | Everything before call 2 |
| Per-job decision, add-on, placement adjustment | Layout (S8), then ladder (S10) | Everything up to and including fusion and routing |
| Exception accepted | Ladder (S10) and status | Everything before |
| Sheet reorder, merge, split | Sheet packing (S12) | Every zone plan |
| Start field changed by the SME | Router (or fusion if a derived fact uses it) | Imagery, map, OSM, call 1 |
| Unrelated placemark edited | Nothing for untouched zones | All of it |

The map is data in `review/resume.py`, and a test checks every question kind maps to a stage.

### 4.4 Regroup, inherit and sheets

Regroup calls S9's functions with the SME's constraint (method `SME`, case 18). The steps are:
1. New zones get new geometry-derived ids with `derived_from` (S9 question 9).
2. Unchanged zones keep their version and run.
3. Only changed zones resume, from "fetch map and OSM".
4. Pass 2 and the overlap check re-run.

**Inherit (D-10)** is an explicit action on a new zone: "inherit from zone X version N". It copies the SME's fact corrections and confirmed answers whose subject still applies, so a fact about a point that is still in the zone is copied and one about a point that left is not. Each copied item is a new answer with `inherited_from`. Exceptions are never inherited (D-29). Sheet actions call S12's packer with the SME's order or grouping as constraints. An overlap on one sheet is refused (plan 4A rule 5).

### 4.5 TA change (D-16, ADR-022)

1. The SME picks a TA. `ta_change.preview` runs the router on the current facts with the new TA as the hypothesis.
2. It returns the preview in section 3. An `ANALYSIS_EXTENT_INSUFFICIENT` result is shown before any fetch.
3. If the new TA is NOT_ELIGIBLE, confirming it is S10's `TA_SELECTION_KEPT` exception with a reason. For broader 6N.11 cases, it is the engineer handover (S10 question 9).
4. On confirmation, a new zone version is written. It resumes from the router: call 2 runs once if the new TA has AI-observable missing fields, and is skipped otherwise.

### 4.6 Approval gate (D-65)

- `approve(plan_version_id)` is allowed for the role named by question 5 when:
  - the version is current;
  - no question is OPEN that is blocking and has no default (question 3);
  - the status label is not BLOCKED.
- The approval record stores the plan hash, the pack hash, the label and `would_have_been_supported_auto`.
- **The flag at `false`.** A zone whose status is genuinely SUPPORTED_AUTO (no review reasons, `DRAFT_COMPLIANT`) is marked `AUTO_APPROVED` with actor ENGINE. Everything else still waits.
- **Project status.** `APPROVED` when every zone's current version is approved, otherwise as in S3.

### 4.7 Roles and pages

- **Login.** A role dropdown on first load replaces the assistant's separate identity screen. It uses the existing `LocalIdentityProvider` and session token, with no credentials. Each page shows a banner: "Role selected, not verified".
- **SME reviewer page.** Project list, project form, zone review with the drawing (S12 output), TA change, regroup, sheets, add-ons, per-job decisions, the ledger view and the chat assistant.
- **Approver page.** Pending cap approvals, deviation proposals with their exception history, grouping settings (if S9 question 11 says so), and plan approvals (if question 5 says so).
- **Enforcement.** The backend refuses any action outside the role (`authz.require`). The UI hides the controls only as a convenience.

---

## 5. Commit sequence

Branch `tcp-mvp/s11-review`. Fast tier plus impacted suites per commit. Full suite once, at commit 13. S11 is large. A split into two sessions, backend (0 to 7) and UI plus login plan (8 to 13), is question 15.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED` | [B] with 1 | Housekeeping |
| 1 | `review/form/models.py`, `collect.py`: normalise S6 to S10 questions, ids, `show_if` and `reveals`; form snapshot test | [B] with 2 | Plumbing over existing question records |
| 2 | `review/ledger.py`: project stream, hash chain, refusing reader, durable writes for decisions | **[STOP 1]** | The audit record of every SME action. Review the entry shape |
| 3 | `review/resume.py`, zone-level reuse keys in `run_relations.py`, resume from a named stage; strict-replay zero-call tests per stage | **[STOP 2]** | Changes run relations and evidence reuse. Acceptance 1 |
| 4 | `review/form/visibility.py`, `answers.py`, per-job decisions with the owner's defaults, add-on toggles; "needs review" | **[STOP 3]** | Safe defaults and what the SME must answer. Acceptance 5 to 7 |
| 5 | `review/ta_change.py`: preview, confirmation, call-2 count | **[STOP 4]** | TA decisions and the AI budget (C-4) |
| 6 | `review/regroup.py`, inherit, placemark edit (question 4), `review/sheets_actions.py` | **[STOP 5]** | Zone identity and history (D-10, D-82) |
| 7 | `review/approval.py`, gate flag, project `APPROVED` status | **[STOP 6]** | The D-65 gate. Needs questions 3, 5, 6 and 8 |
| 8 | API (`web_api/review_api.py`) and `authz` permissions per role | [B] with 9 | Thin layer over 1 to 7 |
| 9 | UI: role dropdown, SME reviewer page, form, zone review, TA preview, regroup and sheets panels, ledger view; Vitest | [B] with 10 | UI |
| 10 | UI: Approver page; Vitest; web rebuild | **[STOP 7]** | The owner sees both pages before the assistant is wired |
| 11 | Assistant chat tools for answers and review actions (deterministic, ledger entries, no AI decision); no police tool | [B] | Reuses the tool registry |
| 12 | `docs/plans/S11_real_login_plan.md` | **[STOP 8]** | Owner review of the login plan |
| 13 | Full suite once, `docs/reports/S11_review_report.md` | [B] | Required finish |

---

## 6. Tests

All offline. Network blocked. Fixture projects built from fakes and recorded fixtures.

| ID | Test | Notes |
| --- | --- | --- |
| T-1 | Zero-call resume per row of table 4.3 (strict replay, call counter 0) | Acceptance 1 |
| T-2 | TA change: preview predicts and the run makes at most one call 2; skipped when nothing is AI-observable; extent check before any fetch | Acceptance 2 |
| T-3 | Placemark edit reruns only its zone (after question 4) | Acceptance 3 |
| T-4 | Regroup: only changed zones rerun; unchanged zones keep version and run; pass 2 re-runs; inherit copies only applicable items and never exceptions | Acceptance 4 |
| T-5 | Ledger: append-only, hash chain, tamper and truncation detected, reader refuses; three-process append does not fork (S2 pattern) | Acceptance 4 |
| T-6 | Form completeness: one question of each kind from S6 to S10 appears with reason and default; children revealed by parent answers; stable ids across reruns; superseded when inputs change | Acceptance 5 |
| T-7 | Per-job defaults: buffer none, taper unset places none, optional devices listed, add-ons off; "needs review" until answered; answer saved with the version | Acceptance 6 |
| T-8 | Asked-if-needed visibility per TA from the pack; `work_side` always | Acceptance 7 |
| T-9 | Approval gate true and false; approved version immutable; a change needs a new approval; "would have been SUPPORTED_AUTO" shown | Acceptance 8 |
| T-10 | Roles: each action per role at the API; pages show only their role's controls (Vitest); every ledger entry "role selected, not verified" | Acceptance 9 |
| T-11 | No police switch: no action, tool or UI string offers one | Acceptance 10 |
| T-12 | Mandatory start fields: an answer to a contradiction question changes a field only when the SME types the new value; no code writes one | CLAUDE.md rule 4 |
| T-13 | Answers validated against the stored spec only; a browser-sent spec is ignored | As `clarify_forms.py` |
| T-14 | No raw path in the ledger, answers, approvals (S2 scan); migrations round trip | |

---

## 7. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S6 `SiteFact`, `Question`, two-source rule, `work_side` suggestion | Form questions, inherit | Planned. A-1 |
| S7 `RoutingDecision`, `route()`, call 2 request builder and budget guard | TA change | Planned. A-2 |
| S8 `LayoutGap`, `optional_not_placed`, add-on modules, per-job inputs (buffer, taper choice, optional devices) | Per-job decisions, add-ons | Planned. A-3 |
| S9 grouping functions, proposals, zone identity, `derived_from` | Regroup, form grouping section | Planned (this round). A-4 |
| S10 `PlanStatus`, exceptions, reuse offers, approver role, `Actor` | Gate, roles, exception questions | Planned (this round). A-5 |
| S12 sheet model and packer | Sheet actions; drawing in zone review | Spec only. A-7 |
| S2 and S3 run relations, strict replay, project store | Resume, versions | Merged |

Feeds: S13 (approved plans and the ledger in the comparator report), S15 (old single-run review paths become orphan candidates).

---

## 8. Client inputs and decisions S11 consumes

- **Client inputs:** who holds each role (S10 question 1), the identity provider for real login (Entra tenant, groups), and the start fields and answers per job.
- **SME questions at run time:** everything in table 4.2.
- **Owner decisions:** section 10, part C.

---

## 9. What could go stale if S6 to S10 change

| Assumption | Shape I rely on | What breaks in S11 if it changes |
| --- | --- | --- |
| A-1 (S6) | `Question {question_id, kind WIDTH_NEAR_THRESHOLD|LANES_DISAGREE|START_FIELD_CONFLICT|FACT_UNKNOWN|WORK_SIDE_CONFIRM, reason, options, default_if_skipped, reveals}` and `SiteFact` with `status`, `reason_code`, `candidates[]` (S6 plan 4) | `collect.py` normalisation for S6 kinds; inherit rules |
| A-2 (S7) | `RoutingDecision` with `questions[]` of kinds `DECIDING_FACT|UNSOURCED_CONDITION|TA_CONFLICT|NEAR_MATCH|FACT_CONFLICT|MANDATORY_CONTRADICTION`; `route()` pure; call 2 budget guard per zone run (S7 plan 3.3, T-11) | TA-change preview and the call count (C-4) |
| A-3 (S8) | `LayoutGap {gap_id, record_id, status, question}`, `optional_not_placed[]`, per-job inputs `buffer_choice`, `taper_range_choice` (UNSET), `optional_device_policy` (OMIT), add-ons sidewalk closed and detour as per-zone inputs (S8 plan 3.3 and 3.5, owner constraint) | Per-job decision items and their effect on resume. The S8 plan copy still drops the pedestrian module (B-12); the owner now says sidewalk closed is built in S8 |
| A-4 (S9) | Pure regroup functions; zone ids geometry-derived with `derived_from`; proposals as `Question`s (S9 plan 3) | Regroup and inherit |
| A-5 (S10) | `PlanStatus {label, zone_decision, needs_review, review_reasons[], would_have_been_supported_auto}`, `ExceptionRecord`, reuse offers, `Actor` (S10 plan 3) | Gate, exception questions |
| A-6 (S8/S10) | `revision_derivation.derive` re-runs from eligibility on the new strategies and the ladder; strict replay works for zone runs | Resume from a named stage; if not, commit 3 is larger |
| A-7 (S12) | A `Sheet` record (`sheet_id, number, of, label, scale, zone_ids[]`) and a packer that accepts an order and fixed groupings | Sheet actions; if S12 is not merged first, commit 6 drops sheet actions (question 16) |
| A-8 (S3) | Project id = hash of geometry; re-upload of the same geometry reopens | The placemark-edit action (C-2) |

---

## 10. OPEN QUESTIONS

Three groups: **A. Client inputs**, **B. SME questions**, **C. Owner decisions**. I have decided none.

### A. Client inputs

**1. Documentation edits for the removed police switch (C-1).** This needs the owner's edits, but the client's practice decides whether Colorado-type jobs must later show police.
- Options: (a) the owner edits CLAUDE.md rule 5, D-68, ADR-048, plan Sections 4B and 8, and slices S11 and S13 now; (b) edit at S13; (c) leave the text and note the override in the S11 report.
- Effects: (c) leaves CLAUDE.md, which every session reads, telling the next session to build the switch.
- Suggestion: (a), before S11 starts.
- Blocks: **S11 start** (CLAUDE.md conflicts with the scope).

### B. SME questions

**2. Per-job decision defaults: confirm the list and wording.** Owner defaults: buffer none, taper unset places no taper, optional devices omitted and listed. My additions: add-ons off, `work_side` keeps the AI suggestion, flagged.
- Options: (a) as listed; (b) add other items (for example W16-2P plaque, G20-2) as explicit questions rather than lines in "optional devices".
- Suggestion: (a).
- Blocks: commit 4.

**3. Which skipped questions may still allow approval?**
- Options: (a) every per-job decision and every question with a safe default may be skipped, so the default stands, and the approval records each skipped item; (b) per-job decisions must be explicitly answered (accepting the default counts); (c) only safety-critical questions must be answered.
- Effects: (a) lets a plan with no taper be approved by one click; (b) forces one click per item.
- Suggestion: (b).
- Blocks: commit 7.

### C. Owner decisions

**4. Placemark edit without a new project (C-2).**
- Options: (a) a "replace input" action on an existing project: the new file becomes an input revision, the project id stays, locations are re-matched by geometry, and untouched zones keep their ids and runs; (b) a UI "move point" edit on the location list (no file); (c) accept a new project and copy the SME's answers with inherit (all zones run again; cross-run cache is future scope).
- Effects: (a) changes S3's rule "same geometry, same project" into "first upload names the project". (c) cannot meet the slice criterion.
- Suggestion: (a), plus (b) later.
- Blocks: **commit 6**.

**5. Who clicks the approval gate (C-5)?**
- Options: (a) the SME reviewer (D-65 as written); (b) the Approver; (c) both, in order.
- Effects: (b) and (c) contradict D-65's "SME click". (c) adds a second unverified click.
- Suggestion: (a); the Approver covers deviations, the cap and grouping settings.
- Blocks: commit 7.

**6. Project approval statuses.**
- Options: (a) add `APPROVED` and `PARTIALLY_APPROVED` to the S3 roll-up; (b) keep project statuses, show approvals per zone only.
- Suggestion: (a).
- Blocks: commit 7.

**7. AI-call budget on a TA change (C-4).**
- Options: (a) the budget counts calls made by one zone run; replayed calls are free, so a TA-change run has one replayed call 1 and one new call 2; (b) two calls per zone over its life, so a TA change after call 2 needs owner approval; (c) as (a), with a per-zone lifetime cap in config.
- Suggestion: (a), stated in CLAUDE.md by the owner.
- Blocks: commit 5.

**8. Where `require_sme_approval_for_all_plans` lives.**
- Options: (a) `config/pipeline_config.json` `review` section (guarded; an `APPROVED` entry); (b) per project, defaulting from (a); (c) a separate config file.
- Suggestion: (b): the plan says it changes per client without a code change.
- Blocks: commit 7.

**9. Real login: plan only, or build in S11?** The owner said "real login before client use, planned in S11".
- Options: (a) S11 writes the plan only; a later slice builds it before client use; (b) S11 builds an Entra provider behind a flag.
- Effects: (b) needs a tenant, app registration and secrets handling, none of which exist, and the owner's live-call rules would need an exception for the identity provider.
- Suggestion: (a).
- Blocks: commit 12 scope.

**10. Project archive flag.** The owner said "later, never delete".
- Options: (a) S11 adds `archived` and hides archived projects (small); (b) a later slice.
- Suggestion: (b).
- Blocks: no.

**11. Inherit scope (D-10).**
- Options: (a) facts and answers whose subject still applies; never exceptions, never approvals; (b) all SME decisions of the old lineage, each re-confirmed; (c) facts only.
- Suggestion: (a).
- Blocks: commit 6.

**12. One ledger or two.** The assistant already has a hash-chained audit per conversation.
- Options: (a) a new project ledger for plan decisions, referencing assistant audit ids; (b) extend the assistant audit to be the ledger.
- Effects: (b) mixes chat events with plan decisions and keys streams by conversation, not project.
- Suggestion: (a).
- Blocks: commit 2.

**13. Role dropdown: identities or roles?** The repo picks a configured identity (subject plus roles). The owner says "roles are a dropdown".
- Options: (a) keep the identity dropdown from `users.local.json`; (b) a role dropdown plus a typed name; (c) a role dropdown only, no name.
- Effects: (c) records no person, so S10's self-approval rule cannot work.
- Suggestion: (a).
- Blocks: commit 9.

**14. What the SME chat assistant may do.** The owner says "full chat assistant".
- Options: (a) every review action available as a tool, each with the same confirmation and ledger entry as the page; (b) answers and facts only; TA change, regroup and approval only on the page.
- Suggestion: (a), with approval excluded from chat.
- Blocks: commit 11.

**15. Split S11 into two sessions?**
- Options: (a) one session; (b) backend (commits 0 to 7), then UI and login plan (8 to 13).
- Suggestion: (b).
- Blocks: planning only.

**16. Branch parent and S12.**
- Options: (a) off the merge of S10 and S12, with sheet actions included; (b) off S10, with sheet actions moved to S12 or a follow-up.
- Suggestion: (a).
- Blocks: commit 6 (sheets part).

### Summary

| # | Question | Group | Blocks S11? | Suggestion |
| --- | --- | --- | --- | --- |
| 1 | Docs still describe the police switch | Client input / docs | **S11 start** | Owner edits before S11 |
| 2 | Per-job defaults list | SME | Commit 4 | As listed |
| 3 | Skipped questions and approval | SME | Commit 7 | Explicit answer for per-job items |
| 4 | Placemark edit keeps the project | Owner | **Commit 6** | "Replace input" action |
| 5 | Who clicks the approval gate | Owner | Commit 7 | SME reviewer |
| 6 | Project approval statuses | Owner | Commit 7 | Add `APPROVED`, `PARTIALLY_APPROVED` |
| 7 | AI budget on a TA change | Owner | Commit 5 | Per zone run; replay free |
| 8 | Where the gate flag lives | Owner | Commit 7 | Per project, default from config |
| 9 | Real login: plan or build | Owner | Commit 12 | Plan only |
| 10 | Archive flag | Owner | No | Later slice |
| 11 | Inherit scope | Owner | Commit 6 | Applicable facts and answers |
| 12 | One ledger or two | Owner | Commit 2 | New project ledger |
| 13 | Dropdown of identities or roles | Owner | Commit 9 | Identities |
| 14 | Chat assistant scope | Owner | Commit 11 | All actions except approval |
| 15 | Two sessions | Owner | Planning | Backend, then UI |
| 16 | Branch parent and S12 | Owner | Commit 6 | Off S10 + S12 |
