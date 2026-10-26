"""Identifiers. Record ids are unique (time + random); finding ids are stable (content-derived)."""
import datetime, re, secrets

from tcp_poc.models import sha256_hex

ID_RE = re.compile(r"^[a-z]{2,8}-[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")
STABLE_RE = re.compile(r"^[A-Z]{1,4}-[0-9A-F]{10}$")


def new_id(prefix):
    return f"{prefix}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(4)}"


def stable_id(prefix, *parts):
    return f"{prefix}-{sha256_hex('|'.join(str(p) for p in parts))[:10].upper()}"


def valid(any_id):
    return bool(ID_RE.match(any_id or "") or STABLE_RE.match(any_id or ""))
