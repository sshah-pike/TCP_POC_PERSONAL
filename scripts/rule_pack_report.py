"""Write docs/reports/S4_rule_pack_review.md from rule pack v1, for SME and owner sign-off (S4, updated in S4b).

Run after any pack change: python scripts/rule_pack_report.py
tests/unit/rules/test_rule_pack_report.py fails when the committed report no longer matches the pack.
The tables are generated from the pack; the decisions, proposals and external inputs below are the owner's decisions
recorded during S4 and are kept here so the report is rebuilt the same way every time.
"""
import json, os, sys
from tcp_planner.rules.rule_pack_models import All, Any_, Cmp, Evidence, Not
from tcp_planner.rules.rule_pack_store import JsonRulePackStore
from tcp_planner.rules.rule_pack_validator import validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "reports", "S4_rule_pack_review.md")
POC = os.path.join(ROOT, "rule_pack", "APPROVED_TWO_LANE_POC_RULE_PACK.json")
EDITION_LINE = ("Source edition: MUTCD Chapter 6, December 2023 revision (file sha256 recorded). "
                "The edition the client applies is not yet confirmed.")

# source_ref count after each S4 commit that changed the pack (commit 3's message said 57 in error; 48 is right)
SOURCE_REF_COUNTS = [("Commit 3, base tables", "e6ad7d5", 48),
                     ("Commit 4, TA files (+4 Sect. 6B.04 paras 03-06, +1 Sect. 6P.01 para 07, +59 TA files)", "e36225b", 112),
                     ("Commits 5 to 8 (no pack records added)", "43f5f46", 112),
                     ("S4b pack round (sign sizes, note-only devices, anchors, 6G.10 and 6I.02, 6N.11 split)", "tcp-mvp/s04b-pack-round", None)]

DECISIONS = [
    ("Scope", "Rules come from the MUTCD only. The Colorado, E Second St and Granite drafts are comparison material, not rule sources. The client, jurisdiction and deviation layers stay in the schema, empty."),
    ("Approval", "All sourced values are usable for now. An SME approval step comes in a later slice. Nothing is approved by default; unsourced values stay SOURCE_REVIEW_REQUIRED or UNKNOWN."),
    ("Q-A, figures", "Values read only from a figure drawing are FIGURE_TRANSCRIPTION evidence tied to a committed render. TA-33's 500 ft and 100 ft (optional) stay SOURCE_REVIEW_REQUIRED."),
    ("Q-B, Sect. 6N.11", "Encoded exactly as the source. The undivided four-lane reading stays a proposed interpretation (SOURCE_REVIEW_REQUIRED); an undivided TA-33 site routes to an SME question. Divided roads match as encoded."),
    ("Q-C, shoulder taper", "Both values stored as printed. Table 6B-3 '0.33 L' computes; Sect. 6B.08 para 10 'approximately 1/3 L' is cited Guidance."),
    ("Shifting taper", "Table 6B-3 '0.5 L' computes; Sect. 6B.08 para 08 'approximately 1/2 L' is cited Guidance."),
    ("Sect. 6B.04 paras 03-06", "Loaded as Guidance, cited only, each marked as overlapping Table 6B-1 so nothing is applied twice."),
    ("Extra sourced values", "Approximately 20 ft device spacing in one-lane two-way and downstream tapers (6B.08 paras 12, 14), the 6K.01 para 05 2 x speed extension and the 6N.08 15 ft median rule are loaded."),
    ("TA-10 road form", "'Not multi-lane' is encoded as lanes_per_direction < 2 from Sect. 6N.11 para 02 (see the reasoning below; the SME may overrule)."),
    ("W16-2P", "Optional on both TA-10 approaches (owner checked the 6P-10 render; the figure labels it '(optional)' on one approach only)."),
    ("TA-6", "Stays UNDETERMINED until the low-speed cutoff and 'minor road' have sources."),
    ("Note-only signs", "ROAD NARROWS, SHOULDER WORK and BE PREPARED TO STOP have no device records; they stay as note actions."),
    ("TA-33 'stationary'", "The word 'Stationary' in the TA-33 title is not encoded as a condition (it would make duration a required fact)."),
    ("Registry", "The four new registry fields and the duration split are kept; the differences from plan section 4B are listed below as proposals."),
    ("schema_version", "Carried by rule_pack/pack.json and every part file; rows inherit it (also recorded in CLAUDE.md)."),
    ("RI double fines (history)", "Before the scope change the owner placed RI double fines in the jurisdiction layer (plan section 10 called it a jurisdiction module; the slice spec and D-51 listed it under the client layer). The scope change then removed it from v1."),
]

