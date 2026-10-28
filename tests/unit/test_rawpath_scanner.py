from tests.support.rawpath_scan import find_raw_paths


def test_flags_raw_paths():
    doc = {"a": r"C:\Users\x\f.kml", "b": "/home/u/f.kml", "c": "../x", "d": ["\\\\srv\\share\\f"], "e": {"C:/k": 1}}
    assert len(find_raw_paths(doc)) == 5


def test_allows_store_keys_and_plain_text():
    doc = {"uri": "20261013-131822-3a950b/output/plan.json", "n": "a/b", "t": "50 ft / 100 ft", "u": "https://x/y/z"}
    assert find_raw_paths(doc) == []
