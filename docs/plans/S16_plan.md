Status: PLANNED, PAUSED until the accuracy gate between S7 and S8 (D-153, FS-21). Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

## Owner decisions applied (2026-10-31)

Register: `docs/decisions/OWNER_DECISIONS_2026-10-31.md`. Where this block differs from older text, this block is the active text; the older wording is kept in the "Amendments 2026-10-31" note in section 2. S16 is paused until the accuracy gate between S7 and S8 (D-153, FS-21).

- **Display only (D-154, Y16).** S16 only **displays values from the rule pack JSON**. The approval flow and the formula calculator are future scope (FS-23), started by the first real pack change after the MVP. No rule pack change happens in the MVP; the owner approves any that does (D-144).
- **Calibration values read-only (D-127, FS-09).** S16 shows the calibration values read-only: the 5 m edge, the 30 degree bearing, the confidence floors per profile and the pixel errors, each with its CALIBRATION_PENDING tag, read from `config/site_understanding.json`. The values stay in config; each run already records the values it used, and each change has a decision-log entry. The approval record and screen for calibration values are FS-09.
- **Roles (D-142, D-143).** The approver role exists for rule pack approval only, so it is the role the future approval flow (FS-23) will use. Until then S16 has no write route.
- **6N.11 ids.** `E-TA33-FORM-UNDIVIDED-6N11` no longer exists in pack 1.1.0; the broader undivided case is `E-TA33-FORM-UNDIVIDED-OTHER` (S4b follow-up e).
- **Sealed versions.** The browser reads the sealed versions side by side (pack store merged, commit `69ab4c0`).

# S16 plan: rule management UI

Planning only. Branch when built: `tcp-mvp/s16-rules-ui`, off the last merged slice (S16 is the last slice). Written on `tmp/plan-base4` (S1 to S4 merged). Nothing here is approved until the owner says so.

**S16 has no spec yet.** `docs/slices/TCP_MVP_Development_Slices.md` covers S0 to S15, plan section 13 lists slices up to S15, and CLAUDE.md names "S0 to S15". This plan is built from the owner's constraints in the planning request only. Adding S16 to the slices doc and the plan is an owner step (not done here; no doc outside `docs/plans/` was edited).

Read for this plan: CLAUDE.md (core rules 1 to 3, 9; storage); plan sections 7 ("Learning from exceptions"), 10, 11, 12 ("Users and roles"), 15 (D-14, D-21, D-28, D-30, D-39, D-65; open questions 15 and 17) and ADR-021, ADR-027, ADR-033; `S4_rule_pack_report.md` and `S4_rule_pack_review.md` (owner decisions, unsourced items, the proposal on open question 15); `S3_orchestrator_report.md` (cap approval actor); the plan copies `docs/plans/S5_plan.md` to `S8_plan.md` (not final), in particular S5 Q1 (sign sizes in the pack), S7 B-1 (SME determinations and promotion), S8 B-1 (pack amendment); `rule_pack/pack.json`, `rule_pack/base/sources.json`; `src/tcp_planner/rules/rule_pack_store.py`, `storage/interfaces.py`; `web_api/server.py`; `review/assistant/routes.py`, `core/authz.py`; `config/assistant/users.example.json`; `apps/web/src/App.tsx`.

Owner constraints applied:
- Roles are a dropdown with no login; every action is audited as "role selected, not verified".
- S16 is first a **read-only browser** for rules, rule packs, formulas, TAs, signs and sources.
- Then **approval as an append-only record that creates a new pack version and hash**. Never edit a source file in place.
- Show the **edition from the pack** (December 2023).
- The approver list is the dropdown role for now.
- Rules come from the MUTCD Chapter 6, December 2023, only.

Legend: **[B]** batchable. **[STOP]** owner review. **A-n** assumption, repeated in section 9.

---

## 1. What is there today (verified by reading)

