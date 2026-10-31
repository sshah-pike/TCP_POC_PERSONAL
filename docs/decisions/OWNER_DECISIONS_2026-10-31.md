# Owner decisions 2026-10-31 (site understanding)

Place this file at `docs/decisions/OWNER_DECISIONS_2026-10-31.md`.

**Numbering is provisional.** D-111 is the next free number after D-110 as of the last report (S5 merge). Check `docs/decisions/` and renumber before committing if other decisions were added since.

Sources: owner answers in conversation 2026-10-31. Repo files outside this document were not changed by these decisions. The plan text, slices doc and S7 and S8 plans still need the follow-up edits listed at the end.

## D-111: OSM missing 'oneway' tag

- **Decision:** A missing oneway tag counts as 'not one-way' for the OSM source, at lower confidence; the AI must also say false. For lanes and shoulder a missing tag gives no information. For divided, code checks the geometry for a parallel opposite-direction way.
- **Context:** OSM leaves out the oneway tag on two-way streets (OSM convention as understood; not checked today). Results now have three outcomes: FOUND (the source gives a value), NOT_PRESENT (the source was checked and the tag is absent) and UNKNOWN (we could not determine it: occluded, too blurry, or the source failed).
- **Applies to:** S6 commit 7
- **Status:** Answered: A, refined (2026-10-31)

## D-112: What call 1 is given as input

- **Decision:** hybrid zoom: the wide image in call 1 (context and road identity), a fine zoom-19 view in call 2 (measurement and conflicts).
- **Context:** The nine calls used a wide image (0.44 m per pixel), where a lane is about 5 pixels. A zoom-19 view gives about 20 pixels per lane.
- **Applies to:** S6 accuracy plan
- **Status:** Answered: hybrid zoom (2026-10-31)

## D-113: Edge handling for the work location

- **Decision:** Within 5 m of the edge (or no road near): UNKNOWN plus a question; distance in config, tagged CALIBRATION_PENDING, with an optional exceptions JSON.
- **Context:** When the KML point is within a set distance of the road edge, the image cannot decide 'in lane', 'on shoulder' or 'beyond'. The tool marks it UNKNOWN and asks the SME one question.
- **Applies to:** S6
- **Status:** Answered: A (2026-10-30)

## D-114: Zoom-19 probe for Massachusetts

- **Decision:** run the zoom-19 probe for E Second and Colorado (two Azure requests, run by the owner).
- **Context:** One zoom-19 request each for E Second and Colorado, to see whether Azure gives real detail there (Rhode Island was measured at 22 to 44 times the old gate).
- **Applies to:** S6
- **Status:** Answered: A (2026-10-30)

## D-115: User-Agent contact for Overpass

- **Decision:** a descriptive name with no company name and no contact until production.
- **Context:** The public Overpass server logs the user agent. Not required for development. Use a descriptive name without a company name or email until production.
- **Applies to:** S6 commit 7
- **Status:** Answered: no contact for now

## D-116: Pack store for sealed rule pack versions

- **Decision:** build the pack store that keeps sealed rule pack versions side by side after S5 and before S7.
- **Context:** A store that keeps each sealed version side by side so a run recorded against a pack hash replays without a git checkout. Task prompt is written.
- **Applies to:** Before S7
- **Status:** Answered: A; parked for now

## D-117: Device rows for add-on signs

- **Decision:** add device rows for the add-on signs just before the S8 add-on commit.
- **Context:** Sidewalk and detour signs have sizes and placeholder symbols but no device rows.
- **Applies to:** Before S8 add-ons
- **Status:** Answered: A

## D-118: Count flagged values as 'wrong and used'

- **Decision:** yes. The accuracy report counts a wrong value that is passed on with AI_ONLY_UNCONFIRMED as wrong-and-used, with the flag shown beside it.
- **Context:** The accuracy report counts a wrong value passed on with AI_ONLY_UNCONFIRMED, with the flag shown beside it.
- **Applies to:** S6 accuracy report
- **Status:** Answered: A

## D-119: Pipeline order for site understanding

