"""Device catalog v0.2 (S5): integrity, hash, resolution, asset swap, isolation. Offline."""
import ast, copy, glob, json, os, re, shutil

import pytest

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.rules import device_catalog as dc
from tcp_planner.rules.device_catalog import DeviceCatalogError, compute_catalog_hash, load_catalog
from tcp_planner.rules.rule_pack_store import JsonRulePackStore

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(ROOT, "src", "tcp_planner")


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


def _doc():
    with open(dc.DEVICE_CATALOG_PATH, encoding="utf-8") as f: return json.load(f)


def test_counts_and_unique_ids(cat):
    ids = [e.device_id for e in cat.entries]
    assert len(ids) == 51 and len(set(ids)) == 51
    assert cat.version == "0.2" and cat.catalog.schema_version == "1"


def test_every_asset_exists_matches_and_parses(cat):
    import xml.etree.ElementTree as ET
    assert cat.verify_assets() == []
    for e in cat.entries:
        assert e.asset.media_type == "image/svg+xml"
        ET.parse(cat.asset_path(e.device_id))


def test_every_asset_file_is_in_the_catalog(cat):
    on_disk = {f"symbols/svg/{n}" for n in os.listdir(os.path.join(dc.ASSETS_DIR, "symbols", "svg"))}
    assert on_disk == {e.asset.uri for e in cat.entries}


def test_size_source_rules(cat):
    by = {e.device_id: e for e in cat.entries}
    srr = {i for i, e in by.items() if e.size_source.value == "SOURCE_REVIEW_REQUIRED"}
    assert srr == {"CLIENT-POLICE-OFFICER-AHEAD", "M4-9AL", "R9-3BR", "RI-27.1.1"}
    assert all(by[i].size_text == "" for i in srr)
    assert {i for i, e in by.items() if e.size_source.value == "TEXT_ONLY"} == {i for i in by if i.startswith("DEV-")}
    assert {i for i, e in by.items() if e.size_source.value == "PACK"} == {
        "W20-1", "W20-4", "W20-5R", "W20-5L", "W20-7", "W21-5", "W5-1", "W4-2R", "W4-2L", "W3-4", "W16-2P", "G20-2"}


def test_no_regulatory_number_or_used_by_in_catalog():
    for e in _doc()["entries"]:
        assert not ({"size_in", "used_by_tas", "version", "pack_device_id"} & set(e))


def test_pack_devices_and_ta_uses_resolve(cat, pack):
    for d in pack.records("device"): assert cat.has(d.catalog_id), d.id
    by_pack = {d.id: d for d in pack.records("device")}
    for u in pack.records("ta_device_use"): assert cat.has(by_pack[u.device_id].catalog_id), u.id


def test_golden_codes_resolve_except_out_of_scope_police_sign(cat):
    codes = set()
    for f in glob.glob(os.path.join(ROOT, "tests", "golden", "golden_*.json")):
        codes |= set(re.findall(r'"(?:code|sign_code|device_code|mutcd_code|device_id)": "([^"]+)"', open(f, encoding="utf-8").read()))
    unresolved = set()
    for c in codes:
        try: cat.resolve(c)
        except DeviceCatalogError: unresolved.add(c)
    assert unresolved == {"W20-8"}          # Colorado police sign: out of scope, no alias


def test_alias_is_comparison_only_proposed(cat):
    r = cat.resolve("M4-A8")
    assert (r.entry.device_id, r.via, r.alias_status.value) == ("M4-8a", "ALIAS", "PROPOSED")
    assert cat.resolve("W20-1").via == "DEVICE_ID"
    assert [e.device_id for e in cat.entries if e.printed_as] == ["M4-8a"]
    with pytest.raises(DeviceCatalogError) as ex: cat.resolve("NOPE-1")
    assert ex.value.code == "DEVICE_UNKNOWN"
    with pytest.raises(DeviceCatalogError): cat.get("W20-8")


def test_hash_is_stable_over_key_order_and_changes_with_content():
    doc = _doc()
    assert doc["catalog_hash"] == compute_catalog_hash(doc)
    shuffled = json.loads(json.dumps(doc, sort_keys=True))
    assert compute_catalog_hash(shuffled) == doc["catalog_hash"]
    changed = copy.deepcopy(doc); changed["entries"][0]["name"] += "x"
    assert compute_catalog_hash(changed) != doc["catalog_hash"]
    changed = copy.deepcopy(doc); changed["entries"][0]["asset"]["sha256"] = "f" * 64
    assert compute_catalog_hash(changed) != doc["catalog_hash"]


