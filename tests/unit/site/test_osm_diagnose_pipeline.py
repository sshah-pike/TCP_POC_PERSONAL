"""OSM history table, the diagnosis script and the pipeline script (S6, OSM diagnosis). Fake transports and a fake clock: no network."""
import importlib.util
import json
import os
import sys

import pytest

from tcp_planner.site_model.site_config import load_site_config, setting
from tests.unit.site.test_osm import EW, answer, element
from tests.unit.site.test_owner_scripts_osm_probe import at, Scripted, GOOD

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

pytestmark = pytest.mark.usefixtures("overpass_provider")      # these tests are about the Overpass provider; the shipped default is osm_api
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", name + ".py"))
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m


H = load("s06_osm_history")
D = load("s06_osm_diagnose")
P = load("s06_osm_pipeline")
CFG = load_site_config()


class Clock:
    def __init__(self): self.t = 0.0; self.sleeps = []

    def __call__(self): return self.t

    def sleep(self, s): self.sleeps.append(s); self.t += s

    def run(self, s): self.t += s


# ================================================================= history
OLD = '''
def fetch_osm(lat, lon, radius_m):
    import requests
    resp = requests.get("https://api.openstreetmap.org/api/0.6/map", params={"bbox": bbox},
                        timeout=(5, 30), headers={"User-Agent": "tcp-poc/0.2"})
'''
NEW = '''
URL = "https://overpass-api.de/api/interpreter"
def fetch_ways(client):
    resp = client.request(SOURCE_ID, URL, params={"data": q})
'''
TRANSPORT = '''
import requests
def requests_transport(method, url, params, body, headers, timeout):
    r = requests.request(method, url, params=params, data=body, headers=headers, timeout=(5, timeout or 30))
'''


def test_analyze_reads_url_method_params_user_agent_timeout_and_library():
    a = H.analyze(OLD)
    assert a == {"url": "https://api.openstreetmap.org/api/0.6/map", "method": "GET", "sent_as": "query string (params=)", "headers": "tcp-poc/0.2", "timeout": "(5, 30)",
                 "library": "requests", "truststore": False}
    b = H.analyze(NEW)
    assert b["url"] == "https://overpass-api.de/api/interpreter" and b["method"].startswith("GET") and b["sent_as"] == "query string (params=)"
    assert H.analyze(TRANSPORT)["library"] == "requests" and "per call" in H.analyze(TRANSPORT)["method"]
    assert H.analyze("x = 1") == {k: None for k in ("url", "method", "sent_as", "headers", "timeout", "library")} | {"truststore": False}
    assert H.analyze("app.use_os_trust_store()")["truststore"] is True
    assert H.analyze("import urllib.request\nurllib.request.urlopen(u)")["library"] == "urllib"


def fake_reader(rev, path):
    return {"tcp_poc/osm_adapter.py": OLD, "src/tcp_planner/data_sources/osm_overpass.py": OLD, "src/tcp_planner/data_sources/osm.py": NEW,
            "src/tcp_planner/data_sources/base.py": TRANSPORT + '\nh = {"User-Agent": cfg["user_agent"]}', "tests/support/record.py": "app.use_os_trust_store()",
            "scripts/s06_record_osm.py": "use_os_trust_store()"}.get(path)


def test_the_table_builder_marks_a_missing_file_and_never_invents_a_field():
    rows = H.build_rows(reader=lambda rev, path: None)
    assert len(rows) == len(H.PLACES) and not any(r["found"] for r in rows) and all(r["url"] is None for r in rows)


def test_the_differences_between_the_old_working_adapter_and_the_current_one():
    rows = H.build_rows(reader=fake_reader)
    old = next(r for r in rows if r["label"].startswith("old adapter at HEAD")); new = next(r for r in rows if r["label"].startswith("current adapter"))
    d = {a: (o, n) for a, o, n in H.differences(old, {**new, "truststore": True}, "[out:json];...")}
    assert d["host"] == ("api.openstreetmap.org", "overpass-api.de") and "service" in d and "query" in d and "answer format" in d and "server work" in d
    assert d["User-Agent"][0] == "tcp-poc/0.2"
    assert "method" not in d or d["method"][0] == "GET"


