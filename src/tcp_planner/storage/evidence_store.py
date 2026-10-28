"""Evidence artifacts for UI runs: persist external-provider results at acquisition and replay verified ones.

<run>/evidence/manifest.state.json (a state record; old runs have manifest.json) lists every artifact the run used:
  - "saved": produced by this run (file in this run's evidence/ folder)
  - "reference": reused from an earlier run (path + SHA-256 of the source file; nothing copied)
Artifacts: map images (PNG, lossless) + georeference, raw OSM elements, AI results (sanitized raw response +
normalized observation). No credentials or URLs are stored.

Replay is used only through run_pipeline's own injection points (map_provider / osm_source / vision_provider).
A replay answers a call only when the saved artifact matches the EXACT request the pipeline is making now
(request signature), the file exists, its hash matches and its content loads and validates; otherwise the real
provider is called and the reason is recorded. The pipeline's own logic runs unchanged either way.
"""
import datetime, hashlib, io, json, os, threading

from tcp_planner.contracts import canonical_json, sha256_hex
from tcp_planner.storage import stores
from tcp_planner.storage.interfaces import (ArtifactRef, ArtifactMissing, IntegrityError, StateExists, StaleHead,
                                            StorageError, media_type_for_key)

MANIFEST = "manifest.json"
ANALYSIS_SPANS = {"map": "tcp.map.retrieve", "osm": "tcp.osm.resolve", "ai": "tcp.vision.analyze"}
KIND_STAGE = {"map": "imagery", "osm": "osm", "ai": "vision"}
OFFLINE_PROVIDERS = {"offline_synthetic", "offline_static"}
MAP_META_REQUIRED = ("center", "bounding_box", "metres_per_pixel", "width_pixels", "height_pixels", "ground_extent_m")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def pixel_hash(img):
    return sha256_bytes(f"{img.mode}:{img.size[0]}x{img.size[1]}:".encode() + img.tobytes())


def signature_hash(sig):
    return sha256_hex(canonical_json(sig))


def geometry_hash(pg):
    return sha256_hex(canonical_json({"work_reference": pg["work_reference"], "work_path": pg.get("work_path") or []}))


# ---------------------------------------------------------------- request signatures (what a reuse must match)
def map_signature(provider, pg, half_extent_m, size_px):
    return {"kind": "map", "provider": getattr(provider, "name", None),
            "scale_model": getattr(provider, "SCALE_MODEL", None), "api_version": getattr(provider, "API_VERSION", None),
            "service": getattr(provider, "SERVICE", None), "geometry_hash": geometry_hash(pg),
            "half_extent_m": round(float(half_extent_m), 6), "size_px": int(size_px)}


def osm_signature(source, lat, lon, radius_m):
    return {"kind": "osm", "source": source, "lat": round(float(lat), 7), "lon": round(float(lon), 7),
            "radius_m": round(float(radius_m), 6)}


def ai_signature(image, context, views=None):
    """AI evidence is keyed by its exact inputs: image pixels, extra-view pixels and the pipeline-computed context."""
    sig = {"kind": "ai", "image_pixel_sha256": pixel_hash(image), "context_hash": sha256_hex(canonical_json(context))}
    if views:
        sig.update(evidence_mode="multi", views=[{"role": v["role"], "pixel_sha256": pixel_hash(v["image"])} for v in views])
    return sig


# ---------------------------------------------------------------- per-run store
MANIFEST_SCHEMA_VERSION = 1


def evidence_key(run_id, name):
    return f"{run_id}/evidence/{name}"


MANIFEST_KEY = "evidence/manifest"  # a state record in the run's own folder: <run>/evidence/manifest.state.json


