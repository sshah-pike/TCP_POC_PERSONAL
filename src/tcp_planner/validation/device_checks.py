"""Device validators (S5): every placed device exists in the catalog, and its size comes from the rule pack.

Input: placed objects `{object_id, device_id}` (S8 will add the size it drew, as `size: {width_in, height_in}`) and the
road type. Output: validator-result records in the shape of validation/validators.py (`id`, `status` PASS or FAIL,
`severity`, `detail`), with the object, the device, the pack and catalog versions and hashes for the trace.

A device whose size is SOURCE_REVIEW_REQUIRED or UNKNOWN passes, but `forces_review` is set and the device is named
(Q12 A); the plan is REVIEW_REQUIRED. A drawn size that differs from the pack's size fails. A size is never taken from
the catalog (it holds none) and never from another column.
"""
from tcp_planner.contracts import TcpError
from tcp_planner.rules.device_sizes import size_for


def _result(cid, ok, placed, detail, pack, catalog, **extra):
    return {"id": cid, "status": "PASS" if ok else "FAIL", "severity": "BLOCK", "object_id": placed.get("object_id"),
            "device_id": placed.get("device_id"), "detail": detail, "pack_id": pack.id, "pack_version": pack.version,
            "pack_hash": pack.hash, "catalog_version": catalog.version, "catalog_hash": catalog.hash, **extra}


def validate_devices(placed_objects, road_type, pack, catalog):
    """Check each placed device. Returns {"checks": [...], "forces_review": bool, "review_devices": [...], "ok": bool}."""
    checks, review = [], []
    for placed in placed_objects:
        did = placed.get("device_id")
        if not isinstance(did, str) or not catalog.has(did):
            checks.append(_result("DEVICE_EXISTS", False, placed, f"device {did!r} is not in the device catalog", pack, catalog))
            continue
        checks.append(_result("DEVICE_EXISTS", True, placed, "in the catalog", pack, catalog))
        try: size = size_for(pack, catalog, did, road_type)
        except TcpError as e:
            checks.append(_result("DEVICE_SIZE_FROM_PACK", False, placed, str(e), pack, catalog)); continue
        drawn = placed.get("size")
        if drawn is not None and size["status"] == "SOURCED" and (drawn.get("width_in"), drawn.get("height_in")) != (size["width_in"], size["height_in"]):
            checks.append(_result("DEVICE_SIZE_FROM_PACK", False, placed,
                                  f"drawn {drawn.get('width_in')} x {drawn.get('height_in')} in differs from the pack's "
                                  f"{size['width_in']} x {size['height_in']} in ({size['record_id']}, column {size['column']})",
                                  pack, catalog, size_record_id=size["record_id"]))
            continue
        if drawn is not None and size["status"] in ("SOURCE_REVIEW_REQUIRED", "UNKNOWN") and (drawn.get("width_in") is not None or drawn.get("height_in") is not None):
            checks.append(_result("DEVICE_SIZE_FROM_PACK", False, placed,
                                  f"a size was drawn for {did} but the pack has none ({size['status']}): it was not read from the pack",
                                  pack, catalog))
            continue
        if size["requires_review"]:
            review.append(did)
            checks.append(_result("DEVICE_SIZE_FROM_PACK", True, placed, f"{size['status']}: {size['reason']}", pack, catalog,
                                  forces_review=True, review_reason=size["review_reason"], sme_question=size["sme_question"],
                                  size_record_id=size["record_id"]))
        else:
            checks.append(_result("DEVICE_SIZE_FROM_PACK", True, placed,
                                  "not a sign: no pack size" if size["status"] == "NOT_APPLICABLE" else "size read from the pack",
                                  pack, catalog, size_record_id=size["record_id"], column=size["column"]))
    return {"checks": checks, "forces_review": bool(review), "review_devices": sorted(set(review)),
            "ok": all(c["status"] == "PASS" for c in checks)}
