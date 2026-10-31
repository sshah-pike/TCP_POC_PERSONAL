"""Owner's recorder for OpenStreetMap fixtures (S6 step 13): one bounded Overpass query per site, saved so tests replay it offline.

  $env:TCP_LIVE = "1"
  python scripts/s06_record_osm.py --sites sites.csv                     records one fixture per site under tests/fixtures/recorded/<site_id>/source/
  python scripts/s06_record_osm.py --sites sites.csv --dry-run           no network: prints each query
  python scripts/s06_record_osm.py --sites sites.csv --out some\\folder   another fixture root

sites.csv has the columns of the call 1 sites file: site_id, lat, lon, extent_m (and optionally ta_situation); extent_m is not used here
(the query radius comes from config/site_understanding.json osm.query_radius_m, capped by config/data_sources.json). A site that already
has a fixture for the same query is skipped: fixtures are write-once and a stored response is never fetched again.

The provider is config osm.provider: osm_api (the OSM main API, default) or overpass; fixtures are never shared between them.
Every request goes through the allow-listed SourceClient (the host of the provider only, descriptive User-Agent without a company name or
contact, size bound); an error answer is never recorded. Calls use_os_trust_store() first; certificate verification is never turned off.
Two seconds pass between requests (Overpass fair use). A timeout, a dropped connection, HTTP 408, 429 or 5xx is retried per site: after the waits
in config osm.retry_waits_s (10 s, then 30 s: at most 2 retries). Timeouts come from config: osm.query_timeout_s (the query asks the server for 60 s)
and config/data_sources.json osm_overpass.timeout_s (the client waits up to 90 s); both CALIBRATION_PENDING. A site that still fails prints the HTTP
status or the timeout and the script goes on with the next site; the exit code is 1 if any site failed. Run it again: recorded sites are skipped.
"""
import argparse, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT, os.path.join(ROOT, "scripts")]
DEFAULT_OUT = os.path.join(ROOT, "tests", "fixtures", "recorded")
PAUSE_S = 2.0


def retryable(e):
    """A timeout, a dropped connection, a rate limit (408, 429) or a server error (5xx) is worth another try; anything else is not."""
    if e.code in ("SOURCE_TIMEOUT", "SOURCE_NETWORK_ERROR"): return True
    status = (e.details or {}).get("http_status")
    return e.code == "SOURCE_HTTP_ERROR" and isinstance(status, int) and (status in (408, 429) or status >= 500)


def describe(e):
    """The HTTP status or the timeout, in one phrase."""
    status = (e.details or {}).get("http_status")
    if e.code == "SOURCE_TIMEOUT": return f"timeout ({e.message})"
    return f"HTTP status {status}" if status is not None else f"{e.code}: {e.message}"


class Counting:
    """Counts the live requests a transport makes (a site served entirely from recorded fixtures makes none)."""
    def __init__(self, inner): self.inner, self.n = inner, 0

    def __call__(self, *a, **k): self.n += 1; return self.inner(*a, **k)


