"""size_for (S5): the size of a placed catalog device for a road type, read from the rule pack.

This wraps rule_pack_effective.sign_size() and adds only two things: which catalog id reads which pack row
(sign_size_map.py) and which table column a road type uses. It has no size logic of its own and no number.

Column choice (owner decision Q3 A, PROPOSED: the SME has not confirmed it, SME question 38): URBAN_LOW_SPEED,
URBAN_HIGH_SPEED and RURAL read the Conventional column; EXPRESSWAY_FREEWAY reads the Freeway column. The Minimum
column is never selected automatically. A column the table prints as "-" is a gap: it is not read as 0 and is never
replaced by the Conventional size.

A size that is SOURCE_REVIEW_REQUIRED or UNKNOWN does not stop the plan (Q12 A): the result says `requires_review` and
names the device, and the plan is REVIEW_REQUIRED.
"""
from tcp_planner.rules.rule_pack_effective import sign_size
from tcp_planner.rules.sign_size_map import size_designation

COLUMN_FOR_ROAD_TYPE = {
    "URBAN_LOW_SPEED": "conventional",
    "URBAN_HIGH_SPEED": "conventional",
    "RURAL": "conventional",
    "EXPRESSWAY_FREEWAY": "freeway_expressway",
}
COLUMN_MAPPING_STATUS = "PROPOSED"      # until the SME confirms it (SME question 38)


def size_for(pack, catalog, device_id, road_type):
    """Size result for one catalog device on one road type.

    status is SOURCED, SOURCE_REVIEW_REQUIRED or UNKNOWN for a sign (width_in and height_in are numbers only when
    SOURCED), or NOT_APPLICABLE for a device that is not a sign. An unknown device raises DEVICE_UNKNOWN. An unknown road
    type gives UNKNOWN, never a default column.
    """
    entry = catalog.get(device_id)
    out = {"device_id": device_id, "road_type": road_type, "designation": None, "column": COLUMN_FOR_ROAD_TYPE.get(road_type),
           "column_mapping_status": COLUMN_MAPPING_STATUS, "width_in": None, "height_in": None, "unit": "in",
           "requires_review": False, "review_reason": None, "record_id": None, "trace": None, "sme_question": None,
           "reason": None, "catalog_hash": catalog.hash}
    designation, why = size_designation(entry)
    if designation is None:
        if entry.code_status.value == "DEVICE":
            return {**out, "status": "NOT_APPLICABLE", "reason": why}
        return {**out, "status": "UNKNOWN", "requires_review": True, "review_reason": "SIZE_UNKNOWN", "reason": why,
                "sme_question": f"No size row for {device_id}. What size should be drawn?"}
    out["designation"] = designation
    if out["column"] is None:
        return {**out, "status": "UNKNOWN", "requires_review": True, "review_reason": "SIZE_UNKNOWN",
                "reason": f"road type {road_type!r} has no size column; none is assumed",
                "sme_question": f"Which size column applies to road type {road_type}?"}
    r = sign_size(pack, designation, out["column"])
    out.update(status=r["status"], width_in=r["width_in"], height_in=r["height_in"], record_id=r.get("record_id"),
               trace=r.get("trace"), sme_question=r.get("sme_question"), reason=r.get("reason"))
    if r["status"] != "SOURCED":
        out.update(requires_review=True, review_reason=f"SIZE_{r['status']}")
    return out
