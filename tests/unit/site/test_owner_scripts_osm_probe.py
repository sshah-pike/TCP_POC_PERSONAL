"""Owner scripts of step 13 and 16: the OSM recorder, the recorded-OSM to second-source converter, the zoom-19 probe. Fakes only, no network."""
import csv
import importlib.util
import io
import json
import math
import os

import numpy as np
import pytest
from PIL import Image

from tcp_planner.contracts import MapProviderError
from tests.unit.site.test_osm import K, LAT0, LON0, answer, element, latlon

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def load(name):
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


@pytest.fixture(scope="module")
def rec(): return load("s06_record_osm")


@pytest.fixture(scope="module")
def conv(): return load("s06_osm_second_source")


@pytest.fixture(scope="module")
def probe(): return load("s06_probe_native_detail")


EW = [(-100.0, 5.0), (100.0, 5.0)]


def at(lat0, lon0, *els):
    """An Overpass answer whose ways (id, tags, local points in metres) lie around (lat0, lon0)."""
    kk = math.pi / 180 * 6371008.8
    out = []
    for id_, tags, pts in els:
        out.append({"type": "way", "id": id_, "tags": tags, "geometry": [{"lat": lat0 + y / kk, "lon": lon0 + x / (kk * math.cos(math.radians(lat0)))} for x, y in pts]})
    return answer(*out)


class Transport:
    def __init__(self, content=None, status=200):
        self.calls = []; self.status = status
        self.content = content if content is not None else answer(element(1, {"highway": "secondary", "name": "Main St", "lanes": "4", "oneway": "no", "shoulder": "no"}, EW))

    def __call__(self, method, url, params, body, headers, timeout):
        self.calls.append((url, params, headers)); return self.status, self.content


def sites_csv(tmp_path, rows=(("A", LAT0, LON0), ("B", LAT0 + 0.01, LON0))):
    p = tmp_path / "sites.csv"
    p.write_text("site_id,lat,lon,extent_m,ta_situation\n" + "".join(f"{s},{la},{lo},212.4,x\n" for s, la, lo in rows), encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------- the recorder
def test_the_recorder_records_one_fixture_per_site_then_skips_them(rec, tmp_path, capsys):
    t = Transport(); out = tmp_path / "fx"
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t, sleep=lambda s: None) == 0
    assert len(t.calls) == 2 and all(c[0].startswith("https://overpass-api.de/") and "tcp-planner" in c[2]["User-Agent"] for c in t.calls)
    assert all("contact" not in c[2]["User-Agent"].lower() for c in t.calls)
    for s in ("A", "B"): assert len(os.listdir(out / s / "source")) == 1
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t, sleep=lambda s: None) == 0
    assert len(t.calls) == 2 and "already recorded" in capsys.readouterr().out                   # nothing fetched twice


def test_the_recorder_dry_run_makes_no_call_and_needs_no_live_flag(rec, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(tmp_path / "fx"), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[out:json][timeout:60]" in out and "around:150" in out and not (tmp_path / "fx").exists()


def test_the_recorder_needs_tcp_live(rec, tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(tmp_path / "fx")]) == 2 and "TCP_LIVE=1" in capsys.readouterr().out


class Scripted:
    """A transport that answers per call from a list: (status, content) or an exception to raise."""
    def __init__(self, script, default=None):
        self.script, self.calls, self.default = list(script), [], default

    def __call__(self, method, url, params, body, headers, timeout):
        self.calls.append(params["data"])
        step = self.script.pop(0) if self.script else self.default
        if isinstance(step, Exception): raise step
        return step


class ReadTimeout(Exception): pass


GOOD = (200, answer(element(1, {"highway": "secondary", "lanes": "2"}, EW)))


