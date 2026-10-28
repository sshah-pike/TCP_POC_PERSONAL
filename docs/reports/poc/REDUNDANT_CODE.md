# Redundant code (listing only - nothing here was changed or removed)

The POC uses **Azure Maps** as the only imagery provider and **Microsoft Foundry** (GPT profile, `openai_responses`)
as the only model provider. The code below is not used on that path. It is listed with file:line so it can be
reviewed and removed later on purpose. Line numbers are as of 2026-10-19 (after the two-call agent change).

## 1. USGS NAIP imagery provider
| Where | What |
|---|---|
| `tcp_poc/map_provider.py:160-197` | `UsgsNaipProvider` (class, `SERVICE` / `READ_TIMEOUT_S` env settings, `fetch_context`) |
| `tcp_poc/map_provider.py:230` | `get_map_provider()` branch `usgs_naip` |
| `tcp_ui/check_usgs.py:1-70` | whole module: live USGS connectivity check, used only for this provider |
| `tcp_ui/store.py:20` | `"usgs_naip"` in `MAP_PROVIDERS` (already hidden from the UI form by `UI_MAP_PROVIDERS`, line 24) |
| `tcp_ui/tests/test_diagnostics.py:1-193` | tests that drive the USGS provider; skipped unless `TCP_RUN_USGS_TESTS=1` (lines 22-23) - these are the 11 skipped tests |
| env | `TCP_USGS_NAIP_SERVICE`, `TCP_USGS_NAIP_READ_TIMEOUT_S` |

## 2. Esri World Imagery demo provider (also not Azure Maps)
| Where | What |
|---|---|
| `tcp_poc/map_provider.py:138-157` | `EsriDemoProvider` ("INACTIVE legacy provider", licensing not cleared) |
| `tcp_poc/map_provider.py:231` | `get_map_provider()` branch `esri_demo` |
| `tcp_ui/store.py:20` | `"esri_demo"` in `MAP_PROVIDERS` |

## 3. Direct Anthropic API provider (not Foundry)
| Where | What |
|---|---|
| `tcp_poc/anthropic_provider.py:1-64` | whole module: `AnthropicVisionProvider` (direct Anthropic API, `ANTHROPIC_API_KEY`, server-side fallback beta). It also has no `supports_agent`, so the two-call agent reports `AI_PROVIDER_NOT_AGENT_CAPABLE` if it is selected. |
| `tcp_poc/vision_provider.py:162-165` | `get_vision_provider()` default `"anthropic"` (when `TCP_AI_PROVIDER` is unset) and its branch |
| `tcp_ui/runner.py:134` and `tcp_ui/runner.py:489-528` | `_install_anthropic_usage()` - wraps `anthropic.Anthropic` (direct API) to record usage; Foundry usage is recorded from the provider result instead (comment at line 528) |
| `tcp_ui/store.py:21` | `"anthropic"` in `AI_PROVIDERS` (already hidden from the form by `UI_AI_PROVIDERS`, line 25) |
| `tcp_ui/store.py:385, 409` | `_priced(..., provider="anthropic")` default provider key |
| `tcp_ui/pricing.json` `"anthropic"` section | prices for the direct API (all null) |
| `tcp_ui/tests/test_ui_adapter.py:174-195` | test of `_install_anthropic_usage` |
| `tcp_ui/tests/inproc.py:18-28`, `tcp_ui/tests/test_azure_maps_diagnostics.py:30, 44`, `tcp_ui/tests/test_diagnostics.py:30, 45` | save/restore of `anthropic.Anthropic` around in-process runs (only needed because of the wrapper above) |
| env | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, `TCP_MODEL`, `TCP_AI_FALLBACKS` |

## 4. Related, but NOT redundant (kept on purpose)
- `tcp_poc/foundry_provider.py:153-195` `AnthropicMessagesAPI`: Foundry's API family for **Claude deployments on Foundry**.
  It is Foundry (not the direct Anthropic API) and is still the `default_profile` in `foundry_profiles.json`, so it is
  not listed above. This POC run uses the GPT profile (`openai_responses`) only.
- The `anthropic` package (`requirements.txt`) is still needed by `AnthropicMessagesAPI`.
- Superseded by the agent, not by the provider choice (so not part of this list): the UI's legacy comparison
  variants `evidence_mode=multi`, `vision_mode=grounded_v2` and the OSM-claims switch no longer change the model
  request (agent call 1 is always one blind wide image); `tcp_ui/views.py` and `runner.prepare_views()` still run but
  their views are not sent to the model.
