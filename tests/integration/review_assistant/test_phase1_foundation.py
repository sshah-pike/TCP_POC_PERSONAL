import json, os, shutil

import pytest

from .conftest import call, login


def test_disabled_flag_exposes_only_status_and_creates_no_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_SME_ASSISTANT_ENABLED", "false")
    monkeypatch.setenv("TCP_ASSISTANT_DATA_DIR", str(tmp_path / "ad"))
    assert call("GET", "status")[2] == {"enabled": False, "state": "DISABLED"}
    for m, p in (("GET", "identities"), ("POST", "sessions"), ("GET", "session"), ("POST", "conversations")):
        st, _, body = call(m, p, {"subject_id": "sme.1"})
        assert st == 404 and body["error_code"] == "ASSISTANT_DISABLED"
    assert not (tmp_path / "ad").exists()


def test_flag_default_is_off(monkeypatch):
    from tcp_planner.review.assistant import flags
    monkeypatch.delenv("TCP_SME_ASSISTANT_ENABLED", raising=False)
    monkeypatch.setattr(flags, "_env_file_value", lambda k: None)
    assert flags.enabled() is False


def test_identities_and_opaque_session(aenv):
    st, _, body = call("GET", "identities")
    subs = [i["subject_id"] for i in body["identities"]]
    assert subs == ["sme.1", "aud.1", "adm.1"]  # entry with a credential-like key ignored
    token = login()
    st, _, me = call("GET", "session", token=token)
    ident = me["identity"]
    assert ident["subject_id"] == "sme.1" and ident["identity_provider"] == "LOCAL_POC"
    for k in ("tenant_id", "entra_object_id", "upn"): assert ident[k] == "N/A"
    assert ident["session_id"].startswith("sess-")
    sess_dir = aenv / "assistant_data" / "sessions"
    blob = "".join(p.read_text() for p in sess_dir.iterdir())
    assert token not in blob  # only the token hash is stored


def test_caller_controlled_identity_is_not_trusted(aenv):
    st, _, body = call("GET", "session", token="sme.1")
    assert st == 401 and body["error_code"] == "AUTH_SESSION_REQUIRED"
    st, _, body = call("GET", "session", token=None)
    assert st == 401


def test_unknown_identity_rejected(aenv):
    st, _, body = call("POST", "sessions", {"subject_id": "nobody"})
    assert st == 400 and body["error_code"] == "IDENTITY_UNKNOWN"


def test_session_end(aenv):
    t = login()
    assert call("POST", "sessions/end", {}, token=t)[0] == 200
    assert call("GET", "session", token=t)[0] == 401


def test_role_permissions():
    from tcp_planner.review.assistant.core import authz
    from tcp_planner.review.assistant.core.identity import Identity
    aud = Identity(subject_id="a", roles=["AUDITOR"])
    assert authz.has(aud, "audit:read") and not authz.has(aud, "review:decide")
    with pytest.raises(Exception) as e: authz.require(aud, "changeset:confirm")
    assert e.value.code == "AUTHZ_DENIED"
    adm = Identity(subject_id="b", roles=["ADMIN"])
    assert not authz.has(adm, "exception:confirm")
    sme = Identity(subject_id="c", roles=["SME_REVIEWER"])
    assert authz.has(sme, "exception:confirm") and not authz.has(sme, "audit:read")


def test_canonicalization_v1():
    from tcp_planner.review.assistant.core.canonical import canonical_text, message_hash
    assert canonical_text("  a\r\nb\rc  \n") == "a\nb\nc"
    assert canonical_text("x  y") == "x  y"  # inner whitespace preserved
    assert canonical_text("é") == "é"  # NFC
    h1 = message_hash("c1", "m1", "2026-01-01T00:00:00.000+00:00", "Move S2 100 ft upstream")
    assert h1 == message_hash("c1", "m1", "2026-01-01T00:00:00.000+00:00", " Move S2 100 ft upstream\r\n")
    assert h1 != message_hash("c1", "m2", "2026-01-01T00:00:00.000+00:00", "Move S2 100 ft upstream")


def test_json_store_is_create_only_and_tamper_evident(tmp_path):
    from tcp_planner.review.assistant.repositories.json_store import JsonStore
    from tcp_planner.review.assistant.repositories.base import ImmutableExists, IntegrityError
    s = JsonStore(str(tmp_path))
    s.create("versions", "v1", {"a": 1})
    with pytest.raises(ImmutableExists): s.create("versions", "v1", {"a": 2})
    assert s.get("versions", "v1")["a"] == 1
    p = tmp_path / "versions" / "v1.json"
    doc = json.loads(p.read_text()); doc["a"] = 9; p.write_text(json.dumps(doc))
    with pytest.raises(IntegrityError): s.get("versions", "v1")
    with pytest.raises(ValueError): s.create("versions", "../x", {})
    s.put_blob("artifacts", "a1", "f.png", b"x")
    with pytest.raises(ImmutableExists): s.put_blob("artifacts", "a1", "f.png", b"y")
    assert s.compare_and_set_head("k", None, "v1") and not s.compare_and_set_head("k", None, "v2")
    assert s.compare_and_set_head("k", "v1", "v2")


def test_audit_chain_and_secret_scrubbing(aenv):
    from tcp_planner.review.assistant.services.container import container
    a = container().audit
    a.write("X", None, stream="s1", api_key="SHOULD-NOT-APPEAR", note="Bearer abcdefghijklmnop")
    a.write("Y", None, stream="s1", consequential=True)
    evs = a.read("s1")
    assert len(evs) == 2 and a.verify_chain(evs)
    raw = json.dumps(evs)
    assert "SHOULD-NOT-APPEAR" not in raw and "abcdefghijklmnop" not in raw
    evs[0]["event_type"] = "Z"
    assert not a.verify_chain(evs)


