"""The UI layer must report exactly what the existing pipeline decided (offline, no network, no API keys).

Run from the project root:  python -m pytest tests/integration/web_api -q
"""
import base64, json, os, threading, time, urllib.error, urllib.request
import pytest

from tcp_planner.orchestration import offline_scenarios as offline
from tcp_planner.orchestration.pipeline import run_pipeline, DWT_CONFIG_PATH, EXIT
from tcp_planner.web_api import server
from tcp_planner.storage import run_store as store, run_records as records

DRAFT_FILES = {"plan.json", "aerial_image.jpg", "debug_plan.png", "debug_plan.pdf", "tcp_sheet.png", "tcp_sheet.pdf",
               "plan.dxf", "plan.dwg"}
SECRET = "sk-test-SENTINEL-must-never-reach-the-browser"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def run(payload, timeout=180):
        code, body = call("POST", "/api/runs", payload)
        assert code == 201, body
        rid = json.loads(body)["run_id"]; t0 = time.time()
        while True:
            code, body = call("GET", f"/api/runs/{rid}")
            st = json.loads(body)
            if st["state"] != "RUNNING": return st
            assert time.time() - t0 < timeout, "run did not finish"
            time.sleep(0.3)

    yield call, run
    srv.shutdown(); srv.server_close()


def direct(name, out):
    """The same offline run the CLI performs, called directly (reference result)."""
    sc = offline.build(name)
    return run_pipeline(out_dir=str(out), operator=dict(sc["operator"]), map_provider=sc["map_provider"],
                        vision_provider=sc["vision_provider"], osm_source=lambda lat, lon, r: sc["osm_elements"],
                        lat=sc["lat"], lon=sc["lon"], dwt_config=DWT_CONFIG_PATH)


@pytest.mark.parametrize("name", ["supported", "four_lane", "one_way", "intersection", "ai_unavailable",
                                  "missing_road_type", "lane_conflict", "driveway_at_sign"])
def test_ui_reports_existing_decision(api, tmp_path, name):
    _, run = api
    st = run({"input_type": "offline", "offline_scenario": name})
    ref = direct(name, tmp_path / "ref")

    shown = "ERROR" if ref["decision"] == "REVIEW_REQUIRED" and store._is_error(ref["reason_codes"]) else ref["decision"]
    assert st["decision"] == shown  # service/API failures are shown as ERROR, not REVIEW_REQUIRED
    assert st["reason_codes"] == ref["reason_codes"]
    assert st["exit_code"] == EXIT[ref["decision"]]
    outputs = {o["name"] for o in st["outputs"]}
    assert outputs == set(ref["outputs"])  # same files, same names as the direct pipeline run
    assert st["draft_generated"] is (ref["decision"] == "SUPPORTED_AUTO")
    if ref["decision"] != "SUPPORTED_AUTO":
        assert not outputs & DRAFT_FILES, "no draft artifacts may exist for a blocked run"

    by = {s["key"]: s for s in st["stages"]}
    ran = [s for s in st["stages"] if s["status"] != "NOT_RUN"]
    assert all(s["duration_ms"] is not None and s["spans"] for s in ran)
    assert by["rule_pack"]["status"] == "COMPLETED" and st["rule_pack"]["status"] == "APPROVED_FOR_POC"
    elig = by["eligibility"]
    with open(tmp_path / "ref" / "eligibility_result.json", encoding="utf-8") as f: ref_elig = json.load(f)
    if ref_elig["decision"] == "SUPPORTED_AUTO":  # validation can still block afterwards (driveway_at_sign)
        assert elig["status"] == "COMPLETED"
        if ref["decision"] == "REVIEW_REQUIRED":
            assert by["validation"]["status"] == "REVIEW" and by["render"]["status"] == "NOT_RUN"
    else:
        assert elig["status"] == {"REVIEW_REQUIRED": "REVIEW", "ERROR": "ERROR", "UNSUPPORTED_POC": "UNSUPPORTED"}[shown]
        assert all(by[k]["status"] == "NOT_RUN" for k in ("rules", "validation", "render"))
    if ref["decision"] == "SUPPORTED_AUTO":
        a, b = (json.load(open(os.path.join(d, "plan.json"), encoding="utf-8"))
                for d in (store.run_path(st["run_id"], "output"), tmp_path / "ref"))
        for p in (a, b):  # wall-clock timestamps (and the hash/id that include them) differ per run
            for k in ("generated_at", "plan_hash", "plan_id"): p.pop(k)
            p["imagery"].pop("retrieved_at")
        assert a == b  # the UI path produces the identical plan
        assert st["dwt"] == ref["dwt"]  # DWT outcome reported as-is (fails closed without toolchain/blocks)
        assert by["render"]["status"] == "WARNING" and any("DWT" in p for p in by["render"]["problems"])
    # offline runs make no external calls; cost is never shown as $0
    assert st["cost"]["ai"]["calls"] == 0 and st["cost"]["ai"]["estimated_cost_usd"] is None
    assert st["cost"]["total_cost_usd"] is None


