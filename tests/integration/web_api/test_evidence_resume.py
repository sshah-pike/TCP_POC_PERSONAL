"""Evidence persistence, resume/reuse and model comparison (no network, no real credentials).

Runs execute the real runner -> tcp_planner.orchestration.pipeline.main -> run_pipeline in-process; HTTP is a fake.
"""
import base64, json, math, os
import pytest
import requests

from tcp_planner.orchestration import offline_scenarios as offline
from tcp_planner.ai import foundry_provider as fp
from tcp_planner.imagery.map_provider import AzureMapsProvider
from tcp_planner.storage import run_store as store
from tcp_planner.orchestration import run_relations as relations
from tcp_planner.storage.evidence_store import load_manifest, sha256_file
from tests.integration.web_api import inproc
from tests.integration.web_api.inproc import FakeHttp, FakeResponse, FAKE_AZURE_KEY

SC = offline.build("supported")
LAT, LON = SC["lat"], SC["lon"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("AZURE_MAPS_KEY", FAKE_AZURE_KEY)
    monkeypatch.setenv("TCP_FOUNDRY_PROFILES_FILE", inproc.write_profiles(str(tmp_path / "profiles.json")))
    monkeypatch.setitem(fp.APIS, "fake_api", inproc.FakeAPI)
    monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "foundry-test-key-SENTINEL")
    monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://example-resource.services.ai.azure.com")
    monkeypatch.setenv("TCP_FOUNDRY_PROFILE", "fake-a")  # parent runs use fake-a (restored after each test)
    inproc.SEEN.clear()
    return tmp_path


def http(monkeypatch, **kw):
    h = FakeHttp(osm_elements=SC["osm_elements"], **kw)
    monkeypatch.setattr(requests, "get", h)
    return h


def analysis_requests(h):
    """Azure analysis-imagery requests (1280 px). Agent crops (1024 px) are counted separately: call 2 runs on every
    live run because a wide-image road width cannot resolve road edges."""
    return sum(1 for host, kw in h.calls if host == "atlas.microsoft.com" and kw["params"]["width"] == 1280)


def azure_run(lat=LAT, lon=LON, kml=None):
    payload = {"operator": {"road_type": "RURAL"},
               "advanced": {"map_provider": "azure_maps", "ai_provider": "foundry", "no_dwt": True}}
    if kml:
        payload.update(input_type="kml", kml={"filename": "site.kml", "content_base64": base64.b64encode(kml).decode()})
    else:
        payload.update(input_type="coordinates", lat=str(lat), lon=str(lon))
    rid, rdir = store.create_run(payload, set())
    inproc.run(rdir)
    return rid, store.build_state(rid)


def resume(parent, stage, **kw):
    rid, rdir = relations.create_resume_run(parent, stage, **kw)
    inproc.run(rdir)
    return rid, store.build_state(rid)


def kml_bytes(lat, lon):
    return (f'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point>'
            f'<coordinates>{lon},{lat}</coordinates></Point></Placemark></kml>').encode()


def stage(st, key):
    return next(s for s in st["stages"] if s["key"] == key)


# ---------------------------------------------------------------- persistence
def test_azure_image_persisted_immediately_and_kept_after_review(env, monkeypatch):
    h = http(monkeypatch, osm_error=requests.exceptions.ReadTimeout("Read timed out."))
    rid, st = azure_run()
    assert st["decision"] == "ERROR" and st["reason_codes"] == ["OSM_CONTEXT_UNAVAILABLE", "OSM_REQUEST_FAILED"]
    [m] = [e for e in load_manifest(store.run_path(rid)) if e["kind"] == "map"]
    assert m["producer_span"] == "tcp.map.retrieve" and m["mode"] == "saved"
    path = store.run_path(rid, "evidence", m["file"])
    assert os.path.isfile(path) and sha256_file(path) == m["sha256"]
    meta = m["metadata"]["meta"]
    for k in ("bounding_box", "metres_per_pixel", "center", "ground_extent_m", "zoom"): assert k in meta
    assert meta["scale_model"] == "azure-static-512px-v2" and m["metadata"]["format"] == "PNG"
    assert m["metadata"]["width"] == m["metadata"]["height"] == 1280
    sig = m["signature"]
    assert sig["provider"] == "azure_maps" and sig["size_px"] == 1280 and sig["geometry_hash"] and sig["half_extent_m"] > 0
    assert h.count("atlas.microsoft.com") == 1
    assert "aerial_image.jpg" not in {o["name"] for o in st["outputs"]}  # pipeline outputs unchanged
    inproc.assert_no_secret(store.run_path(rid))


