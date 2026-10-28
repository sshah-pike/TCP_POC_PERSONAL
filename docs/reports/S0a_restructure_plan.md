# S0a — Restructure plan (proposal, nothing moved yet)

Status: **STEP 2 proposal. Awaiting approval. No file has been moved, renamed or edited.**
Date: 2026-10-28. Base commit: `b94fafd` (POC Final). Branch: `TCP-MVP` created at `b94fafd`; the slice
branch could not be created (see 0.1).

The package name is written as `tcp_planner` throughout. That name is only a proposal. Confirm it or replace
it before STEP 3 (see 0.3).

---

## 0. Blockers and decisions needed before STEP 3

### 0.1 Branch names collide on Windows
`git branch TCP-MVP` worked. `git switch -c tcp-mvp/s00a-restructure` failed with
`'refs/heads/tcp-mvp' exists; cannot create 'refs/heads/tcp-mvp/s00a-restructure'`. Windows file names are
case-insensitive, so the ref file `TCP-MVP` and the ref directory `tcp-mvp/` are the same path. The
CLAUDE.md convention (`TCP-MVP` plus `tcp-mvp/sNN-...`) cannot work on this machine.

| Option | Trade-off |
|---|---|
| **A (recommended).** Base branch `tcp-mvp/base`, slices `tcp-mvp/s00a-restructure` and so on | Works everywhere. CLAUDE.md and the slices doc need a one-line update. |
| B. Keep `TCP-MVP`, use flat slice names such as `TCP-MVP-s00a-restructure` | No base rename, but breaks the `tcp-mvp/sNN` pattern the docs use. |
| C. Keep both and rely on packed refs | Breaks again the first time `TCP-MVP` is updated as a loose ref. Not advised. |

Nothing has been pushed, so all options are cheap. Under A, the local `TCP-MVP` branch would be renamed
with `git branch -m`, which deletes nothing.

### 0.2 Backups in S0a conflict with CLAUDE.md and slice S15
- CLAUDE.md, "How to work" 4: *"Unused code goes to `backup/` with a manifest, and only in slice S15 after approval."*
- Slices doc S15: the first orphan sweep runs *after S3*. The path is `backup/orphans/<date>/`, with symbol
  snippets under `snippets/`.
- This prompt, STEP 6: move orphans in S0a to `backup/<date>/`.

| Option | Trade-off |
|---|---|
| **A (recommended).** In S0a, back up only (1) whole files that are already documented as redundant and have no importers (`tcp_ui/check_usgs.py`), and (2) the 13 tracked docs that you already moved by hand into the ignored `backup/` (0.4). Use S15's path `backup/orphans/2026-10-28/`. Leave symbol-level cuts (the USGS and Esri classes, the Anthropic usage wrapper) to S15. | Keeps S0a a pure move. Smallest conflict with the plan. |
| B. No backups in S0a. Everything goes to S15. | Fully plan-consistent. `check_usgs.py` gets moved to a new path and then moved again later. |
| C. Follow STEP 6 in full, using `backup/<date>/` | Conflicts with CLAUDE.md and S15 (path and timing). The docs would need updating. |

### 0.3 Package name
`<PRODUCT_NAME>` was not replaced in the prompt. Proposed name: **`tcp_planner`**. Confirm it or give the
name you want.

### 0.4 Uncommitted working-tree changes (your manual reorganization)
`git status` shows 28 tracked files as deleted. I checked every one by content hash (`git hash-object`
against `HEAD`). **All 28 exist byte-identical at a new location. Nothing is lost.**
- 15 now sit in `docs/`, `docs/references/` or `docs/sources/` (untracked).
- 13 (`docs/architecture/*`, `docs/final/*`, `docs/reference/*`) now sit only in the **gitignored**
  `backup/`. If committed as they are, git would record them as deleted.

Also untracked and new: `CLAUDE.md`, `assets/symbols/`, `tests/golden/`.

Proposed first commit on the slice branch, as a separate area commit:
- record the 15 doc moves as renames (git detects them because the content is identical);
- add `CLAUDE.md`, `assets/`, `tests/golden/`;
- record the 13 hand-moved docs as moves into `backup/orphans/2026-10-28/docs/...`, with a manifest (needs
  0.2 A or C).

If you choose 0.2 B, those 13 go to `docs/archive/` instead. Either way they are never recorded as deleted.

### 0.5 `backup/` is gitignored and already holds 383 MB of untracked material
`.gitignore:7` ignores `backup/`. It already holds your manual archive (`archive/`, `output/`,
`debug_sent/`, `examples/`, `final/`, `reference/`, `architecture/`, `command.txt`).
Proposal: change the ignore rule to `backup/*` plus `!backup/orphans/`, so that only the tracked,
manifest-backed area is versioned. Your existing manual archive stays where it is and stays ignored.

