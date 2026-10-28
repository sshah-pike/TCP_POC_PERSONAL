"""Fixture store keyed by a request fingerprint (sha256 of the canonical request), one directory per recorded site.

    <site>/site.json          input description (operator facts, AI profile, where the fixtures came from)
    <site>/input.kml
    <site>/map/<fp>.png|json  analysis image / crop and its georeference metadata
    <site>/osm/<fp>.json      OSM elements
    <site>/ai/<fp>.json       AI result {"request": fingerprint request, "result": provider result}
Every record carries schema_version. Fixtures are write-once: saving over an existing fingerprint with different
content is an error.
"""
import hashlib, io, json, os

SCHEMA_VERSION = 1


class MissingFixtureError(LookupError):
    """Replay asked for a call that was never recorded. Names the kind and the request so the gap is easy to find."""

    def __init__(self, site, kind, fp, request):
        self.kind, self.fingerprint, self.request = kind, fp, request
        super().__init__(f"no recorded {kind} fixture for site '{site}' (fingerprint {fp[:16]}...). Request: "
                         f"{json.dumps(request, sort_keys=True)[:400]}. Replay never makes a live call; record it with "
                         "python -m tests.support.record (TCP_LIVE=1, run by the user) or seed it from a saved run.")


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(request):
    """sha256 of the canonical request. The request always carries its 'kind'."""
    return hashlib.sha256(canonical(request).encode("utf-8")).hexdigest()


class FixtureStore:
    def __init__(self, site_dir):
        self.dir = site_dir
        self.site = os.path.basename(os.path.normpath(site_dir))

    def _path(self, kind, fp, ext):
        return os.path.join(self.dir, kind, f"{fp}.{ext}")

    def has(self, kind, fp):
        return os.path.isfile(self._path(kind, fp, "json"))

    def load(self, kind, request):
        fp = fingerprint(request)
        if not self.has(kind, fp): raise MissingFixtureError(self.site, kind, fp, request)
        with open(self._path(kind, fp, "json"), encoding="utf-8") as f: doc = json.load(f)
        if doc.get("schema_version") != SCHEMA_VERSION or doc.get("fingerprint") != fp:
            raise ValueError(f"fixture {kind}/{fp[:16]} is not schema_version {SCHEMA_VERSION} for this fingerprint")
        return doc, fp

    def load_image(self, kind, fp, doc):
        from PIL import Image
        path = self._path(kind, fp, "png")
        with open(path, "rb") as f: data = f.read()
        if hashlib.sha256(data).hexdigest() != doc["image"]["sha256"]: raise ValueError(f"fixture image {path} changed")
        return Image.open(io.BytesIO(data)).convert("RGB")

    def save(self, kind, request, body, image_png=None):
        """Write-once. body is JSON-safe. Returns the fingerprint."""
        fp = fingerprint(request)
        doc = {"schema_version": SCHEMA_VERSION, "kind": kind, "fingerprint": fp, "request": request, **body}
        if image_png is not None:
            doc["image"] = {"sha256": hashlib.sha256(image_png).hexdigest(), "size": len(image_png), "media_type": "image/png"}
        text = json.dumps(doc, indent=1, sort_keys=True)
        path = self._path(kind, fp, "json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f: same = f.read() == text
            if not same:
                raise FileExistsError(f"fixture {kind}/{fp[:16]} exists with different content (fixtures are write-once)")
            return fp
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if image_png is not None:
            with open(self._path(kind, fp, "png"), "wb") as f: f.write(image_png)
        with open(path, "w", encoding="utf-8") as f: f.write(text)
        return fp
