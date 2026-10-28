# S0a — Restructure report (STEP 8)

Date: 2026-10-28. Branch `tcp-mvp/s00a-restructure`, based on `tcp-mvp/base` (= `b94fafd`, POC Final).
Plan: `docs/reports/S0a_restructure_plan.md`. Baseline: `docs/reports/S0a_baseline.md`.

**Result: the POC is now laid out as a production repository. Behavior is unchanged.** All 13 offline
scenarios and all 36 saved-run replays produce outputs identical to the baseline. Test results equal the
baseline: the same single pre-existing failure, plus one new unit test that passes. Nothing was deleted.
The branch is **not pushed**: the local branch is 9 commits ahead of `origin`, including this report, and you push manually.

---

## 1. Final tree (tracked files, 2 levels)

```
.env.example  .gitignore  CLAUDE.md  README.md  pyproject.toml  requirements.txt
apps/web/                 React + Vite UI (was tcp_ui/web)
assets/{dwt,sheet,symbols}/
backup/orphans/           2026-10-28/ with MANIFEST.json
config/                   pipeline_config.json, dwt_config.json, foundry_profiles.json, pricing.json, assistant/
docs/{architecture,slices,sources,references,reports,notes}/
rule_pack/                APPROVED_TWO_LANE_POC_RULE_PACK.json
scripts/                  build_sheet_frame.py, restore_backup.py
src/tcp_planner/          ai audit config conflicts data_sources evaluation geometry imagery intake layout
                          orchestration review routing rules sheets site_model storage validation web_api
                          cli.py contracts.py
tests/                    unit/ integration/{pipeline,web_api,review_assistant}/ fixtures/kml/ golden/
var/runs/                 782 POC-era run files (tracked); everything else under var/ is ignored
```
Untracked, local only: `var/labels/`, `var/assistant_data/`, `config/assistant/users.local.json`,
`apps/web/{node_modules,dist}`, and your manual archive in `backup/` outside `orphans/`.
Totals: 1101 tracked files. Against `b94fafd`, git counts 1002 renames, 96 additions and 3 modifications.
It also reports 4 deletions, which are moves git cannot match because the files are tiny and their content
changed: `tcp_demo.py`→`src/tcp_planner/cli.py`, `tcp_poc/__init__.py`→`src/tcp_planner/__init__.py`,
`tcp_ui/__init__.py`→`src/tcp_planner/web_api/__init__.py`, `tcp_ui/README.md`→`apps/web/README.md`.

## 2. Commits

| Commit | Content | Checked |
|---|---|---|
| `ce8feea` | Your hand reorganization recorded as renames; 15 superseded docs → `backup/orphans/2026-10-28/docs/`; `.gitignore` `backup/*` + `!backup/orphans/`; CLAUDE.md, assets, golden set, plan and baseline reports added | no code change |
| `bb15698` | docs → `architecture/`, `slices/`, `reports/poc/`, `notes/` | no code change |
| `a72ad06` | Pipeline move (first version), **pushed by you before the amend** | full verification |
| `d5ce8c8` | Pipeline move, amended: editable install, `child_env()` removed, audit-test subprocess path | full verification |
| `de6ff79` | Merge of `a72ad06` and `d5ce8c8`, made outside the session; committed conflict markers in `pyproject.toml` and restored `child_env()` | — |
| `dfb496e` | Fix-forward (your option B): both files restored to `d5ce8c8`; the tree equals `d5ce8c8` | full verification |
| `cd373ca` | `tcp_ui` backend → `tcp_planner`; `check_usgs.py` → backup | full verification |
| `69e8608` | `tcp_assistant` → `tcp_planner.review.assistant`; config → `config/assistant/` | smoke + 2 of 3 suites* |
| `5ae5e7e` | UI → `apps/web/`; npm name `tcp-planner-web` | smoke + build + vitest |
| `4d9fb89` | `runs/` → `var/runs/`; data defaults under `var/`; samples → `tests/fixtures/kml/`; multi-TA package → `docs/references/` | smoke + build |
| `3afd2f0` | README, CLAUDE.md paths and setup, `.env.example` | docs only |
| `7f9a4ae` | Backup manifest, restore script, no-backup-imports test, tool exclusions | smoke + new test |
| `aa2da81` | "POC" dropped from package docstrings; `poc_config` → `pipeline_config` in comments | AST-identical proof |

