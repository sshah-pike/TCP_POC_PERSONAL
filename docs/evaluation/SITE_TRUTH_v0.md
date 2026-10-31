# Site truth v0 (draft, owner cross-check pending)

Place these three files in `docs/evaluation/`: `SITE_TRUTH_v0.md` (this file), `site_truth_v0.json` (the master) and `site_truth_v0.csv` (generated from the JSON for `scripts/s06_accuracy_report.py --truth`). Written 2026-10-31.

## Purpose

Ground truth for scoring how well the tool reads a site: lanes per direction, divided, shoulder, one-way, parking, sidewalk, work location and road width. It is not a source for rules. It starts with the three reference sites and grows to 8 sites (2 per TA situation), which then become the permanent site-reading regression suite.

## How the truth was made, and its limits

- Read from the three reference drawings (rendered at 144 dpi) and the three spike images the models were sent. Widths use the drawing's scale (1" = 40') and a brightness profile across the road.
- Provisional: it is one reader's work and the owner will cross-check it. Two early readings were corrected: Granite's width (hand reading 49 ft included a sidewalk strip; the profile gave 39.7 ft) and Colorado's work location (the point is in a back yard, so the models' BEYOND_SHOULDER was correct).
- Truth must stay independent of the sources under test: never use OSM as truth for OSM.
- The drawings use different aerial imagery from the tool's, and some points are hidden by tree cover or shadow, so a few fields are left without truth.

## Confidence levels

| Level | Meaning | In the CSV? |
|---|---|---|
| high | two independent readings agree, or an explicit symbol or note on the drawing | yes |
| medium-high | one clear reading plus a consistent second hint | yes |
| medium | one reading with a known weakness; excluded from the CSV until verified | no |
| n/a | no truth | no |

## granite: WPI 3178233, Granite St (US-1), Westerly RI, phase I, pole P.32

- **TA situation:** TA-33
- **Point:** P32 (41.371027, -71.820353)
- **Image:** granite.jpg, sha256 starts 5560a76c, 0.448139 m per pixel, zoom 17, half-extent 212.4 m
- **Road:** US-1, runs north-south in the image (the drawing sheet is rotated 90 degrees)
- **Source:** drawing WPI 3178233 sheet 1 and the spike image, read 2026-10-31 (provisional, owner cross-check pending)
- **Posted speed:** 25 mph (medium-high): Sheet note: speed limit 25 mph as observed in the field.

| Field | Truth | Confidence | Evidence | Expected tool behaviour |
|---|---|---|---|---|
| lanes_per_direction | 2 | high | Drawing: two arrows each direction at the sheet end, dashed lane lines, yellow centre line. Aerial image shows several lanes. |  |
| divided_highway | false | high | Yellow centre line, no median on the drawing or the image. |  |
| shoulder_present | false | medium | Curb with a sidewalk strip; no shoulder visible. |  |
| oneway | false | high | 2 WAY STREET arrows in both directions. |  |
| parking_present | false | medium-high | No parked cars on the road at the work point; none drawn. |  |
| sidewalk_present | true | high | Sidewalk strips both sides; SIDEWALK CLOSED signs on the drawing. |  |
| work_location | not scored | n/a | The point sits within about 1 to 2 m of the pavement edge at an intersection corner; the drawing closes the right lane. Edge case. | UNKNOWN plus one SME question (within 5 m of the edge) |
| road_width_ft | 40 | medium | Pavement between the light strips, mid-block about 100 ft along the road from the work vehicle on the sheet; not the intersection approach. Brightness profile on the drawing image gave 39.7 ft. The first hand reading of 49 ft was wrong (it included a sidewalk strip). Tolerance plus or minus 4 ft. |  |

## second: WPI 3171586, E Second St, South Boston MA, phase I, MH 223

- **TA situation:** TA-6
- **Point:** MH 223 (42.337438, -71.026859)
- **Image:** second.jpg, sha256 starts b87f38dd, 0.441419 m per pixel, zoom 17, half-extent 212.4 m
- **Road:** E Second St, runs east-west, about 90 ft east of P St
- **Source:** drawing WPI 3171586 sheets 1 and 2 and the spike image, read 2026-10-31 (provisional, owner cross-check pending)
- **Posted speed:** 25 mph (high): Sheet note: speed limit in the city of Boston is 25 mph.

