# CLAUDE.md — TCP MVP

Read this file at the start of every session. It applies to every slice.

## What this project is

The tool takes a KML of work locations and produces draft traffic control plans (TCPs): PDF sheets with imagery, signs, tapers, buffers and dimensions, plus a full audit trail. An SME reviews and approves every plan.

- **MVP scope:** TA-1, TA-6, TA-10 and TA-33 only. Anything else returns `NO_TA_MATCH`.
- **Branches:** base `tcp-mvp/base`; one branch per slice, `tcp-mvp/sNN-short-name`. The old POC is backed up and is not a regression oracle. There is no separate legacy TA-1 path.
- **Setup, once per environment:** `pip install -e . --no-build-isolation` inside `.venv`.

## Documents (source of truth)

| File | Use |
| --- | --- |
| `docs/architecture/TCP_MVP_Architecture_Plan_v4.md` | The plan, decisions (D-xx) and ADRs |
| `docs/slices/TCP_MVP_Development_Slices.md` | Slice specs S0 to S15: scope, acceptance criteria, tests |
| `docs/slices/schema_spike_prompt.md` | AI output-format spike, run in S0 |
| `docs/reports/` | Slice reports (S0a done; S0 next) |
| `docs/sources/` | MUTCD 11th Edition, Chapter 6, December 2023 revision |
| `docs/references/` | The three reference TMP PDFs; KMLs in `docs/references/kml/` |
| `tests/golden/` | Golden set v0.1 extracted from the reference drafts |
| `assets/symbols/` | Device catalog and placeholder symbols v0.1 |

## Where code lives

| Area | Folder |
| --- | --- |
| Pipeline package | `src/tcp_planner/` (paths resolved only through `src/tcp_planner/config/settings.py`) |
| UI | `apps/web/` |
| Config, rule pack, assets | `config/`, `rule_pack/`, `assets/` |
| Prompts | `prompts/`: one file per prompt, with an id, a version and a sha256 in its header, loaded with a hash check and pinned by tests (D-129). No prompt text lives in code on the new site-understanding path; legacy POC prompts stay in code until the S8 cutover |
| Tests | `tests/unit/`, `tests/integration/...`, `tests/golden/` |
| Run data | `var/` (new runs are not tracked) |
| Backups | `backup/orphans/<date>/` with `MANIFEST.json`; `scripts/restore_backup.py` restores them |
| Experiments | `spikes/` (never imported by `src/`) |

If code and plan disagree, **stop and report**. Do not silently follow either one.

## Core rules

1. **AI only observes. Code decides.**
   - The TA choice, rules, distances and placement are deterministic code driven by the rule pack.
   - The AI returns observations and image positions (pixel coordinates). It never returns a length in feet. Code computes every length (D-64).
2. **Never invent a value.**
   - A value with no source stays empty and is marked `SOURCE_REVIEW_REQUIRED`, which forces REVIEW\_REQUIRED.
   - An unknown fact stays `UNKNOWN` and goes on the one SME form.
3. **No hardcoded regulatory values.**
   - Read every value from the rule pack through `RulePackStore`, with its `rule_id`, source table, section and page.
   - All thresholds and limits live in config or the registry.
4. **Mandatory start fields (D-59):** `road_type`, `posted_speed_mph`, `traffic_volume`, `lane_closure`.
   - The SME types them in the UI, and Run stays disabled until they are filled.
   - No code calculates, pre-fills or overwrites them.
   - A computed check that contradicts one raises a conflict question. It never changes the value.
5. **Traffic control method (D-68):**
   - It is not a UI start field. When the router picks TA-10, code sets it to Flagger.
   - Flagger is the default. Police detail instead of flagger is future scope (D-68).
6. **KML (D-66):** read coordinates only (points, lines, polygons).
   - Ignore all `ExtendedData`, including `tcp:*` and `selected_ta`.
   - Placemark names are display labels only.
7. **TA hypothesis:** comes only from the UI "Select TA" dropdown (Auto, TA-1, TA-6, TA-10, TA-33). It is checked against facts and never trusted alone.
8. **Taper and buffer:**
   - The automatic search never moves them, and no pre-approved band exists for them.
   - Only the SME may move them, as a one-off exception for that plan version.
9. **Every plan object carries a trace:** rule\_id, pack version and hash, source, inputs, calculation, validator results, actor.
10. **Approval gate (D-65):** `require_sme_approval_for_all_plans` defaults to `true`. Every plan waits for an SME click.
11. **Three outcomes and the two-source rule (D-92, D-111, D-119).**
    - Every site fact has one outcome: FOUND (the source gives a value, or the thing is there), NOT_PRESENT (the source was checked and the thing or tag is absent) or UNKNOWN (it could not be determined; a reason code says why). A source that was not checked is never NOT_PRESENT.
    - For lanes per direction, divided, shoulder and one-way, the AI and OSM must agree. Two AI calls, two crops, or any code check never count as a second source. One source gives UNKNOWN, with the AI value kept as a candidate.
    - Code checks and consistency checks only lower confidence or give UNKNOWN.