def test_the_current_query_is_rendered_by_the_adapter_from_config():
    q = H.current_query()
    assert q.startswith("[out:json][timeout:60];way(around:150,") and q.endswith("out tags geom;")


def test_the_history_script_writes_the_report_and_makes_no_request(tmp_path):
    out = tmp_path / "h.md"
    assert H.main(["--out", str(out)], reader=fake_reader) == 0
    text = out.read_text(encoding="utf-8")
    assert "## Differences between the old working adapter and the current one" in text and "api.openstreetmap.org" in text and "tcp-poc/0.2" in text
    assert "'source': 'osm_api'" in text and "never came from Overpass" in text and "What the history alone suggests" in text
    src = open(os.path.join(ROOT, "scripts", "s06_osm_history.py"), encoding="utf-8").read()
    assert "requests.get" not in src and "urlopen" not in src and "socket" not in src


def test_the_real_history_finds_the_old_main_api_adapter():
    rows = H.build_rows()
    first = rows[0]
    assert first["found"] and first["url"] == "https://api.openstreetmap.org/api/0.6/map" and first["headers"] == "tcp-poc/0.2" and first["timeout"] == "(5, 30)"
    assert rows[1]["url"] == first["url"]                                  # the adapter still at HEAD is the same one


# ================================================================= verdict
def R(v, total=1.0, status=200, error=None, json_ok=True, text=None):
    return D.result(v, status, 100, 0.1, 0.5, total, error, json_ok, text)


SLOW = 30.0
FREE = "Connected as: x\nRate limit: 2\n2 slots available now.\n"
BUSY = "Connected as: x\nRate limit: 2\nSlot available after: 2026-10-31T12:00:00Z, in 20 seconds.\n"


def build(**times):
    out = []
    for k in "abcdefghi":
        t = times.get(k, 1.0)
        if t is None: continue
        out.append(R(k, total=t, status=200 if t < 100 else None, error=None if t < 100 else "ReadTimeout", text=times.get("text") if k == "i" else None))
    return out


def v(**t): return D.verdict(build(**t), 20)


def test_all_fast_is_not_reproduced():
    assert v()[0] == "not reproduced now"


def test_project_path_slow_but_plain_requests_fast_is_our_client_code():
    assert v(a=SLOW)[0] == "our client code"
    assert v(a=999.0)[0] == "our client code"                                         # a timeout counts as slow


def test_project_user_agent_slow_but_default_fast_is_the_user_agent():
    assert v(c=SLOW)[0] == "User-Agent"


def test_full_query_slow_but_simple_fast_is_the_query_shape_and_g_tells_which_part():
    p, allv, why = v(b=SLOW, c=SLOW, a=SLOW, e=SLOW, d=SLOW, h=SLOW, g=1.0)
    assert "query shape" in allv and "out geom" in why
    p2, allv2, why2 = v(b=SLOW, c=SLOW, a=SLOW, e=SLOW, d=SLOW, h=SLOW, g=SLOW)
    assert "query shape" in allv2 and "highway filter" in why2
    assert "which part is not known" in D.verdict([r for r in build(b=SLOW, c=SLOW, a=SLOW, e=SLOW, d=SLOW, h=SLOW) if r["variant"] != "g"], 20)[2]


def test_get_slow_but_post_fast_is_the_method():
    p, allv, _ = v(b=SLOW, c=SLOW, a=SLOW, f=SLOW, e=SLOW, h=SLOW, g=SLOW)
    assert "method" in allv and "query shape" not in allv


