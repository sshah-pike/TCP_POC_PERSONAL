"""Owner-run OSM pipeline (S6, OSM diagnosis): diagnose, record, second source, what OSM says at each point, accuracy, one REPORT.md.
Needs TCP_LIVE=1; talks to overpass-api.de only; works from any folder.

  python scripts/s06_osm_pipeline.py --sites sites_v0.csv --truth-sites sites_truth3.csv --truth path\\to\\site_truth_v0.csv --dry-run
  $env:TCP_LIVE = "1"
  python scripts/s06_osm_pipeline.py --sites sites_v0.csv --truth-sites sites_truth3.csv --truth path\\to\\site_truth_v0.csv

Stages (each stops the run on its first failure, prints what failed and still writes REPORT.md):
  1 diagnose   scripts/s06_osm_diagnose.py for the first site. PASSES only if the project path returns HTTP 200 with parseable JSON in under
               osm_diagnose.pass_s (60) seconds. If it fails: the verdict is printed, nothing else is requested, "send REPORT.md".
  2 record     the Overpass fixtures for the sites file (the recorder, with the config timeouts and retries; recorded sites are skipped)
  3 second     second_source.csv for the truth-sites file (OSM as the second source)
  4 osm table  for every site: nearest way, class, name, ref, distance from the work point to the way's centreline (m), lanes, lanes:forward,
               lanes:backward, oneway, maxspeed, sidewalk, shoulder, surface, width, number of ways within the radius
  5 accuracy   scripts/s06_accuracy_report.py on var/s06_call1_check, var/s06_call1_check_v2 (and _v3 if it exists), profiles gpt-5.6-sol and
               claude-opus-5-5, with the truth CSV and second_source.csv; one report per version
  6 REPORT.md  environment, diagnose table and verdict, recorder results per site, stage 4 table, second_source.csv, the accuracy reports in full,
               the fixture files created, the files to upload
The run folder is var/s06_osm_pipeline/<timestamp>/ (not tracked by git). No key or token is printed (there is none); nothing about the
network, proxies or certificate checks is changed.
"""
import argparse, csv, datetime, io, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT, os.path.join(ROOT, "scripts")]
PROFILES = ("gpt-5.6-sol", "claude-opus-5-5")
VERSIONS = (("v1", "s06_call1_check"), ("v2", "s06_call1_check_v2"), ("v3", "s06_call1_check_v3"))


class RunStopped(Exception): pass


class LimitedTransport:
    """The transport of an osm_api run: at most `max_requests` requests in all, at least `min_gap_s` seconds between them (counted from the end of the
    previous one), and the run stops at the first status in `stop_statuses` (429, 509, a gateway page): the answer is returned once so the caller can report
    it, every later request raises. Clock and sleep are injected for tests."""
    def __init__(self, inner, max_requests, min_gap_s, stop_statuses, clock=time.monotonic, sleep=time.sleep):
        self.inner, self.max, self.gap, self.stops, self.clock, self.sleep = inner, max_requests, min_gap_s, tuple(stop_statuses), clock, sleep
        self.count, self.last_end, self.stop_reason, self.stop_page, self.calls = 0, None, None, None, []

    def __call__(self, method, url, params, body, headers, timeout):
        if self.stop_reason: raise RunStopped(self.stop_reason)
        if self.count >= self.max:
            self.stop_reason = f"request limit of {self.max} reached"; raise RunStopped(self.stop_reason)
        if self.last_end is not None:
            wait = self.gap - (self.clock() - self.last_end)
            if wait > 0: self.sleep(wait)
        self.count += 1
        try: status, content = self.inner(method, url, params, body, headers, timeout)
        finally: self.last_end = self.clock()
        self.calls.append((url, dict(params or {}), status))
        if status in self.stops:
            import re
            self.stop_reason = f"HTTP {status}"
            t = re.sub(r"<style.*?</style>", " ", content.decode("utf-8", "replace"), flags=re.S | re.I); self.stop_page = " ".join(re.sub(r"<[^>]+>", " ", t).split())[:400]
        return status, content


def resolve(path):
    """A path as given, else relative to the repository root (so the script works from any folder)."""
    if os.path.isabs(path) or os.path.exists(path): return os.path.abspath(path)
    alt = os.path.join(ROOT, path)
    return os.path.normpath(alt) if os.path.exists(alt) else os.path.abspath(path)


def esc(x): return str(x).replace("|", "/").replace("\n", " ")


