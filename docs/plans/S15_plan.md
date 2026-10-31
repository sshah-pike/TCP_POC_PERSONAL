Status: PLANNED, PAUSED until the accuracy gate between S7 and S8 (D-153, FS-21). Owner decisions are in docs/decisions/OWNER_DECISIONS_2026-10-30.md and docs/decisions/OWNER_DECISIONS_2026-10-31.md; where they differ from this plan, the registers win.

# S15 plan: orphan sweep (unused files and code to backup)

Planning only. Two runs, per the slices doc: **run 1** after S3 (S3 is merged, so run 1 can start now or be folded into run 2, B-1) and **run 2** after S14. Branches when built: `tcp-mvp/s15a-orphans` and `tcp-mvp/s15b-orphans`, each off the last merged slice. Written on `tmp/plan-base4` (S1 to S4 merged). Nothing moves until the owner approves the candidate list. Nothing is ever deleted.

Read for this plan: CLAUDE.md ("Never delete files", backups, known limits); slice spec S15; plan D-52, D-74, D-77, D-78, D-79, D-83; `S0a_restructure_plan.md` and `S0a_restructure_report.md` (the 16 early backups, the symbol-level items left for S15); `S2_storage_report.md` (legacy runs read-only until S15); `S3_orchestrator_report.md` (follow-ups 6 and 7, the one-off label move); the plan copies `docs/plans/S5_plan.md` to `S8_plan.md` (not final), in particular S8 B-14 (cutover from the POC TA-1 path); `backup/orphans/2026-10-28/MANIFEST.json`, `2026-10-29/MANIFEST.json`; `scripts/restore_backup.py`; `pyproject.toml`; `apps/web/package.json`; `tests/unit/test_no_backup_imports.py`.

Owner constraints applied: legacy runs under `var/runs/` stay read-only until S15; never delete files; every move is a backup with a manifest; test gate is the fast tier per commit plus impacted suites, the full suite once per slice.

Legend: **[B]** batchable. **[STOP]** owner review. **A-n** assumption, repeated in section 9.

---

## 1. What is there today (verified by reading)

| Item | Finding |
| --- | --- |
| Backups | `backup/orphans/2026-10-28/` (S0a: 17 entries after S2 added the SQLite adapter and its test) and `2026-10-29/` (S3: one label file). Manifest `schema_version` "1.0"; per entry: `original_path`, `new_path`, `label`, `reason`, `evidence[]`, `sha256`, `git_blob`, `size`, `moved_in_commit`, `commit_before_move`, `restore_command` |
| Restore | `scripts/restore_backup.py <backup_dir> [--apply] [--only path]`: checks the git blob (line-ending independent), then `git mv` back. The spec names a different script, `scripts/restore_orphan.py <manifest-id>` (B-6) |
| Exclusions | Already in place since S0a: pytest `norecursedirs`, ruff `extend-exclude`, mypy `exclude`, coverage `omit` all list `backup`; `tests/unit/test_no_backup_imports.py` enforces "nothing imports backup"; `.gitignore` ignores `backup/*` except `backup/orphans/` |
| Tools | Not installed and not declared: `vulture`, `coverage` (configured in `pyproject.toml` but not a dependency), `knip`, `ts-prune`, `unimported`, `depcheck` (B-3) |
| Legacy runs | `var/runs/` holds 69 POC run folders, 782 tracked files, read-only since S2 (cannot be resumed, revised or compared; listed under "Other runs" in the UI). The protected-run test (D-79) checks that `var/runs/20261020-214203-7f7232` is tracked and unchanged. D-83 dropped the replay of 36 saved runs, so no test replays them |
| Known candidates | From S0a and S3: the USGS and Esri provider classes and their `get_map_provider` branches, `"usgs_naip"` and `"esri_demo"` in the run store, `TCP_USGS_NAIP_*` and `TCP_RUN_USGS_TESTS`; `test_diagnostics.py` (USGS-gated, the 11 skips in every suite run); the direct Anthropic provider (D-78: moves in S15) and its usage wrapper `_install_anthropic_usage` with its test and the `"anthropic"` pricing entry; `NewRunForm.tsx`, `startRun`, `NewRunPayload` (unused since S3) |
| Candidates after later slices (A-1 to A-4) | The POC TA-1 path after the S8 cutover (`layout/rule_engine.py`, `ta1_template`, TA-1 literals in `routing/eligibility.py`, `validation/validators.py`, `findings.py`); the POC rule pack `APPROVED_TWO_LANE_POC_RULE_PACK.json` after the switch-over (guarded by `guard_baseline.py`); the per-run sheet path if S12 retires it; `tests/support/golden_compare_lite.py` after S13; the legacy run readers if the runs move (B-2) |
| Never candidates | Entry points, migrations, fixtures (`tests/fixtures/`), golden files, the symbol library and `gen.py` (dev tool, S5), docs, `spikes/` (never imported), the backed-up POC, the rule-pack sources and figure renders |
| Report path | The spec says `docs/S15_orphan_report.md`; every other report sits in `docs/reports/` (B-7) |

