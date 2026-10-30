# S3 report: project orchestrator and per-zone runs

Branch `tcp-mvp/s03-orchestrator`, from `tcp-mvp/s02-storage` (b2c95fe). One flow for every input: a **project** (one KML, one
point or one offline scenario) holds the work locations; each Point becomes a **zone** and each zone runs as its own **child
run**; the project has a status. The SME types the four mandatory start fields (D-59) per project and per point; Run stays
closed until all are typed. Nothing fills, derives or defaults them.

## Commits

| Commit | Content |
| --- | --- |
| `9d43f8f` S3 0 | guard baseline moved to b2c95fe, `APPROVED` emptied (guard tests: 26 passed) |
| `db93b61` S3 1 | project and zone model (`orchestration/projects.py`), start-field checks, zone stub (one zone per Point), status roll-up, `project.*` config, fail-fast test that `BASELINE_REF` equals the previous slice's tip |
| `f1528c5` S3 1b | config `project` section trimmed to the two approved keys; `APPROVED` hash updated |
| `55748f1` S3 2 | zone engine input (`--zone`), start fields only from the zone, single-location `--kml` points to the `project` command |
| `cc268af` S3 3 | orchestrator (`orchestration/project_runner.py`): idempotent, zone cap, parallel limit, `project` CLI command |
| `d116601` S3 3b | SME lineage key switch (D-82); assistant suites and labels on the project path |
| `adfd4cd` S3 4 | project API, output index in the result record, REVIEW_REQUIRED shown as such with a service badge, `kml_key` |
| `64f68dd` S3 4b | owner decisions: REVIEW_REQUIRED zones count toward the project status, only projects start runs, `approved_by` unverified, sheet files in the output index |
| `5d843e6` S3 5 | UI: project view, typed start fields, Select TA, labels, rejection reasons, service badge, "Input key", history by project, Vitest, web rebuild |
| `447e461` S3 6 | label re-key and the one-off backup move, DXF path scan, start values kept in the run record |
| `dbf66e7` docs | future-scope entry "Police detail instead of flagger" (docs only, owner approved) |

## Acceptance criteria (slice S3)

| Criterion | Result | Evidence |
| --- | --- | --- |
| A single-point KML runs as a one-zone project end to end on replayed fixtures | Met | `test_zone_input.py::test_one_zone_replays_the_recorded_single_point` (recorded `granite_p30`: same request fingerprints as the plain replay, same decision); `test_project_api.py::test_offline_project_end_to_end_with_the_output_index` (real runner) |
| A multi-zone project runs every zone; one failed zone gives PARTIAL and keeps the other drafts | Met | `test_project_runner.py::test_one_failed_zone_gives_partial_and_keeps_the_other_drafts`, `test_three_point_kml_runs_through_the_real_worker` |
| Retrying the orchestrator does not duplicate runs | Met | retry, crash after reserving ids, crash before starting a run, two concurrent Run calls, unchanged inputs: `test_running_twice_creates_no_second_run` and the three tests after it |
| Above the max-zones cap nothing runs until approval | Met | `test_cap_holds_before_any_run_or_call` (no run folder, no launch), `test_cap_over_http` |
| Run cannot start while any mandatory start field is empty | Met | API: 409 `START_FIELDS_MISSING` (`test_run_is_refused_until_every_field_is_typed`); UI: Run disabled (Vitest `Run turns on only when all four are typed`) |
| Three-point KML gives three runs | Met | `test_three_points_three_runs_linked_to_the_project`, and with the real worker |
| Never more than 3 runs active (5 zones, cap 3) | Met | `test_five_zones_never_more_than_three_runs_active` (the other two queue and start as running ones finish); inside a zone the order stays imagery, OSM, AI (`test_zone_order_is_imagery_then_osm_then_ai`) |
| Moved runs folder | Met | `test_moved_runs_folder_keeps_the_project_and_its_runs`: the project opens, a retry creates and starts nothing, a zone run resumes with its project link, the raw-path scan is clean |

