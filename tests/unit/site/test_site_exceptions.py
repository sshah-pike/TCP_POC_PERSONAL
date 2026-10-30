"""Site exceptions (S6 addendum 2026-10-31): empty file changes nothing; an entry applies only to its site and field; malformed fails closed."""
import hashlib
import json

import pytest

from tcp_planner.site_model import site_exceptions as X
from tcp_planner.site_model.facts import SiteFact

BASE = {"readme": {"purpose": "p"}, "schema_version": "1", "entries": []}
DROP = object()                                   # marks a key to leave out of an entry


def entry(**kw):
    e = {"entry_id": "E1", "site_id": "granite_p32", "field": "shoulder_present", "action": "SET_VALUE", "value": False,
         "reason": "OSM tags a shoulder that is a parking lane", "proposed_by_role": "SME", "entered_by_role": "ADMIN", "date": "2026-10-31"}
    e.update(kw)
    return {k: v for k, v in e.items() if v is not DROP}


def loaded(*entries):
    return X.parse(json.dumps({**BASE, "entries": list(entries)}).encode())


def facts():
    return [SiteFact(field="shoulder_present", registry_id="shoulder_present", source="AI", outcome="FOUND", value=True, confidence=0.9,
                     flags=("NEEDS_SECOND_SOURCE",)),
            SiteFact(field="parking_present", source="AI", outcome="FOUND", value=True, flags=("CONTEXT_ONLY",))]


# ---------------------------------------------------------------- the shipped file
def test_the_shipped_file_is_empty_valid_and_has_a_readme_first():
    raw = open(X.PATH, "rb").read()
    doc = json.loads(raw)
    assert list(doc)[0] == "readme" and doc["entries"] == [] and doc["schema_version"] == "1"
    for k in ("purpose", "schema", "rules"): assert k in doc["readme"]
    assert set(doc["readme"]["schema"]) >= {"entry_id", "scope", "field", "action", "value", "reason", "proposed_by_role", "entered_by_role", "date"}
    l = X.load()
    assert l.entries == () and l.sha256 == hashlib.sha256(raw).hexdigest()


def test_an_empty_file_changes_nothing():
    fs = facts()
    out, uses = X.apply(fs, X.load(), site_id="granite_p32", zone_id="z1", osm_way_id=5)
    assert out == fs and uses == []
    rec = X.trace_record(X.load(), uses)
    assert rec["entries"] == 0 and rec["uses"] == [] and len(rec["sha256"]) == 64


# ---------------------------------------------------------------- applying
def test_an_entry_applies_only_to_its_site_and_its_field():
    l = loaded(entry())
    out, uses = X.apply(facts(), l, site_id="granite_p32")
    assert out[0].value is False and out[0].outcome == "NOT_PRESENT" and out[0].source == "SITE_EXCEPTION"
    assert "NEEDS_SECOND_SOURCE" not in out[0].flags and "E1" in out[0].evidence and out[0].candidates[-1].value is True
    assert out[1] == facts()[1]                                                   # another field at the same site: untouched
    assert [u.entry_id for u in uses] == ["E1"] and uses[0].original_value is True and uses[0].original_outcome == "FOUND"
    other, none = X.apply(facts(), l, site_id="colorado_p13")                     # another site: untouched
    assert other == facts() and none == []
    nosite, none2 = X.apply(facts(), l)                                           # no site given: nothing matches
    assert nosite == facts() and none2 == []


def test_zone_and_osm_way_scopes():
    z = loaded(entry(site_id=DROP, zone_id="zone-7"))
    assert X.apply(facts(), z, zone_id="zone-7")[0][0].value is False and X.apply(facts(), z, zone_id="zone-8")[0] == facts()
    w = loaded(entry(site_id=DROP, osm_way_id=123))
    assert X.apply(facts(), w, osm_way_id=123)[0][0].value is False and X.apply(facts(), w, osm_way_id=124)[0] == facts()
    assert X.apply(facts(), w, site_id="123")[0] == facts()


def test_force_unknown():
    l = loaded(entry(action="FORCE_UNKNOWN", value=DROP))
    out, uses = X.apply(facts(), l, site_id="granite_p32")
    assert out[0].outcome == "UNKNOWN" and out[0].value is None and out[0].reason_code == "site_exception" and uses[0].action == "FORCE_UNKNOWN"