| Item | Finding |
| --- | --- |
| Pack | `rule_pack/pack.json`: `TCP_MUTCD_CH6_RULE_PACK` 1.0.0, status DRAFT, hash `98c18fb2...`, `source_edition_note`, ten part files (all FEDERAL), `schema_version` on the manifest and parts. 112 source_refs, 52 registry fields, 18 table rows, 9 formulas, 73 rules, 18 eligibility conditions, 11 devices, 18 device uses, 0 deviations; 13 unsourced records, each with an SME question |
| Edition | `source_document` `SD-MUTCD11-CH6-2023-12`: edition "11th Edition", revision "December 2023", artifact `{uri: docs/sources/..., sha256, size, media_type}`. The POC pack's header cites a different edition (December 2025) |
| Evidence | Every source_ref has `section`, `paragraph`, `table`, `figure`, `note`, `page_printed`, `page_pdf`, `strength`, `evidence` (QUOTE or FIGURE_TRANSCRIPTION), `quote` or `transcription`, `figure_render`. Page snapshots in `tests/fixtures/rule_pack_sources/cited_pages.json`; four figure renders in `.../figures/` |
| Store | Interface `RulePackStore` (`list_versions`, `load(version=None)` "None means the active version", `content_hash`). `JsonRulePackStore` reads **one** root and returns one version. `seal()` rewrites the manifest **in place** (authoring helper used by the S4 scripts). `RulePack.trace(record_id)` returns rule id, pack id, version, hash and source refs |
| Report | `scripts/rule_pack_report.py` writes `S4_rule_pack_review.md` from the pack (tables, quotes, unsourced list) |
| Identity | The SME assistant already has an identity dropdown with **no credentials** (`config/assistant/users.local.json`, roles `SME_REVIEWER`, `AUDITOR`, `ADMIN`), sessions, an authz map and an audit writer. Plan section 12 names roles SME, approver and admin. No `APPROVER` role exists |
| Approvals elsewhere | S3 zone-cap approval stores `approved_by` as typed text with `verified: false`. D-28 and S10 plan a "named approver role from a config list" for permanent deviations. The S4 review proposed approvals **outside** the pack as `{record id, pack hash, approver, time}` with the pack staying DRAFT; the owner now wants approval to **create a new pack version and hash** |
| Web | Standard-library HTTP server, `/api/...` routes dispatched by prefix; React UI without a router library; Vitest |

## 2. Scope and acceptance criteria

### Phase 1: read-only browser (can merge on its own)

1. Browse **rule packs** (versions, status, hash, parts, layer, active flag), **rules**, **eligibility conditions**, **formulas**, **tables and rows**, **TAs** (figure, conditions, notes, device sequence), **signs and devices** (pack device, catalog entry, size rows from S5, symbol), **sources** (document, edition, every source_ref with quote or transcription, page and figure render), **registry fields**, and the **unsourced items** with their SME questions.
2. Every value is shown with its rule id, source table, section, page and strength (CLAUDE.md rule 3), and the evidence (quote or figure transcription).
3. The **edition** shown anywhere comes from the pack's `source_document`, never from UI text.
4. "Used by": for each record, the records that refer to it (for example which TAs use W20-1, which rules cite SR-6B04-P03).
5. A **diff** between two pack versions.
6. No write route in phase 1.
7. Show the calibration values read-only (D-127), with their CALIBRATION_PENDING tags and the values each run used.

### Phase 2: approval and pack versions (future scope: D-154, FS-23)

1. **Role dropdown** (no login). Every action records `{role, display_name, verified: false, note "role selected, not verified"}`.
2. **Approval record**: append-only, never edited; scope and effect per B-2 and B-3.
3. Each approval **creates a new pack version** with a new hash; the previous version's files are never changed.
4. An **active-version pointer** with compare-and-set; runs pin the version and hash they used (they already record the pack ref).
5. An **audit view** of every approval event.

