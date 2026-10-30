"""Fixture harness (S0): fingerprints, write-once store, missing fixture is an error, network is blocked."""
import socket

import pytest

from tests.support.fixtures import FixtureStore, MissingFixtureError, fingerprint
from tests.support.providers import OsmFixtures, MapFixtures, osm_request


def test_fingerprint_is_stable_and_order_independent():
    a = {"kind": "osm", "lat": 1.0, "lon": 2.0}
    assert fingerprint(a) == fingerprint({"lon": 2.0, "lat": 1.0, "kind": "osm"})
    assert fingerprint(a) != fingerprint({**a, "lat": 1.1})


def test_roundtrip_and_write_once(tmp_path):
    s = FixtureStore(str(tmp_path / "site")); req = osm_request("osm_api", 41.0, -71.0, 262.4)
    s.save("osm", req, {"elements": [{"id": 1}]})
    doc, fp = s.load("osm", req)
    assert doc["schema_version"] == 1 and doc["elements"] == [{"id": 1}] and fp == fingerprint(req)
    s.save("osm", req, {"elements": [{"id": 1}]})            # identical content: fine
    with pytest.raises(FileExistsError):
        s.save("osm", req, {"elements": [{"id": 2}]})         # different content: write-once


def test_missing_fixture_raises_clear_error_and_never_calls_live(tmp_path):
    osm = OsmFixtures(FixtureStore(str(tmp_path / "empty")))   # replay mode: no live source
    with pytest.raises(MissingFixtureError) as e:
        osm(41.0, -71.0, 262.4)
    msg = str(e.value)
    assert "no recorded osm fixture" in msg and "Replay never makes a live call" in msg and "262.4" in msg
    assert osm.calls and osm.calls[0][0] == "osm"


def test_map_replay_missing_is_error(tmp_path):
    m = MapFixtures(FixtureStore(str(tmp_path / "empty")), identity=object())
    with pytest.raises(MissingFixtureError):
        m.fetch_view(41.0, -71.0, 19, 1024)


def test_network_is_blocked_in_tests():
    from tests.support.netblock import NetworkBlockedError
    with pytest.raises(NetworkBlockedError):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(NetworkBlockedError):
        socket.socket().connect(("203.0.113.10", 80))


def test_loopback_stays_open():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    try:
        c = socket.create_connection(srv.getsockname(), timeout=2); c.close()
    finally:
        srv.close()


def test_record_then_replay_with_fake_live_sources(tmp_path):
    from PIL import Image
    store = FixtureStore(str(tmp_path / "site"))
    osm_live = OsmFixtures(store, live=lambda lat, lon, r: [{"id": 7}])
    assert osm_live(41.0, -71.0, 100) == [{"id": 7}]

    class FakeMap:
        name, SCALE_MODEL, API_VERSION = "azure_maps", "m", "v"
        def fetch_view(self, lat, lon, zoom, size):
            return Image.new("RGB", (size, size), (9, 8, 7)), {"zoom": zoom}
    live = MapFixtures(store, FakeMap(), live=FakeMap())
    live.fetch_view(41.0, -71.0, 19, 16)
    replay_osm, replay_map = OsmFixtures(store), MapFixtures(store, FakeMap())
    assert replay_osm(41.0, -71.0, 100) == [{"id": 7}]
    img, meta = replay_map.fetch_view(41.0, -71.0, 19, 16)
    assert img.getpixel((0, 0)) == (9, 8, 7) and meta == {"zoom": 19}
    assert replay_osm.calls == osm_live.calls


def test_live_recorder_refuses_without_tcp_live(monkeypatch, tmp_path):
    from tests.support import record
    monkeypatch.delenv("TCP_LIVE", raising=False)
    with pytest.raises(SystemExit):
        record.live(str(tmp_path / "x.kml"), "x", "RURAL", out_root=str(tmp_path))
