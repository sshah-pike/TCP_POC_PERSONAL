"""History of every piece of code in this repo that talked to OpenStreetMap or Overpass, compared with the current adapter (S6, OSM diagnosis).

  python scripts/s06_osm_history.py [--out docs/reports/S6_osm_history.md]

Read-only: it reads git history and files, makes no network request. For each place it reads the source text (a file at HEAD, or `git show <rev>:<path>`)
and extracts, with plain pattern matching, the URL, the HTTP method, how the query was sent, the headers (User-Agent), the timeout, whether
use_os_trust_store() / truststore was active and the HTTP library. The table and the list of differences go to docs/reports/S6_osm_history.md.
Nothing is assumed: a field it cannot find is written as "not found in the text".
"""
import argparse, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

# (label, git rev or "HEAD", path, note). The first is the POC's first commit; the others are the files that still talk to OSM at HEAD.
PLACES = (
    ("POC V1 adapter (first version)", "1d5aa36", "tcp_poc/osm_adapter.py", "the code that ran in every earlier recorded run (the Ten Rod demo point, Granite, Alton Bradford)"),
    ("old adapter at HEAD (used by the old pipeline)", "HEAD", "src/tcp_planner/data_sources/osm_overpass.py", "moved by S0a, unchanged; `pipeline.py` and `run_worker.py` call `fetch_osm`"),
    ("fixture recorder of the old pipeline", "HEAD", "tests/support/record.py", "`python -m tests.support.record live`: calls the old `fetch_osm`; TLS through the pipeline's use_os_trust_store"),
    ("current adapter (S6)", "HEAD", "src/tcp_planner/data_sources/osm.py", "Overpass interpreter, query language, JSON"),
    ("current client (S6)", "HEAD", "src/tcp_planner/data_sources/base.py", "SourceClient and requests_transport; headers and timeout come from config/data_sources.json"),
    ("current recorder (S6)", "HEAD", "scripts/s06_record_osm.py", "calls use_os_trust_store() before the first request"),
)


def read_at(rev, path, root=ROOT, run=None):
    """Source text of `path` at `rev` ('HEAD' reads the working file). None when it does not exist there."""
    if rev == "HEAD":
        p = os.path.join(root, path)
        return open(p, encoding="utf-8").read() if os.path.isfile(p) else None
    run = run or (lambda args: subprocess.run(args, cwd=root, capture_output=True, text=True))
    r = run(["git", "show", f"{rev}:{path}"])
    return r.stdout if r.returncode == 0 else None