def _temp_copy(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    shutil.copytree(os.path.join(dc.ASSETS_DIR, "symbols"), assets / "symbols")
    monkeypatch.setattr(dc, "ASSETS_DIR", str(assets))
    monkeypatch.setattr(dc, "DEVICE_CATALOG_PATH", str(assets / "symbols" / "device_catalog.json"))
    return assets


def test_asset_swap_changes_only_that_entry_and_the_hash(tmp_path, monkeypatch):
    before = _doc()
    assets = _temp_copy(tmp_path, monkeypatch)
    with open(assets / "symbols" / "svg" / "W20-1.svg", "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><title>client</title></svg>')
    with pytest.raises(DeviceCatalogError) as ex: load_catalog()          # a changed asset is caught until sealed
    assert ex.value.code == "ASSET_INVALID"
    new_hash = dc.seal()
    after = json.load(open(assets / "symbols" / "device_catalog.json", encoding="utf-8"))
    assert new_hash != before["catalog_hash"]
    diff = [b["device_id"] for b, a in zip(before["entries"], after["entries"]) if b != a]
    assert diff == ["W20-1"]
    a0, b0 = after["entries"][0]["asset"], before["entries"][0]["asset"]
    assert {k for k in a0 if a0[k] != b0[k]} == {"sha256", "size"}
    load_catalog()


def test_unsealed_edit_is_refused(tmp_path, monkeypatch):
    assets = _temp_copy(tmp_path, monkeypatch)
    p = assets / "symbols" / "device_catalog.json"
    doc = json.load(open(p, encoding="utf-8")); doc["entries"][3]["name"] = "changed"
    json.dump(doc, open(p, "w", encoding="utf-8"))
    with pytest.raises(DeviceCatalogError) as ex: load_catalog()
    assert ex.value.code == "CATALOG_HASH_MISMATCH"


def test_wrong_schema_version_and_bad_uri_are_refused(tmp_path, monkeypatch):
    assets = _temp_copy(tmp_path, monkeypatch)
    p = assets / "symbols" / "device_catalog.json"
    doc = json.load(open(p, encoding="utf-8")); doc["schema_version"] = "2"
    json.dump(doc, open(p, "w", encoding="utf-8"))
    with pytest.raises(DeviceCatalogError) as ex: load_catalog()
    assert ex.value.code == "CATALOG_SCHEMA_VERSION"
    for bad in ("../x.svg", "C:/x.svg", "symbols" + chr(92) + "svg" + chr(92) + "a.svg", "/abs/a.svg"):
        with pytest.raises(DeviceCatalogError): dc.asset_file_path(bad)


def test_no_raw_path_in_catalog():
    text = open(dc.DEVICE_CATALOG_PATH, encoding="utf-8").read()
    assert not re.search(r"[A-Za-z]:[\/]|\\|file://|OneDrive", text)


def test_only_the_loader_reads_the_catalog_or_symbol_folder():
    allowed = {"rules/device_catalog.py", "config/settings.py"}
    pat = re.compile(r"device_catalog\.json|SYMBOLS_DIR|DEVICE_CATALOG_PATH|assets[/\\]symbols|^symbols$")
    offenders = []
    for d, dirs, files in os.walk(SRC):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for n in files:
            rel = os.path.relpath(os.path.join(d, n), SRC).replace(os.sep, "/")
            if not n.endswith(".py") or rel in allowed: continue
            tree = ast.parse(open(os.path.join(d, n), encoding="utf-8").read())      # code only: comments may mention it
            names = [x.value for x in ast.walk(tree) if isinstance(x, ast.Constant) and isinstance(x.value, str)]
            names += [x.id for x in ast.walk(tree) if isinstance(x, ast.Name)] + [x.attr for x in ast.walk(tree) if isinstance(x, ast.Attribute)]
            names += [a.name for x in ast.walk(tree) if isinstance(x, ast.ImportFrom) for a in x.names]
            if any(pat.search(s) for s in names): offenders.append(rel)
    assert not offenders, offenders
