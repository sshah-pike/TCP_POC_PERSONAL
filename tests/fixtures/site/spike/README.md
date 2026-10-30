# Spike data for S6 (real model output, pre-tuning prompt)

Copied from branch `tcp-mvp/s00-schema-spike` (`spikes/schema_spike/raw`, `inputs`), commit 1a8f59c, S6 Q16 A.

- `raw/*_B_r*.response.json`: the 9 variant-B responses of `claude-opus-5-5` (3 sites x 3 repetitions). They come from the
  spike prompt, before the S0 tuning changes. They are parser and measurement inputs, not replay fixtures: the new
  call 1 request has a different fingerprint.
- `raw/granite_B_r1.request.json`: one request, for the schema and prompt wording of the spike.
- `inputs/*.jpg` and `*.json`: the three wide Azure Maps images (1280 px) and their scale (`metres_per_pixel`).
  The images are Azure Maps imagery stored in the repo (D-46 dropped the terms check).
