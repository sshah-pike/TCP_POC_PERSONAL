"""Rule pack v1 validator: ids, references, units, sources and the no-unsourced-number rule. Holds no values itself.

`validate(pack)` checks structure and sources. With `page_texts` (the cited-page snapshot) it also checks that every
quote is on its cited page, and with `figure_renders` that every figure render is the recorded file.
"""
import re, unicodedata
from dataclasses import dataclass, field
from tcp_planner.rules.rule_pack_models import METADATA_NUMBERS, Evidence, Layer, Status, expr_fields, expr_numbers

PART_LAYER_BY_DIR = {"base": Layer.FEDERAL, "ta": Layer.FEDERAL, "jurisdiction": Layer.JURISDICTION,
                     "client": Layer.CLIENT, "deviation": Layer.DEVIATION}
_NUM_IN_EXPR = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def normalize_text(text):
    """Same normalisation as the cited-page snapshot: NFKC, U+2010/U+2011 -> '-', whitespace runs -> one space."""
    t = unicodedata.normalize("NFKC", text).replace("‐", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", t).strip()


def number_in_text(n, text):
    """True when the number is written in the text, as printed: 2640 matches '2,640' or '2640'; 0.33 matches '0.33'."""
    if isinstance(n, float) and n.is_integer(): n = int(n)
    forms = {f"{n:,}", str(n)} if isinstance(n, int) else {str(n)}
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)", text) for f in forms)


@dataclass
class Report:
    errors: list = field(default_factory=list)
    unsourced: list = field(default_factory=list)        # {id, table, status, question}: each becomes an SME question
    interpretations: list = field(default_factory=list)  # {id, table, interpretation}: owner-approved readings

    @property
    def ok(self): return not self.errors