# ---------------------------------------------------------------- resume
def test_resume_from_osm_reuses_map_without_new_azure_call(env, monkeypatch):
    http(monkeypatch, osm_error=requests.exceptions.ReadTimeout("Read timed out."))
    parent, _ = azure_run()
    before = inproc.tree_hashes(store.run_path(parent))
    h = http(monkeypatch)  # OSM healthy now
    child, st = resume(parent, "osm")
    assert child != parent and st["lineage"]["parent_run_id"] == parent and st["lineage"]["requested_stage"] == "osm"
    assert st["lineage"]["actual_stage"] == "osm"
    assert analysis_requests(h) == 0 and h.count("api.openstreetmap.org") == 1
    img = stage(st, "imagery")
    assert img["reuse"] and img["reuse"][0]["source_run"] == parent and img["reuse"][0]["api_call"] is False
    assert img["new_calls"] == []
    imagery = next(s for s in st["cost"]["services"] if s["service"] == "Imagery")
    # the analysis image is reused; the Imagery cost row now also counts the agent's crop requests (1024 px)
    assert imagery["requests"] == h.count("atlas.microsoft.com") - analysis_requests(h)
    assert st["lineage"]["parent_cost"] is not None  # original run cost kept separately
    assert inproc.tree_hashes(store.run_path(parent)) == before  # original run immutable
    inproc.assert_no_secret(store.run_path(child))


def test_resume_from_ai_calls_neither_azure_nor_osm(env, monkeypatch):
    http(monkeypatch); parent, pst = azure_run()
    assert stage(pst, "vision")["status"] in ("COMPLETED", "WARNING")
    h = http(monkeypatch)
    child, st = resume(parent, "vision", ai_profile="fake-b", ai_provider="foundry")
    assert h.count("api.openstreetmap.org") == 0
    # analysis imagery is reused; the only Azure requests are the agent's crops (1024 px) for fake-b's unresolved
    # two-way field, recorded as vision-stage calls
    assert analysis_requests(h) == 0 and all(c[1]["params"]["width"] == 1024 for c in h.calls)
    assert stage(st, "imagery")["new_calls"] == []
    assert all(c["purpose"].startswith("agent crop") for c in stage(st, "vision")["new_calls"])
    assert st["lineage"]["actual_stage"] == "vision"
    assert {"map", "osm"} <= {r["kind"] for s in st["stages"] for r in s["reuse"]} <= {"map", "osm", "map_crop"}
    # parent fake-a and child fake-b: call 1 + call 2 each - the AI really re-ran
    assert [m for m, *_ in inproc.SEEN] == ["ok", "ok", "low", "low"]
    assert inproc.SEEN[0][1:] == inproc.SEEN[2][1:]  # identical call-1 image bytes and prompt for both models


def test_changed_kml_invalidates_map_and_osm_reuse(env, monkeypatch):
    http(monkeypatch); parent, _ = azure_run(kml=kml_bytes(LAT, LON))
    rid, rdir = relations.create_resume_run(parent, "vision", ai_profile="fake-a", ai_provider="foundry")
    with open(json.load(open(os.path.join(rdir, "ui", "request.json")))["request"]["kml_saved_path"], "wb") as f:
        f.write(kml_bytes(LAT + 0.0003, LON))  # the input changed after the resume was prepared
    h = http(monkeypatch); inproc.run(rdir); st = store.build_state(rid)
    assert analysis_requests(h) == 1 and h.count("api.openstreetmap.org") == 1
    assert st["lineage"]["actual_stage"] == "imagery"
    rej = stage(st, "imagery")["reuse_rejected"][0]["reason"]
    assert "geometry_hash" in rej


def test_changed_map_configuration_invalidates_map_evidence(env, monkeypatch):
    http(monkeypatch); parent, _ = azure_run()
    monkeypatch.setattr(AzureMapsProvider, "API_VERSION", "2099-01-01")
    h = http(monkeypatch)
    child, st = resume(parent, "vision", ai_profile="fake-a", ai_provider="foundry")
    assert analysis_requests(h) == 1
    assert "api_version" in stage(st, "imagery")["reuse_rejected"][0]["reason"]
    assert st["lineage"]["actual_stage"] == "imagery"


