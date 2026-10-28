# TCP Planner web UI (local)

A thin local UI around the pipeline. Each run is the unmodified CLI entry point
`tcp_planner.orchestration.pipeline.main(argv)`, executed in its own process; the UI only observes it.
Decisions, outputs, the TCP sheet and the DWT output are exactly what the pipeline produces.

## Run

```
pip install -r requirements.txt                 # pipeline dependencies; the UI server adds none
pip install -e . --no-build-isolation           # makes tcp_planner importable (src/ layout)
python -m tcp_planner.web_api.server            # API + built UI on http://127.0.0.1:8765
```

Build the UI once (needs Node.js 20+):

```
cd apps/web
npm install
npm run build                                    # served by tcp_planner.web_api.server from apps/web/dist
```

UI development with hot reload: keep `python -m tcp_planner.web_api.server` running, then `npm run dev` in
`apps/web` and open http://127.0.0.1:5173 (`/api` is proxied to the Python server).

Credentials stay where they are today (`.env` / environment, read by the pipeline process). The
server never reads or returns them.

## Storage

```
var/runs/<run-id>/input/    uploaded KML
var/runs/<run-id>/output/   the pipeline --out directory (unchanged file names)
var/runs/<run-id>/ui/       UI metadata: request.json, process.json, events.jsonl (telemetry spans),
                            result.json, rule_pack.json, usage.json (Anthropic response.usage), stdout.log
```

Set `TCP_UI_RUNS_DIR` to store runs elsewhere.

## Cost

AI token usage is recorded from the Anthropic API response. A cost is shown only as an *estimate*
and only when per-token prices are entered in `config/pricing.json` (shipped empty). Imagery and OSM
providers do not report cost to the pipeline, so they show "Not Available".

## Tests

```
python -m pytest tests/integration/web_api -q   # offline; compares UI-reported results with direct pipeline runs
cd apps/web && npm test                         # UI unit tests (vitest)
```