def test_a_failing_site_is_retried_twice_with_the_configured_waits_then_the_next_site_goes_on(rec, tmp_path, capsys):
    t = Scripted([(429, b"too many requests")] * 3 + [GOOD]); out = tmp_path / "fx"; waits = []
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t, sleep=waits.append) == 1       # exit 1: one site failed
    text = capsys.readouterr().out
    assert len(t.calls) == 4                                                       # site A: 3 attempts (1 + 2 retries), site B: 1
    assert [w for w in waits if w != rec.PAUSE_S] == [10, 30]                      # the configured waits, in order
    assert "A: FAILED after 3 attempt(s): HTTP status 429" in text and "too many requests" in text and "continuing with the next site" in text
    assert "B: recorded 1 way(s)" in text and "1 recorded, 0 already there, 1 failed (A)" in text
    assert not os.path.isdir(out / "A" / "source") and os.path.isdir(out / "B" / "source")


def test_a_timeout_then_success_records_the_site_after_one_retry(rec, tmp_path, capsys):
    t = Scripted([ReadTimeout("read timed out"), GOOD], default=GOOD); out = tmp_path / "fx"; waits = []
    p = tmp_path / "one.csv"; p.write_text("site_id,lat,lon,extent_m\nA,%s,%s,212.4\n" % (LAT0, LON0), encoding="utf-8")
    assert rec.main(["--sites", str(p), "--out", str(out)], transport=t, sleep=waits.append) == 0
    text = capsys.readouterr().out
    assert len(t.calls) == 2 and waits == [10] and "timeout" in text and "retry 1 of 2 after 10 s" in text and "A: recorded 1 way(s)" in text
    assert os.path.isdir(out / "A" / "source")


def test_a_final_timeout_prints_the_timeout_and_the_run_continues(rec, tmp_path, capsys):
    t = Scripted([ReadTimeout("x")] * 3 + [GOOD]); out = tmp_path / "fx"
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t, sleep=lambda s: None) == 1
    text = capsys.readouterr().out
    assert "A: FAILED after 3 attempt(s): timeout" in text and "90 s read timeout" in text and "B: recorded" in text


def test_an_error_that_cannot_improve_is_not_retried(rec, tmp_path, capsys):
    t = Scripted([(400, b"bad query")] , default=GOOD); waits = []
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(tmp_path / "fx")], transport=t, sleep=waits.append) == 1
    text = capsys.readouterr().out
    assert "A: FAILED after 1 attempt(s): HTTP status 400" in text and "bad query" in text and "retry" not in text
    assert len(t.calls) == 2                                                       # A once, then B


def test_rerunning_after_a_failure_skips_what_is_recorded_and_fetches_only_the_rest(rec, tmp_path, capsys):
    out = tmp_path / "fx"
    t1 = Scripted([GOOD] + [(504, b"gateway timeout")] * 3)
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t1, sleep=lambda s: None) == 1
    capsys.readouterr()
    t2 = Scripted([], default=GOOD)
    assert rec.main(["--sites", sites_csv(tmp_path), "--out", str(out)], transport=t2, sleep=lambda s: None) == 0
    text = capsys.readouterr().out
    assert len(t2.calls) == 1 and "A: already recorded" in text and "B: recorded" in text


def test_the_retry_waits_and_timeouts_come_from_config_not_from_the_script():
    src = open(os.path.join(ROOT, "scripts", "s06_record_osm.py"), encoding="utf-8").read()
    assert 'setting("osm", "retry_waits_s"' in src and 'setting("osm", "query_timeout_s"' in src
    assert "[10, 30]" not in src and "timeout=60" not in src and "90" not in src.split('"""')[2]


def test_a_bad_sites_file_is_named(rec, tmp_path, capsys):
    p = tmp_path / "s.csv"; p.write_text("site_id,lat,lon,extent_m\nA,x,y,z\n", encoding="utf-8")
    assert rec.main(["--sites", str(p), "--out", str(tmp_path / "fx")], transport=Transport()) == 2 and "line 2" in capsys.readouterr().out


