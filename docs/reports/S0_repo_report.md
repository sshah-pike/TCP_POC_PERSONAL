# S0 repo report: the plan checked against the real code (items 1 to 34)

Date: 2026-10-28. Branch `tcp-mvp/s00-setup`, code after the S0 commits (D-78, D-79, fixture harness, stored oracle).
Method: the Section 18 verification prompt of `docs/architecture/TCP_MVP_Architecture_Plan_v4.md`, answered item by item with file and line evidence.
The evidence was gathered by read-only research (code reading, XML parsing of the KMLs; public web pages for item 32 only). **No live Azure Maps or AI call was made for
this report.** A sample of the claims was re-checked by hand (obstructions empty in the base scenario, `EXPECTED_TA`, the 150 m setting, the metre-valued width in the call 2 prompt,
the `MULTIPLE_WORK_POINTS` rejection). Line numbers are as of this branch; paths are the post-S0a layout. Anything that could not be verified is marked UNKNOWN.

Verdict key: CONFIRMED (the plan is right), PARTLY TRUE, REFUTED (the plan is wrong), UNKNOWN.

## Headline findings

1. **The pipeline cannot read the real multi-point KMLs.** `parse_kml` rejects more than one Point (`MULTIPLE_WORK_POINTS`) and ends the run as `UNSUPPORTED_POC` before imagery, OSM or AI work (items 1, 2). GRANITE1 has 5 Points and E Second Street has 2 Points, so neither runs until S1 (intake) and S3 (zones). Only Colorado and the three TA examples pass intake. This is why recording the real KMLs moves to after S6.
2. **D-64 is not true of the code today.** The AI reports a width and an edge distance in metres in call 2 (`traveled_way_width_m`, `distance_to_nearest_edge_m`); call 1 has a pixel width that the wire path converts to and from metres (item 33). The plan says the AI returns positions only. This must be rewritten or the schema changed in S6.
3. **There is no router, and the code is TA-1 only in many places** (`EXPECTED_TA = "TA-1"`, `ta1_template`, rule engine, validators, eligibility, findings) (items 15, 18, 26). The router is a new module, not an edit of eligibility.
4. **No model image limit and no resize step exist** (item 21), and crops are new Azure Maps fetches, not cuts from the wide image. D-27 and the "crop in code first" rule are new behavior.
5. **Only OSM, the AI and the cross-section feed fusion** (item 24). MassDOT, MassGIS, RIGIS, HPMS, GTFS and FRA are new work; Azure Maps supplies imagery only (item 32).
6. **Several things the plan treats as new already exist** in some form: parallel child runs in separate processes (item 14), a role model (item 29), a compare-and-set version head (item 8), and a thin `RecordStore` interface on the assistant side (item 7).

## Items 1 to 11: intake, geometry and storage

### Item 1: work_reference and work_path feed s0, sign stations and W1. CONFIRMED
Signs are measured from one reference point, not from the upstream end of a path. `work_reference` is the local-frame origin; `s0` is its projection on the OSM centerline (`work.reference_station_m`);
both advance signs sit at `work_station - direction * A` with A from the rule pack. `work_path` feeds only the lateral encroachment check, W1's `geometry_type` label and drawing.
`parse_kml` takes the first Point in document order. For a 139 m path the upstream sign is A feet upstream of the Point, not of the path start; with the Point mid-path and A = 100 ft (30.5 m) it lands inside the path (derived from the code, not run).
Evidence: `site_model/fusion.py:193,477,334-336`; `geometry/local_frame.py:89,120,150-157`; `layout/rule_engine.py:84-85,97-107`; `intake/kml_reader.py:96-97`; `review/decision_overlay.py:266-268`.
Plan impact: say zone sign spacing is anchored at one reference point; path-aware placement needs new logic, a rule-pack basis and a choice of reference station.

### Item 2: eligibility, `input_feature_count`, MULTIPLE_WORK_LOCATIONS. CONFIRMED
Eligibility fails with `MULTIPLE_WORK_LOCATIONS` when `input_feature_count > 2` or `work_reference` is missing. `parse_kml` counts points plus lines, so on KML input the largest passable count is 2 and the check can never fire; coordinates give 1. It is in `TA_NON_OVERRIDABLE`.
The adapter must give each child run a `project_geometry` with `work_reference`, `work_path` (list), `input_feature_count` of at most 2, `input_hash`, `input_type`, `source_file` and `non_authoritative_metadata`.
**Where multi-point KMLs stop early** (the caution you asked me to confirm): `parse_kml` is called at `orchestration/pipeline.py:106`; any `InputRejected` there writes `eligibility_result.json` with `UNSUPPORTED_POC` and returns, with no imagery, OSM, AI or sheet work. Reasons: `MULTIPLE_WORK_POINTS` (more than one Point, `kml_reader.py:89`), `MULTIPLE_WORK_AREAS` (more than one LineString, `:90`), `NO_WORK_REFERENCE_POINT`, `UNSUPPORTED_GEOMETRY` (Polygon, Model, Track), `INVALID_COORDINATES`, `INVALID_KML` (over 5 MB, DTD or entity, malformed), `WORK_PATH_TOO_LONG`. The pipeline takes only `kml` or `lat`/`lon`: there is no entry point for pre-split zone geometry.
Counted by XML parse: GRANITE1 5 Points, 0 lines; E Second Street 2 Points, 0 lines (the "+1 line" in the verification brief is wrong); Colorado 1 Point; each TA example 1 Point. So GRANITE1 and E Second Street stop at intake; Colorado and the examples pass as single points.
Evidence: `intake/kml_reader.py:44-46,87-94,101-109`; `orchestration/pipeline.py:104-111`; `routing/eligibility.py:104-105`; `conflicts/sme_disposition.py:18`.
Plan impact: S1 replaces reject-on-multiple with a list of points; a per-zone entry point (geometry injected, not a file path) is needed.

