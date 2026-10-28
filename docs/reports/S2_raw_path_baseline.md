# S2 baseline: raw paths in persisted JSON (before any change)

Measured on branch `tcp-mvp/s02-storage` at commit e44e2e5, with `tests/support/rawpath_scan.py` over the run folders
that `run_store.create_run` plus `run_worker` produce (offline scenario `supported`, input `coordinates` and `kml`).

| File | Location | Value |
| --- | --- | --- |
| `ui/request.json` | `argv[5]` (the `--out` value) | absolute `<runs>/<run_id>/output` |
| `ui/result.json` | `out_dir` | absolute `<runs>/<run_id>/output` |

Found by reading the code, not reproduced by the offline run (it needs a real upload, an online run or a resume):

| File | Field | Source |
| --- | --- | --- |
| `ui/request.json` | `argv` `--kml <abs>`, `request.kml_saved_path` | `run_store.create_run` (115-118); `run_relations` (199-203) |
| `evidence/manifest.json` | none persisted today (`path` is built in memory by `resolve`) | `evidence_store.resolve` (129) |
| `ui/resume.json`, `ui/comparison.json` | may hold run ids, to be checked when routed | `run_relations` (231, 272) |

The old tracked POC runs under `var/runs/` store absolute paths and stay as they are (D-77, decision 5A: read-only
legacy reader).

Target after S2: the scan finds nothing in any new run folder.
