"""S6 call 1 model check: the same 9 calls (3 sites x 3 repetitions) on one deployment, or call 1 on any sites you list. OWNER only.

  PowerShell, from the repo root:
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --dry-run --only 1   no network: print the request body of call 1
  $env:TCP_LIVE = "1"
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --only 1             call 1 alone
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --from 2             calls 2 to 9 (no --only/--from: all 9)
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --summary            table rows from the saved results
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --parallel 3         D-104: 3 calls at once; prints wall time, per-call time,
                                                                               any 429 or error body (no call is skipped after an error)
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --sites sites.csv --reps 3     call 1 on every site of the csv, 3 times each

Then the same with --profile claude-opus-5-5. The nine calls: 1-3 Granite (north-south road) repetitions 1-3, 4-6 E Second St (east-west road) repetitions 1-3, 7-9 Colorado (diagonal road) repetitions 1-3. Each call prints the exact request body first (no key; every image shown as its
size and SHA-256), then the result. The run STOPS at the first API error and prints the HTTP status and the API's error body
(key-like strings removed). Results are saved under var/s06_call1_check/<profile>/ (not tracked by git).

--sites sites.csv   columns: site_id, lat, lon, extent_m. extent_m is the HALF extent in metres, as half_extent_m in the pipeline: the image
                    covers at least +/- extent_m around the point (212.4 gives the 1280 px, zoom 17 image of the spike, 0.45 m per pixel).
                    The wide image is fetched through the existing Azure Maps path (needs TCP_LIVE=1 and AZURE_MAPS_KEY) and stored write-once
                    under var/s06_sites/<site_id>/ (wide.jpg and wide.json). A site already stored with the same lat, lon and extent is NOT
                    fetched again; the same site_id with different values is refused (use a new site_id). Results are saved as
                    <site_id>_r<rep>.json in the profile's folder, ready for scripts/s06_accuracy_report.py (site_id = the truth csv site_id).
                    --dry-run fetches nothing: it prints the request body for stored sites and says which images would be fetched.
use_os_trust_store() runs first; certificate verification is never turned off. The script writes nothing to the repo's tracked files.
"""
import argparse, csv, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

SITES = ("granite", "second", "colorado")
INPUTS = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "inputs")
OUT = os.path.join(ROOT, "var", "s06_call1_check")
VERSION = 1          # prompt version of this run (--prompt-version); version N results go to var/s06_call1_check_vN/<profile>/, never over the version 1 files


def out_root():
    return OUT if VERSION == 1 else f"{OUT}_v{VERSION}"
