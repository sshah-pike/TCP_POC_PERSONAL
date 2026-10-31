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
