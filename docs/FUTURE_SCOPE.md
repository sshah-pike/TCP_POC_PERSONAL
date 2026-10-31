# Future scope

Written 2026-10-31. Place this file at `docs/FUTURE_SCOPE.md`. It lists work that was deliberately deferred, why, and what starts it. Items marked "owner conversation 2026-10-31" come from the owner's discussion of site understanding and have no earlier source in the repo. Nothing here is decided until the owner answers the decision named in each entry.

## Index

| ID | Title | Area | Starts when |
|---|---|---|---|
| FS-01 | Agent loop in call 1 and deep mode | Site understanding | A trigger fires (see entry) |
| FS-02 | Relax the lane re-ask | Site understanding | The 8-site check shows how often it changes the answer |
| FS-03 | Verified site facts store | Site understanding | After S11 |
| FS-04 | Repeated-question analysis | Learning | After enough logged questions exist |
| FS-05 | Full prompt versioning | Learning | After the prompt file registry has run for a while |
| FS-06 | State data sources | Data | After the first scored test |
| FS-07 | Alternative aerial imagery | Data | After the zoom-19 probe and the first scored test |
| FS-08 | Self-hosted Overpass and production hosting | Operations | Before production |
| FS-09 | Calibration approval records and screen | Operations | S16 |
| FS-10 | Accuracy certification and live-correction log | Quality | When client jobs are available |
| FS-11 | More TAs beyond the four | Product | When a fifth TA has a source |
| FS-12 | Model choice, per-profile floors, prices | Site understanding | After measurement |
| FS-13 | Police detail instead of a flagger | Product | Owner decision |
| FS-14 | Temporary no-parking and RI double fines | Product | When a source is found |
| FS-15 | CAD blocks and real symbols | Product | Client supplies blocks, or before S8 add-ons |
| FS-16 | Real login | Operations | Before client use |
| FS-17 | Project archive flag | Operations | Later slice |
| FS-18 | Pack versions and run records | Operations | Before the first recording and after S8 |
| FS-19 | Orphan sweep (S15) | Operations | After the S8 cutover and after S16 |
| FS-20 | Test tiering | Operations | After the merges settle |
| FS-21 | Paused slices S9 to S16 | Roadmap | After the accuracy gate |
| FS-22 | Client's current sheet template | Product | The client supplies it |
| FS-23 | Rule pack approval flow and formula calculator | Operations | The first real pack change after the MVP |

## Site understanding

### FS-01 Agent loop in call 1 and deep mode

- **What it is:** a short loop (plan-and-execute or ReAct) where the AI picks measurements, code runs them, and the AI reviews. A deep mode would turn it on with a warning that it costs more. It would be tested as a lab experiment first.
- **Why deferred:** the design allows two AI calls per zone. A loop needs more, varies in length and is harder to replay. Code checks and call 2 are tried first.
- **Trigger:** build it only if one of these shows up: wrong-and-used above zero on lanes, divided, shoulder or one-way that call 2 and the code checks do not fix; or a question rate above the bar that comes from facts more looking could resolve (widths, lane lines, which road). Not for questions caused by missing data or tree cover.
- **Dependencies:** a scored test, the call-2 design, a deterministic replay of tool steps.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** raise the two-call limit in deep mode; the config value that selects it.

### FS-02 Relax the lane re-ask

- **What it is:** lane count is a field in call 2 whenever call 2 runs, and a config switch can turn it off. Decide whether to keep it after measuring.
- **Why deferred:** its value is unknown until the 8-site check shows how often the fine-zoom view changes the answer.
- **Trigger:** results of the 8-site check.
- **Dependencies:** S7 call 2, the 8-site check.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** keep, narrow to conflicts only, or drop.

### FS-03 Verified site facts store

- **What it is:** an SME-confirmed road fact (lanes, divided, shoulder, one-way, width) stored against the OSM road segment with its date and who confirmed it. The next job on that road asks "still true?" with a one-click confirm.
- **Why deferred:** it needs the question form (S11) and the question log first.
- **Trigger:** S11 merged and the question log has data.
- **Dependencies:** S11, FS-04, an expiry rule.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** the expiry period; never store job-specific facts such as work location or lane closure.

### FS-12 Model choice, per-profile floors, prices

- **What it is:** choose between gpt-5.6-sol and claude-opus-5-5 for call 1 and call 2, and calibrate the confidence floors per model.
- **Why deferred:** the owner chose gpt-5.6-sol for call 1 for now (2026-10-31), and the Claude profile stays working. Nine calls on three sites cannot rank the models, so revisit after measurement. No price data exists.
- **Trigger:** the scored test and the 8-site check.
- **Dependencies:** the accuracy report, a truth file.
- **Source:** D-97, owner conversation 2026-10-31.
- **Decision still needed:** the model per call, the floors, and an acceptable cost per zone.