## What was built

- **Project record** (`ProjectStore`, `_shared/projects/<id>.state.json`; event stream `projects/<id>`): name, source, every
  `WorkLocation` (rejected ones kept with reasons), `inputs` (every upload: ref and time), `labels` (display label of each
  location with the upload it follows), `start_fields` (project row and per-location overrides, all `null` until typed),
  `ta_hypothesis` (project and per location, default AUTO), `advanced`, `zones`, `run_request`, `cap_approval`, `status`.
- **Project id** = hash of the usable geometry (Q2-B); an offline project also hashes its scenario name, because all offline
  scenarios use one point. The same geometry reopens the same project.
- **Re-upload** (decision 3): the new file is kept as another write-once input (`projects/<id>/input/<sha12>-<name>`), the
  project name and the display labels follow the latest upload, and each label records `input_sha256` and `input_key` of the
  upload it follows. Labels are for the list and the sheet only; nothing is decided from them (D-72).
- **Zones**: one per usable location (grouping stub; grouping is S9). A line or polygon zone is `NOT_SUPPORTED_UNTIL_S14` and
  never runs; a Point+Line KML runs the Point. A zone's version goes up only when its inputs change after it already has a run.
- **Run**: records the zone set and reserves one run id per zone inside one compare-and-set update; builds each run (write-once
  `zone_input.json`, then the request record as the commit point); starts at most `project.max_parallel_zone_runs` (3) at once.
  The request record keeps the exact start values used (`request.operator`, `zone_input.json` and
  `project_geometry.json` agree); a later change makes new runs and leaves the old records byte for byte as they were.
- **Engine input**: `--zone <key>` replaces `--kml/--lat/--lon`; the zone's start fields are the only operator source
  (`--road-type`, `--speed`, `--requires-lane-closure` are refused with it). The zone block (id, version, Select TA, sheet label,
  start fields) is in `project_geometry` and so in the site-model hash; `project_id` and `lineage_key` are not (Q8-A).
  `traffic_volume` and the Select TA hypothesis are recorded and carried; nothing uses them before S7.
- **Lineage key** (D-82): `lineage_key(project_id, zone geometry hash)`, read from the project link in a run's request record.
  A run outside a project has none; the assistant answers `NO_PROJECT_LINEAGE` (409 `RUN_NOT_ELIGIBLE`). Labels are keyed by it.
- **API**: `GET/POST /api/projects`, `GET /api/projects/<id>`, `POST .../inputs`, `.../run`, `.../approve-cap`.
  `POST /api/runs` answers 400 for every input: only a project starts runs (internal run creation stays for resume, comparison
  and tests).
- **CLI**: `python -m tcp_planner.cli project --kml FILE --road-type ... --speed ... --traffic-volume ... --lane-closure ...`
  (typed, never filled; a missing field stops with `START_FIELDS_MISSING`).
- **UI**: new-project form (no start fields on it), project view (start fields empty with no default, Apply to all points,
  per-point cells, Select TA, Run disabled until all four are typed for every runnable location, cap banner, zone list), run
  history grouped by project, REVIEW_REQUIRED shown as such with a "service error" badge, "Input key", rejection reasons for a
  KML with no usable location. 26 new Vitest tests; the web app was rebuilt.

## Project status: the Q6 definition changed (owner decision after commit 4)

Each finished zone is one of **DRAFT** (a draft exists and it is SUPPORTED_AUTO), **REVIEW** (it finished REVIEW_REQUIRED, or
has a draft that is not SUPPORTED_AUTO) or **NONE** (the run errored, was stopped or is UNSUPPORTED_POC, or the zone never runs:
a line or polygon). The per-zone `draft_available` flag stays separate from the decision.

