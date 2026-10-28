"""SME revision input for revision runs (python -m tcp_planner.orchestration.pipeline ... --sme-revision PATH). Fails closed.

A revision is created by the SME Review Assistant after the SME confirmed a full change review. It carries the
cumulative SME decisions (overlay), and - from later phases - SME exceptions, placement adjustments and proposed
objects. It never carries rule-pack values. Verification:
  - TCP_SME_ASSISTANT_ENABLED must be true
  - schema + content_sha256 (canonical JSON without content_sha256)
  - approved rule pack id/version/hash identical to the loaded pack
  - SME action policy hash identical to the current verified policy
  - the machine site model rebuilt by this run must equal revision.machine_site_model_id (checked in app.py)
"""
import json, os

from tcp_planner.contracts import TcpError, canonical_json, sha256_hex

SCHEMA = "tcp-sme-revision-v1"
FLAG = "TCP_SME_ASSISTANT_ENABLED"
PLAN_STATUS_COMPLIANT = "DRAFT_COMPLIANT"
PLAN_STATUS_EXCEPTION = "DRAFT_WITH_ENGINEERING_EXCEPTION"


class SmeRevisionError(TcpError): pass


def revision_hash(doc):
    return sha256_hex(canonical_json({k: v for k, v in doc.items() if k != "content_sha256"}))


def enabled():
    return str(os.environ.get(FLAG) or "").strip().lower() in ("1", "true", "yes", "on")


def load(path, pack):
    if not enabled():
        raise SmeRevisionError("SME_ASSISTANT_DISABLED", f"--sme-revision requires {FLAG}=true")
    try:
        with open(path, encoding="utf-8") as f: doc = json.load(f)
    except (OSError, ValueError) as e:
        raise SmeRevisionError("SME_REVISION_INVALID", f"revision cannot be read ({type(e).__name__})")
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise SmeRevisionError("SME_REVISION_INVALID", "unknown revision schema")
    if doc.get("content_sha256") != revision_hash(doc):
        raise SmeRevisionError("SME_REVISION_HASH_MISMATCH", "revision content hash validation failed")
    rp = doc.get("rule_pack") or {}
    if (rp.get("id"), rp.get("version"), rp.get("hash")) != (pack.id, pack.version, pack.hash):
        raise SmeRevisionError("SME_REVISION_RULE_PACK_MISMATCH", "revision was reviewed against a different rule pack")
    from tcp_planner.review.action_policy import load_policy, PolicyError
    try:
        pol = load_policy()
    except PolicyError as e:
        raise SmeRevisionError(e.code, e.message)
    if (doc.get("policy") or {}).get("sha256") != pol.hash:
        raise SmeRevisionError("SME_REVISION_POLICY_MISMATCH", "SME action policy changed since the review")
    for k in ("machine_site_model_id", "decisions", "plan_version_id", "change_set_id"):
        if k not in doc: raise SmeRevisionError("SME_REVISION_INVALID", f"revision field {k} missing")
    doc["_policy"] = pol
    return doc


def plan_fields(revision):
    """Lineage block stored in plan.json of a revision run (part of the plan hash)."""
    return {k: revision.get(k) for k in ("revision_id", "plan_version_id", "parent_version_id", "change_set_id",
                                         "site_evidence_version", "content_sha256", "parent_run_id")}


def applied_record(revision):
    return {k: v for k, v in revision.items() if not k.startswith("_")}