## Learning and prompts

### FS-04 Repeated-question analysis

- **What it is:** build a question log store and analyse it to find questions that repeat and are answered the same way, then propose standing rules, defaults or verified facts.
- **Why deferred:** the owner decided on no log store now. Saved answer records keep kind, field, zone id, project id, OSM way id, answer, who answered and time taken, so repeats can be mined later.
- **Trigger:** enough answered questions exist (the owner decides how many).
- **Dependencies:** the S11 project ledger.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** which repeats may become automatic rules.

### FS-05 Full prompt versioning

- **What it is:** history and changelog for each prompt, side-by-side comparison runs, and rollback.
- **Why deferred:** the prompt file registry (one file per prompt, with id, version and hash, loaded with a hash check and pinned by tests) is built before any prompt is enhanced and is not future scope. Full versioning is optional on top.
- **Trigger:** the registry has run for a while and prompt changes become frequent.
- **Dependencies:** the registry, the site-reading regression suite.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** how long to keep old versions.

## Data

### FS-06 State data sources

- **What it is:** MassGIS, RIGIS, HPMS, Census, 3DEP, GTFS and FRA adapters (S6 session 2), used as second sources for lanes, divided, shoulder and one-way, and for grade crossings and curves.
- **Why deferred:** choose them by how many SME questions each removes, which needs the first scored test.
- **Trigger:** the first scored test shows which fields still lack a second source.
- **Dependencies:** a discovery spike with the owner's permission, licences and endpoints.
- **Source:** S6 plan, owner conversation 2026-10-31.
- **Decision still needed:** the order and the permission to run the discovery spike.

### FS-07 Alternative aerial imagery

- **What it is:** compare state orthophotos (MassGIS, RIGIS) with Azure Maps for contrast, alignment and shadow at the reference sites.
- **Why deferred:** Azure's detail at zoom 19 in Massachusetts is not measured yet. The probe comes first.
- **Trigger:** the probe and the first scored test.
- **Dependencies:** the zoom-19 probe, FS-06.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** whether to add a second imagery provider.

## Quality

### FS-10 Accuracy certification and live-correction log

- **What it is:** a larger test from client hold-out jobs, plus every SME correction logged per field. The 8-site early check becomes the permanent site-reading regression suite (a fixed set of labelled sites replayed offline before any change to a prompt, schema, threshold or model).
- **Why deferred:** a small set finds failures but cannot certify. Zero wrong answers in 8 sites leaves an upper bound of about 37%; in 30 sites about 10%.
- **Trigger:** client jobs arrive (hold-out request C9), or live use produces corrections.
- **Dependencies:** the truth file format, the accuracy report script.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** pass bars for wrong-and-used and the UNKNOWN rate.

### FS-11 More TAs beyond the four

- **What it is:** adding a fifth or later TA by changing only the pack.
- **Why deferred:** only TA-1, TA-6, TA-10 and TA-33 are in scope. The S7 generality tests enforce that the router, the what-if test and call 2 field selection need no code change.
- **Trigger:** a fifth TA with a MUTCD source.
- **Dependencies:** S7 generality tests, a new pack version.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** which TA, and its source.

## Product

### FS-13 Police detail instead of a flagger

- **What it is:** a police-detail variant of TA-10 and others.
- **Why deferred:** MUTCD allows either and gives no rule for choosing. D-68 defers it to future scope.
- **Trigger:** owner decision, with a client rule for when to use police.
- **Dependencies:** a pack change, a layout rule.
- **Source:** D-68, D-86.
- **Decision still needed:** the choosing rule.

### FS-14 Temporary no-parking (R8-3) and RI double fines

- **What it is:** R8-3 placement and the Rhode Island double-fines signs.
- **Why deferred:** no source. The 6G.08 section on fines was deliberately not loaded.
- **Trigger:** a source (a MUTCD section for R8-3, a state document for the fines).
- **Dependencies:** SME questions on practice (S13 in the question list).
- **Source:** D-90.
- **Decision still needed:** the practice.

### FS-15 CAD blocks and real symbols

- **What it is:** use the client's CAD blocks, or draw real symbols for the placeholder ones. M4-9a must show its arrow.
- **Why deferred:** every symbol is a placeholder, and nothing consumes them until S8.
- **Trigger:** the client supplies blocks, or before the S8 add-on commit.
- **Dependencies:** the S5 catalog and symbol library, add-on device rows.
- **Source:** S5 report, D-110.
- **Decision still needed:** the licence and format of any client blocks.

