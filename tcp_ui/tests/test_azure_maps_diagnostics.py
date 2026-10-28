"""Azure Maps failure diagnostics: same fail-closed decision, extra sanitized cause (no network, no real key).

The real runner -> tcp_planner.orchestration.pipeline.main -> AzureMapsProvider path runs in-process with requests.get replaced by a
fake. .env loading is disabled so no real credential enters the test; a fake key is set instead.
"""
import io, json, os, ssl, sys
import pytest
import requests
from requests import exceptions as rx

from tcp_planner.orchestration import pipeline as app
from tcp_ui import runner, store

FAKE_KEY = "AZURE-TEST-KEY-0123456789-SENTINEL"
SECRET = "SECRET_TEST_VALUE"
DRAFT = {"plan.json", "tcp_sheet.png", "tcp_sheet.pdf", "debug_plan.png", "debug_plan.pdf", "plan.dxf", "plan.dwg"}
EXPECTED = ["MAP_CONTEXT_UNAVAILABLE", "MAP_REQUEST_FAILED"]


@pytest.fixture
def inproc(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("AZURE_MAPS_KEY", FAKE_KEY)
    monkeypatch.delenv("AZURE_MAPS_SUBSCRIPTION_KEY", raising=False)
    monkeypatch.setattr(app, "load_env_file", lambda *a, **k: None)  # never read the real .env here
    saved_env = dict(os.environ); saved_argv = list(sys.argv)
    saved = {k: getattr(app, k) for k in ("Telemetry", "run_pipeline", "load_rule_pack", "use_os_trust_store",
                                          "get_map_provider", "get_vision_provider")}
    saved_osm = app.osm_adapter.fetch_osm
    import anthropic; saved_a = (anthropic.Anthropic, getattr(anthropic, "AnthropicFoundry", None))
    saved_ctx = ssl.SSLContext

    def run(fake_get):
        monkeypatch.setattr(requests, "get", fake_get)
        rid, rdir = store.create_run({"input_type": "coordinates", "lat": "41.415", "lon": "-71.742",
                                      "operator": {"road_type": "RURAL"},
                                      "advanced": {"map_provider": "azure_maps", "no_dwt": True}}, set())
        code = runner.main([rdir])
        return code, store.build_state(rid), rdir

    yield run
    for k, v in saved.items(): setattr(app, k, v)
    app.osm_adapter.fetch_osm = saved_osm
    anthropic.Anthropic = saved_a[0]
    if saved_a[1] is not None: anthropic.AnthropicFoundry = saved_a[1]
    if ssl.SSLContext is not saved_ctx:
        import truststore; truststore.extract_from_ssl()
    os.environ.clear(); os.environ.update(saved_env); sys.argv[:] = saved_argv


class FakeResponse:
    def __init__(self, status, ctype, content=b""):
        self.status_code = status; self.headers = {"content-type": ctype}; self.content = content


def raising(exc):
    def fake_get(url, **kw): raise exc
    return fake_get


def assert_fail_closed(code, st, rdir, expected=EXPECTED):
    assert code == 3 and st["decision"] == "ERROR" and st["reason_codes"] == expected
    assert not st["draft_generated"] and not ({o["name"] for o in st["outputs"]} & DRAFT)
    stages = {s["key"]: s for s in st["stages"]}
    assert stages["imagery"]["status"] == "ERROR"
    assert all(stages[k]["status"] == "NOT_RUN" for k in ("osm", "vision", "fusion", "eligibility", "render"))
    with open(os.path.join(rdir, "output", "eligibility_result.json"), encoding="utf-8") as f:
        assert json.load(f)["reason_codes"] == expected
    [d] = stages["imagery"]["diagnostics"]
    assert d["provider"] == "azure_maps"
    assert_no_secret(st, rdir)
    return d


def assert_no_secret(st, rdir):
    blob = json.dumps(st)
    assert FAKE_KEY not in blob and SECRET not in blob
    for root, _, files in os.walk(rdir):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                data = f.read()
            assert FAKE_KEY.encode() not in data and SECRET.encode() not in data, name


def test_tls_certificate_failure(inproc):
    exc = rx.SSLError(
        "HTTPSConnectionPool(host='atlas.microsoft.com', port=443): Max retries exceeded with url: "
        f"/map/static?api-version=2024-04-01&subscription-key={SECRET}&center=-71.7,41.4 (Caused by SSLError("
        "SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get "
        "local issuer certificate (_ssl.c:1032)')))")
    d = assert_fail_closed(*inproc(raising(exc)))
    assert d["category"] == "TLS_CERTIFICATE_VERIFY_FAILED" and d["exception_type"] == "requests.exceptions.SSLError"
    assert "certificate verify failed: unable to get local issuer certificate" in d["message"]
    assert "/map/static?<query removed>" in d["message"] and "center=" not in d["message"]


@pytest.mark.parametrize("exc, category", [
    (rx.ReadTimeout("HTTPSConnectionPool(host='atlas.microsoft.com', port=443): Read timed out. (read timeout=60)"),
     "READ_TIMEOUT"),
    (rx.ConnectTimeout("HTTPSConnectionPool(host='atlas.microsoft.com', port=443): Max retries exceeded "
                       "(Caused by ConnectTimeoutError(..., 'Connection to atlas.microsoft.com timed out.'))"),
     "CONNECT_TIMEOUT"),
])
def test_timeouts(inproc, exc, category):
    d = assert_fail_closed(*inproc(raising(exc)))
    assert d["category"] == category and "timed out" in d["message"].lower()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_http_error_status(inproc, status):
    d = assert_fail_closed(*inproc(lambda url, **kw: FakeResponse(status, "application/json")))
    assert d["category"] == "HTTP_ERROR" and d["http_status"] == status and f"HTTP {status}" in d["message"]


@pytest.mark.parametrize("exc, category", [
    (rx.ConnectionError("HTTPSConnectionPool(host='atlas.microsoft.com', port=443): Max retries exceeded (Caused by "
                        "NameResolutionError(\"Failed to resolve 'atlas.microsoft.com' ([Errno 11001] getaddrinfo "
                        "failed)\"))"), "DNS_FAILURE"),
    (rx.ConnectionError("HTTPSConnectionPool(host='atlas.microsoft.com', port=443): Max retries exceeded (Caused by "
                        "NewConnectionError('[WinError 10061] No connection could be made')"), "CONNECTION_FAILED"),
])
def test_connection_errors(inproc, exc, category):
    assert assert_fail_closed(*inproc(raising(exc)))["category"] == category


def test_secret_in_full_url_is_never_exposed(inproc):
    exc = rx.ConnectionError(f"failed GET https://atlas.microsoft.com/map/static?subscription-key={SECRET}&zoom=18 "
                             f"subscription-key: {FAKE_KEY}")
    d = assert_fail_closed(*inproc(raising(exc)))
    assert "https://atlas.microsoft.com/map/static?<query removed>" in d["message"]


def test_missing_key_fails_closed(inproc, monkeypatch):
    monkeypatch.delenv("AZURE_MAPS_KEY")
    called = []
    code, st, rdir = inproc(lambda url, **kw: called.append(url))
    d = assert_fail_closed(code, st, rdir, ["MAP_CONTEXT_UNAVAILABLE", "MAP_CREDENTIALS_MISSING"])
    assert d["category"] == "CREDENTIALS_MISSING" and called == []  # no request without a key


def test_successful_fetch_sends_key_only_as_header(inproc):
    """Imagery succeeds (simulated); the key goes in the header, never the URL. OSM then fails -> stops early."""
    from PIL import Image
    import numpy as np
    buf = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (1280, 1280, 3), dtype=np.uint8)).save(buf, "JPEG")
    seen = []

    def fake_get(url, **kw):
        seen.append((url, kw))
        if "atlas.microsoft.com" in url: return FakeResponse(200, "image/jpeg", buf.getvalue())
        raise rx.ReadTimeout("Read timed out.")

    code, st, rdir = inproc(fake_get)
    url, kw = next(s for s in seen if "atlas.microsoft.com" in s[0])
    assert kw["headers"]["subscription-key"] == FAKE_KEY
    assert FAKE_KEY not in json.dumps(kw["params"]) and FAKE_KEY not in url
    assert kw["params"]["tilesetId"] == "microsoft.imagery" and kw["params"]["width"] == 1280
    stages = {s["key"]: s for s in st["stages"]}
    assert stages["imagery"]["status"] == "COMPLETED" and stages["imagery"]["diagnostics"] == []
    span = stages["imagery"]["spans"][0]["attributes"]  # (console lines are not captured in-process)
    assert span["provider"] == "azure_maps" and span["width_px"] == 1280 and span["metres_per_pixel"] > 0
    assert code == 3 and st["reason_codes"] == ["OSM_CONTEXT_UNAVAILABLE", "OSM_REQUEST_FAILED"]
    assert stages["osm"]["diagnostics"][0]["category"] == "READ_TIMEOUT"
    assert not st["draft_generated"]
    assert_no_secret(st, rdir)
