"""Approved rule-pack loader. Fails closed; contains no regulatory values of its own."""
import json, os
from tcp_planner.config.settings import RULE_PACK_DIR
from tcp_planner.contracts import RulePackError, canonical_json, sha256_hex, deep_copy

EXPECTED_STATUS = "APPROVED_FOR_POC"
EXPECTED_TA = "TA-1"
DEFAULT_FILENAME = "APPROVED_TWO_LANE_POC_RULE_PACK.json"

SECTIONS = (
    ("01_eligibility_rules", "01 Eligibility Rules"),
    ("02_road_work_classification", "02 Road / Work Classification"),
    ("03_typical_application_selection", "03 Typical Application Selection"),
    ("04_sign_catalog", "04 Sign Catalog"),
    ("05_sign_selection_rules", "05 Sign Selection Rules"),
    ("06_advance_warning_spacing_tables", "06 Advance-Warning Spacing Tables"),
    ("07_taper_formulas", "07 Taper Formulas"),
    ("08_buffer_tables", "08 Buffer Tables"),
    ("09_channelizing_device_rules", "09 Channelizing-Device Rules"),
    ("10_lane_width_rules", "10 Lane-Width Rules"),
    ("11_work_vehicle_rules", "11 Work-Vehicle Rules"),
    ("12_sign_placement_rules", "12 Sign Placement Rules"),
    ("13_station_offset_formulas", "13 Station / Offset Formulas"),
    ("14_orientation_rules", "14 Orientation Rules"),
    ("15_work_zone_geometry", "15 Work-Zone Geometry"),
    ("16_termination_rules", "16 Termination Rules"),
    ("17_exceptions_optional_devices", "17 Exceptions / Optional Devices"),
    ("18_validation_rules", "18 Validation Rules"),
    ("19_dwt_block_mapping", "19 DWT Block Mapping"),
)
SECTION_TITLES = dict(SECTIONS)


def default_path():
    return os.environ.get("TCP_RULE_PACK") or os.path.join(RULE_PACK_DIR, DEFAULT_FILENAME)


