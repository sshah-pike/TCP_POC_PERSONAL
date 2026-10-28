# CLAUDE.md — TCP MVP

Read this file at the start of every session. It applies to every slice.

## What this project is

The tool takes a KML of work locations and produces draft traffic control plans (TCPs): PDF sheets with imagery, signs, tapers, buffers and dimensions, plus a full audit trail. An SME reviews and approves every plan.

- **MVP scope:** TA-1, TA-6, TA-10 and TA-33 only. Anything else returns `NO_TA_MATCH`.
- **Branch:** `TCP-MVP`. The old POC is backed up and is not a regression oracle. There is no separate legacy TA-1 path.

## Documents (source of truth)

| File | Use |
| --- | --- |
| `docs/TCP_MVP_Architecture_Plan_v4.md` | The plan, decisions (D-xx) and ADRs |
| `docs/TCP_MVP_Development_Slices.md` | Slice specs S0 to S15: scope, acceptance criteria, tests |
| `docs/schema_spike_prompt.md` | AI output-format spike, run in S0 |
| `docs/sources/` | MUTCD 11th Edition, Chapter 6, December 2023 revision |
| `docs/references/` | The three reference TMP PDFs and three KMLs |
| `tests/golden/` | Golden set v0.1 extracted from the reference drafts |
| `assets/symbols/` | Device catalog and placeholder symbols v0.1 |

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
   - Police details are a post-draft SME review action: W20-7 becomes POLICE OFFICER AHEAD and the checks re-run.
6. **KML (D-66):** read coordinates only (points, lines, polygons).
   - Ignore all `ExtendedData`, including `tcp:*` and `selected_ta`.
   - Placemark names are display labels only.
7. **TA hypothesis:** comes only from the UI "Select TA" dropdown (Auto, TA-1, TA-6, TA-10, TA-33). It is checked against facts and never trusted alone.
8. **Taper and buffer:**
   - The automatic search never moves them, and no pre-approved band exists for them.
   - Only the SME may move them, as a one-off exception for that plan version.
9. **Every plan object carries a trace:** rule\_id, pack version and hash, source, inputs, calculation, validator results, actor.
10. **Approval gate (D-65):** `require_sme_approval_for_all_plans` defaults to `true`. Every plan waits for an SME click.

## AI calls

- At most two AI calls per zone. Call 1 is the wide read. Call 2 covers only the chosen TA's missing fields, with crops.
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
- Artifacts are write-once.

## Tests

- **Unit and integration tests make no live calls.** Use recorded fixtures and fakes. The network is blocked in tests, and a missing fixture is an error.
- **Live Azure Maps and AI calls** are allowed only in:
  - the S13 full-pipeline test;
  - the S0 schema spike.
  Both run only when `TCP_LIVE=1` and only when the user runs them.
- **Gate for every slice:** applicable suites green, new slice tests green, replay deterministic. From S13 on, the golden comparator report must not get worse.

## How to work

1. **One slice per session.** Branch: `tcp-mvp/sNN-short-name`, off `TCP-MVP`.
2. **Plan first.** Before writing code, show the plan for the slice against its acceptance criteria, and wait for approval.
3. **Stop and ask** when:
   - the repo differs from the plan;
   - a value has no source;
   - a decision is not covered by the docs.
   List options with trade-offs and a recommendation.
4. **Never delete files.** Unused code goes to `backup/` with a manifest, and only in slice S15 after approval.
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