## 2. Scope and acceptance criteria

### In scope

1. **Candidate finding** with every method in the spec: static reachability (Python AST import graph from every entry point; TypeScript tools for `apps/web`), dead-code scan (`vulture` at 80 % or more; unused TypeScript exports), runtime evidence (coverage of the full suite plus one replayed run per real KML), string references (repo, configs, `pyproject` scripts, CI, HTML, JSON), git history (last commit date and author).
2. **Classification** per item: `CONFIRMED_ORPHAN` (every method agrees), `SUSPECT` (listed only), `KEEP` (allowlist).
3. **A report and a stop.** Nothing moves before the owner approves the list, item by item.
4. **Moves**: whole files by `git mv` into `backup/orphans/<YYYY-MM-DD>/<original path>`; symbols cut into `backup/orphans/<date>/snippets/<module_path>__<symbol>.py` (or `.ts`) with a header; tests that only test moved code move with it.
5. **Manifest** per backup date, extended with the spec's fields (B-5).
6. **Restore** of any item with a hash check (B-6).
7. **The legacy runs decision** (B-2) and its execution.
8. **Unused dependencies**: listed; a `pyproject.toml` or `package.json` edit only with approval.

### Out of scope

Deleting anything; renaming the POC output codes (`UNSUPPORTED_POC`, `SELF_CONFIRMED_POC`, "TCP POC Pipeline"), which the slices doc plans as its own commit with a replay diff (B-9); behaviour changes.

### Acceptance criteria (spec)

| # | Criterion | How it is checked |
| --- | --- | --- |
| 1 | All suites green after the move | Full suite once; fast tier per commit |
| 2 | One replayed full-pipeline run of each real KML gives the same request fingerprints and plan outputs as before the move | Before and after replay of the recorded KMLs (run 2; run 1 uses the offline scenarios and the seeded fixtures, A-5) |
| 3 | The UI builds | `tsc --noEmit`, `npm run build`, Vitest |
| 4 | No file is deleted; every moved item is in the manifest; restoring a sample item reproduces the original bytes | A test compares `git ls-files` before and after: every vanished path is a manifest `original_path` whose `new_path` exists; restore round trip |
| 5 | `backup/` is not imported by anything | `test_no_backup_imports.py` (exists), extended to TypeScript |

## 3. Modules touched

New:

| File | Purpose |
| --- | --- |
| `scripts/orphan_scan.py` | Builds the candidate list: AST import graph from entry points, string search, git history, merges tool outputs, applies the allowlist, writes JSON |
| `scripts/orphan_report.py` | Writes the Markdown report from the scan JSON (like `rule_pack_report.py`) |
| `scripts/orphan_move.py` | Executes an approved list: `git mv`, symbol cuts, manifest entries |
| `config/orphan_allowlist.json` | The KEEP list with a reason per entry (`schema_version`) |
| `tests/unit/test_orphan_allowlist.py` | Every allowlisted path exists |
| `tests/unit/test_backup_manifest.py` | Every manifest entry's `new_path` exists and its hash matches; no tracked path vanished without an entry |
| `tests/unit/test_restore_roundtrip.py` | Restore a sample file and a sample snippet into a temporary worktree and compare bytes |
| `docs/reports/S15_orphan_report.md` (run 1), `S15b_orphan_report.md` (run 2) | The stop documents |

Changed: `scripts/restore_backup.py` (id-based restore and snippet restore, B-6), `tests/unit/test_no_backup_imports.py` (TypeScript side), `pyproject.toml` and `apps/web/package.json` only if B-3 adds tools, the live files from which approved symbols are cut, `CLAUDE.md` (the "Legacy runs" known limit, only if B-2 moves them).