### Item 3: where max_work_path_m is enforced. CONFIRMED (POC setting, not an engineering limit)
`config/pipeline_config.json:98-100` has `input.max_work_path_m = 150.0`; the file header says it holds implementation settings, no MUTCD value. `parse_kml` raises `WORK_PATH_TOO_LONG`, and the run ends `UNSUPPORTED_POC`. It applies to KML input only. No source for 150 m exists in the rule pack, validators or code.
Plan impact: none to the 150 m decision; zone splitting must happen before `parse_kml`, or the limit must be bypassed for per-zone geometry.

### Item 4: project_geometry in the site_model_id hash. CONFIRMED
`site_model_id = "SITE-" + content_hash(sm, drop={"site_model_id"})[:16]`; `project_geometry` is embedded whole, so `source_file`, `input_hash` (sha256 of the raw KML bytes), `work_reference`, `work_path`, `input_feature_count` and the ignored-element count all change the id. Only `retrieved_at`, `generated_at` and `duration_ms` are excluded. Zone, TA and sheet fields are not in the site model today; any new key inside it changes the id.
Evidence: `site_model/fusion.py:459-462,516`; `contracts.py:53,78-79`.
Plan impact: decide whether `zone_id` is hashed; keep zone, TA and sheet outside the hashed model or in a dropped key; do not hash the whole-file `input_hash` into a zone id.

### Item 5: OSM way-chain snapping. PARTLY TRUE
A chain exists for one road per run: `_join_chain` extends the nearest way end to end through ways with the same `name` and `ref`, joined within 1.0 m (`data_sources/osm_overpass.py:66-90,98-99`). There is no multi-point snapping, ordering of points along a chain, station spacing, or handling of branches. The OSM fetch is one circle at the work reference.
Estimate (a judgement, not a measurement): new module of a few hundred lines plus tests, M to L. Plan impact: list way-snapping and station ordering as new S3 code that reuses `_join_chain`.

### Item 6: imagery extent for a long zone. PARTLY TRUE
Imagery is centred on `work_reference` and sized `half = max(A) + analysis_margin_m`, about 365 m half-extent (730 m across) from the rule pack's largest A (1000 ft) and the 60 m margin, in one 1280 px image. Extent does not depend on `work_path`. The Azure provider picks the largest integer zoom (1 to 19) that covers the extent; above 1280 px it builds an n x n mosaic (used for the 2560 px sheet aerial; the analysis call is a single request).
`MAP_EXTENT_INSUFFICIENT` is raised when the zoom clamp leaves too few pixels, when `fetch_view` is asked for more than 1280 px, and for a too-small offline image; the pipeline maps any map error to REVIEW_REQUIRED with `MAP_CONTEXT_UNAVAILABLE`.
Evidence: `orchestration/pipeline.py:127-139,150-153`; `imagery/map_provider.py:58,63-90,74,105,210`.
Plan impact: extent is a function of A_max, not zone length; define a zone centre or bounding-box extent per child run; zones beyond about 365 m from the centre need a new extent or several images.

### Item 7: raw file-path reads and writes. CONFIRMED (widespread; overall L)
Run state lives in `var/runs/<run_id>/{input,output,ui,evidence}`, addressed by raw `os.path` joins; some paths are stored inside records (`kml_saved_path`, evidence `path`).
About 15 of roughly 30 matching files do real run, evidence or state I/O. By module: `storage/run_store.py` (layout, input write, ui JSON reads, directory listing), `storage/evidence_store.py` (manifest with tmp and `os.replace`, artifact write, cross-run resolve), `orchestration/pipeline.py` (`Run.write`/`path`, stale-file removal, JPEG saves, report), `orchestration/run_worker.py` (`events.jsonl`, atomic ui JSON, `Image.open` of reused artifacts, `resume.json`), `orchestration/run_relations.py` (deps, KML copy, resume and comparison files), `web_api/server.py` (worker subprocess, logs, file serving), `review/assistant/repositories/json_store.py` (already behind `RecordStore`), `review/assistant/core/audit.py` (daily jsonl with cross-process file locks), `core/identity.py` (sessions), `services/{run_context,pipeline_controller,review_routes,annotated_image}.py` (direct reads), `evaluation/ground_truth_labels.py`. Config, rule-pack and prompt reads are read-only and can stay local.
Estimate: ArtifactStore L (output, evidence, input files and every code path that resolves a path to a file); StateStore M to L (`build_state` reads about 10 files per run and the worker is a separate process that shares state only through files); assistant RecordStore, audit and sessions S to M.
Plan impact: size S2 accordingly and name the callers that bypass any abstraction; copy the assistant `RecordStore` pattern.

