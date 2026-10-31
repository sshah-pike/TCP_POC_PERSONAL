# Open items

Last updated 2026-10-31. Sources: docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md (D-111 to D-156). Deferred work and what starts it: docs/FUTURE_SCOPE.md (FS-01 to FS-23).

## SME questions

| # | Question | Status |
| --- | --- | --- |
| 1 to 15 | The 15 questions emailed to the SME on 2026-10-30. The question texts are in the email, not in the repo; the owner adds one row each here | sent, awaiting reply |
| 16 | Granite: does the KML (WPI 3159540, P32 to P28) match the drawing (WPI 3178233, P.32 to P.42)? The granite-check report says neighbouring stretches sharing P32, medium confidence | sent, awaiting reply |
| 17 | Traffic volume for each golden job (Colorado, E Second St, Granite). D-59 mandatory start field; no source fills it | sent, awaiting reply |
| 38 | Confirm the road-type to sign-size column mapping (PROPOSED in S5, D-109) | open |
| S41 | E Second St: is the street one-way or two-way? The drawing does not show it (`docs/evaluation/SITE_TRUTH_v0.md`) | open |
| new | The SME and client email questions of the 2026-10-31 round. The texts are not in the repo; the owner adds one row each here (this file could not source them) | open |

## Client inputs

| # | Input | Needed by | Status |
| --- | --- | --- | --- |
| 1 | Which MUTCD revision applies (rules use December 2023 only until answered) | S4b onward | open |
| 2 | Who holds the approver role. The role now covers rule pack approval only (D-143); the holder's name is still needed | S16 | open |
| 3 | KML for WPI 3178233 (requested from the SME) | S13 | requested |
| 4 | A TA-1 reference drawing (plan open question 9) | S13 | open |
| 5 | Which MassDOT and RIDOT documents apply (plan open question 17) | later | open |
| 6 | CAD blocks for devices (S5 uses placeholder symbols; FS-15) | S12 | open |
| 7 | Traffic volumes per job | S13 | open |
| C1 | The client's current sheet template (DWT or PDF); the MVP uses the template as currently rebuilt (D-152, FS-22) | FS-22 | open |
| C2 | What each title-block field prints, including which locality name goes on the second line (D-149, FS-22) | FS-22 | open |
| C9 | Hold-out client jobs for the certification test (FS-10) | FS-10 | open |

## Owner tasks

| # | Task | When | Status |
| --- | --- | --- | --- |
| 1 | S6 9-call live check on gpt-5.6-sol, then on claude-opus-5-5; the comparison goes to docs/reports/S6_model_comparison.md. Call 1 uses gpt-5.6-sol by default (D-131) | Before any recording | open |
| 2 | Permission for the MassGIS (first) and RIGIS discovery calls: read-only, limited, three sites named. Moved with S6 session 2 to after the first scored test (FS-06) | After the first scored test | moved |
| 3 | Colorado recording with TCP_LIVE=1 (calls 1 and 2 together) | After S7 merges | open |
| 4 | Remaining recordings with TCP_LIVE=1 | After S9 | open |
| 5 | Zoom-19 probe for E Second and Colorado: two Azure requests, run by the owner (D-114) | S6 | open |
| 6 | Choose and label the four new sites for the 8-site early check, 2 per TA situation: TA-33 (four-lane undivided road, right lane closed), TA-6 (minor low-speed street, work at the curb), TA-10 (two-lane road, work in the lane), TA-1 (work set back from the road). Include one point near an intersection, one under heavy tree cover and one on a curve. Exeter Ten Rod is the fourth existing site (D-125, D-133, D-140) | Gate between S7 and S8 | open |
| 7 | Cross-check `docs/evaluation/site_truth_v0.json` (Granite, E Second, Colorado); any change makes v1 with the reason recorded | Before the first scored test | open |
| 8 | Run the 8-site early check (`TCP_LIVE=1`) and read the accuracy report (D-125, D-134) | Gate between S7 and S8 | open |

## Decisions still open (owner)

| # | Decision | Where | Status |
| --- | --- | --- | --- |
| D-156 (1) | A single source on a safety field (lanes, divided, shoulder, one-way): UNKNOWN with the AI value kept as a pre-filled candidate; S7 makes the question blocking only when the what-if test shows the fact decides the TA. A STOP 5 question. The S6 branch already builds it | STOP 5 report on branch `tcp-mvp/s06-site-understanding` (`docs/reports/S6_stop5_fusion_rules.md`) | open, owner confirmation |
| D-156 (2) | A bearing-check failure makes every road-specific fact from that call UNKNOWN (`wrong_road_suspected`), plus one "which road?" question. A STOP 5 question | same | open, owner confirmation |
| D-156 (3) | Sidewalk against OSM is record-only; a disagreement lowers the confidence class to LOW. A STOP 5 question | same | open, owner confirmation |
| D-155 | Exceptions entry rule: the SME proposes an entry, the admin enters it, each entry gets a decision-log entry; roles recorded as "role selected, not verified" | `config/site_exceptions.json` | proposed |
| D-135 | Pass bar for the UNKNOWN rate | After the first scored test | open |
| FS | The other "Decision still needed" lines of `docs/FUTURE_SCOPE.md` (for example FS-12 the model per call, FS-03 the expiry period) | FUTURE_SCOPE.md | open |

## Answered by the 2026-10-31 decisions

| Earlier item | Answer |
| --- | --- |
| S6 Q12 and Q21: where the Overpass data comes from, discovery of the state sources | Overpass, public server for development and self-hosted before production (D-136, FS-08); discovery moves to after the first scored test (FS-06); no contact in the User-Agent for now (D-115) |
| S6 Q4: call 1 model | gpt-5.6-sol by default; the claude-opus-5-5 profile stays working (D-131) |
| S6 Q18, S6 recordings | No recordings in S6; Colorado after S7, the rest after S9 (D-98, D-128) |
| S7 A-4: the 6N.11 undivided reading | Granite-type case sourced (D-91); broader cases an engineer question |
| S9 Q7, Q8, Q9, Q10, Q17 (Y4 A, Y2 A, Y3 C, Y2 A, Y11 A) | D-147, D-145, D-146, D-145, D-151 |
| S10 Q1, Q10; plan open question 15 (scope) | Three roles, the approver for rule pack approval only (D-142, D-143); the deviations workflow is built with no approvals until a source exists (D-148) |
| S12 A-1, B-1; D-71 wording | Template as currently rebuilt (D-152); title block prints street, city or neighbourhood, state and ZIP (D-149) |
| S16 scope | Display only; the approval flow and calculator are future scope (D-154, FS-23) |
| Add-on device rows (S4b follow-up b) | Added before the S8 add-on commit, with real symbols (D-110, D-117) |
| Pack store | Merged (commit `69ab4c0`; D-116) |

## Plan open questions

Plan v4 open questions 15 (approver role holder), 17 (MassDOT and RIDOT documents) and 18 (Section 4B check) are marked in the plan. The scope of the approver role is answered (D-143); the holder of the role and the document list stay open as client inputs above.

Questions 21 and 24 exist only as items of the plan's verification prompt (Section 18: deployed model image limit; geometry sources), not as open questions. They overlap S6 plan Q19 and Q21 (deployment facts, source access) and stay open there: the deployment facts are partly answered by D-106, and the source access facts moved with FS-06.

Y2 to Y18 (the owner's handover list): D-142 to D-154 record the answers for Y2 to Y18. `docs/FUTURE_SCOPE.md` FS-21 still lists "Y2 to Y18" as decisions needed; treat the register as the later word until FS-21 is corrected.
