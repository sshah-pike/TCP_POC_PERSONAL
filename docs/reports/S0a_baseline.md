# S0a — Baseline before any move (STEP 3)

Date: 2026-10-28. Code at `b94fafd` (POC Final), branch `tcp-mvp/s00a-restructure`, with the uncommitted hand
reorganization of docs in the working tree (code untouched). Python 3.15.0 (`.venv`), pytest 9.1.1, Node 24.14.0.
No live Azure Maps or AI calls were made. Credentials were stripped from the environment, and the replay harness
blocked every socket connect.

## Results

| Check | Command | Result |
|---|---|---|
| Pipeline tests | `python -m pytest tcp_poc/tests -q` | **76 passed** |
| UI backend tests | `python -m pytest tcp_ui/tests -q` | **72 passed, 11 skipped** (USGS NAIP, skipped unless `TCP_RUN_USGS_TESTS=1`) |
| Assistant tests | `python -m pytest tcp_assistant/tests -q` | **108 passed, 1 failed** (pre-existing, see below) |
| UI unit tests | `npx vitest run` (tcp_ui/web) | **19 passed** (1 file) |
| UI build | `npm run build` (tcp_ui/web) | **OK** (`tsc --noEmit && vite build`) |
| CLI help | `python -m tcp_poc.app --help` | exit 0 |
| CLI wrapper | `python docs/tcp_demo.py --help` | exit 1 from `docs/` (it was moved there by hand and cannot import `tcp_poc`); exit 0 with `PYTHONPATH=.` |
| Server help | `python -m tcp_ui.server --help` | exit 0 |
| Import every module | `importlib` walk of `tcp_poc`, `tcp_ui`, `tcp_assistant` | **108 modules, 0 failures** |
| Offline scenario oracle | `python -m tcp_poc.app --offline <sc> --no-dwt` for all 13 scenarios | exit codes: supported 0; ai_unavailable, driveway_at_sign, lane_conflict, missing_lane_count, missing_road_type, poor_image 3; encroach, four_lane, intersection, lane_closure, one_way, sidewalk 4. Normalized outputs **identical across two runs** |
| Saved-run replay | strict-replay resume (`relations.create_resume_run(parent, "fusion", strict_replay=True)`, runner in-process) of every saved run whose evidence has map + OSM + AI, on a temp copy of `runs/` | **36 runs**: 8 SUPPORTED_AUTO, 27 REVIEW_REQUIRED, 1 UNSUPPORTED_POC. **0 network attempts.** Normalized outputs **identical across two runs** |

### Pre-existing failure (not caused by S0a)
`tcp_assistant/tests/test_global_identity.py::test_protected_run_dir_untouched` asserts that
`git status --porcelain -- runs/20261020-214203-7f7232` starts with `??`, meaning the directory is untracked.
The directory has been **tracked** since commit `b94fafd`, so the output is empty and the assertion fails. S0a
does not change this test's logic. The failure is carried forward and must be the only failure after S0a.

### Normalization used by the oracles
Only these are masked in text files (`.json`, `.txt`, `.log`): ISO timestamps, span durations
(`  12.3 ms`), the output/run folder path, and the new run id. PDFs are compared with `/CreationDate` and `/ModDate`
masked. Every other binary file (PNG, JPG) is compared byte for byte. The harness scripts are in the session
scratchpad: `replay_harness.py`, `offline_oracle.py`, `hashout.py`.

### Notes found during baseline
- Saved runs store **absolute paths** (`…\TCP\runs\<id>\input\*.kml`, `--out`, `--sme-revision`) in
  `ui/request.json` (128 files under `runs/`). A resume reads the KML from that absolute path. Moving `runs/`
  therefore breaks resume and replay of every historical run. See the restructure report.
- `runs/*/ui/diagnostics.json` (5 files) records exception classes by module path
  (`tcp_poc.models.MapProviderError`). New diagnostics will carry the new module path.