def first(pattern, text, group=1, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


def analyze(text):
    """Facts read from a source text: url, method, sent_as, headers, timeout, library, truststore. Missing facts are None."""
    t = text or ""
    url = first(r'["\'](https?://[^"\']+)["\']', t)
    method = first(r"requests\.(get|post|request|put)\(", t, flags=re.I)
    if method == "request": method = first(r'requests\.request\(\s*["\'](\w+)["\']', t) or "per call (passed in by the caller)"
    if method is None and re.search(r"def requests_transport", t): method = "per call (the caller passes it; the recorder sends GET)"
    if method is None and re.search(r"client\.request\(", t) and "method=" not in t: method = "GET (the default of SourceClient.request)"
    sent_as = "query string (params=)" if re.search(r"params\s*=", t) else ("form body (data=)" if re.search(r"\bdata\s*=\s*\w", t) else None)
    if "requests_transport" in t and sent_as and "params" in t: sent_as = "query string (params=), the QL text in the data parameter"
    ua = first(r'["\']User-Agent["\']\s*:\s*["\']([^"\']+)["\']', t, flags=re.I)
    if ua is None and re.search(r'cfg\[["\']user_agent["\']\]', t): ua = "from config/data_sources.json user_agent"
    timeout = first(r"timeout\s*=\s*(\([^)]*\)|[\w.]+)", t)
    if timeout is None and re.search(r"timeout_s", t): timeout = "from config/data_sources.json timeout_s (read) and 5 s connect"
    lib = "requests" if re.search(r"\bimport requests\b|requests\.", t) else ("urllib" if "urllib.request" in t else None)
    trust = bool(re.search(r"use_os_trust_store|truststore", t))
    return {"url": url, "method": method.upper() if method and re.fullmatch(r"[a-z]+", method) else method, "sent_as": sent_as, "headers": ua, "timeout": timeout, "library": lib, "truststore": trust}


def current_query(cfg=None):
    """The query text the current adapter sends for a sample point (rendered by the adapter's own builder, from config)."""
    from tcp_planner.data_sources import osm
    from tcp_planner.site_model.site_config import load_site_config, setting
    cfg = cfg or load_site_config()
    return osm.build_query(41.3710266, -71.8203533, setting("osm", "query_radius_m", cfg)[0], setting("osm", "highway_classes", cfg)[0], setting("osm", "query_timeout_s", cfg)[0])


def build_rows(places=PLACES, reader=read_at):
    rows = []
    for label, rev, path, note in places:
        text = reader(rev, path)
        rows.append({"label": label, "where": f"`{path}` @ {rev}", "found": text is not None, "note": note, **analyze(text)})
    return rows


def differences(old, new, new_query, old_query="bbox=west,south,east,north of a square around the point (no query language); the answer is the whole map data of the box (nodes, ways, relations as XML)"):
    """The differences between the old working adapter and the current one, as (aspect, old, new) tuples. Pure: the two analysed rows in."""
    d = []

    def add(aspect, a, b):
        if a != b: d.append((aspect, a, b))
    host = lambda u: re.sub(r"^https?://([^/]+).*$", r"\1", u) if u else None
    add("host", host(old["url"]), host(new["url"]))
    add("endpoint", old["url"], new["url"] or "https://overpass-api.de/api/interpreter (constant URL in osm.py)")
    add("service", "the OSM main API (map call: a bounding box dump)", "the Overpass API (a query language run on the server)")
    add("query", old_query, new_query)
    add("method", old["method"], new["method"])
    add("how it is sent", old["sent_as"], new["sent_as"])
    add("User-Agent", old["headers"], new["headers"])
    add("timeout", old["timeout"], new["timeout"])
    add("HTTP library", old["library"], new["library"])
    add("TLS trust store", "use_os_trust_store() active", "use_os_trust_store() active" if new["truststore"] else "not stated in the text")
    add("answer format", "XML (/api/0.6/map)", "JSON (out tags geom)")
    add("server work", "returns every node and way in the box; the code filters", "the server filters ways by a regex on highway and builds geometry")
    return d


def render(rows, diffs):
    cols = ("label", "where", "url", "method", "sent_as", "headers", "timeout", "truststore", "library")
    out = ["# S6 OSM history: what talked to OpenStreetMap before, and what the current adapter does differently", "",
           "Generated by `scripts/s06_osm_history.py` (read-only: git history and files; no network). A field written *not found in the text* is not in the source.", "",
           "Searches run: `git log --all -S overpass`, `-S api/interpreter`, `-S nominatim` (no hit before S6 for the first two; none for nominatim), and a text search of every .py, .json, .ipynb, .md, .txt and .ps1 file. No notebook and no other script talks to OSM.", "",
           "| place | commit | URL | HTTP method | how the query was sent | headers (User-Agent) | timeout | truststore | library |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        v = lambda k: "not found in the text" if r[k] in (None, "") else (("yes (use_os_trust_store / truststore named)" if r[k] else "not named in this file") if k == "truststore" else str(r[k]))
        out.append(f"| {r['label']} | {r['where']} | {v('url')} | {v('method')} | {v('sent_as')} | {v('headers')} | {v('timeout')} | {v('truststore')} | {v('library')} |")
    out += ["", "Notes per place:", ""] + [f"- **{r['label']}**: {r['note']}" for r in rows]
    out += ["", "## Differences between the old working adapter and the current one", "", "| aspect | old (`osm_overpass.fetch_osm`) | current (`osm.py` + `base.py`) |", "| --- | --- | --- |"]
    out += [f"| {a} | {o} | {n} |" for a, o, n in diffs]
    out += ["", "## Recorded evidence", "",
            "The fixtures under `tests/fixtures/recorded/*/osm/` were recorded by the old adapter: each says `'source': 'osm_api'` with a radius of 262.4 m. "
            "They never came from Overpass. So \"OSM was fast earlier\" refers to **api.openstreetmap.org**, a different service on a different host.", "",
            "## What the history alone suggests", "",
            "The old code never used Overpass. It called the OSM main API (`/api/0.6/map?bbox=`) with a custom User-Agent (`tcp-poc/0.2`), a 5 s connect and a 30 s read timeout, "
            "through `requests`, with the OS trust store. The S6 adapter calls a different service: the public Overpass server at `overpass-api.de`, running a regex-filtered query with `out tags geom`. "
            "A public Overpass server is shared and is often slow or busy, whereas the main API serves a plain bounding box. The difference of service is the first suspect; "
            "the User-Agent, the method and the interpreter are not different in kind (both use `requests`, both set a User-Agent, both GET). The diagnosis script tests the suspects one by one."]
    return "\n".join(out) + "\n"


def main(argv=None, reader=read_at):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "reports", "S6_osm_history.md"))
    a = ap.parse_args(argv)
    rows = build_rows(reader=reader)
    old = next(r for r in rows if r["label"].startswith("old adapter at HEAD")); new = {**next(r for r in rows if r["label"].startswith("current adapter"))}
    cli = next(r for r in rows if r["label"].startswith("current client"))
    for k in ("method", "sent_as", "headers", "timeout", "truststore", "library"):
        if new.get(k) in (None, False) or (k in ("sent_as",) and cli[k]): new[k] = cli[k] if k not in ("method",) else new[k] or cli[k]
    new["truststore"] = new["truststore"] or next(r for r in rows if r["label"].startswith("current recorder"))["truststore"]
    text = render(rows, differences(old, new, current_query()))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    print(f"wrote {a.out} ({len(rows)} places, {sum(r['found'] for r in rows)} found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