# ---------------------------------------------------------------- recorded OSM to the --second-source CSV
def record_world(rec, tmp_path, answers):
    """Record `answers` {site_id: (lat, lon, content)} through the recorder's own client path; returns (sites csv, fixture root)."""
    out = tmp_path / "fx"; rows = []
    for sid, (la, lo, content) in answers.items():
        rows.append((sid, la, lo))
        p = tmp_path / f"{sid}.csv"; p.write_text(f"site_id,lat,lon,extent_m\n{sid},{la},{lo},212.4\n", encoding="utf-8")
        assert rec.main(["--sites", str(p), "--out", str(out)], transport=Transport(content), sleep=lambda s: None) == 0
    return sites_csv(tmp_path, rows), str(out)


def read(path):
    with open(path, encoding="utf-8", newline="") as f: return {r["site_id"]: r for r in csv.DictReader(f)}


def test_the_converter_writes_the_osm_values_the_rules_give(rec, conv, tmp_path, capsys):
    la, lo = LAT0, LON0
    full = at(la, lo, (1, {"highway": "secondary", "name": "Main St", "lanes": "4", "oneway": "no", "shoulder": "yes"}, EW))
    sparse = at(la + 0.01, lo, (2, {"highway": "residential", "name": "Elm St"}, EW))               # no lanes, no oneway, no shoulder tag
    oneway = at(la + 0.02, lo, (3, {"highway": "primary", "oneway": "yes", "lanes": "3", "shoulder": "no"}, EW))
    sites, fx = record_world(rec, tmp_path, {"full": (la, lo, full), "sparse": (la + 0.01, lo, sparse), "oneway": (la + 0.02, lo, oneway)})
    out = tmp_path / "second.csv"
    assert conv.main(["--sites", sites, "--fixtures", fx, "--out", str(out)]) == 0
    rows = read(out)
    assert rows["full"] == {"site_id": "full", "lanes_per_direction": "2", "divided_highway": "false", "shoulder_present": "true", "oneway": "false"}
    assert rows["sparse"] == {"site_id": "sparse", "lanes_per_direction": "", "divided_highway": "false", "shoulder_present": "", "oneway": "false"}
    assert rows["oneway"]["lanes_per_direction"] == "3" and rows["oneway"]["oneway"] == "true" and rows["oneway"]["shoulder_present"] == "false"
    assert rows["oneway"]["divided_highway"] == ""                                              # a one-way way with no opposite carriageway: undecidable
    assert "sparse: no oneway tag" in capsys.readouterr().out                                   # the lower-confidence stand-in is listed


def test_a_missing_fixture_a_which_road_and_no_road_give_blank_rows_with_a_note(rec, conv, tmp_path, capsys):
    la, lo = LAT0, LON0
    cross = at(la, lo, (1, {"highway": "secondary", "name": "A St", "lanes": "2"}, [(-100.0, 5.0), (100.0, 5.0)]),
               (2, {"highway": "secondary", "name": "B St", "lanes": "2"}, [(7.0, -100.0), (7.0, 100.0)]))      # two roads, 2 m apart in distance: not clearly nearer
    far = at(la + 0.01, lo, (1, {"highway": "secondary", "lanes": "2"}, [(-100.0, 200.0), (100.0, 200.0)]))
    sites, fx = record_world(rec, tmp_path, {"cross": (la, lo, cross), "far": (la + 0.01, lo, far)})
    extra = tmp_path / "all.csv"
    lines = ["site_id,lat,lon,extent_m", f"cross,{la},{lo},212.4", f"far,{la + 0.01},{lo},212.4", "ghost,41.0,-71.0,212.4"]
    extra.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    out = tmp_path / "second.csv"
    assert conv.main(["--sites", str(extra), "--fixtures", fx, "--out", str(out)]) == 0
    text = capsys.readouterr().out
    rows = read(out)
    assert all(v == "" for k, v in rows["cross"].items() if k != "site_id") and "WHICH_ROAD" in text
    assert all(v == "" for k, v in rows["far"].items() if k != "site_id") and "no OSM road near" in text
    assert all(v == "" for k, v in rows["ghost"].items() if k != "site_id") and "no recorded OSM fixture" in text


