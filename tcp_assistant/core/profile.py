"""Assistant profile registry (common backend; one profile per assistant)."""
import json, os

from ..flags import CONFIG_DIR
from .errors import AssistantError

PROFILES_PATH = os.path.join(CONFIG_DIR, "assistant_profiles.json")


def load_profile(name="sme_review"):
    try:
        with open(PROFILES_PATH, encoding="utf-8") as f: doc = json.load(f)
    except (OSError, ValueError):
        raise AssistantError("PROFILE_UNAVAILABLE", "Assistant profile configuration cannot be read.", 500, False)
    p = (doc.get("profiles") or {}).get(name)
    if not p or p.get("enabled") is not True or p.get("reserved"):
        raise AssistantError("PROFILE_DISABLED", f"Assistant profile {name!r} is not available.", 404, False)
    return {"name": name, **p}


def public_profiles():
    try:
        with open(PROFILES_PATH, encoding="utf-8") as f: doc = json.load(f)
    except (OSError, ValueError):
        return []
    return [{"name": k, "display_name": v.get("display_name"), "enabled": v.get("enabled") is True and not v.get("reserved"),
             "version": v.get("version")} for k, v in (doc.get("profiles") or {}).items()]
