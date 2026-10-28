"""Assistant errors: stable code, user-facing message, HTTP status, recoverability and deterministic next actions."""


class AssistantError(Exception):
    def __init__(self, code, message, status=400, recoverable=True, actions=None, details=None):
        super().__init__(f"{code}: {message}")
        self.code = code; self.message = message; self.status = status
        self.recoverable = recoverable; self.actions = list(actions or []); self.details = details or {}

    def to_dict(self):
        return {"error_code": self.code, "message": self.message, "recoverable": self.recoverable,
                "actions": self.actions, "details": self.details, "plan_unchanged": True}


def disabled():
    return AssistantError("ASSISTANT_DISABLED", "SME Review Assistant is disabled (TCP_SME_ASSISTANT_ENABLED=false).", 404,
                          recoverable=False)


def unauthenticated():
    return AssistantError("AUTH_SESSION_REQUIRED", "Select a local identity to start an SME review session.", 401)


def forbidden(permission):
    return AssistantError("AUTHZ_DENIED", f"Your role does not permit this action ({permission}).", 403, recoverable=False)


def not_found(what):
    return AssistantError("NOT_FOUND", f"{what} not found.", 404)