@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_damaged_artifacts_are_not_reused(env, monkeypatch, damage):
    http(monkeypatch); parent, _ = azure_run()
    m = next(e for e in load_manifest(store.run_path(parent)) if e["kind"] == "map")
    p = store.run_path(parent, "evidence", m["file"])
    if damage == "corrupt":
        with open(p, "ab") as f: f.write(b"tamper")
    else:
        os.remove(p)
    prev = relations.resume_preview(parent, "vision", "fake-a", "foundry")
    assert prev["moved_earlier"] and prev["predicted_actual_stage"] == "imagery"
    h = http(monkeypatch)
    child, st = resume(parent, "vision", ai_profile="fake-a", ai_provider="foundry")
    assert h.count("atlas.microsoft.com") == 1 and st["lineage"]["actual_stage"] == "imagery"
    reason = stage(st, "imagery")["reuse_rejected"][0]["reason"]
    assert ("hash mismatch" in reason) if damage == "corrupt" else ("missing" in reason)


def test_preview_lists_reused_and_rerun(env, monkeypatch):
    http(monkeypatch); parent, _ = azure_run()
    prev = relations.resume_preview(parent, "vision", "fake-b", "foundry")
    assert not prev["moved_earlier"] and prev["predicted_actual_stage"] == "vision"
    assert {(r["stage"], r["source_run"]) for r in prev["reused"]} == {("imagery", parent), ("osm", parent)}
    assert all(len(r["sha256"]) == 64 and r["api_call"] is False for r in prev["reused"])
    rr = {r["stage"]: r for r in prev["rerun"]}
    assert "fake-b" in rr["vision"]["external_call"] and rr["fusion"]["external_call"] is None
    assert "imagery" not in rr and "osm" not in rr


def test_resume_after_ai_reuses_validated_observation(env, monkeypatch):
    http(monkeypatch); parent, pst = azure_run()
    h = http(monkeypatch); n = len(inproc.SEEN)
    child, st = resume(parent, "fusion")
    assert len(inproc.SEEN) == n  # no model call
    # call 2 always runs now (a wide-image width cannot resolve road edges): its crops are reused too
    assert {r["kind"] for s in st["stages"] for r in s["reuse"]} == {"map", "osm", "ai", "map_crop"}
    assert st["decision"] == pst["decision"] and st["reason_codes"] == pst["reason_codes"]
    assert st["cost"]["ai"]["new_api_call"] is False and st["cost"]["ai"]["reused_from"] == [parent]


# ---------------------------------------------------------------- comparison
def test_model_comparison_identical_inputs_independent_results(env, monkeypatch):
    http(monkeypatch); source, _ = azure_run()
    inproc.SEEN.clear(); h = http(monkeypatch)
    cid = relations.create_comparison(source, ["fake-a", "fake-b", "fake-fail"])
    children = relations.create_children(cid)
    for c in children: inproc.run(store.run_path(c))
    assert h.count("api.openstreetmap.org") == 0  # no analysis-imagery or OSM call; only agent crops (1024 px)
    assert all(c[1]["params"]["width"] == 1024 for c in h.calls)
    call1 = [x for x in inproc.SEEN if len(x[1]) == 1]
    assert sorted(m for m, *_ in call1) == ["fail", "low", "ok"]
    assert len({(img, ctx) for _, img, ctx in call1}) == 1  # exact same call-1 image bytes + prompt for every model
    rep = relations.comparison_state(cid)
    assert rep["complete"] and len(rep["columns"]) == 3
    cols = {c["profile"]: c for c in rep["columns"]}
    assert cols["fake-fail"]["ai_status"] == "ERROR" and cols["fake-fail"]["schema_errors"]
    assert "AI_OBSERVATION_UNAVAILABLE" in cols["fake-fail"]["reason_codes"]
    assert cols["fake-a"]["ai_status"] == cols["fake-b"]["ai_status"] == "OK"
    assert cols["fake-a"]["eligibility"] and cols["fake-b"]["eligibility"]  # each ran Fusion + Eligibility itself
    assert cols["fake-a"]["fusion"]["site_model_id"] != cols["fake-b"]["fusion"]["site_model_id"]
    for c in rep["columns"]:
        for k in ("resolved", "unresolved", "low_confidence", "below_threshold"): assert k in c["metrics"]
        assert {"map", "osm"} <= {r["kind"] for r in c["reused"]} <= {"map", "osm", "map_crop"}
        assert all(x.get("purpose", "").startswith("agent crop") for x in c["new_external_calls"])
    row = next(r for r in rep["rows"] if r["section"] == "observation" and r["field"] == "two_way_visible")
    assert row["differs"] and row["unknown_vs_resolved"]
    conf = next(r for r in rep["rows"] if r["section"] == "confidence" and r["field"] == "two_way_visible")
    assert conf["below_threshold"][1] is True
    assert rep["totals"]["new_map_calls"] == h.count("atlas.microsoft.com")  # agent crops only
    assert rep["totals"]["analysis_map_calls_in_children"] == 0 and rep["totals"]["estimated_cost_usd"] is None
    assert os.path.isfile(store.run_path(cid, "ui", "report.json"))
    text = json.dumps(rep).lower()
    assert "best" not in text and "winner" not in text and "rank" not in text.replace("ranked", "")


