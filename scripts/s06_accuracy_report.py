"""Accuracy of call 1 against known truth, offline and deterministic (S6 accuracy tooling).

  python scripts/s06_accuracy_report.py --results var/s06_call1_check/gpt-5.6-sol [var/s06_call1_check/claude-opus-5-5 ...]
         --truth truth.csv [--second-source osm.csv] [--out report.md] [--json numbers.json]

truth.csv columns:   site_id, lanes_per_direction, divided_highway, shoulder_present, oneway, parking_present, sidewalk_present,
                     work_location, road_width_ft, truth_source, ta_situation (optional, free text)
                     (a blank cell means "no truth for this field at this site")
second-source csv:   site_id, lanes_per_direction, divided_highway, shoulder_present, oneway   (optional; blank = the source has no value)

Each result folder is one profile (folder name); every *.json in it with a raw_response and a site is one call. For each profile and field:
sites scored, correct, wrong, UNKNOWN, and "wrong and used" = a value the tool would pass on that differs from the truth. "Used" follows
the tool's rules: work_location only at the confidence floor and through the registry mapping (marks check not built yet: treated as
missing, so the value carries AI_ONLY_UNCONFIRMED); lanes per direction, divided, shoulder and one-way only when a second source
(the --second-source csv, standing in for OSM) AGREES with the AI - with no second source nothing is passed on; parking and sidewalk
at the common-fact floor (CALIBRATION_PENDING: none applied). Also: repeat stability per site, width error with whether the stated
interval holds the true width, and the one-sided 95 percent upper bound on the wrong-and-used rate over sites (3 / sites when none).
No network, no model call, nothing is changed.
"""
import argparse, csv, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), ROOT]

COLUMNS = ("site_id", "lanes_per_direction", "divided_highway", "shoulder_present", "oneway", "parking_present", "sidewalk_present",
           "work_location", "road_width_ft", "truth_source")
FIELDS = ("lanes_per_direction", "divided_highway", "shoulder_present", "oneway", "parking_present", "sidewalk_present", "work_location")
SECOND_COLUMNS = ("site_id", "lanes_per_direction", "divided_highway", "shoulder_present", "oneway")
BOOL = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}


class TruthError(ValueError): pass


def _parse(field, text, where):
    t = (text or "").strip()
    if t == "": return None
    if field == "lanes_per_direction":
        try: f = float(t)
        except ValueError: raise TruthError(f"{where}: lanes_per_direction {t!r} is not a number")
        if f != int(f) or f < 0: raise TruthError(f"{where}: lanes_per_direction {t!r} is not a whole number")
        return int(f)
    if field == "road_width_ft":
        try: return float(t)
        except ValueError: raise TruthError(f"{where}: road_width_ft {t!r} is not a number")
    if field == "work_location": return t.upper()
    if t.lower() not in BOOL: raise TruthError(f"{where}: {field} {t!r} is not true/false")
    return BOOL[t.lower()]


def read_truth(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (rd.fieldnames or [])]
        if missing: raise TruthError(f"truth csv lacks columns: {', '.join(missing)}")
        out = {}
        for i, row in enumerate(rd, start=2):
            sid = (row["site_id"] or "").strip()
            if not sid: raise TruthError(f"line {i}: empty site_id")
            if sid in out: raise TruthError(f"line {i}: site_id {sid!r} appears twice")
            out[sid] = {**{k: _parse(k, row[k], f"line {i}") for k in FIELDS + ("road_width_ft",)}, "truth_source": (row["truth_source"] or "").strip(),
                      "ta_situation": (row.get("ta_situation") or "").strip()}
    return out


def read_second(path):
    if not path: return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in SECOND_COLUMNS if c not in (rd.fieldnames or [])]
        if missing: raise TruthError(f"second-source csv lacks columns: {', '.join(missing)}")
        return {(r["site_id"] or "").strip(): {k: _parse(k, r[k], f"second source {r['site_id']}") for k in SECOND_COLUMNS[1:]} for r in rd}