class EvidenceStore:
    """Evidence of one run: blobs in the ArtifactStore (<run_id>/evidence/<file>), the manifest as a state record in the
    run's own folder (D-84, files only), so a run folder stays self-contained."""

    def __init__(self, run_id, events=None):
        self.run_id = run_id
        self.events = events or (lambda **ev: None); self.lock = threading.Lock(); self.entries = []

    def _write_manifest(self):
        doc = json.loads(json.dumps({"run_id": self.run_id, "artifacts": self.entries}, default=str))
        state = stores.run_state(self.run_id, create=True); key = MANIFEST_KEY
        for _ in range(5):
            cur = state.get(key)
            try:
                if cur is None: state.put_new(key, doc, MANIFEST_SCHEMA_VERSION)
                else: state.compare_and_set(key, cur.version, doc, MANIFEST_SCHEMA_VERSION)
                return
            except (StateExists, StaleHead):
                continue
        raise StaleHead(f"evidence manifest of {self.run_id} kept changing")

    def save(self, kind, data, ext, signature, metadata, span):
        with self.lock:
            n = sum(1 for e in self.entries if e["kind"] == kind) + 1
            name = f"{kind}_{n}.{ext}"
            key = evidence_key(self.run_id, name)
            stores.artifacts().put(key, data, media_type_for_key(key))
            entry = {"artifact_id": f"{kind}_{n}", "kind": kind, "mode": "saved", "file": name,
                     "sha256": sha256_bytes(data), "size_bytes": len(data), "signature": signature,
                     "signature_hash": signature_hash(signature), "metadata": metadata,
                     "produced_by_run": self.run_id, "producer_span": span, "created_at": now_iso()}
            self.entries.append(entry); self._write_manifest()
        self.events(event="evidence", action="saved", kind=kind, artifact_id=entry["artifact_id"], span=span,
                    sha256=entry["sha256"], file=name)
        return entry

    def reference(self, source, span):
        """Record reuse of a verified artifact from an earlier run (no copy)."""
        with self.lock:
            n = sum(1 for e in self.entries if e["kind"] == source["kind"]) + 1
            entry = {"artifact_id": f"{source['kind']}_{n}", "kind": source["kind"], "mode": "reference",
                     "source_run": source["origin_run"], "source_artifact_id": source["origin_artifact_id"],
                     "source_file": source["origin_file"], "sha256": source["sha256"],
                     "signature": source["signature"], "signature_hash": source["signature_hash"],
                     "metadata": source["metadata"], "producer_span": span, "created_at": now_iso()}
            self.entries.append(entry); self._write_manifest()
        self.events(event="evidence", action="reused", kind=entry["kind"], artifact_id=entry["artifact_id"], span=span,
                    sha256=entry["sha256"], source_run=entry["source_run"], source_artifact_id=entry["source_artifact_id"])
        return entry


def load_manifest(run_id):
    """Evidence entries of a run. Runs from before the StateStore (old POC runs, D-77) keep their manifest.json file;
    it is read here, read-only."""
    state = stores.run_state(run_id)
    rec = state.get(MANIFEST_KEY) if state is not None else None
    if rec is not None: return rec.value.get("artifacts", [])
    try:
        return json.loads(stores.artifacts().get(evidence_key(run_id, MANIFEST)).decode("utf-8")).get("artifacts", [])
    except (ArtifactMissing, StorageError, ValueError):
        return []


def resolve(run_id, entry):
    """Follow references to the run that produced the file. Returns a dict with the origin run, file and an
    ArtifactRef ("ref") to read it through the ArtifactStore, or None."""
    if entry.get("mode") == "saved":
        uri = evidence_key(run_id, entry["file"])
        return {**entry, "origin_run": run_id, "origin_artifact_id": entry["artifact_id"], "origin_file": entry["file"],
                "ref": ArtifactRef(uri, entry["sha256"], int(entry.get("size_bytes", -1)), media_type_for_key(uri))}
    if entry.get("mode") == "reference":
        src = entry.get("source_run"); aid = entry.get("source_artifact_id")
        if not src or not aid: return None
        for e in load_manifest(src):
            if e.get("artifact_id") == aid and e.get("mode") == "saved" and e.get("sha256") == entry.get("sha256"):
                return resolve(src, e)
    return None


def read_bytes(resolved):
    """The artifact's bytes, verified against its recorded sha256 (ArtifactMissing / IntegrityError otherwise)."""
    return stores.artifacts().get(resolved["ref"])


def verify_file(resolved):
    if resolved is None: return "artifact reference cannot be resolved"
    try: read_bytes(resolved)
    except ArtifactMissing: return "artifact file missing"
    except IntegrityError: return "artifact hash mismatch (file changed or corrupt)"
    return None


class ReplaySource:
    """Verified artifacts of a parent run that a resumed run may reuse, by kind."""

    def __init__(self, parent_run_id, kinds, extra_sources=()):
        """extra_sources: further evidence holders (e.g. a comparison's prepared views), read the same way."""
        self.parent = parent_run_id; self.kinds = set(kinds)
        self.entries = [resolve(src, e) or {"_unresolved": e}
                        for src in [parent_run_id, *extra_sources] for e in load_manifest(src)]

    def allows(self, kind):
        return kind in self.kinds

    def find(self, kind, sig):
        """(resolved entry, None) when a verified artifact matches this exact request; else (None, reason)."""
        h = signature_hash(sig)
        cands = [e for e in self.entries if not e.get("_unresolved") and e["kind"] == kind]
        if not cands:
            bad = [e for e in self.entries if e.get("_unresolved", {}).get("kind") == kind]
            return None, ("source artifact reference cannot be resolved" if bad
                          else f"source run {self.parent} has no saved {kind} artifact")
        match = [e for e in cands if e["signature_hash"] == h]
        if not match:
            diff = sorted(k for k in sig if any(c["signature"].get(k) != sig[k] for c in cands))
            return None, f"request differs from the saved {kind} artifact ({', '.join(diff) or 'signature'})"
        e = match[-1]
        problem = verify_file(e)
        return (None, problem) if problem else (e, None)