**Amendments 2026-10-31 (section 2).** Phase 2 (approval and pack versions) was in scope of this slice; it is now future scope (D-154, FS-23), and so is the formula calculator. Phase 1 had six items; item 7 (calibration values, read-only) is new (D-127).

### Out of scope

Editing a rule's text or value in the UI (B-3 decides whether an SME answer to an unsourced item is in scope), the client and jurisdiction layers (empty by owner decision), login and real identity (future), cloud storage, the S10 deviation workflow (S16 shows deviations; approving them stays S10's unless B-9 merges them).

### Acceptance criteria (proposed; there is no spec)

| # | Criterion | How it is checked |
| --- | --- | --- |
| 1 | Every record in the active pack can be opened and shows its source quote or transcription, section, page and strength | Test over every record id through the API |
| 2 | The edition shown is the pack's (`11th Edition`, `December 2023`) | Test: a pack copy with a different edition string changes what the API returns; no edition literal in `apps/web/src` |
| 3 | Phase 1 changes nothing | Every rules route is GET; a store spy records no write; the pack folder's hashes are unchanged after the test run |
| 4 | An approval appends one record and creates one new version with a new hash; the old version loads unchanged with its old hash | Contract test on the store |
| 5 | Every approval event carries role, `verified: false` and the "role selected, not verified" note | Test |
| 6 | No rule-pack file is edited in place | Test: the bytes of every existing version's files before and after an approval are equal |
| 7 | The pipeline reads only the active version through `RulePackStore` | Extends the S4 isolation test |

## 3. Modules touched

New:

| Module | Purpose |
| --- | --- |
| `src/tcp_planner/rules/rule_browser.py` | Read model: record list and detail with trace, evidence and "used by"; TA view; device view (pack plus S5 catalog and sizes); source view; unsourced list; version diff |
| `src/tcp_planner/web_api/rule_routes.py` | `GET /api/rules/packs`, `/packs/<v>`, `/packs/<v>/records?table=&ta=&status=&q=`, `/packs/<v>/records/<id>`, `/packs/<v>/tas/<ta>`, `/packs/<v>/devices`, `/packs/<v>/sources`, `/packs/<a>/diff/<b>`, `/evidence/figure/<source_ref_id>`, `/evidence/page/<source_ref_id>`; phase 2: `POST /api/rules/approvals`, `POST /api/rules/active`, `GET /api/rules/approvals` |
| `src/tcp_planner/rules/pack_versions.py` | Phase 2: multi-version store (version index, active pointer), the version builder (copy unchanged parts, add the approval part, seal into the new location, validate, hash) |
| `src/tcp_planner/audit/actors.py` | Phase 2: the actor record `{role, display_name, verified: false, note}` shared by S3's cap approval, S10, S11 and S16 (B-6) |
| `apps/web/src/components/rules/` | `RulesHome.tsx`, `PackList.tsx`, `RecordTable.tsx`, `RecordDetail.tsx`, `TaView.tsx`, `DeviceView.tsx`, `SourceView.tsx`, `UnsourcedList.tsx`, `PackDiff.tsx`; phase 2 `RoleSelect.tsx`, `ApprovalPanel.tsx`, `ApprovalLog.tsx` |
| `scripts/export_pack_version.py` | Phase 2: writes an approved version from the store into `rule_pack/versions/<version>/` for a reviewed commit (B-4) |

Changed: `rules/rule_pack_store.py` (phase 2: `JsonRulePackStore` reads a version index; the current root is version 1.0.0 and is never rewritten), `storage/interfaces.py` (only if B-5 adds a method such as `active_version()`), `web_api/server.py` (dispatch), `config/settings.py` (evidence paths), `apps/web/src/App.tsx`, `api.ts`, `types.ts`, `CLAUDE.md` (only if the owner approves a note on pack versions).

## 4. Data shapes

