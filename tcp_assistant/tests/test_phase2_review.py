import json

from .conftest import call, login, tree_hash


def _start(runs, sc, who="sme.1"):
    t = login(who)
    st, _, body = call("POST", "conversations", {"run_id": runs[sc]}, token=t)
    assert st == 201, body
    return t, body


def test_review_eligibility_and_cli_runs_rejected(aenv, runs):
    t = login()
    st, _, body = call("GET", f"runs/{runs['missing_road_type']}/eligibility", token=t)
    assert body["eligible"] and body["can_start"]
    # a run directory without an evidence manifest (CLI-like) is not eligible
    import shutil
    rid = runs["supported"]; fake = "20990101-000000-abcdef"
    shutil.copytree(aenv / "runs" / rid, aenv / "runs" / fake); shutil.rmtree(aenv / "runs" / fake / "evidence")
    body = call("GET", f"runs/{fake}/eligibility", token=t)[2]
    assert not body["eligible"] and {r["code"] for r in body["reasons"]} >= {"EVIDENCE_MANIFEST_MISSING"}
    st, _, err = call("POST", "conversations", {"run_id": fake}, token=t)
    assert st == 409 and err["error_code"] == "RUN_NOT_ELIGIBLE"


def test_findings_cards_and_annotated_image(aenv, runs):
    before = tree_hash(aenv / "runs")
    t, v = _start(runs, "missing_road_type")
    f = {x["subject"]: x for x in v["findings"]}
    rt = f["road.road_type"]
    assert rt["requires_review"] and rt["state"] == "UNKNOWN" and rt["severity"] == "BLOCKING"
    assert {c["value"] for c in rt["choices"] if c["action"] == "CORRECT"} >= {"RURAL", "URBAN_LOW_SPEED"}
    assert f["road.lane_count"]["state"] == "DETERMINED" and f["road.lane_count"]["value"] == 2
    cards = [m for m in v["messages"] if m["kind"] == "REVIEW_CARD"]
    assert {c["body"]["finding_id"] for c in cards} == {x["finding_id"] for x in v["findings"] if x["requires_review"]}
    summ = next(m for m in v["messages"] if m["kind"] == "SUMMARY")
    aid = summ["body"]["annotated_image_artifact_id"]
    a = call("GET", f"artifacts/{aid}", token=t)[2]["artifact"]
    assert a["authoritative"] is False and "lane boundaries" in " ".join(a["not_assessed"])
    for it in a["items"]:
        assert it["label"] and it["state"] and "evidence_sources" in it and "n" in it
    st, kind, body = call("GET", f"artifacts/{aid}/file", token=t)
    assert kind == "file" and open(body["path"], "rb").read()[:4] == b"\x89PNG"
    assert tree_hash(aenv / "runs") == before  # runs and original evidence untouched


def test_finding_ids_stable_and_image_deterministic(aenv, runs):
    t, v1 = _start(runs, "driveway_at_sign")
    t2, v2 = _start(runs, "driveway_at_sign")
    assert [x["finding_id"] for x in v1["findings"]] == [x["finding_id"] for x in v2["findings"]]
    a1 = next(m for m in v1["messages"] if m["kind"] == "SUMMARY")["body"]["annotated_image_artifact_id"]
    a2 = next(m for m in v2["messages"] if m["kind"] == "SUMMARY")["body"]["annotated_image_artifact_id"]
    assert a1 == a2  # identical inputs -> the same immutable artifact is reused
    rc = [x for x in v1["findings"] if x["category"] == "RULE_CHECK"]
    assert any(x["subject"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT" and x["rule_status"] == "CONFLICT" for x in rc)
    drv = [x for x in v1["findings"] if x["category"] == "FEATURE" and x["feature_kind"] == "driveways" and x["related_objects"]]
    assert drv and drv[0]["severity"] == "BLOCKING"


def test_lane_conflict_and_ta_visible(aenv, runs):
    t, v = _start(runs, "lane_conflict")
    f = {x["subject"]: x for x in v["findings"]}
    assert f["road.lane_count"]["state"] == "CONFLICT"
    ta = next(x for x in v["findings"] if x["category"] == "TA")
    assert ta["entity_id"] == "TA-1" and ta["candidates"] == []
    t, v = _start(runs, "four_lane")
    ta = next(x for x in v["findings"] if x["category"] == "TA")
    assert ta["status"] == "NOT_APPLICABLE" and ta["state"] == "CONFLICT"


def test_authorization_and_ownership(aenv, runs):
    t, v = _start(runs, "supported")
    cid = v["conversation"]["conversation_id"]
    aud = login("aud.1")
    assert call("POST", "conversations", {"run_id": runs["supported"]}, token=aud)[0] == 403
    assert call("GET", f"conversations/{cid}", token=aud)[0] == 200      # auditor may read
    adm = login("adm.1")
    assert call("GET", "audit", token=adm)[0] == 200
    assert call("GET", "audit", token=t)[0] == 403                      # reviewer has no audit:read


def test_review_flow_makes_no_ai_or_external_calls(aenv, runs, monkeypatch):
    import requests
    from tcp_poc import foundry_provider as fp
    def boom(*a, **k): raise AssertionError("external call attempted")
    monkeypatch.setattr(requests, "get", boom); monkeypatch.setattr(requests, "post", boom)
    for k in list(fp.APIS): monkeypatch.setitem(fp.APIS, k, boom)
    t, v = _start(runs, "intersection")
    assert v["findings"]
    evs = [e for e in __import__("tcp_assistant.services.container", fromlist=["x"]).container().audit.read()
           if e["event_type"] == "TOOL_INVOCATION"]
    assert evs and all(e["external_call"] is False and e["model_deployment"] == "N/A" for e in evs)


def test_http_server_enabled_session_and_artifact(aenv, runs):
    import threading, urllib.request
    from tcp_ui import server
    srv = server.make_server(0); port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def req(method, path, body=None, token=None, raw=False):
        h = {"Content-Type": "application/json"}
        if token: h["X-TCP-Session"] = token
        r = urllib.request.Request(f"http://127.0.0.1:{port}/api/assistant/{path}", method=method, headers=h,
                                   data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(r) as resp: data = resp.read(); return resp.status, (data if raw else json.loads(data))
        except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
    try:
        assert req("GET", "status")[1]["enabled"] is True
        st, body = req("POST", "sessions", {"subject_id": "sme.1"}); tok = body["session_token"]
        st, v = req("POST", "conversations", {"run_id": runs["supported"]}, token=tok)
        assert st == 201
        aid = next(m for m in v["messages"] if m["kind"] == "SUMMARY")["body"]["annotated_image_artifact_id"]
        st, png = req("GET", f"artifacts/{aid}/file", token=tok, raw=True)
        assert st == 200 and png[:4] == b"\x89PNG"
        assert req("GET", f"artifacts/{aid}/file")[0] == 401                      # no session -> no file
        assert req("POST", "conversations", {"run_id": runs["supported"]}, token="sme.1")[0] == 401
    finally:
        srv.shutdown(); srv.server_close()
