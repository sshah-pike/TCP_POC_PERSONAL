"""OSM rules (S6 commit 3, owner plan 2026-10-31): what the tags and the geometry of the chosen way say about each field.

Each rule gives a `SourceReading` (FOUND, NOT_PRESENT or UNKNOWN, see site_model/outcomes.py), never a fact: fusion compares the
reading with the AI's. The two-source rule is unchanged: for lanes per direction, divided, shoulder and one-way the AI and OSM
must agree.

  lanes_per_direction  lanes:forward and lanes:backward when both are tagged and equal; else `lanes` divided by 2, only when it is
                       even and the road is two-way; else UNKNOWN plus a question (odd total, or forward and backward differ).
                       One-way road: the lanes of its single direction. A missing `lanes` tag is no information (UNKNOWN, no question).
  oneway               a tag gives FOUND; a MISSING tag counts as "not one-way" at LOWER confidence (a stand-in): it can agree with
                       an AI "false" and never contradicts an AI "true".
  shoulder_present     yes/both/left/right: FOUND true; no/none: NOT_PRESENT. A missing tag is no information (UNKNOWN).
  sidewalk_present     the same, from the sidewalk tags.
  divided_highway      geometry only: an opposite-direction, parallel, one-way way of the same name or ref within a configured distance.
                       A two-way chosen way with none: NOT_PRESENT. A one-way chosen way with none: UNKNOWN (the other carriageway
                       may be unmapped).
Every distance and angle is read from config/site_understanding.json (osm section, CALIBRATION_PENDING).
"""
from typing import NamedTuple, Optional

from tcp_planner.data_sources.osm import SOURCE_ID, axis_diff_deg, direction_diff_deg, point_to_polyline
from tcp_planner.site_model.facts import Question, question_id
from tcp_planner.site_model.fusion_v2 import SourceReading
from tcp_planner.site_model.site_config import load_site_config, setting

YES, NO = {"yes", "true", "1", "both", "left", "right", "separate"}, {"no", "false", "0", "none"}
ONEWAY_YES, ONEWAY_REVERSE, ONEWAY_NO = {"yes", "true", "1"}, {"-1", "reverse"}, {"no", "false", "0"}
FIELDS = ("lanes_per_direction", "oneway", "shoulder_present", "sidewalk_present", "divided_highway")


class WayChoice(NamedTuple):
    way: object                 # OsmWay
    distance_m: float
    bearing_deg: float          # compass bearing of the nearest segment, direction as drawn


class OsmRead(NamedTuple):
    way_id: Optional[int]
    tags: dict
    readings: dict              # field -> SourceReading
    questions: tuple
    distance_m: Optional[float]


def _unknown_all(reason, note):
    return {f: SourceReading.unknown(SOURCE_ID, note, reason) for f in FIELDS}


def source_failed(error):
    """Readings when the Overpass request failed: every field UNKNOWN with reason source_failed (never NOT_PRESENT)."""
    return OsmRead(None, {}, _unknown_all("source_failed", f"OSM request failed: {error}"), (), None)


def rank_ways(ways, point=(0.0, 0.0), cfg=None):
    """WayChoice list within the configured distance, nearest first; a service way ranks after every other way."""
    cfg = cfg or load_site_config()
    limit = setting("osm", "max_way_distance_m", cfg)[0]
    out = []
    for w in ways:
        d, _, b = point_to_polyline(point, w.points)
        if d <= limit: out.append(WayChoice(w, d, b))
    return sorted(out, key=lambda c: (c.way.tags.get("highway") == "service", c.distance_m, c.way.id))


def _count(tags, key):
    v = tags.get(key, "").strip()
    return int(v) if v.isdigit() else None


def oneway_value(tags):
    """True (one-way), False, or None (reversible or unreadable) from the tags, with a flag 'stated' (False when the tag is missing)."""
    t = tags.get("oneway", "").strip().lower()
    if t in ONEWAY_YES or t in ONEWAY_REVERSE: return True, True
    if t in ONEWAY_NO: return False, True
    if not t:
        if tags.get("junction", "").lower() in ("roundabout", "circular"): return True, False
        return False, False
    return None, True


def is_reversed(tags):
    return tags.get("oneway", "").strip().lower() in ONEWAY_REVERSE


def _q(kind, field, way, reason, context, options=()):
    return Question(question_id=question_id(kind, field, way.id), kind=kind, reason=reason, options=tuple(options), field=field,
                    osm_way_id=way.id, context=context, reveals=(field,))