| Status | Meaning |
| --- | --- |
| `INPUTS_REQUIRED` | a location that would run lacks a start field (new, not in the plan) |
| `READY` | all fields typed, nothing requested for the current inputs (new, not in the plan) |
| `ZONE_CAP_APPROVAL_REQUIRED` | Run asked, more zones than `max_zones`, not approved: nothing runs |
| `RUNNING` | Run asked and a zone is not finished |
| `ALL_DRAFTED` | every zone is DRAFT |
| `REVIEW_REQUIRED` | no zone is NONE and at least one is REVIEW (**changed**: the earlier definition needed a draft) |
| `PARTIAL` | some zones are DRAFT or REVIEW and some are NONE (so one REVIEW zone plus one errored zone is PARTIAL, owner decision) |
| `FAILED` | every zone is NONE: all errored or never ran (**changed**: was "no zone has a draft") |

Today the pipeline writes `plan.json` only for SUPPORTED_AUTO, so a REVIEW_REQUIRED zone has no draft yet; its zone row shows
"draft: none". Drafts for review arrive with S7/S8 and D-65.

## Approved changes to protected files and rules

- `config/pipeline_config.json`: exactly this, nothing else (`APPROVED` in `tests/support/guard_baseline.py`, blob
  `852c9dcaa2503b938cbf98a251b4daddef178fb4`):

  ```diff
     "duplicate_distance_m": 1.0
   },
  +  "project": {
  +    "max_zones": 3,
  +    "max_parallel_zone_runs": 3
  +  },
     "fusion": {
  ```

  `tests/support/guard_baseline.py`: `BASELINE_REF` moved to `b2c95fe56fcb4ed9e43804edae57a5c0bd1013f6`; `APPROVED` holds
  only the entry above.
- One-off exception to "moves only in S15" (Q10b): the old label file moved to `backup/orphans/2026-10-29/` with a manifest
  entry. Before and after JSON: `docs/reports/S3_label_rekey.md`.
- No file under `tests/fixtures/expected/` changed (`git diff b2c95fe..HEAD -- tests/fixtures/expected` is empty);
  `test_global_identity` passes unchanged. No file was deleted.

## Carried from S2

| Item | Outcome |
| --- | --- |
| Pre-S2 assistant conversations stay read-only | Unchanged: they can be read, not continued (`LegacyStreamReadOnly`) |
| Legacy runs under `var/runs/` stay read-only until S15 | Unchanged; they sit under "Other runs" in the history |
| Rename `kml_saved_path` | Done: `kml_key` (a run-relative key), shown as "Input key"; runs made in S2 are still read through the old name (test); the web app was rebuilt |
| SHA-256 and size of every output file in the run result | Done: `result.output_index` = `[{name, uri, sha256, size, media_type}]`, rendered files included; the run state shows each file's sha256. Tests compare it with the files on disk, with sheet rendering on (`tcp_sheet.png`, `tcp_sheet.pdf`) |
| One-time check: can renderer outputs embed a local path? | **PNG, JPEG, PDF (sheet and debug) and JSON: no.** Scanned an offline run's outputs, including the decompressed PDF streams, for the user name, folder names, drive letters and temp folder: only random bytes and the Matplotlib URL matched. The DXF names its image by bare file name (`dwt_renderer.py`, `image_def filename`). **DXF and DWG are unverified**: this machine has no ODA File Converter, so none was produced. A test scans a DXF header and a DWG for local paths and is skipped without the converter (`test_dxf_local_paths.py`); the owner runs one real render later |
| Re-key `var/labels/771bbc3d0913044a.json` (D-82) | Done by hand: new key `04bf2dc90e9c3cac` (demo KML point equals the label point; project `PRJ-f46419bbc77c92b5`, zone `ZONE-c0690d642bc7`); fields and status unchanged; see `S3_label_rekey.md` |
| UI showed REVIEW_REQUIRED (exit 3) as "ERROR" | Fixed (Q12-B): the decision shown is always the pipeline's; service/API failure codes are a separate `service_error` badge. Seven tests that pinned the old display were updated |
| What a project contains | Decided (Q1-A), see "What was built" |
| Stored expected outputs unchanged | Yes |

