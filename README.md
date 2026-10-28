# TCP Planner

Takes a KML of work locations and produces **draft** traffic control plans (TCPs): PDF sheets with imagery,
signs, tapers, buffers and dimensions, plus a full audit trail. An SME reviews and approves every plan.
MVP scope: TA-1, TA-6, TA-10 and TA-33. Read `CLAUDE.md` first; the plan and slice specs are in `docs/`.

Output is an AUTOMATED DRAFT - NOT APPROVED FOR FIELD USE.

## Layout

```
src/tcp_planner/      Python package (pipeline, web API, SME review assistant)
apps/web/             web UI (React + Vite)
config/               settings JSON (pipeline, DWT, Foundry profiles, pricing, assistant)
rule_pack/            approved rule pack data
assets/               sheet frame, DWT template, device symbols
docs/                 architecture, slices, sources (MUTCD), references, reports
tests/                integration suites, fixtures, golden set
scripts/              one-off and maintenance scripts
var/                  run outputs, labels, assistant data, debug dumps (gitignored)
backup/orphans/       moved-out files with MANIFEST.json (never imported)
```

## Setup

Python 3.11+ and, for the UI, Node.js 20+.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e . --no-build-isolation      # editable install of tcp_planner (src/ layout); needs setuptools
copy .env.example .env                     # then fill in TCP_FOUNDRY_* and AZURE_MAPS_KEY
```

## Run

```
python -m tcp_planner.cli --offline supported --no-dwt      # synthetic self-test, no network
python -m tcp_planner.cli --kml site.kml --road-type RURAL  # live: Azure Maps + Foundry (needs .env)
python -m tcp_planner.web_api.server                        # local UI on http://127.0.0.1:8765
```

Build the UI once with `cd apps/web && npm install && npm run build` (see `apps/web/README.md`).

## Tests

Unit and integration tests make no live calls. Run the suites separately:

```
python -m pytest tests/unit -q
python -m pytest tests/integration/pipeline -q
python -m pytest tests/integration/web_api -q
python -m pytest tests/integration/review_assistant -q
cd apps/web && npm test
```

## Backups

Files that are no longer used are moved, never deleted, to `backup/orphans/<date>/` with a `MANIFEST.json`
(original path, reason, evidence, sha256, commit). Restore with
`python scripts/restore_backup.py backup/orphans/<date> --apply`.
