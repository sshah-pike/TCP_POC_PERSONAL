"""Deterministic review findings derived from saved pipeline outputs (no AI).

Finding ids are stable across versions of the same site (lineage key = work-reference geometry hash):
F-<sha256(lineage | category | subject)[:10]>.
"""
from ..core.ids import stable_id
from tcp_poc.models import FT

# visual states (colour + text glyph; never colour alone)
DETERMINED, NEEDS_CONFIRMATION, CONFLICT, UNKNOWN, SME, EXCEPTION = (
    "DETERMINED", "NEEDS_CONFIRMATION", "CONFLICT", "UNKNOWN", "SME_CONFIRMED", "SME_EXCEPTION")
STATE_STYLE = {DETERMINED: {"color": "GREEN", "glyph": "OK"}, NEEDS_CONFIRMATION: {"color": "AMBER", "glyph": "LOW"},
               CONFLICT: {"color": "RED", "glyph": "CONFLICT"}, UNKNOWN: {"color": "GRAY", "glyph": "UNKNOWN"},
               SME: {"color": "BLUE", "glyph": "SME"}, EXCEPTION: {"color": "PURPLE", "glyph": "EXCEPTION"}}
NOT_ASSESSED = ("individual lane boundaries", "lane width per lane", "shoulder geometry", "curb", "median geometry",
                "railroad crossing", "bridge", "existing signs", "existing devices", "PCMS", "taper", "buffer",
                "channelizing devices", "pedestrian route geometry")
FEATURE_KINDS = ("intersections", "driveways", "crosswalks", "roundabouts", "ramps", "obstructions")
KIND_LABEL = {"intersections": "Intersection", "driveways": "Driveway", "crosswalks": "Crosswalk",
              "roundabouts": "Roundabout", "ramps": "Ramp", "obstructions": "Obstruction", "sidewalks": "Sidewalk"}

# editable / displayed site facts: key -> (label, type, essential)
FACTS = {
    "road.lane_count": ("Lane count", "int", True),
    "road.two_way": ("Two-way traffic", "bool", True),
    "road.divided": ("Divided road", "bool", True),
    "road.facility_type": ("Facility type", "enum", True),
    "road.road_type": ("Road type (Table 6B-1)", "enum", True),
    "road.road_edges": ("Traveled-way width (m)", "float", True),
    "work.side": ("Work side of centerline", "enum", True),
    "work.location": ("Work location", "enum", True),
    "work.encroaches_traveled_way": ("Work encroaches traveled way", "bool", True),
    "work.affects_pedestrian_route": ("Pedestrian route impact", "bool", True),
    "site.complex_intersection_conflict": ("Intersection conflict near work", "bool", True),
    "work.requires_lane_closure": ("Lane closure required (derived)", "derived", True),
    "work.requires_alternating_one_lane_traffic": ("Alternating one-lane traffic (derived)", "derived", True),
    "road.centerline_status": ("Road centerline (alignment)", "geometry", True),
}
ENUMS = {"road.facility_type": ["CONVENTIONAL_ROAD", "FREEWAY", "TRUNK_ROAD", "RAMP_OR_LINK", "ROUNDABOUT"],
         "work.side": ["LEFT", "RIGHT"], "work.location": ["TRAVELED_WAY", "SHOULDER", "BEYOND_SHOULDER"]}
RANGES = {"road.lane_count": (1, 8), "road.road_edges": (3.0, 30.0)}
ELIG_FIELD = {"road.traffic_direction": "road.two_way", "facility_type": "road.facility_type"}


def state_of(status, source=None):
    if source and str(source).startswith("SME"): return SME
    return {"RESOLVED": DETERMINED, "LOW_CONFIDENCE": NEEDS_CONFIRMATION, "CONFLICT": CONFLICT,
            "CROSS_VIEW_MISMATCH": CONFLICT}.get(status, UNKNOWN)