### Item 8: move_head compare-and-set and locks. PARTLY TRUE
`versions.move_head` calls `store.compare_and_set_head`, raising `VERSION_CONFLICT` (409) on mismatch; `JsonStore` implements it under a process-local `RLock` (read, compare, tmp file, fsync, `os.replace`). It maps directly to `UPDATE ... WHERE value = :expected`, and `create()` (O_EXCL) maps to an INSERT with a primary key. Limits: the lock is not cross-process, and `proposals.py:205-246` runs `create` then `move_head` as two steps, so a failure between them leaves an orphan version record. A database version needs one transaction around create, head move and blob write.
Evidence: `review/assistant/services/versions.py:96-99`; `repositories/json_store.py:19,36-49,104-116`; `repositories/base.py`.

### Item 9: `_dependency_changes` and evidence signatures. PARTLY TRUE
A change is reported when the config hash, the rule-pack hash, or the KML file hash (against `project_geometry.input_hash`) differs; the last applies only to KML runs and hashes the whole file, so a zone cut from a shared multi-point KML would be flagged whenever any other zone's point changed. Evidence reuse already keys on geometry, not `input_hash`: `geometry_hash(pg)` hashes `{work_reference, work_path}`; `map_signature` adds provider, scale model, API version, half extent and size; `osm_signature` is lat, lon, radius; `ai_signature` is the image pixel hash plus the context hash. So evidence is effectively per zone if each zone has its own geometry.
Evidence: `orchestration/run_relations.py:88-110`; `storage/evidence_store.py:48-70`; `orchestration/run_worker.py:320`.
Plan impact: define a zone-level input hash and a project-level hash, and make `_input_file` and `_dependency_changes` zone-aware.

### Item 10: every use of the SME lineage key. CONFIRMED
The key is `site_id_for(pg) = geometry_hash(pg)[:16]`, set at `run_context.py:83`. Uses: head keys `se-<lk>` and `pv-<lk>`, version ids `se-<lk[:8]>-vN` and `tcp-plan-<lk[:8]>-vN` (`versions.py:28-35,77-78,96-97`); `lineage_key` stored in versions, site-evidence and conversation records (`proposals.py:196-236,283`; `conversations.py:77`); listings filtered by it (`versions.py:50-52,68`; `review_routes.py:314`; `assistant_state.py:33,131`); finding ids `F-sha256(lk|category|subject)[:10]` (`findings.py:136-140`); a review tools cache key (`review_tools.py:55`); ground-truth label files `var/labels/<site_id>.json` and scoring (`ground_truth_labels.py:35,42,79`; `comparison_scoring.py:51`).
If lineages become project-scoped, existing heads, version chains, finding ids and label files would no longer be found unless migrated. Whether any such data needs migrating is UNKNOWN (`var/` was not inspected for it). Plan impact: decide project-, zone- or composite-scoped keys; a clean break is acceptable if `var/` data is disposable and you confirm.

### Item 11: UI and API assume one run is one location. CONFIRMED
`NewRunForm` takes one KML or one lat/lon pair and posts one `/api/runs`; the server starts one OS subprocess per run; there is no project or zone grouping (only `parent_run_id` from resume lineage) and `list_runs` returns a flat list. Polling: `App.tsx` polls the run and comparison lists every 4 s; `RunView` polls `getRun` every 1 s while RUNNING; the assistant dock every 3 s while RUNNING and 10 s otherwise. `list_runs` calls `build_state` for every run directory on disk, each reading about 10 JSON files, so each poll costs O(all runs on disk) and N child runs multiply it. No concurrency cap on worker subprocesses and no paging or caching of `list_runs` was found (the server was not run).
Evidence: `apps/web/src/components/NewRunForm.tsx:21-25,44-45,60-61`; `apps/web/src/App.tsx:36-44`; `components/RunView.tsx:120-138`; `assistant/AssistantDock.tsx:102`; `web_api/server.py:8-15,111-129`; `storage/run_store.py:269-290,495-516`.
Plan impact: a project-level API with a status roll-up, `list_runs` paging or caching, a child-run concurrency cap, and a multi-point entry in the form.

## Items 12 to 22: tests, router, SME, audit, images, sheets

### Item 12: test inventory, golden harness, record and replay. PARTLY TRUE
Record and replay of map, OSM and AI responses now exists (`tests/support/`, S0). There is **no golden pass/fail harness**: `tests/golden/golden_*.json` are an extraction output marked DRAFT in `tests/golden/README.md` ("needs an SME check before it is used as a pass/fail gate") and no test reads them. The replay harness keys by a sha256 of the canonical request, supports write-once fixtures, raises `MissingFixtureError` on a gap, and `conftest.py` blocks non-loopback sockets unless `TCP_LIVE=1`. Three seeded sites exist (`granite_p30`, `alton_bradford`, `exeter_ten_rod`); `test_fixture_replay.py` proves two replays give identical fingerprints, decision and plan hash, but the sites have no expected outputs. Byte-level oracles exist only for the 13 offline scenarios plus the KML-input case (`test_global_identity.py`).
Plan impact: the Section 14 compare rules (TA, sheet count, sign order, positions) are a new test; multi-point recording waits for S6.

