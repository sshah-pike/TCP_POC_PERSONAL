import pytest
from tcp_planner.storage.interfaces import validate_key, InvalidKey, ArtifactRef, StorageError


@pytest.mark.parametrize("k", ["20261013-131822-3a950b/output/plan.json", "a", "x/y z/q.kml", "runs/r1/ui/request.json"])
def test_valid_keys(k):
    assert validate_key(k) == k


@pytest.mark.parametrize("k", ["", "/a", "a/", "a//b", "../a", "a/../b", "C:/x", "a\\b", "a/./b", "a/b.", " a", "a/\x00"])
def test_invalid_keys(k):
    with pytest.raises(InvalidKey): validate_key(k)


def test_ref_round_trip_and_malformed():
    r = ArtifactRef("a/b.json", "0" * 64, 3, "application/json")
    assert ArtifactRef.from_dict(r.to_dict()) == r
    with pytest.raises(StorageError): ArtifactRef.from_dict({"uri": "a/b"})
    with pytest.raises(StorageError): ArtifactRef.from_dict({"uri": "../b", "sha256": "x", "size": 1, "media_type": "t"})


# ------------------------------------------------------------------ uploaded KML names (S2 decision A)
from tcp_planner.storage.uploads import slug, upload_key, store_upload
from tcp_planner.storage.memory import InMemoryArtifactStore

RUN = "20261028-212645-f05da1"
AWKWARD = ["Granite (rev 2).kml", "Colorado Ave, Warwick RI.kml", "A&B.kml", "a'b.kml", "-x.kml", "_x.kml", "#12.kml",
           "[1].kml", "caf\u00e9.kml", "\u5de5\u4e8b.kml", "noext", "E Second St.KML", "", "...", ".kml", "a/b\\c.kml", "x.kml.kml"]


@pytest.mark.parametrize("name", AWKWARD)
def test_slug_always_gives_a_valid_key(name):
    s = slug(name)
    assert s.endswith(".kml") and s[0].isalnum() and validate_key(f"{RUN}/input/{s}")


def test_slug_values():
    assert slug("Granite (rev 2).kml") == "Granite__rev_2_.kml"
    assert slug("Colorado Ave, Warwick RI.kml") == "Colorado_Ave__Warwick_RI.kml"
    assert slug("A&B.kml") == "A_B.kml" and slug("a'b.kml") == "a_b.kml"
    assert slug("-x.kml") == "x.kml" and slug("caf\u00e9.kml") == "caf_.kml"
    assert slug("E Second St.KML") == "E_Second_St.kml" and slug("noext") == "noext.kml"
    assert slug("") == "input.kml" and slug("...") == "input.kml" and slug(".kml") == "input.kml"


def test_colliding_slugs_get_a_hash_suffix_and_nothing_is_overwritten():
    st = InMemoryArtifactStore()
    a = store_upload(st, RUN, "A&B.kml", b"<kml>1</kml>")
    b = store_upload(st, RUN, "A B.kml", b"<kml>2</kml>")      # cleans to the same key, different bytes
    assert a.uri == f"{RUN}/input/A_B.kml" and b.uri != a.uri and b.uri.startswith(f"{RUN}/input/A_B-")
    assert st.get(a) == b"<kml>1</kml>" and st.get(b) == b"<kml>2</kml>"
    c = store_upload(st, RUN, "A?B.kml", b"<kml>1</kml>")      # same bytes: idempotent, same key
    assert c == a and len(st.list(RUN)) == 2
    assert upload_key(RUN, "A B.kml", b"<kml>2</kml>", lambda k: a.sha256) == b.uri  # deterministic
