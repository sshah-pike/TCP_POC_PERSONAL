Status: PLANNED, PAUSED until the accuracy gate between S7 and S8 (D-153, FS-21). Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

# S14 plan: polygon and line normalization

Planning only. Branch when built: `tcp-mvp/s14-geometry`, off `tcp-mvp/s09-grouping` or later (the slices doc: "S14 can follow S9 at any time"; see B-12). Written on `tmp/plan-base4` (S1 to S4 merged). Nothing here is approved until the owner says so.

Read for this plan: CLAUDE.md; slice specs S1, S3, S6, S8, S9, S12, S14; plan sections 4 (the 150 m case), 4A (cases 5, 14, 15, 16), 5, 9, 12, 14 (R11) and ADR-011, ADR-026, D-06, D-19, D-66; `S0_repo_report.md` items 1 and 13 (polygon touch points); `S3_orchestrator_report.md`; the plan copies `docs/plans/S5_plan.md` to `S8_plan.md` (not final), in particular S6 Q10 (footprint and encroachment) and S8 B-6 (work space with unknown length); `src/tcp_planner/intake/kml_reader.py`, `work_location.py`; `orchestration/projects.py`; `geometry/local_frame.py`; the six KMLs in `docs/references/kml/`.

Owner constraints applied: the KML supplies coordinates only (D-66); recordings of real KMLs are run by the owner with `TCP_LIVE=1`; never delete files.

Legend: **[B]** batchable. **[STOP]** owner review. **A-n** assumption, repeated in section 9.

---

## 1. What is there today (verified by reading)

| Item | Finding |
| --- | --- |
| Intake (S1) | `parse_all` reads Point, LineString and Polygon (outer ring plus holes), flattens MultiGeometry into one `WorkLocation` per part (same `placemark_index`, its own `geometry_index`). Checks: coordinates parse, a line has 2 or more pairs, a ring is closed with 4 or more pairs. Reasons: `INVALID_GEOMETRY`, `EMPTY`, `UNSUPPORTED_TYPE`, `DUPLICATE_OF:<id>` (Points only). **No check** for self-intersection, repeated vertices, zero length or area, holes outside the outer ring, or size |
| Geometry hash | From the coordinates as read (7 decimals); never from names, order or file hash. Changing stored coordinates (for example re-orienting a ring) would change ids |
| Projects (S3) | A zone from a line or polygon is `NOT_SUPPORTED_UNTIL_S14` and never runs; a Point plus Line KML runs the Point |
| Engine | Takes a `work_reference` point and an optional `work_path` (ordered points), limited by `max_work_path_m` = 150 in `pipeline_config.json`. Signs are anchored at one reference point today (S0 item 1) |
| POC touch points | S0 item 13 lists where a polygon would touch the POC code: fusion encroachment, validator `GEO-TRAVELED-WAY`, eligibility, rule engine `geometry_type`, placement path, SME overlay, annotated image, sheet renderer (a fixed symbolic box), evidence hashing. Most of these are replaced by S6 to S8 and S12, so S14 targets their **new** shapes, not the POC lines |
| Projection | `geometry/local_frame.py` has `enu()` (local east-north-up about a centre). No `shapely` or `pyproj` is installed |
| Real inputs | All six KMLs in `docs/references/kml/` hold Points only. No line or polygon example exists in the repo |

## 2. Scope and acceptance criteria

### In scope

1. **Validate** lines and polygons beyond S1's checks, and reject unusable ones with a reason.
2. **Orient and project**: a derived, normalised geometry in a local metric frame (outer ring and holes in a fixed winding), without changing the stored coordinates or the geometry hash.
3. **Map each geometry type to an engine work path** and a **work-space footprint** (station range along the road, lateral extent per side).
4. **Split lines over 150 m** (case 5, D-19), each piece flagged `ZONE_SPLIT_AUTOMATIC`; the same for polygons whose road extent is over 150 m (B-5).
5. **Polygon effects** on fusion (encroachment and remaining width), validators (traveled-way and width checks), grouping gaps (case 15), the SME image and the sheet drawing.
6. Lift `NOT_SUPPORTED_UNTIL_S14` so line and polygon zones run, with a project-record migration.

### Out of scope

New TAs, any change to Point behaviour, KML `ExtendedData` (D-66), reference-only toggles (future scope), a geometry library dependency unless B-9 approves it.

### Acceptance criteria