\* At your request, full verification stopped after `cd373ca`. Later commits got a smoke check: import every
module, CLI and server `--help`, pytest collection (268, then 269 tests), and the UI build where relevant.
Then **one full verification ran on the final tree** (section 4). The `69e8608` partial run had passed the
pipeline and web API suites before it was stopped.

## 3. Moves and renames
Section 2 of the plan applies as approved, with these corrections:
- `tests/integration/pipeline/test_foundry_provider.py` stays with the pipeline suite. The plan's
  `tests/unit/ai/` placement was wrong because the test runs the pipeline and relies on that suite's
  `conftest.py`.
- The backup holds **15** docs, not 13. It is the same approved set: `docs/architecture` 3, `docs/final` 5,
  `docs/reference` 7.
- Planned commit 7 ("tests") was not needed, because each suite moved with its package.
- `scripts/build_sheet_frame.py` is run as `python scripts/build_sheet_frame.py`, not with `-m`.
- No placeholder packages were created. `grouping/` and the `RulePackStore` side of `rules/` do not exist yet.

Module renames are as listed in plan section 2 **(R)**. Package renames: `tcp_poc` → `tcp_planner`,
`tcp_ui` → `tcp_planner.{web_api,storage,orchestration,evaluation,imagery,audit}`, `tcp_assistant` →
`tcp_planner.review.assistant` (`api` → `routes`, `api_review` → `review_routes`, `model/` → `text_model/`).
npm `tcp-poc-runner` → `tcp-planner-web`. CLI: `python -m tcp_planner.cli`, or `tcp-planner` once installed.
Environment variable names and API routes are unchanged.

## 4. Baseline vs after

| Check | Baseline (`b94fafd`) | After (final tree, `7f9a4ae`; `aa2da81` is comments only) |
|---|---|---|
| Pipeline suite | 76 passed | 76 passed |
| UI backend / web API suite | 72 passed, 11 skipped | 72 passed, 11 skipped |
| Assistant suite | 108 passed, 1 failed (pre-existing) | 108 passed, 1 failed (same test) |
| Unit suite | — | 1 passed (new no-backup-imports test) |
| vitest | 19 passed | 19 passed |
| UI build | OK | OK (`apps/web`) |
| CLI `--help` | OK (`tcp_poc.app`) | OK (`tcp_planner.cli`) |
| Server `--help` | OK | OK (`tcp_planner.web_api.server`) |
| Import every module | 108, 0 failures | 102, 0 failures (test modules are no longer inside a package; `check_usgs` is in backup) |
| Offline oracle, 13 scenarios | exit codes 0/3/4 as listed | same exit codes, **all output files identical** |
| Saved-run replay | 36 runs, 0 network attempts | 36 runs, 0 network attempts, **all outputs identical** |

Replay after the move: as you decided, the harness copies `var/runs/` to a temp folder and rewrites the old
absolute `…\TCP\runs\…` paths only inside that copy (66 `ui/request.json` files). No saved record in the
repository was edited.

Pre-existing failure:
`tests/integration/review_assistant/test_global_identity.py::test_protected_untracked_run_directory_untouched`.
It expects `var/runs/20261020-214203-7f7232` (was `runs/…`) to be untracked, but it has been tracked since
`b94fafd`.

