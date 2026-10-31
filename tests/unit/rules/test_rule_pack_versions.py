"""Sealed rule pack versions: rule_pack/versions/<version>/ plus the append-only INDEX.json (pack-store)."""
import json, os, shutil, stat
import pytest
from tcp_planner.config.settings import RULE_PACK_DIR
from tcp_planner.contracts import RulePackError
from tcp_planner.rules.rule_pack_store import JsonRulePackStore, MANIFEST
from scripts import seal_rule_pack_version as seal_version

VERSIONS = os.path.join(RULE_PACK_DIR, "versions")
# Pinned here so a rewritten INDEX entry fails (an entry is never edited; a new version is appended).
PINNED = {"1.0.0": "98c18fb207284ae884a28d20e2a5eba56facd74dfbc2aa7aa06797afe9e53d43",
          "1.1.0": "80c25240ab584974f40f4f17205a8490127549837a30f7b69e9d11dd95a18b0a"}


def _make_writable(path):
    os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)


def _rmtree(path):
    """rmtree that clears the read-only bit and retries (OneDrive and copy2 leave read-only files on Windows)."""
    def onexc(func, p, exc):
        if not isinstance(exc, PermissionError): raise exc
        _make_writable(p); func(p)
    shutil.rmtree(path, onexc=onexc)


def _copy_pack(dst):
    """Copy rule_pack/ without carrying file attributes, so a read-only source does not give a read-only copy."""
    shutil.copytree(RULE_PACK_DIR, dst, copy_function=shutil.copyfile)


def _set_read_only(root):
    for d, dirs, files in os.walk(root):
        for n in files: os.chmod(os.path.join(d, n), stat.S_IREAD)


def _index():
    with open(os.path.join(VERSIONS, "INDEX.json"), encoding="utf-8") as f: return json.load(f)["versions"]


def test_list_versions_is_every_sealed_version_in_order():
    assert JsonRulePackStore().list_versions() == [e["version"] for e in _index()] == ["1.0.0", "1.1.0"]


@pytest.mark.parametrize("entry", _index(), ids=lambda e: e["version"])
def test_frozen_directory_recomputes_to_the_index_hash(entry):
    frozen = JsonRulePackStore(os.path.join(VERSIONS, entry["version"]))
    assert frozen.content_hash() == entry["content_sha256"] == JsonRulePackStore().content_hash(entry["version"])
    assert frozen.load().hash == entry["content_sha256"]


def test_frozen_directory_holds_exactly_the_manifest_and_its_parts():
    for e in _index():
        folder = os.path.join(VERSIONS, e["version"])
        m = JsonRulePackStore(folder)._manifest_doc()
        on_disk = {os.path.relpath(os.path.join(d, n), folder).replace(os.sep, "/") for d, _, ns in os.walk(folder) for n in ns}
        assert on_disk == {MANIFEST} | {p["path"] for p in m["parts"]}


def test_latest_index_entry_is_the_current_pack():
    """A change to the current pack without a new sealed version fails here (run scripts/seal_rule_pack_version.py)."""
    store = JsonRulePackStore()
    assert _index()[-1]["content_sha256"] == store.content_hash() == store.load().hash
    assert _index()[-1]["version"] == store.load().version


def test_index_entries_are_never_rewritten():
    idx = {e["version"]: e for e in _index()}
    for v, h in PINNED.items(): assert idx[v]["content_sha256"] == h
    assert list(idx)[:2] == list(PINNED)
    assert len({e["version"] for e in _index()}) == len(_index())


def test_load_latest_equals_current_and_old_versions_load_side_by_side():
    store = JsonRulePackStore()
    old, new = store.load("1.0.0"), store.load("1.1.0")
    assert store.load().hash == new.hash and store.load(None).version == new.version == "1.1.0"
    assert (old.version, old.hash) == ("1.0.0", PINNED["1.0.0"]) and (new.hash == PINNED["1.1.0"])
    assert old.hash != new.hash and set(new.by_id) != set(old.by_id)
    assert store.content_hash("1.0.0") == PINNED["1.0.0"] and store.content_hash("1.1.0") == PINNED["1.1.0"]


def test_unknown_version_raises_version_missing():
    for call in (lambda s: s.load("9.9.9"), lambda s: s.content_hash("9.9.9")):
        with pytest.raises(RulePackError) as e: call(JsonRulePackStore())
        assert e.value.code == "RULE_PACK_VERSION_MISSING"


def test_tampered_frozen_copy_is_refused(tmp_path):
    root = tmp_path / "rule_pack"; _copy_pack(root)
    p = root / "versions" / "1.0.0" / "base" / "rules.json"
    doc = json.loads(p.read_text(encoding="utf-8")); doc["tables"]["rule"][0]["text"] += " x"
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RulePackError) as e: JsonRulePackStore(str(root)).load("1.0.0")
    assert e.value.code == "RULE_PACK_HASH_MISMATCH"


def test_seal_script_refuses_to_overwrite_and_appends_a_new_version(tmp_path):
    root = str(tmp_path / "rule_pack"); _copy_pack(root)
    before = open(os.path.join(root, "versions", "INDEX.json"), "rb").read()
    assert seal_version.main(["--source-commit", "abc"], root=root) == 1          # 1.1.0 is already sealed
    assert open(os.path.join(root, "versions", "INDEX.json"), "rb").read() == before
    _rmtree(os.path.join(root, "versions", "1.1.0"))
    idx = json.loads(before); idx["versions"].pop()
    json.dump(idx, open(os.path.join(root, "versions", "INDEX.json"), "w"))
    assert seal_version.main(["--source-commit", "abc", "--expect-hash", "0" * 64], root=root) == 1   # wrong expected hash
    assert not os.path.exists(os.path.join(root, "versions", "1.1.0"))
    assert seal_version.main(["--source-commit", "abc"], root=root) == 0
    assert JsonRulePackStore(root).list_versions() == ["1.0.0", "1.1.0"]
    assert JsonRulePackStore(root).content_hash("1.1.0") == PINNED["1.1.0"]
    assert seal_version.main(["--source-commit", "abc"], root=root) == 1          # second run refuses


def test_unsealed_current_pack_is_listed_last(tmp_path):
    root = str(tmp_path / "rule_pack"); _copy_pack(root)
    idx_path = os.path.join(root, "versions", "INDEX.json")
    idx = json.load(open(idx_path)); idx["versions"].pop(); json.dump(idx, open(idx_path, "w"))
    assert JsonRulePackStore(root).list_versions() == ["1.0.0", "1.1.0"]


def test_read_only_tree_copies_and_removes_and_the_script_still_works(tmp_path):
    src = str(tmp_path / "src"); _copy_pack(src); _set_read_only(src)
    try:
        root = str(tmp_path / "rule_pack")
        shutil.copytree(src, root, copy_function=shutil.copyfile)
        assert all(os.access(os.path.join(d, n), os.W_OK) for d, _, ns in os.walk(root) for n in ns)   # copy is not read-only
        assert JsonRulePackStore(root).content_hash("1.1.0") == PINNED["1.1.0"]
        _set_read_only(root)                                                                          # a read-only tree is removable
        _rmtree(os.path.join(root, "versions", "1.1.0"))
        assert not os.path.exists(os.path.join(root, "versions", "1.1.0"))
    finally:
        _rmtree(src)