EXTERNAL_INPUTS = [
    ("R-LOW-SPEED-CUTOFF", "Upper speed for 'low speed' (Sect. 6N.07 para 04; TA-6 notes 2 and 4). Blocks TA-6 and the 9 ft option."),
    ("E-TA6-MINOR-ROAD", "Definition of 'minor road' (TA-6 note 2). Blocks TA-6."),
    ("R-TA10-SHORT-ZONE", "Length of a 'short TTC zone' for the single-flagger option (TA-10 note 2)."),
    ("R-6N11-TA33-UNDIVIDED-OTHER / E-TA33-FORM-UNDIVIDED-OTHER", "Whether TA-33 may be used on an undivided road with three or more lanes each way, or with a left-lane or interior-lane closure (Sect. 6N.11 para 06 covers only the four-lane, right-lane case; S4b stage E)."),
    ("R-6B4-W-MERGING, R-6B4-W-SHIFTING, R-6B4-W-SHOULDER", "Which measured width is W (Table 6B-4) for each taper type (S4b stage C)."),
    ("R-SIGN-NAMING-W4-2-SIDE", "Whether W4-2R and W4-2L are the codes the drafts and the sign supplier use, and W4-2L is the mirror image (S4b stage A)."),
    ("R-SIGN-SIZE-M4-9AL, R-SIGN-SIZE-R9-3BR", "Which sign each client code is, and its size (not in the MUTCD tables; S4b stage A)."),
    ("R-TA33-FIG-G20-2-500FT, R-TA33-FIG-DOWNSTREAM-100FT", "Confirmation of the two numbers read only from Figure 6P-33."),
    ("R-TMA-SPEED-THRESHOLD", "Whether a TMA is ever suggested by speed, and at what speed (open question 6)."),
    ("R-DEFAULT-WORK-VEHICLE-WIDTH", "Assumed work-vehicle width when none is visible (open question 7)."),
    ("R-DEFAULT-WORK-LENGTH-*", "Assumed work-space length per work type: pole, manhole, excavation, trench (open question 2)."),
    ("Edition", "The MUTCD edition the client applies (this pack cites the December 2023 file)."),
]

REGISTRY_PROPOSALS = [
    ("work_location", "New field (BEYOND_SHOULDER, ON_SHOULDER_OR_ENCROACHING, IN_LANE). Plan section 6 (D-60) routes on it but section 4B does not list it."),
    ("offset_width_ft", "New field: Table 6B-4 'W = width of offset in feet', computed by code per taper."),
    ("distance_behind_curb_in", "New field: TA-1 note 3 'more than 24 inches behind the curb'. Section 4B has only distance_from_edge_ft."),
    ("low_speed_road", "New field, computed from posted_speed_mph and R-LOW-SPEED-CUTOFF; UNKNOWN while the cutoff has no source."),
    ("duration", "Section 4B offers 'Short-duration or mobile' as one value; the pack splits SHORT_DURATION and MOBILE because TA-1 note 4, TA-6 note 10 and TA-10 note 3 treat them separately."),
    ("traffic_control_method", "Enum values FLAGGER and POLICE_DETAIL (D-68); section 4B names them in prose only."),
    ("closed_lane_side", "Enum values RIGHT and MEDIAN_SIDE for section 4B's 'Right lane or median-side lane'."),
]

