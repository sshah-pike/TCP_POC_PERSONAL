"""Test helpers: run the UI runner in-process with every patched global restored afterwards; fakes for
Azure Maps, the OSM API and Foundry model backends (no network, no real credentials)."""
import contextlib, hashlib, io, json, math, os, ssl, sys
from urllib.parse import urlsplit

from tcp_planner.orchestration import pipeline as app

FAKE_AZURE_KEY = "AZURE-TEST-KEY-0123456789-SENTINEL"
PATCHED = ("Telemetry", "run_pipeline", "load_rule_pack", "use_os_trust_store", "get_map_provider",
           "get_vision_provider", "load_env_file")


@contextlib.contextmanager
def isolated():
    """Snapshot/restore app globals, the OSM fetch, Anthropic client classes, TLS context, env and argv."""
    saved = {k: getattr(app, k) for k in PATCHED}
    saved_osm = app.osm_adapter.fetch_osm
    import anthropic
    saved_a = (anthropic.Anthropic, getattr(anthropic, "AnthropicFoundry", None))
    env = dict(os.environ); argv = list(sys.argv); ctx = ssl.SSLContext
    app.load_env_file = lambda *a, **k: None  # never read the real .env in tests
    try:
        yield
    finally:
        for k, v in saved.items(): setattr(app, k, v)
        app.osm_adapter.fetch_osm = saved_osm
        anthropic.Anthropic = saved_a[0]
        if saved_a[1] is not None: anthropic.AnthropicFoundry = saved_a[1]
        if ssl.SSLContext is not ctx:
            import truststore; truststore.extract_from_ssl()
        os.environ.clear(); os.environ.update(env); sys.argv[:] = argv


def run(rdir):
    from tcp_planner.orchestration import run_worker as runner
    with isolated():
        return runner.main([rdir])


def tree_hashes(path):
    out = {}
    for root, _, files in os.walk(path):
        for n in files:
            p = os.path.join(root, n)
            with open(p, "rb") as f: out[os.path.relpath(p, path)] = hashlib.sha256(f.read()).hexdigest()
    return out


def assert_no_secret(*paths, secrets=(FAKE_AZURE_KEY,)):
    for path in paths:
        for root, _, files in os.walk(path):
            for n in files:
                with open(os.path.join(root, n), "rb") as f: data = f.read()
                for s in secrets: assert s.encode() not in data, (n, s)


# ---------------------------------------------------------------- fake HTTP
class FakeResponse:
    def __init__(self, status, ctype, content=b""):
        self.status_code = status; self.headers = {"content-type": ctype}; self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")


def azure_tile_image(params):
    """Deterministic image whose pixels encode their GLOBAL pixel coordinates at the requested zoom (512 grid)."""
    import numpy as np
    from PIL import Image
    lon, lat = (float(v) for v in params["center"].split(","))
    z, w = int(params["zoom"]), int(params["width"])
    world = 512 * 2 ** z
    cx = (lon + 180) / 360 * world
    cy = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * world
    x0, y0 = int(round(cx - w / 2)), int(round(cy - w / 2))
    xs = (np.arange(w) + x0) % 251; ys = (np.arange(w) + y0) % 241
    arr = np.zeros((w, w, 3), dtype=np.uint8)
    arr[:, :, 0] = xs[None, :]; arr[:, :, 1] = ys[:, None]; arr[:, :, 2] = 77
    buf = io.BytesIO(); Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def osm_xml(elements):
    """OSM API XML for offline-style elements (ways with geometry, tagged nodes)."""
    nodes, ways, nid = [], [], 1
    for e in elements:
        if e["type"] == "node":
            tags = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in (e.get("tags") or {}).items())
            nodes.append(f'<node id="{9000 + nid}" lat="{e["lat"]}" lon="{e["lon"]}">{tags}</node>'); nid += 1
    for e in elements:
        if e["type"] != "way": continue
        refs = []
        for g in e["geometry"]:
            nodes.append(f'<node id="{nid}" lat="{g["lat"]}" lon="{g["lon"]}"/>'); refs.append(nid); nid += 1
        nds = "".join(f'<nd ref="{r}"/>' for r in refs)
        tags = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in (e.get("tags") or {}).items())
        ways.append(f'<way id="{e["id"]}">{nds}{tags}</way>')
    return ('<?xml version="1.0"?><osm version="0.6">' + "".join(nodes) + "".join(ways) + "</osm>").encode()


class FakeHttp:
    """requests.get replacement: Azure Maps (tile images), OSM API (XML). Records every call by host."""

    def __init__(self, osm_elements=None, azure=None, osm_error=None):
        self.calls = []; self.osm_elements = osm_elements; self.azure = azure; self.osm_error = osm_error

    def count(self, host):
        return sum(1 for h, _ in self.calls if h == host)

    def __call__(self, url, params=None, **kw):
        host = urlsplit(url).hostname; self.calls.append((host, {"params": params, **kw}))
        if host == "atlas.microsoft.com":
            if self.azure: return self.azure(params, kw)
            return FakeResponse(200, "image/png", azure_tile_image(params))
        if host == "api.openstreetmap.org":
            if self.osm_error: raise self.osm_error
            return FakeResponse(200, "application/xml", osm_xml(self.osm_elements))
        raise AssertionError(f"unexpected request to {host}")


# ---------------------------------------------------------------- fake Foundry API adapter
SEEN = []  # (mode, image sha256 tuple, text sha256) for every fake model call