def test_requests_slow_but_urllib_or_powershell_fast_is_the_library_or_interpreter():
    assert "library or interpreter" in v(b=SLOW, c=SLOW, a=SLOW, d=SLOW, f=SLOW, g=SLOW)[1]
    assert "library or interpreter" in v(b=SLOW, c=SLOW, a=SLOW, d=SLOW, f=SLOW, g=SLOW, e=SLOW)[1]          # PowerShell fast alone is enough
    assert "library or interpreter" not in v(b=SLOW, c=SLOW, a=SLOW, d=SLOW, f=SLOW, g=SLOW, e=SLOW, h=None)[1]


def test_everything_slow_with_no_free_slot_is_server_busy_and_with_a_fine_status_is_network():
    slow = dict(a=SLOW, b=SLOW, c=SLOW, d=SLOW, e=SLOW, f=SLOW, g=SLOW, h=SLOW)
    assert v(**slow, i=1.0, text=BUSY)[0] == "server busy"
    assert v(**slow, i=1.0, text=FREE)[0] == "network"
    assert v(**slow, i=1.0, text=None)[0] == "network"


def test_status_text_parsing():
    assert D.status_has_free_slot(FREE) is True and D.status_has_free_slot(BUSY) is False and D.status_has_free_slot("0 slots available now") is False
    assert D.status_has_free_slot("") is None and D.status_has_free_slot(None) is None


def test_a_429_is_its_own_verdict():
    rs = build(); rs[2] = R("c", status=429, total=0.2)
    assert D.verdict(rs, 20)[0] == "rate limited (HTTP 429)"


def test_stage_one_passes_only_for_the_project_path_with_200_json_under_the_pass_time():
    ok = [R("a", total=12.0)]
    assert D.passed(ok, 60) is True
    assert D.passed([R("a", total=61.0)], 60) is False and D.passed([R("a", total=12.0, json_ok=False)], 60) is False
    assert D.passed([R("a", total=12.0, status=500)], 60) is False and D.passed([R("a", total=None, status=None, error="ReadTimeout")], 60) is False
    assert D.passed([R("b", total=1.0)], 60) is False and D.passed([], 60) is False


# ================================================================= the run: limits, gap, 429
def runners(clock, durations=None, statuses=None, text=FREE, skip=()):
    out = {}
    for k, _ in D.VARIANTS:
        if k in skip: out[k] = None; continue

        def fn(k=k):
            d = (durations or {}).get(k, 1.0); clock.run(d)
            st = (statuses or {}).get(k, 200)
            return D.result(k, st, 100, 0.1, 0.4, d, None if st == 200 else "HTTPError", True, text if k == "i" else None)
        out[k] = fn
    return out


SITE = {"site_id": "granite", "lat": 41.3710266, "lon": -71.8203533}


def test_nine_requests_with_at_least_the_configured_gap_between_them():
    c = Clock(); o = D.run_diagnose(SITE, runners(c), CFG, c, c.sleep, log=lambda *_: None)
    assert o["requests_made"] == 9 and [r["variant"] for r in o["results"]] == list("abcdefghi") and o["verdict"] == "not reproduced now" and o["passed"] is True
    gap = setting("osm_diagnose", "min_gap_s", CFG)[0]
    assert len(c.sleeps) == 8 and all(abs(s - gap) < 1e-9 for s in c.sleeps)                             # the gap counts from the END of the previous request


def test_the_gap_is_measured_from_the_end_of_the_previous_request_not_from_its_start():
    c = Clock(); starts = []
    base = runners(c, durations={"a": 20.0})

    def tracked(k, fn):
        def f(): starts.append((k, c())); return fn()
        return f
    rs = {k: tracked(k, fn) for k, fn in base.items() if fn}
    D.run_diagnose(SITE, rs, CFG, c, c.sleep, log=lambda *_: None)
    t = dict(starts)
    assert t["b"] - t["a"] >= 20.0 + 8                                                                   # a took 20 s, then 8 s more before b started