| # | Criterion | Reading |
| --- | --- | --- |
| 1 | A polygon with a hole and a concave polygon map to a valid work path | Synthetic fixtures on the three real roads: each gives a work path and footprint inside the road's analysed geometry, and the zone runs on fakes |
| 2 | An invalid ring is rejected with a reason | Each failure in section 5.1 gives its own reason code; the record is kept (nothing discarded) |
| 3 | Lines over 150 m are split | Into pieces of 150 m or less, each `ZONE_SPLIT_AUTOMATIC`, REVIEW_REQUIRED |
| 4 | Point behaviour unchanged | Every Point fixture replays with the same request fingerprints and outputs; no stored expected output changes |

## 3. Modules touched

New:

| Module | Purpose |
| --- | --- |
| `src/tcp_planner/geometry/validate.py` | Validity checks for lines and rings (section 5.1) |
| `src/tcp_planner/geometry/normalize.py` | `NormalizedGeometry`: local frame, winding, simplified duplicate vertices, length, area, principal axis |
| `src/tcp_planner/geometry/footprint.py` | Road projection: station range and lateral extent on the zone centerline; `WorkFootprint` |
| `src/tcp_planner/geometry/split.py` | Splitting long lines and long footprints (B-4, B-5) |
| `src/tcp_planner/geometry/planar.py` | Only if B-9 picks in-house geometry: segment intersection, point in polygon, polygon area, projection on a polyline |

Changed (target modules from S6, S8, S9, S12; names from their plans):

| Area | Change |
| --- | --- |
| `orchestration/projects.py` | Remove the `NOT_SUPPORTED_UNTIL_S14` gate behind a project-record migration (zone status and version) |
| Zone engine input (S3 `zone_input.json`) | Carries `footprint` and the normalised `work_path`; `schema_version` bump and migration |
| S6 fusion and pre-calculation | Encroachment and remaining width from the footprint's lateral extent when present (B-2) |
| S8 `WorkSpace` | `length_source = "KML_FOOTPRINT"`; upstream and downstream ends from the footprint (fills S8 B-6 for these zones) |
| S8 validators `LAY-WIDTH`, traveled-way check | Measured against the footprint edge |
| S9 grouping | Gaps between work-space extents, not between points; case 15 (point and line overlap) |
| S12 renderer | Draws the footprint to scale instead of the work-zone symbol |
| SME overlay image | Draws the footprint outline |

## 4. Data shapes

```
GeometryCheck { location_id, ok, reasons [ RING_SELF_INTERSECTS|RING_TOO_FEW_DISTINCT_POINTS|ZERO_AREA|ZERO_LENGTH|
                HOLE_OUTSIDE_OUTER|HOLES_OVERLAP|HOLE_TOUCHES_OUTER|LINE_SELF_INTERSECTS|SPIKE|TOO_LARGE ], details {} }

NormalizedGeometry {                               # derived; never replaces the stored coordinates
  schema_version, location_id, geometry_hash, kind LINE|POLYGON,
  frame { origin_latlon, method "ENU_LOCAL" }, outer_m [[x, y]] (counter-clockwise), holes_m [[[x, y]]] (clockwise),
  length_m | area_m2, principal_axis_deg, removed_vertices n }

WorkFootprint {
  schema_version, zone_id, source KML_LINE|KML_POLYGON|KML_POINT,
  centerline_ref, station_range_m [s0, s1], length_ft,
  lateral { side LEFT|RIGHT|BOTH, near_offset_m, far_offset_m, interval_m },   # from the road centerline
  crosses_centerline bool, holes_ignored n, representative_point latlon,
  work_path [latlon],                                                          # what the engine receives
  flags [ ZONE_SPLIT_AUTOMATIC, LINE_ACROSS_ROAD, SPANS_TWO_ROADS, NOT_ON_ROAD, HOLE_IGNORED ],
  trace { inputs [location_id, geometry_hash, centerline evidence], calculation, actor "ENGINE:footprint@<v>" } }
```

All persisted through the stores with refs, no raw path, `schema_version` on each.

## 5. How each step works (proposals)

### 5.1 Validation

| Check | Rule | Reason |
| --- | --- | --- |
| Distinct points | A line needs 2 distinct points; a ring 3 distinct points plus closure | `RING_TOO_FEW_DISTINCT_POINTS`, `ZERO_LENGTH` |
| Self-intersection | No two non-adjacent edges of a ring cross (bowtie); a line may not cross itself | `RING_SELF_INTERSECTS`, `LINE_SELF_INTERSECTS` |
| Area | Polygon area above a config floor | `ZERO_AREA` |
| Holes | Each hole inside the outer ring, not touching it, not overlapping another hole | `HOLE_OUTSIDE_OUTER`, `HOLE_TOUCHES_OUTER`, `HOLES_OVERLAP` |
| Spikes | No vertex whose two edges fold back within a config angle | `SPIKE` |
| Size | Longest dimension below a config ceiling (the imagery half-extent, about 365 m, S0 item 6) | `TOO_LARGE` |

