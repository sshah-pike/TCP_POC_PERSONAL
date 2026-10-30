"""Sign sizes in the pack (S4b): Tables 6G-1, 6H-1 and 6I-1, one row per sign, read through sign_size() only.

Every catalog id S8 can place (the catalog_id of a pack device) resolves to exactly one size row, or to none for a
stated reason. A size the table prints as "—" is a gap with an SME question, never 0 and never another column's size.
"""
import json, os, re
import pytest
from tcp_planner.rules.rule_pack_effective import SIGN_SIZE_COLUMNS, sign_size
from tcp_planner.rules.rule_pack_store import JsonRulePackStore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CATALOG = os.path.join(ROOT, "assets", "symbols", "device_catalog.json")

# Pack devices with no size row, and why. Anything else S8 can place must have exactly one row.
NO_SIZE_ROW = {
    "DV-ARROW-BOARD": "not a sign; arrow-board sizes (Sect. 6L.06) not loaded (owner decision S4b stage A, item 5)",
    "DV-FLAGGER": "not a sign",
    "DV-WORK-VEHICLE": "not a sign",
    "DV-TMA": "not a sign",
}
# Client codes in the catalog that no MUTCD size table lists: no size, an SME question (owner decision S4b stage A, item 4).
CLIENT_CODES = {"M4-9AL": "R-SIGN-SIZE-M4-9AL", "R9-3BR": "R-SIGN-SIZE-R9-3BR"}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


@pytest.fixture(scope="module")
def catalog_ids():
    with open(CATALOG, encoding="utf-8") as f: return {e["id"] for e in json.load(f)["entries"]}


def _size_rows(pack):
    defs = {d.id for d in pack.records("table_def") if set(d.key_fields) == {"sign"}}
    return [r for r in pack.records("table_row") if r.table_def_id in defs]


def test_every_placeable_catalog_id_resolves_to_one_size_row_or_a_stated_reason(pack, catalog_ids):
    rows = _size_rows(pack)
    for dev in pack.records("device"):
        assert dev.catalog_id in catalog_ids, f"{dev.id}: catalog id {dev.catalog_id} not in the catalog"
        hits = [r for r in rows if r.key == {"sign": dev.code}]
        if dev.id in NO_SIZE_ROW:
            assert hits == [], f"{dev.id} is listed as having no size but has {[r.id for r in hits]}"
            assert sign_size(pack, dev.code, "conventional")["status"] == "UNKNOWN"
        else:
            assert len(hits) == 1, f"{dev.id} ({dev.code}): {len(hits)} size rows"
            assert sign_size(pack, dev.code, "conventional")["record_id"] == hits[0].id
    assert set(NO_SIZE_ROW) <= {d.id for d in pack.records("device")}


def test_size_rows_are_unique_per_sign(pack):
    keys = [r.key["sign"] for r in _size_rows(pack)]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("code", sorted(CLIENT_CODES))
def test_client_codes_have_no_size_and_raise_a_question(pack, catalog_ids, code):
    assert code in catalog_ids
    assert not [r for r in _size_rows(pack) if r.key["sign"] == code]
    got = sign_size(pack, code, "conventional")
    rec = pack.get(CLIENT_CODES[code])
    assert got["status"] == "UNKNOWN" and got["width_in"] is None and got["height_in"] is None
    assert got["record_id"] == rec.id and got["sme_question"] == rec.sme_question and rec.status.value == "UNKNOWN"


def test_every_size_is_the_number_printed_in_its_quote(pack):
    """Each row's quote ends in the three printed columns; the values are exactly those, '—' as null."""
    for r in _size_rows(pack):
        quote = pack.get(r.source_ref_ids[0]).quote
        cols = re.findall(r"(\d+ x \d+|—)", quote)[-3:]
        for col, printed in zip(SIGN_SIZE_COLUMNS, cols):
            want = (None, None) if printed == "—" else tuple(int(x) for x in printed.split(" x "))
            assert (r.values[f"{col}_width"], r.values[f"{col}_height"]) == want, (r.id, col, printed)


def test_a_dash_size_is_a_gap_with_a_question_never_zero_or_another_column(pack):
    gaps = 0
    for r in _size_rows(pack):
        for col in SIGN_SIZE_COLUMNS:
            if r.values[f"{col}_width"] is not None: continue
            gaps += 1
            got = sign_size(pack, r.key["sign"], col)
            assert got["status"] == "SOURCE_REVIEW_REQUIRED" and got["sme_question"]
            assert got["width_in"] is None and got["height_in"] is None      # not 0, not a fallback
            assert got["record_id"] == r.id
    assert gaps > 0
    w16 = sign_size(pack, "W16-2P", "minimum")
    conv = sign_size(pack, "W16-2P", "conventional")
    assert conv["status"] == "SOURCED" and (conv["width_in"], conv["height_in"]) == (24, 18)
    assert w16["status"] == "SOURCE_REVIEW_REQUIRED" and w16["width_in"] != 0 and w16["width_in"] != conv["width_in"]
    r9 = sign_size(pack, "R9-9", "freeway_expressway")
    assert r9["status"] == "SOURCE_REVIEW_REQUIRED" and r9["width_in"] is None


def test_sourced_size_carries_its_trace(pack):
    got = sign_size(pack, "W20-1", "freeway_expressway")
    assert (got["status"], got["width_in"], got["height_in"], got["unit"]) == ("SOURCED", 48, 48, "in")
    ref = got["trace"]["source_refs"][0]
    assert (ref["table"], ref["page"], ref["strength"]) == ("6H-1", "804", "STANDARD") and got["trace"]["pack_hash"] == pack.hash


def test_side_variants_carry_the_owner_approved_interpretation(pack):
    for code in ("W20-5R", "W20-5L", "W4-2R", "W4-2L"):
        got = sign_size(pack, code, "conventional")
        assert got["status"] == "SOURCED" and got["interpretation"].startswith("INTERPRETATION:")
    assert pack.get("R-SIGN-NAMING-W4-2-SIDE").status.value == "SOURCE_REVIEW_REQUIRED"


def test_unknown_column_is_an_error(pack):
    with pytest.raises(ValueError): sign_size(pack, "W20-1", "large")