- **Decision:** AI call 1 first and blind, then code and OSM checks, then fusion with the two-source rule, then AI call 2 at fine zoom for TA-specific, unknown and conflicting fields, then the SME for anything unresolved. Two AI calls per zone at most.
- **Context:** Order: AI call 1 first and blind (it does not see OSM or code results), then code and OSM checks, then fusion with the two-source rule, then AI call 2 at fine zoom for TA-specific, unknown and conflicting fields, then the SME for anything still unresolved. Two AI calls per zone at most.
- **Applies to:** S6 and S7
- **Status:** Answered: A (2026-10-31)

## D-120: Call 2 re-observes without seeing the competing value

- **Decision:** call 2 re-observes without being shown the OSM value, the call-1 value or any code value for lanes, divided, shoulder or one-way.
- **Context:** Call 2 is asked to observe at fine zoom without being shown the OSM value or the call-1 value, because a model shown a number tends to agree with it.
- **Applies to:** S7 call 2
- **Status:** Answered: A (2026-10-31)

## D-121: Re-ask the lane count at fine zoom on every zone

- **Decision:** lane count is a field in call 2 whenever call 2 runs; it never forces a call by itself; a config switch turns it off.
- **Context:** Lane count is a field in call 2 whenever call 2 runs. It never forces a call by itself. A config switch turns it off. It only helps when AI and OSM agree and the fine-zoom view disagrees.
- **Applies to:** S7 call 2
- **Status:** Answered: B (2026-10-31)

## D-122: Agent loop in call 1 (ReAct or plan-and-execute)

- **Decision:** parked. Build the agent loop only if one trigger fires (see FS-01).
- **Context:** An open-ended loop needs more than two AI calls per zone and is harder to replay. Parked. Build it only if one of these shows up: wrong-and-used above zero that call 2 and the code checks do not fix; or a question rate above the bar caused by facts that more looking could resolve (widths, lane lines, which road). Not for questions caused by missing data or tree cover. The deep-mode toggle is removed from S11 and returns only if a trigger fires.
- **Applies to:** Lab
- **Status:** Answered: A, build only if a trigger shows up (2026-10-31)

## D-123: Call 1 and call 2 disagree

- **Decision:** if call 1 and call 2 disagree on a field, the field becomes UNKNOWN and goes to the SME.
- **Context:** If the fine-view answer in call 2 disagrees with call 1, which wins?
- **Applies to:** S7 fusion
- **Status:** Answered: A (2026-10-31)

## D-124: Experiment arms and selection rule

- **Decision:** arm A original call 1 only; arm B the plan (call 1, fusion, call 2 at fine zoom); arm C arm B plus the enhanced call-1 prompt and code measurement of call-1 marks; arm D (lab only, parked) a loop in call 1. Pre-registered rule: first zero wrong-and-used on lanes, divided, shoulder and one-way with the 95% upper bound; then the lowest UNKNOWN rate; then width error; then fewest calls and least time; ties go to the simpler arm.
- **Context:** Arm A: original call 1 only. Arm B: the plan (call 1, fusion, call 2 at fine zoom). Arm C: arm B plus an enhanced call-1 prompt and code measurement of the call-1 marks before fusion. Arm D (lab only): arm C with a loop in call 1. Pre-registered rule: first zero wrong-and-used on lanes, divided, shoulder and one-way (with the 95% upper bound); then lowest UNKNOWN rate; then width error; then fewest calls and least time; ties go to the simpler arm. Tune on 15 dev sites, freeze, score once on 15 test sites; the three reference sites are dev only.
- **Applies to:** Lab
- **Status:** Answered: A (2026-10-31)

## D-125: Early failure-finding check: number of sites

- **Decision:** early failure-finding check on 8 sites, 2 per TA situation (4 already available, 4 new); certification later from client jobs and live corrections.
- **Context:** A small set cannot certify accuracy (zero wrong answers in 8 sites still leaves an upper bound of about 37%), but it can find failures before S8. Certification comes later from client jobs and live SME corrections. The 8 sites later become the permanent site-reading regression suite.
- **Applies to:** Gate before S8
- **Status:** Answered: A (2026-10-31)

## D-126: Verified site facts store

- **Decision:** add the verified site facts store after S11, kept simple, with an expiry and a one-click 'still true?' confirm.
- **Context:** An SME-confirmed road fact (lanes, divided, shoulder, one-way, width) is stored against the OSM road segment with date and who confirmed it. The next job on that road asks 'still true?'. Facts expire after a set time. Job-specific facts (work location, lane closure) are never stored this way.
- **Applies to:** After S11
- **Status:** Answered: A (2026-10-31)