Invalid geometry is never repaired (B-7). Thresholds are config (`geometry` section), not regulatory.

### 5.2 Orientation and projection

Local ENU about the location's first vertex (existing `enu()`); outer ring counter-clockwise, holes clockwise in that frame; consecutive duplicate vertices dropped in the derived copy only. The stored coordinates and the geometry hash do not change, so ids stay stable.

### 5.3 Mapping to a work path (two stages)

1. **Before any call (S9 pass 1)**: geometry only. A line's own vertices are its provisional work path; a polygon's provisional path is its principal axis clipped to the polygon. Used for grouping and the 150 m split.
2. **After the zone's road geometry exists (S6)**: project the footprint onto the zone centerline: station range = min and max station of all vertices; lateral extent = min and max signed offset per side; `crosses_centerline` when offsets of both signs exist. The engine work path is the centerline between `s0` and `s1`.

Holes are ignored for the extent and flagged (B-3). A line roughly across the road (B-6) and a footprint that spans two roads (case 6) raise questions instead of a path.

### 5.4 Splits

Lines over 150 m: cut into `ceil(L / 150)` equal pieces (B-4); polygons whose station range exceeds 150 m: cut by station (B-5). Each piece is its own zone with `ZONE_SPLIT_AUTOMATIC` and the cross-zone check flags the seam (D-19).

## 6. Commit sequence