### Item 13: Polygon support. CONFIRMED (unsupported today)
`parse_kml` records Polygon as `UNSUPPORTED_GEOMETRY`; the model carries only `work_reference` and `work_path`. Touch points: intake (new geometry type and a representative point), fusion encroachment (`fusion.py:334-337`), validator `GEO-TRAVELED-WAY` (`validators.py:134-141`), eligibility (`eligibility.py:104`), rule engine `geometry_type` (`rule_engine.py:85`), placement path (`local_frame.py:150-157`), SME overlay (`decision_overlay.py:266-270`), annotated image (`annotated_image.py:159`), sheet renderer (`sheet_renderer.py:122-130`, a fixed symbolic box, never to scale) and evidence hashing (`evidence_store.py:49`).
Plan impact: keep Polygon out of the MVP; if added, budget a `work_area` field and changes in about 8 modules.

### Item 14: child runs in parallel. PARTLY TRUE
Parallelism exists: the comparison feature creates several child runs, each in its own directory, and starts each as a separate `run_worker` subprocess without waiting (`web_api/server.py:72-96,110-130`; `orchestration/run_relations.py:282-298`). Output clearing is per run (`pipeline.py:67-73`) and the evidence lock is per process, so no output file is shared between runs. Missing: rate-limit handling (a 429 maps to `AI_RATE_LIMITED`, no retry or backoff found, `ai/foundry_provider.py:138,180`) and a concurrency cap, so N zones means N simultaneous Foundry, Azure Maps and Overpass calls.
Plan impact: add a bounded worker pool and backoff for 429; the real shared-state risk is the new project-level state.

### Item 15: router. REFUTED (none exists)
The rule pack fixes `selected_ta = "TA-1"` with `other_tas_allowed: []`; the loader hard-fails otherwise (`rules/rule_pack_loader.py:7,64-66,103-120,148-149`) and `rule_engine.execute` raises `RULE_PACK_TA_NOT_SUPPORTED` for any other TA (`layout/rule_engine.py:76-80`). Eligibility is a pass/fail check of TA-1 conditions, not a chooser (`routing/eligibility.py:69-108`). Deciding fields today: `work.location`, `work.encroaches_traveled_way`, `work.requires_lane_closure`, all computed by fusion. There is one observation schema for calls 1 and 2 (`ai/vision_provider.py:27-52`, `ai/vision_agent.py:150-166,180-189`); call 2 re-asks the same field groups per `crops.field_map` and cannot take TA-specific fields without a new group and prompt section.
Adding TA-6, TA-10 and TA-33 needs per-TA rule-pack sections, a template builder per TA, `rule_engine.execute` branches, and an extended schema with new call 2 groups. Plan impact: the router is a new module plus a new rule-pack layout.

### Item 16: obstructions. CONFIRMED (not used in the sign-conflict check)
`GeometryValidator` loops over driveways, intersections, crosswalks, roundabouts and ramps only (`validation/validators.py:151`). Obstructions go into `site_model.features.obstructions` (`fusion.py:442`) and are used only by the assistant's spatial warnings and the annotated image (`review/assistant/services/geometry_tools.py:16,154-158,180,189`). **None of the 13 offline scenarios contains an obstruction** (0 of 13: the base scenario has `obstructions=[]` and no branch adds one, `offline_scenarios.py:35,43-69`). Adding a check changes the stored expected outputs only if a new check id appears in `validation_results.json` (3 scenario directories have that file per the research; regenerate with `python -m tests.support.make_expected`). Plan impact: a new obstruction scenario is needed to test the rule.

### Item 17: work-fact change and recomputation. PARTLY TRUE
Derived work facts are recomputed deterministically after SME fact decisions (`review/decision_overlay.py:1-16,251-290`: lane count and road edges, then encroachment, location, lane closure, alternating traffic, pedestrian impact). `review/revision_derivation.py:19-50` re-runs eligibility, rules, placement, adjustments and both validators, so it is the hook for a router re-run. Sign moves never alter work facts (`plan_adjustments.py:26-45`). No "remaining lane width" value is computed anywhere. Plan impact: add remaining lane width as a derived field and put the router between `evaluate_eligibility` and `execute_rules` in `derive`.

### Item 18: SME exceptions. PARTLY TRUE
Two exception types exist, staged through the assistant tool `record_exception`: `RULE_CONFLICT` (accept a failed validator check unless non-overridable) and `TA_NOT_APPLICABLE` (generate the TA-1 layout though eligibility failed). Both need `sme_exceptions_enabled` (true now), a policy action, a role, a reason and a confirm flag, and both are self-confirmed. `MULTIPLE_WORK_LOCATIONS` and `ROAD_TYPE_NOT_SUPPORTED` stay non-overridable. The SME cannot choose a TA: `ta_eval.catalog` lists only TA-1 and `rule_engine.execute` rejects others.
Evidence: `review/assistant/services/exception_tools.py:1-9,24-91`; `conflicts/sme_disposition.py:11-19,53-100`; `review/action_policy.py:12-17`; `apps/web/src/assistant/ExceptionDialog.tsx`.
Plan impact: the conflict ladder's "SME exception" step needs a new base-TA action, a router candidate list, a template per TA, and removal of the TA-1 literals.

