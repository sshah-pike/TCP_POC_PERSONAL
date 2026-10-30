"""Dev tool: render every catalog symbol (SVG) to a PNG and record the PNG's hash in the catalog (S5, owner decision Q7 A).

Run after adding or changing an SVG: python scripts/render_symbols.py
Needs PyMuPDF (the `tools` extra). It is a dev tool: nothing under src/ imports it, and the app reads only the committed
PNGs, whose sha256 and size are in the catalog. PNG bytes can differ between PyMuPDF versions, so re-run it only when a
symbol changes; the committed PNG and its recorded hash are what the app trusts.

A CLIENT_ASSET that is already a PNG is not re-rendered: its raster is the asset itself.
"""
import json, os, sys
import pymupdf   # PyMuPDF
from tcp_planner.config.settings import DEVICE_CATALOG_PATH
from tcp_planner.rules.device_catalog import asset_file_path, seal

ZOOM = 2.0   # PNG pixels per SVG unit: a 200 x 200 symbol becomes 400 x 400


def render(svg_path, png_path):
    with open(svg_path, "rb") as f: doc = pymupdf.open(stream=f.read(), filetype="svg")
    try:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), alpha=True)
        os.makedirs(os.path.dirname(png_path), exist_ok=True)
        pix.save(png_path)
    finally: doc.close()


def main():
    with open(DEVICE_CATALOG_PATH, encoding="utf-8") as f: doc = json.load(f)
    for e in doc["entries"]:
        a = e["asset"]
        if a["media_type"] == "image/png":
            e["raster"] = {**a}
            continue
        uri = "symbols/png/" + os.path.splitext(os.path.basename(a["uri"]))[0] + ".png"
        render(asset_file_path(a["uri"]), asset_file_path(uri))
        e["raster"] = {"uri": uri, "sha256": "0" * 64, "size": 0, "media_type": "image/png", "status": a["status"]}
    with open(DEVICE_CATALOG_PATH, "w", encoding="utf-8") as f: json.dump(doc, f, indent=1, ensure_ascii=False)
    print("catalog hash", seal())
    return 0


if __name__ == "__main__":
    sys.exit(main())
