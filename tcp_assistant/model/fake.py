"""Deterministic fake text model for tests (records the exact request; never networks)."""
import json

from .provider import TextModelProvider, ModelError, record_call


class FakeTextProvider(TextModelProvider):
    name = "fake"
    deployment = "fake-deployment"
    REQUESTS = []

    def __init__(self, response=None, error=None, raw=None):
        self.response = response; self.error = error; self.raw = raw

    def complete_structured(self, system, user_text, schema, timeout_s):
        record_call(self.name, self.deployment)
        FakeTextProvider.REQUESTS.append({"system": system, "user": user_text, "schema": schema})
        if self.error: raise ModelError(self.error, "fake failure")
        text = self.raw if self.raw is not None else json.dumps(self.response)
        return {"text": text, "model": "fake-model", "request_id": "req-fake", "usage": {"input_tokens": 100, "output_tokens": 50}}