PROPOSALS = [
    ("D-51 (client practice layer, Proposed)",
     "Proposal: mark D-51 as withdrawn for the MVP. The owner's S4 scope change makes the drafts comparison material only. The client layer stays in the schema, empty. If it is revived, each entry must cite its drawing and wait for SME confirmation, as D-51 already says."),
    ("D-68 (traffic control method)",
     "No change to the decision. The pack encodes it as R-TA10-METHOD-FLAGGER: code sets FLAGGER when TA-10 is chosen. Proposal: add to D-68 that the police variant has no rule-pack source in v1. The drafts print POLICE OFFICER AHEAD as 'W20-8' (open question 13); the SME review action that switches to police needs its own source or stays an SME exception."),
    ("Open question 15 (who holds the approver role)",
     "Proposal: keep the default (a configured list of approver users) and add that approvals are recorded outside the pack as {record id, pack hash, approver, time}. The pack itself stays DRAFT, so changing a value changes the hash and voids its approvals."),
    ("Open question 17 (RIDOT and MassDOT documents)",
     "The default 'MUTCD plus client layer' no longer holds. Proposal: change the default to 'MUTCD only'. The jurisdiction layer stays empty until a state document is supplied; RI double fines (Sect. 6G.08) come back only from such a document."),
    ("Open question 18 (section 4B complete)",
     "Proposal: the SME reviews the registry differences listed above together with this question."),
    ("S8 client modules",
     "S8 lists add-on modules (no parking, side streets, pedestrian or sidewalk, RI double fines, police detail, arrow board) and 'buffers from the client layer or Table 6B-2'. Proposal: keep only what the MUTCD sources: side roads (TA-33 note 2, Standard, R-TA33-N2), arrow board (TA-33 note 7, R-TA33-N7; optional elsewhere) and buffers from Table 6B-2 (R-6B06-BUFFER-OPTION). Drop no parking, RI double fines and police detail from S8, or make them SME-added items. A pedestrian module needs Sect. 6G.10 loaded first (cited in the plan, not in v1). Also amend S8's acceptance: golden comparisons will differ where the drafts follow client practice (Colorado's 100 ft buffer against 155 ft from Table 6B-2, POLICE OFFICER AHEAD), so the S13 comparator should list these as known differences."),
]

PLAN_DIFFERENCES = [
    ("D-81 and the S4 spec", "Pack v1 'replaces' the POC pack. Per the owner it is added alongside; the pipeline still reads the POC pack until a separate, approved switch-over."),
    ("POC pack edition", None),
    ("D-60, TA-33", "D-60 allows TA-33 on 'undivided, 2+ lanes each way'. Sect. 6N.11 para 06 says right-hand lane closed on four-lane roads. See the amendment proposal."),
    ("Plan section 10, note 11", "Plan section 10 places the drafts' 11 ft lane-width note in a project-reference layer; the S4 spec put it in the client layer. Both are moot after the scope change."),
]


def _md(s): return str(s).replace("|", "\\|").replace("\n", " ")


def expr_text(e):
    if e is None: return ""
    if isinstance(e, Cmp):
        v = e.value if not isinstance(e.value, list) else "[" + ", ".join(map(str, e.value)) + "]"
        return f"{e.field} {e.op} {v}"
    if isinstance(e, Not): return f"NOT ({expr_text(e.not_)})"
    parts = [expr_text(x) for x in (e.all if isinstance(e, All) else e.any)]
    return "(" + (" AND " if isinstance(e, All) else " OR ").join(parts) + ")"


def _where(r):
    bits = [f"Sect. {r.section}"]
    if r.paragraph: bits.append(f"para {r.paragraph}")
    if r.table: bits.append(f"Table {r.table}")
    if r.figure: bits.append(f"Fig. {r.figure}")
    if r.note: bits.append(f"note {r.note}")
    return ", ".join(bits)


def _cites(pack, rec):
    """'quote' cells and 'where' cells for a record's source refs."""
    refs = [pack.get(s) for s in rec.source_ref_ids]
    quotes = "<br>".join(f"\"{_md(r.quote)}\"" if r.evidence == Evidence.QUOTE else f"[figure transcription] {_md(r.transcription)}" for r in refs)
    where = "<br>".join(f"{_where(r)}, p. {r.page_printed} ({r.strength.value.title()})" for r in refs)
    return quotes or "(none)", where or "(none)"


