# S6 STOP 6: enhanced call-1 prompt (version 2) and code snapping

Status: **for owner review. No live run has been made and none will be until you approve.** Version 1 is untouched and stays the default, so nothing that exists today changes.

## 1. Text diff (user template, version 1 to version 2)

The system text is identical in both versions. Full diff, also in `docs/reports/S6_stop6_prompt_diff.txt`:

```diff
--- call1_user.v1.txt
+++ call1_user.v2.txt
@@ -1,8 +1,9 @@
 Image {w}x{h} px, north-up, {mpp:.3f} m per pixel. Work location = image centre ({cx},{cy}). Sides are N, S, E, W.
-For the road nearest the work location give one fact per field (facts) and one mark per visible feature (marks):
+Choose the road nearest the work location. Name it in road_name (the name or number if readable on a sign or label, else UNKNOWN) and list any other roads you see in other_roads_seen (short list or NONE). For the chosen road give one fact per field (facts) and one mark per visible feature (marks):
 - work_location: ROADWAY|SHOULDER|BEYOND_SHOULDER|SIDEWALK|UNKNOWN. work_side: N|S|E|W.
 - lanes_per_direction: count of through lanes in one direction. sidewalk_side: N|S|E|W|BOTH|NONE|UNKNOWN. obstructions: short list or NONE.
+- shadow_share and canopy_share: a number from 0 to 1, the share of the road and its edges hidden by cast shadow or by tree canopy.
 - every other field: true|false|UNKNOWN.
-- marks: points as 'x1,y1;x2,y2;...' in image pixels; one mark per lane line; road_edge_left and road_edge_right: the two pavement edges, either order.
-Evidence: at most {words} words. For UNKNOWN, evidence is exactly one of: not_visible, occluded, low_resolution, ambiguous.
+- marks: points as 'x1,y1;x2,y2;...' in image pixels; one mark per lane line; road_edge_left and road_edge_right: the two OUTER edges of the asphalt, where the pavement meets grass, soil, gravel or kerb, not the sidewalk edge and not a gutter or kerb line inside the pavement, either order; nearest_edge_point: one point, on the nearer outer pavement edge, closest to the work location.
+Evidence: at most {words} words. Reason: for every fact exactly one of visible, not_visible, occluded, low_resolution, ambiguous, shadowed, canopy (the main reason for your confidence). For UNKNOWN, evidence is exactly one of: not_visible, occluded, low_resolution, ambiguous.
 Report no length or distance. Return the JSON object only.
```

Schema change (strict, flat, no union, no min/max; checked by the same tests as version 1): four more `field` values (`road_name`, `other_roads_seen`, `shadow_share`, `canopy_share`), one more `unit` value (`share`), one more `feature` value (`nearest_edge_point`), and a required `reason` on every fact (enum: visible, not_visible, occluded, low_resolution, ambiguous, shadowed, canopy). Schema name for the Responses API: `tcp_site_facts_v2`.

## 2. Hashes

| Item | Version 1 (unchanged) | Version 2 (new) |
| --- | --- | --- |
| System text sha256 | `5e731eab10a7455ac1ace58f3f30520bc0fb0dc2d0aa4eb397cd1b57bed7266b` | same |
| User template sha256 | `81b8f01912963d536b1c1b14d702f0abd6bcc062f512522ad3729f49bcbef988` | `00ac1ea2810962ee8e5a99297489210f46a2090e9ccfcfb407bba7b88dfefe96` |
| Combined (system NUL user) | `58a344b4f526c55c965b35f80d9c8d78d222932fdbda2e80b1f606ce2550ad6f` | `ce63b8dd1dbfb56f1d8c5be1c399e35480537cc0701be1f1e98ccfcfc2e837b8` |
| Schema sha256 | `39d25f9a2c671005ed7a11a09659e01ee863dc7f6dce96a1399af9f2e3f43e02` | `c651156d3f4a6efdb04fa1aa18e7eea0ac32f64a4d9b0d59d7c85ab3f1af109e` |
| Granite P32 request prompt sha256 | `720ac0e1898533f5bfafd6623ec6c9e3797d2b5f5a0338fb85da84124fe48fc3` | `1b9a7cc7dd0026e0fe027e2238c26554becaadf9b2d69e7338265d01e05c4959` |

All pinned in `tests/unit/site/test_prompt_registry.py` (version 1) and `tests/unit/site/test_call1_v2.py` (version 2). The request fingerprint now also names `prompt_version`.

