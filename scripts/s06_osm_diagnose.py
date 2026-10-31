"""Owner-run diagnosis of the Overpass read timeout (S6, OSM diagnosis). Needs TCP_LIVE=1; talks to overpass-api.de only.

  python scripts/s06_osm_diagnose.py --sites sites_v0.csv --dry-run          prints what would be requested; runs nothing
  $env:TCP_LIVE = "1"
  python scripts/s06_osm_diagnose.py --sites sites_v0.csv                    one site (the first row, or --site ID), nine requests

At most `osm_diagnose.max_requests` (14) requests in total, at least `osm_diagnose.min_gap_s` (8) seconds between them, and it stops at the first
HTTP 429 and says so. Variants, each run once, for ONE site:
  a the project's own SourceClient path, exactly as the recorder calls it     b plain requests GET, the library's default User-Agent
  c plain requests GET, the project's User-Agent                               d plain requests POST (data=), default User-Agent
  e urllib.request GET                                                          f the SIMPLE query (way(around:R,lat,lon)[highway];out tags;)
  g the project query with 'out tags;' instead of 'out tags geom;'              h PowerShell Invoke-WebRequest of the same URL (Windows only)
  i /api/status (its full text: rate limit and free slots)
It prints a table (variant, HTTP status, bytes, connect s, first byte s, total s, error type), the environment (interpreter, OpenSSL, requests and
urllib3 versions, proxy variables and the OS proxy settings, IPv4 and IPv6 resolution and which one the connection used, whether truststore is
injected) and a VERDICT. The whole output is saved to var/s06_osm_pipeline/<timestamp>/diagnose.md. Nothing is changed: no proxy, no setting, no
environment variable; certificate verification stays on; no key or token is printed (there is none).
Calls use_os_trust_store() first, like every live script of the project.
"""
import argparse, datetime, json, os, platform, socket, ssl, subprocess, sys, time
from urllib.parse import quote, urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT, os.path.join(ROOT, "scripts")]
VARIANTS = (("a", "project SourceClient path (as the recorder calls it)"), ("b", "requests GET, default User-Agent"), ("c", "requests GET, project User-Agent"),
            ("d", "requests POST (data=), default User-Agent"), ("e", "urllib.request GET"), ("f", "SIMPLE query, requests GET"),
            ("g", "project query with 'out tags;', requests GET"), ("h", "PowerShell Invoke-WebRequest (control)"), ("i", "/api/status"))


class BudgetExceeded(Exception): pass


class Stop429(Exception): pass


class Budget:
    """Counts requests against the limit and keeps the minimum gap between them (clock and sleep are injected, so tests use a fake clock)."""
    def __init__(self, max_requests, min_gap_s, clock=time.monotonic, sleep=time.sleep):
        self.max, self.gap, self.clock, self.sleep, self.count, self.last_end = max_requests, min_gap_s, clock, sleep, 0, None

    def take(self):
        if self.count >= self.max: raise BudgetExceeded(f"request limit of {self.max} reached")
        if self.last_end is not None:
            wait = self.gap - (self.clock() - self.last_end)
            if wait > 0: self.sleep(wait)
        self.count += 1

    def done(self): self.last_end = self.clock()


def result(variant, status=None, nbytes=None, connect=None, first=None, total=None, error=None, json_ok=None, text=None, peer=None):
    return {"variant": variant, "status": status, "bytes": nbytes, "connect_s": connect, "first_byte_s": first, "total_s": total, "error": error,
            "json_ok": json_ok, "text": text, "peer": peer}


def is_slow(r, slow_s):
    return r is not None and (r["error"] is not None or r["status"] != 200 or (r["total_s"] is not None and r["total_s"] > slow_s))


def is_fast(r, slow_s):
    return r is not None and r["error"] is None and r["status"] == 200 and r["total_s"] is not None and r["total_s"] <= slow_s


def status_has_free_slot(text):
    """True when /api/status says a slot is free, False when it says none is, None when the text does not say."""
    t = (text or "").lower()
    if "slot available after" in t or "0 slots available now" in t: return False
    if "slots available now" in t or "slot available now" in t: return True
    return None