def test_ui_supported_with_tcp_sheet(api, monkeypatch):
    monkeypatch.setenv("TCP_RENDER_SHEET", "1")
    call, run = api
    st = run({"input_type": "offline", "offline_scenario": "supported", "advanced": {"no_dwt": True}}, timeout=300)
    assert st["decision"] == "SUPPORTED_AUTO" and st["draft_generated"]
    names = {o["name"] for o in st["outputs"]}
    assert {"tcp_sheet.png", "tcp_sheet.pdf"} <= names
    code, body = call("GET", f"/api/runs/{st['run_id']}/files/tcp_sheet.png")
    assert code == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"
    assert st["dwt"] == {"status": "SKIPPED"}


def test_invalid_kml_is_unsupported_at_input(api):
    _, run = api
    st = run({"input_type": "kml", "kml": {"filename": "bad.kml",
                                           "content_base64": base64.b64encode(b"<notkml/>").decode()}})
    assert st["decision"] == "UNSUPPORTED_POC" and st["exit_code"] == 4 and "INVALID_KML" in st["reason_codes"]
    stages = {s["key"]: s for s in st["stages"]}
    assert stages["input"]["status"] == "UNSUPPORTED"
    assert "eligibility_result.json" in stages["input"]["artifacts"]
    assert all(s["status"] == "NOT_RUN" for k, s in stages.items() if k != "input")
    assert os.path.isfile(records.resolve(st["request"]["kml_saved_path"]))  # a run-relative key (D-77) and not st["draft_generated"]


def test_out_of_range_coordinates_rejected_by_pipeline(api):
    _, run = api
    st = run({"input_type": "coordinates", "lat": "200", "lon": "-82.9"})
    assert st["decision"] == "UNSUPPORTED_POC" and "INVALID_COORDINATES" in st["reason_codes"]


def test_rule_pack_failure_is_pipeline_failed(api, monkeypatch, tmp_path):
    monkeypatch.setenv("TCP_RULE_PACK", str(tmp_path / "missing_pack.json"))
    _, run = api
    st = run({"input_type": "offline", "offline_scenario": "supported"})
    assert st["decision"] == "FAILED" and st["exit_code"] == 2
    assert st["error"]["error_code"] == "RULE_PACK_MISSING"
    assert {s["key"]: s["status"] for s in st["stages"]}["rule_pack"] == "FAILED"
    assert st["rule_pack"] is None and not st["draft_generated"]


def test_no_secrets_and_no_path_escape(api):
    call, run = api
    st = run({"input_type": "offline", "offline_scenario": "four_lane"})
    rid = st["run_id"]
    for path in ("/api/meta", "/api/runs", f"/api/runs/{rid}"):
        code, body = call("GET", path)
        assert code == 200 and SECRET.encode() not in body
    for bad in ("..%2F..%2Fui%2Frequest.state.json", "..%2F..%2Fui%2Frequest.json", "..%5Cui%5Crequest.json", "%2E%2E"):
        assert call("GET", f"/api/runs/{rid}/files/{bad}")[0] in (400, 404)
    assert call("GET", "/api/runs/..%2F..%2Fetc")[0] in (400, 404)
    assert call("GET", "/api/meta", headers={"Host": "evil.example"})[0] == 403


def test_bad_requests_rejected_before_running(api):
    call, _ = api
    assert call("POST", "/api/runs", {"input_type": "offline", "offline_scenario": "nope"})[0] == 400
    assert call("POST", "/api/runs", {"input_type": "coordinates", "lat": "", "lon": "1"})[0] == 400
    assert call("POST", "/api/runs", {"input_type": "offline", "offline_scenario": "supported",
                                      "operator": {"options": [{"key": "a b", "value": "1"}]}})[0] == 400


def test_cost_is_estimated_only_from_configured_prices():
    usage = {"input_tokens": 1_000_000, "output_tokens": 500_000, "cache_read_input_tokens": 0}
    none = {"anthropic": {"m": {"input_per_mtok": None, "output_per_mtok": None}}}
    assert store._priced("m", usage, none)[0] is None
    priced = {"anthropic": {"m": {"input_per_mtok": 2.0, "output_per_mtok": 10.0}}}
    assert store._priced("m", usage, priced) == (7.0, None)
    assert store._priced("other-model", usage, priced)[0] is None
    with open(store.PRICING_PATH, encoding="utf-8") as f:
        shipped = json.load(f)["anthropic"]
    assert all(v is None for m in shipped.values() for v in m.values())  # no unverified prices shipped


def test_anthropic_usage_recorder_observes_only(tmp_path, monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    from tcp_planner.orchestration import run_worker as runner
    from anthropic.resources.messages import Messages

    class Resp:
        model = "claude-test"; stop_reason = "end_turn"
        class usage:
            @staticmethod
            def model_dump(mode=None): return {"input_tokens": 11, "output_tokens": 7}

    sentinel = Resp()
    monkeypatch.setattr(Messages, "create", lambda self, **k: sentinel)
    orig = anthropic.Anthropic
    try:
        rec = runner.Recorder(str(tmp_path))
        runner._install_anthropic_usage(rec)
        client = anthropic.Anthropic(api_key="test")
        assert client.messages.create(model="claude-test", max_tokens=1, messages=[]) is sentinel  # unchanged
        assert rec.usage[0]["usage"] == {"input_tokens": 11, "output_tokens": 7}
        assert rec.usage[0]["response_model"] == "claude-test"
    finally:
        anthropic.Anthropic = orig
