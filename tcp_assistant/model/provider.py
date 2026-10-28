"""Text-model provider abstraction (model/deployment chosen by the assistant profile). No tools are ever offered to the
model; it returns one structured JSON object. CALLS counts every model request made by this process (tests use it to
prove structured actions make zero model calls)."""
import threading

CALLS = []
_LOCK = threading.Lock()


class ModelError(Exception):
    def __init__(self, code, message, usage=None):
        super().__init__(f"{code}: {message}"); self.code = code; self.message = message; self.usage = usage


class TextModelProvider:
    name = "abstract"
    deployment = None

    def complete_structured(self, system, user_text, schema, timeout_s):
        """-> {"text": raw JSON text, "model", "request_id", "usage"}; raises ModelError."""
        raise NotImplementedError


def record_call(provider, deployment):
    with _LOCK: CALLS.append({"provider": provider, "deployment": deployment})


_FACTORY = {"provider": None}


def set_factory(fn):
    """Tests inject a fake provider factory; None restores the configured Foundry provider."""
    _FACTORY["provider"] = fn


_ENV = {"done": False}


def _prepare_environment():
    """The UI server process does not load .env (only pipeline child processes do). Load it here exactly as the CLI
    does (os.environ.setdefault: real environment variables win) and use the OS trust store for TLS, once."""
    if _ENV["done"]: return
    from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
    load_env_file(); use_os_trust_store()
    _ENV["done"] = True


def get_provider(profile):
    if _FACTORY["provider"] is not None: return _FACTORY["provider"](profile)
    _prepare_environment()
    from .foundry_text import FoundryTextProvider
    return FoundryTextProvider(profile["model"].get("foundry_profile"))