```
PackSummary { pack_id, version, status, content_sha256, parts [ {path, layer, sha256} ], active bool,
              edition { source_document_id, title, edition, revision, artifact_ref }, created_from_version|null, approval_ids [] }

RecordView { table, id, layer, status SOURCED|SOURCE_REVIEW_REQUIRED|UNKNOWN, value_summary, record (as stored),
             trace (RulePack.trace), evidence [ {source_ref_id, section, paragraph, table, figure, note, page_printed, strength,
             kind QUOTE|FIGURE_TRANSCRIPTION, text, figure_render_ref|null} ], used_by [ {table, id} ],
             approvals [ {approval_id, decision, version} ], sme_question|null }

Actor { role "SME"|"APPROVER"|"ADMIN"|"VIEWER", display_name|null, verified false, note "role selected, not verified", at }

ApprovalEvent (append-only stream "rule_packs/approvals", schema_version "1")
{ approval_id, base_version, base_hash, scope { kind RECORDS|TA|TABLE|PACK, ids [] }, decision APPROVE|WITHDRAW,
  reason, actor Actor, created_version, created_hash }

Approval part (new part file in the new version, layer "APPROVAL", schema_version "1")
{ approvals [ {approval_id, record_ids [], decision, base_hash, actor {role, verified false}, at, reason} ] }

VersionIndex (StateStore record "rule_packs/index", compare-and-set)
{ schema_version, versions [ {version, hash, location_ref, parent_version, created_by_approval_id} ], active_version, active_hash }
```

A new version is `parent` plus the approval part, re-sealed into its own location; its manifest has `version` (B-7), `status`, `parent_version` and `parent_hash`. The parent's files are read, never written.

## 5. Commit sequence

Gate per commit: fast tier plus `tests/unit/rules/`, the web API suite and Vitest; full suite once per phase.