### Item 19: SME question form. PARTLY TRUE
Three separate places ask the SME: the run form (`NewRunForm.tsx`: road type, speed, lane closure, options), finding-by-finding review cards (CONFIRM, CORRECT or MARK_UNRESOLVED per finding, `review/assistant/review_routes.py`), and chat clarification forms (`services/clarify_forms.py`: choice, number and text fields with required, range and choices). There is no batched form and no conditional sub-question (no show-if logic). Plan impact: a form-spec schema with conditions, a server endpoint for all open questions of a project, and a new renderer reusing the field types; the four start fields extend `NewRunForm`.

### Item 20: audit per object. PARTLY TRUE
Recorded per plan object in `generated_by`: rule id, pack id, version and hash, TA id, source section and table, the table value and placement station and offset; `VAL-TRACE` enforces those keys (`layout/rule_engine.py:14-19`; `validation/validators.py:107-114`). The site model carries a field-level audit list (`fusion.py:84,123,498`). SME actions go to a hash-chained append-only log (`review/assistant/core/audit.py`) and exception records. Missing against Section 11: authority layer and source page, per-object input-fact references, an explicit calculation formula with units, per-object validator results, per-object artifact hashes, an actor for machine objects, and a decision ledger for grouping, TA proposed and answered.

### Item 21: images. PARTLY TRUE; the model's maximum image size is UNKNOWN
No model limit appears in the repo and there is no resize step: `_jpeg` saves at quality 88 (`ai/foundry_provider.py:280-281,299-302`). Call 1 sends the full 1280x1280 wide image with annotations drawn on a copy. Crops are not cut from the wide image: `_fetch_crops` makes a new `fetch_view` Azure Maps request per crop (1024 px, zoom 19) with a sharpness check against an upsampled zoom-18 image (`ai/vision_agent.py:192-205,606-660`). `MAX_ZOOM = 19` is documented but `fetch_view` does not clamp, so zoom 20 can be requested and would be caught by the sharpness check; config uses zoom 19. The default profile is `gpt-5.6-sol` (`config/foundry_profiles.json`); the spike ran on `claude-opus-5-5`, and the Claude input for the 1280 px image was about 2,185 tokens (3,597 total input), so no downscale to a smaller size was visible.
Plan impact: "crop in code first" and "resize to the model limit" (D-27) are new behavior; the limit must come from the deployment owner.

### Item 22: sheets. PARTLY TRUE
`SheetRenderer` composes the sheet with matplotlib on a raster frame (`assets/sheet/sheet_frame.png`, from an approved CADD PDF), page 2448x1584 pt (34x22 in), regions from `sheet_layout.json`, written as PDF (150 dpi) and PNG (`sheets/sheet_renderer.py:11,26-85,100-112,187-244`). It chooses the smallest standard scale (20 to 200 ft/in, which includes 40 and 50) where objects and callouts fit, so the scale cannot be forced. It draws title-block values (print number hard-coded "1 OF 1", phase label "TA-1 DRAFT"), a 4-segment scale bar, 5 hard-coded general notes (not the 12 of Section 4A), a draft watermark and a plan-hash strip. The legend and notes box are part of the raster frame; no north arrow is drawn.
Plan impact: the common template at 1"=40' and 1"=50' needs a forced-scale option, notes fed from data, a drawn legend from the device list, a north arrow, and per-phase pagination, so a vector or data-driven frame.

## Items 23 to 33: width, sources, rules, devices, schema, lengths

### Item 23: width measurement. PARTLY TRUE
Primary road width is a deterministic cross-section measurement from a close aerial view (brightness profiles perpendicular to the OSM centerline, edge-line pairs fitting lanes x 2.4 to 5.5 m); the AI also reports a width and an OSM `width` tag is parsed. There is no direct lane-width measurement: per-lane width is width divided by lane count. Uncertainty is recorded only as section spread (`spread_m`, limit 0.5 m), per-attribute confidence and `centerline_error_allowance_m` 2.5 m; no pixel-size (GSD) uncertainty is recorded.
Evidence: `site_model/cross_section.py:34-109`; `site_model/fusion.py:249-295`; `data_sources/osm_overpass.py:50-53,161`; `config/pipeline_config.json:60-80,105-113`.
Plan impact (and D-80): width comes first from the cross-section, then AI and OSM; ADR-032's pixel uncertainty is new.

### Item 24: geometry sources and confidence. PARTLY TRUE
Fusion uses only OSM, the AI observation (calls 1 and 2), the cross-section and the KML geometry. No MassDOT, MassGIS, RIGIS, HPMS, GTFS or FRA code exists in `src` or `config`. Confidence: explicit OSM tag 0.9, implicit 0.6; AI confidence is the model's `attribute_confidence` with a 0.7 floor for critical fields and a 0.5 agreement floor; the geometry-derived work side is 1.0; OSM agreement counts only if the way was edited within 5 years.
Evidence: `site_model/fusion.py:71-76,133-157,177`; `config/pipeline_config.json:20-31,101-114`. Plan impact: the state-data cross-checks (D-80) are new work.