## 4. Data shapes

```
Candidate {
  id, kind FILE|SYMBOL|DEPENDENCY|RUN_FOLDER, path, symbol|null, line_range|null,
  evidence { import_graph "UNREACHABLE"|"REACHABLE:<entry>", vulture {confidence}|null, ts_tool {...}|null,
             coverage "NEVER_EXECUTED"|"EXECUTED"|"NOT_MEASURED", string_refs [ {file, line} ], dynamic_hint [] ,
             last_commit {sha, date, author} },
  label CONFIRMED_ORPHAN|SUSPECT|KEEP, why, proposed_action MOVE|CUT|LIST_ONLY }

Manifest (schema_version "1.1"; 1.0 entries stay readable)
{ schema_version, slice "S15", date, note,
  entries [ { id, kind FILE|SYMBOL|RUN_FOLDER, original_path, new_path, symbol|null, original_line_range|null,
              label, reason, evidence [], sha256, git_blob, size, files [ {path, sha256, git_blob} ] (RUN_FOLDER only),
              moved_in_commit, commit_before_move, last_commit {date, author}, approved_by, restore_command } ] }

Snippet header (top of each snippets/<module_path>__<symbol>.py)
# original: src/tcp_planner/<path>.py  lines 138-197  commit <sha>  symbol <name>
# moved by S15 <date>; restore: python scripts/restore_backup.py backup/orphans/<date> --id <entry id>
```

## 5. How candidates are decided

1. **Entry points**: `tcp_planner.cli:main`, `python -m tcp_planner.web_api.server`, the run worker, the `project` command, every `scripts/*.py`, `tests/support/record.py`, every test file that tests live code, `apps/web/src/main.tsx`.
2. A file is `CONFIRMED_ORPHAN` only when: unreachable from every entry point, never executed in coverage, no string reference outside itself and its own tests, not on the allowlist, and (for Python) not listed in `__all__`, not exported from a package `__init__`, not reached through `getattr` or a registry.
3. Anything with one contrary signal is `SUSPECT`, listed with that signal, never moved.
4. A symbol inside a live file follows the same rule at symbol level; `vulture` below 80 % is never enough alone.
5. A test file is an orphan only when every test in it tests moved code; it moves to `backup/orphans/<date>/tests/`.

## 6. Commit sequence (per run)

Gate per commit: fast tier plus the impacted suites; the full suite, the UI build and the before-and-after replay once at the end.

| # | Commit | Marks | Why |
| --- | --- | --- | --- |
| 0 | Move `BASELINE_REF`, empty `APPROVED` | [B] with 1 | Housekeeping |
| 1 | Tools per B-3 (`pyproject.toml` `tools` extra, npm `devDependencies`) | **[STOP]** | A dependency change |
| 2 | `orphan_scan.py`, `orphan_report.py`, `config/orphan_allowlist.json`, allowlist test | [B] with 3 | |
| 3 | Run the scan with coverage and replays; write the report | **[STOP]**, owner approves item by item | The spec's stop |
| 4 | Restore script extension (id-based, snippet restore) and round-trip tests | [B] | Before anything moves, so every move is restorable |
| 5 | Move approved whole files; manifest | [B] with 6 | |
| 6 | Cut approved symbols; remove imports that became unused; move their tests; manifest | **[STOP]** | Edits live files; the owner reviews the diff |
| 7 | Legacy runs per B-2 (run folders, readers, D-79 test, CLAUDE.md known limit) | **[STOP]** | Changes a protected test and the UI history |
| 8 | Unused dependencies per B-8 | **[STOP]** if any are removed | `pyproject.toml` or `package.json` |
| 9 | Verification: full suite, UI build, before-and-after replay, a sample restore; `docs/reports/S15_orphan_report.md` final section | [B] | Acceptance |

## 7. Tests

| ID | Test | Covers |
| --- | --- | --- |
| T-1 | **Import graph**: no module under `src/`, `scripts/`, `tests/` or `apps/web/src` imports from `backup/` | Acceptance 5 (exists for Python; extend to TypeScript) |
| T-2 | **Restore round trip**: a moved file and a cut symbol restore to the original bytes in a temporary worktree | Acceptance 4 |
| T-3 | **No deletion**: every path in `git ls-files` at the base commit is either still tracked or a manifest `original_path` with an existing `new_path` | Acceptance 4 |
| T-4 | **Before and after replay**: the recorded KMLs (run 2) and the offline scenarios give the same request fingerprints and outputs | Acceptance 2 |
| T-5 | **Allowlist paths exist** | Spec |
| T-6 | **Manifest integrity**: every entry's sha256 and git blob match its file | |
| T-7 | **UI**: `tsc --noEmit`, `npm run build`, Vitest | Acceptance 3 |

