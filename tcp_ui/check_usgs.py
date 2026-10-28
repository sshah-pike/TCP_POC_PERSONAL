"""Live USGS NAIP connectivity check using the pipeline's own TLS setup and provider code.

    python -m tcp_ui.check_usgs --lat 41.69 --lon -71.55
    python -m tcp_ui.check_usgs --kml samples/kml/<file>.kml

Answers two separate questions:
  1. TLS: does an HTTPS request to the USGS service succeed with certificate verification
     (same `requests` stack, after the same app.use_os_trust_store() as the CLI)?
  2. Imagery: does UsgsNaipProvider().fetch_context() - the exact pipeline call, same extent and
     image size the pipeline requests - return a usable image?
Output is sanitized (no query strings, keys or tokens). Makes no pipeline decision.
"""
import argparse, ssl, sys, time


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--kml"); src.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    a = ap.parse_args(argv)

    from tcp_planner.orchestration import pipeline as app
    from tcp_planner.intake import kml_reader as kml_input
    from tcp_planner.contracts import FT
    from tcp_ui.diagnostics import describe
    app.load_env_file(); app.use_os_trust_store()  # identical initialisation to tcp_planner.orchestration.pipeline.main()
    mod = ssl.SSLContext.__module__
    print(f"Trust store: {'Windows system store via truststore' if mod.startswith('truststore') else 'Python default (truststore NOT active)'}"
          f"  [ssl.SSLContext from {mod}]")

    import requests
    from tcp_planner.imagery.map_provider import UsgsNaipProvider
    prov = UsgsNaipProvider()
    meta_url = prov.BASE.format(svc=prov.SERVICE).rsplit("/", 1)[0]  # ImageServer root (no query)
    t0 = time.perf_counter()
    try:
        r = requests.get(meta_url, params={"f": "json"}, timeout=(5, 30), headers={"User-Agent": "tcp-poc/0.2"})
        print(f"1. TLS handshake + certificate verification: OK  ({time.perf_counter()-t0:.2f} s, HTTP {r.status_code})")
        tls_ok = True
    except requests.RequestException as e:
        d = describe(e, prov.name, round((time.perf_counter() - t0) * 1000, 1))
        print(f"1. TLS/connection: FAILED  {d['category']}  {d['exception_type']}: {d['message']}")
        tls_ok = False

    if a.kml:
        cfg = app.load_config(); pg = kml_input.parse_kml(a.kml, cfg["input"]["max_work_path_m"])
    else:
        if a.lon is None: ap.error("--lon is required with --lat")
        pg = kml_input.from_coordinates(a.lat, a.lon)
    cfg = app.load_config(); pack = app.load_rule_pack()
    half = max(pack.spacing_value_ft(rt, "A")[1] for rt in cfg["supported_road_types"]) * FT + cfg["imagery"]["analysis_margin_m"]
    print(f"2. USGS imagery export ({cfg['imagery']['width_px']} px, {2*half:.0f} m across, read timeout "
          f"{prov.READ_TIMEOUT_S:g} s) ...", flush=True)
    t0 = time.perf_counter()
    try:
        img, meta = prov.fetch_context(pg, half, cfg["imagery"]["width_px"])
        print(f"   imagery retrieval: OK  ({time.perf_counter()-t0:.2f} s, {img.size[0]}x{img.size[1]}, "
              f"{meta['metres_per_pixel']:.3f} m/px)")
        img_ok = True
    except Exception as e:
        d = describe(e, prov.name, round((time.perf_counter() - t0) * 1000, 1))
        print(f"   imagery retrieval: FAILED  pipeline code {d['pipeline_error_code']}  category {d['category']}  "
              f"after {d['duration_ms']/1000:.2f} s")
        print(f"   {d['exception_type']}: {d['message']}" + (f"  (HTTP {d['http_status']})" if d["http_status"] else ""))
        img_ok = False
    return 0 if (tls_ok and img_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
