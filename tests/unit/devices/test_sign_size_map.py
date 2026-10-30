"""Catalog id -> pack size designation (S5): every catalog id has exactly one size row, or none with a stated reason."""
import pytest

from tcp_planner.rules.device_catalog import load_catalog
from tcp_planner.rules.rule_pack_effective import sign_size
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.rules.sign_size_map import NO_SIZE_ROW, NOT_A_SIGN, PACK_DESIGNATION, size_designation


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def _size_rows(pack):
    defs = {d.id for d in pack.records("table_def") if set(d.key_fields) == {"sign"}}
    return [r for r in pack.records("table_row") if r.table_def_id in defs]


def test_every_catalog_id_is_in_exactly_one_place(cat):
    for e in cat.entries:
        places = [e.device_id in PACK_DESIGNATION, e.device_id in NO_SIZE_ROW, e.code_status.value == "DEVICE"]
        assert sum(places) == 1, (e.device_id, places)
    assert set(PACK_DESIGNATION) | set(NO_SIZE_ROW) <= {e.device_id for e in cat.entries}


def test_every_catalog_id_resolves_to_exactly_one_size_row_or_a_stated_reason(cat, pack):
    rows = _size_rows(pack)
    for e in cat.entries:
        designation, reason = size_designation(e)
        if designation is None:
            assert reason and reason.strip()
            assert not [r for r in rows if r.key["sign"] == e.device_id], f"{e.device_id} has a row but is listed without one"
            assert sign_size(pack, e.device_id, "conventional")["status"] == "UNKNOWN" or e.code_status.value == "DEVICE"
        else:
            hits = [r for r in rows if r.key == {"sign": designation}]
            assert len(hits) == 1, (e.device_id, designation, len(hits))
            assert sign_size(pack, designation, "conventional")["record_id"] == hits[0].id


def test_size_source_pack_means_a_mapped_pack_size_row(cat):
    for e in cat.entries:
        assert (e.size_source.value == "PACK") == (e.device_id in PACK_DESIGNATION), e.device_id


def test_no_mapped_designation_is_a_stranger(cat, pack):
    designations = {r.key["sign"] for r in _size_rows(pack)}
    assert set(PACK_DESIGNATION.values()) <= designations
    covered = set(PACK_DESIGNATION.values())
    assert designations - covered == set()      # no gap: every pack size row is read by at least one catalog entry


def test_left_right_variants_read_their_designation_row(cat):
    expect = {"R9-10L": "R9-10", "R9-11L": "R9-11", "R9-11R": "R9-11", "M4-9L": "M4-9", "M4-9R": "M4-9",
              "W20-5L": "W20-5L", "W20-5R": "W20-5R", "W4-2L": "W4-2L", "W4-2R": "W4-2R",
              "M4-9a-L": "M4-9a", "M4-9a-R": "M4-9a", "M4-9b": "M4-9b", "M4-9c-L": "M4-9c", "M4-9c-R": "M4-9c"}
    for k, v in expect.items(): assert PACK_DESIGNATION[k] == v


def test_devices_are_not_signs(cat):
    for e in cat.entries:
        if e.code_status.value == "DEVICE": assert size_designation(e) == (None, NOT_A_SIGN)


def test_new_detour_entries_are_placeholders_with_legend_only_and_no_pack_device_rows(cat, pack):
    import re
    new = ["M4-9a-L", "M4-9a-R", "M4-9b", "M4-9c-L", "M4-9c-R"]
    arrows = {"M4-9a-L", "M4-9a-R", "M4-9c-L", "M4-9c-R"}          # Sect. 6I.02 para 11 (M4-9a) and the Table 6I-1 title (M4-9c)
    quotes = {"M4-9a": "Bike/Pedestrian Detour", "M4-9b": "Pedestrian Detour", "M4-9c": "Bike Detour (with arrow)"}
    for i in new:
        e = cat.get(i)
        assert e.asset.status.value == "PLACEHOLDER_ASSET" and e.size_source.value == "PACK"
        svg = open(cat.asset_path(i), encoding="utf-8").read()
        assert "PLACEHOLDER_ASSET" in svg and "PLACEHOLDER" in re.sub("<!--.*?-->", "", svg)   # a visible label, not only the comment
        assert "<polygon" not in svg and "<path" not in svg                                       # legend text only: no arrow glyph
        base = PACK_DESIGNATION[i]
        assert any(q in pack.get(r.source_ref_ids[0]).quote for r in pack.records("table_row") if r.key == {"sign": base}
                   for q in [quotes[base]])
    assert {e for e in new if e.endswith(("L", "R"))} == arrows
    assert not [d for d in pack.records("device") if d.catalog_id in new]
    assert not [u for u in pack.records("ta_device_use") if u.device_id in {"DV-" + i for i in new}]