SITES_STORE = os.path.join(ROOT, "var", "s06_sites")
CALLS = [(i + 1, SITES[i // 3], i % 3 + 1) for i in range(9)]   # (call number, site, repetition)
SITE_COLUMNS = ("site_id", "lat", "lon", "extent_m")
SITE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class SitesError(ValueError): pass


TA_SITUATION = {}          # site_id -> ta_situation from the optional sites csv column (filled by main; written into each result)


def read_sites(path):
    """[{site_id, lat, lon, extent_m}] from the csv; every problem is named with its line. Nothing is fetched."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in SITE_COLUMNS if c not in (rd.fieldnames or [])]
        if missing: raise SitesError(f"sites csv lacks columns: {', '.join(missing)} (needs {', '.join(SITE_COLUMNS)})")
        out, seen = [], set()
        for i, r in enumerate(rd, start=2):
            sid = (r["site_id"] or "").strip()
            if not SITE_ID.match(sid): raise SitesError(f"line {i}: site_id {sid!r} must be letters, digits, '_', '.' or '-' (at most 64)")
            if sid in seen: raise SitesError(f"line {i}: site_id {sid!r} appears twice")
            seen.add(sid)
            try: lat, lon, ext = float(r["lat"]), float(r["lon"]), float(r["extent_m"])
            except (TypeError, ValueError): raise SitesError(f"line {i} ({sid}): lat, lon and extent_m must be numbers")
            if not -85 <= lat <= 85 or not -180 <= lon <= 180: raise SitesError(f"line {i} ({sid}): lat/lon out of range")
            if not 20 <= ext <= 5000: raise SitesError(f"line {i} ({sid}): extent_m {ext} must be between 20 and 5000 (half extent in metres)")
            out.append({"site_id": sid, "lat": lat, "lon": lon, "extent_m": ext, "ta_situation": (r.get("ta_situation") or "").strip()})
    if not out: raise SitesError("sites csv has no rows")
    return out


def _site_store():
    from tcp_planner.storage.local_fs import LocalFsArtifactStore
    return LocalFsArtifactStore(SITES_STORE)


def stored_site(site):
    """(image bytes, meta) when the site is stored with the SAME lat, lon and extent; None when it is not stored; SitesError when the
    id is stored with other values (stored images are never overwritten)."""
    if not os.path.isdir(SITES_STORE): return None                  # nothing stored yet (and a dry run creates nothing)
    store = _site_store(); key = f"{site['site_id']}/wide"
    if not store.exists(key + ".json"): return None
    meta = json.loads(store.get(key + ".json"))
    if (meta["lat"], meta["lon"], meta["extent_m"]) != (site["lat"], site["lon"], site["extent_m"]):
        raise SitesError(f"{site['site_id']} is already stored for lat {meta['lat']}, lon {meta['lon']}, extent_m {meta['extent_m']}; use a new site_id")
    return store.get(key + ".jpg"), meta


def fetch_site(site, provider=None):
    """Fetch the wide image through the existing Azure Maps path and store it write-once. Returns (bytes, meta)."""
    import io
    from tcp_planner.config.settings import CONFIG_DIR
    from tcp_planner.imagery.map_provider import get_map_provider
    from tcp_planner.imagery.prepare import JPEG_QUALITY
    with open(os.path.join(CONFIG_DIR, "pipeline_config.json"), encoding="utf-8") as f: px = json.load(f)["imagery"]["wide_image_px"]
    provider = provider or get_map_provider("azure_maps")
    img, m = provider.fetch_context({"work_reference": {"latitude": site["lat"], "longitude": site["lon"]}}, site["extent_m"], px)
    buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY); data = buf.getvalue()
    import hashlib
    meta = {**site, "metres_per_pixel": m["metres_per_pixel"], "width_pixels": m["width_pixels"], "zoom": m.get("zoom"), "provider": m.get("provider"),
            "retrieved_at": m.get("retrieved_at"), "sha256": hashlib.sha256(data).hexdigest(), "map_meta": m}
    store = _site_store(); key = f"{site['site_id']}/wide"
    store.put(key + ".jpg", data, "image/jpeg"); store.put(key + ".json", json.dumps(meta, sort_keys=True).encode(), "application/json")
    return data, meta


def _prepare(profile, site):
    from tcp_planner.ai import call1
    from tcp_planner.imagery.prepare import resize_for_model
    with open(os.path.join(INPUTS, site + ".jpg"), "rb") as f: data = f.read()
    with open(os.path.join(INPUTS, site + ".json"), encoding="utf-8") as f: mpp = json.load(f)["metres_per_pixel"]
    sent, record = resize_for_model(data, call1.profile_max_image_px(profile), mpp)
    return call1.build_request(sent, record, version=VERSION)


def _prepare_bytes(profile, data, mpp):
    from tcp_planner.ai import call1
    from tcp_planner.imagery.prepare import resize_for_model
    sent, record = resize_for_model(data, call1.profile_max_image_px(profile), mpp)
    return call1.build_request(sent, record, version=VERSION)


def _row(r):
    lanes = r["lanes_per_direction"]
    return (f"| {r['call']} | {r['site']} | {r['rep']} | {r['profile']} | {r['seconds']} | {r['input_tokens']} | {r['output_tokens']} | "
            f"{r.get('reasoning_tokens', 0)} | {'yes' if r['schema_valid'] else 'NO'} | {lanes['value']} ({lanes['status']}, {lanes['confidence']}) |")


def summary(profile):
    d = os.path.join(out_root(), profile); rows = []
    for n, _, _ in CALLS:
        p = os.path.join(d, f"call{n}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f: rows.append(_row(json.load(f)))
    print("| call | site | rep | profile | seconds | input tokens | output tokens | reasoning tokens | schema valid | lanes_per_direction |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    print("\n".join(rows) or "(no saved calls)")


def _call(call1, profile, ProviderError, name, n, site, rep, req):
    """One live call. Returns (result dict, None) or (None, error dict). Saves the result file. Runs in a worker thread when parallel.
    n is the call number (call<n>.json) or, for --sites, the label '<site_id>_r<rep>' (<label>.json)."""
    t0 = time.perf_counter()
    try:
        reply = call1.send_call1(profile, req)
    except ProviderError as e:
        return None, {"call": n, "seconds": round(time.perf_counter() - t0, 2), "code": e.code, "status": e.details.get("http_status"),
                      "body": e.details.get("api_error_text") or e.message}
    secs = round(time.perf_counter() - t0, 2)
    if reply.truncated or not reply.text:
        return None, {"call": n, "seconds": secs, "code": "TRUNCATED" if reply.truncated else "EMPTY", "status": None,
                      "body": f"{'response hit the output limit' if reply.truncated else 'empty response'}; usage {reply.usage}"}
    res = call1.parse_call1(reply.text, tuple(req["image"]["sent_px"]), version=VERSION)
    problems = call1.schema_problems(reply.text, res)
    lanes = res.observations["lanes_per_direction"]
    out = {"call": n, "site": site, "ta_situation": TA_SITUATION.get(site, ""), "prompt_version": VERSION, "rep": rep, "profile": name, "seconds": secs, "model": reply.model, "request_id": reply.request_id,
           "input_tokens": reply.usage.get("input_tokens"), "output_tokens": reply.usage.get("output_tokens"),
           "reasoning_tokens": reply.usage.get("reasoning_tokens", 0), "schema_valid": not problems, "schema_problems": problems,
           "unknown_facts": sum(o.status == "UNKNOWN" for o in res.observations.values()), "marks": len(res.marks),
           "lanes_per_direction": {"value": lanes.value, "status": lanes.status, "confidence": lanes.confidence},
           "fingerprint": call1.request_fingerprint(req, profile), "image": req["image"], "raw_response": reply.text}
    fname = n if isinstance(n, str) else f"call{n}"
    with open(os.path.join(out_root(), name, f"{fname}.json"), "w", encoding="utf-8") as f: json.dump(out, f, indent=2, ensure_ascii=False)
    return out, None


def _print_error(err):
    print(f"\nSTOP: call {err['call']} failed: {err['code']}\n  HTTP status: {err['status']}\n  API error body: {err['body']}")


def _print_result(out):
    print(f"\nresult: call {out['call']}, {out['seconds']} s, {out['input_tokens']} in / {out['output_tokens']} out tokens, "
          f"schema valid {out['schema_valid']} {out['schema_problems'] or ''}")
    print("lanes_per_direction:", out["lanes_per_direction"], "| unknown facts:", out["unknown_facts"], "| marks:", out["marks"])
    print(_row(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=None, help="profile name in config/foundry_profiles.json (default: its default_profile, gpt-5.6-sol; claude-opus-5-5 keeps working)")
    ap.add_argument("--prompt-version", type=int, choices=(1, 2, 3), default=1, help="1: the prompt of the nine recorded calls (default); 2: the enhanced prompt (STOP 6); 3: prompt v3 (STOP 7)")
    ap.add_argument("--only", type=int, choices=range(1, 10), metavar="N", help="run call N alone (1-9)")
    ap.add_argument("--from", dest="start", type=int, choices=range(1, 10), default=1, metavar="N", help="start at call N")
    ap.add_argument("--parallel", type=int, default=1, metavar="N", help="run N calls at once on this profile (default 1, one after the other)")
    ap.add_argument("--sites", metavar="CSV", help="run call 1 on the sites of this csv (site_id, lat, lon, extent_m) instead of the nine spike calls")
    ap.add_argument("--reps", type=int, default=1, metavar="N", help="with --sites: repetitions per site (default 1)")
    ap.add_argument("--dry-run", action="store_true", help="print the request body of the selected call(s); no network")
    ap.add_argument("--summary", action="store_true", help="print table rows from the saved results and exit")
    a = ap.parse_args(argv)
    if a.parallel < 1: print("--parallel must be at least 1"); return 2
    if a.reps < 1: print("--reps must be at least 1"); return 2
    if a.sites and (a.only or a.start != 1): print("--sites cannot be combined with --only or --from"); return 2
    global VERSION
    VERSION = a.prompt_version
    if a.profile is None:
        from tcp_planner.ai.foundry_provider import load_profiles
        a.profile = load_profiles().get("default_profile")
        if not a.profile: print("no --profile given and config/foundry_profiles.json has no default_profile"); return 2
    if a.summary: summary(a.profile); return 0
    sites = None
    if a.sites:
        try: sites = read_sites(a.sites)
        except (SitesError, OSError) as e: print(f"sites file problem: {e}"); return 2
        TA_SITUATION.clear(); TA_SITUATION.update({x["site_id"]: x["ta_situation"] for x in sites})

    from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
    load_env_file(); use_os_trust_store()
    from tcp_planner.ai import call1
    from tcp_planner.ai.foundry_provider import FoundryVisionProvider
    from tcp_planner.contracts import MapProviderError, ProviderError
    profile = FoundryVisionProvider(profile=a.profile)
    if profile.profile_cfg is None: print(f"unknown profile {a.profile!r}"); return 2
    if not a.dry_run and os.environ.get("TCP_LIVE") != "1": print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2

    os.makedirs(os.path.join(out_root(), a.profile), exist_ok=True)
    items = []          # (label, site, rep, request or None)
    if sites is None:
        items = [(n, site, rep, _prepare(profile, site)) for n, site, rep in CALLS if (n == a.only if a.only else n >= a.start)]
    else:
        for s in sites:                                    # the wide images first, one by one; a stored image is never fetched again
            try: got = stored_site(s)
            except SitesError as e: print(f"STOP: {e}"); return 2
            if got is None:
                if a.dry_run: print(f"\n[dry run] {s['site_id']}: the wide image is not stored; it would be fetched (lat {s['lat']}, lon {s['lon']}, half extent {s['extent_m']} m)"); continue
                try: got = fetch_site(s)
                except MapProviderError as e: print(f"\nSTOP: wide image for {s['site_id']} failed: {e.code}: {e.message}"); return 1
                print(f"\nfetched and stored the wide image of {s['site_id']}: zoom {got[1]['zoom']}, {got[1]['metres_per_pixel']:.4f} m per pixel, sha256 {got[1]['sha256']}")
            req = _prepare_bytes(profile, got[0], got[1]["metres_per_pixel"])
            items += [(f"{s['site_id']}_r{r}", s["site_id"], r, req) for r in range(1, a.reps + 1)]

    def show(n, site, rep, req):
        print(f"\n=== call {n}: {site} repetition {rep} on {a.profile} ({profile.deployment}, {profile.api}, effort {profile.effort}) ===")
        print("image:", json.dumps(req["image"]))
        print("request body (no key; images as size and sha256):")
        print(json.dumps(call1.describe_body(call1.wire_body(profile, req)), indent=2, ensure_ascii=False))

    if a.parallel == 1:                        # one after the other; stops at the first error
        for n, site, rep, req in items:
            show(n, site, rep, req)
            if a.dry_run: continue
            out, err = _call(call1, profile, ProviderError, a.profile, n, site, rep, req)
            if err: _print_error(err); return 1
            _print_result(out)
        return 0

    # parallel: every request body first, then N calls at once; no call is skipped after an error, so a 429 shows up in full
    for n, site, rep, req in items: show(n, site, rep, req)
    if a.dry_run: return 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"\n=== running {len(items)} calls, {a.parallel} at a time, on {a.profile} ===")
    outs, errs, t0 = [], [], time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.parallel) as pool:
        futs = [pool.submit(_call, call1, profile, ProviderError, a.profile, n, site, rep, req) for n, site, rep, req in items]
        for f in as_completed(futs):
            out, err = f.result()
            if err: errs.append(err); _print_error(err)
            else: outs.append(out); _print_result(out)
    wall = round(time.perf_counter() - t0, 2)
    per = sorted([(str(o["call"]), o["seconds"]) for o in outs] + [(str(e["call"]), e["seconds"]) for e in errs])
    n429 = sum(1 for e in errs if e["status"] == 429 or e["code"] == "AI_RATE_LIMITED")
    print(f"\nparallel {a.parallel}: wall time {wall} s for {len(items)} calls; per-call seconds {dict(per)}; "
          f"sum of per-call seconds {round(sum(s for _, s in per), 2)}; ok {len(outs)}, errors {len(errs)} (HTTP 429: {n429})")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
