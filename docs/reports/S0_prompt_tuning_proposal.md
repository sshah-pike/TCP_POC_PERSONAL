# S0 prompt tuning proposal (call 1, format B)

Date: 2026-10-28. Read-only analysis of the schema spike data (`git show tcp-mvp/s00-schema-spike:spikes/schema_spike/raw/...`,
the 9 variant-B responses, 3 sites x 3 repetitions). **No live call was made and no code or prompt was changed.**
Spike report: `spikes/schema_spike/REPORT.md` on branch `tcp-mvp/s00-schema-spike`.

## 1. Where the ~2,300 output tokens go

Mean per call: **2,305 output tokens = about 700 thinking tokens (30%) + about 1,605 tokens of JSON text** (3,931 characters).
The thinking tokens come from `output_tokens_details.thinking_tokens` in each response. The thinking text itself is not returned.
At the observed 22 s per call, 2,305 tokens is about 105 tokens/s, so 100 output tokens is about 1 s.

Split of the JSON text, by character share of the compact JSON, turned into tokens with the calibrated ratio of 0.408 tokens per character:

| Part | Share of JSON | Mean tokens/call |
| --- | --- | --- |
| JSON structure (keys, quotes, braces, commas) | 36.3% | 583 |
| fact `evidence` | 30.7% | 493 |
| fact `field` names | 8.0% | 128 |
| mark `evidence` | 6.5% | 104 |
| fact `status` | 4.5% | 72 |
| fact `value` | 4.2% | 68 |
| fact `unit` | 2.8% | 45 |
| mark `points` | 2.3% | 37 |
| mark `feature` | 1.9% | 30 |
| fact `confidence` | 1.5% | 24 |
| mark `status` | 1.4% | 22 |
| (thinking, not in the text) | | about 700 |

Facts per call: 18.0 (all 18 fields every time); marks per call: 5.7; UNKNOWN facts per call: 3.2.
Evidence is already short: mean **10.7 words**, maximum 28, and only 27 of 162 fact evidence strings (17%) are over 15 words.
Marks carry **very few points**: mean 1.8 points per mark, maximum 5. The weak point of the marks is too few points, not too many.
Input side: 3,597 tokens per call = the 1280 px image (about 2,185 tokens) + about 1,410 tokens of system prompt, instruction text and schema.

**Reading of the numbers.** The evidence text is only about 37% of the JSON and already short. Together, the fixed structure and the field
names are 44% and cannot shrink without changing the D-61 schema. About 30% of the output is thinking and no wording change touches it.
So prompt wording can save roughly 5 to 10% of the output, not more.

## 2. Proposals, ranked by tokens saved

Each cap was simulated on the 9 saved responses (truncate or replace in the parsed JSON, re-serialize compactly, convert characters to tokens
with the calibrated ratio). This is an **estimate from editing saved answers**: a live model rewrites its evidence instead of being cut, and
may behave a little differently. Run a live check before relying on the numbers (section 5). All proposals keep every property required, add
no union type and no min/max, so the schema stays at 0 optional and 0 union parameters.

| # | Change | Saving per call | Accuracy impact | Audit impact |
| --- | --- | --- | --- | --- |
| 1 | P5: remove the `unit` property from facts; code derives it from `field` (one lookup table in the registry) | **-103 tok (4.5%)** | None: `unit` is constant per field and was never a model judgment. | None: the unit is still on every stored fact, added by code with the field registry as its source. **Changes the D-61 schema, so needs your approval.** |
| 2 | Evidence cap at 10 words (P1b) | -112 tok (4.9%) | Over 10 words in 42% of the fact evidence strings (68 of 162); the model is likely to drop the cause, which the SME form uses. Not recommended. | Evidence becomes thin. |
| 3 | P4: remove `approaching_lanes_one` (derivable from `lanes_per_direction` and `oneway`) | -77 tok (3.3%) | **Negative.** It tracks `lanes_per_direction` in all 9 responses, and in Granite r2 (`lanes_per_direction` = 2) it was UNKNOWN. It is the cheap cross-check on the unstable lane count. | A derived value would inherit the same instability. |
| 4 | P2': UNKNOWN evidence is one fixed reason code (`not_visible`, `occluded`, `low_resolution`, `ambiguous`); UNKNOWN marks get empty points | **-79 tok (3.4%)** | None: the value is UNKNOWN either way. | Keeps a machine-readable reason, which is better than free text for grouping SME questions. A bare "not visible" text (P2, -75 tok) is weaker for the same saving. |
| 5 | P1: evidence at most 15 words | -38 tok (1.6%) | Small: only 17% of strings are cut, and the cap fits the 10.7-word mean. | Evidence stays meaningful. |
| 6 | P3: at most 6 points per mark | **0 tok** | None | None. The model never returns more than 5 points. Not worth adding. |
| 7 | Shorter instructions (exact text in section 3) | about -119 input tokens (3% of input), no output change; latency effect negligible | None found; the field list is already enforced by the schema enum. | None. |