def to_wire(value, schema=None):
    """Canonical observation -> tri-state wire form (what a compliant model returns)."""
    from tcp_planner.ai import foundry_provider as fp
    from tcp_planner.ai.vision_provider import OBSERVATION_SCHEMA
    schema = schema or OBSERVATION_SCHEMA
    if fp._is_nullable_boolean(schema): return {True: "YES", False: "NO", None: "UNKNOWN"}[value]
    if isinstance(value, dict) and "properties" in schema:
        return {k: to_wire(v, schema["properties"][k]) if k in schema["properties"] else v for k, v in value.items()}
    if isinstance(value, list) and "items" in schema: return [to_wire(v, schema["items"]) for v in value]
    return value


class FakeAPI:
    """Stands in for one API family; the deployment name selects the behaviour (dep-ok / dep-low / dep-fail)."""
    name = "fake_api"
    CAPABILITIES = {"image_input": True, "structured_output": True, "usage_reporting": True, "verified": "test fake"}

    def send(self, endpoint, key, deployment, effort, parts, schema, system=None):
        from tcp_planner.orchestration import offline_scenarios as offline
        from tcp_planner.ai.foundry_provider import Reply
        mode = deployment.split("-")[-1]
        imgs = tuple(hashlib.sha256(v).hexdigest() for k, v in parts if k == "image")
        text = hashlib.sha256("".join(v for k, v in parts if k == "text").encode()).hexdigest()
        SEEN.append((mode, imgs, text))
        obs = json.loads(json.dumps(offline.build("supported")["vision_provider"].observation))
        usage = {"input_tokens": 1000 * len(imgs), "output_tokens": 300, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        if mode == "fail":
            return Reply('{"two_way_visible": "maybe"}', "fake-model-fail", None, usage)
        if mode == "low":
            obs["attribute_confidence"]["two_way_visible"] = 0.4; obs["two_way_visible"] = None
        LAST_TEXT[:] = ["".join(v for k, v in parts if k == "text")]
        if "extras" in (schema.get("properties") or {}):  # agent call 1 (wide, blind)
            return Reply(json.dumps(to_call1_wire(obs, distance_m=0.2 if mode == "inconsistent" else 5.35)),
                         f"fake-model-{mode}", None, usage)
        if "evidence" in (schema.get("properties") or {}):  # grounded_v2 request / agent call 2
            return Reply(json.dumps(to_grounded_wire(obs, "osm_claim_checks" in schema["properties"], mode,
                                                     width_in="IMAGE_2" if len(imgs) > 1 else "IMAGE_1")),
                         f"fake-model-{mode}", None, usage)
        return Reply(json.dumps(to_wire(obs)), f"fake-model-{mode}", None, usage)


LAST_TEXT = [""]


def to_grounded_wire(obs, with_claims, mode="ok", width_in="IMAGE_1"):
    """What a compliant model returns in grounded_v2: metres, positions in the image where seen, evidence."""
    w = to_wire(obs)
    re = w["road_edges"]; px = re.pop("traveled_way_width_px")
    re.update(traveled_way_width_m=7.3, width_measured_in=width_in)
    w["work_reference"].update(distance_to_nearest_edge_m=0.2 if mode == "inconsistent" else 8.4,
                               distance_measured_in="IMAGE_1")
    for items in w["features"].values():
        for it in items:
            x, y = it.pop("image_x"), it.pop("image_y")
            it.update(image="IMAGE_1" if x is not None else "NONE", x=x, y=y)
    w["evidence"] = {k: {"image": "IMAGE_1", "basis": f"fake basis for {k}"} for k in
                     ("lane_count", "two_way", "divided", "road_edges", "work_side", "work_location", "intersections", "pedestrian")}
    if with_claims:
        w["osm_claim_checks"] = [{"claim_id": "OSM-1", "seen": "YES", "classification": "PUBLIC_ROAD", "basis": "fake"}]
    return w


def to_call1_wire(obs, mpp=None, distance_m=5.35):
    """What a compliant model returns in agent call 1: metres, IMAGE_1 positions, extras, no osm_conflicts."""
    from tcp_planner.orchestration import offline_scenarios as offline
    mpp = mpp or 2 * offline.HALF / offline.SIZE
    w = to_wire(obs); w.pop("osm_conflicts")
    re = w["road_edges"]; px = re.pop("traveled_way_width_px")
    re.update(traveled_way_width_m=None if px is None else round(px * mpp, 3),
              width_measured_in="NONE" if px is None else "IMAGE_1")
    w["work_reference"].update(distance_to_nearest_edge_m=distance_m, distance_measured_in="IMAGE_1")
    for items in w["features"].values():
        for it in items:
            x, y = it.pop("image_x"), it.pop("image_y")
            it.update(image="IMAGE_1" if x is not None else "NONE", x=x, y=y)
    w["extras"] = []
    return w


def write_profiles(path):
    doc = {"default_profile": "fake-a", "profiles": {
        "fake-a": {"display_name": "Fake A", "deployment": "dep-ok", "api": "fake_api", "enabled": True},
        "fake-b": {"display_name": "Fake B", "deployment": "dep-low", "api": "fake_api", "enabled": True},
        "fake-fail": {"display_name": "Fake fail", "deployment": "dep-fail", "api": "fake_api", "enabled": True},
        "fake-inconsistent": {"display_name": "Fake inconsistent", "deployment": "dep-inconsistent", "api": "fake_api"},
        "disabled-one": {"deployment": "dep-x", "api": "fake_api", "enabled": False}}}
    with open(path, "w", encoding="utf-8") as f: json.dump(doc, f)
    return path
