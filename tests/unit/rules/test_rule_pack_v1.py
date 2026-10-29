"""Rule pack v1 as committed in rule_pack/: every quote is on its cited MUTCD page, every number is in its quote,
unsourced items are exactly the known list, and the formulas reproduce Table 6B-4 (S4 acceptance criteria)."""
import hashlib, json, os
import pytest
from tcp_planner.contracts import RulePackError
from tcp_planner.rules.rule_pack_eval import eval_expr, evaluate_formula
from tcp_planner.rules.rule_pack_store import NO_TA_MATCH, JsonRulePackStore
from tcp_planner.rules.rule_pack_validator import validate

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SNAPSHOT = os.path.join(ROOT, "tests", "fixtures", "rule_pack_sources", "cited_pages.json")
PACK_DIRS = ("base", "ta", "jurisdiction", "client")

# Every record that is not SOURCED. Adding one must be deliberate: it becomes an SME question.
EXPECTED_UNSOURCED = {
    "R-LOW-SPEED-CUTOFF": "SOURCE_REVIEW_REQUIRED",
    "R-6N11-TA33-UNDIVIDED-FOUR-LANE": "SOURCE_REVIEW_REQUIRED",
    "R-TMA-SPEED-THRESHOLD": "UNKNOWN",
    "R-DEFAULT-WORK-VEHICLE-WIDTH": "UNKNOWN",
    "R-DEFAULT-WORK-LENGTH-POLE": "UNKNOWN",
    "R-DEFAULT-WORK-LENGTH-MANHOLE": "UNKNOWN",
    "R-DEFAULT-WORK-LENGTH-EXCAVATION": "UNKNOWN",
    "R-DEFAULT-WORK-LENGTH-TRENCH": "UNKNOWN",
    "E-TA6-MINOR-ROAD": "SOURCE_REVIEW_REQUIRED",
    "R-TA10-SHORT-ZONE": "SOURCE_REVIEW_REQUIRED",
    "E-TA33-FORM-UNDIVIDED-6N11": "SOURCE_REVIEW_REQUIRED",
    "R-TA33-FIG-G20-2-500FT": "SOURCE_REVIEW_REQUIRED",
    "R-TA33-FIG-DOWNSTREAM-100FT": "SOURCE_REVIEW_REQUIRED",
}


@pytest.fixture(scope="module")
def pack():
    return JsonRulePackStore().load()


@pytest.fixture(scope="module")
def snapshot():
    with open(SNAPSHOT, encoding="utf-8") as f: return json.load(f)


def _page_texts(snap):
    return {(d["source_document_id"], p["pdf_page"]): p for d in snap["documents"] for p in d["pages"]}


def test_pack_validates_against_the_page_snapshot_and_figure_renders(pack, snapshot):
    renders = {e["artifact"]["uri"]: e["artifact"] for e in snapshot["figure_renders"]}
    rep = validate(pack, page_texts=_page_texts(snapshot), figure_renders=renders)
    assert rep.errors == []