Not simulated, and not part of the recommendation: lowering `effort` from `high` would act on the ~700 thinking tokens (the largest
single block, about 7 s per call). It may also worsen the unstable lane count, so it would need its own live comparison with your approval.

## 3. Recommended combined change

**P1 + P2' + P5 + shorter instructions. Keep `approaching_lanes_one`. Skip P3 and the 10-word cap.**

Estimated saving, simulated on the 9 responses: **-218 output tokens per call (9.5%, about 2 s)** with P5, or **-115 tokens (5.0%)** without P5,
plus about 119 input tokens. This is a modest gain; the recommendation is mainly about making the evidence cheaper to audit and the schema simpler
(one less property per fact), not about cost.

Exact text changes.

1. System prompt, unchanged (364 characters).
2. Instruction text for variant B (743 characters, was 1,125):
```
Image {w}x{h} px, north-up, {mpp} m per pixel. Work location = image centre ({cx},{cy}). Sides are N, S, E, W.
For the road nearest the work location give one fact per field (facts) and one mark per visible feature (marks):
- work_location: ROADWAY|SHOULDER|BEYOND_SHOULDER|SIDEWALK|UNKNOWN. work_side: N|S|E|W.
- lanes_per_direction: count of through lanes in one direction. sidewalk_side: N|S|E|W|BOTH|NONE|UNKNOWN. obstructions: short list or NONE.
- every other field: true|false|UNKNOWN.
- marks: points as 'x1,y1;x2,y2;...' in image pixels; one mark per lane line; road_edge_left and road_edge_right are left and right when facing north.
Evidence: at most 15 words. For UNKNOWN, evidence is exactly one of: not_visible, occluded, low_resolution, ambiguous.
Report no length or distance. Return the JSON object only.
```
(The road-edge sentence adds about 90 characters; the saving is then about 100 input tokens.)
3. Schema: remove `unit` from `facts.items.properties` and from `required` (the `unit` enum disappears with it). Add a `FIELD_UNIT` table to the
   registry (bool, count, enum or text per field). The Pydantic model fills `unit` from it. Everything else is unchanged.
4. Code, on parse: a UNKNOWN fact whose evidence is not one of the four codes is accepted (the fact is still UNKNOWN); the evidence is stored as given.
   Evidence over 15 words is stored in full and flagged in the trace; it is never cut in code, because a cut would change an audit record.

## 4. Risks

- The caps are instructions, not constraints. The strict schema cannot enforce a word count, so the model may exceed 15 words. The saving is real only if it follows.
- Truncation-based simulation under-counts the case where a shorter evidence string also shortens the thinking, and over-counts the case where the model replaces a cut sentence with a new one of the same length.
- Removing `unit` must be done in one place (schema, Pydantic model and fixtures together). The spike code and S6 are the only users so far.

## 5. Check before adopting (needs your authorization; not done)

One live run: the recommended prompt and schema on the same 3 images, 3 repetitions each = 9 calls, compared on output tokens, UNKNOWN counts, known-fact
agreement and stability with the baseline in the spike report. Together with it, 3 calls at `effort=medium` on Granite would show whether lowering the effort
moves the lane count (Granite was 2/1/1 at `high`).

## 6. What this analysis does not show

- Whether a different wording would reduce the instability of `lanes_per_direction` or the weak `lane_line`, `shoulder_edge` and `curb` marks. Those need crops and OSM cross-checks (D-80), not tuning of the first call.
- Whether tokens matter for cost. No price was used, because the plan has no cost estimates in scope.