def verdict(results, slow_s):
    """(primary verdict, [all matching], explanation). Rules, in this priority order:
    project path slow but plain requests fast -> our client code; project UA slow but default fast -> User-Agent; full query slow but simple fast ->
    query shape (g tells highway filter from out geom); GET slow but POST fast -> method; requests slow but urllib or PowerShell fast -> library or
    interpreter; everything slow and the status shows no free slots -> server busy; everything slow and the status fine -> network; all fast -> not reproduced."""
    R = {r["variant"]: r for r in results}
    if any(r["status"] == 429 for r in results): return "rate limited (HTTP 429)", ["rate limited"], "the server answered HTTP 429: the run stopped; wait and rerun later"
    a, b, c, d, e, f, g, h, i = (R.get(k) for k in "abcdefghi")
    slow = lambda r: is_slow(r, slow_s); fast = lambda r: is_fast(r, slow_s)
    query_variants = [r for r in (a, b, c, d, e, f, g, h) if r is not None]
    if query_variants and all(fast(r) for r in query_variants): return "not reproduced now", ["not reproduced now"], "every variant answered fast: the earlier stall did not happen now"
    out = []
    if slow(a) and (fast(b) or fast(c)): out.append(("our client code", "the project path is slow while plain requests with the same query are fast"))
    if slow(c) and fast(b): out.append(("User-Agent", "the project User-Agent is slow while the library's default User-Agent is fast"))
    if (slow(b) or slow(c)) and fast(f):
        shape = ("which part is not known (variant g did not run)" if g is None else "the highway filter or the query text (the same query with 'out tags;' is also slow)" if slow(g)
                 else "the out geom part (the same query with 'out tags;' is fast)")
        out.append(("query shape", f"the full query is slow while the simple query is fast; cause is most likely {shape}"))
    if slow(b) and fast(d): out.append(("method", "GET is slow while POST is fast"))
    if slow(b) and (fast(e) or fast(h)): out.append(("library or interpreter", "requests is slow while urllib or PowerShell is fast"))
    if query_variants and all(slow(r) for r in query_variants):
        free = status_has_free_slot(i["text"] if i else None)
        if free is False: out.append(("server busy", "everything is slow and /api/status shows no free slot"))
        else: out.append(("network", "everything is slow and /api/status does not show a busy server" if free else "everything is slow and /api/status gives no slot information"))
    if not out: return "inconclusive", [], "the variants disagree in a way the table does not cover; send the report"
    return out[0][0], [o[0] for o in out], "; ".join(o[1] for o in out)


def passed(results, pass_s):
    """Stage 1 of the pipeline: the project path returned HTTP 200 with parseable JSON in under `pass_s` seconds."""
    a = next((r for r in results if r["variant"] == "a"), None)
    return bool(a and a["error"] is None and a["status"] == 200 and a["json_ok"] and a["total_s"] is not None and a["total_s"] < pass_s)


# ---------------------------------------------------------------- the real runners (used only in a live run)
def _patch_connect(record):
    """Time every TCP connect urllib3 or http.client makes while active; returns an undo function. Records (seconds, peer family)."""
    import urllib3.util.connection as uc
    orig_u, orig_s = uc.create_connection, socket.create_connection

    def wrap(orig):
        def f(*a, **k):
            t = time.perf_counter(); sock = orig(*a, **k); record.append((time.perf_counter() - t, sock.getpeername()[0])); return sock
        return f
    uc.create_connection, socket.create_connection = wrap(orig_u), wrap(orig_s)

    def undo(): uc.create_connection, socket.create_connection = orig_u, orig_s
    return undo


def _json_ok(content):
    try: json.loads(content); return True
    except (ValueError, TypeError): return False


def timed_requests(variant, method, url, *, params=None, data=None, headers=None, read_timeout, connect_timeout):
    import requests
    rec = []; undo = _patch_connect(rec); t0 = time.perf_counter(); first = None
    try:
        r = requests.request(method, url, params=params, data=data, headers=headers, timeout=(connect_timeout, read_timeout), stream=True)
        first = time.perf_counter() - t0
        body = r.content
        return result(variant, r.status_code, len(body), rec[0][0] if rec else None, first, time.perf_counter() - t0, None, _json_ok(body) if variant != "i" else None,
                      body.decode("utf-8", "replace") if variant == "i" else None, rec[0][1] if rec else None)
    except Exception as e:
        return result(variant, None, None, rec[0][0] if rec else None, first, time.perf_counter() - t0, type(e).__name__, peer=rec[0][1] if rec else None)
    finally: undo()