### Item 25: KML content. CONFIRMED
The reader takes coordinates only; `ExtendedData`, name, description and styles are counted (`ignored_element_count`) and ignored; no code reads `selected_ta`. It is strict: exactly one Point, at most one LineString, polygons rejected, DTD and entities rejected, 5 MB cap (`intake/kml_reader.py:11-14,64-94,104-109`). Plan impact: keep "coordinates only"; the reader must be extended for multiple points, polygons and folders.

### Item 26: rule pack loader. CONFIRMED
`load_rule_pack(path)` loads one JSON file (default name, `TCP_RULE_PACK` override), checks status `APPROVED_FOR_POC`, the SHA-256, 19 required sections and cross-references, and enforces `EXPECTED_TA = "TA-1"` (`rules/rule_pack_loader.py:6-8,34-35,103-119,122-143,146-174`). TA-1 is also hard-coded in `ta1_template` (W20-1, dimension A), `layout/rule_engine.py:74-77`, `validation/validators.py:61`, `routing/eligibility.py:140-156` and `review/assistant/services/findings.py:218`. A `RulePackStore` can wrap the loader, but multi-TA also needs those TA-1 points changed (D-81: rule pack v1 replaces the POC pack in S4).

### Item 27: existing tests. PARTLY TRUE
No live calls: Azure Maps tests patch `requests.get`; the harness replays by default. Classification is from file structure and keywords; the tests were not each read in full.

| Suite or file | Class |
| --- | --- |
| `tests/unit/test_no_backup_imports.py`, `tests/unit/test_fixture_harness.py`, `tests/support/*`, `tests/golden/*` | applies to the MVP (infrastructure) |
| `tests/integration/pipeline/test_fixture_replay.py`, `test_pipeline.py` | depends on TA-1 / legacy |
| `tests/integration/pipeline/test_foundry_provider.py` | applies (transport); the schema parts need a rewrite |
| `tests/integration/web_api/test_azure_maps_diagnostics.py`, `test_diagnostics.py` | applies (imagery) |
| `tests/integration/web_api/test_grounded.py`, `test_evidence_resume.py` | needs a rewrite (schema and agent change) |
| `tests/integration/web_api/test_ui_adapter.py` | needs a rewrite (TA-1 form fields) |
| `tests/integration/review_assistant/test_phase1_foundation.py`, `test_global_identity.py` | applies (identity, roles) |
| `tests/integration/review_assistant/test_phase2` to `test_phase8`, `test_floating_assistant.py` | depends on TA-1 / legacy |
| `tests/fixtures/expected/offline/*`, `tests/fixtures/recorded/*` | depends on TA-1 (stored outputs) |
| `apps/web/src/assistant/__tests__/assistant.test.tsx` | depends on TA-1 (UI) |

Plan impact: keep the harness, imagery and identity tests; re-record or rewrite fixtures and goldens; treat the TA-1 suites as legacy.

### Item 28: zone split beyond 150 m. CONFIRMED (no splitting today)
A longer LineString is rejected with `WORK_PATH_TOO_LONG`; Polygons are `UNSUPPORTED_GEOMETRY`; a second LineString is `MULTIPLE_WORK_AREAS`. A split at the largest gap would hook in at `intake/kml_reader.py:98-103` and the call at `orchestration/pipeline.py:106`; `geometry/local_frame.py:22-25` (`cum`) gives path lengths. Plan impact: zone splitting is new work at intake and orchestration; 150 m becomes a split threshold.

### Item 29: roles. PARTLY TRUE
A role model exists: local identities from `users.local.json` (not committed): `subject_id`, `display_name`, `roles`; a dropdown login gives an opaque session token (SHA-256 stored, 8 h TTL); no credentials, and entries with password-like keys are ignored. Roles: `SME_REVIEWER`, `AUDITOR`, `ADMIN`; there is **no approver role**. `SME_REVIEWER` has review:decide, changeset:create and confirm, exception:confirm, pipeline:resume, message:submit; `AUDITOR` and `ADMIN` are read-only (`ADMIN` adds config:read). `EntraIdentityProvider` is a placeholder returning 501. The action policy has `approval_mode SELF_CONFIRMED_POC`.
Evidence: `review/assistant/core/identity.py:12-16,44-124`; `core/authz.py:4-9`; `config/assistant/SME_ACTION_POLICY.json:2-12`. Plan impact: add an approver role to the role table, permissions and policy (open question 15).

### Item 30: devices and DWT. CONFIRMED
`assets/symbols/device_catalog.json` is version 0.1, status `PLACEHOLDER_ASSETS`; entries carry id, MUTCD code, size, category, `used_by_tas`, an SVG `asset.file` and a placeholder status; about 45 SVGs are in `assets/symbols/svg/`. The DWT is `assets/dwt/DCR-TMP-AERIAL IMAGE-TEMPLATE.dwt` (AC1032, feet). In `config/dwt_config.json` the `block_map` entries are null, `layer_map` is empty and `oda_file_converter` is null. Plan impact: Section 10A should state the placeholder assets and the unfilled DWT block mapping.