Gate per commit: fast tier plus the impacted suites (intake, projects, pipeline, grouping, sheets); full suite once at the end. A Point-only replay check runs with every commit (acceptance 4).

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED`; `geometry` config section and guard entry | [B] with 1 | Housekeeping |
| 1 | `validate.py` (and `planar.py` or the dependency, B-9); invalid-ring fixtures | **[STOP]** if B-9 adds a dependency, else [B] | A `pyproject.toml` change needs approval |
| 2 | `normalize.py`; winding and projection tests; ids unchanged | [B] with 3 | |
| 3 | Synthetic fixtures: a concave polygon, a polygon with a hole, a line along the road, a line across the road, a 180 m line, a two-road polygon, on the Colorado, E Second St and Granite roads; marked as test inputs | [B] | No real line or polygon KML exists (A-1) |
| 4 | `footprint.py`: provisional and road-projected footprints | **[STOP]** | Decides the work space every TA strategy uses (B-1, B-2, B-3) |
| 5 | `split.py`: long lines and long footprints | **[STOP]** | B-4, B-5 |
| 6 | Project migration: lift `NOT_SUPPORTED_UNTIL_S14`, zone input `schema_version` bump | [B] | |
| 7 | Fusion and pre-calculation: encroachment and remaining width from the footprint | **[STOP]** | Safety-critical: feeds the lane-closure conflict check (D-59, D-57) |
| 8 | Layout and validators: `WorkSpace` from the footprint; `LAY-WIDTH` and the traveled-way check against it | [B] with 9 | |
| 9 | Grouping gaps between extents (case 15); SME overlay and sheet footprint drawing | [B] | |
| 10 | End-to-end on fakes for each fixture; the Point replay check | **[STOP]** | Acceptance |
| 11 | `docs/reports/S14_geometry_report.md`; full suite; the trigger for the final S15 run | [B] | |

## 7. Tests

| ID | Test | Covers |
| --- | --- | --- |
| T-1 | **Polygon fixtures**: concave, with a hole, convex, on each of the three roads; each gives a footprint and a work path | Acceptance 1 |
| T-2 | **Invalid rings**: bowtie, open ring (S1 already), three distinct points, zero area, hole outside, hole touching, overlapping holes, spike; one reason each; the record kept | Acceptance 2 |
| T-3 | **Long lines**: 149 m not split; 151 m and 400 m split into pieces of 150 m or less; each piece flagged; split result independent of vertex order and of the placemark order | Acceptance 3, D-19 |
| T-4 | **Ids stable**: normalising never changes `geometry_hash` or `location_id` | |
| T-5 | **Point behaviour unchanged**: every Point fixture replays with the same fingerprints; `tests/fixtures/expected/` unchanged | Acceptance 4 |
| T-6 | **Footprint numbers**: a hand-computed polygon gives the expected station range and lateral offsets within 0.01 m | |
| T-7 | **Mandatory fields never written**: a footprint that encroaches while the SME typed "no lane closure" raises a conflict question and leaves the field alone | CLAUDE.md rule 4 |
| T-8 | **Questions**: a line across the road, a two-road polygon and an off-road polygon each raise their question | Cases 6, 16, B-6 |
| T-9 | **Grouping with extents**: a point inside a line's extent joins its zone (case 15); gaps are measured between extents | |
| T-10 | **No live call**; any new request type for a footprint zone is served by fakes | CLAUDE.md |

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S9 grouping and the 150 m split | Case 5 and case 15 hooks | Not planned yet (A-2) |
| S6 centerline, road edges, encroachment and remaining-width calculation | Road projection, fusion effects | Planned (A-3) |
| S8 `WorkSpace`, `LAY-WIDTH`, envelope | Layout from the footprint | Planned (A-4) |
| S12 renderer | Drawing the footprint | Planned (A-5) |
| S3 projects and zone input | Migration | Merged |

Feeds: the final S15 run; S13 if the owner later records a line or polygon KML.

## 9. What could go stale if S6 to S8 change (assumptions)

| Assumption | If it changes |
| --- | --- |
| A-1: no real line or polygon input exists, so fixtures are synthetic | When the client sends one, a recording is needed (`TCP_LIVE=1`, owner) because the zone geometry is in the request fingerprint |
| A-2: S9 measures gaps between points and splits at the largest gaps; zones carry the case id | S14 changes the gap measure to extents |
| A-3: S6 exposes the zone centerline and road edges in metres with uncertainty, and computes encroachment from a work width (S6 Q10 option A: UNKNOWN without an SME footprint) | Road projection and the encroachment change in commit 7. If S6 already accepts a footprint, commit 7 shrinks |
| A-4: S8 `WorkSpace {upstream_end_station_m, downstream_end_station_m, side, lateral_near_offset_m, lateral_far_offset_m, length_source}` | Footprint mapping; with a footprint the S8 `POINT_ONLY` mode no longer applies to these zones |
| A-5: S12 draws the work location from an extent | Footprint drawing |
| A-6: the engine limit stays `max_work_path_m` = 150 | Split lengths |

## 10. Where the plan, the spec and the repo differ

1. The spec says "lines over 150 m are split (case 5)"; D-19 says "split at the largest gaps", and a line has no gaps (B-4).
2. Plan R11 rates polygons High and spreads their effects over fusion, validators and the SME image; most of those modules are being rewritten in S6 to S8 and S12, so S14's size depends on how those slices model the work space.
3. No real line or polygon input exists to test against.

## 11. OPEN QUESTIONS

### Part A: client inputs and SME questions

**A-1. What the client means by a line or a polygon in a KML.** A trench centerline, a work-area outline including equipment, the excavation only, or a route.
- Options: the client answers and sends one or two real examples.
- Effects: decides B-1 and B-2.
- Suggestion: ask with B-1.
- Blocks: commit 4 sign-off.

**A-2. A trench or line across the road.** Work across both directions usually means phased halves.
- Options: the SME says how such a crossing is drawn (two zones, one per half; or out of the MVP).
- Blocks: commit 4 for that case only.

**A-3. Polygons on both sides of the road or at an intersection.**
- Options: the SME says whether that is one job or several.
- Blocks: no (a question is raised meanwhile).

### Part B: owner decisions

**B-1. How a polygon becomes a work path.**
- Options: (a) project onto the road centerline (station range and lateral extent), as section 5.3; (b) centroid only, as a point; (c) a medial axis or skeleton.
- Effects: (b) loses the length and the encroachment, so S8 stays `POINT_ONLY`. (c) adds complexity with little gain on a straight road.
- Suggestion: (a).
- Blocks: commit 4.

**B-2. Is a KML polygon an authoritative work footprint?**
- Options: (a) yes: its lateral extent gives encroachment and remaining width (source KML, the client's drawn input, not fused geometry), and a contradiction with `lane_closure` raises a conflict; (b) display only: encroachment still comes from S6 and the SME; (c) authoritative for length, display only for width.
- Effects: (a) fills S6's UNKNOWN remaining width for these zones and makes the lane-closure conflict fire. A loosely drawn polygon then drives a safety check.
- Suggestion: (c) until A-1 is answered.
- Blocks: commit 7.

**B-3. Holes.**
- Options: (a) ignored for the extent and flagged `HOLE_IGNORED`; (b) a hole makes the polygon REVIEW_REQUIRED; (c) reject polygons with holes.
- Effects: the acceptance needs (a) or (b) (a polygon with a hole must map to a valid path).
- Suggestion: (a) plus REVIEW_REQUIRED, i.e. (a) and (b) together.
- Blocks: commit 4.

**B-4. How a long line is split.**
- Options: (a) equal pieces of 150 m or less; (b) at vertices nearest each 150 m mark; (c) at intersections first, then (a).
- Effects: D-19 speaks of gaps, which a line lacks.
- Suggestion: (c), falling back to (a).
- Blocks: commit 5.

**B-5. Polygons longer than 150 m along the road.**
- Options: (a) split by station like a line; (b) reject with `TOO_LARGE`; (c) a question to the SME.
- Suggestion: (a), flagged.
- Blocks: commit 5.

**B-6. A line or polygon across the road.**
- Options: (a) a question `LINE_ACROSS_ROAD` and no plan until answered; (b) treat as a lane closure in both directions; (c) reject.
- Effects: (b) decides a TA-relevant fact from geometry, which the SME should confirm.
- Suggestion: (a).
- Blocks: no.

**B-7. Invalid geometry: repair or reject?**
- Options: (a) reject with a reason, never repair; (b) repair simple cases (duplicate vertices, wrong winding) and reject the rest.
- Effects: winding and duplicate vertices are normalised in the derived copy in both options; (b) would also "fix" a bowtie, which changes the drawn shape.
- Suggestion: (a) for anything that changes the shape.
- Blocks: commit 1.

**B-8. Where normalisation runs.**
- Options: (a) at intake (S1 path), stored with the project; (b) in the zone stage, per run.
- Effects: (a) gives validation results before Run and lets the UI show reasons early.
- Suggestion: (a) for validation and the provisional footprint; the road projection necessarily per run.
- Blocks: commit 2.

**B-9. Geometry library.**
- Options: (a) add `shapely` (well tested; a new dependency in `pyproject.toml`); (b) in-house planar code (about 300 lines, fully tested here).
- Suggestion: (a) if the owner accepts the dependency; else (b).
- Blocks: commit 1.

**B-10. Recording a line or polygon zone.**
- Options: (a) fakes only in S14; (b) the owner records one synthetic polygon on a real road with `TCP_LIVE=1`; (c) wait for a client example (A-1).
- Suggestion: (a), then (c).
- Blocks: no.

**B-11. MultiGeometry with mixed parts.** S1 already gives each part its own location.
- Options: (a) keep that; grouping decides whether parts share a zone (case 15); (b) one location per placemark.
- Suggestion: (a).
- Blocks: no.

**B-12. When S14 runs.** It can follow S9 at any time, but it changes S6, S8, S9 and S12 code.
- Options: (a) right after S9, before S12, so S12 draws footprints from the start; (b) after S13, as the slices doc orders it.
- Effects: (a) avoids reworking the renderer; (b) keeps the golden path stable first.
- Suggestion: (b), with S12 already taking an extent (S12 plan, section 2).
- Blocks: no.

### Summary table

| # | Question | Group | Blocks S14? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | Meaning of lines and polygons; examples | Client input | Commit 4 sign-off | Ask with B-1 |
| A-2 | Crossing trench | SME question | Commit 4, that case | SME states the drawing rule |
| A-3 | Two-side or intersection polygons | SME question | No | Question meanwhile |
| B-1 | Polygon to work path | Decision | Commit 4 | Project onto the centerline |
| B-2 | Polygon as authoritative footprint | Decision | Commit 7 | Length yes, width display only |
| B-3 | Holes | Decision | Commit 4 | Ignore, flag, REVIEW_REQUIRED |
| B-4 | Long line split | Decision | Commit 5 | Intersections, then equal pieces |
| B-5 | Long polygons | Decision | Commit 5 | Split by station |
| B-6 | Across the road | Decision | No | Question, no plan |
| B-7 | Repair or reject | Decision | Commit 1 | Reject shape changes |
| B-8 | Where normalisation runs | Decision | Commit 2 | Intake; projection per run |
| B-9 | Geometry library | Decision | Commit 1 | `shapely` if accepted |
| B-10 | Recording a footprint zone | Decision | No | Fakes, then a client example |
| B-11 | MultiGeometry | Decision | No | One location per part |
| B-12 | Slice order | Decision | No | After S13; S12 takes extents |