### 0.6 `runs/` is tracked (782 files, about 485 MB on disk) and tests depend on it
`tcp_assistant/tests/test_global_identity.py:12` protects `runs/20261020-214203-7f7232`, a tracked
directory, and runs `git status` on it. If `runs/` is moved to `var/runs/` and gitignored, git would have
to stop tracking those files (`git rm --cached`).

| Option | Trade-off |
|---|---|
| **A (recommended).** `git mv runs var/runs`, keep the existing 782 files tracked, and ignore `var/*` so new runs are not tracked. Update the protected path in the test. | Nothing leaves the tree. New output stays out of git. The repo stays big. |
| B. Move it and untrack it with `git rm --cached` | Smaller tree, but the files leave the branch (history keeps them). The protected-run test needs a new fixture. |
| C. Leave `runs/` where it is for now | No risk, but it misses the goal. |

---

## 1. Inventory (STEP 1 findings)

### 1.1 Top level
| Path | Tracked | What it is |
|---|---|---|
| `tcp_poc/` | 42 files | Pipeline package (CLI `python -m tcp_poc.app`) |
| `tcp_ui/` | 69 files | Python local API server, run store and runner, plus the React/Vite UI in `tcp_ui/web` |
| `tcp_assistant/` | 60 files | SME Review Assistant, **Python**, mounted by `tcp_ui/server.py` under `/api/assistant/*` |
| `TCP_MULTI_TA_POC_PACKAGE/` | 14 | Reference package: multi-TA rule pack v2, router, schemas, 6 KMLs. No code reads it. |
| `samples/kml/` | 8 | Demo and real KMLs used for manual runs |
| `runs/` | 782 | Saved UI runs (`input/`, `output/`, `ui/`, `evidence/`) |
| `docs/` | 3 tracked + new untracked | Plan, slices, sources, references, POC notes |
| `tests/golden/` | untracked | Golden set v0.1 plus `build.py` and `extract.py` |
| `assets/symbols/` | untracked | Device catalog, SVG symbols, `gen.py`, gallery |
| `requirements.txt`, `.gitignore`, `.env.example` | tracked | No `pyproject.toml`, `setup.py`, `pytest.ini` or `README.md` at the root |
| `.env` | ignored, never committed (`git log --all -- .env` is empty) | Local secrets |
| `labels/`, `assistant_data/` (17 MB) | ignored | UI ground-truth labels and assistant storage |
| `.venv/`, `.pytest_cache/`, `.vscode/` | ignored | Local tooling |
| `*.zip` (`tests/tcp_golden_set_v0.1.zip`, `assets/tcp_symbol_library_v0.1.zip`) | ignored by `*.zip` | Source archives of the golden set and symbol library |

**CI and Docker:** none (no `.github/`, Dockerfile, or pipeline YAML).

### 1.2 Entry points
| Entry | Defined in |
|---|---|
| CLI pipeline `python -m tcp_poc.app` / `python tcp_demo.py` | `tcp_poc/app.py:main` (argparse at :450-475); `docs/tcp_demo.py` (moved from the root, 15 lines) |
| UI server `python -m tcp_ui.server` (:8765) | `tcp_ui/server.py` |
| Run worker subprocess `python -m tcp_ui.runner <run_dir>` | `tcp_ui/runner.py` (calls `tcp_poc.app.main(argv)` in-process) |
| Maintenance: `python -m tcp_poc.sheet_template <pdf>`, `python -m tcp_poc.sme_policy --rehash`, `python -m tcp_ui.check_usgs` | the respective modules |
| UI: `npm run dev/build/test` | `tcp_ui/web/package.json` (name `tcp-poc-runner`), Vite proxies `/api` to `:8765` |
| Tests | `tcp_poc/tests` (51 tests), `tcp_ui/tests` (60), `tcp_assistant/tests` (82), `tcp_ui/web/src/assistant/__tests__` (vitest). These are counts of `def test_` and exclude parametrization. |

