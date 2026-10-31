# S6 calibration values (step 14)

Generated from `config/site_understanding.json` (and `config/data_sources.json` for the Overpass limits). Every value below is a starting
value that is USED and carries the flag CALIBRATION_PENDING in the trace; none is a calibrated or regulatory number. A test
(`tests/unit/site/test_calibration_in_config.py`) keeps this list current, proves every value the code reads exists in config, and
proves the S6 modules contain no other number than structural ones (0, 1, 2, a half, 180 and 360 degrees, the luminance weights, the earth radius).

## CALIBRATION_PENDING (44)

| config path | value | what it controls |
| --- | --- | --- |
| `measurement/edge_pixel_error_px_cross_section` | 1.0 | D-38 example: one pixel of error on each edge. Starting value for the deterministic cross-section. S6 STOP 2: accepted as the starting model. |
| `measurement/edge_pixel_error_px_ai_marks` | 3.0 | Derived from the nine recorded spike widths (claude-opus-5-5, pre-tuning prompt, 3 sites x 3 repetitions): at the spike scale (about 0.44 m per pixel) all nine traveled-way widths fall inside the band (3.0 px x 2 edges) around their site's median, which 1.0 px and 2.0 px do not achieve. NOT calibrated against drawings (Q20). gpt-5.6-sol has not run; its marks may differ. Recorded as a test (test_ai_mark_error_evidence). |
| `crops/pending_features` | ["shoulder_edge", "curb", "sidewalk", "bicycle_lane"] | No pixels-per-feature value exists for these. Until one is calibrated they are never judged sufficient, so a higher-zoom view (up to the zoom ceiling) is always requested when one of them is needed. May cost extra Azure Maps requests. |
| `osm/query_radius_m` | 150 | radius of the one bounded Overpass query around the work point; must not exceed config/data_sources.json osm_overpass.query_limits.max_radius_m |
| `osm/max_way_distance_m` | 25 | a way farther than this from the work point is not the road of the job |
| `osm/divided_max_separation_m` | 60 | largest distance between the two carriageways of a divided road |
| `osm/divided_parallel_tolerance_deg` | 20 | largest angle (mod 180) between the two ways for them to count as parallel |
| `osm/divided_require_same_name_or_ref` | true | the opposite way must share the name or the ref of the chosen way |
| `osm/query_timeout_s` | 60 | the [timeout:N] of the Overpass query: how long the server may work on it. The first recording run timed out at 25 s on a busy public server |
| `osm/retry_waits_s` | [10, 30] | a failed or timed-out Overpass request is retried once per entry, waiting this many seconds first (so at most 2 retries: after 10 s, then after 30 s) |
| `bearing/tolerance_deg` | 30 | largest angle (mod 180) between the mark bearing and an OSM way bearing for them to be the same road |
| `bearing/which_road_distance_m` | 25 | OSM ways (service ways excluded) within this distance of the work point are the candidates for the reference road; the nearest is used only when it is clearly nearer than the next road that runs a different way (nearest_margin_m) |
| `bearing/nearest_margin_m` | 8 | the OSM reference way is the one nearest the work point only if it is at least this much nearer than the next road that runs a different way; otherwise the SME is asked which road. The marks never choose the reference way. |
| `edge_rule/near_edge_m` | 5 | within this distance of the nearest road edge (or with no road near) work_location is UNKNOWN plus one SME question |
| `edge_rule/no_road_near_m` | 25 | no road near: no OSM way within this distance of the work point and no usable road-edge marks. With a road within the distance a BEYOND_SHOULDER answer stays FOUND; with none the SME gets one question candidate (informational unless S7's what-if test makes it blocking) |
| `confidence_floors/default/safety_critical` | null | no floor applied until calibrated |
| `confidence_floors/default/common` | null | no floor applied until calibrated |
| `snapping/features` | ["road_edge_left", "road_edge_right", "shoulder_edge", "curb"] | marks that follow a step edge; lane lines are painted stripes and are not snapped |
| `snapping/search_radius_px` | 12 | how far from the AI's point, across the line, an edge is searched (pixels of the image as sent) |
| `snapping/sample_step_px` | 8 | spacing of the sample points along the AI's polyline |
| `snapping/min_edge_contrast` | 14 | smallest grey-level step (0 to 255) across a candidate edge for it to count as a real edge |
| `snapping/min_accepted_fraction` | 0.6 | a mark with a smaller share of sample points that found an edge is rejected (no_edge_nearby) |
| `snapping/smooth_window` | 5 | odd number of sample points of the median filter over the offsets along the line |
| `snapping/edge_arm_px` | 3 | samples on each side of a candidate edge averaged to measure the grey-level step; also the spread of a soft edge |
| `code_checks/stations` | 9 | cross-sections taken along the road strip between the two edge marks |
| `code_checks/lane_line_min_contrast` | 25 | grey-level excess of a painted line over the local pavement (0 to 255) |
| `code_checks/lane_line_max_width_px` | 7 | widest bright run that still counts as a painted line (pixels of the image as sent) |
| `code_checks/lane_line_merge_px` | 6 | two lines closer than this (a double yellow) count as one |
| `code_checks/lane_line_edge_margin_px` | 8 | lines this close to an edge mark are edge lines, not lane lines |
| `code_checks/lane_line_min_station_fraction` | 0.6 | a line must be seen in this share of the stations to count as detected |
| `code_checks/lane_line_position_tolerance_px` | 6 | lateral position tolerance when matching a line between stations |
| `code_checks/min_lines_to_judge` | 1 | with fewer painted lines than this detected the lane-line check does nothing (owner review R5: it never lowers confidence when no painted lines are detected) |
| `code_checks/green_margin` | 12 | a pixel is canopy when its green exceeds both red and blue by this much |
| `code_checks/shadow_luminance_ratio` | 0.6 | a non-canopy pixel is shadow when darker than this share of the strip's reference luminance |
| `code_checks/reference_percentile` | 75 | percentile of the non-canopy strip luminance used as the sunlit reference |
| `code_checks/occlusion_share_max` | 0.35 | code share of the road strip hidden by shadow plus canopy above which edge-based facts become UNKNOWN (occluded) |
| `code_checks/model_share_tolerance` | 0.25 | the model's shadow and canopy shares are a cross-check candidate: a difference above this is recorded as evidence; it never changes a fact |
| `code_checks/max_osm_offset_m` | 10 | largest distance between the road centre seen in the marks and the OSM reference way; above it OSM cannot confirm an AI value |
| `code_checks/min_cross_section_px` | 8 | a cross-section across the road strip with fewer pixels than this is skipped by the lane-line check |
| `consistency/lane_count_vs_width` | true | runs ONLY when parking_present and shoulder_present are both read false (owner review R5); plausible lane width range is read from pipeline_config fusion.lane_width_plausible_m |
| `consistency/lane_lines_vs_lane_count` | true | painted lane lines against the lane count; nothing happens when no painted line is detected (R5) |
| `consistency/approaching_lanes_vs_lane_count` | true | approaching_lanes_one against lanes_per_direction |
| `consistency/sidewalk_pair` | true | sidewalk_present against sidewalk_side |
| `consistency/work_location_vs_edges` | true | work_location against the work point and the edge marks (the marks check) |

Overpass limits (`config/data_sources.json`, osm_overpass.query_limits, CALIBRATION_PENDING): `max_radius_m` 600, `max_elements` 5000.

## With a named source (22)

| config path | value | source |
| --- | --- | --- |
| `call1/evidence_max_words` | 15 | S0 prompt tuning proposal P1, approved S6 Q3 B |
| `call1/safety_critical_fields` | ["lanes_per_direction", "divided_highway", "shoulder_present", "oneway"] | owner decision, S6 session 1 (Q7/Q8): AI plus OSM must agree, otherwise UNKNOWN |
| `call1/ai_only_review_fields` | ["median_work", "bicycle_lane_present", "approaching_lanes_one"] | owner decision, STOP 5 review R2 (2026-10-31) |
| `measurement/edges_per_width` | 2 | geometry: a width is bounded by two edges, each with the pixel error |
| `measurement/interval_includes_section_spread` | true | S6 Q9 A: interval = width +/- (edge error x mpp_sent x edges) plus the section spread |
| `defaults/work_vehicle_width_in` | 102 | 23 CFR 658.15 (maximum vehicle width 102 in); owner decision S6 session 1 |
| `defaults/work_space_depth_ft` | null | UNKNOWN |
| `defaults/work_space_clearance_ft` | null | UNKNOWN |
| `crops/lane_group` | ["lane", "road_edge", "lane_line"] | S6 Q15 A: the existing crops.min_px_per_lane applies to the lane features |
| `crops/zoom_ceiling` | "crops.primary_zoom" | config/pipeline_config.json crops.primary_zoom (the documented maximum of the microsoft.imagery tileset); no higher zoom is ever requested, so the upsampling sharpness check (sharpness.min_detail_gain_ratio) is not needed here |
| `osm/highway_classes` | ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"] | OSM wiki Key:highway (road classes a vehicle can use); service included for driveways and parking aisles so they can be told apart, never chosen over a named road |
| `confidence_floors/default/work_location` | 0.85 | owner decision, S6 session 1 |
| `stages/osm` | true | owner decision, S6 plan item 10 |
| `stages/bearing` | true | owner decision, S6 plan item 10 |
| `stages/snapping` | true | owner decision, S6 plan item 10 |
| `stages/edge_rule` | true | owner decision, S6 plan item 10 |
| `stages/lane_lines` | true | owner decision, S6 plan item 10 |
| `stages/shadow_canopy` | true | owner decision, S6 plan item 10 |
| `stages/osm_offset` | true | owner decision, S6 plan item 10 |
| `stages/consistency` | true | owner decision, S6 plan item 10 |
| `stages/site_exceptions` | true | owner decision, S6 addendum |
| `stages/enhanced_prompt` | false | owner decision, STOP 6 |