def lanes_reading(way):
    tags = way.tags
    ow, _ = oneway_value(tags)
    lanes, fwd, bwd = _count(tags, "lanes"), _count(tags, "lanes:forward"), _count(tags, "lanes:backward")
    ctx = {"lanes": tags.get("lanes"), "lanes:forward": tags.get("lanes:forward"), "lanes:backward": tags.get("lanes:backward"),
           "oneway": tags.get("oneway")}
    if ow is None:
        return SourceReading.unknown(SOURCE_ID, "oneway tag is reversible or unreadable", "ambiguous"), None
    if ow:
        n = fwd if fwd is not None else lanes
        if n is None: return SourceReading.unknown(SOURCE_ID, "one-way road with no lanes tag", "no_tag"), None
        return SourceReading.found(SOURCE_ID, n, note="one-way: all tagged lanes run one way"), None
    if fwd is not None and bwd is not None:
        if fwd == bwd: return SourceReading.found(SOURCE_ID, fwd, note="lanes:forward equals lanes:backward"), None
        q = _q("LANES_UNSPLIT", "lanes_per_direction", way, f"OSM tags {fwd} lanes forward and {bwd} backward: which direction is the work in?", ctx)
        return SourceReading.unknown(SOURCE_ID, "forward and backward lanes differ", "ambiguous"), q
    if lanes is None:
        return SourceReading.unknown(SOURCE_ID, "no lanes tag", "no_tag"), None
    if lanes % 2 == 0: return SourceReading.found(SOURCE_ID, lanes // 2, note="lanes divided by 2 (even total, two-way)"), None
    q = _q("LANES_UNSPLIT", "lanes_per_direction", way, f"OSM tags {lanes} lanes in total (odd): they cannot be split between the two directions", ctx)
    return SourceReading.unknown(SOURCE_ID, "odd lane total on a two-way road", "ambiguous"), q


def oneway_reading(way):
    v, stated = oneway_value(way.tags)
    if v is None: return SourceReading.unknown(SOURCE_ID, "oneway tag is reversible or unreadable", "ambiguous")
    if stated: return SourceReading.found(SOURCE_ID, v, note=f"oneway={way.tags.get('oneway')}")
    if v: return SourceReading.found(SOURCE_ID, True, lower_confidence=True, note="no oneway tag; a roundabout is one-way by OSM convention")
    return SourceReading.found(SOURCE_ID, False, lower_confidence=True, note="no oneway tag: counted as not one-way")


def _side_reading(tags, key):
    """Reading for `shoulder` or `sidewalk` from key, key:both, key:left, key:right."""
    vals = [tags[k].strip().lower() for k in (key, f"{key}:both", f"{key}:left", f"{key}:right") if k in tags]
    if not vals: return SourceReading.unknown(SOURCE_ID, f"no {key} tag", "no_tag")
    if any(v in YES for v in vals): return SourceReading.found(SOURCE_ID, True, note=f"{key} tag: {', '.join(vals)}")
    if all(v in NO for v in vals): return SourceReading.not_present(SOURCE_ID, False, note=f"{key} tag: {', '.join(vals)}")
    return SourceReading.unknown(SOURCE_ID, f"{key} tag {vals} is not yes or no", "ambiguous")


def _same_road(a, b, require):
    if not require: return True
    for k in ("name", "ref"):
        if a.tags.get(k) and a.tags.get(k) == b.tags.get(k): return True
    return False


def divided_reading(choice, ways, cfg):
    sep, _ = setting("osm", "divided_max_separation_m", cfg)
    tol, _ = setting("osm", "divided_parallel_tolerance_deg", cfg)
    need_name, _ = setting("osm", "divided_require_same_name_or_ref", cfg)
    w = choice.way
    ow, _ = oneway_value(w.tags)
    if ow is None: return SourceReading.unknown(SOURCE_ID, "oneway tag is reversible or unreadable", "ambiguous")
    if not ow:
        return SourceReading.not_present(SOURCE_ID, False, note="the chosen way carries both directions: no separate carriageway")
    own_dir = (choice.bearing_deg + (180 if is_reversed(w.tags) else 0)) % 360
    # the nearest point of the chosen way is where the opposite carriageway is looked for
    _, near, _ = point_to_polyline((0.0, 0.0), w.points)
    for o in ways:
        if o.id == w.id or o.tags.get("highway") == "service" or not _same_road(w, o, need_name): continue
        oo, _ = oneway_value(o.tags)
        if oo is not True: continue
        d, _, ob = point_to_polyline(near, o.points)
        odir = (ob + (180 if is_reversed(o.tags) else 0)) % 360
        if d <= sep and axis_diff_deg(choice.bearing_deg, ob) <= tol and abs(direction_diff_deg(own_dir, odir) - 180) <= tol:
            return SourceReading.found(SOURCE_ID, True, note=f"opposite one-way carriageway (way {o.id}) {d:.0f} m away, parallel within {tol} degrees")
    return SourceReading.unknown(SOURCE_ID, "one-way chosen way and no opposite carriageway found: the other side may be unmapped", "ambiguous")


def osm_read(ways, point=(0.0, 0.0), cfg=None, choice=None):
    """OsmRead for the chosen way (the nearest within the configured distance, or `choice`). No way near: every field UNKNOWN with
    reason no_source and no question here (the road question is raised by the bearing check)."""
    cfg = cfg or load_site_config()
    ranked = rank_ways(ways, point, cfg)
    choice = choice or (ranked[0] if ranked else None)
    if choice is None:
        return OsmRead(None, {}, _unknown_all("no_source", "no OSM road within the configured distance of the work point"), (), None)
    w, questions = choice.way, []
    lanes, q = lanes_reading(w)
    if q: questions.append(q)
    readings = {"lanes_per_direction": lanes, "oneway": oneway_reading(w), "shoulder_present": _side_reading(w.tags, "shoulder"),
                "sidewalk_present": _side_reading(w.tags, "sidewalk"), "divided_highway": divided_reading(choice, ways, cfg)}
    return OsmRead(w.id, dict(w.tags), readings, tuple(questions), choice.distance_m)
