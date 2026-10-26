import json

from .conftest import call, login
from .test_phase3_decisions import no_external  # noqa: F401
from .test_phase4_versions import inproc_launch, conv, review, confirm, out  # noqa: F401


def obj(t, cid, **p):
    return call("POST", f"conversations/{cid}/objects", p, token=t)


def exc(t, cid, chk, reason="SME engineering decision"):
    st, _, r = call("POST", f"conversations/{cid}/exceptions", {"type": "RULE_CONFLICT", "check_id": chk, "reason": reason,
                                                                "confirm_exception": True}, token=t)
    assert st == 200, r
    return r


def _stations(v):
    return {o["object_id"]: o["station_m"] for o in v["objects"]}


def test_create_s3_approved_sign_requires_rule_exceptions(aenv, runs, inproc_launch):
    t, cid = conv(runs, "supported")
    v = call("GET", f"conversations/{cid}", token=t)[2]
    s = _stations(v)
    st, _, r = obj(t, cid, object_id="S3", approval_class="APPROVED_CATALOG_DEVICE", category="SIGN", sign_code="W20-1",
                   approach="INCREASING_STATION", station_m=(s["S1"] + s["W1"]) / 2, side="RIGHT",
                   purpose="second advance warning sign", reason="sight distance at crest")
    assert st == 200, r
    assert r["object"]["unsupported_by_approved_catalog"] is False and r["object"]["policy_action"] == "add_approved_device"
    p = r["preview"]
    fails = sorted(x["check_id"] for x in p["rules"] if x["proposed"] == "FAIL")
    assert "VAL-SIGN" in fails and "VAL-PROHIBITED-OBJECTS" not in fails
    assert p["plan_outcome"]["status"] == "BLOCKED"
    for chk in fails: r = exc(t, cid, chk)
    assert r["preview"]["plan_outcome"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    rv = review(t, cid)
    assert rv["review"]["objects"]["proposed"][0]["object_id"] == "S3" and rv["review"]["objects"]["validation_coverage_gaps"]
    st, _, res = confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")
    child = res["resume_attempt"]["run_id"]
    call("GET", f"conversations/{cid}", token=t)
    plan = out(aenv, child, "plan.json")
    s3 = next(o for o in plan["objects"] if o["object_id"] == "S3")
    assert s3["object_type"] == "SIGN" and s3["sme"]["approval_class"] == "APPROVED_CATALOG_DEVICE"
    assert s3["generated_by"]["sme_proposed"] is True and s3["generated_by"]["rule_id"].startswith("SME_PROPOSED_OBJECT")
    val = out(aenv, child, "validation_results.json")
    assert next(c for c in val["rule_validation"]["checks"] if c["id"] == "VAL-SIGN")["status"] == "FAIL"


def test_unsupported_pcms_is_typed_exception_and_cannot_masquerade(aenv, runs, inproc_launch):
    t, cid = conv(runs, "supported")
    s = _stations(call("GET", f"conversations/{cid}", token=t)[2])
    base = dict(object_id="PCMS1", category="PCMS", station_m=s["S1"] - 20, side="RIGHT", reason="event traffic")
    st, _, r = obj(t, cid, approval_class="APPROVED_CATALOG_DEVICE", purpose="message", **base)
    assert st == 400 and r["error_code"] == "UNSUPPORTED_BY_APPROVED_CATALOG"
    st, _, r = obj(t, cid, approval_class="UNAPPROVED_KNOWN_DEVICE", purpose="message", **base)
    assert st == 400 and r["error_code"] == "UNSUPPORTED_NOT_CONFIRMED"
    st, _, r = obj(t, cid, approval_class="UNAPPROVED_KNOWN_DEVICE", confirm_unsupported=True, **base)
    assert st == 400 and r["error_code"] == "PURPOSE_REQUIRED"
    st, _, r = obj(t, cid, approval_class="UNAPPROVED_KNOWN_DEVICE", confirm_unsupported=True, purpose="advance event message", **base)
    assert st == 200, r
    assert r["object"]["unsupported_by_approved_catalog"] and r["object"]["policy_action"] == "add_unsupported_device"
    vp = next(x for x in r["preview"]["rules"] if x["check_id"] == "VAL-PROHIBITED-OBJECTS")
    assert vp["proposed"] == "FAIL" and vp["rule_status_proposed"] == "CONFLICT"
    d = next(x for x in r["preview"]["dispositions"]["dispositions"] if x["check_id"] == "VAL-PROHIBITED-OBJECTS")
    assert d["disposition"] == "ACCEPTED_WITH_SME_OVERRIDE"
    assert r["preview"]["plan_outcome"]["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    rv = review(t, cid)
    st, _, res = confirm(t, cid, rv, "CONFIRM_AND_REGENERATE")
    child = res["resume_attempt"]["run_id"]
    call("GET", f"conversations/{cid}", token=t)
    plan = out(aenv, child, "plan.json")
    pc = next(o for o in plan["objects"] if o["object_id"] == "PCMS1")
    assert pc["object_type"] == "SME_PROPOSED_OBJECT" and pc["sme"]["approval_class"] == "UNAPPROVED_KNOWN_DEVICE"
    assert pc["dwt_block"] is None and pc["generated_by"]["sme_proposed"] is True
    assert plan["status"] == "DRAFT_WITH_ENGINEERING_EXCEPTION"
    val = out(aenv, child, "validation_results.json")
    assert next(c for c in val["rule_validation"]["checks"] if c["id"] == "VAL-PROHIBITED-OBJECTS")["status"] == "FAIL"


def test_taper_zone_cones_in_lane_and_personnel(aenv, runs, no_external):
    t, cid = conv(runs, "supported")
    s = _stations(call("GET", f"conversations/{cid}", token=t)[2])
    st, _, r = obj(t, cid, object_id="TAPER1", approval_class="GEOMETRY_ZONE", category="TAPER", station_m=s["W1"] - 40,
                   end_station_m=s["W1"] - 10, side="LEFT", offset_from_centerline_m=1.0, purpose="shoulder taper",
                   confirm_unsupported=True, reason="equipment staging")
    assert st == 200, r
    assert r["object"]["policy_action"] == "create_taper"
    fails = {x["check_id"] for x in r["preview"]["rules"] if x["proposed"] == "FAIL"}
    assert {"VAL-PROHIBITED-OBJECTS", "GEO-TRAVELED-WAY"} <= fails                      # inside the traveled way
    assert r["preview"]["plan_outcome"]["status"] == "BLOCKED"                        # lane conflict needs its own exception
    st, _, r = obj(t, cid, object_id="FLAG1", approval_class="PERSONNEL_POSITION", category="FLAGGER", station_m=s["W1"] + 30,
                   side="RIGHT", purpose="flagger for trucks", confirm_unsupported=True, reason="truck access")
    assert st == 200 and r["object"]["policy_action"] == "add_personnel_position"
    st, _, r = obj(t, cid, object_id="S1", approval_class="SME_DEFINED_OBJECT", category="OTHER", station_m=10, side="RIGHT",
                   purpose="x", confirm_unsupported=True, reason="x")
    assert st == 400 and r["error_code"] == "OBJECT_EXISTS"
    st, _, r = obj(t, cid, object_id="BUF1", approval_class="GEOMETRY_ZONE", category="BUFFER", station_m=s["W1"], side="RIGHT",
                   purpose="buffer", confirm_unsupported=True, reason="x")
    assert st == 400 and r["error_code"] == "POSITION_REQUIRED"                     # zone needs an end station
    st, _, r = obj(t, cid, object_id="CONE9", approval_class="UNAPPROVED_KNOWN_DEVICE", category="CONE", station_m=99999,
                   side="RIGHT", purpose="x", confirm_unsupported=True, reason="x")
    assert st == 409 and r["error_code"] == "OUTSIDE_EVIDENCE_COVERAGE"


def test_policy_can_disable_object_types_and_removal(aenv, runs, tmp_path, monkeypatch, no_external):
    from tcp_poc import sme_policy as P
    doc = json.load(open(P.POLICY_PATH, encoding="utf-8")); doc["actions"]["create_taper"]["enabled"] = False
    doc["content_sha256"] = P.policy_hash(doc); pth = tmp_path / "pol.json"; pth.write_text(json.dumps(doc))
    monkeypatch.setenv("TCP_SME_ACTION_POLICY", str(pth))
    t, cid = conv(runs, "supported")
    s = _stations(call("GET", f"conversations/{cid}", token=t)[2])
    st, _, r = obj(t, cid, object_id="TAPER1", approval_class="GEOMETRY_ZONE", category="TAPER", station_m=s["W1"] - 40,
                   end_station_m=s["W1"] - 10, side="LEFT", purpose="x", confirm_unsupported=True, reason="x")
    assert st == 403 and r["error_code"] == "POLICY_DENIED"
    st, _, r = call("POST", f"conversations/{cid}/objects/remove", {"object_id": "W1", "reason": "x"}, token=t)
    assert st == 400 and r["error_code"] == "OBJECT_NOT_REMOVABLE"
    st, _, r = call("POST", f"conversations/{cid}/objects/remove", {"object_id": "S2", "reason": "single approach closed"}, token=t)
    assert st == 200 and any(x["check_id"] == "VAL-SIGN" and x["proposed"] == "FAIL" for x in r["preview"]["rules"])
    assert not any(row["object_id"] == "S2" and row["proposed"] for row in r["preview"]["placement"])