## D-127: Calibration values: light version now

- **Decision:** light version now (values in config, each run records the values it used, each change gets a decision-log entry); the approval screen stays in S16.
- **Context:** The 5 m edge, the 30 degree bearing, the confidence floors and the pixel errors stay in config. Every run records the values it used, and each change gets a decision-log entry. The approval screen stays in S16.
- **Applies to:** S6, S16
- **Status:** Answered: A (2026-10-31)

## D-128: Final site-understanding plan

- **Decision:** the owner resumed work on the plan presented on 2026-10-31. It rests on these points:
  - The enhanced call-1 prompt and code snapping of marks to real edges are permanent.
  - The router runs twice: a provisional pass before call 2 and a final pass after the second fusion.
  - A what-if test marks each unresolved fact as deciding or not deciding for routing. No TA id may appear in the router, fusion or call-2 code; a made-up TA added to a test pack must work with no code change (generality tests, S7 requirements).
  - Consistency checks (lane count against width, work location against edge distance) are config-driven and can only lower confidence or give UNKNOWN.
  - Each stage has an off switch for measurement.
  - S6 session 1 resumes for the permanent design only; no agent loop, no deep mode, no call 2 (S7).
  - Early failure-finding check on 8 sites (2 per TA situation); certification later from client jobs and live corrections.
  - Verified site facts store comes after S11. Calibration values stay in config with each run recording the values it used (light version).
- **Status:** Answered by resuming work (2026-10-31).

## D-129: Prompt file registry now; full versioning later

- **Decision:** all prompts move into one `prompts/` folder, one file per prompt, each with an id, version and hash, loaded with a hash check and pinned by tests, before any prompt is enhanced. History, changelog, comparison runs and rollback are future scope (FS-05).
- **Status:** Answered: A (2026-10-31).

## D-130: Answer records instead of a question log store

- **Decision:** no question log store now. Every saved answer record keeps kind, field, zone, project, OSM way and answer time so repeated questions can be mined later (future scope, FS-04).
- **Status:** Answered: A (2026-10-31).

## D-131: Call 1 model

- **Decision:** call 1 uses gpt-5.6-sol by default; the claude-opus-5-5 profile stays working. Revisit after measurement.
- **Status:** Answered (2026-10-31).

## D-132: Confidence floors per model profile

- **Decision:** key the floors by profile: a default entry plus optional per-profile entries; no profile entry ships until calibrated.
- **Status:** Answered (2026-10-31).

## D-133: Test sites for the early check

- **Decision:** the owner labels 8 sites himself: Granite, E Second, Colorado, Ten Rod (existing) and 4 new, 2 per TA situation. Not 30.
- **Status:** Answered (2026-10-31).

## D-134: Pass bar for the safety fields

- **Decision:** zero wrong-and-used on lanes per direction, divided, shoulder and one-way, reported with its 95% upper bound.
- **Status:** Answered (2026-10-31).

## D-135: Pass bar for the UNKNOWN rate

- **Decision:** set after the first scored test.
- **Status:** Answered (2026-10-31).

## D-136: Overpass hosting

- **Decision:** public server for development and fixtures; self-host with Massachusetts and Rhode Island extracts before production.
- **Status:** Answered (2026-10-31).

## D-137: Alternative aerial imagery

- **Decision:** future scope (FS-07).
- **Status:** Answered (2026-10-31).

## D-138: Site exceptions file

- **Decision:** create config/site_exceptions.json now, empty and documented. Per-job answers still travel with the plan.
- **Status:** Answered (2026-10-31).

## D-139: Lab experiments

- **Decision:** future scope. The agent loop and deep mode are built only if a trigger in FS-01 fires.
- **Status:** Answered (2026-10-31).

## D-140: Fourth existing site

- **Decision:** Exeter Ten Rod. Four existing plus four new makes eight sites.
- **Status:** Answered (2026-10-31).

## D-141: Admin role

- **Decision:** the admin can do everything for now.
- **Status:** Answered (2026-10-31).

## D-142: Roles

