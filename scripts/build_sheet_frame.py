"""Build a reusable sheet frame from an approved CADD plan PDF (renderer configuration, non-regulatory).

Removes the project-specific content of the source sheet - the aerial image, plan graphics in the
viewport, title/address, dates, EWO, file path and project notes - and keeps the standard frame:
border, general notes box, traffic legend, channelization/sign details, Dig Safe box, utility note,
north arrow, logos and the empty title-block grid. Writes:

  sheet_frame.png    blank frame raster
  sheet_layout.json  page size + named regions (PDF points, origin top-left) + source hash

Usage:  python scripts/build_sheet_frame.py "<CADD FINAL>.pdf" [out_dir]
"""
import hashlib, json, os, sys

PAGE_DPI = 200
ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sheet")

# Regions measured from '3) CADD FINAL - 1A7DS9M WPI 3160485.pdf' (2448 x 1584 pt, ANSI D 34x22 in).
LAYOUT = {
    "viewport": [35.9, 36.1, 2089.6, 1386.0],
    "general_notes_box": [53.0, 1129.6, 564.5, 1368.8],
    "phase_label": [2092.0, 30.0, 2410.0, 82.0],
    "project_notes": [617.0, 1400.0, 1188.0, 1464.0],
    "project_notes_overflow": [1188.0, 1400.0, 1320.0, 1416.0],
    "scale_cell": [615.0, 1477.0, 1188.0, 1546.5],
    "title_lines": [2092.0, 1404.0, 2410.0, 1462.0],
    "field_surveyed_by": [2150.0, 1473.0, 2251.0, 1487.0],
    "field_print_no": [2295.0, 1473.0, 2410.0, 1487.0],
    "field_drawn_by": [2140.0, 1500.0, 2251.0, 1514.0],
    "field_scale": [2281.0, 1500.0, 2410.0, 1514.0],
    "field_date": [2118.0, 1527.0, 2251.0, 1541.0],
    "field_ewo": [2276.0, 1527.0, 2410.0, 1541.0],
    "revision_rows": [38.0, 1423.0, 324.0, 1546.0],
    "file_path_strip": [16.0, 420.0, 34.0, 1560.0],
    "legend_panel": [2089.6, 82.0, 2411.8, 1386.0],
}

# Text removed from the frame (project specific). Rectangles in PDF points.
TEXT_REDACTIONS = ["phase_label", "project_notes", "project_notes_overflow", "title_lines", "field_surveyed_by", "field_print_no", "field_drawn_by",
                   "field_scale", "field_date", "field_ewo", "revision_rows", "file_path_strip"]
EXTRA_TEXT_REDACTIONS = [[30.0, 1546.0, 90.0, 1560.0]]   # drawing serial number under the border


def _viewport_minus_notes(vp, nb):
    x0, y0, x1, y1 = vp; a, b, c, d = nb
    return [[x0 + 0.6, y0 + 0.6, x1 - 0.6, b], [c, b, x1 - 0.6, y1 - 0.6],
            [x0 + 0.6, b, a, y1 - 0.6], [a, d, c, y1 - 0.6]]


def extract(pdf_path, out_dir=ASSET_DIR):
    import pymupdf
    os.makedirs(out_dir, exist_ok=True)
    with open(pdf_path, "rb") as f: src_hash = hashlib.sha256(f.read()).hexdigest()
    doc = pymupdf.open(pdf_path); page = doc[0]
    # pass 1: empty the viewport (aerial image, plan graphics, labels) but keep the general notes box
    for rc in _viewport_minus_notes(LAYOUT["viewport"], LAYOUT["general_notes_box"]):
        page.add_redact_annot(pymupdf.Rect(rc), fill=(1, 1, 1))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_REMOVE, graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # pass 2: scale bar cell graphics (redrawn per plan scale)
    page.add_redact_annot(pymupdf.Rect(LAYOUT["scale_cell"]), fill=(1, 1, 1))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # pass 3: project-specific text only (keep grid lines and labels such as 'DATE:')
    for key in TEXT_REDACTIONS:
        page.add_redact_annot(pymupdf.Rect(LAYOUT[key]), fill=None)
    for rc in EXTRA_TEXT_REDACTIONS:
        page.add_redact_annot(pymupdf.Rect(rc), fill=None)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    pix = page.get_pixmap(dpi=PAGE_DPI, alpha=False)
    png = os.path.join(out_dir, "sheet_frame.png"); pix.save(png)
    # rotated margin text (file path / date) is not removed by text redaction: blank it in the raster
    from PIL import Image, ImageDraw
    Image.MAX_IMAGE_PIXELS = None
    im = Image.open(png).convert("RGB"); k = PAGE_DPI / 72.0
    x0, y0, x1, y1 = LAYOUT["file_path_strip"]
    ImageDraw.Draw(im).rectangle([x0 * k, y0 * k, x1 * k, y1 * k], fill=(255, 255, 255))
    im.save(png, optimize=True)
    meta = {"source_pdf": os.path.basename(pdf_path), "source_sha256": src_hash,
            "regulatory_status": "NON_MUTCD_RENDERER_CONFIGURATION",
            "page_size_pt": [page.rect.width, page.rect.height], "raster_dpi": PAGE_DPI,
            "raster_px": [pix.width, pix.height], "regions_pt": LAYOUT}
    with open(os.path.join(out_dir, "sheet_layout.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


if __name__ == "__main__":
    print(json.dumps(extract(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ASSET_DIR)["raster_px"]))