def _value(rec, table):
    if table == "table_row":
        return ", ".join(f"{k} = {v}" for k, v in rec.key.items()) + " -> " + ", ".join(f"{k} = {v}" for k, v in rec.values.items())
    if table == "formula":
        cases = "; ".join((f"if {expr_text(c.when)}: " if c.when else "") + c.expression for c in rec.cases)
        return f"{cases} [{rec.result_unit}, {rec.qualifier}, {rec.role}]"
    if table == "eligibility_condition":
        return (expr_text(rec.expr) or "(no expression)") + (f" [OR group {rec.any_group}]" if rec.any_group else "")
    v = []
    if rec.value is not None: v.append(f"{rec.value}" + (f" to {rec.value_max}" if rec.value_max is not None else "") + f" {rec.unit}" + (f" {rec.qualifier}" if rec.qualifier else ""))
    if rec.condition is not None: v.append(f"when {expr_text(rec.condition)}")
    if rec.action: v.append(f"-> {rec.action}")
    if rec.role == "CITED_ONLY": v.append(f"CITED ONLY (overlaps {', '.join(rec.overlaps)})")
    return "; ".join(v) or "(text rule)"


def _table(pack, rows, table):
    out = ["| Record | Value | Quote | Section, page (strength) |", "| --- | --- | --- | --- |"]
    for rec in rows:
        q, w = _cites(pack, rec)
        out.append(f"| {rec.id} | {_md(_value(rec, table))} | {q} | {w} |")
    return out


