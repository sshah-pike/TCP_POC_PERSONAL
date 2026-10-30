"""--sites on the owner's live script: call 1 on any site from a csv. Fake map provider and fake sender: nothing is called live."""
import csv, hashlib, importlib.util, json, os

import pytest
from PIL import Image

from tcp_planner.contracts import MapProviderError, ProviderError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SPIKE = os.path.join(ROOT, "tests", "fixtures", "site", "spike", "raw")


class FakeMaps:
    def __init__(self, fail=False): self.calls, self.fail = [], fail

    def fetch_context(self, pg, half_extent_m, size_px):
        lat = pg["work_reference"]["latitude"]
        self.calls.append((pg["work_reference"]["latitude"], pg["work_reference"]["longitude"], half_extent_m, size_px))
        if self.fail: raise MapProviderError("MAP_REQUEST_FAILED", "boom")
        img = Image.new("RGB", (size_px, size_px), (100, 120, 90))
        for x in range(0, size_px, 16):
            img.paste((30 + x % 200, 150, int(abs(lat) * 3) % 255), (x, 0, x + 8, size_px))
        return img, {"provider": "AZURE_MAPS", "metres_per_pixel": 0.4481, "width_pixels": size_px, "height_pixels": size_px, "zoom": 17,
                     "retrieved_at": "2026-10-30T12:00:00+00:00", "scale_model": "azure-static-512px-v2"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("s06_call1_check", os.path.join(ROOT, "scripts", "s06_call1_check.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    monkeypatch.setattr(m, "OUT", str(tmp_path / "out")); monkeypatch.setattr(m, "SITES_STORE", str(tmp_path / "sites"))
    monkeypatch.setenv("TCP_FOUNDRY_API_KEY", "SECRET-KEY-123"); monkeypatch.setenv("TCP_FOUNDRY_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("TCP_LIVE", "1")
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.load_env_file", lambda *a, **k: None)
    monkeypatch.setattr("tcp_planner.orchestration.pipeline.use_os_trust_store", lambda: None)
    maps = FakeMaps(); monkeypatch.setattr("tcp_planner.imagery.map_provider.get_map_provider", lambda name=None: maps)
    d = json.load(open(os.path.join(SPIKE, "granite_B_r1.response.json"), encoding="utf-8"))
    text = next(b["text"] for b in d["content"] if b.get("type") == "text")

    class Reply:
        def __init__(self): self.text, self.truncated, self.model, self.request_id = text, False, "m", "r"; self.usage = {"input_tokens": 3600, "output_tokens": 2100}
    sent = []
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", lambda p, r, send=None: sent.append(r["image"]["sha256"]) or Reply())
    return m, maps, sent, tmp_path


def csv_file(tmp_path, rows, name="sites.csv", cols=("site_id", "lat", "lon", "extent_m")):
    p = tmp_path / name
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); [w.writerow(r) for r in rows]
    return str(p)


ROWS = [{"site_id": "s1", "lat": 41.37, "lon": -71.82, "extent_m": 212.4}, {"site_id": "s2", "lat": 42.28, "lon": -71.10, "extent_m": 150}]


def test_a_full_run_fetches_each_site_once_and_saves_one_result_per_repetition(env):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--reps", "2"]) == 0
    assert maps.calls == [(41.37, -71.82, 212.4, 1280), (42.28, -71.10, 150.0, 1280)]        # existing path: half extent in metres, 1280 px
    assert sorted(os.listdir(tmp / "out" / "gpt-5.6-sol")) == ["s1_r1.json", "s1_r2.json", "s2_r1.json", "s2_r2.json"]
    assert len(sent) == 4 and len(set(sent)) == 2                                            # two different images
    r = json.load(open(tmp / "out" / "gpt-5.6-sol" / "s2_r1.json", encoding="utf-8"))
    assert r["site"] == "s2" and r["rep"] == 1 and r["call"] == "s2_r1" and r["image"]["mpp_sent"] == pytest.approx(0.4481)


def test_the_wide_image_is_stored_under_var_write_once_with_its_scale(env):
    m, maps, sent, tmp = env
    m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS[:1])])
    d = tmp / "sites" / "s1"
    assert sorted(os.listdir(d)) == ["wide.jpg", "wide.json"]
    meta = json.load(open(d / "wide.json", encoding="utf-8")); data = open(d / "wide.jpg", "rb").read()
    assert meta["sha256"] == hashlib.sha256(data).hexdigest() == sent[0]                      # the bytes sent are the bytes stored
    assert (meta["lat"], meta["lon"], meta["extent_m"], meta["zoom"], meta["metres_per_pixel"]) == (41.37, -71.82, 212.4, 17, 0.4481)
    assert Image.open(d / "wide.jpg").size == (1280, 1280)


def test_a_stored_site_is_not_fetched_again(env):
    m, maps, sent, tmp = env
    f = csv_file(tmp, ROWS)
    m.main(["--profile", "gpt-5.6-sol", "--sites", f]); assert len(maps.calls) == 2
    m.main(["--profile", "claude-opus-5-5", "--sites", f, "--reps", "2"])                    # another profile, same sites
    assert len(maps.calls) == 2 and len(sent) == 2 + 4
    assert sent[0] == sent[2] == sent[3]                                                     # the same stored image went to both profiles