def read_results(folder):
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"): continue
        d = json.load(open(os.path.join(folder, name), encoding="utf-8"))
        if "raw_response" in d and "site" in d: out.append({**d, "_file": name})
    return out


def upper_bound_95(k, n):
    """One-sided 95 percent upper bound on a rate with k events in n sites. k = 0: the rule of three, 3 / n (as asked). k > 0: the exact
    Clopper-Pearson bound, p with P(X <= k | n, p) = 0.05. n = 0: 1.0 (nothing is known)."""
    if n <= 0: return 1.0
    if k == 0: return min(1.0, 3.0 / n)
    if k >= n: return 1.0
    cdf = lambda p: sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
    lo, hi = k / n, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > 0.05 else (lo, mid)
    return (lo + hi) / 2


def _observation_value(field, obs, floor_wl, wl_marks):
    """(value the AI gave after the registry mapping, confidence, flags). work_location goes through map_work_location."""
    o = obs[field]
    if field == "work_location":
        from tcp_planner.ai.call1 import map_work_location
        fact, _ = map_work_location(o, wl_marks, floor_wl)
        return (fact.value if fact.status == "RESOLVED" else None), o.confidence, tuple(fact.flags)
    return (o.value if o.status == "RESOLVED" else None), o.confidence, ()


def score(truth, results_by_profile, second=None, cfg=None):
    """The numbers: {profile: {"fields": {...}, "width": {...}}}. Deterministic: sorted everywhere."""
    from tcp_planner.ai.call1 import MARKS_MISSING, parse_call1
    from tcp_planner.site_model import lengths as L
    from tcp_planner.site_model.site_config import call1_setting, confidence_floor, load_site_config
    cfg = cfg or load_site_config(); second = second or {}
    critical = set(call1_setting("safety_critical_fields", cfg))
    report = {}
    for profile in sorted(results_by_profile):
        floor_wl, common_floor, critical_floor = (confidence_floor(k, profile, cfg)[0] for k in ("work_location", "common", "safety_critical"))
        calls = []
        for r in results_by_profile[profile]:
            if r["site"] not in truth: continue
            res = parse_call1(r["raw_response"], tuple(r["image"]["sent_px"]), cfg)
            calls.append((r, res))
        fields = {}
        for field in FIELDS:
            rows = []
            for r, res in calls:
                t = truth[r["site"]][field]
                if t is None: continue
                value, conf, flags = _observation_value(field, res.observations, floor_wl, MARKS_MISSING)
                if field in critical:
                    s = second.get(r["site"], {}).get(field)
                    above = critical_floor is None or (conf is not None and conf >= critical_floor)
                    used = value if (value is not None and above and s is not None and s == value) else None
                elif field == "work_location": used = value
                else: used = value if (value is not None and (common_floor is None or (conf is not None and conf >= common_floor))) else None
                outcome = "UNKNOWN" if value is None else "correct" if value == t else "wrong"
                rows.append({"site": r["site"], "call": r["_file"], "truth": t, "value": value, "confidence": conf, "outcome": outcome,
                             "used": used is not None, "wrong_and_used": used is not None and used != t, "flags": flags})
            sites = sorted({x["site"] for x in rows})
            wu_sites = sorted({x["site"] for x in rows if x["wrong_and_used"]})
            stability = {}
            for s in sites:
                vals = [x["value"] for x in rows if x["site"] == s]
                stability[s] = {"values": vals, "stable": len(set(map(str, vals))) == 1}
            fields[field] = {"sites": sites, "calls": len(rows), "correct": sum(x["outcome"] == "correct" for x in rows),
                             "wrong": sum(x["outcome"] == "wrong" for x in rows), "unknown": sum(x["outcome"] == "UNKNOWN" for x in rows),
                             "used": sum(x["used"] for x in rows), "wrong_and_used": sum(x["wrong_and_used"] for x in rows),
                             "wrong_and_used_sites": wu_sites, "upper95": upper_bound_95(len(wu_sites), len(sites)) if sites else None,
                             "wrong_rows": [x for x in rows if x["outcome"] == "wrong"], "stability": stability}
        wrows = []
        for r, res in calls:
            t = truth[r["site"]]["road_width_ft"]
            if t is None: continue
            tw, why = L.traveled_way_width(res.marks, r["image"]["mpp_sent"])
            if tw is None: wrows.append({"site": r["site"], "call": r["_file"], "truth": t, "measured": None, "reason": why}); continue
            wrows.append({"site": r["site"], "call": r["_file"], "truth": t, "measured": tw.value_ft, "lo": tw.interval_ft.lo, "hi": tw.interval_ft.hi,
                          "error": tw.value_ft - t, "contains": tw.interval_ft.lo <= t <= tw.interval_ft.hi})
        meas = [x for x in wrows if x["measured"] is not None]
        by_ta = {}                          # per ta_situation of the truth csv (optional column), over all scored fields
        for fld in fields.values():
            for site in fld["sites"]:
                by_ta.setdefault(truth[site]["ta_situation"] or "(none)", {"sites": set(), "wrong": 0, "wrong_and_used": 0})["sites"].add(site)
            for x in fld["wrong_rows"]:
                e = by_ta[truth[x["site"]]["ta_situation"] or "(none)"]
                e["wrong"] += 1; e["wrong_and_used"] += bool(x["wrong_and_used"])
        by_ta = {k: {"sites": sorted(v["sites"]), "wrong": v["wrong"], "wrong_and_used": v["wrong_and_used"]} for k, v in sorted(by_ta.items())}
        report[profile] = {"by_ta_situation": by_ta, "fields": fields, "width": {
            "calls": len(wrows), "measured": len(meas), "rows": wrows,
            "mean_abs_error": (sum(abs(x["error"]) for x in meas) / len(meas)) if meas else None,
            "max_abs_error": max((abs(x["error"]) for x in meas), default=None),
            "interval_contains_truth": sum(x["contains"] for x in meas)}}
    return report


