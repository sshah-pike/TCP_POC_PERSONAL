"""Backend authorization: role -> permissions. The UI only mirrors this; every route checks here."""
from .errors import forbidden

ROLE_PERMISSIONS = {
    "SME_REVIEWER": {"review:read", "review:decide", "changeset:create", "changeset:confirm", "exception:confirm",
                     "pipeline:resume", "message:submit", "artifact:read"},
    "AUDITOR": {"review:read", "audit:read", "artifact:read"},
    "ADMIN": {"review:read", "audit:read", "artifact:read", "config:read"},
}


def permissions(identity):
    out = set()
    for r in identity.roles: out |= ROLE_PERMISSIONS.get(r, set())
    return out


def has(identity, permission):
    return permission in permissions(identity)


def require(identity, permission):
    if not has(identity, permission): raise forbidden(permission)
    return permission