def fact_value(site, elig, key):
    """(value, status, confidence, observations, source, note) of one fact from the site model / eligibility."""
    road, work = site["road"], site["work"]
    if key == "road.road_edges":
        e = road["road_edges"]
        return e.get("traveled_way_width_m"), e["status"], None, e.get("observations", []), e.get("source"), e.get("note")
    if key == "road.centerline_status":
        return road["centerline_status"], road["centerline_status"], None, [], "OSM", (road.get("centerline_correction") or {}).get("note")
    if key == "site.complex_intersection_conflict":
        ov = ((site.get("sme_overlay") or {}).get("facts") or {}).get(key)
        if ov: return ov["value"], "RESOLVED", None, [], ov["source"], ov.get("note")
        d = (elig or {}).get("detected_facts", {}).get(key) or {}
        return d.get("value"), d.get("status", "UNRESOLVED"), (site.get("feature_confidence") or {}).get("intersection_conflict"), \
            [{"source": "AI", "confidence": (site.get("feature_confidence") or {}).get("intersection_conflict")},
             {"source": "OSM+AI", "features_in_window": len(((elig or {}).get("intersection_analysis") or {}).get("features_in_window") or [])}], \
            None, "decided in eligibility from features near the work"
    grp, name = key.split(".", 1)
    f = (road if grp == "road" else work)[name]
    return f.get("value"), f.get("status"), f.get("confidence"), f.get("observations", []), f.get("source"), f.get("note")


def _sources(obs, source):
    s = sorted({o.get("source") for o in obs or [] if o.get("source")})
    if source and source not in s: s.append(source)
    return s


def _reason(elig, key):
    for lst, kind in (((elig or {}).get("unresolved_fields") or [], "UNRESOLVED"), ((elig or {}).get("failed_conditions") or [], "FAILED")):
        for u in lst:
            if ELIG_FIELD.get(u.get("field"), u.get("field")) == key: return u.get("reason_code"), kind
    return None, None


def fact_choices(key, value, ctx):
    typ = FACTS[key][1]
    if typ in ("derived", "geometry"): return []
    ch = []
    if value is not None: ch.append({"action": "CONFIRM", "label": f"Confirm detected value ({value})"})
    if typ == "bool":
        ch += [{"action": "CORRECT", "value": True, "label": "Yes"}, {"action": "CORRECT", "value": False, "label": "No"}]
    elif typ == "enum":
        opts = ENUMS.get(key) or (ctx["rule_pack"].road_types() if key == "road.road_type" else [])
        ch += [{"action": "CORRECT", "value": o, "label": o} for o in opts if o != value]
    elif typ == "int":
        ch += [{"action": "CORRECT", "value": v, "label": f"{v} lanes"} for v in (2, 3) if v != value]
        ch.append({"action": "CORRECT", "input": "int", "range": RANGES[key], "label": "Enter another lane count"})
    elif typ == "float":
        ch.append({"action": "CORRECT", "input": "float", "range": RANGES[key], "label": "Enter measured width (m)"})
    ch.append({"action": "MARK_UNRESOLVED", "label": "Mark unresolved"})
    return ch


def feature_key(kind, f, index):
    if f.get("source") == "OSM":
        return f"osm:{kind}:" + (f"way:{f['way_id']}" if f.get("way_id") else f"node:{f.get('node_id')}")
    if f.get("source") == "SME": return f"sme:{kind}:{f.get('sme_feature_id')}"
    return f"ai:{kind}:{index}"


def iter_features(site, which="features"):
    """(key, kind, feature) for every feature incl. sidewalks; which = features | original_features."""
    feats = site.get(which) or site.get("features") or {}
    for kind in FEATURE_KINDS:
        n_ai = 0
        for f in feats.get(kind, []):
            idx = n_ai if f.get("source") == "AI" else None
            if f.get("source") == "AI": n_ai += 1
            yield f.get("feature_key") or feature_key(kind, f, idx), kind, f
    for f in feats.get("sidewalks", []):
        yield f.get("feature_key") or f"{str(f.get('source')).lower()}:sidewalks:{f.get('side')}", "sidewalks", f


def feature_state(kind, f, thr):
    if f.get("sme_decision") in ("CONFIRMED", "MODIFIED", "ADDED"): return SME
    if f.get("sme_decision") == "REJECTED": return SME
    if kind == "sidewalks": return DETERMINED if f.get("present") is not None else UNKNOWN
    if f.get("source") == "OSM": return DETERMINED
    if f.get("station_m") is None: return UNKNOWN
    c = f.get("confidence")
    return DETERMINED if c is not None and c >= thr else NEEDS_CONFIRMATION