12. **No TA id in the router, the fusion or the call-2 code (D-128).** A made-up TA added to a test pack must work with no code change; a test scans for TA ids.
13. **Calibration values (D-127).** Every calibration value (the 5 m edge, the 30 degree bearing, the confidence floors per profile, the pixel errors) lives in config, tagged `CALIBRATION_PENDING` until calibrated. Each run records the values it used. Each change gets a decision-log entry.
14. **Site exceptions (D-138, D-155).** `config/site_exceptions.json` holds site exceptions. The SME proposes an entry, the admin enters it, and each entry gets a decision-log entry. Per-job answers travel with the plan, not in this file.
15. **Roles (D-141 to D-143).** SME reviewer, approver and admin. The approver is for rule pack approval only. The zone cap and deviations are the SME's. The admin can do everything for now. Roles are a dropdown and every action is recorded as "role selected, not verified".
16. **Sealed rule pack versions (D-107, D-144).** Frozen copies under `rule_pack/versions/<version>/` and `INDEX.json` are never edited. The current pack must equal the latest INDEX entry. Any pack change needs a new version through `scripts/seal_rule_pack_version.py` and the owner's approval.

## AI calls

- At most two AI calls per zone. Call 1 is the wide read and runs first and blind: it never sees OSM values or any value from code (D-119). Call 2 re-observes at fine zoom the deciding facts, the chosen TA's fields and the conflicts, with crops. It is never shown the OSM, call-1 or code value for lanes, divided, shoulder or one-way (D-120). If call 1 and call 2 disagree on a field, the field is UNKNOWN (D-123). Lane count is a field in call 2 whenever call 2 runs; it never forces a call by itself (D-121).
- Prompts live in `prompts/`, one file per prompt with id, version and hash, loaded with a hash check and pinned by tests (D-129). This applies to the new site-understanding path; legacy POC prompts stay in code until the S8 cutover.
- Output is **JSON only** (D-61). The format is decided by the S0 spike; the expected result is a flat facts list.
  - Every property is required. Use no nullable unions and no `minimum`/`maximum` in the schema.
  - Validate in code with Pydantic. Compare enum values without regard to case.
  - A missing or malformed fact becomes `UNKNOWN`.
- Resize every image in code to the model's limit before sending.
- Crops are cut in code first. Fetch a higher-zoom Azure Maps image only when there are too few pixels.

## Data sources (D-53, D-62, D-63)

**Allowed:**
- Azure Maps
- OSM (Overpass)
- MassGIS / MassDOT road inventory
- RIGIS / RIDOT
- FHWA HPMS
- Census TIGER urban areas
- USGS 3DEP
- MBTA and RIPTA GTFS
- FRA grade-crossing inventory
- City open data, when a job needs it

**How to treat them:**
- All fused geometry is low confidence. Imagery decides, and disagreements are recorded.
- None of these sources fills a mandatory start field.
- Do not add any other paid API.

## Storage

- All reads and writes go through `ArtifactStore`, `StateStore` and `RulePackStore`. Use local adapters only, because cloud is out of the MVP.
- Persist artifact references `{uri, sha256, size, media_type}`, never raw paths.
- Every persisted record carries a `schema_version`.
  - Rule pack exception (S4): `schema_version` sits on `rule_pack/pack.json` and on every part file. Rows inherit their part's version and do not repeat it.
- Artifacts are write-once.

### Known limits of the file stores (S2, D-84)

- **Lock gap.** A state write checks that it still owns its lock file and then calls `os.replace`. A lock can be taken
  over in the gap between the check and the replace, so two writers can in rare cases both write; the version number
  (compare-and-set) catches most of these.
- **PID reuse.** A lock records the owner's PID and timestamp. After the owner dies, a new process may reuse the PID and
  the lock looks alive until it goes stale (`TCP_STATE_LOCK_STALE_S`, default 30 s).
- **OneDrive.** The repo sits in OneDrive. It may sync or hold `.lock`, `.tmp-*` and `*.lock.stale-*` files, which makes
  a write wait or retry. These names are in `.gitignore`. Local disks only; no network shares.
- **Event durability.** Only events the caller marks `durable=True` (process started and finished, result) are fsynced.
  A progress event (span start/end) survives a process crash but can be lost in a power cut.
- **Line endings.** Pipeline output files keep the OS line ending (CRLF on Windows), exactly as before S2, so stored
  expected outputs stay byte-identical. Hashes of the same run differ between Windows and Linux.
- **Legacy runs.** Runs made before S2 (`ui/*.json`) are read-only: listed and opened, never resumed, revised or compared.
  Assistant event streams written before S2 can be read but not appended to; sessions from before S2 are not read.