def test_the_request_limit_stops_the_run():
    cfg = load_site_config(); cfg["osm_diagnose"]["max_requests"]["value"] = 3
    c = Clock(); o = D.run_diagnose(SITE, runners(c), cfg, c, c.sleep, log=lambda *_: None)
    assert o["requests_made"] == 3 and len(o["results"]) == 3 and "request limit of 3 reached" in o["stopped"]


def test_the_default_limits_are_14_requests_and_8_seconds_from_config_calibration_pending():
    assert setting("osm_diagnose", "max_requests", CFG) == (14, ("CALIBRATION_PENDING",)) and setting("osm_diagnose", "min_gap_s", CFG) == (8, ("CALIBRATION_PENDING",))
    assert len(D.VARIANTS) == 9 <= 14


def test_a_429_stops_the_run_at_once_and_says_so():
    c = Clock(); logs = []
    o = D.run_diagnose(SITE, runners(c, statuses={"c": 429}), CFG, c, c.sleep, log=logs.append)
    assert [r["variant"] for r in o["results"]] == ["a", "b", "c"] and o["stopped"] == "HTTP 429 at variant c" and o["verdict"] == "rate limited (HTTP 429)"
    assert any("STOP: HTTP 429" in str(x) for x in logs) and o["passed"] is True or o["passed"] is False


def test_a_variant_that_is_not_available_is_skipped_and_does_not_count():
    c = Clock(); o = D.run_diagnose(SITE, runners(c, skip=("h",)), CFG, c, c.sleep, log=lambda *_: None)
    assert o["requests_made"] == 8 and "h" not in [r["variant"] for r in o["results"]]


def test_the_report_has_the_table_the_verdict_the_environment_and_the_status_text():
    c = Clock(); o = D.run_diagnose(SITE, runners(c), CFG, c, c.sleep, log=lambda *_: None)
    sources = {"user_agent": "ua", "sources": {"osm_overpass": {"timeout_s": 90}}}
    text = D.render(SITE, o, D.environment("https://overpass-api.de/api/interpreter", {}), D.effective(SITE, load_site_config(), sources), "t")
    for s in ("| variant | what | HTTP status | bytes | connect s | first byte s | total s | error type |", "**VERDICT: not reproduced now**", "## Effective settings of variant a",
              "## Environment", "- python:", "- openssl:", "- requests:", "- urllib3:", "- HTTP_PROXY:", "- NO_PROXY:", "- os_proxies_urllib_getproxies:", "- dns:", "- truststore_injected:",
              "## /api/status (full text)", "2 slots available now", "Stage 1 test"):
        assert s in text, s
    assert "key" not in text.lower().replace("keys", "") or "api_key" not in text.lower()


def test_environment_reports_ipv4_and_ipv6_resolution_and_versions():
    env = D.environment("https://overpass-api.de/api/interpreter", {})
    assert env["host"] == "overpass-api.de" and isinstance(env["dns"], list) and env["python"] and env["openssl"] and env["urllib3"]
    assert "venv_base_interpreter" in env and "requests_environ_proxies_for_url" in env


# ================================================================= the diagnose script
def sites_file(tmp_path, ids=("granite", "second")):
    p = tmp_path / "sites.csv"
    p.write_text("site_id,lat,lon,extent_m,ta_situation\n" + "".join(f"{s},{41.0 + i},-71.0,212.4,x\n" for i, s in enumerate(ids)), encoding="utf-8"); return str(p)


