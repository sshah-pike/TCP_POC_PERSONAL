# Owner decisions, 2026-10-30

Status: APPROVED by the owner on 2026-10-30. This register wins over any plan text that differs (see the "Owner decisions applied" section in docs/plans/S5 to S8). New D-numbers continue after D-84.

Wording is the owner's, kept as given.

## D-85: Source edition

Rules come from MUTCD Chapter 6, December 2023 revision only. The Colorado, E Second and Granite drafts are comparison material, not sources. A later revision is a separate re-extraction task; the client is asked which revision applies.

## D-86: Traffic control method

Flagger is the default traffic control method. Police detail instead of flagger is future scope (entry already in the plan).

## D-87: S4 rule pack

S4 rule pack approved by the owner as the working pack. The manifest stays DRAFT. Approval logged 2026-10-30 against pack content hash 98c18fb207284ae884a28d20e2a5eba56facd74dfbc2aa7aa06797afe9e53d43 (version 1.0.0; computed by JsonRulePackStore.content_hash(), because rule_pack/pack.json stores the part hashes but not the pack hash). The 13 unsourced items and the figure-only values stay as they are.

## D-88: Golden set

Golden set v0.1 accepted by the owner, used with tolerances.

## D-89: Comparison scores

Comparison reports two scores: a core score (MUTCD items the tool is meant to produce) and a full score (everything in the draft, unbuilt extras counted as misses).

## D-90: Add-ons

Add-ons (owner scope B): sidewalk closed (R9-9, R9-11 family) and detour (M4-9 family) get MUTCD sources in the S4b pack round and are built in S8. No-parking (R8-3) and RI double fines wait for their sources. All add-ons are optional per zone; the engineer turns them on; the tool never adds them by itself.

## D-91: 6N.11

6N.11: a Granite-type case (undivided, two lanes each way, right lane closed) is treated as sourced from 6N.11 para 02 and para 06 (owner-confirmed reading). Broader cases (three or more lanes each way, left-lane or interior closures on undivided roads) remain an engineer question.

## D-92: Safety-critical fields

Safety-critical fields: lanes per direction, divided, shoulder, one-way each need two agreeing sources or become UNKNOWN. The work location uses a confidence of at least 0.85 and the SME confirms the work side. work_location values come from the registry vocabulary.

## D-93: Default work vehicle width

Default work vehicle width 102 in (23 CFR 658.15), kept in the S6 settings file (not the pack), flagged DEFAULT_ASSUMED, optional, overridable per job. A result that used it is REVIEW_REQUIRED. Work space depth and clearance are asked per job.

## D-94: Decide per job

"Decide per job" means the review form asks for that zone, the answer is saved with the plan, and until answered the tool uses the stated safe default and marks the plan "needs review". Defaults: buffer none; taper length unset places no taper; optional devices omitted and listed. A "standing rule" is set only if the SME gives one.

## D-95: Roles

Roles: dropdown roles (SME reviewer with full chat assistant; Approver who approves changes and the zone cap), no login for now, every action audited as "role selected, not verified". Real login before client use, in S11. Role-specific pages and components come with the UI slices.

## D-96: Cutover chain

Cutover chain: S6 builds beside the old path, S7 adds a non-gating route stage, S8 cuts over once with regenerated oracles that the owner reviews. The POC output renames happen in that same commit.

## D-97: S6 call 1 model

S6 call 1 uses gpt-5.6-sol (D-78 default). The same 9-call check is compared against claude-opus-5-5 before any real-KML recording. The safety-critical cross-check rule applies to both.

## D-98: Real-KML recording

Recording the real KMLs: Colorado once after S7 merges (calls 1 and 2 together); the rest after S9. Granite is compared at pole P32 (Phase I) only. The owner runs recordings with TCP_LIVE=1.

## D-99: S4b pack round

S4b pack round before S5 commit 3 and before S8: sign sizes as quoted pack rows, note-only devices, placement anchors, add-on sections, 6N.11 split.

## D-100: Title block

Title block: street, city, state and ZIP; the street number only if it is in the input.

## D-101: Merge style

Merge style: merge commits (--no-ff), no squash. RulePackStore reconciled to S4's shape (list_versions(), load(version=None, validate_pack=True), content_hash(version=None)). Done 2026-10-30, tcp-mvp/base.

## D-102: Approver role, grouping, S16

Approver role: dropdown. Grouping settings and the 18-case table are confirmed at S9 planning. Rule management UI is the last slice, S16, read-only browser first, then approval as an append-only record.

## D-103: Test tiering

Test tiering after the merge: slow marker, impact map, slice-end full run. Pytest-xdist only after measuring.

## D-104: S3 follow-ups

S3 follow-ups: a REVIEW_REQUIRED zone gets a draft in S7; projects get an archive flag later, never delete; max_parallel_zone_runs stays 3 and is measured in S6; the cap approval wording "approved (not verified)" is a cosmetic UI fix.

## D-105: Granite

Granite: the KML (WPI 3159540, points P32 to P28, about north) and the drawing (WPI 3178233, P.32 to P.42, east) are neighbouring stretches sharing P32 (granite-check report, medium confidence). The KML for WPI 3178233 has been requested from the SME.

## D-106: Azure

Azure: account TCP-Foundary-RR, East US; deployments claude-opus-5-5 and gpt-5.6-sol (5,000 requests and 5,000,000 tokens per minute each) and claude-opus-5-5-fast (2,000 and 2,000,000).
