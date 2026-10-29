"""Page-text snapshot of every MUTCD page that rule pack v1 cites (S4; dev-time spike, never imported by src/).

Writes tests/fixtures/rule_pack_sources/cited_pages.json. Tests check rule-pack quotes against this snapshot, so
they need neither PyMuPDF nor the PDFs. Each document is pinned by sha256; a different file fails --check.

Usage:
  python spikes/rule_pack_extract/extract.py           write the snapshot
  python spikes/rule_pack_extract/extract.py --check   re-extract and compare with the committed snapshot

Normalisation (also applied to every quote in the pack): Unicode NFKC, the hyphen variants U+2010 and U+2011 become
"-", and every run of whitespace becomes one space. Nothing else is changed.
"""
import hashlib, json, os, re, sys, unicodedata
import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "tests", "fixtures", "rule_pack_sources", "cited_pages.json")
SCHEMA_VERSION = "1"

# key -> (repo-relative path, PDF page numbers (1-based) that the pack cites, why)
MUTCD = "docs/sources/CHAPTER 6 - DEC 2023 MUTCD REVISION.pdf"
DOCS = {
    "SD-MUTCD11-CH6-2023-12": (MUTCD, {
        9: "6B.06 paras 01-14 (buffer option para 11); Table 6B-1",
        11: "6B.06 para 15, 6B.07, 6B.08 paras 01-05; Tables 6B-2, 6B-3, 6B-4",
        12: "6B.08 paras 06-15 (shifting 1/2 L, shoulder 1/3 L, downstream and one-lane two-way tapers, ~20 ft spacing)",
        31: "6G.08 paras 01-02 (higher fines signs R2-10, R2-11)",
        33: "6G.08 paras 03-05 (DOUBLE FINES legends); 6G.10 (SIDEWALK CLOSED signs)",
        51: "6K.01 para 04 (device spacing 1 x and 2 x speed)",
        82: "6N.07 (10 ft remaining width, 9 ft option); 6N.08; 6N.09 para 07 (flaggers, Figure 6P-10)",
        83: "6N.10; 6N.11 (merging taper standard para 03; TA-33 on undivided or divided four-lane roads para 06)",
        93: "6P.01 paras 01-07 (strength of figure content, permitted deviations)",
        96: "Notes for Figure 6P-1 (TA-1)",
        97: "Figure 6P-1 drawing (labels are vector graphics, not text)",
        106: "Notes for Figure 6P-6 (TA-6)",
        107: "Figure 6P-6 drawing (labels are vector graphics, not text)",
        114: "Notes for Figure 6P-10 (TA-10)",
        115: "Figure 6P-10 drawing (labels are vector graphics, not text)",
        160: "Notes for Figure 6P-33 (TA-33)",
        161: "Figure 6P-33 drawing (labels are vector graphics, not text)",
    }),
}
# The reference TMP drafts are comparison material, not rule sources (S4 scope change), so they are not snapshotted.
FIGURE_PAGES = {97, 107, 115, 161}


def normalize(text):
    t = unicodedata.normalize("NFKC", text).replace("‐", "-").replace("‑", "-")
    return re.sub(r"\s+", " ", t).strip()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def build():
    docs = []
    for key, (rel, pages) in DOCS.items():
        path = os.path.join(ROOT, *rel.split("/"))
        pdf = pymupdf.open(path)
        out_pages = []
        for n, why in sorted(pages.items()):
            raw = pdf[n - 1].get_text("text")
            m = re.search(r"Page (\d{3})", raw)
            out_pages.append({"pdf_page": n, "printed_page": m.group(1) if m else None, "cited_for": why,
                              "figure_labels_in_text_layer": False if n in FIGURE_PAGES else None,
                              "text": normalize(raw)})
        docs.append({"source_document_id": key,
                     "artifact": {"uri": rel, "sha256": _sha256(path), "size": os.path.getsize(path),
                                  "media_type": "application/pdf"},
                     "page_count": pdf.page_count, "pages": out_pages})
    return {"schema_version": SCHEMA_VERSION, "generator": "spikes/rule_pack_extract/extract.py",
            "extractor": f"PyMuPDF {pymupdf.VersionBind}", "normalization": "NFKC; U+2010/U+2011 -> '-'; whitespace runs -> ' '",
            "documents": docs}


def main(argv):
    snap = build()
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as f: old = json.load(f)
        old.pop("extractor", None); new = dict(snap); new.pop("extractor", None)
        ok = old == new
        print("snapshot matches the PDFs" if ok else "SNAPSHOT DIFFERS from the PDFs")
        return 0 if ok else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1); f.write("\n")
    for d in snap["documents"]:
        print(f"{d['source_document_id']}: {len(d['pages'])} pages, sha256 {d['artifact']['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
