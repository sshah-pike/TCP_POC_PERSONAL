"""Data source framework (S6 commit 6): allow list, fingerprinted client, fixture hook, SourceCall, fusion records and confidence
classes. No network: replay from fixtures, fakes for recording."""
import base64, json, os

import pytest

from tcp_planner.data_sources import base as B
from tcp_planner.site_model import fusion_v2 as F
from tcp_planner.site_model.start_fields import START_FIELDS
from tcp_planner.storage.memory import InMemoryArtifactStore
from tests.support.fixtures import MissingFixtureError, fingerprint
from tests.support.source_fixtures import SourceFixtures

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
URL = "https://overpass-api.de/api/interpreter"


class Transport:
    def __init__(self, status=200, content=b'{"elements": []}'): self.calls, self.status, self.content = [], status, content

    def __call__(self, method, url, params, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "params": params, "body": body, "headers": headers, "timeout": timeout})
        return self.status, self.content


def client(tmp_path=None, transport=None, hook=True, store=None):
    h = SourceFixtures(str(tmp_path / "site")) if hook and tmp_path is not None else None
    return B.SourceClient(hook=h, transport=transport, store=store, now=lambda: "2026-10-30T12:00:00+00:00")


# ---------------------------------------------------------------- the allow list
def test_session_1_enables_only_azure_maps_and_overpass():
    cfg = B.load_sources()["sources"]
    assert {k for k, v in cfg.items() if v["enabled"]} == {"azure_maps", "osm_overpass"}
    assert cfg["osm_overpass"]["hosts"] == ["overpass-api.de"] and cfg["azure_maps"]["hosts"] == ["atlas.microsoft.com"]


def test_session_2_sources_are_listed_but_disabled_with_no_host():
    cfg = B.load_sources()["sources"]
    later = {"massgis", "rigis", "hpms", "census_urban", "usgs_3dep", "gtfs_mbta", "gtfs_ripta", "fra_crossings"}
    assert later <= set(cfg) and all(cfg[k]["hosts"] == [] and cfg[k]["enabled"] is False and "PLANNED" in cfg[k]["status"] for k in later)


def test_every_source_has_a_license_note():
    assert all(v["license_note"] for v in B.load_sources()["sources"].values())


@pytest.mark.parametrize("url", ["https://example.com/api", "https://overpass-api.de.evil.example/api", "https://evil.example/overpass-api.de",
                                 "https://atlas.microsoft.com/map", "http://overpass-api.de/api/interpreter", "ftp://overpass-api.de/x"])
def test_a_host_outside_the_allow_list_is_refused_before_any_network_use(url):
    t = Transport(); c = B.SourceClient(transport=t)
    with pytest.raises(B.SourceError) as e: c.request("osm_overpass", url)
    assert e.value.code == "SOURCE_HOST_NOT_ALLOWED" and t.calls == []


def test_one_sources_host_is_not_another_sources_host():
    t = Transport(); c = B.SourceClient(transport=t)
    with pytest.raises(B.SourceError) as e: c.request("azure_maps", URL)
    assert e.value.code == "SOURCE_HOST_NOT_ALLOWED" and t.calls == []


@pytest.mark.parametrize("source", ["massgis", "rigis", "hpms", "census_urban", "usgs_3dep", "gtfs_mbta", "gtfs_ripta", "fra_crossings"])
def test_a_disabled_source_is_refused(source):
    t = Transport()
    with pytest.raises(B.SourceError) as e: B.SourceClient(transport=t).request(source, "https://example.gov/x")
    assert e.value.code == "SOURCE_DISABLED" and t.calls == []


def test_an_unknown_source_is_refused():
    with pytest.raises(B.SourceError) as e: B.SourceClient(transport=Transport()).request("some_paid_api", URL)
    assert e.value.code == "SOURCE_UNKNOWN"


def test_the_host_comparison_is_case_insensitive_but_exact():
    c = B.SourceClient(transport=Transport())
    assert c.check("osm_overpass", "https://OVERPASS-API.DE/api/interpreter")[1] == "overpass-api.de"


# ---------------------------------------------------------------- the request: User-Agent, bounds, fingerprint
def test_a_live_request_sends_a_descriptive_user_agent_and_the_source_timeout(tmp_path):
    t = Transport(); c = client(tmp_path, t)
    c.request("osm_overpass", URL, {"data": "[out:json];"})
    call = t.calls[0]
    assert call["headers"]["User-Agent"] == B.load_sources()["user_agent"] and "tcp-planner" in call["headers"]["User-Agent"]
    assert call["timeout"] == B.load_sources()["sources"]["osm_overpass"]["timeout_s"]


