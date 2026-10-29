# S2 storage report

Branch `tcp-mvp/s02-storage`. Files only (D-84): artifacts as files, state as one `.state.json` file per record and one
`.events.jsonl` file per stream, each run's state inside its own run folder. No SQLite anywhere in `src/` or `tests/`.

## Commit numbering

| Part | Content |
| --- | --- |
| 1 to 3 | interfaces and key rules, local filesystem ArtifactStore, in-memory fakes, contract suite, migrations, sanitized upload keys, FileStateStore (files only), `stores.py`, SQLite adapter moved to `backup/orphans/2026-10-28/` |
| 4a | evidence store on the ArtifactStore; manifest as a state record in the run folder; evidence readers return refs |
| 5a | pipeline `Run` on the ArtifactStore; `--out` rule |
| 5b | Recorder and `ui/*` as relative-path state records; `append_event` tail read and durability; commit 4 leftovers (run_store routing, D-77 relative paths) |
| 5c | worker and launch by run id; read-only legacy reader |

The old "commit 4" work (SQLite based) is kept on the local branch `s2-commit4-wip` (not pushed). A diff of its 12 files
against HEAD showed only the expected differences: `stores.py`, `settings.py` and the `MANIFEST_KEY` and docstring edits in
`evidence_store.py`.

## What changed in 5a to 5c

- **5a.** `Run` writes JSON and the report through `LocalFsArtifactStore.put` (write-once, SHA-256 refs in `run.refs`).
  Files that renderers write (JPEG, PNG, PDF, DXF, DWG) are registered with `run.adopt()` right after rendering. A non-empty
  `--out` is an error (`OUT_DIR_NOT_EMPTY`, exit 2) unless `--overwrite`; the message prints the flag to add.
  `--overwrite` is the only place the old stale-file cleanup survives. `MANIFEST.json` note and `.gitignore` updated.
- **5b.** New `storage/run_records.py`: the 13 `ui/*` records (`request`, `resume`, `comparison`, `prep`, `report`,
  `result`, `process`, `usage`, `diagnostics`, `calls`, `deps`, `rule_pack`, `tls`) and the event stream
  (`ui/events.events.jsonl`) as state records, with a legacy fallback for reading. `argv`, `kml_saved_path` and the SME
  revision hold run-relative keys; the worker resolves them under the runs folder (`resolve_argv`). `result` holds
  `out_key` instead of the absolute `out_dir`. KML uploads and the SME revision go through the ArtifactStore. The Recorder
  prints each distinct write or event failure once to stdout (= `stdout.log`) and goes on; the final `process` record is
  retried three times and then raises. The server's reaper updates `process` with compare-and-set and never overwrites the
  worker's own record.
- **5c.** The worker and `server.launch` take a run id, not a folder. Legacy runs (`ui/*.json`, no state files) can be
  listed and opened; every write path raises `LegacyRunReadOnly`; the HTTP API answers 409 `LEGACY_RUN_READ_ONLY` with
  "This run was made before the storage change. It can be viewed but not resumed, revised or compared. Start a new run."
  The assistant's regenerate answers the same code. The worker refuses a legacy run.

## Event stream: decisions and measurements

- Only state-changing events are fsynced (`process_started`, `run_result`, `process_finished`). The caller passes
  `durable=True`; the default is flushed only. The state records themselves are always fsynced.
- `append_event` reads the sequence number from the file tail (8 KB blocks), not by parsing the whole file. A torn tail
  is still refused. Only the last line is validated on append; `events()` still parses the whole file.
- The lock file is no longer fsynced (it only has to be visible to other processes). This was not in the plan; it is the
  largest part of the per-call saving.

| Measurement | Old code | New code |
| --- | --- | --- |
| 2,000 `append_event` calls, empty stream, all fsynced (old) / not durable (new) | 35.7 s (17.8 ms each) | 5.7 s (2.8 ms each) |
| last 500 / first 500 of those calls | 1.49x | 1.65x |
| 200 appends to a stream pre-seeded with 20,000 events | 14.2 s | 0.42 s |
| 200 appends to an empty stream | 2.5 s | 0.44 s |

At 2,000 events the old code's parse cost is hidden behind fsync and locking, so the "last 500 under 3x first 500" check
(kept as asked) would not have caught it. The pre-seeded 20,000-event check is the one that fails on the old code.

