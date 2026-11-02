"""The model comparison table (S6 step 16): offline, deterministic, ranks nothing."""
import importlib.util
import json
import os

import pytest

from tests.unit.site.test_understanding import response

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="module")
def M():
    spec = importlib.util.spec_from_file_location("s06_model_comparison", os.path.join(ROOT, "scripts", "s06_model_comparison.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def write_call(folder, n, site, rep, raw):
    os.makedirs(folder, exist_ok=True)
    json.dump({"call": n, "site": site, "rep": rep, "seconds": 10.0 * n, "input_tokens": 100, "output_tokens": 50 * n, "schema_valid": True,
               "image": {"sent_px": [400, 400], "mpp_sent": 0.1}, "raw_response": raw}, open(os.path.join(folder, f"call{n}.json"), "w", encoding="utf-8"))


def test_the_table_is_built_from_saved_results_and_picks_no_winner(M, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SAVED", str(tmp_path))
    good = response(); wrong = response(marks=[("road_edge_left", "300,100;300,360"), ("road_edge_right", "380,100;380,360"), ("work_point", "200,200")])
    write_call(tmp_path / "p1", 4, "second", 1, wrong); write_call(tmp_path / "p1", 5, "second", 2, good)
    write_call(tmp_path / "p2", 4, "second", 1, good)
    out = tmp_path / "cmp.md"
    assert M.main(["--profiles", "p1", "p2", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "No winner is picked" in text and "## p1" in text and "## p2" in text
    assert text.count("WRONG ROAD SUSPECTED") == 1 and "| 1 of 2 |" in text            # the one wrong-road row, and the per-site count
    assert "| p1 | 2 | 2 | 1 |" in text and "| p2 | 1 | 1 | 0 |" in text
    assert not any(w in text.lower() for w in ("is better", "is best", "recommend", "we choose", "winner:"))


def test_the_same_results_give_the_same_text(M, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SAVED", str(tmp_path)); write_call(tmp_path / "p1", 5, "second", 2, response())
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    M.main(["--profiles", "p1", "--out", str(a)]); M.main(["--profiles", "p1", "--out", str(b)])
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_without_results_it_says_so(M, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "SAVED", str(tmp_path))
    assert M.main(["--profiles", "nothing"]) == 2 and "no saved results" in capsys.readouterr().out


def test_a_later_version_is_read_from_its_own_folder_and_the_version_1_text_is_unchanged(M, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SAVED", str(tmp_path / "s06"))
    write_call(tmp_path / "s06" / "p1", 4, "second", 1, response())
    write_call(tmp_path / "s06_v2" / "p1", 4, "second", 1, response(version=2))
    write_call(tmp_path / "s06_v2" / "p1", 10, "granite_p28", 1, response(version=2))             # a call number outside 1..9 is not read
    one, both = tmp_path / "one.md", tmp_path / "both.md"
    assert M.main(["--profiles", "p1", "--out", str(one)]) == 0 and M.main(["--profiles", "p1", "--versions", "1", "2", "--out", str(both)]) == 0
    a, b = one.read_text(encoding="utf-8"), both.read_text(encoding="utf-8")
    assert b.startswith(a) and "prompt version 2" in b[len(a):] and "## p1 (prompt version 2)" in b
    assert "granite_p28" not in b and "Scope, sources" not in b                               # no truth given: no facts section


def test_the_facts_section_states_scope_wrong_and_used_and_both_width_truths(M, tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SAVED", str(tmp_path / "s06"))
    wrong_parking = response(overrides={"parking_present": ("false", "bool")})
    write_call(tmp_path / "s06" / "p1", 4, "second", 1, wrong_parking); write_call(tmp_path / "s06" / "p1", 5, "second", 2, response(overrides={"parking_present": ("true", "bool")}))
    truth = tmp_path / "truth.csv"
    truth.write_text("site_id,lanes_per_direction,divided_highway,shoulder_present,oneway,parking_present,sidewalk_present,work_location,road_width_ft,truth_source\n"
                     "second,,,,,true,,,27.5,test drawing (provisional)\n", encoding="utf-8")
    out = tmp_path / "cmp.md"
    assert M.main(["--profiles", "p1", "--truth", str(truth), "--proposed-width-ft", "34", "--date", "2026-11-02", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "**Date:** 2026-11-02" in text and "PROVISIONAL" in text and "No winner is picked (D-97)" in text and "truth.csv" in text
    assert "Prompt version 1, p1: 1 wrong-and-used parking_present value (second call4)" in text and str(tmp_path) not in text   # file names only, no local paths
    assert "error vs 27.5 ft (current)" in text and "error vs 34.0 ft (proposed)" in text and "| v1 | p1 | call4 |" in text
    assert not any(w in text.lower() for w in ("is better", "is best", "recommend", "we choose", "winner:"))
