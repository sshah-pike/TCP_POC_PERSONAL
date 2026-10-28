# TCP golden set v0.1

Extracted automatically on 2026-10-26 from the client's approved drafts:
Colorado St (TA-10), E Second St (TA-6), Granite St (TA-33). Status: DRAFT.
Needs an SME check before it is used as a pass/fail gate.

Files
- golden_colorado.json, golden_e_second.json, golden_granite.json
- extract.py: reads the PDFs' text layer (pdfplumber) -> raw.json
- build.py: raw.json -> golden files (approach sequences, counts)

Method
- Each sign's small code label sits next to its post. Its centre is
  measured from the mean centre of the work-point labels (P.13, MH 223, ...)
  and converted to feet with the sheet scale (34 x 22 in sheet,
  1 in = 40 ft or 50 ft). Frame: sheet axes, x right, y down. Not georeferenced.
- Expected error about 5 to 15 ft.
- Not captured: taper, buffer and channelizer shapes; work-vehicle position.
  Dimension labels are kept as text with their positions.

Known limits
- E Second St draws advance signs about 40 ft apart but labels them 100 ft MIN.
  Compare against the label value, not the drawn position.
- Approach split is automatic (main road = within 60 ft across). Check by
  hand near intersections (Granite I, II, III, V).
- The Granite drawing (WPI 3178233) is not the same job as the Granite KML
  (WPI 3159540).

Compare rules
- Exact: TA, sheet count, work points per sheet, scale, advance-sign order
  per approach, sign code set.
- Tolerance: position along road 15 ft, spacing 10 ft, same side of road.