def test_the_trace_lists_every_use_and_the_file_hash():
    l = loaded(entry(), entry(entry_id="E2", field="parking_present", value=False))
    out, uses = X.apply(facts(), l, site_id="granite_p32")
    rec = X.trace_record(l, uses)
    assert rec["roles"] == "role selected, not verified" and rec["entries"] == 2 and [u["entry_id"] for u in rec["uses"]] == ["E1", "E2"] and rec["sha256"] == l.sha256
    assert json.dumps(rec)                                                         # JSON-serialisable for the trace


def test_two_entries_for_one_field_at_one_site_fail_closed():
    l = loaded(entry(), entry(entry_id="E2", value=True))
    with pytest.raises(X.SiteExceptionError): X.apply(facts(), l, site_id="granite_p32")


# ---------------------------------------------------------------- malformed fails closed
@pytest.mark.parametrize("bad", [
    entry(entry_id=DROP), entry(field=DROP), entry(action=DROP), entry(reason=""), entry(proposed_by_role=DROP), entry(entered_by_role=DROP), entry(date="31/10/2026"), entry(date=DROP),
    entry(proposed_by_role="OWNER"), entry(entered_by_role="sme"), entry(entered_by_role="SME"), entry(entered_by_role="APPROVER"),
    entry(proposed_by_role="APPROVER"),
    entry(action="DELETE"), entry(value=DROP), entry(value=None), entry(value=[1]),
    entry(action="FORCE_UNKNOWN", value=True), entry(site_id=DROP), entry(zone_id="z"), entry(site_id=""), entry(site_id=DROP, osm_way_id="12"),
    entry(site_id=DROP, osm_way_id=True), entry(extra="x"), entry(field="posted_speed_mph"), entry(field="road_type"),
    entry(field="traffic_volume"), entry(field="lane_closure"), "not an object"])
def test_a_malformed_entry_fails_closed(bad):
    with pytest.raises(X.SiteExceptionError) as e: loaded(bad)
    assert e.value.code == "SITE_EXCEPTIONS_MALFORMED"


def test_duplicate_entry_ids_are_refused():
    with pytest.raises(X.SiteExceptionError): loaded(entry(), entry())


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\xff\xfe", json.dumps({**BASE, "schema_version": "2"}).encode(),
                                 json.dumps({k: v for k, v in BASE.items() if k != "readme"}).encode(),
                                 json.dumps({**BASE, "entries": {}}).encode(), json.dumps({**BASE, "more": 1}).encode(),
                                 json.dumps({k: v for k, v in BASE.items() if k != "entries"}).encode()])
def test_a_malformed_file_fails_closed(raw):
    with pytest.raises(X.SiteExceptionError): X.parse(raw)


def test_a_missing_file_fails_closed(tmp_path):
    with pytest.raises(X.SiteExceptionError): X.load(str(tmp_path / "nope.json"))


def test_no_real_entry_ships():
    assert json.load(open(X.PATH, encoding="utf-8"))["entries"] == []


# ---------------------------------------------------------------- roles (owner addendum 2026-10-31)
def test_the_dropdown_roles_and_what_each_may_do():
    assert X.ROLES == ("SME", "APPROVER", "ADMIN")
    assert loaded(entry(proposed_by_role="SME", entered_by_role="ADMIN")).entries
    assert loaded(entry(proposed_by_role="ADMIN", entered_by_role="ADMIN")).entries          # the admin can do everything for now
    for bad in (entry(proposed_by_role="APPROVER"), entry(entered_by_role="APPROVER"), entry(entered_by_role="SME")):
        with pytest.raises(X.SiteExceptionError): loaded(bad)                                 # the approver is for rule pack approval only; the SME proposes, the admin enters


def test_every_use_names_both_roles_and_the_trace_says_they_are_not_verified():
    l = loaded(entry())
    _, uses = X.apply(facts(), l, site_id="granite_p32")
    assert (uses[0].proposed_by_role, uses[0].entered_by_role) == ("SME", "ADMIN")
    rec = X.trace_record(l, uses)
    assert rec["uses"][0]["proposed_by_role"] == "SME" and rec["roles"] == X.ROLE_NOTE == "role selected, not verified"