def test_comparison_rejects_unavailable_profiles(env, monkeypatch):
    http(monkeypatch); source, _ = azure_run()
    with pytest.raises(store.BadRequest): relations.create_comparison(source, ["disabled-one", "fake-a"])
    with pytest.raises(store.BadRequest): relations.create_comparison(source, ["no-such-profile", "fake-a"])
    with pytest.raises(store.BadRequest): relations.create_comparison(source, ["fake-a"])  # needs two columns


# ---------------------------------------------------------------- Azure provider fixes
def test_azure_scale_uses_512px_grid(monkeypatch):
    monkeypatch.setenv("AZURE_MAPS_KEY", FAKE_AZURE_KEY)
    h = FakeHttp(); monkeypatch.setattr(requests, "get", h)
    from tcp_planner.intake import kml_reader as kml_input
    img, meta = AzureMapsProvider().fetch_context(kml_input.from_coordinates(LAT, LON), 212.4, 1280)
    z = meta["zoom"]
    assert meta["metres_per_pixel"] == pytest.approx(2 * math.pi * 6378137.0 * math.cos(math.radians(LAT)) / (512 * 2 ** z), rel=1e-6)
    assert meta["ground_extent_m"]["width"] >= 2 * 212.4 and h.count("atlas.microsoft.com") == 1


def test_azure_sheet_mosaic_within_limits_and_georeferenced(monkeypatch):
    import numpy as np
    monkeypatch.setenv("AZURE_MAPS_KEY", FAKE_AZURE_KEY)
    h = FakeHttp(); monkeypatch.setattr(requests, "get", h)
    from tcp_planner.intake import kml_reader as kml_input
    img, meta = AzureMapsProvider().fetch_context(kml_input.from_coordinates(LAT, LON), 424.0, 2560)
    assert img.size == (2560, 2560) and meta["request_tiles"] == 4 and h.count("atlas.microsoft.com") == 4
    assert all(c[1]["params"]["width"] <= 2000 and c[1]["params"]["height"] <= 1500 for c in h.calls)
    # pixels encode global pixel coordinates: the mosaic must be one continuous grid centred on the work point
    z = meta["zoom"]; world = 512 * 2 ** z
    cx = (LON + 180) / 360 * world
    cy = (1 - math.log(math.tan(math.radians(LAT)) + 1 / math.cos(math.radians(LAT))) / math.pi) / 2 * world
    a = np.asarray(img)
    x0, y0 = int(round(cx - 1280)), int(round(cy - 1280))
    xs = np.arange(0, 2560, 37); ys = np.arange(0, 2560, 41)
    assert (a[0, xs, 0] == (xs + x0) % 251).all() and (a[ys, 0, 1] == (ys + y0) % 241).all()
    assert meta["center"] == {"latitude": round(LAT, 7), "longitude": round(LON, 7)} and meta["width_pixels"] == 2560


@pytest.mark.parametrize("response", [
    lambda p, kw: FakeResponse(200, "application/json", b'{"error": {"code": "x"}}'),
    lambda p, kw: FakeResponse(200, "image/png", b"not really a png"),
])
def test_azure_non_image_response_fails_closed_as_map_failure(env, monkeypatch, response):
    http(monkeypatch, azure=response)
    rid, st = azure_run()
    assert st["decision"] == "ERROR" and st["exit_code"] == 3
    assert st["reason_codes"] == ["MAP_CONTEXT_UNAVAILABLE", "MAP_REQUEST_FAILED"]
    d = stage(st, "imagery")["diagnostics"][0]
    assert d["pipeline_error_code"] == "MAP_REQUEST_FAILED" and d["http_status"] == 200
    assert not [e for e in load_manifest(store.run_path(rid)) if e["kind"] == "map"]  # nothing persisted on failure
    inproc.assert_no_secret(store.run_path(rid))


