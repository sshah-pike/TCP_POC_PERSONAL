"""Owner's live probe: is there native detail at zoom 19 in Massachusetts? (S6 step 13)

  $env:TCP_LIVE = "1"
  python scripts/s06_probe_native_detail.py            two Azure Maps requests: one zoom-19 view each for E Second MH 223 and Colorado P13
  python scripts/s06_probe_native_detail.py --dry-run  no network: shows what would be requested

For each site the script requests ONE zoom-19 view (512 px, centred on the work point), compares it with the held zoom-17 wide image of
the same site (tests/fixtures/site/spike/inputs) using the same information-only detail check as the crop engine (Laplacian variance
of the view against the same ground area of the wide image enlarged), and saves the view and the numbers under var/s06_native_detail/.
A ratio far above the old gate (1.15) means real native detail; a ratio near 1 means the service enlarged a coarser tile (upsampled).
Rhode Island measured 22 to 44. The check is information only: it never gates anything.

Calls use_os_trust_store() first (the pipeline CLI does the same); certificate verification is never turned off. A failed request stops
the script with the HTTP status and the error text (no key).
"""
import argparse, io, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]
INPUTS = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "inputs")
OUT = os.path.join(ROOT, "var", "s06_native_detail")
ZOOM, SIZE_PX = 19, 512
SITES = (("second", "E Second MH 223"), ("colorado", "Colorado P13"))


def _load(site):
    with open(os.path.join(INPUTS, site + ".json"), encoding="utf-8") as f: meta = json.load(f)
    return meta, os.path.join(INPUTS, site + ".jpg")


def probe(site, label, provider):
    """Fetch one zoom-19 view, measure it against the held wide image, save both numbers and view. Returns the record."""
    import hashlib
    from PIL import Image, ImageStat
    from tcp_planner.imagery import crops
    meta, wide_path = _load(site)
    lat, lon = meta["lat"], meta["lon"]
    img, vmeta = provider.fetch_view(lat, lon, ZOOM, SIZE_PX)
    wide = Image.open(wide_path); wide.load()
    min_ratio = crops._pipeline()["sharpness"]["min_detail_gain_ratio"]
    info = crops.detail_gain(img.convert("RGB"), (lat, lon), vmeta["metres_per_pixel"], wide.convert("RGB"), (lat, lon), meta["metres_per_pixel"], min_ratio)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=92); data = buf.getvalue()
    d = os.path.join(OUT, site); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "zoom19.jpg"), "wb") as f: f.write(data)
    rec = {"site": site, "label": label, "lat": lat, "lon": lon, "zoom": ZOOM, "size_px": SIZE_PX, "metres_per_pixel": vmeta["metres_per_pixel"],
           "wide_metres_per_pixel": meta["metres_per_pixel"], "view_sha256": hashlib.sha256(data).hexdigest(), "view_std": round(ImageStat.Stat(img.convert("L")).stddev[0], 2),
           "detail_check": info, "retrieved_at": vmeta.get("retrieved_at")}
    with open(os.path.join(d, "zoom19.json"), "w", encoding="utf-8") as f: json.dump(rec, f, indent=2, ensure_ascii=False)
    return rec


def main(argv=None, provider=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="no network: list the requests")
    a = ap.parse_args(argv)
    if a.dry_run:
        for site, label in SITES:
            meta, _ = _load(site)
            print(f"[dry run] {label}: one zoom-{ZOOM} request, {SIZE_PX} px, centre lat {meta['lat']}, lon {meta['lon']}; compared with the held zoom-17 image ({meta['metres_per_pixel']} m/px)")
        return 0
    if os.environ.get("TCP_LIVE") != "1": print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2
    from tcp_planner.contracts import MapProviderError
    if provider is None:
        from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
        load_env_file(); use_os_trust_store()
        from tcp_planner.imagery.map_provider import get_map_provider
        provider = get_map_provider("azure_maps")
    rows = []
    for site, label in SITES:
        try: rec = probe(site, label, provider)
        except MapProviderError as e:
            print(f"\nSTOP: the zoom-{ZOOM} request for {label} failed: {e.code}: {e.message}"); return 1
        rows.append(rec)
        di = rec["detail_check"] or {}
        print(f"{label}: {rec['metres_per_pixel']:.4f} m/px, detail ratio {di.get('ratio')} ({di.get('flag')}), saved var/s06_native_detail/{site}/zoom19.jpg")
    print("\n| site | zoom | m/px | wide m/px | detail ratio | flag | view std |\n| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        di = r["detail_check"] or {}
        print(f"| {r['label']} | {r['zoom']} | {r['metres_per_pixel']:.4f} | {r['wide_metres_per_pixel']} | {di.get('ratio')} | {di.get('flag')} | {r['view_std']} |")
    print("\nRhode Island (three sites) measured 22 to 44; the old gate is 1.15. Send the table back; the view files stay under var/ (not tracked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
