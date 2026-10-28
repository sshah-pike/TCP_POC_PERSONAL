"""Feature flag and storage location. Reading the flag never creates assistant storage."""
import os

from tcp_planner.config import settings

FLAG = "TCP_SME_ASSISTANT_ENABLED"
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))  # package data: prompts/
PROJECT_ROOT = settings.PROJECT_ROOT
CONFIG_DIR = os.path.join(settings.CONFIG_DIR, "assistant")


def _env_file_value(key):
    """Value of ONE key from the project .env (the server never loads the rest of .env into its environment)."""
    path = os.path.join(PROJECT_ROOT, ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line: continue
                k, v = line.split("=", 1)
                if k.strip() == key: return v.split("#", 1)[0].strip().strip("\"'")
    except OSError:
        pass
    return None


def enabled():
    v = os.environ.get(FLAG)
    if v is None: v = _env_file_value(FLAG)
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def data_dir():
    return os.environ.get("TCP_ASSISTANT_DATA_DIR") or os.path.join(PROJECT_ROOT, "assistant_data")
