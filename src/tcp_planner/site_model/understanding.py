"""Site understanding, one zone (S6 step 11): call 1 result + code checks + OSM + fusion, wired BESIDE the old path.

This module reads a call 1 response (it never makes a call), the image bytes that were sent, and optionally OSM ways; it returns facts,
questions and a trace. It imports nothing of the old pipeline and nothing of the old pipeline imports it, so the old path's outputs
cannot change (tests: tests/unit/site/test_understanding.py, test_old_call_body_unchanged.py and the global-identity guard).

Order of work (each stage has its switch in config `stages`; a stage that is off is recorded in the trace):
  1 parse the response (prompt version 1 or 2)            2 snapping of the edge marks (code)
  3 bearing check; the OSM reference way is chosen by the work point (never by the marks)
  4 OSM read of the reference way (or "not clear", or "failed")
  5 facts from the observations (floors per profile, the marks check for work_location)
  6 edge rule on work_location                            7 widths from the marks (code, with the pack's straddle test)
  8 code checks: lane lines, shadow and canopy share, image-to-OSM offset
  9 fusion: the safety-critical fields need AI + OSM to agree; sidewalk is record only
 10 consistency checks                                    11 a bearing failure blocks the road-specific facts and widths
 12 site exceptions (human overrides, last)               13 rule inputs and the review gate
The gate (`RuleInputs.gate`) is called HERE, where the result is built: `decision` is REVIEW_REQUIRED, naming the facts, as soon as a
used fact carries AI_ONLY_UNCONFIRMED, OSM_TAG_ASSUMED, CODE_CHECK_LOWERED, DEFAULT_ASSUMED or PROPOSED.
Every run's trace records the config values it used (the sections and their sha256), the prompt and schema hashes, the stage switches,
every check's evidence, the OSM source call, the site exceptions file hash and every exception use. Everything is deterministic.
"""
import hashlib
import json
from typing import NamedTuple, Optional

from tcp_planner.ai import call1
from tcp_planner.ai import prompt_registry as pr
from tcp_planner.contracts import SUPPORTED_AUTO, canonical_json, sha256_hex
from tcp_planner.imagery import snap as snapping
from tcp_planner.site_model import bearing_check as BC
from tcp_planner.site_model import code_checks as CC
from tcp_planner.site_model import consistency as K
from tcp_planner.site_model import edge_rule as ER
from tcp_planner.site_model import fusion_apply as FA
from tcp_planner.site_model import lengths as L
from tcp_planner.site_model import osm_rules as OR
from tcp_planner.site_model import site_exceptions as SX
from tcp_planner.site_model.facts import question_scope, rule_inputs
from tcp_planner.site_model.site_config import FLOOR_KINDS, confidence_floor, load_site_config, stage_on

CONFIG_SECTIONS = ("call1", "measurement", "defaults", "crops", "osm", "bearing", "edge_rule", "confidence_floors", "snapping", "code_checks",
                   "consistency", "stages")
SCHEMA_VERSION = "1"


class SiteInput(NamedTuple):
    response_text: str                      # the model's JSON answer
    image_bytes: bytes                      # the image as sent (same pixels as the marks)
    image_record: dict                      # from resize_for_model: sent_px, mpp_sent, sha256
    profile: Optional[str] = None           # Foundry profile name (picks the confidence floors)
    prompt_version: Optional[int] = None    # None: from the stage switch enhanced_prompt
    site_id: Optional[str] = None
    zone_id: Optional[str] = None
    project_id: Optional[str] = None
    ways: Optional[tuple] = None            # OsmWay tuple in the local frame; None = OSM not consulted
    osm_error: Optional[str] = None         # the OSM request failed
    osm_call: Optional[dict] = None         # the SourceCall record, for the trace
    pack: Optional[object] = None           # rule pack: needed for the width facts (the straddle test)
    exceptions: Optional[object] = None     # site_exceptions.Loaded (default: the shipped file)


class SiteUnderstanding(NamedTuple):
    facts: tuple
    questions: tuple
    marks: tuple
    decision: str                           # SUPPORTED_AUTO or REVIEW_REQUIRED after the gate (the base decision of this module)
    reasons: tuple                          # each: {"fact", "flag", "reason"}
    trace: dict

    @property
    def rule_inputs(self):
        return rule_inputs(self.facts)

    def gated(self, decision, used=None):
        """The gate for a result a caller builds from these facts (S7's router): (decision, reasons)."""
        return self.rule_inputs.gate(decision, used)