## 8. Dependencies

| Depends on | For | State |
| --- | --- | --- |
| S3 (run 1) | The first sweep's baseline | Merged |
| S8 cutover (B-14 of the S8 plan) | The POC TA-1 path becomes a candidate | Planned (A-1) |
| The pack switch-over (S7 or S8) | The POC pack becomes a candidate | Planned (A-2) |
| S12 (per-run sheet) and S13 (`golden_compare_lite.py`) | More candidates | Planned (A-3, A-4) |
| Recordings of the three real KMLs | Acceptance 2 in run 2 | Owner, after S7 and S9 |
| S14 | Run 2 starts after it | Planned |
| S16 | Comes after S15 run 2 (B-10) | Planned |

## 9. What could go stale if S6 to S8 change (assumptions)

| Assumption | If it changes |
| --- | --- |
| A-1: S8 cuts over from the POC TA-1 path (S8 B-14 option a) | If S8 keeps both paths, the TA-1 code is SUSPECT, not orphan, and D-32 is breached |
| A-2: the pipeline stops reading the POC pack after S7 or S8 | If not, the POC pack and `guard_baseline.py` entries stay KEEP |
| A-3: S12 keeps or retires the per-run sheet (S12 B-16) | Whether `sheet_renderer.py` parts are candidates |
| A-4: S6 builds new call 1 beside the old one and switches in S7 (S6 Q2 option A) | The old call 1 prompt, schema and parser become candidates only after the switch |
| A-5: run 1 has no real-KML recording | Acceptance 2 in run 1 uses the offline scenarios and the seeded fixtures (Granite P30, Alton Bradford, Exeter) |
| A-6: the S6 data-source adapters stay behind one registry | String references and `getattr` keep them SUSPECT, which is correct |

## 10. Where the spec and the repo differ

1. Spec report path `docs/S15_orphan_report.md`; reports live in `docs/reports/` (B-7).
2. Spec restore script `scripts/restore_orphan.py <manifest-id>`; `scripts/restore_backup.py` exists and restores by path (B-6).
3. The spec allows moves "only in S15"; S0a and S3 made approved early exceptions. Their manifests stay as they are (1.0).
4. The spec's "TypeScript in `tcp_ui`" became `apps/web` in S0a (already noted in the S0a report).
5. The spec says "one replayed full-pipeline run of each real KML"; no real KML is recorded yet, so run 1 cannot meet it literally (A-5).
6. Moving the legacy runs breaks the D-79 protected-run test unless the test is updated with approval.
7. S16 runs after S15 run 2, so the "final" sweep is not last (B-10).

## 11. OPEN QUESTIONS

### Part A: client inputs and SME questions

None that block. One question for the owner's team, not the client:

**A-1. Does anyone still open the POC runs** under "Other runs" (for history, demos or comparison)?
- Effects: decides B-2.
- Blocks: commit 7.

### Part B: owner decisions

**B-1. Two runs or one.** Run 1 was due after S3.
- Options: (a) run 1 now (known S0a items, `NewRunForm.tsx`), run 2 after S14; (b) one run after S14; (c) run 1 after the S8 cutover, when the POC TA-1 path is also a candidate, and run 2 after S14.
- Effects: (a) cleans early but needs the scan tooling twice. (c) catches the largest candidate group in the first run.
- Suggestion: (c).
- Blocks: when run 1 starts.

**B-2. The legacy runs under `var/runs/`** (69 folders, 782 tracked files).
- Options: (a) keep in place, read-only, forever; (b) move all 69 to `backup/orphans/<date>/var/runs/` with one manifest entry per run folder, re-point the D-79 test to the backup path, and move the legacy readers as code orphans; (c) move all except the protected run; (d) move them and keep a small JSON index of what each run was, so the UI can still list them as "archived".
- Effects: (b) and (d) remove them from the UI history; the POC is not a regression oracle (CLAUDE.md). (a) keeps the read-only code path alive. (c) keeps one run only to satisfy a test.
- Suggestion: (d) if A-1 says nobody opens them, else (a).
- Blocks: commit 7.

