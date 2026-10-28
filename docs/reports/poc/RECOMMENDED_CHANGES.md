# Recommended changes - TCP POC (after the two-call agent, 2026-10-19)

Status: recommendations only, except Part A items 2-5, which were IMPLEMENTED on 2026-10-19 (see "Result" below).
Evidence: live runs on RI-91 Alton Bradford Rd (output/AGENT_LIVE_RUN1_Alton_Bradford_Rd, runs/20261019-160302-a724d3,
runs/20261019-161129-5a18e8, runs/20261019-162708-b96762) and the offline test suites.

---------------------------------------------------------------------------------------------------------------------
## Part A - What Alton Bradford Rd needs to reach SUPPORTED_AUTO and produce a draft

### Where the runs stopped

| Run | Call 1 | Call 2 | Stopped by |
|---|---|---|---|
| CLI live run 1 | all fields right (LEFT, BEYOND_SHOULDER, 7.6 m, 2 lanes) | not needed | Plan validation `GEO-DRIVEWAY-INTERSECTION-CONFLICT`: a model-reported driveway (station 792.8 m) within 15 m of sign S2 (station 797.7 m) |
| UI 160302 | Claude profile | failed: Claude "compiled grammar is too large" | `AI_CALL2_UNAVAILABLE`, no road type |
| UI 161129, UI 162708 (GPT) | work point read as RIGHT side, in the travel lane (wrong) | corrected: LEFT, BEYOND_SHOULDER, 0.98 | `CROSS_VIEW_MISMATCH` (call 2 is not allowed to overrule call 1) |

### What has to be in place (in order) - items 2-5 implemented 2026-10-19

1. **Operator input - road type.** `RURAL` (Table 6B-1) must be supplied; it sets sign distance A = 500 ft. Without it
   the result is always `ROAD_TYPE_UNRESOLVED` (see Part B-6 for removing the manual step later).
2. **Model profile - use GPT for both calls.** Select `gpt-5.6-sol` in the UI, or set `TCP_FOUNDRY_PROFILE=gpt-5.6-sol`,
   or change `default_profile` in `tcp_poc/foundry_profiles.json` (currently the Claude profile, whose call 2 fails).
3. **Fix A1 - mark the work reference on the call-1 image.** Draw the same work-reference ring call 2 already uses
   (grounded "annot-v1") on the native 1280 px image. Call 1 is told the point is "at the centre" but cannot see it at
   0.45 m/px; it got the side right in 1 of 3 Alton runs, call 2 (with the ring) in 2 of 2.
4. **Fix A2 - consistency check only on fields call 1 already resolved.** Fields call 1 failed on (low confidence,
   conflict with geometry/OSM) are decided by call 2 at `fusion.min_critical_confidence`, still subject to the geometry
   and OSM conflict rules. Today a correct call-2 answer is always blocked as a mismatch.
5. **Fix A3 - verify features at the planned sign locations before validation.** The road type is known before the
   model runs, so the sign stations (work station +/- A) are known too. Add a close-view crop centred on each planned
   sign location to call 2 (still one call, within `crops.max_images_call2`) and judge driveway / intersection
   clearance from those positions instead of the wide-image guess. The run-1 blocker is a driveway that call 1 placed
   on the wrong side of the road where the image shows woods.
