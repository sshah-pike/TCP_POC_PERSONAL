"""Proof that the existing tcp_observation request is byte-identical before and after the build_body() refactor (S6 STOP 1, point 3).

The golden file was produced by running the PRE-refactor foundry_provider.py (commit 3529192, the last commit before
`build_body` existed) with fixed inputs and capturing what its send() handed to the SDK (anthropic_messages) and to
requests.post (openai_responses). Both API families are checked, by build_body() and by the real send() path.
"""
import base64, hashlib, json, os

import pytest

from tcp_planner.ai import foundry_provider as fp
from tcp_planner.ai.vision_provider import SYSTEM_PROMPT

GOLDEN = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fixtures", "provider",
                      "tcp_observation_body_before_refactor.json")
G = json.load(open(GOLDEN, encoding="utf-8"))
I = G["inputs"]
PARTS = [(k, base64.b64decode(v) if k == "image" else v) for k, v in I["parts"]]


def _bytes(obj):
    """Compact JSON in insertion order: key order is part of "byte-identical"."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def test_golden_inputs_are_the_real_old_call():
    assert I["schema"] == fp.tri_state_schema()          # the old call's schema has not changed either
    assert I["system"] == SYSTEM_PROMPT


def test_anthropic_build_body_is_byte_identical():
    body = fp.AnthropicMessagesAPI.build_body(I["deployment"], I["effort"], PARTS, I["schema"], I["system"])
    assert _bytes(body) == _bytes(G["anthropic_messages"])
    assert list(body) == list(G["anthropic_messages"])    # same keyword arguments, same order


def test_openai_build_body_is_byte_identical():
    body = fp.OpenAIResponsesAPI.build_body(I["deployment"], I["effort"], PARTS, I["schema"], I["system"])
    assert _bytes(body) == _bytes(G["openai_responses"])
    assert list(body) == list(G["openai_responses"])
    assert body["text"]["format"]["name"] == "tcp_observation"


def test_anthropic_send_hands_the_sdk_the_same_arguments(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    seen = {}

    class Msgs:
        def create(self, **kw): seen.update(kw); raise anthropic.APIConnectionError(request=None)

    class Client:
        def __init__(self, **k): self.messages = Msgs()
    monkeypatch.setattr(anthropic, "AnthropicFoundry", Client)
    with pytest.raises(Exception): fp.AnthropicMessagesAPI().send("https://e", "k", I["deployment"], I["effort"], PARTS, I["schema"], system=I["system"])
    assert _bytes(seen) == _bytes(G["anthropic_messages"])


def test_openai_send_posts_the_same_body_to_the_same_url(monkeypatch):
    import requests
    seen = {}

    def post(url, json=None, **kw): seen.update(url=url, json=json); raise requests.RequestException()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(Exception): fp.OpenAIResponsesAPI().send("https://e", "k", I["deployment"], I["effort"], PARTS, I["schema"], system=I["system"])
    assert _bytes(seen["json"]) == _bytes(G["openai_responses"]) and seen["url"] == G["openai_url"]


def test_golden_file_itself_is_pinned():
    """A change to the golden file is a deliberate act: it needs this hash updated in the same commit."""
    raw = open(GOLDEN, "rb").read().replace(b"\r\n", b"\n")   # line endings do not count
    assert hashlib.sha256(raw).hexdigest() == PINNED


PINNED = "586c9e3c238ee69a9770811d7ce3db1eba4f6629cfab0eedc7a5b2272c91b0e9"