**B-3. Tools.**
- Options: (a) add `vulture` and `coverage` to the `tools` extra and `knip` to `apps/web` `devDependencies`; (b) run them once from a throwaway environment (`pipx`, `npx`) without changing project files, and commit only their outputs in the report; (c) AST graph, string search and git history only.
- Effects: (c) does not meet the spec's method list. (a) changes dependency files; (b) needs network access at run time on the owner's machine.
- Suggestion: (b) for run 1, (a) if run 2 confirms the tools are worth keeping.
- Blocks: commit 1.

**B-4. Approval granularity.**
- Options: (a) item by item in the report (a checkbox column the owner fills); (b) by group (for example "all USGS items"); (c) all CONFIRMED_ORPHAN items at once.
- Suggestion: (a) for symbols and runs, (b) for whole-file groups.
- Blocks: commit 5.

**B-5. Manifest version.**
- Options: (a) new entries use schema 1.1 (adds `id`, `kind`, `symbol`, `original_line_range`, `last_commit`, `approved_by`, `files[]`); old 1.0 manifests stay unchanged and readable; (b) migrate the two old manifests to 1.1.
- Effects: (b) edits committed backup records.
- Suggestion: (a).
- Blocks: commit 4.

**B-6. Restore script.**
- Options: (a) extend `scripts/restore_backup.py` with `--id` and snippet restore; (b) add `scripts/restore_orphan.py` as the spec names it, wrapping the existing script.
- Suggestion: (a), and note the spec's name as superseded.
- Blocks: commit 4.

**B-7. Report path.**
- Options: (a) `docs/reports/S15_orphan_report.md`; (b) `docs/S15_orphan_report.md` as the spec says.
- Suggestion: (a).
- Blocks: no.

**B-8. Unused dependencies.** `anthropic` stays a dependency while the direct provider exists; after it moves, it may be unused.
- Options: (a) list only; (b) remove from `pyproject.toml` in the same slice, after approval.
- Suggestion: (b) for `anthropic` once the provider and its wrapper are moved and no import remains; (a) for everything else.
- Blocks: commit 8.

**B-9. POC naming** (`UNSUPPORTED_POC`, `SELF_CONFIRMED_POC`, "TCP POC Pipeline").
- Options: (a) its own commit outside S15, as the slices doc says; (b) fold it into S15 run 2.
- Effects: renaming changes stored expected outputs (D-83) and is a behaviour change, not an orphan move.
- Suggestion: (a).
- Blocks: no.

**B-10. A sweep after S16.** S16 is the last slice and comes after S15 run 2.
- Options: (a) a short third run after S16 with the same tooling; (b) S16 promises no orphans of its own; (c) move S15 run 2 after S16.
- Suggestion: (c).
- Blocks: no.

**B-11. Snippet restore when the live file has changed since the cut.**
- Options: (a) restore re-inserts at the recorded anchor (the symbol before it) and refuses if the anchor is gone; (b) restore writes the snippet back as a separate module next to the original and leaves wiring to a person; (c) document a manual restore only.
- Suggestion: (a) with (b) as the fallback.
- Blocks: commit 4.

### Summary table

| # | Question | Group | Blocks S15? | Suggestion |
| --- | --- | --- | --- | --- |
| A-1 | Does anyone open the POC runs | Owner's team | Commit 7 | Ask |
| B-1 | Two runs or one | Decision | Start of run 1 | Run 1 after the S8 cutover, run 2 after S14 |
| B-2 | Legacy runs | Decision | Commit 7 | Move with an archive index if unused |
| B-3 | Tools | Decision | Commit 1 | Throwaway environment first |
| B-4 | Approval granularity | Decision | Commit 5 | Items for symbols and runs, groups for files |
| B-5 | Manifest version | Decision | Commit 4 | 1.1 for new entries only |
| B-6 | Restore script | Decision | Commit 4 | Extend the existing script |
| B-7 | Report path | Decision | No | `docs/reports/` |
| B-8 | Unused dependencies | Decision | Commit 8 | Remove `anthropic` after its code moves |
| B-9 | POC naming | Decision | No | Separate commit |
| B-10 | Sweep after S16 | Decision | No | Run 2 after S16 |
| B-11 | Snippet restore | Decision | Commit 4 | Anchor re-insert, module fallback |