Editable install check: `pip install -e . --no-build-isolation --no-deps --no-index` installed
`tcp-planner 0.2.0` from local `setuptools` with no download. With the install present, the identity test's
HEAD run (`git archive HEAD src config rule_pack assets` into a temp dir, `cwd` = temp, `PYTHONPATH` =
temp/src) imports `tcp_planner`, `orchestration.pipeline` and `settings.PROJECT_ROOT` from the **temp tree**,
and `CONFIG_PATH` resolves to temp/config/pipeline_config.json. It does not use the editable install.

## 5. Backups
`backup/orphans/2026-10-28/MANIFEST.json` holds 16 entries, all CONFIRMED_ORPHAN: 15 POC-era docs and
`tcp_ui/check_usgs.py`. Each entry records original and new path, reason, evidence, sha256, git blob, size,
the commit that moved it, the commit before the move, and a restore command. `scripts/restore_backup.py`
lists entries by default and `git mv`s them back with `--apply`, after checking the blob id. Its dry run
verifies all 16.
`backup/`, `spikes/` and `var/` are excluded from pytest (`norecursedirs`), packaging (src-only discovery),
ruff, mypy and coverage. `tests/unit/test_no_backup_imports.py` fails if `src/`, `tests/` or `scripts/`
imports from them. A planted probe import confirmed the test catches it.
Symbol-level cuts (USGS/Esri providers, the Anthropic usage wrapper and its test) wait for S15.

## 6. Code changes beyond moves and imports (no decision logic touched)
1. New `tcp_planner.config.settings`: `PROJECT_ROOT`, `SRC_DIR`, `CONFIG_DIR`, `RULE_PACK_DIR`, `ASSETS_DIR`,
   `VAR_DIR`. Path constants read from it instead of `__file__`. The assistant `flags.PACKAGE_DIR` still
   points at the package, for `prompts/`.
2. `config/dwt_config.json`: `dwt_path` changed to `../assets/dwt/…`, because it is resolved relative to the
   config file.
3. Defaults moved under `var/`: runs, labels, assistant data, debug dumps, and the CLI `--out` default
   (`var/output`, now absolute under the repo root; it was `output` relative to cwd). Env overrides unchanged.
4. The run worker names argparse `cli.py` (was `tcp_demo.py`). This only affects usage and error text.
5. The UI server serves `apps/web/dist`. `child_env()` was **removed**; the subprocesses rely on the editable
   install.
6. `pyproject.toml`: build system, project metadata and dependencies, the `tcp-planner` script, pytest
   `pythonpath`, tool exclusions.
7. Tests: the git-HEAD tests archive `src config rule_pack assets` and run with `PYTHONPATH` set to the
   archived tree. Changed-file checks name the new paths. Repo-root computations were adjusted for the new
   depth. The audit concurrency subprocess adds `src/` to its path. The no-regulatory-literals scan now walks
   the whole package recursively (a superset of the old flat `tcp_poc` scan).
8. Text: `users.local.json` location in a docstring and an API note; one UI hint (`var/runs/…`); the CLI
   docstring; the UI README.

