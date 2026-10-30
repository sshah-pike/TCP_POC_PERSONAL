"""Reader for config/site_understanding.json (S6 settings; every value carries a source or CALIBRATION_PENDING)."""
import json, os
from tcp_planner.config.settings import CONFIG_DIR

PATH = os.path.join(CONFIG_DIR, "site_understanding.json")


def load_site_config(path=None):
    with open(path or PATH, encoding="utf-8") as f: return json.load(f)


def call1_setting(name, cfg=None):
    """Value of a call 1 setting; None while the entry is CALIBRATION_PENDING."""
    entry = (cfg or load_site_config())["call1"][name]
    return None if entry.get("source") == "CALIBRATION_PENDING" else entry["value"]