def record_sites(sites, out, transport, sleep=time.sleep, cfg=None, log=print, clock=time.monotonic, stop=None):
    """Record the OSM fixtures of the configured provider (config osm.provider) with the config timeouts and retries. Returns one record per site:
    {site_id, status 'recorded' | 'skipped' | 'failed' | 'not_attempted', attempts, seconds, ways, fixture, boxes, note, error}. A site whose requests are
    all in the fixture store is replayed and reported 'skipped' (no live request); a partly recorded site continues where it stopped. Never raises for a
    source failure: a final failure is printed (HTTP status or timeout) and the next site goes on, unless `stop()` says the run must stop (a 429, a
    gateway page, the request limit): then the remaining sites are 'not_attempted'. A fixture is never reused across providers (its request names the
    source and the URL)."""
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import SourceClient, SourceError
    from tcp_planner.site_model.site_config import load_site_config, setting
    from tests.support.source_fixtures import SourceFixtures
    cfg = cfg or load_site_config()
    waits = list(setting("osm", "retry_waits_s", cfg)[0])
    records, halted = [], False
    for i, s in enumerate(sites):
        hook = SourceFixtures(os.path.join(out, s["site_id"]))
        fp = osm.request_key(s["lat"], s["lon"], cfg)
        rec = {"site_id": s["site_id"], "status": None, "attempts": 0, "seconds": 0.0, "ways": None, "fixture": fp, "boxes": None, "note": None, "error": None}
        records.append(rec)
        if halted:
            rec["status"] = "not_attempted"; continue
        counting = Counting(transport)
        client = SourceClient(hook=hook, transport=counting)
        r, err, t0 = None, None, clock()
        for attempt in range(len(waits) + 1):
            rec["attempts"] = attempt + 1
            try: r = osm.fetch_ways(client, s["lat"], s["lon"], cfg); err = None; break
            except SourceError as e:
                err = e
                if (stop and stop()) or not retryable(e) or attempt == len(waits): break
                log(f"{s['site_id']}: {describe(e)}; retry {attempt + 1} of {len(waits)} after {waits[attempt]:g} s")
                sleep(waits[attempt])
        rec["seconds"] = round(clock() - t0, 2)
        if err is not None:
            rec.update(status="failed", error=describe(err))
            log(f"\n{s['site_id']}: FAILED after {rec['attempts']} attempt(s): {describe(err)}"
                + (f"\n  body: {(err.details or {}).get('body')}" if (err.details or {}).get("body") else "") + "\n  continuing with the next site")
            if stop and stop(): halted = True; log(f"STOP: {stop()}: the run stops here; the remaining sites are not attempted")
            continue
        info = r.info or {}
        rec.update(ways=len(r.ways), boxes=[x.get("bbox_half_m") for x in info.get("attempts", [])] or None, note=info.get("note"))
        if counting.n == 0:
            rec["status"] = "skipped"; log(f"{s['site_id']}: already recorded ({fp[:12]}), skipped")
            continue
        rec["status"] = "recorded"
        log(f"{s['site_id']}: recorded {len(r.ways)} way(s), fixture {fp[:12]} under {os.path.join(out, s['site_id'], 'source')}" + (f" ({info['note']})" if info.get("note") else ""))
        if i < len(sites) - 1: sleep(PAUSE_S)
    return records


def main(argv=None, transport=None, sleep=time.sleep):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", required=True); ap.add_argument("--out", default=DEFAULT_OUT); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from s06_call1_check import SitesError, read_sites
    try: sites = read_sites(a.sites)
    except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import requests_transport
    from tcp_planner.site_model.site_config import load_site_config, setting
    cfg = load_site_config(); radius = setting("osm", "query_radius_m", cfg)[0]; classes = setting("osm", "highway_classes", cfg)[0]
    timeout_s = setting("osm", "query_timeout_s", cfg)[0]
    if a.dry_run:
        for s in sites:
            print(f"[dry run] {s['site_id']}: {osm.request_preview(s['lat'], s['lon'], cfg)}")
        print(f"\n{len(sites)} request(s) would be made by provider {setting('osm', 'provider', cfg)[0]}, radius {radius} m; fixtures go to {a.out}")
        return 0
    if os.environ.get("TCP_LIVE") != "1" and transport is None: print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2
    if transport is None:
        from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
        load_env_file(); use_os_trust_store(); transport = requests_transport
    records = record_sites(sites, a.out, transport, sleep, cfg=cfg)
    done = sum(r["status"] == "recorded" for r in records); skipped = sum(r["status"] == "skipped" for r in records)
    failed = [r["site_id"] for r in records if r["status"] == "failed"]
    print(f"\n{done} recorded, {skipped} already there, {len(failed)} failed" + (f" ({', '.join(failed)}): run the same command again; recorded sites are skipped" if failed else "")
          + f". Next: python scripts/s06_osm_second_source.py --sites {a.sites} --out second_source.csv")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