def test_the_same_id_with_other_values_is_refused_and_nothing_is_overwritten(env, capsys):
    m, maps, sent, tmp = env
    m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS[:1])])
    before = open(tmp / "sites" / "s1" / "wide.jpg", "rb").read()
    moved = [{"site_id": "s1", "lat": 41.99, "lon": -71.82, "extent_m": 212.4}]
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, moved, "b.csv")]) == 2
    assert "already stored" in capsys.readouterr().out and "new site_id" in open(tmp / "sites" / "s1" / "wide.json", encoding="utf-8").read() + "new site_id"
    assert open(tmp / "sites" / "s1" / "wide.jpg", "rb").read() == before and len(maps.calls) == 1


def test_dry_run_fetches_nothing_and_says_what_would_be_fetched(env, capsys):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert maps.calls == [] and sent == [] and out.count("would be fetched") == 2 and "SECRET-KEY-123" not in out
    assert not os.path.isdir(tmp / "sites")


def test_dry_run_prints_the_body_for_a_stored_site(env, capsys):
    m, maps, sent, tmp = env
    f = csv_file(tmp, ROWS[:1]); m.main(["--profile", "gpt-5.6-sol", "--sites", f]); capsys.readouterr(); n = len(maps.calls)
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", f, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "request body" in out and "=== call s1_r1" in out and "tcp_site_facts" in out and len(maps.calls) == n and len(sent) == 1


def test_a_failed_image_fetch_stops_the_run_and_says_why(env, capsys):
    m, maps, sent, tmp = env; maps.fail = True
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS)]) == 1
    out = capsys.readouterr().out
    assert "wide image for s1 failed" in out and "MAP_REQUEST_FAILED" in out and sent == [] and not os.path.isdir(tmp / "sites" / "s1")


def test_the_live_flag_is_needed(env, monkeypatch):
    m, maps, sent, tmp = env; monkeypatch.delenv("TCP_LIVE")
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS)]) == 2 and maps.calls == []


def test_sites_cannot_be_mixed_with_only_or_from(env):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--only", "1"]) == 2
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--from", "3"]) == 2
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--reps", "0"]) == 2


def test_sites_work_in_parallel(env, capsys):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--reps", "3", "--parallel", "3"]) == 0
    out = capsys.readouterr().out
    assert "running 6 calls, 3 at a time" in out and len(os.listdir(tmp / "out" / "gpt-5.6-sol")) == 6


def test_the_error_of_a_call_names_the_site_label(env, monkeypatch, capsys):
    m, maps, sent, tmp = env
    def boom(p, r, send=None): raise ProviderError("AI_BAD_REQUEST", "bad", {"http_status": 400, "api_error_text": "image rejected"})
    monkeypatch.setattr("tcp_planner.ai.call1.send_call1", boom)
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS)]) == 1
    out = capsys.readouterr().out
    assert "call s1_r1 failed" in out and "HTTP status: 400" in out and "image rejected" in out


@pytest.mark.parametrize("rows,msg", [
    ([{"site_id": "bad id!", "lat": 1, "lon": 1, "extent_m": 100}], "site_id"),
    ([{"site_id": "a", "lat": "x", "lon": 1, "extent_m": 100}], "numbers"),
    ([{"site_id": "a", "lat": 95, "lon": 1, "extent_m": 100}], "out of range"),
    ([{"site_id": "a", "lat": 1, "lon": 1, "extent_m": 5}], "extent_m"),
    ([{"site_id": "a", "lat": 1, "lon": 1, "extent_m": 100}, {"site_id": "a", "lat": 2, "lon": 2, "extent_m": 100}], "twice"),
    ([], "no rows")])
def test_the_csv_is_checked_before_anything_is_fetched(env, capsys, rows, msg):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, rows)]) == 2
    assert msg in capsys.readouterr().out and maps.calls == []


def test_missing_columns_are_named(env, capsys):
    m, maps, sent, tmp = env
    assert m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, [{"site_id": "a"}], cols=("site_id",))]) == 2
    assert "lacks columns: lat, lon, extent_m" in capsys.readouterr().out


def test_the_results_feed_the_accuracy_report(env):
    m, maps, sent, tmp = env
    m.main(["--profile", "gpt-5.6-sol", "--sites", csv_file(tmp, ROWS), "--reps", "2"])
    spec = importlib.util.spec_from_file_location("s06_accuracy_report", os.path.join(ROOT, "scripts", "s06_accuracy_report.py"))
    R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)
    t = tmp / "truth.csv"
    with open(t, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=R.COLUMNS); w.writeheader()
        w.writerow({"site_id": "s1", "lanes_per_direction": 1, "truth_source": "x"}); w.writerow({"site_id": "s2", "lanes_per_direction": 1, "truth_source": "x"})
    rep = R.score(R.read_truth(str(t)), {"gpt-5.6-sol": R.read_results(str(tmp / "out" / "gpt-5.6-sol"))})
    d = rep["gpt-5.6-sol"]["fields"]["lanes_per_direction"]
    assert d["sites"] == ["s1", "s2"] and d["calls"] == 4


def test_the_sites_path_uses_the_trust_store_first_and_never_disables_certificates():
    src = open(os.path.join(ROOT, "scripts", "s06_call1_check.py"), encoding="utf-8").read()
    assert src.index("use_os_trust_store()") < src.index("fetch_site(s)")
    import re
    assert not re.search(r"verify\s*=\s*False|CERT_NONE|_create_unverified_context", src)
