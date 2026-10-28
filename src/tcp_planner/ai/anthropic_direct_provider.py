"""Anthropic (Claude) implementation of VisionProvider. The only module that imports `anthropic`."""
import base64, io, json, os
from tcp_planner.contracts import ProviderError
from .vision_provider import VisionProvider, SYSTEM_PROMPT, build_prompt, api_schema, validate_observation

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicVisionProvider(VisionProvider):
    name = "anthropic"

    def __init__(self, model=None):
        # ANTHROPIC_MODEL is the documented setting; TCP_MODEL is honoured for older .env files.
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or os.environ.get("TCP_MODEL") or DEFAULT_MODEL
        self.effort = os.environ.get("TCP_AI_EFFORT", "high")
        # Server-side refusal fallback (on by default); set TCP_AI_FALLBACKS=off to disable.
        self.fallbacks = os.environ.get("TCP_AI_FALLBACKS", "default").strip().lower() != "off"

    def analyze(self, image, context):
        try:
            import anthropic
        except ImportError:
            raise ProviderError("AI_SDK_MISSING", "pip install anthropic")
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise ProviderError("AI_CREDENTIALS_MISSING", "set ANTHROPIC_API_KEY")
        buf = io.BytesIO(); image.save(buf, "JPEG", quality=88)
        kwargs = dict(
            model=self.model, max_tokens=16000, system=SYSTEM_PROMPT,
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": api_schema()}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(buf.getvalue()).decode()}},
                {"type": "text", "text": build_prompt(context)}]}])
        client = anthropic.Anthropic()
        try:
            if self.fallbacks:
                resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.AuthenticationError:
            raise ProviderError("AI_AUTH_FAILED", "Anthropic authentication failed")
        except anthropic.NotFoundError:
            raise ProviderError("AI_MODEL_NOT_FOUND", f"model {self.model!r} not available")
        except anthropic.RateLimitError:
            raise ProviderError("AI_RATE_LIMITED", "Anthropic rate limit")
        except anthropic.BadRequestError as e:
            msg = getattr(e, "message", "bad request")
            if "credit balance" in msg.lower():
                raise ProviderError("AI_CREDIT_BALANCE_TOO_LOW", "Anthropic account has insufficient credits")
            raise ProviderError("AI_BAD_REQUEST", msg[:300])
        except anthropic.APIStatusError as e:
            raise ProviderError("AI_API_ERROR", f"HTTP {e.status_code}")
        except anthropic.APIConnectionError:
            raise ProviderError("AI_CONNECTION_FAILED", "could not reach Anthropic")
        if resp.stop_reason == "refusal":
            raise ProviderError("AI_REFUSAL", "model declined the request")
        if resp.stop_reason == "max_tokens":
            raise ProviderError("AI_TRUNCATED", "response hit max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if not text: raise ProviderError("AI_EMPTY_RESPONSE", "no text block returned")
        try: obs = json.loads(text)
        except ValueError: raise ProviderError("AI_SCHEMA_INVALID", "response is not JSON")
        return {"observation": validate_observation(obs), "provider": self.name, "model": resp.model,
                "request_id": getattr(resp, "_request_id", None)}