def _numbers(obj, path=""):
    """(dotted path, number) for every numeric leaf; bools excluded."""
    if isinstance(obj, bool) or obj is None: return []
    if isinstance(obj, (int, float)): return [(path, obj)]
    if isinstance(obj, dict): return [x for k, v in obj.items() for x in _numbers(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, (list, tuple)): return [x for v in obj for x in _numbers(v, path)]
    return []


def _expressions(table, rec):
    """Every condition expression a record carries."""
    out = []
    if table == "eligibility_condition" and rec.expr is not None: out.append(rec.expr)
    if table == "rule" and rec.condition is not None: out.append(rec.condition)
    if table == "formula": out += [c.when for c in rec.cases]
    if table == "deviation": out.append(rec.conditions)
    return out


def _record_numbers(table, rec):
    """Regulatory numbers in a record: numeric leaves outside conditions and metadata, plus condition and formula literals."""
    data = rec.model_dump(by_alias=True, exclude={"expr", "condition", "cases", "conditions"})
    nums = [n for p, n in _numbers(data) if (table, p) not in METADATA_NUMBERS]
    nums += [n for e in _expressions(table, rec) for n in expr_numbers(e)]
    if table == "formula":
        for c in rec.cases:
            nums += [float(x) if "." in x else int(x) for x in _NUM_IN_EXPR.findall(c.expression)]
    return nums


def _evidence_texts(pack, rec):
    texts = []
    for sid in getattr(rec, "source_ref_ids", []) or []:
        ref = pack.by_id.get(sid)
        if ref is None or not hasattr(ref, "evidence"): continue
        texts.append(ref.quote if ref.evidence == Evidence.QUOTE else ref.transcription)
    return texts


def _number_sourced(n, texts):
    if any(number_in_text(n, t) for t in texts): return True
    return n == 2 and any("squared" in t for t in texts)   # "WS squared" is the exponent 2 in Table 6B-4


def validate(pack, page_texts=None, figure_renders=None):
    """Check a loaded pack (see rule_pack_store.RulePack). Returns a Report; never raises for content problems."""
    r = Report(); err = r.errors.append
    seen = {}
    for table, rec in pack.all_records():
        if rec.id in seen: err(f"duplicate id {rec.id} in {table} and {seen[rec.id]}")
        seen[rec.id] = table

    def ref(rid, want, owner):
        if seen.get(rid) != want: err(f"{owner}: {want} {rid!r} does not exist")

    fields = {rec.id for rec in pack.records("registry_field")}
    scope = set(pack.manifest.ta_scope)
    for part_path, layer, table, rec in pack.located_records():
        owner = f"{table} {rec.id}"
        top = part_path.split("/")[0]
        if PART_LAYER_BY_DIR.get(top) != layer: err(f"{part_path}: layer {layer.value} does not match folder {top}/")
        if table == "rule" and rec.layer != layer: err(f"{owner}: layer {rec.layer.value} differs from its part's")
        for sid in getattr(rec, "source_ref_ids", []) or []: ref(sid, "source_ref", owner)
        if table == "source_ref": ref(rec.source_document_id, "source_document", owner)
        if table == "ta" and rec.id not in scope: err(f"{owner}: not in the pack's ta_scope {sorted(scope)}")
        if getattr(rec, "ta_id", None) is not None: ref(rec.ta_id, "ta", owner)
        if table == "ta_device_use": ref(rec.device_id, "device", owner)
        if table == "deviation": ref(rec.rule_id, "rule", owner)
        if table == "table_row":
            ref(rec.table_def_id, "table_def", owner)
            td = pack.by_id.get(rec.table_def_id)
            if td is not None and seen.get(rec.table_def_id) == "table_def":
                if set(rec.key) != set(td.key_fields): err(f"{owner}: key fields {sorted(rec.key)} != {sorted(td.key_fields)}")
                if set(rec.values) != set(td.value_fields): err(f"{owner}: value fields {sorted(rec.values)} != {sorted(td.value_fields)}")
        for e in _expressions(table, rec):
            for f in expr_fields(e):
                if f not in fields: err(f"{owner}: condition field {f!r} is not a registry_field")
        if table == "formula":
            for sym, f in rec.variables.items():
                if f not in fields: err(f"{owner}: variable {sym} binds to unknown registry_field {f!r}")

        # sources and numbers
        status = getattr(rec, "status", None)
        if status is not None and status != Status.SOURCED:
            r.unsourced.append({"id": rec.id, "table": table, "status": status.value, "question": rec.sme_question})
        if getattr(rec, "interpretation", None):
            r.interpretations.append({"id": rec.id, "table": table, "interpretation": rec.interpretation})
        nums = _record_numbers(table, rec)
        if nums:
            if status is not None and status != Status.SOURCED: err(f"{owner}: {status.value} record holds numbers {nums}")
            texts = _evidence_texts(pack, rec)
            if not texts: err(f"{owner}: numbers {nums} without any source_ref")
            missing = [n for n in nums if not _number_sourced(n, texts)]
            if missing and not getattr(rec, "interpretation", None):
                err(f"{owner}: numbers {missing} do not appear in the quote or transcription of its source_refs")

    for rec in pack.records("source_ref"):
        if page_texts is not None and rec.evidence == Evidence.QUOTE:
            page = page_texts.get((rec.source_document_id, rec.page_pdf))
            if page is None: err(f"source_ref {rec.id}: page {rec.page_pdf} of {rec.source_document_id} is not in the snapshot")
            else:
                if page["printed_page"] != rec.page_printed:
                    err(f"source_ref {rec.id}: printed page {rec.page_printed} but the snapshot says {page['printed_page']}")
                if normalize_text(rec.quote) not in page["text"]:
                    err(f"source_ref {rec.id}: quote not found on page {rec.page_printed}")
        if figure_renders is not None and rec.figure_render is not None:
            want = figure_renders.get(rec.figure_render.uri)
            if want is None or want["sha256"] != rec.figure_render.sha256:
                err(f"source_ref {rec.id}: figure render {rec.figure_render.uri} does not match the snapshot")
    return r
