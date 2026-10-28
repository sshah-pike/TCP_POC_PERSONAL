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
