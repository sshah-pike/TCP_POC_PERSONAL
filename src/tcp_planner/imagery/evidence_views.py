"""Multi-resolution evidence plan: a fixed, deterministic set of extra map views per site.

Views (corrected Azure 512-px scale; each keeps its own georeference metadata):
  work_area        zoom 19 (~0.11 m/px at 41 N), 1024 px, centred on the work reference
  corridor_ahead   zoom 18 (~0.22 m/px), 1024 px, centred half the analysis half-extent ahead along the road bearing
  corridor_behind  zoom 18, same distance behind
Together with the overview they cover the whole analysis corridor (+/- half-extent) at 2-4x the overview resolution.
The plan depends only on the work reference, the reference bearing the pipeline already computed (the same rounded
value sent to the model) and the analysis half-extent - so every model in a comparison gets the same views.
The model cannot request other views.
"""
import math

from tcp_planner.geometry.local_frame import inv

PLAN_VERSION = "views-v1"
VIEW_KIND = "map_view"


def plan_views(work_reference, bearing_deg, half_extent_m):
    lat0, lon0 = work_reference["latitude"], work_reference["longitude"]
    th = math.radians(float(bearing_deg)); ux, uy = math.sin(th), math.cos(th)  # east/north unit of travel direction
    d = round(float(half_extent_m) / 2, 1)
    specs = [("work_area", "work-area close-up", 19, (0.0, 0.0)),
             ("corridor_ahead", f"road corridor {d:.0f} m ahead along the reference bearing", 18, (d * ux, d * uy)),
             ("corridor_behind", f"road corridor {d:.0f} m behind along the reference bearing", 18, (-d * ux, -d * uy))]
    out = []
    for role, label, zoom, (dx, dy) in specs:
        lat, lon = inv(dx, dy, lat0, lon0)
        out.append({"role": role, "label": label, "zoom": zoom, "size_px": 1024, "lat": round(lat, 7), "lon": round(lon, 7),
                    "offset_m": (round(dx, 2), round(dy, 2))})
    return out


def view_signature(provider, spec, geometry_hash):
    return {"kind": VIEW_KIND, "plan": spec.get("plan", PLAN_VERSION), "role": spec["role"], "provider": getattr(provider, "name", None),
            "scale_model": getattr(provider, "SCALE_MODEL", None), "api_version": getattr(provider, "API_VERSION", None),
            "geometry_hash": geometry_hash, "zoom": spec["zoom"], "lat": spec["lat"], "lon": spec["lon"],
            "size_px": spec["size_px"]}


CENTERLINE_PLAN_VERSION = "views-cl-v1"


def plan_views_centerline(work_reference, centerline_enu, work_station_m, half_extent_m):
    """Same three views, but corridor views centred ON the OSM centerline +/- half the half-extent along the road
    (follows curves). Requires the centerline in the work-reference local frame (metres)."""
    from tcp_planner.geometry.local_frame import at
    lat0, lon0 = work_reference["latitude"], work_reference["longitude"]
    d = round(float(half_extent_m) / 2, 1)
    specs = [("work_area", "work-area close-up", 19, (0.0, 0.0))]
    for sign, role, word in ((1, "corridor_ahead", "ahead"), (-1, "corridor_behind", "behind")):
        (x, y), _ = at(centerline_enu, work_station_m + sign * d)
        specs.append((role, f"road corridor {d:.0f} m {word} along the OSM centerline", 18, (x, y)))
    out = []
    for role, label, zoom, (dx, dy) in specs:
        lat, lon = inv(dx, dy, lat0, lon0)
        out.append({"role": role, "label": label, "zoom": zoom, "size_px": 1024, "lat": round(lat, 7), "lon": round(lon, 7),
                    "offset_m": (round(dx, 2), round(dy, 2)), "plan": CENTERLINE_PLAN_VERSION})
    return out