def timed_urllib(variant, url, read_timeout):
    import urllib.request
    rec = []; undo = _patch_connect(rec); t0 = time.perf_counter(); first = None
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=read_timeout) as r:
            first = time.perf_counter() - t0; body = r.read(); status = r.status
        return result(variant, status, len(body), rec[0][0] if rec else None, first, time.perf_counter() - t0, None, _json_ok(body), peer=rec[0][1] if rec else None)
    except Exception as e:
        status = getattr(e, "code", None)
        return result(variant, status, None, rec[0][0] if rec else None, first, time.perf_counter() - t0, type(e).__name__, peer=rec[0][1] if rec else None)
    finally: undo()


def timed_powershell(variant, url, read_timeout):
    ps = ("$sw=[Diagnostics.Stopwatch]::StartNew(); try { $r=Invoke-WebRequest -UseBasicParsing -Uri '" + url.replace("'", "''") + "' -TimeoutSec " + str(int(read_timeout)) +
          "; Write-Output ('STATUS=' + $r.StatusCode + ' BYTES=' + $r.RawContentLength + ' SECONDS=' + $sw.Elapsed.TotalSeconds) } catch { Write-Output ('ERROR=' + $_.Exception.GetType().Name + ' SECONDS=' + $sw.Elapsed.TotalSeconds) }")
    t0 = time.perf_counter()
    try: p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=read_timeout + 30)
    except Exception as e: return result(variant, None, None, None, None, time.perf_counter() - t0, type(e).__name__)
    out = p.stdout.strip(); kv = dict(x.split("=", 1) for x in out.split() if "=" in x)
    secs = float(kv["SECONDS"]) if "SECONDS" in kv else time.perf_counter() - t0
    if "STATUS" in kv: return result(variant, int(kv["STATUS"]), int(kv.get("BYTES", 0) or 0), None, None, secs, None)
    return result(variant, None, None, None, None, secs, kv.get("ERROR", "PowerShellError"))


def queries(site, cfg):
    from tcp_planner.data_sources import osm
    from tcp_planner.site_model.site_config import setting
    r = setting("osm", "query_radius_m", cfg)[0]; t = setting("osm", "query_timeout_s", cfg)[0]
    full = osm.build_query(site["lat"], site["lon"], r, setting("osm", "highway_classes", cfg)[0], t)
    simple = f"[out:json][timeout:{t:g}];way(around:{r:g},{site['lat']:.7f},{site['lon']:.7f})[highway];out tags;"
    return {"full": full, "simple": simple, "no_geom": full.replace("out tags geom;", "out tags;"), "radius": r}


def real_runners(site, cfg, sources):
    """{variant: callable() -> result} for a live run. Each makes exactly one request."""
    from tcp_planner.data_sources import osm
    from tcp_planner.data_sources.base import SourceClient, requests_transport
    from tcp_planner.site_model.site_config import setting
    q = queries(site, cfg); ua = sources["user_agent"]; url = osm.URL
    ct, rt = setting("osm_diagnose", "connect_timeout_s", cfg)[0], setting("osm_diagnose", "read_timeout_s", cfg)[0]
    get_url = lambda text: url + "?" + urlencode({"data": text})
    status_url = url.replace("/interpreter", "/status")

    def a():
        box = {}; rec = []

        def transport(method, u, params, body, headers, timeout):
            undo = _patch_connect(rec); t0 = time.perf_counter()
            try: st, content = requests_transport(method, u, params, body, headers, timeout)
            finally: undo()
            box.update(status=st, bytes=len(content), total=time.perf_counter() - t0, json=_json_ok(content)); return st, content
        from tcp_planner.data_sources.base import SourceError
        t0 = time.perf_counter()
        try: osm.fetch_ways(SourceClient(sources=sources, transport=transport), site["lat"], site["lon"], cfg)
        except SourceError as e:
            return result("a", (e.details or {}).get("http_status"), box.get("bytes"), rec[0][0] if rec else None, None, time.perf_counter() - t0, e.code, box.get("json"),
                          peer=rec[0][1] if rec else None)
        return result("a", box["status"], box["bytes"], rec[0][0] if rec else None, None, box["total"], None, box["json"], peer=rec[0][1] if rec else None)
    return {
        "a": a,
        "b": lambda: timed_requests("b", "GET", url, params={"data": q["full"]}, read_timeout=rt, connect_timeout=ct),
        "c": lambda: timed_requests("c", "GET", url, params={"data": q["full"]}, headers={"User-Agent": ua}, read_timeout=rt, connect_timeout=ct),
        "d": lambda: timed_requests("d", "POST", url, data={"data": q["full"]}, read_timeout=rt, connect_timeout=ct),
        "e": lambda: timed_urllib("e", get_url(q["full"]), rt),
        "f": lambda: timed_requests("f", "GET", url, params={"data": q["simple"]}, read_timeout=rt, connect_timeout=ct),
        "g": lambda: timed_requests("g", "GET", url, params={"data": q["no_geom"]}, read_timeout=rt, connect_timeout=ct),
        "h": (lambda: timed_powershell("h", get_url(q["full"]), rt)) if sys.platform == "win32" else None,
        "i": lambda: timed_requests("i", "GET", status_url, read_timeout=rt, connect_timeout=ct),
    }