# ---------------------------------------------------------------- API surface (what the browser receives)
def test_api_endpoints_and_no_credentials(env, monkeypatch):
    import threading, urllib.request, urllib.error
    from tcp_planner.web_api import server
    http(monkeypatch); source, _ = azure_run()
    cid = relations.create_comparison(source, ["fake-a", "fake-fail"])
    children = relations.create_children(cid)
    for c in children: inproc.run(store.run_path(c))
    srv = server.make_server(0); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path):
        try:
            with urllib.request.urlopen(base + path, timeout=30) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r: return r.status, r.read()
        except urllib.error.HTTPError as e: return e.code, e.read()
    try:
        bodies = []
        for p in ("/api/meta", "/api/runs", "/api/comparisons", f"/api/comparisons/{cid}", f"/api/runs/{children[0]}",
                  f"/api/runs/{source}/resume-preview?stage=vision&ai_profile=fake-b"):
            code, b = get(p); assert code == 200, (p, code, b); bodies.append(b)
        meta = json.loads(bodies[0])
        assert {p["name"] for p in meta["foundry_profiles"] if p["available"]} == {"fake-a", "fake-b", "fake-fail", "fake-inconsistent"}
        runs = {r["run_id"]: r for r in json.loads(bodies[1])}
        assert runs[children[0]]["parent_run_id"] == source and runs[children[0]]["comparison_id"] == cid
        assert json.loads(bodies[3])["complete"] and json.loads(bodies[5])["predicted_actual_stage"] == "vision"
        m = next(e for e in load_manifest(store.run_path(source)) if e["kind"] == "map")
        code, img = get(f"/api/runs/{source}/evidence/{m['file']}"); assert code == 200 and img[:8] == b"\x89PNG\r\n\x1a\n"
        assert get(f"/api/runs/{source}/evidence/manifest.json")[0] == 404  # only artifacts the manifest lists
        assert get(f"/api/runs/{source}/evidence/..%2Fui%2Frequest.json")[0] in (400, 404)
        assert post(f"/api/runs/{source}/resume", {"stage": "nonsense"})[0] == 400
        assert post(f"/api/runs/{source}/resume", {"stage": "vision", "ai_profile": "disabled-one"})[0] == 400
        assert post("/api/comparisons", {"source_run_id": source, "profiles": ["nope"]})[0] == 400
        for b in bodies + [img]: assert FAKE_AZURE_KEY.encode() not in b
    finally:
        srv.shutdown(); srv.server_close()
    inproc.assert_no_secret(store.runs_dir())


def test_fully_reused_run_reports_zero_provider_calls(env, monkeypatch):
    http(monkeypatch); parent, _ = azure_run()
    child, st = resume(parent, "fusion")  # everything external reused: no calls at all -> no calls.json written
    svc = {s["service"]: s for s in st["cost"]["services"]}
    assert svc["Imagery"]["requests"] == 0 and svc["Imagery"]["new_api_call"] is False
    assert svc["OpenStreetMap"]["requests"] == 0 and svc["OpenStreetMap"]["new_api_call"] is False
    assert "no new provider call" in svc["Imagery"]["note"] and st["cost"]["ai"]["new_api_call"] is False



# ---------------------------------------------------------------- multi-resolution evidence
def prep(cid):
    from tcp_planner.orchestration import run_worker as runner
    with inproc.isolated():
        return runner.prepare_views(store.run_path(cid))