def test_the_user_agent_carries_no_email_address_no_company_name_and_no_contact():
    ua = B.load_sources()["user_agent"].lower()                 # owner decision 2026-10-31: descriptive, nothing identifying
    assert "@" not in ua and "contact" not in ua and "pike" not in ua and "hexaware" not in ua and "http" not in ua


def test_an_oversized_response_is_refused_and_not_recorded(tmp_path):
    t = Transport(content=b"x" * (B.load_sources()["sources"]["osm_overpass"]["max_bytes"] + 1)); c = client(tmp_path, t)
    with pytest.raises(B.SourceError) as e: c.request("osm_overpass", URL, {"data": "q"})
    assert e.value.code == "SOURCE_RESPONSE_TOO_LARGE" and c.calls == []
    assert not os.path.isdir(tmp_path / "site" / "source")


def test_an_error_answer_is_raised_with_status_and_body_and_never_recorded(tmp_path):
    t = Transport(status=429, content=b"Too many requests"); c = client(tmp_path, t)
    with pytest.raises(B.SourceError) as e: c.request("osm_overpass", URL, {"data": "q"})
    assert e.value.code == "SOURCE_HTTP_ERROR" and e.value.details["http_status"] == 429 and "Too many requests" in e.value.details["body"]
    assert not os.path.isdir(tmp_path / "site" / "source")


def test_the_fingerprint_is_the_same_for_the_same_request_and_differs_otherwise():
    r1 = B.request_record("osm_overpass", "get", URL, {"b": 2, "a": 1}); r2 = B.request_record("osm_overpass", "GET", URL, {"a": 1, "b": 2})
    assert B.request_fingerprint(r1) == B.request_fingerprint(r2) == fingerprint(r1)           # same key as the fixture store's
    assert B.request_fingerprint(B.request_record("osm_overpass", "GET", URL, {"a": 1})) != B.request_fingerprint(r1)
    assert B.request_fingerprint(B.request_record("azure_maps", "GET", URL, {"a": 1, "b": 2})) != B.request_fingerprint(r1)


# ---------------------------------------------------------------- the fixture hook: record once, replay with no transport
def test_recording_then_replay_makes_no_second_call(tmp_path):
    t = Transport(content=b'{"elements": [1]}')
    rec = client(tmp_path, t).request("osm_overpass", URL, {"data": "q1"}, attribute_names=["highway", "lanes"])
    assert len(t.calls) == 1 and rec.call.replayed is False and rec.content == b'{"elements": [1]}'
    replay = client(tmp_path, transport=None).request("osm_overpass", URL, {"data": "q1"}, attribute_names=["highway", "lanes"])
    assert len(t.calls) == 1 and replay.call.replayed is True and replay.content == rec.content
    assert replay.call.request_fingerprint == rec.call.request_fingerprint and replay.call.retrieved_at == rec.call.retrieved_at   # deterministic
    assert json.loads(replay.content) == {"elements": [1]}


def test_replay_with_a_missing_fixture_is_an_error_not_a_live_call(tmp_path):
    t = Transport()
    c = B.SourceClient(hook=SourceFixtures(str(tmp_path / "site")), transport=None)
    with pytest.raises(MissingFixtureError): c.request("osm_overpass", URL, {"data": "never recorded"})
    assert t.calls == []


def test_no_hook_and_no_transport_is_an_error():
    with pytest.raises(B.SourceError) as e: B.SourceClient().request("osm_overpass", URL, {"data": "q"})
    assert e.value.code == "SOURCE_NO_TRANSPORT"


def test_the_replayed_request_goes_through_the_allow_list_too(tmp_path):
    c = client(tmp_path, Transport()); c.request("osm_overpass", URL, {"data": "q"})
    with pytest.raises(B.SourceError): client(tmp_path, None).request("osm_overpass", "https://evil.example/api/interpreter", {"data": "q"})


def test_fixtures_are_write_once(tmp_path):
    hook = SourceFixtures(str(tmp_path / "site")); rec = B.request_record("osm_overpass", "GET", URL, {"data": "q"})
    hook.save(rec, {"status": 200, "body_b64": base64.b64encode(b"a").decode(), "retrieved_at": "t"})
    with pytest.raises(FileExistsError): hook.save(rec, {"status": 200, "body_b64": base64.b64encode(b"b").decode(), "retrieved_at": "t"})


