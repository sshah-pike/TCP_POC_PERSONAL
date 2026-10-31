"""Turn recorded OSM fixtures into the --second-source CSV of scripts/s06_accuracy_report.py (S6 step 16). Offline, no network.

  python scripts/s06_osm_second_source.py --sites sites.csv --out second_source.csv
  python scripts/s06_accuracy_report.py --results var/s06_call1_check/gpt-5.6-sol --truth truth.csv --second-source second_source.csv

For every site of sites.csv the recorded Overpass answer is replayed (a missing fixture is reported and the site is left out), the OSM
reference way is chosen by the WORK POINT only (the nearest way, clearly nearer than the next road that runs a different way; otherwise
the site gets blank cells), and the OSM rules give the four safety-critical fields:
  lanes_per_direction  number, or blank when OSM gives no usable value (no tag, odd total, forward differs from backward)
  divided_highway      true / false (a two-way chosen way with no opposite carriageway is false), blank when undecidable
  shoulder_present     true / false from the shoulder tags, blank when there is no tag
  oneway               true / false from the tag; a MISSING tag is written false (the rule counts it as not one-way at lower confidence:
                       it can agree with an AI false and never contradicts an AI true; the notes list those sites)
A blank cell means OSM has no value, so the accuracy report never passes that field on. The columns are those of the report's
--second-source file (site_id, lanes_per_direction, divided_highway, shoulder_present, oneway). Notes go to the screen.
"""
import argparse, csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT, os.path.join(ROOT, "scripts")]
DEFAULT_FIXTURES = os.path.join(ROOT, "tests", "fixtures", "recorded")
COLUMNS = ("site_id", "lanes_per_direction", "divided_highway", "shoulder_present", "oneway")


def cell(reading):
    if reading is None or reading.outcome == "UNKNOWN" or reading.value is None: return ""
    return str(reading.value).lower() if isinstance(reading.value, bool) else str(reading.value)


def row_for(site, fixtures_root, cfg):
    """(row dict, [notes]) for one site, from its recorded fixture."""
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import SourceClient, SourceError
    from tests.support.fixtures import MissingFixtureError
    from tests.support.source_fixtures import SourceFixtures
    from tcp_planner.site_model import bearing_check as BC
    from tcp_planner.site_model import osm_rules as OR
    row = {"site_id": site["site_id"], **{c: "" for c in COLUMNS[1:]}}
    client = SourceClient(hook=SourceFixtures(os.path.join(fixtures_root, site["site_id"])), transport=None)
    try: res = osm.fetch_ways(client, site["lat"], site["lon"], cfg)
    except MissingFixtureError: return row, [f"{site['site_id']}: no recorded OSM fixture (run s06_record_osm.py); left blank"]
    except SourceError as e: return row, [f"{site['site_id']}: {e.code}: {e.message}; left blank"]
    chk = BC.check_bearing((), res.ways, cfg=cfg)                 # no marks: the reference way comes from the work point alone
    if chk.status == BC.WHICH_ROAD: return row, [f"{site['site_id']}: the reference road is not clear (WHICH_ROAD); left blank"]
    if chk.status == BC.NO_ROAD: return row, [f"{site['site_id']}: no OSM road near the work point; left blank"]
    read = OR.osm_read(res.ways, choice=chk.reference, cfg=cfg)
    notes = []
    for field, r in read.readings.items():
        if field in row: row[field] = cell(r)
    ow = read.readings["oneway"]
    if ow.lower_confidence: notes.append(f"{site['site_id']}: no oneway tag on way {read.way_id}; written as false (lower confidence)")
    return row, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", required=True); ap.add_argument("--fixtures", default=DEFAULT_FIXTURES); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    from s06_call1_check import SitesError, read_sites
    from tcp_planner.site_model.site_config import load_site_config
    try: sites = read_sites(a.sites)
    except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
    cfg = load_site_config(); rows, notes = [], []
    for s in sites:
        r, n = row_for(s, a.fixtures, cfg); rows.append(r); notes += n
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS); w.writeheader(); w.writerows(rows)
    for n in notes: print(n)
    filled = sum(any(r[c] != "" for c in COLUMNS[1:]) for r in rows)
    print(f"\nwrote {len(rows)} row(s) ({filled} with at least one OSM value) to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
