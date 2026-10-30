# Open items

Last updated 2026-10-30. Source: docs/decisions/OWNER_DECISIONS_2026-10-30.md.

## SME questions

| # | Question | Status |
| --- | --- | --- |
| 1 to 15 | The 15 questions emailed to the SME on 2026-10-30. The question texts are in the email, not in the repo; the owner adds one row each here | sent, awaiting reply |
| 16 | Granite: does the KML (WPI 3159540, P32 to P28) match the drawing (WPI 3178233, P.32 to P.42)? The granite-check report says neighbouring stretches sharing P32, medium confidence | sent, awaiting reply |
| 17 | Traffic volume for each golden job (Colorado, E Second St, Granite). D-59 mandatory start field; no source fills it | sent, awaiting reply |

## Client inputs

| # | Input | Needed by | Status |
| --- | --- | --- | --- |
| 1 | Which MUTCD revision applies (rules use December 2023 only until answered) | S4b onward | open |
| 2 | Who holds the approver role | S10, S11 | open |
| 3 | KML for WPI 3178233 (requested from the SME) | S13 | requested |
| 4 | A TA-1 reference drawing (plan open question 9) | S13 | open |
| 5 | Which MassDOT and RIDOT documents apply (plan open question 17) | later | open |
| 6 | CAD blocks for devices (S5 uses placeholder symbols) | S12 | open |
| 7 | Traffic volumes per job | S13 | open |

## Owner tasks

| # | Task | When | Status |
| --- | --- | --- | --- |
| 1 | S6 9-call live check on gpt-5.6-sol, then on claude-opus-5-5; the comparison goes to docs/reports/S6_model_comparison.md | Before any recording | open |
| 2 | Permission for the MassGIS (first) and RIGIS discovery calls: read-only, limited, three sites named | S6 session 2 | open |
| 3 | Colorado recording with TCP_LIVE=1 (calls 1 and 2 together) | After S7 merges | open |
| 4 | Remaining recordings with TCP_LIVE=1 | After S9 | open |

## Plan open questions

Plan v4 open questions 15 (approver role holder), 17 (MassDOT and RIDOT documents) and 18 (Section 4B check) are marked in the plan. The holder of the approver role and the document list stay open as client inputs above.

Questions 21 and 24 exist only as items of the plan's verification prompt (Section 18: deployed model image limit; geometry sources), not as open questions. They overlap S6 plan Q19 and Q21 (deployment facts, source access) and stay open there: the deployment facts are partly answered by D-106, the source access facts are covered by owner task 2.
