"""Symbol library (S5): the symbol a sheet draws for a catalog device, looked up by device_id.

The app draws the pre-rendered PNG (owner decision Q7 A). scripts/render_symbols.py, a dev tool, makes the PNGs from the
SVGs; nothing here imports it or any PDF or SVG library. A lookup checks the file against the sha256 and size in the
catalog, so a changed or missing file is an error, never a silent change of look.

Drop-in replacement for client artwork: replace the asset of one catalog entry with a client SVG or PNG (status
CLIENT_ASSET), re-seal the catalog (scripts/seal_device_catalog.py) and, for an SVG, re-run scripts/render_symbols.py.
Only that entry and the catalog hash change. A DWG or DXF block is not read here: convert it to SVG or PNG first
(plan open question 16, client CAD blocks).
"""
import struct
from dataclasses import dataclass
from tcp_planner.rules.device_catalog import DeviceCatalog, DeviceCatalogError, load_catalog

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class Symbol:
    device_id: str
    status: str            # PLACEHOLDER_ASSET or CLIENT_ASSET
    placeholder: bool
    png_path: str
    png_sha256: str
    width_px: int
    height_px: int
    asset_uri: str         # the source symbol file (SVG or PNG)


class SymbolLibrary:
    def __init__(self, catalog=None):
        self.catalog = catalog if isinstance(catalog, DeviceCatalog) else load_catalog()

    def symbol(self, device_id):
        """The symbol for a device. An unknown device raises DEVICE_UNKNOWN; a changed file raises ASSET_HASH_MISMATCH."""
        entry = self.catalog.get(device_id)
        path = self.catalog.asset_path(device_id, raster=True)
        with open(path, "rb") as f: head = f.read(24)
        if head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
            raise DeviceCatalogError("SYMBOL_NOT_PNG", f"raster for {device_id} is not a PNG", {"device_id": device_id})
        w, h = struct.unpack(">II", head[16:24])
        return Symbol(device_id=device_id, status=entry.asset.status.value,
                      placeholder=entry.asset.status.value == "PLACEHOLDER_ASSET", png_path=path,
                      png_sha256=entry.raster.sha256, width_px=w, height_px=h, asset_uri=entry.asset.uri)

    def png_bytes(self, device_id):
        with open(self.symbol(device_id).png_path, "rb") as f: return f.read()

    def placeholder_status(self, device_ids):
        return self.catalog.placeholder_status(device_ids)