### 1.3 Python import graph (AST, all `.py` outside `.venv`, `backup` and `node_modules`)
- `tcp_ui` → `tcp_poc` (runner, server, store, relations, evidence)
- `tcp_assistant` → `tcp_poc` (sme_*, plan_adjustments, foundry_provider) and → `tcp_ui` (store, relations, labels, server via `sys.modules`)
- `tcp_poc` imports neither `tcp_ui` nor `tcp_assistant`.
- Modules nobody imports, apart from tests and entry points: `tcp_poc.sheet_template` (CLI tool), `tcp_ui.check_usgs`, and `tcp_assistant.services.{decision,exception,review}_tools`. The last three are loaded dynamically by `tcp_assistant/services/registry.py:10` with `importlib.import_module(f"tcp_assistant.services.{mod}")`.
- **String-based module references that must be edited by hand** (an import rewrite will not catch them):
  `registry.py:10,12`; `__import__("tcp_ui.store"…)` `assistant_state.py:220`;
  `__import__("tcp_assistant.services…")` in `clarify_forms.py:165`, `conversations.py:145`, `interpret_tools.py:343`, `test_phase2_review.py:91`;
  `sys.modules.get("tcp_ui.server")` in `assistant_state.py:137`, `pipeline_controller.py:112`, `test_phase4_versions.py:231,238`;
  `-m tcp_poc.app` in `test_global_identity.py:22`; `-m tcp_ui.runner` and `sys.argv[0]="tcp_demo.py"` in `tcp_ui/runner.py:647` and server spawn code.
- **Tests that read git `HEAD` by path** (they will silently pass or fail after a move, so they must be updated):
  `test_global_identity.py:15` (`git archive HEAD tcp_poc`, then runs the HEAD pipeline as an oracle), `:59-61` and
  `test_phase3_decisions.py:152-153` (`git diff HEAD -- tcp_poc/validators.py …`), and `:71` (protected run dir).

### 1.4 How config and data are located today
| Thing | How it is found | File:line |
|---|---|---|
| Project root | `dirname(dirname(__file__))` of the package | `tcp_poc/rule_pack.py:9`, `tcp_ui/store.py:13`, `tcp_assistant/flags.py:6` |
| `.env` | `PROJECT_ROOT/.env`, then `cwd/.env` | `tcp_poc/app.py:38`, `tcp_assistant/flags.py:12` |
| Rule pack | `TCP_RULE_PACK` or `tcp_poc/APPROVED_TWO_LANE_POC_RULE_PACK.json` | `tcp_poc/rule_pack.py:7,36` |
| Pipeline config | `tcp_poc/poc_config.json` (`--config` overrides) | `tcp_poc/app.py:26` |
| DWT config / template | `tcp_poc/dwt_config.json`, `tcp_poc/assets/dwt/*.dwt` | `tcp_poc/app.py:27` |
| Sheet frame | `tcp_poc/assets/sheet/` | `sheet_renderer.py:9`, `sheet_template.py:16` |
| Foundry profiles | `TCP_FOUNDRY_PROFILES_FILE` or `tcp_poc/foundry_profiles.json` | `foundry_provider.py:242` |
| SME action policy | `TCP_SME_ACTION_POLICY` or `PROJECT_ROOT/tcp_assistant/config/SME_ACTION_POLICY.json` (hash-verified) | `tcp_poc/sme_policy.py:13` |
| Pricing | `tcp_ui/pricing.json` | `tcp_ui/store.py:14` |
| Runs | `TCP_UI_RUNS_DIR` or `PROJECT_ROOT/runs` | `tcp_ui/store.py:61` |
| Labels | `TCP_UI_LABELS_DIR` or `PROJECT_ROOT/labels` | `tcp_ui/labels.py:27` |
| Assistant data | `TCP_ASSISTANT_DATA_DIR` or `PROJECT_ROOT/assistant_data` | `tcp_assistant/flags.py:32` |
| Debug dumps | `PROJECT_ROOT/debug_sent` | `tcp_poc/foundry_provider.py:309` |
| CLI output | `--out output` (**relative to cwd**) | `tcp_poc/app.py:462` |
| Built UI | `tcp_ui/web/dist` | `tcp_ui/server.py:23` |
| Assistant users | `TCP_ASSISTANT_USERS_FILE` or `tcp_assistant/config/users.local.json` | `tcp_assistant/core/identity.py:49` |

No hardcoded absolute paths were found. Every path is relative to `__file__`, `PROJECT_ROOT` or cwd.

### 1.5 Secrets
- No real secret is tracked. `.env` was never committed, and `.env.example` has empty key placeholders.
- Two test fixtures contain **fake** key-shaped strings by design: `tcp_ui/tests/test_diagnostics.py:188` (a fake
  Azure key in a URL used to test redaction) and `tcp_ui/tests/test_ui_adapter.py:14` (`SECRET = "sk-tes…"`).
  Both stay as they are.
- `runs/*/ui/result.json` and `rule_pack.json` contain long hex strings. These are SHA-256 hashes, and no
  key/token/secret field names appear.
- `.env.example` is already complete for the active path. Nothing needs to move out of tracked files.

---

## 2. Mapping: current path → new path → reason

`P` = `src/tcp_planner`. Every move is a `git mv`. Module renames are marked **(R)**.

