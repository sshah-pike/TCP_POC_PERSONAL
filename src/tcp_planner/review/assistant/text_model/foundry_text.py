"""Microsoft Foundry text interpretation: reuses the existing Foundry connection, profile registry, API-family adapters
(tcp_planner.ai.foundry_provider.APIS, text parts only) and error classification. The key stays in the process environment and
is never placed in prompts, logs, audit records or responses."""
import threading

from tcp_planner.contracts import ProviderError, redact
from .provider import TextModelProvider, ModelError, record_call


class FoundryTextProvider(TextModelProvider):
    name = "foundry"

    def __init__(self, profile_name=None):
        from tcp_planner.ai import foundry_provider as fp
        doc = fp.load_profiles()
        self.profile = profile_name or doc.get("default_profile")
        p = (doc.get("profiles") or {}).get(self.profile)
        if not p or p.get("enabled", True) is False:
            raise ModelError("MODEL_PROFILE_UNAVAILABLE", f"Foundry profile {self.profile!r} is not available")
        self.deployment = fp._deployment(p); self.api = p.get("api"); self.effort = p.get("effort")
        self._fp = fp

    def complete_structured(self, system, user_text, schema, timeout_s):
        api = self._fp.APIS.get(self.api)
        if api is None: raise ModelError("MODEL_API_UNKNOWN", f"unknown Foundry API {self.api!r}")
        try:
            endpoint, key = self._fp.foundry_connection()
        except ProviderError as e:
            raise ModelError(e.code, e.message)
        box = {}

        def call():
            try: box["reply"] = api().send(endpoint, key, self.deployment, self.effort, [("text", user_text)], schema, system=system)
            except Exception as e: box["error"] = e
        record_call(self.name, self.deployment)
        t = threading.Thread(target=call, daemon=True); t.start(); t.join(timeout_s)
        if t.is_alive(): raise ModelError("MODEL_TIMEOUT", f"no response within {timeout_s} s")
        if "error" in box:
            e = box["error"]
            raise ModelError(getattr(e, "code", "MODEL_ERROR"), redact(getattr(e, "message", str(e)), 300),
                             (getattr(e, "details", None) or {}).get("usage"))
        rep = box["reply"]
        if rep.truncated: raise ModelError("MODEL_TRUNCATED", "response hit the output limit", rep.usage)
        return {"text": rep.text or "", "model": rep.model, "request_id": rep.request_id, "usage": rep.usage}