### Phase 1

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED` | [B] with 1 | Housekeeping |
| 1 | `rule_browser.py` read model and tests over every record of the pack | [B] with 2 | |
| 2 | `rule_routes.py` GET routes; read-only tests (store spy, pack hashes unchanged) | [B] | |
| 3 | Evidence serving: figure renders, page text, source PDF link (B-8) | **[STOP]** | Serving files from `tests/fixtures/` and `docs/sources/` |
| 4 | UI: Rules area, tables, record detail, TA, device, source, unsourced and diff views; edition from the API; Vitest; web rebuild | [B] | |
| 5 | Phase 1 report section; owner walk-through | **[STOP]** | Phase 1 can merge here |

### Phase 2

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 6 | Role dropdown and `audit/actors.py`; align S3's cap approval and the assistant identities (B-6) | **[STOP]** | The role list and who may approve |
| 7 | Multi-version store: version index, active pointer, version 1.0.0 imported unchanged; storage contract tests | **[STOP]** | Storage layout (B-4, B-5) |
| 8 | Approval events and the version builder; validate and seal into the new location; old version unchanged | **[STOP]** | What an approval changes (B-2, B-3, B-7) |
| 9 | Activation and its effect on runs (reuse keys, REVIEW_REQUIRED rules) | **[STOP]** | B-10, B-11 |
| 10 | UI approval panel, approval log, diff of the new version | [B] | |
| 11 | `export_pack_version.py` and its test | [B] | |
| 12 | `docs/reports/S16_rules_ui_report.md`; full suite | [B] | |

## 6. Tests

| ID | Test | Covers |
| --- | --- | --- |
| T-1 | Every record id in the active pack opens through the API with evidence, section, page and strength | Acceptance 1 |
| T-2 | Edition comes from the pack; a test pack with another edition shows that edition; a source scan finds no edition literal in `apps/web/src` | Acceptance 2 |
| T-3 | Phase 1 routes are GET only; no store write; pack part hashes unchanged | Acceptance 3 |
| T-4 | "Used by" is complete: every reference in the pack appears in the target's `used_by` | |
| T-5 | Diff of a version with itself is empty; a changed row shows as changed | |
| T-6 | Approval appends one event; a second identical request is idempotent (same approval id) or refused (B-12) | Acceptance 4 |
| T-7 | New version: new hash, validates, parent loads unchanged with the parent hash; bytes of every parent file unchanged | Acceptances 4, 6 |
| T-8 | Active pointer: compare-and-set rejects a stale head | S2 contract |
| T-9 | Every event's actor has `verified: false` and the note | Acceptance 5 |
| T-10 | Pipeline reads only the active version via `RulePackStore` | Acceptance 7 |
| T-11 | A run pinned to version 1.0.0 still reports 1.0.0 and its hash after a new version is active | Audit trail |
| T-12 | UI: browser views, role dropdown, approval panel, log (Vitest) | |

## 7. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S4 pack and store | Everything | Merged |
| S5 catalog, sign sizes, symbols | Signs view | Planned (A-1) |
| S7 SME determinations and promotion proposals | Phase 2 input: what gets proposed for approval | Planned (A-2) |
| S8 pack amendment (placement anchors) | New fields to display | Planned (A-3) |
| S10 approver role, deviations | Role list alignment; deviation view | Not planned yet |
| S11 ledger | Where approval events are mirrored | Not planned yet |
| S3 cap approval actor; assistant identities | One actor model | Merged; B-6 |
| S15 | Runs before S16 (S15 plan B-10) | Planned |

## 8. What the browser shows per table (phase 1)

| Table | Columns | Detail |
| --- | --- | --- |
| `rule` | id, scope, TA, strength, condition, action or value, status | Quote, page, "used by", cited-only marker, overlaps |
| `eligibility_condition` | id, TA, expression, OR group, status | Quote; the SME question when unsourced |
| `formula` | id, expression, unit, mode (EXACT, AT_LEAST, AT_MOST, APPROXIMATE), use (COMPUTE, CITED_ONLY) | Quote; B-13 for a "try it" calculator |
| `table_def`, `table_row` | Table, key, values, unit | Quote per row |
| `ta`, `ta_device_use` | TA, figure, device, approach, sequence, spacing dimension, required | Figure render and its transcription |
| `device` (+ S5 catalog) | Device, code, code status, sizes by road type, asset status | Symbol image, size source and quote |
| `source_document`, `source_ref` | Document, edition, revision; section, page, strength, evidence kind | Page text from the snapshot; figure render |
| `registry_field` | Field, type, unit, source type | Proposals listed in the S4 review |
| Unsourced | Record, status, SME question | Links to the record |

## 9. What could go stale if S6 to S8 change (assumptions)

| Assumption | If it changes |
| --- | --- |
| A-1: S5 puts sign sizes in the pack as `table_row` records (S5 Q1 option C) and keeps assets in the catalog with its own hash | The device view joins two sources; under S5 Q1 option A sizes come from the catalog only |
| A-2: S7's `SmeDetermination` is per plan version and S7 proposes promotion to the pack (S7 B-1 suggestion) | Phase 2's main input. If S7 promotes nothing, approvals cover only existing records |
| A-3: S8 amends the pack with `placement_anchor` data (S8 B-1 option a) | New fields in the TA and device views; a pack version change before S16 |
| A-4: S6 keeps its thresholds in config, not in the pack registry (S6 Q7 option B) | Thresholds are not browsable here; if they move to the registry they appear as registry fields |
| A-5: runs keep recording `{pack id, version, hash}` | T-11 |

## 10. Where the plan, the spec and the repo differ

1. No slice spec, plan section or CLAUDE.md entry exists for S16.
2. The S4 review proposed approvals **outside** the pack with the pack staying DRAFT; the owner now wants approval to create a new pack version and hash. Every approval therefore changes the hash that zone reuse keys include (plan section 9), so resumed runs recompute rules and placement (no external calls).
3. Plan section 12 names roles SME, approver and admin; the assistant has SME_REVIEWER, AUDITOR and ADMIN; D-28 and S10 speak of "a configured list of approver users". The owner's "the approver list is the dropdown role" replaces the user list for now.
4. `seal()` rewrites `pack.json` in place. S16 must never call it on an existing version.
5. `RulePackStore.load(version=None)` is documented as "the active version", but the JSON store has no notion of active.

## 11. OPEN QUESTIONS

### Part A: client inputs and SME questions

**A-1. Who holds the approver role at the client** (plan open question 15, risk R21).
- Effects: with a dropdown, anyone can select APPROVER; the audit says "not verified".
- Suggestion: the client names the people; the dropdown shows their display names (still unverified).
- Blocks: no for phase 1; phase 2 sign-off.

**A-2. Which MUTCD edition the client applies** (S4 open). The browser shows the pack's edition; a different client edition means a different pack, not an edit.
- Blocks: no.

**A-3. The 13 unsourced items and the two proposed interpretations** (S4 review). They are the first things an SME will want to settle in the UI.
- Effects: decides whether B-3 (answers in the UI) is needed.
- Blocks: no.

**A-4. Should catalog entries (CLIENT_CODE, STATE_CODE signs) be approvable** in the same flow?
- Blocks: no.

### Part B: owner decisions

**B-1. Phase split.**
- Options: (a) phase 1 merges on its own, phase 2 is a second session; (b) one slice.
- Suggestion: (a).
- Blocks: no.

**B-2. Approval granularity.**
- Options: (a) per record; (b) per TA or per table; (c) whole pack; (d) any of these, recorded as a scope.
- Effects: (c) is one click and one version; (a) gives many versions unless approvals are batched.
- Suggestion: (d), with a batch of records making one version.
- Blocks: commit 8.

**B-3. What an approval may change.**
- Options: (a) only marks records approved (no record content changes); (b) (a) plus confirming a proposed interpretation (for example E-TA33-FORM-UNDIVIDED-OTHER from SOURCE_REVIEW_REQUIRED to an SME-confirmed status); (c) (b) plus entering a value the MUTCD does not give (low-speed cutoff, short-zone length) with source "SME", in its own layer.
- Effects: (c) brings values that are not from the MUTCD into the pack; the owner's rule is "MUTCD only", and CLAUDE.md rule 2 allows a value only with a source. (b) changes what the router can decide automatically.
- Suggestion: (a) in S16; (b) and (c) only after a separate decision on where SME-sourced values live.
- Blocks: commit 8.

**B-4. Where new pack versions live.**
- Options: (a) `rule_pack/versions/<version>/` in the repo, written at run time (the working tree changes when someone clicks); (b) in `ArtifactStore` (content-addressed parts, under `var/`, untracked) with the index in `StateStore`; (c) (b) plus an export script that writes an approved version into `rule_pack/versions/` for a reviewed commit.
- Effects: (b) alone keeps approvals on one machine; (a) mixes run-time writes with tracked files.
- Suggestion: (c).
- Blocks: commit 7.

**B-5. The active version.**
- Options: (a) a new version becomes active immediately; (b) activation is a separate APPROVER action; (c) activation only by a committed config change.
- Effects: (a) changes the pack under running projects at once. (c) needs a code review for every activation.
- Suggestion: (b).
- Blocks: commit 9.

**B-6. Roles and the actor model.**
- Options: (a) a new role dropdown for the whole UI with SME, APPROVER, ADMIN, VIEWER; (b) reuse the assistant's identity dropdown and add APPROVER; (c) both: the assistant identities feed the dropdown, the role is chosen per action.
- Effects: one actor shape should also replace S3's `approved_by` text and serve S10 and S11. Plan section 12, the assistant and D-28 use three different role sets today.
- Suggestion: (b), with a shared `Actor` record.
- Blocks: commit 6.

**B-7. Version numbering.**
- Options: (a) patch bump per approval (1.0.0 to 1.0.1); (b) minor bump; (c) a date-based version.
- Suggestion: (a); the hash is the identity, the number is for people.
- Blocks: commit 8.

**B-8. Serving evidence files.**
- Options: (a) serve the figure renders and page text from `tests/fixtures/rule_pack_sources/` through `settings.py`, read-only; (b) copy them into `assets/` (an S15-style move needs approval); (c) also serve the source PDF from `docs/sources/` for "open at page".
- Suggestion: (a) plus (c).
- Blocks: commit 3.

**B-9. S10 deviations and S16 approvals.**
- Options: (a) S16 shows deviations read-only; S10 approves them; (b) S16 becomes the single approval UI for records and deviations.
- Suggestion: (b) if S10 is not built yet when S16 starts, else (a).
- Blocks: no.

**B-10. Effect of approval on plans.**
- Options: (a) none beyond the new hash: approval is a record; plans still follow D-39 and D-65; (b) an unapproved record used by a plan forces REVIEW_REQUIRED (D-65 already stops every plan); (c) only approved packs can be active.
- Effects: S4 recorded "all sourced values are usable for now".
- Suggestion: (a), and revisit (b) if D-65 is ever switched off.
- Blocks: commit 9.

**B-11. Runs made with an older version.**
- Options: (a) keep their pack ref; a resume after activation recomputes rules and placement with the new version (plan section 9); (b) resumes stay on the version they started with.
- Suggestion: (a), shown in the run view as "pack changed since this draft".
- Blocks: commit 9.

**B-12. Withdrawing an approval.**
- Options: (a) a WITHDRAW event creates another new version; (b) no withdrawal in the MVP.
- Suggestion: (a).
- Blocks: commit 8.

**B-13. A "try it" calculator for formulas** (for example L for W and S).
- Options: (a) yes, read-only, using `rule_pack_eval` and showing the trace; (b) no.
- Effects: (a) is a useful check for the SME and computes nothing that is stored.
- Suggestion: (a).
- Blocks: no.

**B-14. Proposer and approver the same person.**
- Options: (a) allowed; (b) refused when the same display name proposes and approves (weak without login).
- Suggestion: (a), recorded, until real identity exists.
- Blocks: no.

**B-15. Adding S16 to the slices doc, the plan and CLAUDE.md.**
- Options: (a) the owner adds it from this plan before S16 starts; (b) S16's report does it.
- Suggestion: (a).
- Blocks: the start of S16 (CLAUDE.md: the repo and the plan must agree).

### Summary table

| # | Question | Group | Blocks S16? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | Who holds the approver role | Client input | Phase 2 sign-off | Client names people; still unverified |
| A-2 | Edition the client applies | Client input | No | Confirm; another edition is another pack |
| A-3 | The 13 unsourced items | SME question | No | Settle outside S16 unless B-3 (c) |
| A-4 | Approving catalog codes | Client input | No | Ask |
| B-1 | Phase split | Decision | No | Two phases |
| B-2 | Approval granularity | Decision | Commit 8 | Any scope; one batch, one version |
| B-3 | What an approval may change | Decision | Commit 8 | Mark approved only |
| B-4 | Where versions live | Decision | Commit 7 | Store plus export for commit |
| B-5 | Active version | Decision | Commit 9 | Separate APPROVER action |
| B-6 | Roles and actor model | Decision | Commit 6 | Assistant identities plus APPROVER, one actor record |
| B-7 | Version numbering | Decision | Commit 8 | Patch bump |
| B-8 | Serving evidence files | Decision | Commit 3 | Read-only from fixtures; PDF link |
| B-9 | Deviations | Decision | No | Single approval UI if S10 not built |
| B-10 | Effect of approval on plans | Decision | Commit 9 | None beyond the hash |
| B-11 | Runs on older versions | Decision | Commit 9 | Recompute on resume, shown |
| B-12 | Withdrawing | Decision | Commit 8 | New version per withdrawal |
| B-13 | Formula calculator | Decision | No | Yes, read-only |
| B-14 | Same proposer and approver | Decision | No | Allowed, recorded |
| B-15 | Add S16 to the docs | Decision | Start of S16 | Owner adds it first |