def test_policy_hash_verified_and_master_switch(tmp_path):
    from tcp_planner.review import action_policy as P
    pol = P.load_policy()
    assert pol.allowed("override_rule_conflict", ["SME_REVIEWER"])[0]
    assert not pol.allowed("override_rule_conflict", ["AUDITOR"])[0]
    assert not pol.allowed("request_new_imagery", ["SME_REVIEWER"])[0]
    assert not pol.condition_overridable("OUTSIDE_EVIDENCE_COVERAGE")
    doc = json.load(open(P.POLICY_PATH, encoding="utf-8"))
    doc["sme_exceptions_enabled"] = False; doc["overridable_conditions"]["AUDIT_WRITE_FAILURE"] = True
    path = tmp_path / "p.json"; path.write_text(json.dumps(doc))
    with pytest.raises(P.PolicyError) as e: P.load_policy(str(path))
    assert e.value.code == "SME_POLICY_HASH_MISMATCH"
    doc["content_sha256"] = P.policy_hash(doc); path.write_text(json.dumps(doc))
    off = P.load_policy(str(path))
    assert not off.allowed("override_rule_conflict", ["SME_REVIEWER"])[0]   # master switch
    assert off.allowed("correct_site_fact", ["SME_REVIEWER"])[0]            # normal corrections still allowed
    assert not off.condition_overridable("AUDIT_WRITE_FAILURE")             # hard-coded never overridable


def test_reserved_profiles_disabled():
    from tcp_planner.review.assistant.core.profile import load_profile
    assert load_profile("sme_review")["prompt_version"]
    for name in ("tcp_knowledge", "document_revision"):
        with pytest.raises(Exception) as e: load_profile(name)
        assert e.value.code == "PROFILE_DISABLED"


def test_tool_registry_allow_list_permission_and_audit_fail_closed(aenv):
    from tcp_planner.review.assistant.core.tools import Tool, ToolContext, ToolRegistry
    from tcp_planner.review.assistant.core.identity import Identity
    from tcp_planner.review.assistant.core.audit import AuditService
    from tcp_planner.review.assistant.core.errors import AssistantError
    reg = ToolRegistry(); ran = []
    reg.register(Tool("create_change_set", lambda ctx, **k: ran.append(1) or {"ok": 1}, permission="changeset:create", mutates=True))
    prof = {"allowed_tools": ["create_change_set"], "max_authorized_actions_per_conversation": 10}
    audit = AuditService(str(aenv / "ad2"))
    sme = Identity(subject_id="s", roles=["SME_REVIEWER"]); aud = Identity(subject_id="a", roles=["AUDITOR"])
    assert reg.invoke(ToolContext(sme, prof, audit), "create_change_set") == {"ok": 1}
    with pytest.raises(AssistantError) as e: reg.invoke(ToolContext(aud, prof, audit), "create_change_set")
    assert e.value.code == "AUTHZ_DENIED"
    with pytest.raises(AssistantError) as e: reg.invoke(ToolContext(sme, {"allowed_tools": []}, audit), "create_change_set")
    assert e.value.code == "TOOL_NOT_ALLOWED"
    class Broken(AuditService):
        def write(self, *a, **k): raise AssistantError("AUDIT_WRITE_FAILED", "x", 500)
    ran.clear()
    with pytest.raises(AssistantError) as e: reg.invoke(ToolContext(sme, prof, Broken(str(aenv))), "create_change_set")
    assert e.value.code == "AUDIT_WRITE_FAILED" and ran == []   # mutating tool never ran
    evs = audit.read()
    assert any(ev["event_type"] == "TOOL_INVOCATION" and ev["tool_name"] == "create_change_set" for ev in evs)


def test_server_mount_disabled_and_existing_routes_unaffected(tmp_path, monkeypatch):
    import threading, urllib.request
    from tcp_planner.web_api import server
    monkeypatch.setenv("TCP_SME_ASSISTANT_ENABLED", "false")
    monkeypatch.setenv("TCP_UI_RUNS_DIR", str(tmp_path))
    srv = server.make_server(0); port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        def get(p):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{p}") as r: return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
        assert get("/api/assistant/status") == (200, {"enabled": False, "state": "DISABLED"})
        assert get("/api/assistant/identities")[0] == 404
        assert get("/api/runs") == (200, [])
    finally:
        srv.shutdown(); srv.server_close()


def test_audit_chain_valid_with_concurrent_processes(tmp_path):
    """Two server processes writing the same conversation stream must still produce one valid hash chain."""
    import subprocess, sys, textwrap
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    code = textwrap.dedent(f"""
        import sys; sys.path[:0] = [{root!r}, {os.path.join(root, 'src')!r}]
        from tcp_planner.review.assistant.core.audit import AuditService
        a = AuditService({str(tmp_path)!r})
        for i in range(40): a.write("PING", stream="conv-shared", n=i, writer=sys.argv[1])
    """)
    procs = [subprocess.Popen([sys.executable, "-c", code, w]) for w in ("A", "B")]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    from tcp_planner.review.assistant.core.audit import AuditService
    evs = AuditService(str(tmp_path)).read("conv-shared")
    assert len(evs) == 80 and {e["writer"] for e in evs} == {"A", "B"}
    assert AuditService.verify_chain(evs)
    assert all(e["event_type"] == "PING" for e in AuditService(str(tmp_path)).read())   # .lock files are not read
