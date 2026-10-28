"""SME_ACTION_POLICY loader (hash-verified, fail closed). Used by the assistant and, for revision runs, by the pipeline.

The policy governs which SME actions exist, which role may perform them and which are engineering exceptions. It never
changes a rule-pack value or a validator; it only decides whether a FAILED/blocked result may be accepted as a
plan-specific SME exception. Editing the file requires recomputing content_sha256:
    python -m tcp_planner.review.action_policy --rehash
"""
import json, os, sys

from tcp_planner.contracts import canonical_json, sha256_hex, TcpError
from tcp_planner.config.settings import CONFIG_DIR

POLICY_PATH = os.path.join(CONFIG_DIR, "assistant", "SME_ACTION_POLICY.json")
ACCEPTED_STATUS = ("POC_CONFIGURATION",)
ACTIONS = ("correct_site_fact", "confirm_site_fact", "mark_site_fact_unresolved", "reject_site_feature",
           "confirm_site_feature", "add_site_feature", "modify_site_feature", "move_existing_device",
           "add_approved_device", "add_unsupported_device", "remove_device", "create_taper", "create_buffer",
           "add_personnel_position", "override_rule_conflict", "proceed_without_applicable_ta", "request_new_analysis",
           "request_new_imagery", "proceed_outside_evidence_coverage")
CONDITIONS = ("NO_USABLE_GEOMETRY", "OUTSIDE_EVIDENCE_COVERAGE", "EVIDENCE_CORRUPT_OR_MISSING",
              "CHANGE_NOT_CALCULABLE", "AUDIT_WRITE_FAILURE", "VERSION_WRITE_FAILURE")
NEVER_OVERRIDABLE = ("NO_USABLE_GEOMETRY", "EVIDENCE_CORRUPT_OR_MISSING", "CHANGE_NOT_CALCULABLE",
                     "AUDIT_WRITE_FAILURE", "VERSION_WRITE_FAILURE")  # hard-coded: configuration cannot enable these


class PolicyError(TcpError): pass


def policy_hash(doc):
    return sha256_hex(canonical_json({k: v for k, v in doc.items() if k != "content_sha256"}))


class SmeActionPolicy:
    def __init__(self, doc, path):
        self.doc = doc; self.path = path; self.hash = doc["content_sha256"]
        self.id = doc["policy"]["id"]; self.version = doc["policy"]["version"]

    @property
    def ref(self):
        return {"id": self.id, "version": self.version, "sha256": self.hash}

    @property
    def exceptions_enabled(self):
        return self.doc.get("sme_exceptions_enabled") is True

    def action(self, name):
        return (self.doc.get("actions") or {}).get(name) or {}

    def is_exception(self, name):
        return self.action(name).get("is_exception") is True

    def allowed(self, name, roles):
        """(ok, reason). Exceptions additionally need the master switch."""
        a = self.action(name)
        if name not in ACTIONS or not a: return False, f"action {name} is not defined in the SME action policy"
        if a.get("enabled") is not True: return False, f"action {name} is disabled by the SME action policy"
        if a.get("is_exception") and not self.exceptions_enabled: return False, "SME exceptions are disabled (sme_exceptions_enabled=false)"
        if not set(roles or ()) & set(a.get("roles") or ()): return False, f"role not authorized for {name}"
        return True, None

    def reason_required(self, name):
        return self.action(name).get("reason_required") is True

    def condition_overridable(self, condition):
        if condition in NEVER_OVERRIDABLE: return False
        return (self.doc.get("overridable_conditions") or {}).get(condition) is True


def load_policy(path=None):
    path = path or os.environ.get("TCP_SME_ACTION_POLICY") or POLICY_PATH
    try:
        with open(path, encoding="utf-8") as f: doc = json.load(f)
    except (OSError, ValueError) as e:
        raise PolicyError("SME_POLICY_UNAVAILABLE", f"SME action policy cannot be read ({type(e).__name__})")
    if not isinstance(doc, dict) or not isinstance(doc.get("policy"), dict) or not doc.get("content_sha256"):
        raise PolicyError("SME_POLICY_INVALID", "SME action policy header missing")
    if doc["policy"].get("status") not in ACCEPTED_STATUS:
        raise PolicyError("SME_POLICY_NOT_ACCEPTED", f"policy status {doc['policy'].get('status')!r} not accepted")
    if policy_hash(doc) != doc["content_sha256"]:
        raise PolicyError("SME_POLICY_HASH_MISMATCH", "SME action policy content hash validation failed")
    unknown = sorted(set(doc.get("actions") or {}) - set(ACTIONS))
    if unknown: raise PolicyError("SME_POLICY_INVALID", f"unknown actions {unknown}")
    return SmeActionPolicy(doc, path)


def _rehash(path):
    with open(path, encoding="utf-8") as f: doc = json.load(f)
    doc["content_sha256"] = policy_hash(doc)
    with open(path, "w", encoding="utf-8") as f: json.dump(doc, f, indent=2, ensure_ascii=False); f.write("\n")
    return doc["content_sha256"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--rehash"]:
        print(_rehash(sys.argv[2] if len(sys.argv) > 2 else POLICY_PATH))
    else:
        p = load_policy(); print(f"{p.id} v{p.version} sha256 {p.hash} exceptions_enabled={p.exceptions_enabled}")
