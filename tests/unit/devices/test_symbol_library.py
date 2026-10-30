"""Symbol library and the PNG dev script output (S5). Offline; PyMuPDF is not needed here."""
import ast, json, os, re, shutil, struct, zlib

import pytest

from tcp_planner.contracts import TcpError
from tcp_planner.rules import device_catalog as dc
from tcp_planner.rules.device_catalog import load_catalog
from tcp_planner.rules.symbol_library import PNG_SIGNATURE, SymbolLibrary

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ZOOM = 2     # scripts/render_symbols.py


@pytest.fixture(scope="module")
def lib():
    return SymbolLibrary()


def test_every_catalog_device_has_a_png_that_matches_its_hash(lib):
    for e in lib.catalog.entries:
        s = lib.symbol(e.device_id)
        assert s.placeholder and s.status == "PLACEHOLDER_ASSET" and s.width_px > 0 and s.height_px > 0
        data = lib.png_bytes(e.device_id)
        assert data[:8] == PNG_SIGNATURE
        import hashlib
        assert hashlib.sha256(data).hexdigest() == e.raster.sha256 and len(data) == e.raster.size


def test_png_pixel_size_is_the_svg_size_times_the_zoom(lib):
    for e in lib.catalog.entries:
        svg = open(lib.catalog.asset_path(e.device_id), encoding="utf-8").read()
        w, h = (int(re.search(rf'<svg[^>]* {k}="(\d+)"', svg).group(1)) for k in ("width", "height"))
        s = lib.symbol(e.device_id)
        assert (s.width_px, s.height_px) == (w * ZOOM, h * ZOOM), e.device_id


def test_png_files_are_exactly_the_rasters_in_the_catalog(lib):
    on_disk = {f"symbols/png/{n}" for n in os.listdir(os.path.join(dc.ASSETS_DIR, "symbols", "png"))}
    assert on_disk == {e.raster.uri for e in lib.catalog.entries}
    uris = [e.raster.uri.lower() for e in lib.catalog.entries]
    assert len(set(uris)) == len(uris)


def test_unknown_device_and_changed_png_are_errors(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    shutil.copytree(os.path.join(dc.ASSETS_DIR, "symbols"), assets / "symbols")
    monkeypatch.setattr(dc, "ASSETS_DIR", str(assets))
    monkeypatch.setattr(dc, "DEVICE_CATALOG_PATH", str(assets / "symbols" / "device_catalog.json"))
    lib = SymbolLibrary()
    with pytest.raises(TcpError) as ex: lib.symbol("NOPE")
    assert ex.value.code == "DEVICE_UNKNOWN"
    with open(assets / "symbols" / "png" / "W20-1.png", "ab") as f: f.write(b"x")
    with pytest.raises(TcpError) as ex: lib.symbol("W20-1")
    assert ex.value.code == "ASSET_HASH_MISMATCH"


def _png(w, h, rgb):
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_client_png_swap_changes_only_that_symbol_and_the_catalog_hash(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    shutil.copytree(os.path.join(dc.ASSETS_DIR, "symbols"), assets / "symbols")
    monkeypatch.setattr(dc, "ASSETS_DIR", str(assets))
    p = assets / "symbols" / "device_catalog.json"
    monkeypatch.setattr(dc, "DEVICE_CATALOG_PATH", str(p))
    before = json.load(open(p, encoding="utf-8"))
    (assets / "symbols" / "png" / "client").mkdir()
    (assets / "symbols" / "png" / "client" / "W20-1.png").write_bytes(_png(8, 6, (1, 2, 3)))
    doc = json.load(open(p, encoding="utf-8"))
    for e in doc["entries"]:
        if e["device_id"] == "W20-1":
            e["asset"] = {"uri": "symbols/png/client/W20-1.png", "sha256": "0" * 64, "size": 0, "media_type": "image/png", "status": "CLIENT_ASSET"}
            e["raster"] = dict(e["asset"])
    json.dump(doc, open(p, "w", encoding="utf-8"))
    new_hash = dc.seal()
    after = json.load(open(p, encoding="utf-8"))
    assert new_hash != before["catalog_hash"]
    assert [b["device_id"] for b, a in zip(before["entries"], after["entries"]) if b != a] == ["W20-1"]
    lib = SymbolLibrary()
    s = lib.symbol("W20-1")
    assert (s.width_px, s.height_px, s.placeholder, s.status) == (8, 6, False, "CLIENT_ASSET")
    assert lib.symbol("G20-2").placeholder
    assert lib.placeholder_status(["W20-1"])["uses_placeholder"] is False
    assert lib.placeholder_status(["W20-1", "G20-2"])["device_ids"] == ["G20-2"]


def test_src_imports_no_svg_or_pdf_renderer():
    src = os.path.join(ROOT, "src", "tcp_planner")
    banned = {"fitz", "pymupdf", "cairosvg", "svglib", "pdfplumber", "pdfminer", "pypdf", "reportlab"}
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for n in files:
            if not n.endswith(".py"): continue
            for node in ast.walk(ast.parse(open(os.path.join(d, n), encoding="utf-8").read())):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                assert not [x for x in names if x.split(".")[0] in banned], (n, names)