def osm_table(sites, fixtures_root, cfg):
    """Rows of stage 4 from the recorded fixtures (replay, no network)."""
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import SourceClient, SourceError
    from tcp_planner.site_model import bearing_check as BC
    from tcp_planner.site_model import osm_rules as OR
    from tests.support.fixtures import MissingFixtureError
    from tests.support.source_fixtures import SourceFixtures
    rows = []
    for s in sites:
        base = {"site": s["site_id"]}
        client = SourceClient(hook=SourceFixtures(os.path.join(fixtures_root, s["site_id"])), transport=None)
        try: res = osm.fetch_ways(client, s["lat"], s["lon"], cfg)
        except (MissingFixtureError, SourceError) as e:
            rows.append({**base, "error": f"no fixture ({type(e).__name__})"}); continue
        ways = res.ways
        if not ways: rows.append({**base, "error": "no way within the radius", "ways_in_radius": 0}); continue
        dist = sorted(((osm.point_to_polyline((0.0, 0.0), w.points)[0], w) for w in ways), key=lambda x: (x[0], x[1].id))
        d, w = dist[0]; t = w.tags
        chk = BC.check_bearing((), ways, cfg=cfg)
        ref = chk.way_id if chk.status in (BC.NO_MARKS, BC.AGREE) else chk.status
        rows.append({**base, "way": w.id, "class": t.get("highway"), "name": t.get("name"), "ref": t.get("ref"), "distance_m": round(d, 1), "lanes": t.get("lanes"),
                     "lanes_forward": t.get("lanes:forward"), "lanes_backward": t.get("lanes:backward"), "oneway": t.get("oneway"), "maxspeed": t.get("maxspeed"),
                     "sidewalk": t.get("sidewalk") or t.get("sidewalk:both") or t.get("sidewalk:left") or t.get("sidewalk:right"),
                     "shoulder": t.get("shoulder") or t.get("shoulder:both") or t.get("shoulder:left") or t.get("shoulder:right"),
                     "surface": t.get("surface"), "width": t.get("width"), "ways_in_radius": len(ways), "reference_way": ref})
    return rows


TABLE_COLS = (("site", "site"), ("way", "nearest way"), ("class", "class"), ("name", "name"), ("ref", "ref"), ("distance_m", "distance to centreline m"), ("lanes", "lanes"),
              ("lanes_forward", "lanes:forward"), ("lanes_backward", "lanes:backward"), ("oneway", "oneway"), ("maxspeed", "maxspeed"), ("sidewalk", "sidewalk"),
              ("shoulder", "shoulder"), ("surface", "surface"), ("width", "width"), ("ways_in_radius", "ways in radius"), ("reference_way", "reference way by the work point"))


def render_table(rows):
    out = ["| " + " | ".join(h for _, h in TABLE_COLS) + " |", "| " + " | ".join("---" for _ in TABLE_COLS) + " |"]
    for r in rows:
        if "error" in r and "way" not in r:
            out.append(f"| {esc(r['site'])} | {esc(r['error'])} |" + " |" * (len(TABLE_COLS) - 2)); continue
        out.append("| " + " | ".join("-" if r.get(k) in (None, "") else esc(r[k]) for k, _ in TABLE_COLS) + " |")
    return "\n".join(out)


def fixture_files(fixtures_root, site_ids):
    out = []
    for sid in site_ids:
        d = os.path.join(fixtures_root, sid, "source")
        if os.path.isdir(d): out += [os.path.join(d, n) for n in sorted(os.listdir(d))]
    return out


def write_second_source(truth_sites, fixtures_root, path, cfg):
    import s06_osm_second_source as conv
    rows, notes = [], []
    for s in truth_sites:
        r, n = conv.row_for(s, fixtures_root, cfg); rows.append(r); notes += n
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=conv.COLUMNS); w.writeheader(); w.writerows(rows)
    return rows, notes


def accuracy_reports(run, truth, second, results_root, accuracy):
    """[(version, path or None, exit code, note)] one per results version. `accuracy` is the report's main()."""
    out = []
    for ver, folder in VERSIONS:
        root = os.path.join(results_root, folder)
        if not os.path.isdir(root):
            out.append((ver, None, None, f"{folder} does not exist" + (" (optional)" if ver == "v3" else ""))); continue
        dirs = [os.path.join(root, p) for p in PROFILES if os.path.isdir(os.path.join(root, p))]
        if not dirs: out.append((ver, None, None, f"{folder} has no profile folder for {', '.join(PROFILES)}")); continue
        path = os.path.join(run, f"accuracy_{ver}.md")
        buf = io.StringIO(); old = sys.stdout; sys.stdout = buf
        try: rc = accuracy(["--results", *dirs, "--truth", truth, "--second-source", second, "--out", path])
        finally: sys.stdout = old
        out.append((ver, path if os.path.isfile(path) else None, rc, buf.getvalue().strip()))
    return out


