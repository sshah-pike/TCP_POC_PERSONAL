# TCP POC Runner (local UI)

A thin local UI around the existing pipeline. Each run is the unmodified CLI entry point
`tcp_planner.orchestration.pipeline.main(argv)`, executed in its own process; the UI only observes it. Decisions, outputs,
the TCP sheet and the DWT output are exactly what the pipeline produces.

## Run

```
pip install -r requirements.txt            # existing pipeline dependencies; the UI server adds none
python -m tcp_ui.server                     # API + built UI on http://127.0.0.1:8765
```

Build the UI once (needs Node.js 20+):

```
cd tcp_ui/web
npm install
npm run build                               # served by tcp_ui.server from tcp_ui/web/dist
```

UI development with hot reload: keep `python -m tcp_ui.server` running, then `npm run dev` in
`tcp_ui/web` and open http://127.0.0.1:5173 (`/api` is proxied to the Python server).

Credentials stay where they are today (`.env` / environment, read by the pipeline process). The
server never reads or returns them.

## Storage

```
runs/<run-id>/input/    uploaded KML
runs/<run-id>/output/   the pipeline --out directory (unchanged file names)
runs/<run-id>/ui/       UI metadata: request.json, process.json, events.jsonl (telemetry spans),
                        result.json, rule_pack.json, usage.json (Anthropic response.usage), stdout.log
```

Set `TCP_UI_RUNS_DIR` to store runs elsewhere.

## Cost

AI token usage is recorded from the Anthropic API response. A cost is shown only as an *estimate*
and only when per-token prices are entered in `tcp_ui/pricing.json` (shipped empty). Imagery and OSM
providers do not report cost to the pipeline, so they show "Not Available".

## Tests

```
python -m pytest tcp_ui/tests -q            # offline; compares UI-reported results with direct pipeline runs
```
