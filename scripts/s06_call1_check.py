"""S6 call 1 model check: the same 9 calls (3 sites x 3 repetitions) on one deployment. Run by the OWNER only.

  PowerShell, from the repo root:
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --dry-run --only 1   no network: print the request body of call 1
  $env:TCP_LIVE = "1"
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --only 1             call 1 alone
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --from 2             calls 2 to 9 (no --only/--from: all 9)
  python scripts/s06_call1_check.py --profile gpt-5.6-sol --summary            table rows from the saved results

Then the same with --profile claude-opus-5-5. The nine calls: 1-3 Granite (north-south road) repetitions 1-3, 4-6 E Second St (east-west road) repetitions 1-3, 7-9 Colorado (diagonal road) repetitions 1-3. Each call prints the exact request body first (no key; every image shown as its
size and SHA-256), then the result. The run STOPS at the first API error and prints the HTTP status and the API's error body
(key-like strings removed). Results are saved under var/s06_call1_check/<profile>/ (not tracked by git).
use_os_trust_store() runs first; certificate verification is never turned off. The script writes nothing to the repo's tracked files.
"""
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

SITES = ("granite", "second", "colorado")
INPUTS = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "inputs")
OUT = os.path.join(ROOT, "var", "s06_call1_check")
CALLS = [(i + 1, SITES[i // 3], i % 3 + 1) for i in range(9)]   # (call number, site, repetition)


def _prepare(profile, site):
    from tcp_planner.ai import call1
    from tcp_planner.imagery.prepare import resize_for_model
    with open(os.path.join(INPUTS, site + ".jpg"), "rb") as f: data = f.read()
    with open(os.path.join(INPUTS, site + ".json"), encoding="utf-8") as f: mpp = json.load(f)["metres_per_pixel"]
    sent, record = resize_for_model(data, call1.profile_max_image_px(profile), mpp)
    return call1.build_request(sent, record)


def _row(r):
    lanes = r["lanes_per_direction"]
    return (f"| {r['call']} | {r['site']} | {r['rep']} | {r['profile']} | {r['seconds']} | {r['input_tokens']} | {r['output_tokens']} | "
            f"{r.get('reasoning_tokens', 0)} | {'yes' if r['schema_valid'] else 'NO'} | {lanes['value']} ({lanes['status']}, {lanes['confidence']}) |")


def summary(profile):
    d = os.path.join(OUT, profile); rows = []
    for n, _, _ in CALLS:
        p = os.path.join(d, f"call{n}.json")
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f: rows.append(_row(json.load(f)))
    print("| call | site | rep | profile | seconds | input tokens | output tokens | reasoning tokens | schema valid | lanes_per_direction |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    print("\n".join(rows) or "(no saved calls)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="profile name in config/foundry_profiles.json")
    ap.add_argument("--only", type=int, choices=range(1, 10), metavar="N", help="run call N alone (1-9)")
    ap.add_argument("--from", dest="start", type=int, choices=range(1, 10), default=1, metavar="N", help="start at call N")
    ap.add_argument("--dry-run", action="store_true", help="print the request body of the selected call(s); no network")
    ap.add_argument("--summary", action="store_true", help="print table rows from the saved results and exit")
    a = ap.parse_args(argv)
    if a.summary: summary(a.profile); return 0

    from tcp_planner.orchestration.pipeline import load_env_file, use_os_trust_store
    load_env_file(); use_os_trust_store()
    from tcp_planner.ai import call1
    from tcp_planner.ai.foundry_provider import FoundryVisionProvider
    from tcp_planner.contracts import ProviderError
    profile = FoundryVisionProvider(profile=a.profile)
    if profile.profile_cfg is None: print(f"unknown profile {a.profile!r}"); return 2
    if not a.dry_run and os.environ.get("TCP_LIVE") != "1": print("live calls need TCP_LIVE=1 (or use --dry-run)"); return 2

    todo = [c for c in CALLS if (c[0] == a.only if a.only else c[0] >= a.start)]
    os.makedirs(os.path.join(OUT, a.profile), exist_ok=True)
    for n, site, rep in todo:
        req = _prepare(profile, site)
        print(f"\n=== call {n}: {site} repetition {rep} on {a.profile} ({profile.deployment}, {profile.api}, effort {profile.effort}) ===")
        print("image:", json.dumps(req["image"]))
        print("request body (no key; images as size and sha256):")
        print(json.dumps(call1.describe_body(call1.wire_body(profile, req)), indent=2, ensure_ascii=False))
        if a.dry_run: continue
        t0 = time.perf_counter()
        try:
            reply = call1.send_call1(profile, req)
        except ProviderError as e:
            print(f"\nSTOP: call {n} failed: {e.code}\n  HTTP status: {e.details.get('http_status')}\n  API error body: {e.details.get('api_error_text') or e.message}")
            return 1
        secs = round(time.perf_counter() - t0, 2)
        if reply.truncated or not reply.text:
            print(f"\nSTOP: call {n}: {'response hit the output limit' if reply.truncated else 'empty response'}; usage {reply.usage}"); return 1
        res = call1.parse_call1(reply.text, tuple(req["image"]["sent_px"]))
        problems = call1.schema_problems(reply.text, res)
        lanes = res.observations["lanes_per_direction"]
        out = {"call": n, "site": site, "rep": rep, "profile": a.profile, "seconds": secs, "model": reply.model, "request_id": reply.request_id,
               "input_tokens": reply.usage.get("input_tokens"), "output_tokens": reply.usage.get("output_tokens"),
               "reasoning_tokens": reply.usage.get("reasoning_tokens", 0), "schema_valid": not problems, "schema_problems": problems,
               "unknown_facts": sum(o.status == "UNKNOWN" for o in res.observations.values()), "marks": len(res.marks),
               "lanes_per_direction": {"value": lanes.value, "status": lanes.status, "confidence": lanes.confidence},
               "fingerprint": call1.request_fingerprint(req, profile), "image": req["image"], "raw_response": reply.text}
        with open(os.path.join(OUT, a.profile, f"call{n}.json"), "w", encoding="utf-8") as f: json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nresult: {secs} s, {out['input_tokens']} in / {out['output_tokens']} out tokens, schema valid {not problems} {problems or ''}")
        print("lanes_per_direction:", out["lanes_per_direction"], "| unknown facts:", out["unknown_facts"], "| marks:", out["marks"])
        print(_row(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