## Operations

### FS-08 Self-hosted Overpass and production hosting

- **What it is:** run Overpass with Massachusetts and Rhode Island extracts, and decide where the tool is hosted.
- **Why deferred:** the public Overpass server is acceptable for development. A maintainer announced in October 2025 that it would block Azure and AWS traffic for some time; the current state is unknown.
- **Trigger:** before production.
- **Dependencies:** the hosting decision.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** the hosting; the User-Agent contact (a shared mailbox) before production.

### FS-09 Calibration approval records and screen

- **What it is:** each calibration value (the 5 m edge, the 30 degree bearing, the confidence floors, the pixel errors) changed through an approved record, shown on a read-only screen.
- **Why deferred:** the light version is built now: values in config, every run records the values it used, each change gets a decision-log entry.
- **Trigger:** S16.
- **Dependencies:** S16, the approver role.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** who approves.

### FS-16 Real login

- **What it is:** replace the role dropdown with real login.
- **Why deferred:** no login for the MVP. Actions are audited as "role selected, not verified".
- **Trigger:** before client use.
- **Dependencies:** the identity provider.
- **Source:** handover decisions.
- **Decision still needed:** the provider.

### FS-17 Project archive flag

- **What it is:** archive a project without deleting it.
- **Why deferred:** S3 follow-up.
- **Trigger:** a later slice.
- **Dependencies:** the project ledger.
- **Source:** S3 follow-ups.
- **Decision still needed:** none yet.

### FS-18 Pack versions and run records

- **What it is:** pipeline runs record the pack version and hash. Any pack change after S8 becomes a new sealed version through `scripts/seal_rule_pack_version.py`.
- **Why deferred:** the pack store that keeps sealed versions side by side is a decided task and runs before S7.
- **Trigger:** before the first recording, and after S8.
- **Dependencies:** the pack store.
- **Source:** D-107, owner decisions 2026-10-30.
- **Decision still needed:** none.

### FS-19 Orphan sweep (S15)

- **What it is:** move unused files to `backup/orphans/<date>/` with a manifest entry. Do not remove the `anthropic` dependency while Claude is compared.
- **Why deferred:** run 1 after the S8 cutover, run 2 after S16.
- **Trigger:** those points.
- **Dependencies:** S8, S16.
- **Source:** the S15 plan.
- **Decision still needed:** Y15.

### FS-20 Test tiering

- **What it is:** a `slow` marker, an impact map script, and a slice-end full run. No weakening of guards or the global identity test.
- **Why deferred:** it edits CLAUDE.md, `pyproject.toml` and test markers that other branches also touch.
- **Trigger:** after the merges settle.
- **Dependencies:** none.
- **Source:** handover Appendix B.
- **Decision still needed:** whether to add pytest-xdist after measuring.

## Roadmap

### FS-21 Paused slices S9 to S16

- **What it is:** grouping and zone split (S9), conflicts and the exception ladder (S10), the question form and SME review (S11), sheets and PDF (S12), the golden comparator (S13), polygons and lines (S14), the orphan sweep (S15) and the rule management UI (S16). Owner decisions Y2 to Y18: answered, D-142 to D-154 (2026-10-31).
- **Why deferred:** the owner paused them to focus on site-understanding accuracy.
- **Trigger:** after the accuracy gate between S7 and S8.
- **Dependencies:** the gate, the S7 call 2 and router.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** none for Y2 to Y18 (answered, D-142 to D-154); the slices stay paused until the accuracy gate. For S9, revisit the "not on road" flag: the Colorado point sits in a yard, so pass 1 needs it.

### FS-22 Client's current sheet template

- **What it is:** replace the sheet template rebuilt from the E Second St drawing with the client's current template (DWT or PDF) and its title-block rules.
- **Why deferred:** the owner decided to use the template as currently rebuilt (Y12).
- **Trigger:** the client supplies the template (client question C1).
- **Dependencies:** S12.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** what each title-block field prints (C2).

### FS-23 Rule pack approval flow and formula calculator

- **What it is:** an approval flow for rule pack changes (any scope, one batch is one version, activation a separate action) and a read-only formula calculator, both in S16.
- **Why deferred:** no rule pack change happens in the MVP, and the owner approves any that does (Y8). S16 only displays values from the JSON for now (Y16).
- **Trigger:** the first real pack change after the MVP.
- **Dependencies:** S16, the pack store, the approver role.
- **Source:** owner conversation 2026-10-31.
- **Decision still needed:** none yet.