### Item 31: input schema compared with Section 4B. PARTLY TRUE
Section 4B says the AI returns positions. Call 1 (`OBSERVATION_SCHEMA`, `ai/vision_provider.py:27-50`) also asks for lane-marking visibility, shoulders and sidewalks left and right, road-edge visibility, work-reference side and relative position, six feature lists (intersections, driveways, crosswalks, roundabouts, ramps, obstructions, each with description, position, side, confidence), `image_quality`, eight attribute confidences, `osm_conflicts` and notes. The call 2 and grounded schema adds `traveled_way_width_m` with `width_measured_in`, `distance_to_nearest_edge_m` with `distance_measured_in`, per-feature image and position, evidence items, claims (`claim_id`, `seen`) and up to 5 extras (`ai/grounded_vision.py:70-100,186-204`; `ai/vision_agent.py:86-130,150-166`). Today's UI form (`apps/web/src/components/NewRunForm.tsx:28-36,56`) has KML or coordinates or an offline scenario, road type, speed (informational), lane closure, free-form options, and technical selectors; it has no traffic volume, duration, night work, TA hypothesis or title-block fields.
Plan impact: Section 4B must add the observation fields above, evidence and claims, image quality, attribute confidences and OSM conflict reporting.

### Item 32: data sources. PARTLY TRUE (public documentation only; no API call was made)
Azure Maps: only imagery is fetched (`https://atlas.microsoft.com/map/static`, tileset `microsoft.imagery`, key in a `subscription-key` header, per-request limit 2000 x 1500 px, composed from tiles; `imagery/map_provider.py:42-125`). There are no road, search or route calls, so **Azure Maps returns no road attributes today**; road attributes come from OSM tags, the AI and the cross-section. The code uses the OSM `/api/0.6/map` endpoint, not Overpass (`data_sources/osm_overpass.py:13-23`).

| Source | Endpoint | Key | Rate limit |
| --- | --- | --- | --- |
| OSM map API (in code) | `https://api.openstreetmap.org/api/0.6/map?bbox=` | no; descriptive User-Agent required | verified: no numeric limit, at most 2 download threads, may be blocked; 0.25 sq deg and 50,000 nodes per query (may change) |
| OSM Nominatim (not used) | `nominatim.openstreetmap.org` | no | verified: 1 request per second |
| MBTA GTFS | `api-v3.mbta.com`; static feed URL not on the page | key recommended; needed for the default limit | verified: 1,000 per minute with a key; unkeyed limit not stated |
| MassGIS, RIGIS, HPMS, Census urban areas, USGS 3DEP, RIPTA GTFS, FRA grade crossings | UNKNOWN | UNKNOWN (Census has key and limit sections not retrieved) | UNKNOWN |

Sources checked: `operations.osmfoundation.org/policies/api/`, `wiki.openstreetmap.org/wiki/API_v0.6`, `operations.osmfoundation.org/policies/nominatim/`, `www.mbta.com/developers/v3-api`, the Census API user guide. Plan impact: seven sources still need endpoint, key and limit verification; for speed and road attributes use OSM `maxspeed` or add a new Azure call (a decision).

