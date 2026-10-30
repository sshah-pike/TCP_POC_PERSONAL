"""Result outcomes of a fact (S6): FOUND, NOT_PRESENT, UNKNOWN. One module, so every reader means the same thing.

  FOUND        the source looked and the thing is there (a presence field is true), or the field has a value that is not a
               yes/no presence (a count, a side, a classification such as oneway=false).
  NOT_PRESENT  the source looked and found nothing there. Only presence fields have it; the value is False (or NONE).
               It is a real answer and a valid rule input, unlike UNKNOWN.
  UNKNOWN      the source could not determine it: occluded, too blurry, malformed, no tag, the source failed. No value.
               The reason code says which of these. An unchecked source is never NOT_PRESENT.

`NOT_PRESENT_MEANING` is the written definition per call 1 field; `None` means the field has no NOT_PRESENT outcome (a
false value is then FOUND, or the field always has a value). A test keeps this table in step with `call1.FIELDS`.
"""
FOUND, NOT_PRESENT, UNKNOWN = "FOUND", "NOT_PRESENT", "UNKNOWN"
OUTCOMES = (FOUND, NOT_PRESENT, UNKNOWN)
HAS_VALUE = (FOUND, NOT_PRESENT)

NOT_PRESENT_MEANING = {
    "work_location": None,
    "work_side": None,
    "lanes_per_direction": None,
    "oneway": None,                          # false is FOUND: a two-way road is a classification, not an absent feature
    "shoulder_present": "no usable shoulder next to the travel lanes was seen (OSM: shoulder tag says no)",
    "divided_highway": "no parallel opposite-direction carriageway was seen (OSM geometry: none within the configured distance)",
    "median_work": None,                     # the work is or is not in a median; false is FOUND
    "bicycle_lane_present": "no bicycle lane was seen next to the travel lanes",
    "sidewalk_present": "no sidewalk was seen beside the road (OSM: sidewalk tag none/no)",
    "sidewalk_side": "value NONE: no sidewalk on either side",
    "parking_present": "no on-street parking was seen along the road",
    "bus_stop_present": "no bus stop was seen at the work location",
    "driveway_present": "no driveway or side-street opening was seen at the work location",
    "crosswalk_present": "no marked crosswalk was seen at the work location",
    "intersection_in_view": "no intersection was seen in the image",
    "grade_crossing_present": "no railroad crossing was seen in the image",
    "obstructions": "value NONE: nothing blocks the view of the road",
    "approaching_lanes_one": None,           # false means more than one approaching lane: FOUND
}

# the value that means "nothing there" for a field that has a NOT_PRESENT outcome
ABSENT_VALUES = {"sidewalk_side": "NONE", "obstructions": "NONE"}


def has_not_present(field):
    return NOT_PRESENT_MEANING.get(field) is not None


def outcome_for(field, value):
    """UNKNOWN for no value; NOT_PRESENT when a presence field says nothing is there; else FOUND."""
    if value is None:
        return UNKNOWN
    if has_not_present(field):
        absent = ABSENT_VALUES.get(field, False)
        if value is False or (isinstance(absent, str) and isinstance(value, str) and value.strip().upper() == absent):
            return NOT_PRESENT
    return FOUND