def build_report(pack):
    rep = validate(pack)
    with open(POC, encoding="utf-8") as f: poc = json.load(f)["rule_pack"]["source"]
    sd = pack.records("source_document")[0]
    fig_ids = {r.id for r in pack.records("source_ref") if r.evidence == Evidence.FIGURE_TRANSCRIPTION}
    L = ["# S4 rule pack v1: review report", "", EDITION_LINE, "",
         "*For the SME and the owner. Generated by `scripts/rule_pack_report.py` from `rule_pack/`; do not edit by hand.*", "",
         "## Pack", "",
         f"- Pack `{pack.id}` version `{pack.version}`, status `{pack.manifest.status}`, hash `{pack.hash}`.",
         f"- Source: {sd.title}, {sd.edition}, {sd.revision}. File `{sd.artifact.uri}`, sha256 `{sd.artifact.sha256}`, {sd.artifact.size} bytes.",
         f"- The POC pack (`rule_pack/APPROVED_TWO_LANE_POC_RULE_PACK.json`, unchanged) cites a different edition text: \"{poc['document']}\", {poc['date']}. Pack v1 cites only the December 2023 file in the repo.",
         f"- TAs: {', '.join(pack.manifest.ta_scope)}. Any other TA is NO_TA_MATCH. Only the federal layer has records.",
         ""]
    counts = {t: len(pack.records(t)) for t in ("source_ref", "registry_field", "table_def", "table_row", "formula", "rule",
                                                 "eligibility_condition", "device", "ta_device_use", "deviation")}
    L += ["| Table | Records |", "| --- | --- |"] + [f"| {t} | {n} |" for t, n in counts.items()] + [""]
    L += ["### source_ref count by commit", "", "| Commit | Hash | source_refs |", "| --- | --- | --- |"]
    L += [f"| {c} | {h} | {n if n is not None else counts['source_ref']} |" for c, h, n in SOURCE_REF_COUNTS] + [""]
    L += ["## How to read this report", "",
          "- **Status.** SOURCED: the value is in the cited text. SOURCE_REVIEW_REQUIRED: the source names the item but gives no usable value. UNKNOWN: no source at all. Unsourced records carry no value and an SME question.",
          "- **Evidence.** A quote is verbatim text from the cited page, checked by test against a snapshot of that page. A figure transcription is what a figure drawing shows, read from the committed render (the figure labels have no text layer).",
          "- **Cited only.** Kept for the record and never applied; the record named in 'overlaps' applies instead.",
          "- **Strength** is the MUTCD heading: Standard, Guidance, Option, Support. Sect. 6P.01 para 02: figure content other than the notes is generally Guidance.", ""]
    L += ["## Owner decisions recorded in S4", "", "| Item | Decision |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in DECISIONS] + [""]

    L += ["## Every value, with quote and page", "", "### Tables 6B-1, 6B-2, 6B-3 and sign sizes (Tables 6G-1, 6H-1, 6I-1)", ""]
    L += _table(pack, pack.records("table_row"), "table_row") + [""]
    L += ["### Formulas (Tables 6B-3, 6B-4; Sect. 6B.08, 6K.01)", ""] + _table(pack, pack.records("formula"), "formula") + [""]
    shared = [r for r in pack.records("rule") if r.ta_id is None and r.status.value == "SOURCED"]
    L += ["### Shared rules", ""] + _table(pack, shared, "rule") + [""]
    for ta in pack.records("ta"):
        L += [f"### {ta.id}: {ta.title} (Figure {ta.figure})", "", "Eligibility conditions:", ""]
        L += _table(pack, [c for c in pack.records("eligibility_condition") if c.ta_id == ta.id], "eligibility_condition") + [""]
        L += ["Rules (figure notes and figure-derived rules):", ""]
        L += _table(pack, [r for r in pack.records("rule") if r.ta_id == ta.id and r.status.value == "SOURCED"], "rule") + [""]
        L += ["Device sequence (from the figure):", "", "| Device | Approach | Sequence | Spacing | Required |", "| --- | --- | --- | --- | --- |"]
        for u in [u for u in pack.records("ta_device_use") if u.ta_id == ta.id]:
            L.append(f"| {pack.get(u.device_id).code} | {_md(u.approach)} | {u.sequence} | {u.spacing_dimension or ''} | {'yes' if u.required else 'no'} |")
        L.append("")

    L += ["## Figure-only values", "",
          "Read from the figure drawings, which have no text layer for their labels. Each render is committed with its sha256.", "",
          "| Source ref | Figure, page | Render file | Reading | Used by |", "| --- | --- | --- | --- | --- |"]
    for r in pack.records("source_ref"):
        if r.id in fig_ids:
            users = [x.id for t in ("rule", "ta_device_use", "eligibility_condition") for x in pack.records(t) if r.id in x.source_ref_ids]
            L.append(f"| {r.id} | {r.figure}, p. {r.page_printed} | `{r.figure_render.uri}` | {_md(r.transcription)} | {', '.join(users)} |")
    L += [""]

    L += ["## Unsourced items and their SME questions", "", "| Record | Status | SME question |", "| --- | --- | --- |"]
    L += [f"| {u['id']} | {u['status']} | {_md(u['question'])} |" for u in rep.unsourced] + [""]
    L += ["## External inputs needed", "", "| Item | What is needed |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in EXTERNAL_INPUTS] + [""]

    L += ["## Interpretations and readings for the SME to check", "",
          "| Record | Status | Reading |", "| --- | --- | --- |"]
    L += [f"| {i['id']} | {i['status']} | {_md(i['interpretation'])} |" for i in rep.interpretations] + [""]
    L += ["**TA-10 'not multi-lane' (E-TA10-NOT-MULTI-LANE).** TA-10 is a two-lane road with one lane each way. The pack encodes this as `lanes_per_direction < 2`. The number 2 comes from Sect. 6N.11 para 02, which defines a multi-lane highway as one with \"two or more lanes of moving motor vehicle traffic in one direction\"; a road that is not multi-lane therefore has fewer than two lanes in each direction. With `oneway = false` (two-way traffic alternating through one lane, figure title) and `divided_highway = false` (Sect. 6N.09, two-lane highway), this matches the figure. It is treated as a literal reading of para 02, not an interpretation. If the SME disagrees, the condition becomes SOURCE_REVIEW_REQUIRED and every TA-10 site goes to an SME question.", ""]

    L += ["## Proposed amendment to D-60 (Sect. 6N.11)", "",
          "Current D-60 text: \"TA-33 is one OR'd rule covering divided roads and undivided roads with two or more lanes each way (6N.11).\"", "",
          "Source, Sect. 6N.11 para 06, p. 847 (Option): \"When the right-hand lane is closed, TTC similar to that shown in Figure 6P-33 may be used for undivided or divided four-lane roads.\"", "",
          "Proposed D-60 text: \"TA-33 is one OR'd rule: (a) a divided highway with two or more lanes in the closed direction (figure title; 6N.11 paras 02 and 03), or (b) an undivided four-lane road with the right-hand lane closed (6N.11 para 06). Branch (b) is a proposed reading of 'four-lane' (two lanes each way) and stays SOURCE_REVIEW_REQUIRED until the SME confirms it; until then an undivided site goes to an SME question. A left-lane (median-side) closure on an undivided road, or an undivided road with more than two lanes each way, is not covered by 6N.11 para 06.\"", "",
          "Not edited in the plan; for the owner to decide.", "",
          "**Superseded (S4b).** Owner decision D-91 (2026-10-30) and S4b stage E source branch (b) for the four-lane, right-lane case; broader undivided cases stay SOURCE_REVIEW_REQUIRED. See 'S4b changes'.", ""]

    L += ["## Differences from plan section 4B (proposals)", "", "| Field | Proposal |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in REGISTRY_PROPOSALS] + [""]
    L += ["## Proposals for the owner (not edited)", ""]
    for a, b in PROPOSALS: L += [f"**{a}.** {b}", ""]
    L += ["## Where the repo or plan differs", "", "| Item | Note |", "| --- | --- |"]
    for a, b in PLAN_DIFFERENCES:
        b = b or f"The POC pack header cites \"{poc['document']}\", {poc['date']}; v1 cites the December 2023 file. The POC header is unchanged."
        L.append(f"| {a} | {_md(b)} |")
    L.append("")
    L += s4b_section(pack, rep)
    return "\n".join(L)


# ---------- S4b pack round (owner decisions D-90, D-91, D-99; 2026-10-30) ----------
S4B_STAGES = [
    ("A", "Sign sizes: Tables 6G-1 (p. 796), 6H-1 (pp. 803-804) and 6I-1 (p. 811) as quoted rows in base/sign_sizes.json, one row per sign, inches, width x height; '—' is null. The tables are made binding by Sect. 6G.02 para 02, 6H.01 para 03 and 6I.01 para 07 (Standard). Read only through rule_pack_effective.sign_size(): a null column is a gap with an SME question, never 0 and never another column."),
    ("B", "Device rows for the note-only signs W21-5, W3-4, W5-1, W20-5L and W4-2L (S5 plan Q4 option B). No model, validator or ta_device_use change; the note rules keep their actions (USE_LEFT_LANE_SIGNS, ROAD_NARROWS_SIGN_MAY_BE_ADDED, BE_PREPARED_TO_STOP_MAY_BE_ADDED, W20-1_MAY_BE_REPLACED). No note rule has a field that can name a device, so none was filled or added."),
    ("C", "Placement anchors as owner-accepted readings of the figure renders (R-TAxx-ANCHOR-A, R-6B1-ABC-CONSECUTIVE). The TA-1 and TA-6 opposite-approach readings are marked 'Owner-accepted, SME confirmation pending'. W per taper type (merging, shifting, shoulder) is SOURCE_REVIEW_REQUIRED; W is not set."),
    ("D", "Add-ons (D-90): Sect. 6G.10 (sidewalk closed; 6G.08 not loaded) and Sect. 6I.02 (M4-9 family, M4-8a; M4-8P, M4-8bP, M4-10 not loaded) as cited rules in base/sidewalk_detour.json, optional per zone. No layout numbers: the MUTCD gives none."),
    ("E", "Sect. 6N.11 split (D-91): undivided, two lanes each way, right lane closed is SOURCED from paras 02 and 06 (owner-confirmed reading); broader undivided cases stay SOURCE_REVIEW_REQUIRED."),
]
S4B_REMOVED = [
    ("R-6N11-TA33-UNDIVIDED-FOUR-LANE", "base/rules.json", "Replaced by R-6N11-TA33-UNDIVIDED-FOUR-LANE-RIGHT (SOURCED) and R-6N11-TA33-UNDIVIDED-OTHER (SOURCE_REVIEW_REQUIRED)", "docs/plans/S7_plan.md lines 43, 201, 383; docs/plans/S16_plan.md line 234"),
    ("E-TA33-FORM-UNDIVIDED-6N11", "ta/TA-33.json", "Replaced by E-TA33-FORM-UNDIVIDED-FOUR-LANE-RIGHT (SOURCED) and E-TA33-FORM-UNDIVIDED-OTHER (SOURCE_REVIEW_REQUIRED)", "docs/plans/S7_plan.md lines 43, 201, 383; docs/plans/S16_plan.md line 234"),
]
S4B_CHANGED = [
    ("SR-6P33-FIG-SIGNS", "Transcription corrected (owner checked the 400 dpi crops). Superseded reading: \"a W4-2R Lane Ends sign at dimension A from the upstream end of the shoulder taper\". Current: A runs from the upstream end of the merging taper (start of L); the shoulder taper begins inside A and ends where the merging taper begins. SourceRef has no note field, so the old wording is kept here."),
    ("R-TA1-ANCHOR-A, R-TA6-ANCHOR-A-OPPOSITE", "Rule text ends 'Owner-accepted, SME confirmation pending.'"),
    ("Manifest", "version 1.0.0 -> 1.1.0; status stays DRAFT. Two part files added: base/sign_sizes.json, base/sidewalk_detour.json."),
    ("Registry", "One field added: addon_sidewalk_closed (boolean, ASKED_IF_NEEDED, SME_FORM). It is the S11 add-on toggle ADDON:sidewalk_closed; S11 must map the toggle onto this fact and not invent a second name. No other registry change (closed_lane_side unchanged)."),
]
S4B_SUPERSEDED_S4 = [
    ("Q-B, Sect. 6N.11", "Superseded by D-91 and stage E."),
    ("Note-only signs", "Superseded by stage B: the five signs have device records; the note actions are unchanged."),
    ("S8 client modules proposal ('a pedestrian module needs Sect. 6G.10 loaded first')", "6G.10 is loaded (stage D)."),
]
S4B_FOLLOW_UPS = [
    ("a", "Pack store", "Keep sealed versions side by side (for example rule_pack/versions/<version>/) so a run replays against its recorded pack version without git. Before the first recording against pack v1. Today the store holds one version: after 1.1.0, load('1.0.0') raises RULE_PACK_VERSION_MISSING; 1.0.0 is in git at 9649481, and no run is recorded against it (the pipeline still reads the POC pack)."),
    ("b", "Add-on signs (S5, S8)", "R9-9, R9-10, R9-11, R9-11a, M4-9, M4-9a, M4-9b, M4-9c and M4-8a have size rows but no device rows, and several have no catalog entry or symbol (see 'Size rows and the device catalog'). They need catalog entries, symbols and device rows before S8 places them."),
    ("c", "closed_lane_side (S7)", "An unknown or unstated side must never default to RIGHT. The enum has only RIGHT and MEDIAN_SIDE, so a left or interior closure on an undivided road cannot be stated exactly; it routes to E-TA33-FORM-UNDIVIDED-OTHER only when reported as MEDIAN_SIDE. No registry change in S4b (owner decision)."),
    ("d", "S8 plan", "docs/plans/S8_plan.md lines 208, 219 and 221 (lines 199, 210 and 212 in the earlier copy in C:/work/plans-backup) describe the TA-33 anchor as 'A from the upstream end of the shoulder taper' / 'of the last taper' and list 'TA-33 A when there is no shoulder taper' as undefined. Superseded by the corrected reading: A always ends at the upstream end of the merging taper (R-TA33-ANCHOR-A)."),
    ("e", "S7 and S16 plans", "They cite the removed ids E-TA33-FORM-UNDIVIDED-6N11 and R-6N11-TA33-UNDIVIDED-FOUR-LANE (docs/plans/S7_plan.md lines 43, 201, 383; docs/plans/S16_plan.md line 234). Use the replacement ids above."),
]
CATALOG = os.path.join(ROOT, "assets", "symbols", "device_catalog.json")


def s4b_section(pack, rep):
    with open(CATALOG, encoding="utf-8") as f: catalog = {e["device_id"]: e for e in json.load(f)["entries"]}
    size_defs = {d.id: d.table for d in pack.records("table_def") if set(d.key_fields) == {"sign"}}
    size_rows = [r for r in pack.records("table_row") if r.table_def_id in size_defs]
    L = ["## S4b changes", "",
         f"Pack version `{pack.version}`, status `{pack.manifest.status}`, hash `{pack.hash}`. "
         f"{len(rep.unsourced)} unsourced records, {len(rep.interpretations)} interpretations, "
         f"{len(pack.records('registry_field'))} registry fields.", "",
         "| Stage | What changed |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in S4B_STAGES] + [""]
    L += ["### Records removed or replaced", "", "| Record | Part | Replaced by | Cited in |", "| --- | --- | --- | --- |"]
    L += [f"| {a} | {b} | {_md(c)} | {d} |" for a, b, c, d in S4B_REMOVED] + [""]
    L += ["### Other changed records", "", "| Record | Change |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in S4B_CHANGED] + [""]
    L += ["### S4 decisions above that S4b supersedes", "", "| S4 item | Now |", "| --- | --- |"]
    L += [f"| {a} | {_md(b)} |" for a, b in S4B_SUPERSEDED_S4] + [""]
    L += ["### Flags written into a device `name`", "",
          "`Device` has no interpretation or note field (no model change in S4b), so these flags are in the name text.", "",
          "| Device | Name |", "| --- | --- |"]
    L += [f"| {d.id} | {_md(d.name)} |" for d in pack.records("device") if "INTERPRETATION" in d.name or "prints no code" in d.name] + [""]
    L += ["### Size rows and the device catalog", "",
          "Every size row whose sign code has no catalog entry with the same id. Where a catalog entry exists, its sizes equal the row (checked when the rows were built).", "",
          "| Size row | Sign | Catalog |", "| --- | --- | --- |"]
    for r in size_rows:
        sign = r.key["sign"]
        if sign in catalog: continue
        near = sorted(i for i in catalog if i.startswith(sign) and i[len(sign):] in ("L", "R", "-L", "-R"))
        L.append(f"| {r.id} | {sign} | " + (f"side variants only: {', '.join(near)}" if near else "no entry") + " |")
    L += ["", "### Add-on rules: gate and action kind", "",
          "None fires on its own: each needs its gate fact true; an unset fact evaluates to None (tests/unit/rules/test_rule_pack_addons.py). "
          "No add-on sign has a device row or a ta_device_use row, so none is required or placed by a TA.", "",
          "| Rule | Strength | Gate | Action | Action kind |", "| --- | --- | --- | --- | --- |"]
    for r in pack.records("rule"):
        if r.topic not in ("sidewalk_closure", "detour"): continue
        kind = ("none (text only)" if not r.action else "sign placement (Guidance)" if r.strength.value == "GUIDANCE"
                else "sign required when the add-on is on (Standard)" if r.strength.value == "STANDARD" else "optional sign (Option)")
        L.append(f"| {r.id} | {r.strength.value.title()} | {expr_text(r.condition)} | {r.action or ''} | {kind} |")
    L += ["", "### Follow-ups", "", "| | Area | Follow-up |", "| --- | --- | --- |"]
    L += [f"| {a} | {b} | {_md(c)} |" for a, b, c in S4B_FOLLOW_UPS] + [""]
    return L


def main():
    text = build_report(JsonRulePackStore().load())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