| Field | Truth | Confidence | Evidence | Expected tool behaviour |
|---|---|---|---|---|
| lanes_per_direction | 1 | medium-high | No lane lines seen; about 27 ft wide with parked cars. Holds if the street is two-way; one-way is not shown on the drawing. |  |
| divided_highway | false | high | No median. |  |
| shoulder_present | false | medium | Curb with parking; no shoulder visible. |  |
| oneway | not scored | n/a | Not shown on the drawing. Needs the SME (question S41). | UNKNOWN |
| parking_present | true | high | Parked cars along the north edge; R8-3 no-parking signs on the south side. |  |
| sidewalk_present | true | medium-high | Sidewalk strips on both sides. |  |
| work_location | not scored | n/a | The manhole sits at the south curb, under building shadow. Edge case. | UNKNOWN plus one SME question (within 5 m of the edge) |
| road_width_ft | 27.5 | medium-high | Three readings: drawing dimension 26 ft, code edge profile on the spike image 27.5 ft, first hand reading 29 ft. Tolerance plus or minus 2.5 ft. |  |

## colorado: WPI 3168057, 130 Colorado St, Mattapan MA, P13

- **TA situation:** TA-10 per the drawing; the point itself sits in a yard
- **Point:** P13 (42.275759, -71.101215)
- **Image:** colorado.jpg, sha256 starts d9eb9370, 0.441851 m per pixel, zoom 17, half-extent 212.4 m
- **Road:** none close to the point; the nearest streets in the image are diagonal and about 50 m away (estimate, plus or minus 10 m)
- **Source:** drawing WPI 3168057, the spike image, and the owner's check of the KML and drawing, 2026-10-31 (provisional)
- **Posted speed:** 25 mph (high): Sheet note: speed limit in the city of Boston is 25 mph unless posted.

| Field | Truth | Confidence | Evidence | Expected tool behaviour |
|---|---|---|---|---|
| lanes_per_direction | 1 | medium-high | Colorado St is two-way with parking. The image's nearest street may be a different street, also a narrow residential street. |  |
| divided_highway | false | high | No median. |  |
| shoulder_present | false | medium | Curb with parking; no shoulder visible. |  |
| oneway | false | high | 2 WAY STREET symbols at both ends of Colorado St on the drawing. |  |
| parking_present | true | high | Parked cars on the street; R8-3 signs on both sides on the drawing. |  |
| sidewalk_present | not scored | n/a | South side: none at the work zone (sheet note). North side appears to have one. The point is in a yard. |  |
| work_location | BEYOND_SHOULDER | high | The owner checked the drawing and the KML: the point is in a back yard. The image shows a driveway behind houses. | UNKNOWN plus a 'which road?' question (no road within 5 m) |
| road_width_ft | not scored | n/a | Colorado St measured 25 to 26 ft by code and 27 ft by hand at the visible east end of the sheet, but which street is nearest in the spike image is not established. |  |

## How it is used

- `site_truth_v0.json` is the master. `site_truth_v0.csv` is generated from it and contains only values with confidence high or medium-high. A blank cell means no truth and the field is not scored.
- `expected_tool_behavior` records what the tool should do on edge cases (for example UNKNOWN plus a question when the point is within 5 m of the road edge). A UNKNOWN is not a wrong answer, so these cases do not count as wrong-and-used.
- Run: `python scripts/s06_accuracy_report.py --results var/s06_call1_check/<profile> --truth docs/evaluation/site_truth_v0.csv`. Check the CSV against `docs/templates/S6_truth_template.csv` first; the script names any bad cell by line and exits with code 2.
- Dev data only. At 8 sites this finds failures; it cannot certify an error rate (zero wrong answers in 8 sites still leaves an upper bound of about 37%).
- Never tune a prompt or threshold on these sites and then score on the same sites as proof.

To regenerate the CSV from the JSON: keep each field whose confidence is `high` or `medium-high` and whose value is not null; write booleans as `true` or `false`; leave other cells empty.

## Sites still to add (8 sites in total, 2 per TA situation)

| Slot | TA situation | Guidance |
|---|---|---|
| fourth existing site: Exeter Ten Rod (stored demo point) | TA-1, to be confirmed | work set back from the road, beyond the shoulder |
| new | TA-33 | four-lane undivided road with the right lane closed |
| new | TA-6 | minor low-speed street with shoulder or parking lane and work at the curb |
| new | TA-10 | two-lane road with work in the lane |
| new | TA-1 | work set back from the road, beyond the shoulder |

Across the 8, include at least one point near an intersection, one under heavy tree cover and one on a curve. Label from Street View or the aerial image and record the source and its date. Use points from past job KMLs you already hold.

## Owner cross-check

- [ ] Granite: lanes (2), divided, one-way, sidewalks; confirm the shoulder and parking cells.
- [ ] E Second: confirm lanes (1) and the width (27.5 ft); decide whether one-way can be filled from the SME (question S41).
- [ ] Colorado: confirm the point is in a yard in both the KML and the drawing, and the width of the nearest street if you know it.
- [ ] Anything you change: edit the JSON, bump the version to v1 and note the reason; do not edit values in place.

## Changelog

- v0, 2026-10-31: first draft, three reference sites.
