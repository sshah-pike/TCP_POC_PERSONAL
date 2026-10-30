"""Write every asset's sha256 and size and the catalog hash into assets/symbols/device_catalog.json, then load it.

Run after any deliberate change to the catalog or to a symbol file: python scripts/seal_device_catalog.py
"""
import sys
from tcp_planner.rules.device_catalog import DeviceCatalogError, load_catalog, seal


def main():
    h = seal()
    try: cat = load_catalog()
    except DeviceCatalogError as e: print("ERROR", e); return 1
    print(f"catalog hash {h}; {len(cat.entries)} entries; 0 errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