## 3. Recorded fixtures that go stale

Nothing in the repository is keyed to the version 2 request, so no committed fixture breaks. What is affected:

| Fixture | Effect |
| --- | --- |
| `tests/fixtures/site/spike/raw/*` (nine Claude responses, version 1) | Still valid as version 1 evidence for the parser and pins. They are **not** version 2 evidence: no `reason`, no shares, no `nearest_edge_point`, marks unsnapped. |
| The owner's saved results `var/s06_call1_check/<profile>/call1..9.json` (gpt-5.6-sol and claude-opus-5-5, version 1) | Same: valid version 1 results. Every table made from them (`docs/reports/S6_gpt_nine_calls_measurements.md`, the accuracy report) describes version 1 only. A version 2 run needs its own nine calls; they go to `var/s06_call1_check_v2/<profile>/`, never over the version 1 files. |
| `tests/fixtures/site/bearing/marks_nine_and_nine.json` | Version 1 marks; still valid for the bearing tests. |
| `tests/fixtures/recorded/*/ai/*.json` (Alton Bradford, Exeter Ten Rod, Granite P30) | **Not stale.** They are the old pipeline's recorded calls (`tcp_observation`, multi-image evidence), keyed by the old request. Call 1 version 2 never touches that path; `tests/unit/site/test_old_call_body_unchanged.py` proves the old body is unchanged. |
| Overpass fixtures | None recorded yet (the owner records them with `scripts/s06_record_osm.py`, step 13). |

Once call 1 is wired (step 11) recorded call-1 fixtures will be keyed by this fingerprint, so a later wording change makes them stale; none exist today.

## 4. Code snapping (`src/tcp_planner/imagery/snap.py`, config `snapping`)

- For every `road_edge_left`, `road_edge_right`, `shoulder_edge` and `curb` mark the polyline is sampled every 8 px; the grey profile across the line is read over +/- 12 px; the **nearest** real step edge (contrast of at least 14 grey levels) becomes the point; offsets are median-filtered along the line. A mark with fewer than 60 percent of its samples on an edge is **rejected**: UNKNOWN, reason `no_edge_nearby`, the AI's points kept in `original_points`. Lane lines and the work point are not snapped. All five numbers are CALIBRATION_PENDING.
- Tested on synthetic images: snaps onto the edge, follows a diagonal edge, nearest edge wins over the strongest, weak edges and edges beyond the radius are not edges, partial edges follow the accept fraction, a stray blob does not kink the line, and a snapped pair gives the true width where the rough AI pair is off by more than 4 ft.

## 5. The request is blind

`build_request(image_bytes, record, cfg, version)` takes no OSM or code value. Tests: the text equals the template filled with the image size, scale, centre and word cap only; the signature cannot carry anything else; no OSM or code word appears in the prompt or schema; `call1.py` imports no data source and no code check; building the request while OSM calls are rigged to fail succeeds.

## 6. Contradiction with the plan, and what is not wired yet

- **Distance of the point to the pavement edge.** Your list asks the AI for it. CLAUDE.md rule 1 and D-64 say the AI never returns a length. I implemented it as a **point**: `nearest_edge_point`, one pixel position on the nearer outer pavement edge. Code computes the distance (the same geometry as `distance_from_edge`) and will compare it with the work-point distance in the step 9 consistency checks. Say if you want it another way.
- `road_name` and `other_roads_seen` are labels for the SME and the trace. They are never matched to OSM by text (the reference way comes from the work point only).
- Not wired yet (steps 9 to 11): snapping inside the run, the shadow and canopy share check (`shadow_share`, `canopy_share` are parsed and kept as CONTEXT_ONLY facts), the use of `nearest_edge_point` and of `reason` in the consistency checks.

## 7. What you run after approving (PowerShell, `TCP_LIVE=1`, nothing is run by me)

```powershell
# see the exact version 2 body first, no network
python scripts/s06_call1_check.py --dry-run --only 1 --prompt-version 2
# one call
$env:TCP_LIVE = "1"
python scripts/s06_call1_check.py --only 1 --prompt-version 2
# the nine calls, three at a time (D-104), on each profile
python scripts/s06_call1_check.py --profile gpt-5.6-sol --prompt-version 2 --parallel 3
python scripts/s06_call1_check.py --profile claude-opus-5-5 --prompt-version 2 --parallel 3
```

Results go to `var/s06_call1_check_v2/<profile>/`.
