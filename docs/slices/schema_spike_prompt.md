# Schema spike: test the AI output format before building (slice S0)

Paste the block below into Claude Code in VS Code. It changes no pipeline code. It writes only to `spikes/schema_spike/`.

```
You are working in the TCP repository. Create branch tcp-mvp/s00-schema-spike
from tcp-mvp/base (after S0a is merged). The current call 1 schema is in
src/tcp_planner/ai/vision_provider.py; the Foundry request code is in
src/tcp_planner/ai/foundry_provider.py; the three KMLs are in
docs/references/kml/.
Do NOT change any pipeline code. Write only under spikes/schema_spike/.

GOAL
Decide the output format for AI call 1 before it is built. JSON only
Compare two variants on the deployed Claude model in Azure Foundry, using the same
images and prompt text, and report which is accepted, valid and accurate.

LIVE CALLS
This spike is the one allowed exception to the no-live-calls rule. Run
only when TCP_LIVE=1. Budget: 3 sites x 2 variants x 3 repetitions = 18 AI
calls at most. Reuse existing wide images from earlier run folders for the
three KMLs if present; otherwise fetch each once from Azure Maps and store
them under spikes/schema_spike/inputs/. Stop and report if the budget would
be exceeded.

SITES
 - 1A8G8FM WPI 3159540 GRANITE1.kml (first point)
 - 1A8J1KB WPI 3171586 - E Second Street.kml (MH 223)
 - WPI 3168057 130 COLORADO.kml (P13)

FIELDS (the call 1 field list, from plan Section 4B)
work_location, work_side, lanes_per_direction, oneway, shoulder_present,
divided_highway, median_work, bicycle_lane_present, sidewalk_present,
sidewalk_side, parking_present, bus_stop_present, driveway_present,
crosswalk_present, intersection_in_view, grade_crossing_present,
obstructions, approaching_lanes_one
plus image positions (pixel coordinates) for: left road edge, right road
edge, each lane line, shoulder edge, work point, curb.
The model must never return a length in feet.

VARIANT A - current style
One property per field, each nullable ("type": ["string","null"] or
anyOf), each wrapped as {value, confidence, evidence}, sent with strict
structured output (output_config.format). First run it with the repo's
current call 1 schema unchanged, then with all fields above added.
Record whether the request is accepted. On error, save the full error text
verbatim (this is the Foundry error we need).

VARIANT B - flat facts list, strict
Send this schema with output_config.format, strict:
{
 "type":"object","additionalProperties":false,
 "required":["facts","marks"],
 "properties":{
  "facts":{"type":"array","items":{
    "type":"object","additionalProperties":false,
    "required":["field","value","unit","status","confidence","evidence"],
    "properties":{
     "field":{"type":"string","enum":[<the field names above>]},
     "value":{"type":"string"},
     "unit":{"type":"string","enum":["bool","count","enum","text","none"]},
     "status":{"type":"string","enum":["RESOLVED","UNKNOWN","CONFLICT"]},
     "confidence":{"type":"number"},
     "evidence":{"type":"string"}}}},
  "marks":{"type":"array","items":{
    "type":"object","additionalProperties":false,
    "required":["feature","points","status","evidence"],
    "properties":{
     "feature":{"type":"string","enum":["road_edge_left","road_edge_right",
       "lane_line","shoulder_edge","work_point","curb"]},
     "points":{"type":"string"},
     "status":{"type":"string","enum":["RESOLVED","UNKNOWN"]},
     "evidence":{"type":"string"}}}}}}
"points" is "x1,y1;x2,y2;..." in image pixels. No minimum/maximum
constraints. Parse in code with Pydantic; compare enum values ignoring
case; treat a missing field as UNKNOWN.

MEASURE, per call
 - accepted (yes/no) and full error text if not
 - parse success and schema-valid (after Pydantic) yes/no
 - number of expected fields returned; number UNKNOWN
 - input tokens, output tokens, latency (first call and repeat, to see
   grammar compile time)
 - count of optional params and union-type params in the schema, computed
   by a script (Anthropic limits: 24 optional, 16 union-type, 20 strict
   tools per request)
 - agreement with these known facts:
     Colorado: two-lane, undivided, sidewalk absent on the south side
     E Second St: undivided, parking present
     Granite: US-1, multi-lane
   and agreement between the 3 repetitions (stability)

OUTPUT
spikes/schema_spike/REPORT.md with one table per site and one summary table
(variant x metric), the raw requests and responses in raw/, and a
recommendation: which output format, with token use and latency for
each. Do not merge
anything into the pipeline. Stop after the report.
```
