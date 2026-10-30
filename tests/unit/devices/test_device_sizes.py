"""size_for, placeholder status and device validators (S5). Offline."""
import ast, copy, inspect, json, os, re

import pytest

from tcp_planner.contracts import TcpError
from tcp_planner.rules import device_catalog as dc
from tcp_planner.rules import device_sizes
from tcp_planner.rules.device_catalog import load_catalog
from tcp_planner.rules.device_sizes import COLUMN_FOR_ROAD_TYPE, COLUMN_MAPPING_STATUS, size_for
from tcp_planner.rules.rule_pack_effective import sign_size
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.rules.sign_size_map import PACK_DESIGNATION
from tcp_planner.validation.device_checks import validate_devices

ROAD_TYPES = ["URBAN_LOW_SPEED", "URBAN_HIGH_SPEED", "RURAL", "EXPRESSWAY_FREEWAY"]


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def test_column_mapping_covers_exactly_the_registry_road_types_and_is_proposed(pack):
    assert set(COLUMN_FOR_ROAD_TYPE) == set(pack.get("road_type").enum_values) == set(ROAD_TYPES)
    assert COLUMN_MAPPING_STATUS == "PROPOSED"
    assert "minimum" not in COLUMN_FOR_ROAD_TYPE.values()          # Minimum is never selected automatically
    assert [COLUMN_FOR_ROAD_TYPE[r] for r in ROAD_TYPES] == ["conventional"] * 3 + ["freeway_expressway"]


@pytest.mark.parametrize("road_type", ROAD_TYPES)
@pytest.mark.parametrize("device_id", sorted(PACK_DESIGNATION))
def test_size_for_equals_sign_size_of_the_mapped_column(pack, cat, device_id, road_type):
    got = size_for(pack, cat, device_id, road_type)
    want = sign_size(pack, PACK_DESIGNATION[device_id], COLUMN_FOR_ROAD_TYPE[road_type])
    assert got["column"] == COLUMN_FOR_ROAD_TYPE[road_type] and got["column_mapping_status"] == "PROPOSED"
    assert got["status"] == want["status"] and got["record_id"] == want.get("record_id")
    assert (got["width_in"], got["height_in"]) == (want["width_in"], want["height_in"])
    if want["status"] == "SOURCED":
        assert not got["requires_review"] and got["width_in"] > 0 and got["trace"]["pack_hash"] == pack.hash
    else:
        assert got["requires_review"] and got["width_in"] is None and got["height_in"] is None and got["sme_question"]


def test_every_sourced_size_is_the_number_in_its_quote(pack, cat):
    """Quote check for every size S5 can return: the numbers equal the ones printed in the cited row's quote."""
    for device_id in PACK_DESIGNATION:
        for road_type in ROAD_TYPES:
            r = size_for(pack, cat, device_id, road_type)
            if r["status"] != "SOURCED": continue
            quote = r["trace"]["source_refs"][0]
            quote = pack.get(quote["source_ref_id"]).quote
            col = {"conventional": 0, "freeway_expressway": 1}[r["column"]]
            printed = re.findall(r"(\d+ x \d+|—)", quote)[-3:][col]
            assert printed == f"{r['width_in']} x {r['height_in']}", (device_id, road_type, printed)
            assert r["trace"]["source_refs"][0]["page"] and r["trace"]["source_refs"][0]["table"]


def test_a_dash_column_is_a_gap_never_zero_never_the_conventional_size(pack, cat):
    for did in ("R9-9", "R9-10L", "R9-11L", "R9-11R", "R9-11a", "M4-9a-L", "M4-9b", "M4-9c-R"):
        r = size_for(pack, cat, did, "EXPRESSWAY_FREEWAY")
        assert r["status"] == "SOURCE_REVIEW_REQUIRED" and r["width_in"] is None and r["requires_review"]
        assert r["review_reason"] == "SIZE_SOURCE_REVIEW_REQUIRED" and r["device_id"] == did
        conv = size_for(pack, cat, did, "RURAL")
        assert conv["status"] == "SOURCED" and conv["width_in"]          # the Conventional column is its own, not a stand-in


def test_signs_with_no_size_row_and_client_codes_are_unknown_and_force_review(pack, cat):
    for did in ("R8-3", "R2-11", "W9-2L", "M4-9AL", "R9-3BR", "CLIENT-POLICE-OFFICER-AHEAD", "RI-27.1.1"):
        r = size_for(pack, cat, did, "RURAL")
        assert r["status"] == "UNKNOWN" and r["requires_review"] and r["review_reason"] == "SIZE_UNKNOWN"
        assert r["width_in"] is None and r["height_in"] is None and r["reason"] and r["device_id"] == did


def test_devices_are_not_applicable_and_do_not_force_review(pack, cat):
    r = size_for(pack, cat, "DEV-CONE", "RURAL")
    assert r["status"] == "NOT_APPLICABLE" and not r["requires_review"] and r["width_in"] is None


def test_unknown_device_raises_and_unknown_road_type_is_unknown_not_a_default(pack, cat):
    with pytest.raises(TcpError) as ex: size_for(pack, cat, "NOPE", "RURAL")
    assert ex.value.code == "DEVICE_UNKNOWN"
    r = size_for(pack, cat, "W20-1", "GRAVEL")
    assert r["status"] == "UNKNOWN" and r["column"] is None and r["requires_review"] and r["width_in"] is None


