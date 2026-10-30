# S6 result outcomes: what NOT_PRESENT means per field

Generated from `src/tcp_planner/site_model/outcomes.py` (the single source; a test keeps it in step with `call1.FIELDS`).

- **FOUND**: the source looked and the thing is there, or the field has a value that is not an absence (a count, a side, a classification).
- **NOT_PRESENT**: the source looked and found nothing there. A real answer and a valid rule input.
- **UNKNOWN**: the source could not determine it (occluded, too blurry, malformed, no tag, source failed). No value; the reason code says why. A source that was not checked is never NOT_PRESENT.

| Field | NOT_PRESENT means |
| --- | --- |
| work_location | not applicable: a false or absent reading is FOUND or UNKNOWN |
| work_side | not applicable: a false or absent reading is FOUND or UNKNOWN |
| lanes_per_direction | not applicable: a false or absent reading is FOUND or UNKNOWN |
| oneway | not applicable: a false or absent reading is FOUND or UNKNOWN |
| shoulder_present | no usable shoulder next to the travel lanes was seen (OSM: shoulder tag says no) |
| divided_highway | no parallel opposite-direction carriageway was seen (OSM geometry: none within the configured distance) |
| median_work | not applicable: a false or absent reading is FOUND or UNKNOWN |
| bicycle_lane_present | no bicycle lane was seen next to the travel lanes |
| sidewalk_present | no sidewalk was seen beside the road (OSM: sidewalk tag none/no) |
| sidewalk_side | value NONE: no sidewalk on either side |
| parking_present | no on-street parking was seen along the road |
| bus_stop_present | no bus stop was seen at the work location |
| driveway_present | no driveway or side-street opening was seen at the work location |
| crosswalk_present | no marked crosswalk was seen at the work location |
| intersection_in_view | no intersection was seen in the image |
| grade_crossing_present | no railroad crossing was seen in the image |
| obstructions | value NONE: nothing blocks the view of the road |
| approaching_lanes_one | not applicable: a false or absent reading is FOUND or UNKNOWN |