# ---------------------------------------------------------------- SourceCall
def test_source_call_records_who_what_when_and_the_licence(tmp_path):
    store = InMemoryArtifactStore()
    r = client(tmp_path, Transport(), store=store).request("osm_overpass", URL, {"data": "q"}, attribute_names=("highway", "lanes", "oneway"))
    c = r.call
    assert (c.source_id, c.host, c.schema_version, c.replayed) == ("osm_overpass", "overpass-api.de", "1", False)
    assert c.attribute_names == ("highway", "lanes", "oneway") and "ODbL" in c.license_note and c.retrieved_at == "2026-10-30T12:00:00+00:00"
    assert set(c.artifact_ref) == {"uri", "sha256", "size", "media_type"} and store.get(c.artifact_ref["uri"]) == r.content
    assert "\\" not in c.artifact_ref["uri"]
    assert json.loads(c.model_dump_json())["request_fingerprint"] == c.request_fingerprint


def test_the_raw_response_is_stored_write_once_and_found_again(tmp_path):
    store = InMemoryArtifactStore(); t = Transport()
    c = client(tmp_path, t, store=store)
    a = c.request("osm_overpass", URL, {"data": "q"}); b = client(tmp_path, None, store=store).request("osm_overpass", URL, {"data": "q"})
    assert a.call.artifact_ref == b.call.artifact_ref


def test_no_module_of_the_framework_turns_certificate_checks_off():
    import re
    bad = re.compile(r"verify\s*=\s*False|CERT_NONE|_create_unverified_context")
    for rel in ("src/tcp_planner/data_sources/base.py", "src/tcp_planner/site_model/fusion_v2.py"):
        assert not bad.search(open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8").read())


# ---------------------------------------------------------------- confidence classes (Q14 A)
def test_only_a_human_origin_is_high():
    for o in ("SME", "UI", "SME_OVERRIDE", "SME_FORM"): assert F.confidence_class(o) == F.HIGH
    for o in ("osm_overpass", "massgis", "hpms"):
        assert F.confidence_class(o, True) == F.MEDIUM and F.confidence_class(o, False) == F.LOW and F.confidence_class(o, None) == F.LOW
        assert F.confidence_class(o, True) != F.HIGH


def test_classes_are_ordered_and_numbers_are_not_used_for_fused_values():
    assert F.CLASSES == ("LOW", "MEDIUM", "HIGH")
    rec = F.compare("lanes_per_direction", 2, [("osm_overpass", 2)])
    assert all(c.confidence_class in (None, "LOW", "MEDIUM", "HIGH") for c in rec.candidates)


# ---------------------------------------------------------------- the comparison record
def test_agreement_gives_a_medium_data_candidate():
    rec = F.compare("divided_highway", False, [("osm_overpass", False)])
    assert rec.agreement == F.AGREE and [c.confidence_class for c in rec.candidates] == [None, "MEDIUM"] and rec.candidates[0].source == "AI"


def test_disagreement_is_recorded_and_the_data_candidate_is_low():
    rec = F.compare("lanes_per_direction", 2, [("osm_overpass", 1)])
    assert rec.agreement == F.DISAGREE and rec.candidates[1].confidence_class == "LOW" and "osm_overpass" in rec.note
    assert [c.value for c in rec.candidates] == [2, 1]                    # both values are kept


def test_one_source_only_is_single_source():
    rec = F.compare("oneway", False, [])
    assert rec.agreement == F.SINGLE_SOURCE and len(rec.candidates) == 1


def test_an_undecidable_source_neither_agrees_nor_disagrees():
    rec = F.compare("lanes_per_direction", 1, [("osm_overpass", None)])
    assert rec.agreement == F.UNDECIDABLE and rec.candidates[1].confidence_class == "LOW"
    assert F.compare("lanes_per_direction", None, [("osm_overpass", 1)]).agreement == F.UNDECIDABLE      # the imagery reading is unknown


def test_one_source_disagreeing_among_several_is_a_disagreement():
    assert F.compare("lanes_per_direction", 2, [("osm_overpass", 2), ("massgis", 3)]).agreement == F.DISAGREE
    assert F.compare("lanes_per_direction", 2, [("osm_overpass", 2), ("massgis", None)]).agreement == F.AGREE


def test_a_custom_equality_is_honoured():
    assert F.compare("lanes_per_direction", 2, [("osm_overpass", 4)], same=lambda ai, s: ai * 2 == s).agreement == F.AGREE


@pytest.mark.parametrize("field", START_FIELDS)
def test_no_source_may_supply_a_mandatory_start_field(field):
    with pytest.raises(ValueError): F.compare(field, "x", [("osm_overpass", "y")])


def test_two_ai_readings_are_not_two_sources():
    """The record has exactly one AI candidate whatever the number of AI reads: only a data source can make a second source."""
    rec = F.compare("lanes_per_direction", 2, [])
    assert sum(1 for c in rec.candidates if c.source == "AI") == 1 and rec.agreement == F.SINGLE_SOURCE