def test_size_for_has_no_size_logic_or_number_of_its_own():
    tree = ast.parse(inspect.getsource(device_sizes))
    nums = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)]
    assert nums == []
    assert "json" not in {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}


# ---- placeholder status (A5) ----

def test_placeholder_status_lists_only_placeholders_and_gives_the_label(cat):
    s = cat.placeholder_status(["W20-1", "DEV-CONE", "W20-1"])
    assert s == {"uses_placeholder": True, "device_ids": ["DEV-CONE", "W20-1"], "reason_code": "PLACEHOLDER_ASSET",
                 "label": "PLACEHOLDER SYMBOLS - NOT CLIENT LIBRARY", "requires_review": True}
    none = cat.placeholder_status([])
    assert none["uses_placeholder"] is False and none["requires_review"] is False and none["device_ids"] == []
    with pytest.raises(TcpError): cat.placeholder_status(["NOPE"])


def test_a_client_asset_is_not_a_placeholder_and_a_mixed_plan_lists_only_placeholders(tmp_path, monkeypatch):
    import shutil
    assets = tmp_path / "assets"
    shutil.copytree(os.path.join(dc.ASSETS_DIR, "symbols"), assets / "symbols")
    monkeypatch.setattr(dc, "ASSETS_DIR", str(assets))
    monkeypatch.setattr(dc, "DEVICE_CATALOG_PATH", str(assets / "symbols" / "device_catalog.json"))
    p = assets / "symbols" / "device_catalog.json"
    doc = json.load(open(p, encoding="utf-8"))
    for e in doc["entries"]:
        if e["device_id"] == "W20-1": e["asset"]["status"] = "CLIENT_ASSET"
    json.dump(doc, open(p, "w", encoding="utf-8"))
    dc.seal()
    c = load_catalog()
    assert c.placeholder_status(["W20-1"])["uses_placeholder"] is False
    mixed = c.placeholder_status(["W20-1", "G20-2"])
    assert mixed["device_ids"] == ["G20-2"] and mixed["requires_review"] and mixed["label"]


# ---- validators ----

def test_validator_passes_known_sourced_devices_and_records_the_trace(pack, cat):
    out = validate_devices([{"object_id": "O1", "device_id": "W20-1"}, {"object_id": "O2", "device_id": "DEV-CONE"}], "RURAL", pack, cat)
    assert out["ok"] and not out["forces_review"] and out["review_devices"] == []
    for c in out["checks"]:
        assert c["status"] == "PASS" and c["severity"] == "BLOCK"
        assert c["pack_hash"] == pack.hash and c["pack_version"] == pack.version and c["catalog_hash"] == cat.hash
        assert c["object_id"] in ("O1", "O2") and c["device_id"]


def test_validator_fails_a_device_not_in_the_catalog(pack, cat):
    out = validate_devices([{"object_id": "O1", "device_id": "W20-8"}], "RURAL", pack, cat)
    assert not out["ok"] and out["checks"][0]["id"] == "DEVICE_EXISTS" and out["checks"][0]["status"] == "FAIL"


def test_validator_fails_a_size_not_from_the_pack(pack, cat):
    good = size_for(pack, cat, "W20-1", "RURAL")
    ok = validate_devices([{"object_id": "O1", "device_id": "W20-1", "size": {"width_in": good["width_in"], "height_in": good["height_in"]}}], "RURAL", pack, cat)
    assert ok["ok"]
    bad = validate_devices([{"object_id": "O1", "device_id": "W20-1", "size": {"width_in": 30, "height_in": 30}}], "RURAL", pack, cat)
    assert not bad["ok"] and bad["checks"][-1]["id"] == "DEVICE_SIZE_FROM_PACK" and bad["checks"][-1]["size_record_id"] == good["record_id"]
    # the Freeway size on a RURAL road is a size from another column: fails
    fw = size_for(pack, cat, "W20-1", "EXPRESSWAY_FREEWAY")
    wrong = validate_devices([{"object_id": "O1", "device_id": "W20-1", "size": {"width_in": fw["width_in"], "height_in": fw["height_in"]}}], "RURAL", pack, cat)
    assert not wrong["ok"]


def test_validator_passes_a_sizeless_device_but_forces_review_and_names_it(pack, cat):
    out = validate_devices([{"object_id": "O1", "device_id": "R9-9"}, {"object_id": "O2", "device_id": "M4-9AL"},
                            {"object_id": "O3", "device_id": "W20-1"}], "EXPRESSWAY_FREEWAY", pack, cat)
    assert out["ok"] and out["forces_review"] and out["review_devices"] == ["M4-9AL", "R9-9"]
    flagged = [c for c in out["checks"] if c.get("forces_review")]
    assert {c["device_id"] for c in flagged} == {"M4-9AL", "R9-9"} and all(c["sme_question"] for c in flagged)
    # a size drawn where the pack has none was not read from the pack
    bad = validate_devices([{"object_id": "O1", "device_id": "R9-9", "size": {"width_in": 24, "height_in": 12}}], "EXPRESSWAY_FREEWAY", pack, cat)
    assert not bad["ok"]
