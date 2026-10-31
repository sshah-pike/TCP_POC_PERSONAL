"""Owner's recorder for OpenStreetMap fixtures (S6 step 13): one bounded Overpass query per site, saved so tests replay it offline.

  $env:TCP_LIVE = "1"
  python scripts/s06_record_osm.py --sites sites.csv                     records one fixture per site under tests/fixtures/recorded/<site_id>/source/
  python scripts/s06_record_osm.py --sites sites.csv --dry-run           no network: prints each query
  python scripts/s06_record_osm.py --sites sites.csv --out some\\folder   another fixture root

sites.csv has the columns of the call 1 sites file: site_id, lat, lon, extent_m (and optionally ta_situation); extent_m is not used here
(the query radius comes from config/site_understanding.json osm.query_radius_m, capped by config/data_sources.json). A site that already
has a fixture for the same query is skipped: fixtures are write-once and a stored response is never fetched again.

Every request goes through the allow-listed SourceClient (host overpass-api.de only, descriptive User-Agent without a company name or
contact, size bound); an error answer is never recorded. Calls use_os_trust_store() first; certificate verification is never turned off.
Two seconds pass between requests (Overpass fair use). The script stops at the first error and prints the HTTP status and the body.
"""
import argparse, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT, os.path.join(ROOT, "scripts")]
DEFAULT_OUT = os.path.join(ROOT, "tests", "fixtures", "recorded")
PAUSE_S = 2.0


def main(argv=None, transport=None, sleep=time.sleep):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", required=True); ap.add_argument("--out", default=DEFAULT_OUT); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from s06_call1_check import SitesError, read_sites
    try: sites = read_sites(a.sites)
    except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import SourceClient, SourceError, request_fingerprint, request_record, requests_transport
    from tcp_planner.site_model.site_config import load_site_config, setting
    from tests.support.source_fixtures import SourceFixtures
    cfg = load_site_config(); radius = setting("osm", "query_radius_m", cfg)[0]; classes = setting("osm", "highway_classes", cfg)[0]
    if a.dry_run:
        for s in sites:
            q = osm.build_query(s["lat"], s["lon"], radius, classes)
            print(f"[dry run] {s['site_id']}: {q}")
        print(f"\n{len(sites)} request(s) would be made to {osm.URL}, radius {radius} m; fixtures go to {a.out}")
        return 0
    if os.environ.get("TCP_LIVE") != "1" and transport is None: print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2
    if transport is None:
        from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
        load_env_file(); use_os_trust_store(); transport = requests_transport
    done = skipped = 0
    for i, s in enumerate(sites):
        hook = SourceFixtures(os.path.join(a.out, s["site_id"]))
        q = osm.build_query(s["lat"], s["lon"], radius, classes)
        fp = request_fingerprint(request_record(osm.SOURCE_ID, "GET", osm.URL, {"data": q}))
        if hook.has(fp):
            print(f"{s['site_id']}: already recorded ({fp[:12]}), skipped"); skipped += 1; continue
        client = SourceClient(hook=hook, transport=transport)
        try: r = osm.fetch_ways(client, s["lat"], s["lon"], cfg)
        except SourceError as e:
            body = (e.details or {}).get("body") if hasattr(e, "details") else None
            print(f"\nSTOP: {s['site_id']} failed: {e.code}: {e.message}" + (f"\n  HTTP status: {(e.details or {}).get('http_status')}\n  body: {body}" if body is not None else "")); return 1
        print(f"{s['site_id']}: recorded {len(r.ways)} way(s), fixture {fp[:12]} under {os.path.join(a.out, s['site_id'], 'source')}")
        done += 1
        if i < len(sites) - 1: sleep(PAUSE_S)
    print(f"\n{done} recorded, {skipped} already there. Next: python scripts/s06_osm_second_source.py --sites {a.sites} --out second_source.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