## 7. Proposed renames for later (not applied, per section 3.3)
| Item | Where | Proposed |
|---|---|---|
| `UNSUPPORTED_POC` | decision code, exit map, UI, outputs | `UNSUPPORTED` |
| `SELF_CONFIRMED_POC` | SME exception status | `SELF_CONFIRMED` |
| `APPROVED_FOR_POC` | rule pack status, loader `EXPECTED_STATUS` | replaced by rule pack v1 status (S4) |
| `LOCAL_POC` | identity provider name | `LOCAL` |
| `POC_CONFIGURATION`, `POC_APPROXIMATION` | config status values (hash-verified policy) | `MVP_CONFIGURATION` / `APPROXIMATION` |
| `TCP_POC_IMPLEMENTATION_CONFIG` | `config_id` in `pipeline_config.json` (config hash) | `TCP_PIPELINE_CONFIG` |
| `APPROVED_TWO_LANE_POC_RULE_PACK.json` | rule pack file and id | superseded by rule pack v1 (S4) |
| `APP_VERSION = "tcp-poc 0.2.0"`, `User-Agent: tcp-poc/0.2`, telemetry service `tcp-poc` | outputs, HTTP headers | `tcp-planner …` |
| "TCP POC Pipeline 2", "TCP POC Runner", `TCP-POC (AUTO)`, "UNSUPPORTED POC", "outside the current POC scope" | run report, sheet, UI | product wording |
| `"offset_source": "poc_config.placement…"` | written into `plan.json` | `pipeline_config.placement…` |
| "implementation config (poc_config.json) changed" | resume preview message | name `pipeline_config.json` |
| `TCP_UI_RUNS_DIR`, `TCP_UI_LABELS_DIR` | env vars (kept, per your decision) | `TCP_RUNS_DIR`, `TCP_LABELS_DIR` |
| `tcp_ui` / `tcp_poc` module paths in `var/runs/*/ui/diagnostics.json` (5 files) | historical records | none (records are write-once) |

## 8. Unfinished, follow-ups, known issues
1. **S2 follow-up: store run paths relative to the runs root.** Saved requests hold absolute paths
   (`--kml`, `--out`, `--sme-revision`, `kml_saved_path`), so the 36 POC-era runs cannot be resumed from
   `var/runs/` (accepted). New runs still write absolute paths.
2. **Direct Anthropic default:** `vision_provider.get_vision_provider()` still defaults to the direct Anthropic
   provider when `TCP_AI_PROVIDER` is unset. CLAUDE.md and `.env.example` say Foundry only. Not changed in
   S0a.
3. Pre-existing failing test (section 4): its "untracked" premise no longer holds. Decide whether to fix the
   test or untrack that run.
4. `config/`, `rule_pack/` and `assets/` sit outside the package. This works from a checkout or an editable
   install, not from a built wheel.
5. The editable install is a per-environment step (`pip install -e . --no-build-isolation`). Without it,
   `python -m tcp_planner…` works only from pytest or with `PYTHONPATH=src`.
6. The branch history contains both versions of commit 3 and a merge (section 2), because the first version
   was pushed before the amend.
7. The branch is not pushed: 9 local commits (including this report) on top of `origin/tcp-mvp/s00a-restructure`.

## 9. Where the repo now differs from the plan docs (for you to update)
1. `docs/slices/TCP_MVP_Development_Slices.md` header: "Branch: `TCP-MVP`". The base branch is now
   `tcp-mvp/base` (CLAUDE.md is updated).
2. Slices S0: report path `docs/S0_repo_report.md`. Suggested: `docs/reports/S0_repo_report.md`.
3. Slices S15: "TypeScript in `tcp_ui`" is now `apps/web`. The backup path `backup/orphans/<date>/` matches;
   S0a already used it for 16 files.
4. Plan v4 line 1474 (section 18, item 7): "raw file-path read or write in tcp_poc, tcp_ui and tcp_assistant"
   now refers to `src/tcp_planner/`. Path roots are centralized in `tcp_planner.config.settings`.
5. Slices S4 file layout `rule_pack/base/…`, `rule_pack/ta/…`: the `rule_pack/` folder now exists, holding
   only the POC pack.
6. CLAUDE.md "Never delete files … only in slice S15": S0a moved 16 files early, with your approval (plan
   0.2 A).
7. Module names in the slices doc ("names are proposals") should be checked against plan section 2. Examples:
   eligibility is in `routing/`, the rule engine in `layout/`, run orchestration in `orchestration/`.

## 10. Open questions
1. Push: when should `tcp-mvp/s00a-restructure` (9 local commits) be pushed?
2. The pre-existing failing test (section 8 item 3): fix the test, or untrack the protected run?
3. The direct Anthropic default (section 8 item 2): change it to Foundry in S0, or leave it for S15?
