"""Text-layer survey of the S4 source PDFs (dev-time spike, never imported by src/).

Usage: python spikes/rule_pack_extract/survey.py
Prints, per PDF: sha256, page count, pages with little or no text, and the printed page labels seen.
"""
import hashlib, os, sys
import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PDFS = [os.path.join(ROOT, "docs", "sources", "CHAPTER 6 - DEC 2023 MUTCD REVISION.pdf"),
        *sorted(os.path.join(ROOT, "docs", "references", f) for f in os.listdir(os.path.join(ROOT, "docs", "references"))
                if f.lower().endswith(".pdf"))]
LOW_TEXT = 200  # characters; below this a page is listed for a manual look


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def main():
    for p in PDFS:
        doc = pymupdf.open(p)
        lens = [len(pg.get_text("text").strip()) for pg in doc]
        low = [i + 1 for i, n in enumerate(lens) if n < LOW_TEXT]
        print(f"== {os.path.relpath(p, ROOT)}")
        print(f"   sha256 {sha256(p)}  pages {doc.page_count}  total chars {sum(lens)}")
        print(f"   pages under {LOW_TEXT} chars: {low if low else 'none'}")
        imgs = sum(len(pg.get_images()) for pg in doc)
        print(f"   embedded images {imgs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