- **Rendered files.** Image, PDF and DXF outputs are registered with the store (SHA-256 and size) only after the renderer
  wrote them. Since S3 the SHA-256 and size of every output file are in the run's `result.output_index`. The raw-path scan
  reads JSON only. One-time check in S3: PNG, JPEG, PDF and JSON outputs hold no local path; DXF and DWG are unchecked (no ODA
  converter on the dev machine). `tests/integration/pipeline/test_dxf_local_paths.py` checks them where the converter exists.

### Known limits of projects and zone runs (S3)

- **One process drives a project.** The orchestrator's lock is per process (the web server's threads). Do not run the
  `project` command and the server on the same project at the same time.
- **Retry is idempotent, not transactional.** Run reserves run ids in the project record, builds each run, then starts it. A
  crash in between leaves a reserved id or a built run that the next Run completes; nothing is created twice.
- **The live UI path is untried.** Projects ran only on offline scenarios, recorded fixtures and fakes. The Azure Maps and AI
  path through the project UI waits for the real-KML recordings (Colorado after S7, the rest after S9; `TCP_LIVE=1`, run by the owner).
- **Cap approval is not an identity.** `approved_by` is typed text or "UI click", stored with `verified: false` (an SME reviewer
  session replaces it in S10 or S11; the approver role is for rule pack approval only, D-143). An approval covers the zone count it was given for, not a bigger set.
- **A REVIEW_REQUIRED zone has no draft.** The pipeline drafts only SUPPORTED_AUTO; the project status REVIEW_REQUIRED
  reflects the zone decision. Drafts for review come with S7/S8 and D-65.
- **No 429 backoff.** Up to `project.max_parallel_zone_runs` zone runs call Foundry, Azure Maps and Overpass at once.
- **Lineage and labels.** The SME lineage key is `lineage_key(project_id, zone geometry hash)` (D-82). A run outside a
  project has none, and the assistant answers `NO_PROJECT_LINEAGE`. Label files live in `var/labels/` (ignored by git).
- **D-59 breaches still in the engine** (fix in S7/S10): the OSM `maxspeed` fallback and the encroachment override of the SME's
  lane closure, both in `site_model/fusion.py`.
- Only a project starts runs over HTTP: `POST /api/runs` answers 400.

### Known limits of the device catalog (S5)

- **Catalog exception.** `assets/symbols/device_catalog.json` carries `schema_version` once; each entry's `asset` and `raster` are
  `{uri, sha256, size, media_type, status}` with a `uri` relative to `assets/`. The catalog holds no regulatory number: sizes
  come from the pack through `size_for()`. Only `rules/device_catalog.py` reads the file. After any change run
  `scripts/seal_device_catalog.py` (and `scripts/render_symbols.py` after an SVG change).
- The road-type to size-column mapping is PROPOSED until the SME answers question 38.
- Device ids and symbol file names must not differ only by case (Windows, OneDrive).
- PNG bytes can differ between PyMuPDF versions: the committed PNGs and their recorded hashes are authoritative.
- Every symbol is a placeholder; a plan that uses one is REVIEW_REQUIRED and carries the label text. S12 draws it.


## Tests

- **Unit and integration tests make no live calls.** Use recorded fixtures and fakes. The network is blocked in tests, and a missing fixture is an error.
- **Live Azure Maps and AI calls** are allowed only in:
  - the S13 full-pipeline test;
  - the S0 schema spike;
  - recording real-KML fixtures with `python -m tests.support.record live`: Colorado once after S7 merges (calls 1 and 2 together), the rest after S9. Granite is compared at pole P32 (Phase I) only. The owner runs recordings with `TCP_LIVE=1`.
  All run only when `TCP_LIVE=1` and only when the user runs them.
- **Every script that can make live calls** (the recorder, the spike, the S13 test) calls `use_os_trust_store()` first, as the pipeline CLI does. Certificate verification is never turned off.
- **Gate for every slice:** applicable suites green, new slice tests green, replay deterministic. From S13 on, the golden comparator report must not get worse.

## How to work

1. **One slice per session.** Branch: `tcp-mvp/sNN-short-name`, off the previous slice (`tcp-mvp/base` for the first).
2. **Plan first.** Before writing code, show the plan for the slice against its acceptance criteria, and wait for approval.
3. **Stop and ask** when:
   - the repo differs from the plan;
   - a value has no source;
   - a decision is not covered by the docs.
   List options with trade-offs and a recommendation.
4. **Never delete files.** Unused code goes to `backup/orphans/<date>/` with a manifest, and only in slice S15 after approval. S0a's 16 backups were an approved early exception to "only in S15".
5. **Finish every session with:**
   - files changed;
   - tests added;
   - test results;
   - contradictions with the plan;
   - open questions.

## Out of scope for the MVP

- Custom KML tags
- Cost estimates and caps (only a max-zones config cap exists)
- The reference-only UI toggle
- Cross-run imagery cache
- Free-text description parsing
- The pipeline Q&A chatbot
- Engineer-designed plans
- Shared map acquisition
- The cloud move
- Road type and speed pre-fill
- TOON