- **Decision:** three roles: SME reviewer, approver and admin (Y6).
- **Status:** Answered (2026-10-31).

## D-143: Approver scope

- **Decision:** the approver is only for rule pack approval; everything else, including the zone cap and deviations, is done by the SME (Y7). The S3 code that has the approver approving the zone cap needs a small change in S10 or S11.
- **Status:** Answered (2026-10-31).

## D-144: Rule pack changes in the MVP

- **Decision:** no rule pack change happens in the MVP; the owner approves any that does (Y8).
- **Status:** Answered (2026-10-31).

## D-145: Grouping settings location

- **Decision:** config/grouping.json, one path limit input.max_work_path_m, owner confirms (Y2 A).
- **Status:** Answered (2026-10-31).

## D-146: Zone ids

- **Decision:** geometry-derived ids plus a derived_from link; 'inherit' carries facts and answers, never exceptions or approvals; amend ADR-009 (Y3 C).
- **Status:** Answered (2026-10-31).

## D-147: Project-level OSM fetch

- **Decision:** one project-level OSM fetch before the cap check; S3 wording becomes 'before any paid call' (Y4 A).
- **Status:** Answered (2026-10-31).

## D-148: Deviations workflow

- **Decision:** built in S10; no approval until a MUTCD or client document is the source (Y5).
- **Status:** Answered (2026-10-31).

## D-149: City, state, ZIP and street number on the sheet

- **Decision:** as listed (Y9). The reference drafts print street, city or neighbourhood, state and ZIP in the title block; the street number appears on the Colorado sheet.
- **Status:** Answered (2026-10-31).

## D-150: Build order

- **Decision:** do what can run in parallel, fast and easy; otherwise the order in the plan (Y10).
- **Status:** Answered (2026-10-31).

## D-151: Work-path adapter

- **Decision:** S9 builds it unless S8 did (Y11 A).
- **Status:** Answered (2026-10-31).

## D-152: Sheet template

- **Decision:** use the template as currently rebuilt; the client's current template is future scope (FS-22) (Y12).
- **Status:** Answered (2026-10-31).

## D-153: Comparator, polygons and lines, orphan sweep, S9 package, S11 form

- **Decision:** the plans' suggestions (Y13, Y14, Y15, Y17, Y18). S9 to S16 stay paused until the accuracy gate.
- **Status:** Answered (2026-10-31).

## D-154: Rule management UI

- **Decision:** S16 only displays values from the JSON for now; no approval flow and no calculator (Y16) (FS-23).
- **Status:** Answered (2026-10-31).

## D-155: Exceptions entries: who may add them (proposed)

- **Decision:** the SME proposes an entry, the admin enters it, and each entry gets a decision-log entry. Roles are chosen from a dropdown and recorded as 'role selected, not verified'.
- **Status:** Proposed; the owner approves by running the S6 prompt.

## D-156: STOP 5 fusion questions (open)

- **Decision:** not yet answered. Recommendations: (1) a single source on a safety field becomes UNKNOWN with the AI value kept as a pre-filled candidate, and a question candidate that S7 makes blocking only when the what-if test shows the fact decides the TA; (2) a bearing failure makes every road-specific fact from that call UNKNOWN with reason wrong_road_suspected, plus one 'which road?' question; (3) sidewalk against OSM is record-only, a disagreement lowers the confidence class to LOW.
- **Status:** Open.

## Follow-up edits to the repo (not made by this file)

- S7 plan: two-pass router with the what-if test; call 2 rewritten (blind re-observation, lane count when call 2 runs, call 1 and call 2 disagreement gives UNKNOWN); generality tests; the new 6N.11 ids; an unknown `closed_lane_side` never defaults to RIGHT.
- S8 plan lines 208, 219, 221: TA-33 anchor text superseded by the corrected reading; add-on device rows and real symbols before the add-on commit.
- S6 plan: three outcomes, OSM rules, bearing and which-road checks, 5 m edge rule, per-profile floors, enhanced prompt, mark snapping, extra code checks, consistency checks, off switches.
- S9 plan: revisit the 'not on road' flag (Colorado's point sits in a yard).
- S11 plan: question log fields and new question kinds; the deep-mode toggle is removed.
- Link `docs/FUTURE_SCOPE.md` from `docs/OPEN_ITEMS.md`.
