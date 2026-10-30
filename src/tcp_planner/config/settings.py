"""Repository locations. Every data, config and asset path is resolved from the repository root here."""
import os

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/tcp_planner
SRC_DIR = os.path.dirname(PACKAGE_DIR)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
RULE_PACK_DIR = os.path.join(PROJECT_ROOT, "rule_pack")
PROMPTS_DIR = os.path.join(PROJECT_ROOT, "prompts")  # versioned AI prompts, one file each, hash in the header
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
SYMBOLS_DIR = os.path.join(ASSETS_DIR, "symbols")  # device catalog and symbol files; asset uris are relative to ASSETS_DIR
DEVICE_CATALOG_PATH = os.path.join(SYMBOLS_DIR, "device_catalog.json")
VAR_DIR =os.path.join(PROJECT_ROOT, "var")  # run outputs, labels, assistant data, debug dumps (gitignored)


def runs_dir():
    """The runs folder: the root of the artifact store, and the home of every run's own state files. Run records hold
    paths relative to this folder (D-77)."""
    return os.environ.get("TCP_UI_RUNS_DIR") or os.path.join(VAR_DIR, "runs")


# A state lock file older than this many seconds is stale (its owner died) and may be taken over (D-84, file state).
STATE_LOCK_STALE_S = float(os.environ.get("TCP_STATE_LOCK_STALE_S") or 30)
