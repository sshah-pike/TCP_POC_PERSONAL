"""Versioned message canonicalization and hashing.

tcp-msg-canon-v1:
  - text must be a str (the HTTP layer decodes UTF-8 strictly); encoded as UTF-8 for hashing
  - Unicode NFC normalization
  - line endings: CRLF and CR -> LF
  - outer whitespace stripped; inner whitespace preserved exactly (no collapsing)
  - message hash input: canonical JSON of {canon, conversation_id, message_id, created_at, text}
    created_at is assigned once by the server (UTC ISO-8601, milliseconds) and stored with the message
"""
import datetime, unicodedata

from tcp_poc.models import canonical_json, sha256_hex

CANON_VERSION = "tcp-msg-canon-v1"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def canonical_text(text):
    if not isinstance(text, str): raise TypeError("message text must be a string")
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return t.strip()


def message_hash(conversation_id, message_id, created_at, text):
    return sha256_hex(canonical_json({"canon": CANON_VERSION, "conversation_id": conversation_id,
                                      "message_id": message_id, "created_at": created_at,
                                      "text": canonical_text(text)}))


def obj_hash(obj):
    return sha256_hex(canonical_json(obj))