## Named follow-ups

1. **D-59 breach 1, OSM speed fallback** (`src/tcp_planner/site_model/fusion.py:232-237`): with no operator speed the speed is
   taken from OSM `maxspeed`. A zone run always carries a typed speed, so it never fires there, but the code path still
   exists. Fix in S7: speed only from the SME's value.
2. **D-59 breach 2, encroachment overrides the SME's lane closure** (`fusion.py:395-399`): a derived encroachment sets
   `requires_lane_closure` to true even when the SME typed No. D-59 says a computed check raises a conflict and never changes the
   value. Fix in S10 (conflict machinery): raise the conflict, keep the SME's value.
3. **`approved_by` of the zone-cap approval is typed text** (or "UI click"), recorded with `verified: false`. S10's approver role
   replaces it.
4. `traffic_volume` and the Select TA hypothesis are carried but unused until the router (S7), where Select TA is checked
   against the facts.
5. Zone splitting over 150 m, grouping and duplicate merging are S9. Lines and polygons run from S14.
6. `NewRunForm.tsx` and the old `startRun` / `NewRunPayload` stay unused until the S15 orphan sweep.
7. A REVIEW_REQUIRED zone has no draft (see above); S7/S8.

## Known limits

- **One process drives a project.** The orchestrator's lock is per process (the server's threads). Two processes (the server and
  the `project` command) driving the same project at the same time are not supported. Written in `CLAUDE.md`.
- **The live UI path is untried.** Every run so far used offline scenarios, recorded fixtures or fakes; the Azure Maps and AI
  path through the project UI has not been run. That waits for the real-KML recording after S6 (`TCP_LIVE=1`, run by the owner).
- **Rate limits.** N zones still mean up to `max_parallel_zone_runs` simultaneous Foundry, Azure Maps and Overpass calls; there
  is no 429 backoff (S0 report, item 14).
- **Polling cost.** `list_runs` still builds the state of every run on disk on each poll (S0 report, item 11).
- **Label data is untracked.** `var/` is ignored, so the re-keyed label and the old file's history live on this machine; the
  old file is committed in the backup folder.
- **DXF/DWG local paths** are unchecked until a real render (see above).

## Contradictions with the plan and deviations

1. The plan's statuses had no state before Run; `INPUTS_REQUIRED` and `READY` were added (owner accepted).
2. The Q6 definitions of REVIEW_REQUIRED, PARTIAL and FAILED changed (owner decision).
3. The plan's data model lists a `Sheet` entity and a `ProjectPlan` index; neither is built (sheets are S12; per-zone plans are
   in the run folders). `WorkZone.grouping.method` is `ONE_PER_LOCATION` (stub) instead of KML_EXPLICIT/USER/AUTO_RULE/SME.
4. D-82 says "`site_id_for` and the label files switch to the composite key". `site_id_for` now takes a run's request record
   (the lineage key is not derivable from geometry alone) and `save_draft` takes the key as its first argument.
5. `POST /api/runs` is closed (the plan did not say so); owner decision after commit 4.
6. The plain `--kml` path now counts duplicates before the one-Point check (an exact duplicate no longer counts as a second
   Point); with more than one usable Point it points to the `project` command.
7. The zone-cap approval records the zone count it covers; an approval does not cover a bigger set.

## Files changed

55 files, about 4,500 lines added (`git diff --shortstat b2c95fe..HEAD`). Source: `orchestration/projects.py`,
`project_runner.py`, `project_cli.py` (new); `pipeline.py`, `run_worker.py`, `run_relations.py`; `intake/kml_reader.py`,
`lineage.py`; `storage/run_store.py`; `web_api/server.py`, `project_routes.py` (new); `evaluation/ground_truth_labels.py`,
`comparison_scoring.py`; `review/assistant/services/run_context.py`; `cli.py`; `config/pipeline_config.json`. UI: `App.tsx`,
`api.ts`, `types.ts`, `format.ts`, `RunHistory.tsx`, `RunView.tsx`, `Summary.tsx`, `styles.css`, and new `NewProjectForm.tsx`,
`ProjectView.tsx`, `ServiceErrorBadge.tsx`. Docs: this report, `S3_label_rekey.md`, the plan and slices (future scope),
`CLAUDE.md` (known limits). Backup: `backup/orphans/2026-10-29/`.