def _plain(x):
    return json.loads(json.dumps(x, default=lambda o: o.model_dump(mode="json") if hasattr(o, "model_dump") else
                                 (o._asdict() if hasattr(o, "_asdict") else str(o)), sort_keys=True))


def _config_used(cfg):
    sections = {k: cfg[k] for k in CONFIG_SECTIONS if k in cfg}
    return sections, sha256_hex(canonical_json(sections))


def _dedupe(questions):
    seen, out = set(), []
    for q in questions:
        if q.question_id in seen: continue
        seen.add(q.question_id); out.append(q)
    return out


def understand_site(inp: SiteInput, cfg=None) -> SiteUnderstanding:
    cfg = cfg or load_site_config()
    on = {name: stage_on(name, cfg) for name in cfg["stages"] if name != "note"}
    version = inp.prompt_version if inp.prompt_version is not None else (2 if on["enhanced_prompt"] else 1)
    size, mpp = tuple(inp.image_record["sent_px"]), inp.image_record["mpp_sent"]
    notes, questions, checks = [], [], {}
    skipped = {n: "off" for n, v in on.items() if not v}

    # 1-2 parse and snap
    res = call1.parse_call1(inp.response_text, size, cfg, version=version)
    notes += list(res.notes)
    marks = res.marks
    if on["snapping"]:
        sr = snapping.snap_marks(inp.image_bytes, marks, cfg); marks = sr.marks; notes += list(sr.notes)
    obs = res.observations

    # 3 bearing, the reference way by the work point
    chk = None
    if on["bearing"] and inp.ways is not None and inp.osm_error is None:
        chk = BC.check_bearing(marks, inp.ways, cfg=cfg)
        checks["bearing"] = chk._asdict() | {"reference": None if chk.reference is None else {"way_id": chk.reference.way.id, "distance_m": chk.reference.distance_m}}
        checks["bearing"].pop("questions", None)
    elif on["bearing"]: skipped["bearing"] = "no OSM ways" if inp.osm_error is None else "OSM failed"

    # 4 OSM
    osm = None
    if on["osm"]:
        if inp.osm_error is not None: osm = OR.source_failed(inp.osm_error)
        elif inp.ways is None: skipped["osm"] = "not consulted"
        elif chk is not None and chk.status == BC.WHICH_ROAD: osm = OR.osm_unclear()
        elif chk is not None and chk.reference is not None: osm = OR.osm_read(inp.ways, choice=chk.reference, cfg=cfg)
        else: osm = OR.osm_read(inp.ways, cfg=cfg)
    road_near = None if inp.ways is None else ER.road_near(inp.ways, cfg=cfg)

    # 5 facts
    wl_value = obs["work_location"].value if obs["work_location"].status == "RESOLVED" else None
    marks_check = K.work_marks_check(marks, wl_value) if on["consistency"] and cfg["consistency"]["work_location_vs_edges"]["value"] else call1.MARKS_MISSING
    facts, qs = call1.to_site_facts(call1.Call1Result(obs, marks, tuple(notes)), marks_check, cfg, profile=inp.profile)
    questions += qs

    # 6 edge rule
    if on["edge_rule"]:
        er = ER.check_edge(marks, mpp, road_near, cfg)
        checks["edge_rule"] = er._asdict() | {"question": None}
        new = []
        for f in facts:
            nf, q = ER.apply_edge_rule(f, er)
            new.append(nf)
            if q is not None: questions.append(q)
        facts = new

    # 7 widths
    tw = None
    if inp.pack is not None:
        ml = L.measure_lengths(marks, mpp, inp.pack, total_lanes=K.total_lanes(obs), gate={k: (obs[k].value if obs[k].status == "RESOLVED" else None) for k in ("parking_present", "shoulder_present")}, cfg=cfg)
        facts = list(facts) + list(ml.facts); questions += list(ml.questions); tw = ml.measured.get("traveled_way_width")
    else: skipped["widths"] = "no rule pack given"

    # 8 code checks
    line_result = None
    if on["lane_lines"]:
        line_result = CC.lane_lines(inp.image_bytes, marks, cfg); checks["lane_lines"] = line_result._asdict()
    if on["shadow_canopy"]:
        sh = CC.shares(inp.image_bytes, marks, cfg); checks["shadow_canopy"] = sh._asdict()
        checks["model_shares"] = CC.compare_model_shares(sh, _share(obs, "shadow_share"), _share(obs, "canopy_share"), cfg)    # evidence only
        facts = CC.occlusion_effect(facts, sh)
    osm_trusted = True
    if on["osm_offset"]:
        ref_pts = None
        if chk is not None and chk.reference is not None: ref_pts = chk.reference.way.points
        elif inp.ways is not None:
            ranked = OR.rank_ways(inp.ways, cfg=cfg); ref_pts = ranked[0].way.points if ranked else None
        off = CC.osm_offset(marks, size, mpp, ref_pts, cfg); checks["osm_offset"] = off._asdict()
        osm_trusted = off.ok is not False

    # 9 fusion
    fused = FA.fuse_fields(facts, osm, cfg, osm_trusted=osm_trusted)
    facts = list(fused.facts); questions += list(fused.questions)
    if osm is not None: questions += [q for q in osm.questions if q.field not in {x.field for x in fused.questions}]

    # 10 consistency
    if on["consistency"]:
        cons = K.run_consistency(facts, obs, tw, line_result, cfg)
        facts = list(cons.facts); questions += list(cons.questions)
        for r in cons.results: checks[r.name] = r._asdict()

    # 11 a bearing failure blocks the road-specific facts and widths
    if chk is not None and not chk.widths_ok:
        facts = BC.block_road_specific(facts, chk); questions += list(chk.questions)

    # 12 site exceptions (a human decision, applied last)
    loaded = inp.exceptions or SX.load()
    uses = []
    if on["site_exceptions"]:
        facts, uses = SX.apply(facts, loaded, site_id=inp.site_id, zone_id=inp.zone_id, osm_way_id=None if osm is None else osm.way_id)
    exc = SX.trace_record(loaded, uses) | ({"stage": "off"} if not on["site_exceptions"] else {})

    questions = [question_scope(q, inp.zone_id, inp.project_id) for q in _dedupe(questions)]
    facts = tuple(facts)
    ri = rule_inputs(facts)
    decision, reasons = ri.gate(SUPPORTED_AUTO)                    # the gate, where the result is built

    sections, config_sha = _config_used(cfg)
    system, user = (pr.load_prompt(call1.SYSTEM_ID, version), pr.load_prompt(call1.USER_ID, version))
    trace = {"schema_version": SCHEMA_VERSION, "actor": "CODE", "site_id": inp.site_id, "zone_id": inp.zone_id, "project_id": inp.project_id,
             "prompt": {"version": version, "system_sha256": system.sha256, "user_sha256": user.sha256,
                        "schema_sha256": sha256_hex(canonical_json(call1.wire_schema(version)))},
             "profile": inp.profile, "image": {"sha256": inp.image_record.get("sha256"), "sent_px": list(size), "mpp_sent": mpp},
             "stages": {n: ("on" if v else "off") for n, v in on.items()}, "skipped": skipped,
             "config": sections, "config_sha256": config_sha,
             "floors": {k: confidence_floor(k, inp.profile, cfg)[0] for k in FLOOR_KINDS},
             "checks": _plain(checks), "fusion": {k: v.model_dump(mode="json") for k, v in fused.records.items()},
             "osm": None if osm is None else {"way_id": osm.way_id, "tags": osm.tags, "distance_m": osm.distance_m, "call": inp.osm_call},
             "osm_error": inp.osm_error, "site_exceptions": _plain(exc), "notes": notes,
             "gate": {"decision": decision, "reasons": list(reasons)}, "question_ids": [q.question_id for q in questions]}
    return SiteUnderstanding(facts, tuple(questions), tuple(marks), decision, tuple(reasons), _plain(trace))


def _share(obs, name):
    o = obs.get(name)
    return o.value if o is not None and o.status == "RESOLVED" else None


def trace_sha256(u: SiteUnderstanding):
    """Hash of the trace: two runs on the same inputs and config give the same hash (replay determinism)."""
    return hashlib.sha256(canonical_json(u.trace).encode()).hexdigest()