6. **If a real access lies within the clearance of a sign** (the house's gravel yard on the S2 side is close), the plan
   correctly stays REVIEW_REQUIRED unless the **approved rule pack** allows a sign shift (for example "move the sign up to
   X ft away from the work to clear a driveway, never closer than A"). That is a rule-pack decision for the owner of the
   pack; the placement engine and the GEO-STATION check would then follow it.

**Result (2026-10-19, output/AGENT_LIVE_RUN2_Alton_Bradford_Rd):** SUPPORTED_AUTO, plan TCP-51E4674EB18B78C4,
draft exported (plan.json, debug_plan.pdf, tcp_sheet.pdf). Call 1 (ringed image) resolved every field; call 2 was not
needed. Not exercised live in that run: fix A2 (no call 2) and fix A3 (no model feature within 15 m of a sign).
Open points: traveled-way width read as 8.8 m (draft label 7.3 m +/- 1.0 m); the NE sign (S2) stands near a property
access on the sheet - field verification required, as the sheet note says.

With 1-5 in place, the expected Alton outcome is SUPPORTED_AUTO with plan.json, debug_plan.pdf and tcp_sheet.pdf -
**unless** step 6 applies (a genuine access too close to a sign). Not guaranteed: model answers vary between identical
runs, so a run can still end REVIEW_REQUIRED with exact reason codes. Not needed for the decision: confirming the draft
label (labels/771bbc3d0913044a.json) - it is used for evaluation only.

DWT export (plan.dxf/dwg) additionally needs the approved DWT blocks and the ODA converter; without them DWT fails closed
but the draft itself is still exported.

---------------------------------------------------------------------------------------------------------------------
## Part B - Other required / recommended changes found during this work

| # | Change | Why | Effort |
|---|---|---|---|
| B-1 | **Claude call-2 schema size**: shrink the call-2 schema (drop `osm_claim_checks` when there are no junction claims, share more `$defs`, or split claims into text-only verification) or keep Claude for call 1 only | Claude's strict-grammar compiler rejects the call-2 schema with 4 images + claims (run 160302) | S |
| B-2 | Zoom: keep `crops.primary_zoom = 19` (done 2026-10-19). Remove the zoom-20 path or keep it for a future provider | Azure Maps imagery answers HTTP 400 at zoom 20 | done |
| B-3 | Sharpness check: only meaningful when `primary_zoom > fallback_zoom`; with 19/19 it is skipped and recorded as "not measured" | follows from B-2 | done |
| B-4 | Sidewalk agreement: derive the OSM value from the explicit tag only (separately mapped footways can currently change the value the agreement compares) | correctness edge case in the AGREEMENT path | S |
| B-5 | Pricing: add `gpt-5.6-sol` (and Foundry Claude) prices to `tcp_ui/pricing.json` | UI shows "AI cost Not Available" for every run | S |
| B-6 | Road type source: take it from an approved source (work-order field in the KML, state road inventory / urban-area boundaries + speed, or a per-project setting) instead of the form | removes the manual input; must stay an approved mapping, never a model guess | M |
| B-7 | Legacy UI comparison variants (`evidence_mode=multi`, `grounded_v2`, OSM-claims switch) no longer change the model request; remove them or re-purpose them (e.g. compare profiles only) | dead options confuse users | S |
| B-8 | Remove code listed in REDUNDANT_CODE.md (USGS, Esri, direct Anthropic) after sign-off | less surface, simpler tests (the 11 skipped tests) | S |
| B-9 | `imagery.ai_image_px` is no longer used (the model gets `wide_image_px`); remove after sign-off | config hygiene | XS |
| B-10 | Delete or move the `tcp_poc - Copy` / `tcp_ui - Copy` folders; `pytest` from the project root fails on them | test runner hygiene | XS |
| B-11 | Delete `debug_sent/` when finished (contains a real aerial image and prompts) | privacy | XS |
| B-12 | Decide whether `two_way` / `divided` with an **implicit** OSM value should still raise CONFLICT (kept today, stricter than the brief) | spec clarification | XS |
| B-13 | Restart the UI server after updates (Python changes are loaded at start; the built UI is read from disk) | operational | - |

---------------------------------------------------------------------------------------------------------------------
## Part C - Generic architecture: AI builds the site facts, only rule packs are authored per case

Goal: support every typical application (MUTCD Part 6 TA-1 ... TA-46) by writing **rule packs**, not code. AI and
deterministic sources produce one general site model; each rule pack decides eligibility, selects the TA and places
devices from it.

### C-1 What is TA-1-specific in code today

| Area | Today | Target |
|---|---|---|
| Site model | ~13 fixed fields | general road + work-zone model (C-2) |
| Prompts / schema | hand-written for those fields | generated from a field registry (C-3) |
| Eligibility scope | partly rule pack, partly code (`eligibility.py`: ramps, roundabouts, "TA-1 applicable") | 100 % rule pack |
| TA selection | fixed TA-1 | rule-pack decision table: facts -> TA |
| Placement | `geometry.place_objects`: "one sign per approach at A" | generic primitives (station relative to work start/end, lane-relative offsets, tapers, device spacing) driven by the pack |
| Validators | TA-1 checks in code | generated from the pack's `18_validation_rules` |

### C-2 General site model (each fact keeps value / status / confidence / evidence / audit, fail-closed)
- Cross-section per direction: lanes and widths, turn / bike / parking lanes, shoulder width and type, curb,
  median / barrier, sidewalks.
- Corridor: intersections (legs, control, distance), driveways, crosswalks, signals, curves and crests (sight
  distance), ramps, rail crossings.
- Work zone: start / end / length, occupied lanes or shoulder, side, work type, duration, day / night, flagger use.
- Regulatory / traffic: road type, speed limit, traffic volume (ADT), detour availability.

### C-3 Field registry (data-driven AI acquisition)
Per field: definition text, confidence rubric, allowed sources (image / OSM / geometry / GIS / operator), crop recipe,
consistency checks, minimum confidence. Each rule pack declares the fields it needs; the existing two-call agent
(call 1 -> compare -> crops -> call 2) asks only for those. A new TA = registry entries + rule pack.

### C-4 Facts that cannot come from imagery
Road type (urban / rural), legal speed limit, traffic volume, work duration, night work, actual work extent / method,
local agency rules. Source them from the work order / GIS / official datasets, or an engineer - never from the model.

### C-5 Perception quality for harder TAs
- Higher-resolution imagery (5-7.5 cm commercial orthos; Azure stops at ~0.11 m/px) for lane widths and markings.
- Deterministic lane-line / edge extraction (segmentation) for widths and lane counts; the LLM for classification
  and judgement. More repeatable than LLM-only reads.
- Street-level imagery for signs, curbs and sight distance.

### C-6 Evidence before automation
Build a confirmed-label set across site types (labels + evaluation UI exist). Measure per-field accuracy and allow
automatic resolution field by field only when it meets an agreed target. REVIEW_REQUIRED stays the outcome for weak
evidence; "every case fully automatic" is not a realistic target - "every case supported, most automatic, the rest
escalated with exact reasons" is.

### C-7 Suggested sequence
1. General site model + field registry + generated prompts (no TA-1 behaviour change); Part A fixes.
2. Rule-pack schema v2: eligibility, TA selection, parametric templates and validation as data; move TA-1 out of code.
3. Two or three common TAs: shoulder work (TA-3 / TA-4) and two-lane lane closure with flaggers (TA-10) - the latter
   forces tapers, buffers and channelizing devices and proves the generic placement engine.
4. Work-order / GIS integration (road type, speed, work details), better imagery, labelled evaluation set.

---------------------------------------------------------------------------------------------------------------------
## Update 2026-10-19 (late) - implemented after further live runs

| Change | Why | Status |
|---|---|---|
| Road width counts only when measured in a close view (`fusion.width_max_measure_mpp` = 0.25 m/px) | wide-image widths varied 7.6-9.4 m on a 7.3 m road and caused CROSS_VIEW_MISMATCH failures | implemented |
| Deterministic cross-section measurement (`tcp_poc/cross_section.py`, `poc_config.cross_section`): edge lines + centre line from brightness profiles of zoom-19 views at the work point and both sign stations, 3 sections each, must agree | the model's close-view width was still 1.7 m off at Alton; OSM centrelines were 2.8 m (Alton) and 1.6-3.2 m (RI-165) off the painted road, putting work-side signs on the pavement edge | implemented |
| OSM centreline shifted onto the measured road centre before side / encroachment / placement / validation; `centerline_status` UNRESOLVED when the work-point measurement is inconclusive (`cross_section.require_verified_centerline`) | an unchecked centreline can place a sign on the pavement and the validator cannot see it (same frame) | implemented |

Live results: Alton Bradford Rd SUPPORTED_AUTO (UI run 20261019-172533-cffadf, before the cross-section change);
RI-165 Ten Rod Rd demo point SUPPORTED_AUTO (UI run 20261019-175044-ba3d2c, 1 model call, width measured 6.8 m,
OSM offset corrected 1.6-3.2 m; signs land ~1.5 m beyond the edge line vs 2.0 m configured);
WPI 3159540 P30 (Granite St, 4 lanes, sidewalks) correctly UNSUPPORTED_POC.

Open: the measurement uses call 1's lane count (wrong count -> inconclusive, seen at P30); roads without painted edge
lines will stop as CENTERLINE_UNRESOLVED (by design, fail-closed); residual sign lateral error ~0.5 m between measured
stations.
