"""Provider failure diagnostics: same fail-closed decision, extra sanitized cause (no network).

The real runner -> tcp_planner.orchestration.pipeline.main -> UsgsNaipProvider path runs in-process with requests.get replaced by
a fake that raises the exceptions the requests library raises. Only the diagnostic may differ per case.
"""
import io, json, os, ssl, sys
import pytest
import requests
from requests import exceptions as rx

from tcp_planner.orchestration import pipeline as app
from tcp_planner.orchestration import run_worker as runner
from tcp_planner.storage import run_store as store
from tcp_planner.audit import provider_diagnostics as diagnostics

SECRET = "SECRET_TEST_VALUE"
DRAFT = {"plan.json", "tcp_sheet.png", "tcp_sheet.pdf", "debug_plan.png", "debug_plan.pdf", "plan.dxf", "plan.dwg"}
EXPECTED_CODES = ["MAP_CONTEXT_UNAVAILABLE", "MAP_REQUEST_FAILED"]  # existing pipeline behaviour


@pytest.fixture
def inproc(tmp_path, monkeypatch):
    """Run the UI runner in this process; restore every global it patches afterwards."""
    if os.environ.get("TCP_RUN_USGS_TESTS") != "1":  # these tests drive the USGS NAIP provider
        pytest.skip("USGS NAIP is not in use; set TCP_RUN_USGS_TESTS=1 to run these tests")
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    saved_env = dict(os.environ); saved_argv = list(sys.argv)
    saved = {k: getattr(app, k) for k in ("Telemetry", "run_pipeline", "load_rule_pack", "use_os_trust_store",
                                          "get_map_provider", "get_vision_provider")}
    saved_osm = app.osm_adapter.fetch_osm
    try:
        import anthropic; saved_anthropic = anthropic.Anthropic
    except ImportError:
        anthropic = None
    saved_ctx = ssl.SSLContext

    def run(fake_get, lat="41.69", lon="-71.55"):
        monkeypatch.setattr(requests, "get", fake_get)
        rid, rdir = store.create_run({"input_type": "coordinates", "lat": lat, "lon": lon,
                                      "advanced": {"map_provider": "usgs_naip", "no_dwt": True}}, set())
        code = runner.main([rdir])
        return code, store.build_state(rid), rdir

    yield run
    for k, v in saved.items(): setattr(app, k, v)
    app.osm_adapter.fetch_osm = saved_osm
    if anthropic is not None: anthropic.Anthropic = saved_anthropic
    if ssl.SSLContext is not saved_ctx:
        import truststore; truststore.extract_from_ssl()
    os.environ.clear(); os.environ.update(saved_env); sys.argv[:] = saved_argv


def raising(exc):
    def fake_get(url, **kw): raise exc
    return fake_get


class FakeResponse:
    def __init__(self, status, ctype, content=b""):
        self.status_code = status; self.headers = {"content-type": ctype}; self.content = content


def assert_fail_closed(code, st, rdir):
    assert code == 3 and st["decision"] == "ERROR"
    assert st["reason_codes"] == EXPECTED_CODES
    assert not st["draft_generated"] and not ({o["name"] for o in st["outputs"]} & DRAFT)
    stages = {s["key"]: s for s in st["stages"]}
    assert stages["imagery"]["status"] == "ERROR"
    assert all(stages[k]["status"] == "NOT_RUN" for k in ("osm", "vision", "fusion", "eligibility", "render"))
    with open(os.path.join(rdir, "output", "eligibility_result.json"), encoding="utf-8") as f:
        assert json.load(f)["reason_codes"] == EXPECTED_CODES
    [d] = stages["imagery"]["diagnostics"]
    assert d["provider"] == "usgs_naip" and d["pipeline_error_code"] == "MAP_REQUEST_FAILED"
    return d


def assert_no_secret(st, rdir):
    assert SECRET not in json.dumps(st)
    for root, _, files in os.walk(rdir):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                assert SECRET.encode() not in f.read(), name


def test_tls_certificate_failure(inproc):
    exc = rx.SSLError(
        f"HTTPSConnectionPool(host='example.com', port=443): Max retries exceeded with url: /image?api_key={SECRET}"
        "&bbox=1 (Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate "
        "verify failed: unable to get local issuer certificate (_ssl.c:1032)')))")
    code, st, rdir = inproc(raising(exc))
    d = assert_fail_closed(code, st, rdir)
    assert d["category"] == "TLS_CERTIFICATE_VERIFY_FAILED"
    assert d["exception_type"] == "requests.exceptions.SSLError"
    assert "certificate verify failed: unable to get local issuer certificate" in d["message"]
    assert "/image?<query removed>" in d["message"]
    assert_no_secret(st, rdir)


@pytest.mark.parametrize("exc, category", [
    (rx.ReadTimeout("HTTPSConnectionPool(host='imagery.nationalmap.gov', port=443): Read timed out. (read timeout=180)"),
     "READ_TIMEOUT"),
    (rx.ConnectTimeout("HTTPSConnectionPool(host='imagery.nationalmap.gov', port=443): Max retries exceeded "
                       "(Caused by ConnectTimeoutError(..., 'Connection to imagery.nationalmap.gov timed out.'))"),
     "CONNECT_TIMEOUT"),
])
def test_timeouts(inproc, exc, category):
    code, st, rdir = inproc(raising(exc))
    d = assert_fail_closed(code, st, rdir)
    assert d["category"] == category and "timed out" in d["message"].lower()