### Item 33: lengths. REFUTED (the AI reports a length directly)
Code computes lengths in a local east and north frame (`geometry/local_frame.py:14-44`; `layout/rule_engine.py:80,103`; `intake/kml_reader.py:99-103`): centreline and work-path length, stations; advance-sign spacing in feet comes from the rule-pack table. The AI reports lengths in metres in the call 2 and wire schema (`traveled_way_width_m`, `distance_to_nearest_edge_m`; the prompt says "Never report a width or a distance in pixels", `ai/vision_agent.py:101-112,144-146,240-243`; `ai/grounded_vision.py:43-47,83-88,193-204`). Call 1's schema has `traveled_way_width_px`, and the wire path converts metres to pixels on decode and back with `_width_m` (`ai/vision_provider.py:33,127-128`). The deterministic cross-section overrides the model width when it succeeds (`site_model/fusion.py:255-258`). Feature positions are pixels.
Plan impact: **rewrite D-64** or change the S6 schema so the AI returns pixel positions only (the spike's format B already does: marks are pixel points and no field is a length); code measures width independently.

## Item 34: schema spike

Report: `spikes/schema_spike/REPORT.md` and the raw requests and responses in `spikes/schema_spike/raw/`, on branch `tcp-mvp/s00-schema-spike` (commits "Spike: use OS trust store for corporate proxy" and "Schema spike results").
Result: 11 of 18 allowed AI calls. The repo's current call 1 schema (23 union-type parameters) and the same style with all 18 call 1 fields added (24) were both rejected by Foundry with HTTP 400, "too many parameters with union types ... (limit: 16 parameters with unions)". The flat facts list (format B) was accepted in 9 of 9 calls, schema-valid in 9 of 9, 18 of 18 fields every call, 3.2 UNKNOWN per call, mean 3,597 input and 2,305 output tokens, mean latency 22.2 s. **D-61 is decided: B.** Prompt tuning proposal: `docs/reports/S0_prompt_tuning_proposal.md`.

Findings recorded as requirements (plan D-80, slices S6 and S7):
- **`lanes_per_direction` is unstable** (Granite 2, 1, 1 across three repetitions) and safety-critical. Cross-check it with OSM lanes and state data; a disagreement makes it UNKNOWN and raises an SME question; call 2 re-asks it with a lane-marking crop (S6, S7).
- **Marks are weak** (`lane_line`, `shoulder_edge`, `curb`; 34 of 51 marks had valid points, mean 1.8 points per mark). The deterministic `cross_section.py` is the primary width source and AI marks are secondary; an invalid or missing mark makes the width UNKNOWN; marks are requested again from call 2 crops (S6).
- **Sidewalk is often UNKNOWN on the wide image** (all three Colorado calls). Resolve it in call 2 with a crop plus OSM sidewalk tags (S6).
- **Output is about 2,300 tokens per call** (about 700 of them thinking). Cap each evidence string (S6, see the tuning proposal).

## Real KML check (Step 2 of the verification prompt, read-only)

| KML | Points | Lines | Notes |
| --- | --- | --- | --- |
| `1A8G8FM WPI 3159540 GRANITE1.kml` | 5 (P32, P31, P30, P29, P28) | 0 | stops at intake today (`MULTIPLE_WORK_POINTS`) |
| `1A8J1KB WPI 3171586 - E Second Street.kml` | 2 (MH 223, MH FA) | 0 | stops at intake today |
| `WPI 3168057 130 COLORADO.kml` | 1 (P13) | 0 | passes intake as a single point |
| `ta-6_example.kml`, `ta-10_example.kml`, `ta-33_example.kml` | 1 each | 0 | pass intake |

Point and placemark counts come from XML parsing; ExtendedData content, point-to-point distances, the grouping rule's result on them, and the comparison with the reference PDFs (including whether the Granite KML, WPI 3159540, and the Granite drawing, WPI 3178233, are the same job) were **not** examined in S0 and are UNKNOWN here. The spike used the first point of GRANITE1 (P32), MH 223 of E Second Street and P13 of Colorado.

## Where the repo differs from the plan documents

1. D-64 (AI returns positions only): the code asks the AI for metre widths and distances (item 33).
2. Items 1 and 2: signs anchor at one reference point; "E Second Street = 2 Points + 1 line" in the verification brief is wrong (0 lines).
3. D-27 (resize to the model limit, crop in code first): neither exists (item 21).
4. The plan's Overpass source: the code calls the OSM `/api/0.6/map` endpoint (item 32).
5. Source fusion: the plan expects MassDOT and other sources; only OSM, AI and the cross-section exist (item 24).
6. Router, per-TA rule pack and per-TA templates: absent; TA-1 literals are spread over at least six modules (items 15, 26).
7. ADR-032 (width uncertainty from pixel size): only spread and confidence are recorded (item 23).
8. The golden set is an unreviewed extraction, with no comparator test (item 12).
9. Section 4A sheet template: the code has a raster frame with 5 hard-coded notes and an automatic scale (item 22).
10. The role table has no approver role (item 29); exceptions are self-confirmed.
11. `.env` sets `TCP_FOUNDRY_PROFILE=gpt-5.6-sol`, while the spike and D-61 were measured on `claude-opus-5-5`. The default profile in `config/foundry_profiles.json` is also `gpt-5.6-sol`, and its call 2 schema was recorded as exceeding the Claude grammar limit. Which model call 1 uses in production is an open decision.

## Open questions

1. Which Foundry profile (deployment) is the production default for call 1 and call 2: `gpt-5.6-sol` (today) or a Claude deployment (the one measured in the spike)?
2. Rewrite D-64 (the AI may return metre widths), or change the schema so call 2 returns pixels only? The spike format B already returns pixel points only.
3. Approve the prompt tuning proposal (`docs/reports/S0_prompt_tuning_proposal.md`), in particular removing `unit` from the fact schema, which changes the D-61 schema.
4. Lineage key scope (item 10): project, zone or composite; is a clean break without migration acceptable?
5. Data sources (item 32): endpoints, keys and limits for MassGIS, RIGIS, HPMS, Census, 3DEP, RIPTA and FRA are UNKNOWN; who verifies them, and for which jurisdictions first?
6. Model image limit (item 21): who can confirm it for the deployed model?
7. Does the 12-note common sheet template (item 22) justify replacing the raster frame in S12?
8. Who is the approver role (open question 15), given that no approver role exists (item 29)?

## Test results against the S0a baseline

Run once on the final tree (commits 2 to 5 plus this report), network blocked by the root `conftest.py`, no live call.

| Suite | S0a baseline | After S0 |
| --- | --- | --- |
| `tests/integration/pipeline` | 76 passed | **82 passed** (+2 D-78 provider default, +4 fixture replay) |
| `tests/integration/web_api` | 72 passed, 11 skipped | 72 passed, 11 skipped (USGS NAIP, unchanged) |
| `tests/integration/review_assistant` | 108 passed, **1 failed** (protected-run test) | **109 passed**, 0 failed |
| `tests/unit` | 1 passed | **9 passed** (+8 fixture harness and network block) |
| `apps/web` vitest | 19 passed | 19 passed |

Also: the 13 offline scenarios and the KML-input case equal the stored expected outputs, and those stored outputs were checked identical to the pre-S0 code (commit `b7374d4`).
Not re-run for S0: the UI build and the 36 saved-run replays of the S0a baseline (the S0 commits do not touch the UI or the pipeline logic; the one pipeline-affecting change is the D-78 provider default).
Known limit: the network block is in-process, so a test that starts a subprocess (`test_global_identity.py`, which runs the CLI) is not covered by it; those runs use offline fakes and strip `TCP_*`, `AZURE*` and `ANTHROPIC*` variables.
