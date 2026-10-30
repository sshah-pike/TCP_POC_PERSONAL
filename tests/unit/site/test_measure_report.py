"""The measurement report script (owner's nine saved results): built from the S6 measurement code, no network."""
import importlib.util, json, os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SPIKE = os.path.join(ROOT, "tests", "fixtures", "site", "spike")


@pytest.fixture
def report(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("s06_measure_report", os.path.join(ROOT, "scripts", "s06_measure_report.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    d = tmp_path / "gpt-x"; d.mkdir()
    n = 0
    for site in ("granite", "second", "colorado"):
        mpp = json.load(open(os.path.join(SPIKE, "inputs", site + ".json"), encoding="utf-8"))["metres_per_pixel"]
        for rep in (1, 2, 3):
            n += 1
            doc = json.load(open(os.path.join(SPIKE, "raw", f"{site}_B_r{rep}.response.json"), encoding="utf-8"))
            text = next(b["text"] for b in doc["content"] if b.get("type") == "text")
            json.dump({"call": n, "site": site, "rep": rep, "image": {"sent_px": [1280, 1280], "mpp_sent": mpp, "resize_scale": 1.0}, "raw_response": text},
                      open(d / f"call{n}.json", "w", encoding="utf-8"))
    monkeypatch.setattr(m, "SAVED", str(tmp_path))
    return m


def test_the_table_has_nine_rows_and_the_columns_the_owner_asked_for(report):
    rows = report.build("gpt-x")
    assert len(rows) == 9
    text = report.render("gpt-x", rows)
    for col in ("traveled way ft [interval]", "road bearing", "work point to each edge", "lane lines / spacing", "checks:", "## Scale used per site"):
        assert col in text
    assert text.count("\n| ") >= 9 + 2


def test_the_east_west_marks_give_a_bearing_near_90_for_the_spike_responses(report):
    rows = {(r["site"], r["rep"]): r for r in report.build("gpt-x")}
    assert all(abs(rows[("second", i)]["pair"].axis_bearing_deg - 90) < 3 for i in (1, 2, 3))      # E Second St runs east-west


def test_the_scale_is_per_site_and_comes_from_the_saved_record(report):
    rows = report.build("gpt-x")
    assert {r["site"]: round(r["mpp"], 6) for r in rows} == {"granite": 0.448139, "second": 0.441419, "colorado": 0.441851}


def test_a_missing_profile_gives_no_rows(report):
    assert report.build("nope") == []