def report(run, started, env, diag_text, diag, records, table, second_path, second_rows, second_notes, accs, fixtures, failed_stage, args):
    L = [f"# OSM pipeline report, {started}", "", f"Run folder: `{run}`", f"Sites: `{args.sites}`; truth sites: `{args.truth_sites}`; truth: `{args.truth}`", ""]
    L += [f"**Result: {'STOPPED at ' + failed_stage if failed_stage else 'all stages passed'}**", ""]
    L += ["## 1. Environment, diagnose table and verdict", "", diag_text or "(diagnose did not run)", ""]
    L += ["## 2. Recorder results per site", ""]
    if records is None: L += ["(not run)", ""]
    else:
        L += ["| site | status | attempts | seconds | ways found | box half-sizes asked (m) | retry or shrink | error |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        L += [f"| {r['site_id']} | {r['status']} | {r['attempts']} | {r['seconds']} | {'-' if r['ways'] is None else r['ways']} | {', '.join(str(x) for x in (r.get('boxes') or [])) or '-'} | {r.get('note') or '-'} | {r['error'] or '-'} |" for r in records] + [""]
    L += ["## 3. second_source.csv", ""]
    if second_path is None: L += ["(not run)", ""]
    else: L += ["```", open(second_path, encoding="utf-8").read().strip(), "```", ""] + [f"- {esc(n)}" for n in second_notes] + [""]
    L += ["## 4. What OSM says at the work point of each site", "", table if table else "(not run)", ""]
    L += ["## 5. Accuracy reports (OSM as the second source)", ""]
    if accs is None: L += ["(not run)", ""]
    for ver, path, rc, note in accs or []:
        L += [f"### {ver}", ""]
        if path: L += [open(path, encoding="utf-8").read().strip(), ""]
        else: L += [f"not produced: {note}", ""]
        if rc not in (None, 0) and path is None: L += [f"(exit code {rc})", ""]
    L += ["## 6. Fixture files created", ""] + ([f"- `{f}`" for f in fixtures] if fixtures else ["- none"]) + [""]
    up = [os.path.join(run, "REPORT.md"), os.path.join(run, "diagnose.md")]
    if second_path: up.append(second_path)
    up += [p for _, p, _, _ in (accs or []) if p]
    L += ["## 7. Files to upload", ""] + [f"- `{u}`" for u in up] + [""]
    return "\n".join(L) + "\n"


def main(argv=None, runners=None, transport=None, accuracy=None, clock=time.monotonic, sleep=time.sleep, now=None, fixtures_root=None, results_root=None, limit_transport=False):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", required=True); ap.add_argument("--truth-sites", required=True); ap.add_argument("--truth", required=True)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "var", "s06_osm_pipeline")); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    import s06_osm_diagnose as D
    import s06_record_osm as REC
    from s06_call1_check import SitesError, read_sites
    from tcp_planner.data_sources.base import load_sources, requests_transport
    from tcp_planner.site_model.site_config import load_site_config, setting
    sites_path, truth_sites_path, truth_path = resolve(a.sites), resolve(a.truth_sites), resolve(a.truth)
    try: sites, truth_sites = read_sites(sites_path), read_sites(truth_sites_path)
    except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
    if not os.path.isfile(truth_path): print(f"truth file not found: {truth_path}"); return 2
    cfg, sources = load_site_config(), load_sources()
    fixtures_root = fixtures_root or REC.DEFAULT_OUT; results_root = results_root or os.path.join(ROOT, "var")
    a.sites, a.truth_sites, a.truth = sites_path, truth_sites_path, truth_path
    if a.dry_run:
        print(f"[dry run] run folder would be {a.out_dir}\\<timestamp>")
        print(f"  stage 1 diagnose: at most {setting('osm_diagnose', 'max_requests', cfg)[0]} requests for site {sites[0]['site_id']}, passes if the project path answers 200 with JSON in under {setting('osm_diagnose', 'pass_s', cfg)[0]} s")
        print(f"  stage 2 record: {len(sites)} Overpass quer{'y' if len(sites) == 1 else 'ies'} ({', '.join(s['site_id'] for s in sites)}), retries {setting('osm', 'retry_waits_s', cfg)[0]} s, recorded sites skipped")
        print(f"  stage 3 second_source.csv for {', '.join(s['site_id'] for s in truth_sites)}; stage 4 OSM table; stage 5 accuracy on {', '.join(f for _, f in VERSIONS)} with {', '.join(PROFILES)}; stage 6 REPORT.md")
        print("nothing was requested")
        return 0
    if os.environ.get("TCP_LIVE") != "1" and runners is None: print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2
    provider = D.provider_of(cfg)
    limited = None
    if provider == "osm_api" and (transport is None or limit_transport):
        base = transport or requests_transport
        limited = LimitedTransport(base, setting("osm_diagnose", "api_max_requests", cfg)[0], setting("osm_diagnose", "api_min_gap_s", cfg)[0],
                                   setting("osm_diagnose", "stop_statuses", cfg)[0], clock, sleep)
        transport = limited
    if runners is None:
        from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
        load_env_file(); use_os_trust_store()
        transport = transport or requests_transport
        runners = D.real_runners(sites[0], cfg, sources, transport)
    transport = transport or requests_transport
    if callable(runners): runners = runners(sites[0], cfg, sources, transport)           # a factory: the runners share this run's (limited) transport
    stop = (lambda: limited.stop_reason) if limited else None
    if accuracy is None:
        import s06_accuracy_report as ACC; accuracy = ACC.main
    started = (now or datetime.datetime.now()).isoformat(timespec="seconds")
    run = D.run_dir(a.out_dir, now)
    state = dict(diag_text=None, diag=None, records=None, table=None, second_path=None, second_rows=None, second_notes=[], accs=None, fixtures=None)
    failed = None
    from tcp_planner.data_sources import osm as osm_mod
    env = D.environment(D.provider_url(cfg), sources)

    def finish():
        text = report(run, started, env, state["diag_text"], state["diag"], state["records"], state["table"], state["second_path"], state["second_rows"], state["second_notes"],
                      state["accs"], state["fixtures"], failed, a)
        with open(os.path.join(run, "REPORT.md"), "w", encoding="utf-8", newline="\n") as f: f.write(text)
        print(f"\nREPORT.md: {os.path.join(run, 'REPORT.md')}")
        return text

    # stage 1
    print("== stage 1: diagnose ==")
    outcome = D.run_diagnose(sites[0], runners, cfg, clock, sleep)
    state["diag"] = outcome
    state["diag_text"] = D.render(sites[0], outcome, D.environment(D.provider_url(cfg), sources), D.effective(sites[0], cfg, sources), started)
    with open(os.path.join(run, "diagnose.md"), "w", encoding="utf-8", newline="\n") as f: f.write(state["diag_text"])
    if not outcome["passed"]:
        failed = "stage 1 (diagnose)"
        print(f"STAGE 1 FAILED: the project path did not return HTTP 200 with parseable JSON in under {setting('osm_diagnose', 'pass_s', cfg)[0]} s.")
        print(f"VERDICT: {outcome['verdict']}: {outcome['why']}")
        if limited is not None and limited.stop_reason:
            print(f"The run stopped on {limited.stop_reason}." + (f" Page text: {limited.stop_page}" if limited.stop_page else ""))
        print("Nothing else was requested. Send REPORT.md.")
        finish(); return 1
    print("stage 1 passed")
    # stage 2
    print("== stage 2: record the OSM fixtures ==")
    records = REC.record_sites(sites, fixtures_root, transport, sleep, cfg=cfg, clock=clock, stop=stop)
    state["records"] = records; state["fixtures"] = fixture_files(fixtures_root, [s["site_id"] for s in sites])
    bad = [r for r in records if r["status"] in ("failed", "not_attempted")]
    if bad:
        failed = "stage 2 (record)"
        print(f"STAGE 2 FAILED for {', '.join(r['site_id'] for r in bad)}: {bad[0]['error'] or bad[0]['status']}."
              + (f" The run stopped: {limited.stop_reason}" + (f"; page text: {limited.stop_page}" if limited.stop_page else "") if limited and limited.stop_reason else "") + " Send REPORT.md.")
        finish(); return 1
    # stage 3
    print("== stage 3: second_source.csv ==")
    state["second_path"] = os.path.join(run, "second_source.csv")
    state["second_rows"], state["second_notes"] = write_second_source(truth_sites, fixtures_root, state["second_path"], cfg)
    print(f"wrote {state['second_path']}")
    # stage 4
    print("== stage 4: what OSM says at each work point ==")
    state["table"] = render_table(osm_table(sites, fixtures_root, cfg)); print(state["table"])
    # stage 5
    print("== stage 5: accuracy reports ==")
    state["accs"] = accuracy_reports(run, truth_path, state["second_path"], results_root, accuracy)
    for ver, path, rc, note in state["accs"]: print(f"  {ver}: {path or 'not produced'}" + (f" ({note})" if not path else ""))
    if any(rc not in (None, 0) for _, _, rc, _ in state["accs"]):
        failed = "stage 5 (accuracy)"; print("STAGE 5 FAILED: the accuracy report returned an error; see the notes in REPORT.md.")
    # stage 6
    print("== stage 6: REPORT.md ==")
    finish()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