### 2.1 `tcp_poc/` (pipeline)
| Current | New | Reason |
|---|---|---|
| `tcp_poc/__init__.py` | `P/__init__.py` | package root |
| `tcp_poc/app.py` | `P/orchestration/pipeline.py` **(R)** | the end-to-end run (`main`, `run_pipeline`); keeps its `__main__` |
| `tcp_poc/offline.py` | `P/orchestration/offline_scenarios.py` **(R)** | the `--offline` synthetic scenarios used by the CLI and tests |
| `tcp_poc/kml_input.py` | `P/intake/kml_reader.py` **(R)** | KML/coordinates → ProjectGeometry |
| `tcp_poc/geometry.py` | `P/geometry/local_frame.py` **(R)** | ENU frame, stationing, projection |
| `tcp_poc/map_provider.py` | `P/imagery/map_provider.py` | Azure Maps (+ inactive USGS/Esri, see §4) |
| `tcp_poc/osm_adapter.py` | `P/data_sources/osm_overpass.py` **(R)** | OSM adapter |
| `tcp_poc/vision_provider.py` | `P/ai/vision_provider.py` | provider interface + observation contract |
| `tcp_poc/foundry_provider.py` | `P/ai/foundry_provider.py` | Foundry client |
| `tcp_poc/anthropic_provider.py` | `P/ai/anthropic_direct_provider.py` **(R)** | KEEP in S0a (see §4) |
| `tcp_poc/agent.py` | `P/ai/vision_agent.py` **(R)** | the two-call agent |
| `tcp_poc/grounded.py` | `P/ai/grounded_vision.py` **(R)** | grounded_v2 mode (still imported by agent and foundry) |
| `tcp_poc/cross_section.py` | `P/site_model/cross_section.py` | deterministic cross-section from imagery |
| `tcp_poc/site_fusion.py` | `P/site_model/fusion.py` **(R)** | fusion → SiteModel |
| `tcp_poc/eligibility.py` | `P/routing/eligibility.py` | supported/review/unsupported classification (the router's place) |
| `tcp_poc/rule_pack.py` | `P/rules/rule_pack_loader.py` **(R)** | loader; `PROJECT_ROOT` moves to `P/config/settings.py` |
| `tcp_poc/rule_engine.py` | `P/layout/rule_engine.py` | deterministic TA-1 rule execution and placement |
| `tcp_poc/validators.py` | `P/validation/validators.py` | independent validators |
| `tcp_poc/sme_disposition.py` | `P/conflicts/sme_disposition.py` | SME exception layer (the plan puts exceptions in `conflicts/`) |
| `tcp_poc/sme_overlay.py` | `P/review/decision_overlay.py` **(R)** | SME decisions → effective site model |
| `tcp_poc/sme_pipeline.py` | `P/review/revision_derivation.py` **(R)** | post-fusion derivation for preview and revision |
| `tcp_poc/sme_policy.py` | `P/review/action_policy.py` **(R)** | SME_ACTION_POLICY loader |
| `tcp_poc/sme_revision.py` | `P/review/sme_revision.py` | revision input |
| `tcp_poc/plan_adjustments.py` | `P/review/plan_adjustments.py` | SME placement adjustments |
| `tcp_poc/renderers.py` | `P/sheets/debug_renderers.py` **(R)** | debug plan PNG/PDF |
| `tcp_poc/sheet_renderer.py` | `P/sheets/sheet_renderer.py` | CADD-style sheet |
| `tcp_poc/sme_render.py` | `P/sheets/sme_exception_text.py` **(R)** | exception text on artifacts |
| `tcp_poc/dwt_renderer.py` | `P/sheets/dwt_renderer.py` | DWT/CAD output |
| `tcp_poc/sheet_template.py` | `scripts/build_sheet_frame.py` **(R)** | one-off frame builder; nothing imports it |
| `tcp_poc/telemetry.py` | `P/audit/telemetry.py` | spans |
| `tcp_poc/models.py` | `P/contracts.py` **(R)** | shared decisions, reason codes, errors, canonical JSON. *Not in the target layout; proposed.* |
| `tcp_poc/APPROVED_TWO_LANE_POC_RULE_PACK.json` | `rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json` | data out of code. **Name kept** (§3.3) |
| `tcp_poc/poc_config.json` | `config/pipeline_config.json` **(R)** | thresholds config |
| `tcp_poc/dwt_config.json` | `config/dwt_config.json` | renderer config |
| `tcp_poc/foundry_profiles.json` | `config/foundry_profiles.json` | model profile registry |
| `tcp_poc/assets/sheet/{sheet_frame.png,sheet_layout.json}` | `assets/sheet/` | static assets |
| `tcp_poc/assets/dwt/DCR-TMP-AERIAL IMAGE-TEMPLATE.dwt` | `assets/dwt/` | static asset |
| `tcp_poc/tests/conftest.py`, `__init__.py` | `tests/integration/pipeline/` | suite fixtures kept per suite |
| `tcp_poc/tests/test_pipeline.py` | `tests/integration/pipeline/test_pipeline.py` | offline end-to-end |
| `tcp_poc/tests/test_foundry_provider.py` | `tests/unit/ai/test_foundry_provider.py` | provider unit tests with fakes |

### 2.2 `tcp_ui/` (Python API, run store, React UI)
`tcp_ui` holds two things: a Python backend and a TS frontend. The backend goes into the package. Only the TS
app goes to `apps/web/`.

| Current | New | Reason |
|---|---|---|
| `tcp_ui/server.py` | `P/web_api/server.py` | HTTP API + static host. *`web_api/` is not in the target layout; proposed* |
| `tcp_ui/store.py` | `P/storage/run_store.py` **(R)** | local run storage (becomes the local `StateStore`/`ArtifactStore` adapters in a later slice) |
| `tcp_ui/evidence.py` | `P/storage/evidence_store.py` **(R)** | persists provider results for replay |
| `tcp_ui/runner.py` | `P/orchestration/run_worker.py` **(R)** | one pipeline run per process |
| `tcp_ui/relations.py` | `P/orchestration/run_relations.py` **(R)** | resume runs and comparisons |
| `tcp_ui/views.py` | `P/imagery/evidence_views.py` **(R)** | extra map views per site |
| `tcp_ui/diagnostics.py` | `P/audit/provider_diagnostics.py` **(R)** | sanitized provider-failure diagnostics |
| `tcp_ui/labels.py` | `P/evaluation/ground_truth_labels.py` **(R)** | human labels. *`evaluation/` not in target; proposed* |
| `tcp_ui/evaluation.py` | `P/evaluation/comparison_scoring.py` **(R)** | scores comparisons against labels |
| `tcp_ui/check_usgs.py` | `backup/orphans/2026-10-28/tcp_ui/check_usgs.py` | CONFIRMED_ORPHAN (§4) |
| `tcp_ui/pricing.json` | `config/pricing.json` | config |
| `tcp_ui/README.md` | `apps/web/README.md` | paths and commands updated |
| `tcp_ui/__init__.py` | `P/web_api/__init__.py` | |
| `tcp_ui/web/**` (index.html, package*.json, tsconfig, vite/vitest config, `src/**` 47 files) | `apps/web/**` | UI app. `node_modules/` and `dist/` are ignored, so they are rebuilt, not moved |
| `tcp_ui/tests/{__init__,conftest,inproc}.py` | `tests/integration/web_api/` | suite helpers |
| `tcp_ui/tests/test_{ui_adapter,evidence_resume,grounded,azure_maps_diagnostics,diagnostics}.py` | `tests/integration/web_api/` | in-process run tests |

### 2.3 `tcp_assistant/` → `P/review/assistant/`
It is Python, imported by the server, and has no separate process. Proposed: **`P/review/assistant/`**.

| Current | New |
|---|---|
| `tcp_assistant/{__init__,api,api_review,flags}.py` | `P/review/assistant/` (same names; `api_review.py` → `review_routes.py` **(R)**, `api.py` → `routes.py` **(R)**) |
| `tcp_assistant/core/*.py` (10) | `P/review/assistant/core/` |
| `tcp_assistant/model/*.py` (4) | `P/review/assistant/text_model/` **(R dir)**, because `model` is ambiguous next to site_model |
| `tcp_assistant/repositories/*.py` (3) | `P/review/assistant/repositories/` |
| `tcp_assistant/services/*.py` (22) | `P/review/assistant/services/` |
| `tcp_assistant/prompts/sme_intent_v1.txt` | `P/review/assistant/prompts/` (package data, versioned prompt) |
| `tcp_assistant/config/{SME_ACTION_POLICY,assistant_profiles,review_geometry_config,sme_review_guardrails_v1,users.example}.json` | `config/assistant/` (content unchanged; the policy hash is still valid) |
| `tcp_assistant/config/users.local.json` (ignored) | `config/assistant/users.local.json` (ignore rule updated) |
| `tcp_assistant/tests/*` (13) | `tests/integration/review_assistant/` |

### 2.4 Root, docs, data
| Current | New | Reason |
|---|---|---|
| `docs/tcp_demo.py` (was `tcp_demo.py`) | `P/cli.py` | the entry point; `[project.scripts] tcp-planner = "tcp_planner.cli:main"` |
| `docs/TCP_MVP_Architecture_Plan_v4.md` | `docs/architecture/` | plan |
| `docs/{grouping,input_schema,precalculation}_flow.mermaid` | `docs/architecture/` | diagrams |
| `docs/TCP_MVP_Development_Slices.md`, `docs/schema_spike_prompt.md` | `docs/slices/` | slice specs, spike prompt |
| `docs/sources/*`, `docs/references/*.pdf` | unchanged | already in place |
| `TCP_MULTI_TA_POC_PACKAGE/kml/*` (6) | `docs/references/kml/` | CLAUDE.md says `docs/references/` holds the three KMLs, but **today it holds none**. These include the three real ones |
| `TCP_MULTI_TA_POC_PACKAGE/{README.md,manifest.json,ai/,routing/,rule_pack/,schemas/}` | `docs/references/multi_ta_package/` | reference input for S4/S6, not runtime. Inner file names kept (§3.3) |
| `samples/kml/*` (8) | `tests/fixtures/kml/` | demo/test inputs |
| `docs/REDUNDANT_CODE.md`, `RECOMMENDED_CHANGES.md`, `AGENT_REQUESTS_ALTON_RUN1.md` | `docs/reports/poc/` | historical POC reports |
| `docs/things to do .txt` | `docs/notes/backlog.txt` **(R)** | notes. *`docs/notes/` not in target; proposed* |
| `docs/symbols_preview.png` (an older version than `assets/symbols/symbols_preview.png`) | `docs/references/symbols_preview_poc_v0.png` **(R)** | SUSPECT duplicate, kept |
| `assets/symbols/gen.py` | `scripts/generate_symbol_placeholders.py` **(R)** | one-off generator |
| `tests/golden/*` | unchanged | already in place |
| `requirements.txt` | kept; deps also declared in new `pyproject.toml` | |
| — (new) | `pyproject.toml`, `README.md`, `P/config/settings.py`, `scripts/restore_backup.py`, `tests/unit/test_no_backup_imports.py` | required by STEP 5 and 6. Only `settings.py` holds code that is moved (path constants), not new logic |
| `runs/**` (782) | `var/runs/**` | §0.6 |
| `labels/` (ignored) | `var/labels/` | default path updated; `TCP_UI_LABELS_DIR` still overrides |
| `assistant_data/` (ignored) | `var/assistant_data/` | default updated; `TCP_ASSISTANT_DATA_DIR` still overrides |
| `debug_sent/`, `output/` (not present; ignored) | `var/debug_sent/`, `var/output/` | default updated (`--out` default becomes `var/output`) |

### 2.5 Target layout differences, proposed
- Added subpackages that the target does not list: `web_api/` (HTTP server), `evaluation/` (labels and model
  comparison scoring), `contracts.py` (shared types).
- Target subpackages that will be **empty after S0a**: `grouping/` and the rule-pack store side of `rules/`.
  No code exists for them, so I will create no placeholder `__init__.py` unless you want one.

---

## 3. Renames

### 3.1 Packages and distributions
| Old | New | Where it must change |
|---|---|---|
| `tcp_poc` | `tcp_planner` (+ subpackage) | every import (~150 statements), `-m tcp_poc.app` strings, docstrings, `.env.example` comments, README |
| `tcp_ui` | `tcp_planner.web_api` / `.storage` / `.orchestration` / `.evaluation` | imports, `sys.modules.get("tcp_ui.server")` ×4, `__import__("tcp_ui.store")`, `-m tcp_ui.runner` spawn, vite comment |
| `tcp_assistant` | `tcp_planner.review.assistant` | imports, `registry.py` f-string, 5 `__import__` strings |
| npm package `tcp-poc-runner` | `tcp-planner-web` | `apps/web/package.json`, `package-lock.json` (name field only) |
| `tcp_demo.py` CLI | `tcp-planner` script / `python -m tcp_planner.cli` | `runner.py:647` (`sys.argv[0]`), docstrings, README |

### 3.2 Module renames
See the **(R)** rows in §2. No public function or class names change in S0a.

### 3.3 Things that keep "poc" on purpose (renaming them would change behavior or output bytes)
| Item | Why it stays |
|---|---|
| Decision/reason codes `UNSUPPORTED_POC` (27 uses), `SELF_CONFIRMED_POC` (12), `APPROVED_FOR_POC`, `LOCAL_POC`, `POC_CONFIGURATION` | They are written into `eligibility_result.json`, `plan.json`, exit-code maps and the UI. Renaming them changes outputs and breaks the byte-identity test and saved-run replay. **Proposed rename list for later approval:** `UNSUPPORTED_POC → UNSUPPORTED`, `SELF_CONFIRMED_POC → SELF_CONFIRMED`, and so on. |
| Rule pack file name `APPROVED_TWO_LANE_POC_RULE_PACK.json` and its content | Content is hash-verified, and run records carry its identity. A file rename alone does not change the hash, but it is visible in `rule_pack.json` of saved runs. I propose keeping the name until S4 replaces it with rule pack v1. |
| `TCP_MULTI_TA_POC_PACKAGE` inner file names (`APPROVED_MULTI_TA_POC_RULE_PACK_v2.json`) | Reference data |
| Output strings such as `"TCP POC Pipeline …"` and `"TCP POC Runner"` in reports, sheet text and UI title | They change output bytes (run_report.txt, UI). Proposed for a later approved rename. |
| Comments and docstrings that say "POC" | **Will be fixed** where they name the package. Comments describing POC scope ("not in POC scope") are left alone, because they are accurate history until the code is replaced. |
| Everything under `var/runs/`, `backup/`, `docs/reports/poc/` | data or history |

---

## 4. Backup candidates

Evidence sources: **IG** = import graph, **SS** = repo-wide string search, **CFG** = config/CI (there is no CI),
**GH** = git history.

| Item | Label | Evidence |
|---|---|---|
| `tcp_ui/check_usgs.py` (whole file) | **CONFIRMED_ORPHAN** | IG: nothing imports it. SS: referenced only in its own docstring and `docs/REDUNDANT_CODE.md:13`. CFG: not referenced; the UI hides `usgs_naip` (`tcp_ui/store.py:22-24`). GH: added in `1d5aa36` (POC V1), never changed. USGS **NAIP imagery** is not an allowed source (only USGS 3DEP elevation is, per D-53). |
| 13 docs you already hand-moved (`docs/architecture/*` 3, `docs/final/*` 5, `docs/reference/*` 7, minus duplicates) | **CONFIRMED_ORPHAN** (your decision) | SS: no code reference. You already moved them out by hand. `docs/final/flow.pdf` and the Proposal docx have duplicates in `backup/archive/duplicates/`. |
| `UsgsNaipProvider`, `EsriDemoProvider` classes and their `get_map_provider` branches (`map_provider.py:138-197,230-231`), `"usgs_naip"`/`"esri_demo"` in `store.py:20`, env `TCP_USGS_NAIP_*` | **SUSPECT** (listed only) | IG: reachable via `TCP_MAP_PROVIDER`. A symbol-level cut edits code, which is S15's method. |
| `tcp_ui/tests/test_diagnostics.py` | **SUSPECT** | Tests the USGS provider; skipped unless `TCP_RUN_USGS_TESTS=1`. It moves together with the provider in S15. |
| `tcp_poc/anthropic_provider.py` (direct Anthropic API) | **SUSPECT, KEEP in S0a** | IG: imported lazily by `vision_provider.py:162-165`, **and it is the default when `TCP_AI_PROVIDER` is unset**. Moving it changes behavior for an unset environment, so it is out of S0a. |
| `_install_anthropic_usage` (`tcp_ui/runner.py:134,489-528`) and its test (`test_ui_adapter.py:174-195`), `"anthropic"` in `pricing.json`/`store.py:21` | **SUSPECT** | Symbol-level; goes to S15 |
| `tcp_poc/grounded.py`, `tcp_ui/views.py`, `runner.prepare_views()` | **KEEP** | IG: imported and executed (REDUNDANT_CODE.md §4 says the views are computed but not sent) |
| `tcp_poc/sheet_template.py` | **KEEP** (→ scripts/) | maintenance tool, documented in `requirements.txt` |
| Duplicate KMLs: `samples/kml/4) AI IMPORT - 1A8G8FM…kml` is identical to `GRANITE1.kml`, and 3 KMLs are identical between `samples/` and the multi-TA package | **SUSPECT** | content hash equal. Both copies are kept in S0a |
| Old debug dumps (`debug_sent/`) | n/a | **Not in the repo.** They exist only in your ignored `backup/debug_sent/`. Nothing to move |

---

## 5. Run outputs and debug folders → `var/` (gitignored)
`runs/` → `var/runs/` (see §0.6), `labels/` → `var/labels/`, `assistant_data/` → `var/assistant_data/`,
`debug_sent/` → `var/debug_sent/`, CLI `--out` default `output` → `var/output/`.
`.gitignore`: add `var/*`, keep the existing tracked `var/runs` content if §0.6 A is chosen, and remove the
now-obsolete `labels/`, `output/`, `debug_sent/` and `assistant_data/` lines. Ignored folders are moved with a
plain `mv`, because they are not tracked.

## 6. Cannot move safely, or needs care
1. **`test_global_identity.py`** uses `git archive HEAD tcp_poc` as a regression oracle (the committed
   pipeline). After the move, the oracle must archive `src`, `config`, `rule_pack` and `assets`, and run
   `-m tcp_planner.orchestration.pipeline`. In the commit that performs the move itself, HEAD and the working
   tree are different layouts. To avoid that, the test edit goes in the **same commit** as the pipeline move,
   and the oracle compares against the new layout from the next commit onward.
2. **`git diff HEAD -- tcp_poc/validators.py …`** tests (`test_global_identity.py:59-61`,
   `test_phase3_decisions.py:152-153`) would pass vacuously once those paths no longer exist. The paths are
   updated in the same commit.
3. **Saved-run replay and resume:** `tcp_ui/relations.py` evidence and resume compatibility read
   `runs/<id>/ui/rule_pack.json` and the run request. If either stores a **path** to the rule pack or config,
   replay compatibility could change after the move. STEP 3 records replay results so STEP 7 can show this.
   If it breaks, I stop and report; I will not patch the old records.
4. **Package data outside the package:** `config/`, `rule_pack/` and `assets/` sit at the repo root, so they
   resolve through `settings.PROJECT_ROOT`. This works from a checkout or an editable install
   (`pip install -e .`), not from a built wheel. That is fine for the MVP (no packaging target); it is noted for
   later.
5. **`pip install -e .`** into `.venv` becomes required, because the run worker subprocess
   `python -m tcp_planner.orchestration.run_worker` must import the package from `src/`. Pytest gets
   `pythonpath = ["src", "."]`.
6. **`SME_ACTION_POLICY.json`** is hash-verified. It moves with no content change, so the hash still holds.

## 7. Environment variables and API routes
**Kept unchanged:** every variable in §1.4 plus `TCP_AI_PROVIDER`, `TCP_FOUNDRY_*`, `ANTHROPIC_FOUNDRY_*`
aliases, `AZURE_MAPS_KEY`/`AZURE_MAPS_SUBSCRIPTION_KEY`/`AZURE_MAPS_API_VERSION`, `TCP_MAP_PROVIDER`,
`TCP_AI_EFFORT`, `TCP_RENDER_SHEET`, `TCP_ODA_FILE_CONVERTER`, `TCP_TELEMETRY_CONSOLE`,
`TCP_SME_ASSISTANT_ENABLED`, `TCP_DEBUG_SENT`, and the USGS/Anthropic-direct ones. API routes `/api/runs*`,
`/api/labels*` and `/api/assistant/*` are unchanged.

**Proposed renames (not applied without approval):**
| Old | Proposed | Reason |
|---|---|---|
| `TCP_UI_RUNS_DIR` | `TCP_RUNS_DIR` | runs are no longer UI-only |
| `TCP_UI_LABELS_DIR` | `TCP_LABELS_DIR` | same |
| `TCP_RUN_USGS_TESTS` | (drop in S15 with the provider) | |

## 8. Where the repo now differs from the plan docs (for you to update)
1. Branch naming collision (§0.1).
2. Backup timing and path (§0.2).
3. CLAUDE.md "Documents" table: plan → `docs/architecture/…`, slices and spike prompt → `docs/slices/…`.
   STEP 5 updates CLAUDE.md paths as part of this slice, unless you would rather edit CLAUDE.md yourself.
4. CLAUDE.md says `docs/references/` holds three KMLs. Today it holds none (this plan fixes that, §2.4).
5. Slices doc S0 report path `docs/S0_repo_report.md` vs this prompt's `docs/reports/`. I suggest
   `docs/reports/S0_repo_report.md`.
6. Slices doc S15 mentions "TypeScript in `tcp_ui`". After S0a it is `apps/web`.
7. The direct Anthropic provider is the code default when `TCP_AI_PROVIDER` is unset, while CLAUDE.md and
   `.env.example` say Foundry is the only provider. Not changed in S0a (it would be a behavior change);
   flagged for S0 or S15.

## 9. Commit plan (STEP 4, after approval)
1. Commit your hand reorganization (§0.4) plus `.gitignore` backup rule (§0.5).
2. `docs/` restructure.
3. Pipeline `tcp_poc` → `src/tcp_planner/**` + `config/` + `rule_pack/` + `assets/`, with imports and the
   git-HEAD tests fixed **in the same commit** so every commit passes. STEP 5 says to fix references after
   moving; a commit with broken imports is not useful, so I fix each area's references inside that area's
   commit.
4. `tcp_ui` backend → package.
5. `tcp_assistant` → `review/assistant`.
6. UI → `apps/web`.
7. Tests → `tests/{unit,integration}`.
8. Data → `var/`, `samples/`, multi-TA package.
9. `pyproject.toml`, README, `.env.example` comments, CLAUDE.md paths.
10. Backups + manifest + restore script + no-import test (scope per §0.2).
