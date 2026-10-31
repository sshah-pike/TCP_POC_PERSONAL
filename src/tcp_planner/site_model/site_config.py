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


def measurement_setting(name, cfg=None):
    """(value, flags) of a measurement setting. A CALIBRATION_PENDING value is returned with that flag, so every number
    computed from it can carry the flag (the value is a starting point, not a calibrated one)."""
    entry = (cfg or load_site_config())["measurement"][name]
    return entry["value"], (("CALIBRATION_PENDING",) if entry.get("source") == "CALIBRATION_PENDING" else ())


def lane_width_plausible_m():
    """[low, high] metres per lane, read (not copied) from config/pipeline_config.json fusion.lane_width_plausible_m."""
    with open(os.path.join(CONFIG_DIR, "pipeline_config.json"), encoding="utf-8") as f:
        return tuple(json.load(f)["fusion"]["lane_width_plausible_m"])


def default_setting(name, cfg=None):
    """(value, flags, optional) of a default in config 'defaults'. A value with source UNKNOWN is returned as None: it stays
    unknown until the SME supplies it for the job."""
    e = (cfg or load_site_config())["defaults"][name]
    if e.get("source") == "UNKNOWN": return None, ("SOURCE_REVIEW_REQUIRED",), bool(e.get("optional"))
    return e["value"], tuple(e.get("flags", ())), bool(e.get("optional"))


def setting(section, name, cfg=None):
    """(value, flags) of a setting in any section. A CALIBRATION_PENDING value is a starting value that is used and carries that
    flag, so every result computed from it can say so (same rule as `measurement_setting`)."""
    entry = (cfg or load_site_config())[section][name]
    return entry["value"], (("CALIBRATION_PENDING",) if entry.get("source") == "CALIBRATION_PENDING" else ())


def stage_on(name, cfg=None):
    """True when the stage is switched on in config `stages` (S6 step 10). An unknown stage name is an error, not a silent True."""
    return bool((cfg or load_site_config())["stages"][name]["value"])


FLOOR_KINDS = ("work_location", "safety_critical", "common")


def confidence_floor(kind, profile=None, cfg=None):
    """(floor or None, flags) for a kind of fact and a Foundry profile name: the profile's own entry when it has one, else the
    default entry. A floor of None applies no floor. A CALIBRATION_PENDING entry carries that flag."""
    if kind not in FLOOR_KINDS: raise ValueError(f"unknown floor kind {kind!r}")
    section = (cfg or load_site_config())["confidence_floors"]
    entry = ((section.get("profiles") or {}).get(profile) or {}).get(kind) if profile else None
    entry = entry or section["default"][kind]
    return entry["value"], (("CALIBRATION_PENDING",) if entry.get("source") == "CALIBRATION_PENDING" else ())