# ---------------------------------------------------------------- environment, run, render
def environment(url, sources):
    import urllib.request, urllib3
    try: import requests; rv = requests.__version__; env_proxies = requests.utils.get_environ_proxies(url)
    except Exception: rv, env_proxies = "not installed", {}
    host = url.split("/")[2]
    try: infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP); fam = sorted({("IPv6" if i[0] == socket.AF_INET6 else "IPv4", i[4][0]) for i in infos})
    except OSError as e: fam = [("error", type(e).__name__)]
    ts = ssl.SSLContext.__module__.startswith("truststore")
    return {"python": sys.version.replace("\n", " "), "venv_base_interpreter": getattr(sys, "_base_executable", None) or sys.base_prefix, "prefix": sys.prefix,
            "platform": platform.platform(), "openssl": ssl.OPENSSL_VERSION, "requests": rv, "urllib3": urllib3.__version__,
            "HTTP_PROXY": os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"), "HTTPS_PROXY": os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
            "NO_PROXY": os.environ.get("NO_PROXY") or os.environ.get("no_proxy"), "os_proxies_urllib_getproxies": urllib.request.getproxies(),
            "requests_environ_proxies_for_url": env_proxies, "dns": [f"{k} {v}" for k, v in fam], "truststore_injected": ts, "host": host}


def effective(site, cfg, sources):
    from tcp_planner.data_sources import osm
    from tcp_planner.site_model.site_config import setting
    return {"variant a": "project SourceClient path", "url": osm.URL, "method": "GET", "sent_as": "query string, parameter data=<Overpass QL>", "query": queries(site, cfg)["full"],
            "headers": {"User-Agent": sources["user_agent"]}, "timeout (connect, read) s": (5, sources["sources"]["osm_overpass"]["timeout_s"]),
            "query timeout_s (server side)": setting("osm", "query_timeout_s", cfg)[0]}


def run_diagnose(site, runners, cfg, clock=time.monotonic, sleep=time.sleep, log=print):
    """Run the variants in order a..i with the request limit and the gap. Returns {results, verdict, all, why, passed, stopped, status_text}."""
    from tcp_planner.site_model.site_config import setting
    budget = Budget(setting("osm_diagnose", "max_requests", cfg)[0], setting("osm_diagnose", "min_gap_s", cfg)[0], clock, sleep)
    slow_s, pass_s = setting("osm_diagnose", "slow_s", cfg)[0], setting("osm_diagnose", "pass_s", cfg)[0]
    results, stopped = [], None
    for key, label in VARIANTS:
        fn = runners.get(key)
        if fn is None:
            log(f"variant {key} ({label}): skipped (not available here)"); continue
        try: budget.take()
        except BudgetExceeded as e: stopped = str(e); log(f"STOP: {e}"); break
        log(f"variant {key}: {label} ...")
        r = fn(); budget.done(); results.append(r)
        log(f"  -> status {r['status']}, {r['bytes']} bytes, total {r['total_s'] if r['total_s'] is None else round(r['total_s'], 2)} s, error {r['error']}")
        if r["status"] == 429: stopped = f"HTTP 429 at variant {key}"; log(f"STOP: {stopped}: the server asks us to slow down; nothing more is requested"); break
    v, allv, why = verdict(results, slow_s)
    i = next((r for r in results if r["variant"] == "i"), None)
    return {"results": results, "verdict": v, "all": allv, "why": why, "passed": passed(results, pass_s), "stopped": stopped, "status_text": i["text"] if i else None,
            "requests_made": budget.count}