def compute_content_hash(doc):
    """SHA-256 of canonical JSON (sorted keys, compact) with rule_pack.content_sha256 removed."""
    d = deep_copy(doc); d.get("rule_pack", {}).pop("content_sha256", None)
    return sha256_hex(json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _need(cond, code, msg, **details):
    if not cond: raise RulePackError(code, msg, details)


class RulePack:
    def __init__(self, doc, path):
        self.doc = doc; self.path = path
        meta = doc["rule_pack"]
        self.id = meta["id"]; self.version = meta["version"]; self.hash = meta["content_sha256"]
        self.status = meta["status"]

    def section(self, key):
        _need(key in self.doc, "RULE_PACK_SECTION_MISSING", f"section {key} missing", section=key)
        return self.doc[key]

    @property
    def ref(self):
        return {"id": self.id, "version": self.version, "hash": self.hash}

    # ----- lookups used by the engine and validators -----
    def selected_ta(self):
        return self.section("03_typical_application_selection")["selected_ta"]

    def spacing_row(self, road_type):
        tbl = self.section("06_advance_warning_spacing_tables")
        rows = [row for row in tbl["values"] if row.get("road_type") == road_type]
        _need(len(rows) == 1, "RULE_PACK_TABLE_ROW_MISSING",
              f"Table {tbl.get('table')} has no unique row for road type {road_type}", road_type=road_type)
        return tbl["table"], tbl["units"], rows[0]

    def spacing_value_ft(self, road_type, dimension):
        table, units, row = self.spacing_row(road_type)
        _need(units == "ft", "RULE_PACK_UNITS_UNSUPPORTED", f"Table {table} units {units} not supported")
        v = row.get(dimension)
        _need(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0, "RULE_PACK_VALUE_MISSING",
              f"Table {table} dimension {dimension} missing for {road_type}", road_type=road_type, dimension=dimension)
        return table, float(v)

    def road_types(self):
        return [row["road_type"] for row in self.section("06_advance_warning_spacing_tables")["values"]]

    def sign(self, code):
        cat = self.section("04_sign_catalog")
        _need(code in cat, "RULE_PACK_SIGN_MISSING", f"sign {code} not in approved catalog", sign=code)
        return cat[code]

    def dwt_block(self, key):
        blocks = self.section("19_dwt_block_mapping")["blocks"]
        _need(key in blocks, "RULE_PACK_DWT_BLOCK_MAPPING_MISSING", f"no DWT block mapping for {key}", key=key)
        return blocks[key]

    def dwt_layer(self, key):
        layers = self.section("19_dwt_block_mapping")["layers"]
        _need(key in layers, "RULE_PACK_DWT_LAYER_MAPPING_MISSING", f"no DWT layer mapping for {key}", key=key)
        return layers[key]

    def validation_rule_ids(self):
        return [v["id"] for v in self.section("18_validation_rules")]

    def ta1_template(self):
        """The approved TA-1 template, assembled only from rule-pack content."""
        sel = self.section("03_typical_application_selection")
        zone = self.section("15_work_zone_geometry")
        return {
            "id": sel["selected_ta"], "version": self.version, "figure": sel.get("figure"), "title": sel.get("title"),
            "selection_conditions": sel["selection_conditions"],
            "default_advance_sign": "W20-1",
            "advance_sign_spacing_dimension": "A",
            "active_areas": sorted(k for k, v in zone["areas"].items() if v.get("active")),
            "taper_active": bool(self.section("07_taper_formulas")["active_for_selected_TA"]),
            "buffer_active": bool(self.section("08_buffer_tables")["active_for_selected_TA"]),
            "channelizing_required": bool(self.section("09_channelizing_device_rules")["selected_TA"]["required"]),
            "termination_sign_required": bool(self.section("16_termination_rules")["selected_TA"]["termination_sign_required"]),
            "changes_lane_width": bool(self.section("10_lane_width_rules")["selected_TA_changes_lane_width"]),
            "source_rule_pack": self.ref,
        }


def load_rule_pack(path=None):
    path = path or default_path()
    _need(os.path.isfile(path), "RULE_PACK_MISSING", f"approved rule pack not found: {os.path.basename(path)}")
    try:
        with open(path, "rb") as f: doc = json.loads(f.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise RulePackError("RULE_PACK_PARSE_FAILED", f"rule pack is not valid JSON: {e}")
    _need(isinstance(doc, dict) and isinstance(doc.get("rule_pack"), dict), "RULE_PACK_SECTION_MISSING",
          "rule_pack header missing")
    meta = doc["rule_pack"]
    for k in ("id", "version", "status", "content_sha256"):
        _need(meta.get(k), "RULE_PACK_HEADER_INCOMPLETE", f"rule_pack.{k} missing", field=k)
    _need(meta["status"] == EXPECTED_STATUS, "RULE_PACK_NOT_APPROVED",
          f"status {meta['status']!r} is not {EXPECTED_STATUS}")
    actual = compute_content_hash(doc)
    _need(actual == meta["content_sha256"], "RULE_PACK_HASH_MISMATCH", "content hash validation failed",
          expected=meta["content_sha256"], actual=actual)
    missing = [k for k, _ in SECTIONS if k not in doc]
    _need(not missing, "RULE_PACK_SECTION_MISSING", "required sections missing", sections=missing)
    pack = RulePack(doc, path)
    _validate_references(pack)
    return pack


def _validate_references(pack):
    """Every table, rule, sign and mapping the POC consumes must exist."""
    _need(pack.selected_ta() == EXPECTED_TA, "RULE_PACK_TA_NOT_SUPPORTED",
          f"selected TA {pack.selected_ta()} is not {EXPECTED_TA}")
    elig = pack.section("01_eligibility_rules")
    _need(elig.get("all_required"), "RULE_PACK_RULE_MISSING", "no eligibility conditions")
    for c in elig["all_required"]:
        _need({"field", "operator", "value"} <= set(c), "RULE_PACK_RULE_MISSING", "malformed eligibility rule")
    tbl = pack.section("06_advance_warning_spacing_tables")
    _need(tbl.get("table") and tbl.get("values"), "RULE_PACK_TABLE_MISSING", "Table 6B-1 missing")
    pack.sign("W20-1")
    for rule in pack.section("05_sign_selection_rules"):
        _need(rule.get("id") and rule.get("action") is not None, "RULE_PACK_RULE_MISSING", "malformed sign rule")
        act = rule["action"]
        for code in [act.get("replace"), act.get("with")] + [k for k in act if k in pack.section("04_sign_catalog")]:
            if code: pack.sign(code)
    for code in pack.section("12_sign_placement_rules"):
        if code != "sign_support": pack.sign(code)
    for code in pack.section("04_sign_catalog"):
        pack.dwt_block(code)
    pack.dwt_block("WORK_LOCATION")
    for layer in ("signs", "work_area", "road_centerline", "road_edges", "aerial"):
        pack.dwt_layer(layer)
    ids = pack.validation_rule_ids()
    for vid in ("VAL-ELIGIBILITY", "VAL-TA", "VAL-SIGN", "VAL-SPACING", "VAL-LANE", "VAL-PED", "VAL-CONFLICT", "VAL-TRACE"):
        _need(vid in ids, "RULE_PACK_RULE_MISSING", f"validation rule {vid} missing", rule=vid)
    for k in ("13_station_offset_formulas", "14_orientation_rules"):
        _need(pack.section(k).get("regulatory_status") == "IMPLEMENTATION_GEOMETRY_NOT_MUTCD_VALUE",
              "RULE_PACK_RULE_MISSING", f"{k} must be marked as implementation geometry")