def test_http_error_status(inproc):
    code, st, rdir = inproc(lambda url, **kw: FakeResponse(503, "text/html"))
    d = assert_fail_closed(code, st, rdir)
    assert d["category"] == "HTTP_ERROR" and d["http_status"] == 503 and "HTTP 503" in d["message"]


def test_non_image_200_response(inproc):
    code, st, rdir = inproc(lambda url, **kw: FakeResponse(200, "application/json;charset=UTF-8"))
    d = assert_fail_closed(code, st, rdir)
    assert d["category"] == "INVALID_IMAGERY_RESPONSE" and "application/json" in d["message"]


@pytest.mark.parametrize("exc, category", [
    (rx.ConnectionError("HTTPSConnectionPool(host='imagery.nationalmap.gov', port=443): Max retries exceeded "
                        "(Caused by NameResolutionError(\"Failed to resolve 'imagery.nationalmap.gov' "
                        "([Errno 11001] getaddrinfo failed)\"))"), "DNS_FAILURE"),
    (rx.ConnectionError("HTTPSConnectionPool(host='imagery.nationalmap.gov', port=443): Max retries exceeded "
                        "(Caused by NewConnectionError('Failed to establish a new connection: [WinError 10061] "
                        "No connection could be made because the target machine actively refused it'))"),
     "CONNECTION_FAILED"),
])
def test_connection_errors(inproc, exc, category):
    code, st, rdir = inproc(raising(exc))
    assert assert_fail_closed(code, st, rdir)["category"] == category


def test_secret_in_full_url_is_never_exposed(inproc):
    exc = rx.ConnectionError(f"failed GET https://example.com/image?api_key={SECRET}&size=1280 "
                             f"Authorization: Bearer {SECRET}")
    code, st, rdir = inproc(raising(exc))
    d = assert_fail_closed(code, st, rdir)
    assert "https://example.com/image?<query removed>" in d["message"]
    assert_no_secret(st, rdir)


def test_osm_tls_failure_after_imagery_succeeds(inproc):
    """OSM is the host this network inspects; its failure is diagnosed on the OSM stage, decision unchanged."""
    from PIL import Image
    import numpy as np
    buf = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (1280, 1280, 3), dtype=np.uint8)).save(buf, "JPEG")

    def fake_get(url, **kw):
        if "nationalmap" in url: return FakeResponse(200, "image/jpeg", buf.getvalue())
        raise rx.SSLError("HTTPSConnectionPool(host='api.openstreetmap.org', port=443): Max retries exceeded with "
                          "url: /api/0.6/map?bbox=1,2,3,4 (Caused by SSLError(SSLCertVerificationError(1, "
                          "'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in "
                          "certificate chain (_ssl.c:1032)')))")

    code, st, rdir = inproc(fake_get)
    assert code == 3 and st["decision"] == "ERROR"
    assert st["reason_codes"] == ["OSM_CONTEXT_UNAVAILABLE", "OSM_REQUEST_FAILED"]
    stages = {s["key"]: s for s in st["stages"]}
    assert stages["imagery"]["status"] == "COMPLETED" and stages["imagery"]["diagnostics"] == []
    [d] = stages["osm"]["diagnostics"]
    assert d["category"] == "TLS_CERTIFICATE_VERIFY_FAILED" and d["provider"] == "osm_api"
    assert "bbox" not in d["message"]


def test_usgs_read_timeout_passed_to_requests(inproc):
    seen = {}

    def fake_get(url, **kw):
        seen.update(kw); raise rx.ReadTimeout("Read timed out.")

    inproc(fake_get)
    assert seen["timeout"] == (5, 180.0)


def test_runner_uses_cli_trust_store(inproc):
    pytest.importorskip("truststore")
    code, st, _ = inproc(raising(rx.ReadTimeout("Read timed out.")))
    assert st["tls"]["trust_store"] == "WINDOWS_SYSTEM_STORE (truststore)"
    assert st["tls"]["ssl_context"].startswith("truststore")


def test_sanitize_patterns(monkeypatch):
    monkeypatch.setenv("AZURE_MAPS_KEY", "azure-secret-value-123")
    raw = ("GET https://atlas.microsoft.com/map/static?subscription-key=azure-secret-value-123&zoom=17 "
           "url: /arcgis/export?bbox=1,2 token=abc123456 Bearer eyJhbGciOi.payload.sig sk-ant-api03-ABCDEFGHIJK")
    s = diagnostics.sanitize(raw)
    for leaked in ("azure-secret-value-123", "zoom=17", "bbox=1", "abc123456", "eyJhbGciOi", "sk-ant-api03"):
        assert leaked not in s, leaked
    assert "https://atlas.microsoft.com/map/static?<query removed>" in s
