"""Storage keys for uploaded KML files (S2 decision: sanitize the key, keep the original name as data).

The key is <run_id>/input/<slug>.kml. The original file name is not part of the key: it stays in request.kml_filename
(UI label) and is passed explicitly to the parser as source.file, so outputs do not depend on the key.
"""
import hashlib, re

_KEEP = re.compile(r"[^A-Za-z0-9._-]")
_KML_EXT = re.compile(r"\.kml$", re.IGNORECASE)
KML_MEDIA_TYPE = "application/vnd.google-earth.kml+xml"


def slug(original_name):
    """Letters, digits, '.', '_' and '-' kept; everything else becomes '_'; leading non-alphanumerics stripped; 'input'
    if nothing is left. Always ends in .kml."""
    stem = _KML_EXT.sub("", original_name or "")
    stem = _KEEP.sub("_", stem).lstrip("._-")
    stem = re.sub(r"^_+", "", stem)  # '_' from replaced characters is a leading non-alphanumeric too
    return (stem or "input") + ".kml"


def upload_key(run_id, original_name, data, taken=lambda key: None):
    """Key for an upload. `taken(key)` returns the sha256 held at that key, or None when it is free. If another upload in
    the run already cleaned to the same key with different bytes, a short hash of the name and content is added, so
    nothing is overwritten."""
    base = f"{run_id}/input/{slug(original_name)}"
    sha = hashlib.sha256(data).hexdigest()
    held = taken(base)
    if held is None or held == sha:
        return base
    short = hashlib.sha256((original_name or "").encode("utf-8") + b"\0" + data).hexdigest()[:8]
    return f"{base[:-len('.kml')]}-{short}.kml"


def store_upload(store, run_id, original_name, data):
    """Put the bytes under the sanitized key and return the ArtifactRef."""
    key = upload_key(run_id, original_name, data, lambda k: (store.stat(k).sha256 if store.stat(k) else None))
    return store.put(key, data, KML_MEDIA_TYPE)