## Tests added

| File | Tests | Covers |
| --- | --- | --- |
| `tests/unit/test_projects.py` | 28 | project id, start fields (never filled, validated), zones, versions, cap, every status |
| `tests/unit/test_guard_baseline_ref.py` | 1 | `BASELINE_REF` equals the previous slice's tip |
| `tests/unit/test_label_rekey.py` | 3 | re-keyed lineage, manifest entry and hashes, before/after record |
| `tests/integration/pipeline/test_zone_input.py` | 13 | zone engine input, no other start-field source, same site model across uploads, `--kml` message, recorded-fixture replay |
| `tests/integration/pipeline/test_project_runner.py` | 27 | orchestrator, retries, cap, parallel limit, reopen and re-upload, moved folder, exact start values, `project` command |
| `tests/integration/pipeline/test_dxf_local_paths.py` | 2 | local-path scan (always), DXF/DWG scan (skipped without the converter) |
| `tests/integration/review_assistant/test_lineage_key.py` | 4 | composite key, separate projects, `NO_PROJECT_LINEAGE`, resumed zone run |
| `tests/integration/web_api/test_project_api.py` | 24 | API, no-usable-location, typed fields, cap, real runner, output index (with sheet files), status badge, `kml_key` |
| `apps/web/src/components/__tests__/project.test.tsx` | 26 | start-field helpers, new-project form, project view, cap, zones, history, badge, summary |

Tests changed: the seven that pinned the "ERROR" display, the `kml_saved_path` assertions, `test_ui_adapter` (single runs start
directly; the invalid-KML test uses the project route), label tests (new `save_draft` signature), the assistant run library
(one-zone offline projects), `test_multiple_kml_points`.

## Test results

Full Python suite, once, at `dbf66e7` (before the report commit): **570 passed, 12 skipped in 8 min 53 s** (582 tests).
The 12 skips: 11 USGS NAIP diagnostics (off unless `TCP_RUN_USGS_TESTS=1`, as before) and the DXF/DWG local-path test (no ODA File
Converter on this machine). No live call was made. Vitest: **46 passed** (20 existing assistant tests, 26 new); `tsc --noEmit`
and `npm run build` are clean. Replay is deterministic: `test_global_identity` (13 offline scenarios and the KML case) and the
fixture-replay tests pass unchanged, and no file under `tests/fixtures/expected/` changed.

How the suite ran during the slice: the affected suites (unit, pipeline, web API, and the assistant suites when run state, labels
or the lineage key changed) after each commit, the full suite once at the end. Failures on the way, each fixed in one step:
`test_status_cap` (the cap approval now names a zone count), `test_no_persisted_json_holds_a_raw_path` (a missed `save_draft`
caller), 13 web API tests that pinned the old "ERROR" display, and the guard test after the `project` config section (an
approved `APPROVED` entry). One loose end for the owner: the full suite takes about 9 minutes here, the assistant suites about
half of it; a `slow` marker could split them out (proposed, not done).

## Open questions

1. When does a REVIEW_REQUIRED zone get a draft for the SME (D-65 says every plan waits for a click, the pipeline drafts only
   SUPPORTED_AUTO)? Expected in S7/S8; until then the project status REVIEW_REQUIRED reflects the zone decision, not a draft.
2. Should a project be deletable or archivable? There is no such action; projects only accumulate.
3. Is `max_parallel_zone_runs = 3` right once rate limits are measured (no 429 backoff exists)?