def test_snapshot_and_figure_files_are_the_cited_documents(pack, snapshot):
    docs = {d.id: d.artifact for d in pack.records("source_document")}
    for d in snapshot["documents"]:
        assert docs[d["source_document_id"]].sha256 == d["artifact"]["sha256"]
    for e in snapshot["figure_renders"]:
        with open(os.path.join(ROOT, *e["artifact"]["uri"].split("/")), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == e["artifact"]["sha256"]


def test_source_pdf_on_disk_matches_the_recorded_sha256(pack):
    for d in pack.records("source_document"):
        p = os.path.join(ROOT, *d.artifact.uri.split("/"))
        if not os.path.isfile(p): pytest.skip(f"{d.artifact.uri} not present")
        with open(p, "rb") as f: assert hashlib.sha256(f.read()).hexdigest() == d.artifact.sha256


def test_every_part_file_on_disk_is_in_the_manifest(pack):
    listed = {p.path for p in pack.manifest.parts}
    on_disk = {f"{top}/{n}" for top in PACK_DIRS if os.path.isdir(os.path.join(ROOT, "rule_pack", top))
               for n in os.listdir(os.path.join(ROOT, "rule_pack", top)) if n.endswith(".json")}
    assert on_disk == listed


def test_stored_hash_is_the_recomputed_hash(pack):
    assert JsonRulePackStore().content_hash() == pack.hash and JsonRulePackStore().list_versions() == ["1.0.0"]


def test_unsourced_items_are_exactly_the_known_list(pack):
    rep = validate(pack)
    assert {u["id"]: u["status"] for u in rep.unsourced} == EXPECTED_UNSOURCED
    assert all(u["question"] for u in rep.unsourced)


def test_the_only_interpretations_are_the_proposed_6n11_reading_and_they_are_not_approved(pack):
    got = {(i["id"], i["status"]) for i in validate(pack).interpretations}
    assert got == {("R-6N11-TA33-UNDIVIDED-FOUR-LANE", "SOURCE_REVIEW_REQUIRED"),
                   ("E-TA33-FORM-UNDIVIDED-6N11", "SOURCE_REVIEW_REQUIRED")}


def test_scope_and_no_ta_match(pack):
    assert pack.manifest.ta_scope == ["TA-1", "TA-6", "TA-10", "TA-33"] and pack.manifest.status == "DRAFT"
    assert sorted(t.id for t in pack.records("ta")) == ["TA-1", "TA-10", "TA-33", "TA-6"]
    assert pack.ta("TA-2") == NO_TA_MATCH and pack.ta("TA-99") == NO_TA_MATCH and pack.ta("TA-10").figure == "6P-10"


def test_only_the_federal_layer_is_populated(pack):
    """S4 scope change: rules come from the MUTCD only. Jurisdiction, client and deviation layers stay empty."""
    assert {layer.value for _, layer, _, _ in pack.located_records()} == {"FEDERAL"}
    assert {p.layer.value for p in pack.manifest.parts} == {"FEDERAL"}
    assert pack.records("deviation") == []
    for top in ("jurisdiction", "client", "deviation"):
        d = os.path.join(ROOT, "rule_pack", top)
        assert not os.path.isdir(d) or not [n for n in os.listdir(d) if n.endswith(".json")]


# ---------- formulas (acceptance criteria) ----------
def test_table_6b4_at_25_mph_and_11_ft(pack):
    r = evaluate_formula(pack, "F-6B4-L", {"offset_width_ft": 11, "posted_speed_mph": 25})
    assert r["status"] == "SOURCED" and r["expression"] == "W*S**2/60" and r["unit"] == "ft"
    assert r["value"] == 11 * 25 ** 2 / 60 and r["value"] == pytest.approx(114.6, abs=0.05)   # not rounded


def test_table_6b4_at_45_mph_and_12_ft(pack):
    r = evaluate_formula(pack, "F-6B4-L", {"offset_width_ft": 12, "posted_speed_mph": 45})
    assert r["status"] == "SOURCED" and r["expression"] == "W*S" and r["value"] == 540


@pytest.mark.parametrize("speed", [41, 42, 43, 44, 44.9])
def test_speeds_between_the_6b4_bands_are_source_review_required(pack, speed):
    r = evaluate_formula(pack, "F-6B4-L", {"offset_width_ft": 12, "posted_speed_mph": speed})
    assert r["status"] == "SOURCE_REVIEW_REQUIRED" and r["value"] is None


def test_missing_input_is_unknown(pack):
    assert evaluate_formula(pack, "F-6B4-L", {"posted_speed_mph": 25})["status"] == "UNKNOWN"
    assert evaluate_formula(pack, "F-6B3-SHOULDER", {"offset_width_ft": 12, "posted_speed_mph": 42})["status"] == "SOURCE_REVIEW_REQUIRED"


def test_table_6b3_tapers_use_l(pack):
    facts = {"offset_width_ft": 12, "posted_speed_mph": 45}
    assert evaluate_formula(pack, "F-6B3-MERGING", facts)["value"] == 540
    assert evaluate_formula(pack, "F-6B3-SHIFTING", facts)["value"] == 0.5 * 540
    shoulder = evaluate_formula(pack, "F-6B3-SHOULDER", facts)
    assert shoulder["value"] == 0.33 * 540 and shoulder["qualifier"] == "AT_LEAST" and shoulder["inputs"]["L"]["value"] == 540


def test_cited_only_formulas_never_compute(pack):
    for fid in ("F-6B08-SHOULDER-THIRD", "F-6B08-SHIFTING-HALF"):
        with pytest.raises(RulePackError) as e: evaluate_formula(pack, fid, {"offset_width_ft": 12, "posted_speed_mph": 45})
        assert e.value.code == "RULE_PACK_FORMULA_CITED_ONLY"


def test_device_spacing_6k01(pack):
    assert evaluate_formula(pack, "F-6K01-TAPER-SPACING", {"posted_speed_mph": 30})["value"] == 30
    assert evaluate_formula(pack, "F-6K01-TANGENT-SPACING", {"posted_speed_mph": 30})["value"] == 60


# ---------- tables, rules, trace ----------
def test_tables_hold_every_printed_row(pack):
    rows = pack.records("table_row")
    assert {r.key["road_type"] for r in rows if r.table_def_id == "T-6B1"} == {"URBAN_LOW_SPEED", "URBAN_HIGH_SPEED", "RURAL", "EXPRESSWAY_FREEWAY"}
    assert sorted(r.key["speed_mph"] for r in rows if r.table_def_id == "T-6B2") == list(range(20, 80, 5))
    assert all(r.status.value == "SOURCED" and None not in r.values.values() for r in rows)


def test_nine_ft_option_stays_unknown_while_low_speed_has_no_source(pack):
    cond = pack.get("R-6N07-NINE-FT-OPTION").condition
    facts = {"duration": "SHORT_TERM", "traffic_volume": "LOW", "heavy_vehicles": False}
    assert eval_expr(cond, facts) is None
    assert eval_expr(cond, dict(facts, heavy_vehicles=True)) is False


def test_trace_names_table_section_page_and_pack(pack):
    t = pack.trace("T-6B2-25")
    assert t["pack_hash"] == pack.hash and t["pack_version"] == "1.0.0" and t["status"] == "SOURCED"
    assert t["source_refs"] == [{"source_ref_id": "SR-6B2-25", "source_document_id": "SD-MUTCD11-CH6-2023-12", "section": "6B.06",
                                 "paragraph": None, "table": "6B-2", "figure": None, "note": None, "page": "775",
                                 "strength": "OPTION", "evidence": "QUOTE"}]