def test_the_csv_is_what_the_accuracy_report_reads_and_it_feeds_the_two_source_rule(rec, conv, tmp_path):
    spec = importlib.util.spec_from_file_location("acc", os.path.join(ROOT, "scripts", "s06_accuracy_report.py"))
    R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
    sites, fx = record_world(rec, tmp_path, {"full": (LAT0, LON0, at(LAT0, LON0, (1, {"highway": "secondary", "lanes": "4", "oneway": "no", "shoulder": "yes"}, EW)))})
    out = tmp_path / "second.csv"
    assert conv.main(["--sites", sites, "--fixtures", fx, "--out", str(out)]) == 0
    assert tuple(next(csv.reader(open(out, encoding="utf-8")))) == R.SECOND_COLUMNS
    second = R.read_second(str(out))
    assert second["full"] == {"lanes_per_direction": 2, "divided_highway": False, "shoulder_present": True, "oneway": False}


# ---------------------------------------------------------------- the zoom-19 probe
class FakeProvider:
    def __init__(self, fail=None): self.calls, self.fail = [], fail

    def fetch_view(self, lat, lon, zoom, size_px):
        self.calls.append((lat, lon, zoom, size_px))
        if self.fail: raise MapProviderError("MAP_HTTP_ERROR", self.fail)
        rng = np.random.default_rng(1)
        arr = (rng.normal(128, 40, (size_px, size_px, 3))).clip(0, 255).astype(np.uint8)         # a detailed view
        mpp = 2 * math.pi * 6378137 * math.cos(math.radians(lat)) / (512 * 2 ** zoom)
        return Image.fromarray(arr, "RGB"), {"metres_per_pixel": mpp, "retrieved_at": "2026-10-31T12:00:00+00:00"}


def test_the_probe_makes_exactly_one_zoom_19_request_per_site_and_saves_the_view(probe, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TCP_LIVE", "1"); monkeypatch.setattr(probe, "OUT", str(tmp_path / "out"))
    p = FakeProvider()
    assert probe.main([], provider=p) == 0
    assert [c[2:] for c in p.calls] == [(19, 512), (19, 512)] and len(p.calls) == 2
    for site in ("second", "colorado"):
        rec = json.load(open(tmp_path / "out" / site / "zoom19.json", encoding="utf-8"))
        assert rec["zoom"] == 19 and rec["detail_check"]["flag"] in ("NATIVE_DETAIL", "NO_DETAIL_GAIN") and rec["detail_check"]["gating"] is False
        assert os.path.getsize(tmp_path / "out" / site / "zoom19.jpg") > 1000
    out = capsys.readouterr().out
    assert "E Second MH 223" in out and "Colorado P13" in out and "| site | zoom |" in out


def test_the_probe_needs_tcp_live_and_has_a_dry_run(probe, capsys, monkeypatch):
    monkeypatch.delenv("TCP_LIVE", raising=False)
    p = FakeProvider()
    assert probe.main([], provider=p) == 2 and p.calls == []
    assert probe.main(["--dry-run"], provider=p) == 0 and p.calls == [] and "zoom-19 request" in capsys.readouterr().out


def test_the_probe_stops_at_the_first_failed_request_with_the_error(probe, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TCP_LIVE", "1"); monkeypatch.setattr(probe, "OUT", str(tmp_path / "out"))
    p = FakeProvider(fail="HTTP 400 zoom not available")
    assert probe.main([], provider=p) == 1 and len(p.calls) == 1
    assert "STOP" in capsys.readouterr().out


def test_every_live_script_calls_the_os_trust_store_first_and_never_turns_verification_off():
    for name in ("s06_probe_native_detail", "s06_record_osm"):
        src = open(os.path.join(ROOT, "scripts", name + ".py"), encoding="utf-8").read()
        assert "use_os_trust_store()" in src and "verify=False" not in src and "CERT_NONE" not in src
        assert src.index("use_os_trust_store()") < src.index("get_map_provider(") if "get_map_provider(" in src else True