def fmt(x, nd=2): return "-" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def render(site, outcome, env, eff, started):
    L = [f"# OSM diagnosis, {started}", "", f"Site: `{site['site_id']}` (lat {site['lat']}, lon {site['lon']}). Requests made: {outcome['requests_made']}.", "",
         "| variant | what | HTTP status | bytes | connect s | first byte s | total s | error type |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    labels = dict(VARIANTS)
    for r in outcome["results"]:
        L.append(f"| {r['variant']} | {labels[r['variant']]} | {fmt(r['status'])} | {fmt(r['bytes'])} | {fmt(r['connect_s'])} | {fmt(r['first_byte_s'])} | {fmt(r['total_s'])} | {fmt(r['error'])} |")
    L += ["", f"**VERDICT: {outcome['verdict']}**", "", outcome["why"] + (f" (all matching: {', '.join(outcome['all'])})" if len(outcome["all"]) > 1 else ""), ""]
    if outcome["stopped"]: L += [f"Stopped: {outcome['stopped']}", ""]
    L += [f"Stage 1 test (project path HTTP 200, parseable JSON, under the pass time): **{'PASS' if outcome['passed'] else 'FAIL'}**", "",
          "## Effective settings of variant a", ""] + [f"- {k}: {v}" for k, v in eff.items()]
    L += ["", "## Environment", ""] + [f"- {k}: {v}" for k, v in env.items()]
    peers = sorted({r["peer"] for r in outcome["results"] if r.get("peer")})
    L += [f"- address the connections used: {', '.join(peers) if peers else 'not recorded'}", ""]
    if outcome["status_text"]: L += ["## /api/status (full text)", "", "```", outcome["status_text"].strip(), "```", ""]
    return "\n".join(L) + "\n"


def run_dir(base, now=None):
    d = os.path.join(base, (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")); os.makedirs(d, exist_ok=True); return d


def main(argv=None, runners=None, clock=time.monotonic, sleep=time.sleep, run_directory=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites", required=True); ap.add_argument("--site"); ap.add_argument("--out-dir", default=os.path.join(ROOT, "var", "s06_osm_pipeline"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from s06_call1_check import SitesError, read_sites
    from tcp_planner.data_sources.base import load_sources
    from tcp_planner.site_model.site_config import load_site_config, setting
    try: sites = read_sites(a.sites)
    except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
    site = next((s for s in sites if s["site_id"] == a.site), None) if a.site else sites[0]
    if site is None: print(f"site {a.site!r} is not in {a.sites}"); return 2
    cfg, sources = load_site_config(), load_sources()
    if a.dry_run:
        print(f"[dry run] site {site['site_id']}: at most {setting('osm_diagnose', 'max_requests', cfg)[0]} requests, at least {setting('osm_diagnose', 'min_gap_s', cfg)[0]} s apart, stop on HTTP 429")
        for k, label in VARIANTS: print(f"  variant {k}: {label}" + ("  (Windows only)" if k == "h" else ""))
        for k, v in effective(site, cfg, sources).items(): print(f"  {k}: {v}")
        print("nothing was requested")
        return 0
    if os.environ.get("TCP_LIVE") != "1" and runners is None: print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2
    if runners is None:
        from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
        load_env_file(); use_os_trust_store(); runners = real_runners(site, cfg, sources)
    started = datetime.datetime.now().isoformat(timespec="seconds")
    outcome = run_diagnose(site, runners, cfg, clock, sleep)
    from tcp_planner.data_sources import osm
    text = render(site, outcome, environment(osm.URL, sources), effective(site, cfg, sources), started)
    d = run_directory or run_dir(a.out_dir)
    with open(os.path.join(d, "diagnose.md"), "w", encoding="utf-8", newline="\n") as f: f.write(text)
    print("\n" + text); print(f"saved {os.path.join(d, 'diagnose.md')}")
    return 0 if outcome["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