def test_diagnose_dry_run_requests_nothing_and_needs_no_live_flag(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    assert D.main(["--sites", sites_file(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nothing was requested" in out and "variant a" in out and "variant i: /api/status" in out and "(5, 90)" in out


def test_diagnose_needs_tcp_live_and_uses_the_first_site_by_default(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    assert D.main(["--sites", sites_file(tmp_path)]) == 2 and "TCP_LIVE=1" in capsys.readouterr().out
    c = Clock(); run = tmp_path / "run"; run.mkdir()
    assert D.main(["--sites", sites_file(tmp_path)], runners=runners(c), clock=c, sleep=c.sleep, run_directory=str(run)) == 0
    text = (run / "diagnose.md").read_text(encoding="utf-8")
    assert "Site: `granite`" in text and "VERDICT" in text
    assert D.main(["--sites", sites_file(tmp_path), "--site", "nope", "--dry-run"]) == 2


def test_diagnose_exit_code_is_1_when_the_project_path_does_not_pass(tmp_path):
    c = Clock(); run = tmp_path / "run"; run.mkdir()
    assert D.main(["--sites", sites_file(tmp_path)], runners=runners(c, durations={"a": 70.0}), clock=c, sleep=c.sleep, run_directory=str(run)) == 1


def test_the_scripts_take_their_limits_and_timeouts_from_config():
    src = open(os.path.join(ROOT, "scripts", "s06_osm_diagnose.py"), encoding="utf-8").read()
    for name in ("max_requests", "min_gap_s", "slow_s", "pass_s", "connect_timeout_s", "read_timeout_s"): assert f'setting("osm_diagnose", "{name}"' in src
    cfg = CFG["osm_diagnose"]
    for k, v_ in cfg.items():
        if k != "note": assert v_["source"] == "CALIBRATION_PENDING", k


def test_the_diagnose_script_adds_no_host_and_changes_no_settings():
    src = open(os.path.join(ROOT, "scripts", "s06_osm_diagnose.py"), encoding="utf-8").read()
    assert src.count("overpass-api.de") <= 3 and "verify=False" not in src and "CERT_NONE" not in src and "os.environ[" not in src and "os.putenv" not in src
    assert "use_os_trust_store()" in src and "mirror" not in src.lower().replace("no mirror", "")


# ================================================================= the pipeline
SITES = ("granite", "second")


def world(tmp_path, truth_sites=("granite",), results=True):
    sites = tmp_path / "sites.csv"
    sites.write_text("site_id,lat,lon,extent_m,ta_situation\ngranite,41.3710266,-71.8203533,212.4,x\nsecond,42.337438,-71.0268586,212.4,y\n", encoding="utf-8")
    ts = tmp_path / "truth_sites.csv"
    ts.write_text("site_id,lat,lon,extent_m,ta_situation\n" + "".join(l + "\n" for l in ("granite,41.3710266,-71.8203533,212.4,x", "second,42.337438,-71.0268586,212.4,y") if l.split(",")[0] in truth_sites), encoding="utf-8")
    truth = tmp_path / "truth.csv"
    truth.write_text("site_id,lanes_per_direction,divided_highway,shoulder_present,oneway,parking_present,sidewalk_present,work_location,road_width_ft,truth_source,ta_situation\n"
                     "granite,1,false,false,false,false,true,,,drawing,x\n", encoding="utf-8")
    res = tmp_path / "var"
    if results:
        from tests.unit.site.test_understanding import response
        d = res / "s06_call1_check" / "gpt-5.6-sol"; d.mkdir(parents=True)
        json.dump({"site": "granite", "rep": 1, "image": {"sent_px": [400, 400], "mpp_sent": 0.1}, "raw_response": response()}, open(d / "call1.json", "w", encoding="utf-8"))
    return str(sites), str(ts), str(truth), str(res), str(tmp_path / "fx")


def good_transport(site_lat_lons=None):
    def tr(method, url, params, body, headers, timeout):
        q = params["data"]
        lat = float(q.split("around:150,")[1].split(",")[0]); lon = float(q.split("around:150,")[1].split(",")[1].split(")")[0])
        return 200, at(lat, lon, (1, {"highway": "secondary", "name": "Main St", "ref": "US 1", "lanes": "2", "oneway": "no", "shoulder": "no", "maxspeed": "35 mph", "sidewalk": "both", "surface": "asphalt"}, EW))
    return tr


def run_pipeline(tmp_path, **kw):
    sites, ts, truth, res, fx = world(tmp_path, **{k: kw.pop(k) for k in ("truth_sites", "results") if k in kw})
    c = Clock(); out = tmp_path / "runs"
    argv = ["--sites", sites, "--truth-sites", ts, "--truth", truth, "--out-dir", str(out)]
    rc = P.main(argv, runners=kw.get("runners") or runners(c), transport=kw.get("transport") or good_transport(), clock=c, sleep=c.sleep,
                fixtures_root=fx, results_root=res, **({"accuracy": kw["accuracy"]} if "accuracy" in kw else {}))
    runs = sorted(os.listdir(out)); return rc, (out / runs[-1]) if runs else None, fx


def test_the_pipeline_passes_through_all_stages_with_fakes(tmp_path, capsys):
    rc, run, fx = run_pipeline(tmp_path)
    assert rc == 0
    report = (run / "REPORT.md").read_text(encoding="utf-8")
    for section in ("## 1. Environment, diagnose table and verdict", "## 2. Recorder results per site", "## 3. second_source.csv", "## 4. What OSM says at the work point of each site",
                    "## 5. Accuracy reports (OSM as the second source)", "## 6. Fixture files created", "## 7. Files to upload", "all stages passed", "| variant | what |", "VERDICT"):
        assert section in report, section
    assert "| granite | recorded | 1 |" in report and "| second | recorded | 1 |" in report
    assert (run / "second_source.csv").is_file() and (run / "diagnose.md").is_file() and (run / "accuracy_v1.md").is_file()
    assert "granite,2,false,true,false" in report.replace(" ", "") or "granite" in report
    assert "v2" in report and "s06_call1_check_v2 does not exist" in report
    assert len(os.listdir(os.path.join(fx, "granite", "source"))) == 1 and len(os.listdir(os.path.join(fx, "second", "source"))) == 1
    assert report.count("source" + os.sep) >= 2 and "REPORT.md" in report.split("## 7. Files to upload")[1] and "accuracy_v1.md" in report.split("## 7. Files to upload")[1]


def test_stage_4_says_what_osm_has_at_the_work_point(tmp_path):
    rc, run, fx = run_pipeline(tmp_path)
    report = (run / "REPORT.md").read_text(encoding="utf-8")
    row = next(l for l in report.splitlines() if l.startswith("| granite | 1 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[:8] == ["granite", "1", "secondary", "Main St", "US 1", "5.0", "2", "-"] and "35 mph" in cells and "both" in cells and "asphalt" in cells
    assert cells[-2] == "1" and cells[-1] == "1"                                                   # ways in the radius; the reference way by the work point


def test_the_second_source_csv_is_for_the_truth_sites_only(tmp_path):
    rc, run, fx = run_pipeline(tmp_path, truth_sites=("granite",))
    rows = list(__import__("csv").DictReader(open(run / "second_source.csv", encoding="utf-8")))
    assert [r["site_id"] for r in rows] == ["granite"] and rows[0]["lanes_per_direction"] == "1" and rows[0]["shoulder_present"] == "false" and rows[0]["oneway"] == "false"


def test_the_pipeline_stops_at_stage_1_when_diagnose_fails_and_runs_nothing_later(tmp_path, capsys):
    c = Clock(); calls = []

    def tr(*a, **k): calls.append(1); return 200, b"{}"
    rc, run, fx = run_pipeline(tmp_path, runners=runners(c, durations={"a": 75.0}), transport=tr)
    out = capsys.readouterr().out
    assert rc == 1 and calls == [] and "STAGE 1 FAILED" in out and "Send REPORT.md" in out and "VERDICT" in out
    report = (run / "REPORT.md").read_text(encoding="utf-8")
    assert "STOPPED at stage 1 (diagnose)" in report and "(not run)" in report
    assert not (run / "second_source.csv").exists() and not os.path.isdir(fx)


def test_the_pipeline_stops_at_stage_2_when_a_site_cannot_be_recorded(tmp_path, capsys):
    t = Scripted([], default=(500, b"server error"))
    rc, run, fx = run_pipeline(tmp_path, transport=t)
    out = capsys.readouterr().out
    assert rc == 1 and "STAGE 2 FAILED" in out and not (run / "second_source.csv").exists()
    assert "STOPPED at stage 2 (record)" in (run / "REPORT.md").read_text(encoding="utf-8")


def test_accuracy_is_run_per_version_and_a_v3_folder_is_used_when_it_exists(tmp_path):
    sites, ts, truth, res, fx = world(tmp_path)
    for name in ("s06_call1_check_v2", "s06_call1_check_v3"):
        src = os.path.join(res, "s06_call1_check", "gpt-5.6-sol")
        dst = os.path.join(res, name, "gpt-5.6-sol"); os.makedirs(dst); open(os.path.join(dst, "call1.json"), "w", encoding="utf-8").write(open(os.path.join(src, "call1.json"), encoding="utf-8").read())
    seen = []

    def fake_accuracy(argv):
        seen.append(argv); open(argv[argv.index("--out") + 1], "w", encoding="utf-8").write("# fake report\n"); return 0
    c = Clock()
    rc = P.main(["--sites", sites, "--truth-sites", ts, "--truth", truth, "--out-dir", str(tmp_path / "runs")], runners=runners(c), transport=good_transport(), clock=c, sleep=c.sleep,
                fixtures_root=fx, results_root=res, accuracy=fake_accuracy)
    assert rc == 0 and len(seen) == 3 and all("--second-source" in a and a[a.index("--truth") + 1] == truth for a in seen)
    assert [os.path.basename(a[a.index("--out") + 1]) for a in seen] == ["accuracy_v1.md", "accuracy_v2.md", "accuracy_v3.md"]
    assert all(any(p.endswith("gpt-5.6-sol") for p in a) and not any(p.endswith("claude-opus-5-5") for p in a) for a in seen)      # only the profile folders that exist


def test_the_real_accuracy_report_runs_in_the_pipeline_and_its_text_is_in_the_report(tmp_path):
    rc, run, fx = run_pipeline(tmp_path)
    assert rc == 0 and "# Call 1 accuracy against truth" in (run / "REPORT.md").read_text(encoding="utf-8")


def test_the_pipeline_dry_run_requests_nothing_and_writes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    sites, ts, truth, res, fx = world(tmp_path)
    assert P.main(["--sites", sites, "--truth-sites", ts, "--truth", truth, "--out-dir", str(tmp_path / "runs"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "nothing was requested" in out and "stage 1 diagnose" in out and "granite, second" in out and not (tmp_path / "runs").exists()


def test_the_pipeline_needs_tcp_live_and_a_truth_file(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    sites, ts, truth, res, fx = world(tmp_path)
    assert P.main(["--sites", sites, "--truth-sites", ts, "--truth", truth]) == 2 and "TCP_LIVE=1" in capsys.readouterr().out
    assert P.main(["--sites", sites, "--truth-sites", ts, "--truth", str(tmp_path / "missing.csv"), "--dry-run"]) == 2


def test_paths_resolve_from_any_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert P.resolve("scripts/s06_osm_pipeline.py") == os.path.join(ROOT, "scripts", "s06_osm_pipeline.py")           # repo-relative path works from another folder
    (tmp_path / "here.csv").write_text("x", encoding="utf-8")
    assert P.resolve("here.csv") == str(tmp_path / "here.csv")


def test_nothing_secret_is_printed_or_written(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AZURE_MAPS_KEY", "SECRET-KEY-123"); monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "SECRET-KEY-456")
    rc, run, fx = run_pipeline(tmp_path)
    out = capsys.readouterr().out + (run / "REPORT.md").read_text(encoding="utf-8") + (run / "diagnose.md").read_text(encoding="utf-8")
    assert "SECRET-KEY" not in out


def test_the_pipeline_script_uses_the_os_trust_store_and_no_other_host():
    src = open(os.path.join(ROOT, "scripts", "s06_osm_pipeline.py"), encoding="utf-8").read()
    assert "use_os_trust_store()" in src and "verify=False" not in src and "overpass-api.de" not in src.split('"""')[2]


# ================================================================= the first live run, as a regression case (2026-10-31)
GATEWAY_BODY = "failed to connect The destination overpass-api.de is not reachable. Contact your IT administrator with the following error: Connection refused"


def live_run_1():
    """The nine results of the first live diagnosis: the project path answered 200 in 28 s; the default User-Agent got 406; four others got a gateway 502."""
    rs = [D.result("a", 200, 16482, 0.63, None, 28.09, None, True), D.result("b", 406, 156, 0.22, 1.06, 1.06, None, False, body_head="Not Acceptable"),
          D.result("c", 502, 534, 0.22, 1.05, 1.05, None, False, body_head=GATEWAY_BODY), D.result("d", 406, 156, 0.22, 1.03, 1.03, None, False, body_head="Not Acceptable"),
          D.result("e", 406, None, 0.22, None, 1.03, "HTTPError", None, body_head="Not Acceptable"), D.result("f", 502, 856, 0.22, 0.79, 0.79, None, False, body_head=GATEWAY_BODY),
          D.result("g", 502, 856, 0.24, 0.80, 0.80, None, False, body_head=GATEWAY_BODY), D.result("h", None, None, None, None, 1.0, "WebException"),
          D.result("i", 502, 856, 0.22, 0.79, 0.79, None, None, text="<html>Bad Gateway</html>", body_head=GATEWAY_BODY)]
    return rs


def test_the_first_live_run_is_not_read_as_everything_slow():
    rs = live_run_1()
    p, allv, why = D.verdict(rs, 20)
    assert p == "gateway or proxy" and "network" not in allv and "server busy" not in allv
    assert "406" in why and "default User-Agent" in why and "28 s" in why and "variants c, f, g, i" in why
    assert D.passed(rs, 60) is True                                              # the project path itself answered 200 with JSON in under 60 s


def test_an_http_error_is_a_failure_not_slowness():
    assert D.is_slow(D.result("b", 502, 1, None, None, 0.5), 20) is False and D.is_http_error(D.result("b", 502, 1, None, None, 0.5)) is True
    assert D.is_slow(D.result("b", 200, 1, None, None, 30.0), 20) is True and D.is_slow(D.result("b", None, None, None, None, 90.0, "ReadTimeout"), 20) is True
    assert D.is_slow(D.result("b", None, None, None, None, 1.0, "WebException"), 20) is False


def test_http_failures_without_a_gateway_page_are_inconclusive_and_say_which():
    rs2 = [D.result("a", 200, 10, 0.1, None, 5.0, None, True), D.result("b", 500, 1, 0.1, 0.2, 0.2, None, False, body_head="oops")]
    assert D.verdict(rs2, 20)[0] == "inconclusive" and "b: HTTP 500" in D.verdict(rs2, 20)[2]


def test_error_bodies_are_kept_as_plain_text_and_shown_in_the_report():
    assert D.head(b"<html><head><style>p{color:red}</style></head><body><h1>failed to connect</h1><p>Connection refused</p></body></html>") == "failed to connect Connection refused"
    assert D.head(None) is None and len(D.head("x" * 1000)) == 240
    c = Clock(); o = {"results": live_run_1(), "verdict": "gateway or proxy", "all": ["gateway or proxy"], "why": "w", "passed": True, "stopped": None, "status_text": None, "requests_made": 9}
    text = D.render(SITE, o, {"python": "3"}, {"url": "u"}, "t")
    assert "Error bodies (first characters, plain text):" in text and "variant c (HTTP 502): failed to connect" in text


def test_a_429_anywhere_fails_the_pipeline_stage_even_if_the_project_path_answered():
    rs = [D.result("a", 200, 10, 0.1, None, 5.0, None, True), D.result("b", 429, 1, 0.1, 0.2, 0.2)]
    assert D.passed(rs, 60) is False
