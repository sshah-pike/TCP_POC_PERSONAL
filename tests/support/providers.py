"""Replay / record wrappers with the interfaces the pipeline already uses.

map provider   fetch_context(project_geometry, half_extent_m, size_px) and fetch_view(lat, lon, zoom, size_px)
OSM source     callable (lat, lon, radius_m)
vision         analyze(image, context, views=None, grounding=None) and request_fingerprint(...)
In replay mode (default) nothing is delegated: a missing fixture raises MissingFixtureError. In record mode the call goes
to the live provider and the answer is stored. Every call appends (kind, fingerprint) to .calls, so a test can compare runs.
"""
import io, json, os

from .fixtures import FixtureStore, fingerprint


def _png(img):
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()


def map_request(provider, scale_model, api_version, lat, lon, half_extent_m, size_px):
    return {"kind": "map", "provider": provider, "scale_model": scale_model, "api_version": api_version,
            "lat": round(float(lat), 7), "lon": round(float(lon), 7), "half_extent_m": round(float(half_extent_m), 1),
            "size_px": int(size_px)}


def crop_request(provider, scale_model, api_version, lat, lon, zoom, size_px):
    return {"kind": "map_crop", "provider": provider, "scale_model": scale_model, "api_version": api_version,
            "lat": round(float(lat), 7), "lon": round(float(lon), 7), "zoom": int(zoom), "size_px": int(size_px)}


def osm_request(source, lat, lon, radius_m):
    return {"kind": "osm", "source": source, "lat": round(float(lat), 7), "lon": round(float(lon), 7),
            "radius_m": round(float(radius_m), 1)}


def ai_request(request_fingerprint):
    return {"kind": "ai", "request": request_fingerprint}


class MapFixtures:
    """Map provider replaying (or recording) analysis images and agent crops. `identity` supplies name and scale model."""
    last_reused = False
    purpose = None

    def __init__(self, store, identity, live=None):
        self.store, self.live, self.calls = store, live, []
        self.name = getattr(identity, "name", "azure_maps")
        self.SCALE_MODEL = getattr(identity, "SCALE_MODEL", None)
        self.API_VERSION = getattr(identity, "API_VERSION", None)

    def _get(self, kind, request, live_call):
        fp = fingerprint(request); self.calls.append((kind, fp))
        if self.live is None:
            doc, fp = self.store.load(kind, request)
            return self.store.load_image(kind, fp, doc), dict(doc["meta"])
        img, meta = live_call()
        self.store.save(kind, request, {"meta": meta}, _png(img))
        return img, meta

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        ref = project_geometry["work_reference"]
        req = map_request(self.name, self.SCALE_MODEL, self.API_VERSION, ref["latitude"], ref["longitude"],
                          half_extent_m, size_px)
        return self._get("map", req, lambda: self.live.fetch_context(project_geometry, half_extent_m, size_px))

    def fetch_view(self, lat, lon, zoom, size_px):
        req = crop_request(self.name, self.SCALE_MODEL, self.API_VERSION, lat, lon, zoom, size_px)
        return self._get("map_crop", req, lambda: self.live.fetch_view(lat, lon, zoom, size_px))


class OsmFixtures:
    def __init__(self, store, source="osm_api", live=None):
        self.store, self.source, self.live, self.calls = store, source, live, []

    def __call__(self, lat, lon, radius_m):
        req = osm_request(self.source, lat, lon, radius_m)
        fp = fingerprint(req); self.calls.append(("osm", fp))
        if self.live is None:
            doc, _ = self.store.load("osm", req)
            return doc["elements"]
        elements = self.live(lat, lon, radius_m)
        self.store.save("osm", req, {"elements": elements})
        return elements


class VisionFixtures:
    """Vision provider replaying (or recording) AI results. Attribute lookups (name, profile, deployment, api,
    supports_views...) go to `identity`, a provider object built without any network access."""

    def __init__(self, store, identity, live=None):
        self._identity, self.store, self.live, self.calls = identity, store, live, []

    def __getattr__(self, item):
        return getattr(self._identity, item)

    def request_fingerprint(self, image, context, views=None, grounding=None):
        return self._identity.request_fingerprint(image, context, views=views, grounding=grounding)

    def analyze(self, image, context, views=None, grounding=None):
        req = ai_request(self.request_fingerprint(image, context, views, grounding))
        fp = fingerprint(req); self.calls.append(("ai", fp))
        if self.live is None:
            doc, _ = self.store.load("ai", req)
            return doc["result"]
        kw = {k: v for k, v in (("views", views), ("grounding", grounding)) if v}
        result = self.live.analyze(image, context, **kw)
        self.store.save("ai", req, {"result": result})
        return result


class Harness:
    """The three wrappers for one recorded site."""

    def __init__(self, site_dir, live=None):
        """live: None for replay, or {"map": provider, "osm": callable, "vision": provider} to record."""
        from tcp_planner.imagery.map_provider import AzureMapsProvider
        from tcp_planner.ai.foundry_provider import FoundryVisionProvider
        self.store = FixtureStore(site_dir)
        with open(os.path.join(site_dir, "site.json"), encoding="utf-8") as f: self.site = json.load(f)
        live = live or {}
        self.map = MapFixtures(self.store, AzureMapsProvider(), live.get("map"))
        self.osm = OsmFixtures(self.store, "osm_api", live.get("osm"))
        identity = live.get("vision") or FoundryVisionProvider(profile=self.site["ai_profile"])
        self.vision = VisionFixtures(self.store, identity, live.get("vision"))

    @property
    def kml(self):
        return os.path.join(self.store.dir, "input.kml")

    def operator(self):
        o = self.site["operator"]
        return {"road_type": o.get("road_type"), "speed_mph": o.get("speed_mph"),
                "requires_lane_closure": bool(o.get("requires_lane_closure")), "options": dict(o.get("options") or {})}

    def run_kwargs(self):
        """Keyword arguments for run_pipeline that replay (or record) this site."""
        return dict(kml=self.kml, operator=self.operator(), map_provider=self.map, vision_provider=self.vision,
                    osm_source=self.osm)

    def fingerprints(self):
        return list(self.map.calls) + list(self.osm.calls) + list(self.vision.calls)