def render(report, truth, second, cfg=None):
    from tcp_planner.site_model.site_config import confidence_floor, load_site_config
    cfg = cfg or load_site_config()
    floors = "; ".join(f"{p}: work_location {confidence_floor('work_location', p, cfg)[0]}, safety-critical {confidence_floor('safety_critical', p, cfg)[0] or 'none'}, "
                       f"common {confidence_floor('common', p, cfg)[0] or 'none'}" for p in report)
    out = ["# Call 1 accuracy against truth", "",
           f"Truth: {len(truth)} sites ({', '.join(sorted({t['truth_source'] for t in truth.values() if t['truth_source']})) or 'no truth_source given'}). "
           f"Second source (stands in for OSM): {'%d sites' % len(second) if second else 'none supplied: lanes per direction, divided, shoulder and one-way are never passed on'}. "
           f"Floors applied (per profile, default entry unless the profile has its own; none = CALIBRATION_PENDING): {floors}. "
           "work_location is read with the marks check missing, so a passed-on value carries AI_ONLY_UNCONFIRMED.", ""]
    for profile, rep in report.items():
        if any(k != "(none)" for k in rep["by_ta_situation"]):
            out += [f"## {profile}: by ta_situation (truth csv column)", "", "| ta_situation | sites | wrong answers | wrong and used |", "| --- | --- | --- | --- |"]
            out += [f"| {k} | {', '.join(v['sites'])} | {v['wrong']} | {v['wrong_and_used']} |" for k, v in rep["by_ta_situation"].items()] + [""]
        out += [f"## {profile}", "", "| field | sites scored | calls | correct | wrong | UNKNOWN | passed on | wrong and used | sites with wrong and used | 95% upper bound on wrong-and-used rate |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for f, d in rep["fields"].items():
            ub = "n/a (no sites)" if d["upper95"] is None else f"{d['upper95'] * 100:.1f}% ({'3 / %d' % len(d['sites']) if not d['wrong_and_used_sites'] else 'exact, %d of %d sites' % (len(d['wrong_and_used_sites']), len(d['sites']))})"
            out.append(f"| {f} | {len(d['sites'])} | {d['calls']} | {d['correct']} | {d['wrong']} | {d['unknown']} | {d['used']} | {d['wrong_and_used']} | {len(d['wrong_and_used_sites'])} | {ub} |")
        out += ["", "Wrong answers (value, confidence, whether the tool would pass it on):", ""]
        any_wrong = False
        for f, d in rep["fields"].items():
            for x in d["wrong_rows"]:
                any_wrong = True
                out.append(f"- {f}, {x['site']} ({x['call']}): said {x['value']} but truth {x['truth']}, confidence {x['confidence']}, "
                           f"{'WRONG AND USED' if x['wrong_and_used'] else 'not passed on'}{', ' + ', '.join(x['flags']) if x['flags'] else ''}")
        if not any_wrong: out.append("- none")
        out += ["", "Repeat stability (the same field across the repeated calls of a site):", "", "| field | sites with repeats stable | sites scored | unstable sites (values) |", "| --- | --- | --- | --- |"]
        for f, d in rep["fields"].items():
            st = d["stability"]; uns = "; ".join(f"{s}: {st[s]['values']}" for s in sorted(st) if not st[s]["stable"]) or "-"
            out.append(f"| {f} | {sum(v['stable'] for v in st.values())} | {len(st)} | {uns} |")
        w = rep["width"]
        out += ["", "Road width (traveled way, from the marks; interval = AI-mark error, CALIBRATION_PENDING):", ""]
        if not w["calls"]: out.append("- no truth width for the scored sites")
        else:
            out.append(f"- calls with a truth width: {w['calls']}; measured: {w['measured']}; mean absolute error "
                       f"{'n/a' if w['mean_abs_error'] is None else '%.1f ft' % w['mean_abs_error']}; largest "
                       f"{'n/a' if w['max_abs_error'] is None else '%.1f ft' % w['max_abs_error']}; stated interval holds the true width in "
                       f"{w['interval_contains_truth']} of {w['measured']}")
            out += ["", "| site | call | truth ft | measured ft [interval] | error ft | interval holds truth |", "| --- | --- | --- | --- | --- | --- |"]
            for x in w["rows"]:
                if x["measured"] is None: out.append(f"| {x['site']} | {x['call']} | {x['truth']} | none ({x['reason']}) | | |")
                else: out.append(f"| {x['site']} | {x['call']} | {x['truth']} | {x['measured']:.1f} [{x['lo']:.1f}, {x['hi']:.1f}] | {x['error']:+.1f} | {'yes' if x['contains'] else 'NO'} |")
        out.append("")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", nargs="+", required=True, help="result folder(s), one per profile")
    ap.add_argument("--truth", required=True); ap.add_argument("--second-source"); ap.add_argument("--out"); ap.add_argument("--json")
    a = ap.parse_args(argv)
    try: truth = read_truth(a.truth); second = read_second(a.second_source)
    except TruthError as e: print(f"truth file problem: {e}"); return 2
    by = {}
    for folder in a.results:
        if not os.path.isdir(folder): print(f"no such result folder: {folder}"); return 2
        by[os.path.basename(os.path.normpath(folder))] = read_results(folder)
    rep = score(truth, by, second)
    text = render(rep, truth, second)
    unmatched = sorted(set(truth) - {r["site"] for rs in by.values() for r in rs})
    if unmatched: text += f"\nTruth sites with no result in any folder: {', '.join(unmatched)}\n"
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as f: json.dump(rep, f, indent=1, sort_keys=True, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