def test_comparison_multi_resolution_views_acquired_once_and_identical(env, monkeypatch):
    http(monkeypatch); source, _ = azure_run()
    h = http(monkeypatch); inproc.SEEN.clear()
    cid = relations.create_comparison(source, ["fake-a", "fake-b"], ["single", "multi"])
    assert prep(cid) and h.count("atlas.microsoft.com") == 3 and h.count("api.openstreetmap.org") == 0  # views only
    zooms = sorted(c[1]["params"]["zoom"] for c in h.calls)
    assert zooms == [18, 18, 19]
    children = relations.create_children(cid)
    assert len(children) == 4
    h2 = http(monkeypatch)
    for c in children: inproc.run(store.run_path(c))
    assert h2.count("api.openstreetmap.org") == 0  # nothing re-fetched; Azure requests are agent crops (1024 px) only
    assert all(c[1]["params"]["width"] == 1024 for c in h2.calls)
    # the legacy multi-resolution views are still prepared once, but the agent no longer sends them: call 1 is
    # always ONE native wide image, identical for every model and every legacy variant
    call1 = [x for x in inproc.SEEN if len(x[1]) == 1]
    assert len(call1) == 4 and len({x[1:] for x in call1}) == 1
    rep = relations.comparison_state(cid)
    assert rep["complete"] and {c["evidence_mode"] for c in rep["columns"]} == {"single", "multi"}
    for e in load_manifest(store.run_path(cid)):  # views keep their own georeference at the corrected scale
        m = e["metadata"]["meta"]
        assert e["kind"] == "map_view" and m["scale_model"] == "azure-static-512px-v2" and "bounding_box" in m
    inproc.assert_no_secret(store.runs_dir(), secrets=(FAKE_AZURE_KEY, "foundry-test-key-SENTINEL"))


def test_resume_multi_switch_inert_and_agent_crops_reused(env, monkeypatch):
    """Legacy evidence_mode=multi no longer adds views to the model request; agent crops are saved and reused."""
    http(monkeypatch); parent, _ = azure_run()
    h = http(monkeypatch); n = len(inproc.SEEN)
    child, st = resume(parent, "vision", ai_profile="fake-a", ai_provider="foundry", evidence_mode="multi")
    assert analysis_requests(h) == 0 and h.count("api.openstreetmap.org") == 0
    assert h.count("atlas.microsoft.com") == 0  # the parent's crop (same request) is reused
    assert {r["kind"] for r in stage(st, "vision")["reuse"]} == {"map_crop"}
    child_calls = inproc.SEEN[n:]
    assert len(child_calls[0][1]) == 1  # call 1: one wide image, no legacy views
    assert child_calls[1][1:] == inproc.SEEN[n - 1][1:]  # identical call-2 request (same crop, same prompt)


def test_multi_mode_switch_does_not_change_the_agent_path(env, monkeypatch):
    http(monkeypatch)
    runs = {}
    for mode in ("single", "multi"):
        rid, rdir = store.create_run({"input_type": "offline", "offline_scenario": "supported",
                                      "advanced": {"evidence_mode": mode}}, {"supported"})
        inproc.run(rdir); runs[mode] = store.build_state(rid)
    assert runs["multi"]["decision"] == runs["single"]["decision"] == "SUPPORTED_AUTO"
    assert runs["multi"]["plan"]["plan_hash"] == runs["single"]["plan"]["plan_hash"]


def test_legacy_azure_evidence_not_eligible(env, monkeypatch):
    http(monkeypatch); parent, _ = azure_run()
    mpath = store.run_path(parent, "evidence", "manifest.json")
    doc = json.load(open(mpath, encoding="utf-8"))
    for e in doc["artifacts"]:
        if e["kind"] == "map": e["signature"]["scale_model"] = None  # as recorded before the scale fix
    json.dump(doc, open(mpath, "w", encoding="utf-8"))
    prev = relations.resume_preview(parent, "vision", "fake-a", "foundry")
    assert prev["legacy"] and "LEGACY EVIDENCE" in prev["legacy_reason"]
    assert store.build_state(parent)["evidence_compat"]["status"] == "LEGACY"
    with pytest.raises(store.BadRequest): relations.create_comparison(parent, ["fake-a", "fake-b"])
    with pytest.raises(store.BadRequest): relations.create_resume_run(parent, "vision", "fake-a", "foundry")
    rid, _ = relations.create_resume_run(parent, "imagery")  # explicit fresh acquisition is still possible
    assert rid


def test_state_of_run_without_imagery_evidence_is_cheap(env, monkeypatch):
    """Regression: evidence_compat must not re-enter build_state (was unbounded recursion)."""
    import time
    rid, rdir = store.create_run({"input_type": "coordinates", "lat": "abc", "lon": "1"}, set())  # argparse failure
    inproc.run(rdir)
    t0 = time.perf_counter(); st = store.build_state(rid)
    assert time.perf_counter() - t0 < 2 and st["evidence_compat"]["status"] == "NONE"