## Files changed (341539e to HEAD)

Source: `orchestration/pipeline.py`, `run_relations.py`, `run_worker.py`; `storage/file_state.py`, `interfaces.py`,
`memory.py`, `run_records.py` (new), `run_store.py`; `web_api/server.py`; `review/assistant/services/pipeline_controller.py`,
`run_context.py`. Other: `.gitignore`, `CLAUDE.md` (known limits), `backup/orphans/2026-10-28/MANIFEST.json` (note).

## Tests added

| File | Covers |
| --- | --- |
| `tests/integration/pipeline/test_out_dir_rule.py` (6) | `--out` rule, `--overwrite`, store refs and SHA-256, write-once |
| `tests/unit/test_file_state_events_tail.py` (5) | tail sequence, torn tail, durable flag, 2,000-call and 20,000-event benchmark |
| `tests/unit/test_recorder.py` (7) | state records written, failure line once per distinct error, final record retry and raise, durable flag, `out_key` |
| `tests/integration/web_api/test_run_records.py` (2) | no absolute path in records of a new run and a resumed run; moved-runs-folder resume (D-77) |
| `tests/integration/web_api/test_legacy_runs.py` (6) | protected run: list and open leave every byte and every file as it was; resume, comparison and every write path refused; worker refuses |

Tests changed to read through `run_records` instead of `ui/*.json`: `test_phase4_versions.py`, `test_evidence_resume.py`,
`test_ui_adapter.py`, `tests/support/record.py` (reads state records and old files). `test_foundry_provider.py` now runs
into an empty sub-folder (its fixture put `profiles.json` in the `--out` folder). Launcher fakes and worker calls pass a run id.

## Effect on stored outputs

`test_global_identity` (13 offline scenarios and the KML case) passes unchanged, and no file under
`tests/fixtures/expected/` changed. A scan of a fresh offline run folder (records, evidence and outputs) finds no raw path.

## Test results

Full suite, once at the end of 5c (commit b5e83ed): **428 passed, 11 skipped** (402 passed, 11 skipped before this work; 26 new tests). The 11 skips are the existing live-call tests that need `TCP_LIVE=1`. Replay is deterministic: `test_global_identity` and the fixture-replay tests pass unchanged.

## Contradictions with the plan and deviations

1. **Line endings.** The first version of `Run.write` produced LF; the stored expected outputs are CRLF (the old text-mode
   write on Windows). `Run` now writes the OS line ending, so outputs stay byte-identical. Known limit, not a fix.
2. **13 records, not 12.** `tls` is the thirteenth `ui/*` record.
3. **`kml_saved_path` keeps its name** but now holds a run-relative key (`<run_id>/input/<slug>.kml`). The UI shows it as
   "Saved at". Renaming it needs a web rebuild.
4. **Renderer output is sealed after the fact.** PIL, PDF and DWT renderers write straight to the output folder; `adopt()`
   then registers the same bytes with the store. Write-once holds from that point, not during rendering.
5. **List records are wrapped.** `usage`, `diagnostics` and `calls` are lists; a state value must be an object, so they are
   stored as `{"items": [...]}` and `run_records.read` unwraps them. This surfaced only because failures are now reported.
6. **Lock file fsync removed** (see above).
7. **New events** `process_started`, `run_result` and `process_finished` appear in the event stream; the UI ignores them.
8. **`run_pipeline` raises** `TcpError("OUT_DIR_NOT_EMPTY")` for a non-empty folder when called directly (new behavior).
9. **Run folders** still pre-create empty `input/`, `output/` and `ui/` folders.

## Open questions

1. Other `except Exception: pass` blocks remain in the worker's observation wrappers (rule pack, TLS, provider
   diagnostics, usage). Decision 4 covered `Recorder.write` and `Recorder.event`, which now report. Should those wrappers
   also report once per error?
2. Normalize pipeline output to LF? It would change every stored expected output once and make hashes the same on every
   platform.
3. Rename `kml_saved_path` to a key name and rebuild the web app?
4. When may the local branch `s2-commit4-wip` be deleted?
5. The 782 tracked legacy files under `var/runs/` stay read-only; S15 decides whether they move to `backup/orphans/`.