def derive(ctx, cfg):
    site, elig, val, pack = ctx["site_model"], ctx["eligibility"], ctx["validation"], ctx["rule_pack"]
    lk = ctx["lineage_key"]; thr = cfg["fusion"]["min_critical_confidence"]
    out = []

    def add(category, subject, **f):
        fid = stable_id("F", lk, category, subject)
        st = f.get("state", UNKNOWN)
        out.append({"finding_id": fid, "category": category, "subject": subject, **f, "style": STATE_STYLE[st]})
        return out[-1]

    # ---- site facts
    for key, (label, typ, essential) in FACTS.items():
        value, status, conf, obs, source, note = fact_value(site, elig, key)
        st = state_of(status, source)
        code, kind = _reason(elig, key)
        needs = st in (NEEDS_CONFIRMATION, CONFLICT, UNKNOWN) or kind == "FAILED"
        if kind == "FAILED" and st == DETERMINED: st = CONFLICT  # resolved but fails the approved TA-1 condition
        add("SITE_FACT", key, label=label, entity_id=key, value=value, status=status, state=st,
            confidence=conf, evidence_sources=_sources(obs, source), observations=obs, note=note,
            reason_code=code, reason=("fails approved TA-1 condition" if kind == "FAILED" else
                                      f"status {status}" if needs else None),
            severity="BLOCKING" if needs and essential else ("WARNING" if needs else "INFORMATIONAL"),
            requires_review=needs, editable=typ not in ("derived", "geometry"), value_type=typ,
            choices=fact_choices(key, value, ctx), rule_refs=["01_eligibility_rules"] if essential else [])

    # ---- features (OSM / AI / SME), including SME-rejected ones (shown, excluded from validation)
    conflicts = []
    for chk in ((val or {}).get("geometry_validation") or {}).get("checks", []):
        if chk["status"] == "FAIL" and chk["id"] == "GEO-DRIVEWAY-INTERSECTION-CONFLICT":
            conflicts += (chk.get("detail") or {}).get("conflicts") or []
    window = [(w.get("source"), w.get("station_m")) for w in ((elig or {}).get("intersection_analysis") or {}).get("features_in_window") or []]
    seen = set()
    for which in ("features", "rejected"):
        items = list(iter_features(site)) if which == "features" else \
            [(k, f["kind"], f) for k, f in ((site.get("sme_overlay") or {}).get("rejected_features") or {}).items()]
        for key, kind, f in items:
            if key in seen: continue
            seen.add(key)
            st = feature_state(kind, f, thr) if which == "features" else SME
            implicated = [c for c in conflicts if c.get("feature") == kind and c.get("source") == f.get("source")
                          and c.get("station_m") == f.get("station_m")]
            in_window = (f.get("source"), f.get("station_m")) in window and kind in ("intersections", "roundabouts", "ramps")
            needs = which == "features" and (st in (NEEDS_CONFIRMATION, UNKNOWN) or bool(implicated) or in_window)
            if implicated and st == DETERMINED: st = CONFLICT
            label = KIND_LABEL[kind] + (f" ({f.get('side')})" if f.get("side") else "")
            value = f.get("present") if kind == "sidewalks" else (f.get("description") or f.get("highway") or f.get("name"))
            add("FEATURE", key, label=label, entity_id=key, feature_kind=kind, value=value, state=st,
                status="REJECTED_BY_SME" if which == "rejected" else (f.get("sme_decision") or f.get("source")),
                confidence=f.get("confidence"), evidence_sources=[f.get("source")], station_m=f.get("station_m"),
                side=f.get("side"), osm_id=f.get("way_id") or f.get("node_id"),
                reason=("too close to a planned sign (validator GEO-DRIVEWAY-INTERSECTION-CONFLICT)" if implicated else
                        "inside the intersection-analysis window of the work" if in_window else
                        ("sidewalk presence not mapped/observed" if kind == "sidewalks" else "position unknown") if st == UNKNOWN else "low confidence" if st == NEEDS_CONFIRMATION else None),
                severity="BLOCKING" if (implicated or in_window) else ("WARNING" if needs else "INFORMATIONAL"),
                requires_review=needs, related_objects=sorted({c["object"] for c in implicated}),
                choices=[] if which == "rejected" else _feature_choices(kind, f))

    # ---- failed validator checks (rule results come only from the unchanged validators)
    rules = {r["id"]: r for r in pack.section("18_validation_rules")}
    accepted = {d["check_id"]: d for d in ((ctx.get("plan") or {}).get("sme_dispositions") or {}).get("dispositions", [])
                if d.get("disposition") == "ACCEPTED_WITH_SME_OVERRIDE"}
    for part in ("rule_validation", "geometry_validation"):
        for chk in ((val or {}).get(part) or {}).get("checks", []):
            if chk["status"] != "FAIL": continue
            rid = chk.get("rule_pack_validation_id") or chk["id"]
            common = dict(label=f"Validator {chk['id']}", entity_id=chk["id"], value="FAIL", status="CONFLICT", rule_status="CONFLICT",
                          rule_id=rid, rule_text=(rules.get(rid) or {}).get("check"), rule_pack=pack.ref, detail=chk.get("detail"),
                          evidence_sources=["VALIDATOR"])
            if chk["id"] in accepted:   # exported draft: conflict accepted as a plan-specific SME exception (rule stays CONFLICT)
                d = accepted[chk["id"]]
                add("RULE_CHECK", chk["id"], **common, state=EXCEPTION, disposition=d["disposition"], exception_id=d.get("exception_id"),
                    reason="rule CONFLICT accepted as a plan-specific SME exception (not compliant, not independently approved)",
                    severity="WARNING", requires_review=False, choices=[])
                continue
            add("RULE_CHECK", chk["id"], **common, state=CONFLICT,
                reason="independent validation failed", severity="BLOCKING", requires_review=True,
                choices=[{"action": "REQUEST_EXCEPTION", "label": "Request plan-specific SME exception"}])

    # ---- TA applicability (approved structured TA data only)
    sel = pack.section("03_typical_application_selection")
    decision = (elig or {}).get("decision")
    ta_ok = decision == "SUPPORTED_AUTO"
    ta_codes = [c for c in (elig or {}).get("reason_codes") or []]
    add("TA", sel["selected_ta"], label=f"Typical Application {sel['selected_ta']} ({sel.get('title')})",
        entity_id=sel["selected_ta"], value=decision, state=DETERMINED if ta_ok else (CONFLICT if decision == "UNSUPPORTED_POC" else UNKNOWN),
        status="APPLICABLE" if ta_ok else ("NOT_APPLICABLE" if decision == "UNSUPPORTED_POC" else "UNRESOLVED"),
        conditions=sel["selection_conditions"], candidates=sel.get("other_tas_allowed") or [],
        reason=None if ta_ok else ", ".join(ta_codes), evidence_sources=["RULE_PACK_03"], rule_pack=pack.ref,
        severity="INFORMATIONAL" if ta_ok else "BLOCKING", requires_review=not ta_ok, choices=[])

    # ---- service / agent escalations (not site discrepancies)
    for e in site.get("escalations") or []:
        add("SERVICE", e.get("reason_code") or e.get("status"), label=f"Analysis issue: {e.get('status')}",
            entity_id=e.get("field"), value=e.get("status"), state=UNKNOWN, status=e.get("status"),
            reason="analysis step could not verify these facts; confirm the affected facts or request new analysis",
            evidence_sources=["AGENT"], severity="WARNING", requires_review=True, choices=[])

    order = {"BLOCKING": 0, "WARNING": 1, "INFORMATIONAL": 2}
    out.sort(key=lambda f: (not f["requires_review"], order[f["severity"]], f["category"], f["subject"]))
    return out


def _feature_choices(kind, f):
    if kind == "sidewalks":
        return [{"action": "SET_SIDEWALK", "value": True, "label": "Sidewalk present"},
                {"action": "SET_SIDEWALK", "value": False, "label": "Sidewalk absent"},
                {"action": "SET_SIDEWALK", "value": None, "label": "Sidewalk unknown"}]
    return [{"action": "CONFIRM_FEATURE", "label": "Confirm feature"},
            {"action": "REJECT_FEATURE", "label": "Reject feature (not present)", "reason_required": True},
            {"action": "MODIFY_FEATURE", "label": "Correct position / side", "input": "station_side", "reason_required": True}]


def summary(findings):
    rev = [f for f in findings if f["requires_review"]]
    return {"total": len(findings), "requires_review": len(rev),
            "blocking": sum(1 for f in rev if f["severity"] == "BLOCKING"),
            "by_state": {s: sum(1 for f in findings if f["state"] == s) for s in STATE_STYLE}}


def ft(m):
    return None if m is None else round(m / FT, 1)
