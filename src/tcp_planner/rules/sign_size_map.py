"""Catalog id -> pack size designation (S5). The one table that says which Tables 6G-1, 6H-1 and 6I-1 row sizes a catalog entry.

The pack holds one size row per MUTCD designation, keyed `{"sign": <designation>}` (rule_pack/base/sign_sizes.json,
read through rule_pack_effective.sign_size). The catalog has some left/right variants of one designation, and a few
entries no size table lists. Every catalog id is in exactly one of three places here:

- PACK_DESIGNATION: the id has a size row, under the designation given (the id itself, or the base designation for a variant);
- NO_SIZE_ROW: the id has no size row, for the stated reason;
- a DEVICE entry (code_status DEVICE): not a sign, no size row; its size_text is informational only.

tests/unit/devices/test_sign_size_map.py checks this table against the catalog and the pack.
"""
from tcp_planner.rules.device_catalog import CodeStatus

# Catalog id -> designation of the pack size row. A left or right variant reads the row of its designation: the table
# prints one size per designation and does not size the variants separately.
PACK_DESIGNATION = {
    "W20-1": "W20-1", "W20-4": "W20-4", "W20-7": "W20-7", "W16-2P": "W16-2P", "G20-2": "G20-2",
    "W20-5R": "W20-5R", "W20-5L": "W20-5L", "W4-2R": "W4-2R", "W4-2L": "W4-2L",   # side readings owner-approved in S4b
    "W21-5": "W21-5", "W5-1": "W5-1", "W3-4": "W3-4",
    "R9-9": "R9-9", "R9-11a": "R9-11a", "M4-8a": "M4-8a",
    "R9-10L": "R9-10", "R9-11L": "R9-11", "R9-11R": "R9-11", "M4-9L": "M4-9", "M4-9R": "M4-9",
    "M4-9a-L": "M4-9a", "M4-9a-R": "M4-9a", "M4-9b": "M4-9b", "M4-9c-L": "M4-9c", "M4-9c-R": "M4-9c",
}

_NOT_LISTED = "no size row in pack 1.1.0 (Tables 6G-1, 6H-1 and 6I-1 rows not loaded); no in-scope TA uses it"
_CLIENT = "client or state code that no MUTCD size table lists; the pack has an SME question (R-SIGN-SIZE-<code>) or none yet"
NO_SIZE_ROW = {
    "W21-5a": _NOT_LISTED, "W9-2L": _NOT_LISTED, "R8-3": _NOT_LISTED, "R2-10": _NOT_LISTED, "R2-11": _NOT_LISTED,
    "R3-7R": _NOT_LISTED, "R1-1-PADDLE": _NOT_LISTED,
    "M4-9AL": _CLIENT, "R9-3BR": _CLIENT, "CLIENT-POLICE-OFFICER-AHEAD": _CLIENT, "RI-27.1.1": _CLIENT,
}
NOT_A_SIGN = "not a sign: a device, drawn from its symbol; size_text is informational"


def size_designation(entry):
    """(designation, None) for a catalog entry with a pack size row, else (None, the stated reason)."""
    if entry.device_id in PACK_DESIGNATION: return PACK_DESIGNATION[entry.device_id], None
    if entry.code_status == CodeStatus.DEVICE: return None, NOT_A_SIGN
    return None, NO_SIZE_ROW[entry.device_id]
