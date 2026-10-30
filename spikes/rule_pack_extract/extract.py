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
        7: "6B.04 (advance warning area; para 07: Table 6B-1 distances are approximate, guidance only)",
        9:"6B.06 paras 01-14 (buffer option para 11); Table 6B-1",
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
# Figure drawings have no text layer for their labels, so figure-only values are FIGURE_TRANSCRIPTION evidence read
# from these renders. The PNGs are committed next to the snapshot; their sha256 is recorded in it.
FIGURES = {97: "6P-1", 107: "6P-6", 115: "6P-10", 161: "6P-33"}
FIGURE_DPI = 150
FIG_DIR = os.path.join(os.path.dirname(OUT), "figures")


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
            "documents": docs}, render_figures()


def render_figures():
    """{file name: PNG bytes} for the four TA figure pages, and the snapshot entries describing them."""
    pdf = pymupdf.open(os.path.join(ROOT, *MUTCD.split("/")))
    pngs, entries = {}, []
    for n, fig in FIGURES.items():
        png = pdf[n - 1].get_pixmap(dpi=FIGURE_DPI).tobytes("png")
        m = re.search(r"Page (\d{3})", pdf[n - 1].get_text("text"))
        name = f"figure_{fig}_p{m.group(1)}.png"
        pngs[name] = png
        entries.append({"figure": fig, "pdf_page": n, "printed_page": m.group(1), "dpi": FIGURE_DPI,
                        "artifact": {"uri": f"tests/fixtures/rule_pack_sources/figures/{name}",
                                     "sha256": hashlib.sha256(png).hexdigest(), "size": len(png), "media_type": "image/png"}})
    return pngs, entries


def main(argv):
    snap, (pngs, figures) = build()
    snap["figure_renders"] = figures
    if "--check" in argv:
        with open(OUT, encoding="utf-8") as f: old = json.load(f)
        old.pop("extractor", None); new = dict(snap); new.pop("extractor", None)
        ok = old == new
        print("snapshot matches the PDFs" if ok else "SNAPSHOT DIFFERS from the PDFs (text, or figure renders from another PyMuPDF version)")
        return 0 if ok else 1
    os.makedirs(FIG_DIR, exist_ok=True)
    for name, png in pngs.items():
        with open(os.path.join(FIG_DIR, name), "wb") as f: f.write(png)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1); f.write("\n")
    for d in snap["documents"]:
        print(f"{d['source_document_id']}: {len(d['pages'])} pages, sha256 {d['artifact']['sha256'][:16]}...")
    for e in figures: print(f"figure {e['figure']}: {e['artifact']['uri']} ({e['artifact']['size']} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
