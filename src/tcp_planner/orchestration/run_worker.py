"""Execute ONE pipeline run for the UI, in its own process:   python -m tcp_planner.orchestration.run_worker <run_id>

The run is the unmodified CLI entry point `tcp_planner.orchestration.pipeline.main(argv)` with the argv stored in
the run's request record (ui/request, see storage/run_records.py), so argument handling, .env loading, TLS setup, offline scenarios, outputs
and exit codes are exactly those of `python -m tcp_planner.cli ...`.

Observation only (installed in this child process, nothing in tcp_planner is edited):
  - Telemetry subclass: the existing spans, additionally streamed to the run's event stream as they start/end
  - run_pipeline / load_rule_pack wrappers: record the returned result / rule-pack identity, return them unchanged
  - Anthropic client subclass: records response.usage and response.model of each Messages call
  - map provider / OSM fetch wrappers: on failure record a sanitized diagnostic, then re-raise the SAME
    exception unchanged (the pipeline still decides MAP_REQUEST_FAILED -> REVIEW_REQUIRED itself)
  - TLS: the CLI's own app.use_os_trust_store() runs first; the trust store actually in effect is recorded
A recorder write or event that fails never alters a decision or an output: the failure is printed once per distinct
error to stdout.log (nothing is silently dropped) and the run goes on. Only the final process record is different: it is
retried and, if it still fails, raises, so a run never ends looking as if it were still running.
"""
import contextlib, datetime, io, json, os, sys, threading, time, traceback


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


class RecorderWriteError(Exception):
    pass


def _plain(obj):
    """obj as plain JSON data (what the former json.dump(default=str) wrote): unknown types as text, tuples as lists,
    NaN and Infinity as text."""
    return json.loads(json.dumps(obj, default=str, sort_keys=True), parse_constant=str)


class Recorder:
    """Writes the run's UI records and events through run_records (state records in the run's own folder)."""

    def __init__(self, run_id):
        self.run_id = run_id; self.lock = threading.Lock(); self.usage = []; self.diagnostics = []
        self.open_spans = []  # names of telemetry spans currently running (innermost last)
        self._reported = set()

    def _fail(self, what, error):
        """One line per distinct error per run, to stdout (= stdout.log)."""
        from tcp_planner.audit.provider_diagnostics import sanitize
        text = sanitize(f"{type(error).__name__}: {error}")
        if (what, text) in self._reported: return
        self._reported.add((what, text))
        print(f"[recorder] {what} failed: {text}", flush=True)

    def note(self, what, error):
        """For an observer that could not record something: reported once per distinct error, the run goes on."""
        self._fail(what, error)

    def event(self, durable=False, **ev):
        """durable=True for state-changing events (fsynced); progress events are flushed only."""
        from tcp_planner.storage import run_records
        try:
            ev["t"] = now_iso()
            with self.lock: run_records.append_event(self.run_id, _plain(ev), durable=durable)
        except Exception as e:
            self._fail("event " + str(ev.get("event")), e)

    def _put(self, name, obj):
        from tcp_planner.storage import run_records
        with self.lock: run_records.write(self.run_id, name, _plain(obj))

    def write(self, name, obj):
        try:
            self._put(name, obj)
            return True
        except Exception as e:
            self._fail("write " + name, e)
            return False

    def write_final(self, name, obj, attempts=3):
        """The record that ends the run: retried, and raised if it still fails."""
        last = None
        for i in range(attempts):
            try:
                self._put(name, obj)
                return
            except Exception as e:
                last = e; self._fail("write " + name, e); time.sleep(0.2 * (i + 1))
        raise RecorderWriteError(f"could not write the {name} record after {attempts} tries: {last}") from last

    def add_usage(self, item):
        self.usage.append(item); self.write("usage", self.usage)

    def add_diagnostic(self, item):
        item["span"] = self.span()
        self.diagnostics.append(item); self.write("diagnostics", self.diagnostics)

    def add_call(self, item):
        """A provider call this run actually made (reused artifacts are not calls)."""
        item["span"] = self.span()
        self.calls = getattr(self, "calls", []); self.calls.append(item); self.write("calls", self.calls)

    def span(self):
        """Innermost open pipeline-stage span. The agent's step spans (tcp.agent.*) run inside tcp.vision.analyze;
        evidence, calls and diagnostics belong to the stage, so they are skipped here."""
        return next((s for s in reversed(self.open_spans) if not s.startswith("tcp.agent.")), None)


def _result_record(res, run_id):
    """The pipeline result as the run's result record: no absolute path (D-77). out_dir becomes the run-relative key."""
    rec = dict(res)
    if "out_dir" in rec: rec["out_key"] = f"{run_id}/output"; del rec["out_dir"]
    refs = rec.pop("output_refs", None)
    if refs is not None:  # the output index: {name, uri (run-relative key), sha256, size, media_type} per output file
        rec["output_index"] = [{"name": x["name"], "uri": f"{run_id}/output/{x['uri']}", "sha256": x["sha256"],
                                "size": x["size"], "media_type": x["media_type"]} for x in refs]
    return rec


def install_observers(rec, run=None):
    """run: {"run_dir", "run_id", "replay": ReplaySource|None, "ai_provider": str|None} (None = no evidence)."""
    from tcp_planner.orchestration import pipeline as app
    from tcp_planner.audit import telemetry

    base = telemetry.Telemetry

    class ObservedTelemetry(base):
        @contextlib.contextmanager
        def span(self, name, **attrs):
            rec.event(event="span_start", name=name, attributes=telemetry._safe_attrs(attrs))
            rec.open_spans.append(name)
            r = None
            try:
                with base.span(self, name, **attrs) as r:
                    yield r
            finally:
                rec.open_spans.pop()
                if r is not None:
                    rec.event(event="span_end", name=name, status=r.get("status"),
                              duration_ms=r.get("duration_ms"), attributes=r.get("attributes"))

    app.Telemetry = ObservedTelemetry

    orig_run = app.run_pipeline
    ev = _Evidence(rec, run)  # store is None (diagnostics/calls only) when run is None

    def observed_run_pipeline(**kw):
        if True:  # run_pipeline's own injection points; its logic is untouched
            if run and run.get("ai_provider"):  # resumed / comparison run with a selected AI provider
                try: kw["vision_provider"] = app.get_vision_provider(run["ai_provider"])
                except Exception as e: kw["vision_provider"] = e  # same as the CLI: provider error -> AI unavailable
            if kw.get("map_provider") is not None and not isinstance(kw["map_provider"], EvidenceMapProvider):
                kw["map_provider"] = EvidenceMapProvider(kw["map_provider"], ev)
            if kw.get("osm_source") is not None:
                kw["osm_source"] = EvidenceOsmSource(kw["osm_source"], ev, "injected")
            vp = kw.get("vision_provider")
            if vp is not None and not isinstance(vp, (Exception, EvidenceVisionProvider)):
                kw["vision_provider"] = EvidenceVisionProvider(vp, ev)
        res = orig_run(**kw)
        rec.write("result", _result_record(res, rec.run_id))
        rec.event(event="run_result", durable=True)
        return res

    app.run_pipeline = observed_run_pipeline

    orig_load = app.load_rule_pack

    def observed_load_rule_pack(*a, **k):
        pack = orig_load(*a, **k)
        try:
            rec.write("rule_pack", {"id": pack.id, "version": pack.version, "status": pack.status,
                                         "hash": pack.hash, "selected_ta": pack.selected_ta(),
                                         "file": os.path.basename(pack.path)})
        except Exception as e:
            rec.note("rule pack record", e)
        return pack

    app.load_rule_pack = observed_load_rule_pack

    # TLS: run the CLI's own trust-store setup first, exactly as `python -m tcp_planner.cli` does, and only then
    # import the Anthropic SDK - so no HTTP library is loaded before truststore is injected.
    orig_trust = app.use_os_trust_store

    def trust_then_observe():
        orig_trust()
        try:
            import ssl
            mod = ssl.SSLContext.__module__
            rec.write("tls", {"ssl_context": f"{mod}.SSLContext",
                                   "trust_store": "WINDOWS_SYSTEM_STORE (truststore)" if mod.startswith("truststore")
                                   else "PYTHON_DEFAULT (truststore not active)"})
        except Exception as e:
            rec.note("tls record", e)
        _install_anthropic_usage(rec)

    app.use_os_trust_store = trust_then_observe

    orig_get_map = app.get_map_provider
    app.get_map_provider = lambda *a, **k: EvidenceMapProvider(orig_get_map(*a, **k), ev)  # errors propagate
    orig_get_vision = app.get_vision_provider

    def get_vision_provider(*a, **k):
        return EvidenceVisionProvider(orig_get_vision(*a, **k), ev)  # ProviderError propagates unchanged

    app.get_vision_provider = get_vision_provider
    osm = app.osm_adapter
    osm.fetch_osm = EvidenceOsmSource(osm.fetch_osm, ev, "osm_api")


def _record(rec, error, provider, t0):
    try:
        from tcp_planner.audit.provider_diagnostics import describe
        rec.add_diagnostic(describe(error, provider, round((time.perf_counter() - t0) * 1000, 1)))
    except Exception as e:
        rec.note("provider diagnostic record", e)


class _Evidence:
    """Shared state of the evidence wrappers for one run. store is None when evidence is not recorded."""

    def __init__(self, rec, run):
        self.rec = rec
        self.store = self.replay = None
        self.evidence_mode = (run or {}).get("evidence_mode") or "single"
        self.vision_mode = (run or {}).get("vision_mode") or "baseline"
        self.osm_claims = bool((run or {}).get("osm_claims"))
        self.centerline_views = bool((run or {}).get("centerline_views"))
        self.strict = bool((run or {}).get("strict_replay"))  # SME revision runs: replay or fail, never call a provider
        self.analysis = None  # (map provider, project geometry, half extent) of the analysis image
        self.osm_elements = None  # OSM elements the pipeline used (fetched or replayed)
        self._osm_geo = None
        if run:
            from tcp_planner.storage.evidence_store import EvidenceStore
            self.store = EvidenceStore(run["run_id"], rec.event)
            self.replay = run.get("replay")

    def views(self, context):
        """The fixed multi-resolution view set for this site: reused when a verified copy exists, else acquired."""
        from PIL import Image
        from tcp_planner.storage import evidence_store as E
        from tcp_planner.imagery import evidence_views as V
        from tcp_planner.contracts import ProviderError
        if self.analysis is None:
            raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "no analysis imagery to plan multi-resolution views from")
        inner, pg, half = self.analysis
        if not hasattr(inner, "fetch_view"):
            raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "map provider %s cannot supply views" % getattr(inner, "name", "?"))
        out = []
        if self.centerline_views:
            geo = self.osm_geometry(pg)
            if geo is None: raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "OSM centerline unavailable for centerline views")
            plan = V.plan_views_centerline(pg["work_reference"], geo["centerline_enu"], geo["work_station_m"], half)
        else:
            plan = V.plan_views(pg["work_reference"], context["reference_bearing_deg"], half)
        for spec in plan:
            sig = V.view_signature(inner, spec, E.geometry_hash(pg))
            found = self.try_reuse(V.VIEW_KIND, sig) if self.store else None
            if found is not None:
                try:
                    with Image.open(io.BytesIO(E.read_bytes(found))) as im: img = im.convert("RGB")
                    if E.pixel_hash(img) != found["metadata"].get("pixel_sha256"): raise ValueError("pixel hash mismatch")
                    self.accept(found)
                    out.append({**spec, "image": img, "meta": found["metadata"]["meta"]}); continue
                except Exception as e:
                    self.reject(V.VIEW_KIND, "saved view failed validation (%s)" % e)
            self.strict_block(V.VIEW_KIND, ProviderError)
            t0 = time.perf_counter()
            try:
                img, meta = inner.fetch_view(spec["lat"], spec["lon"], spec["zoom"], spec["size_px"])
            except Exception as e:
                _record(self.rec, e, getattr(inner, "name", None), t0)
                raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "multi-resolution view %s unavailable (%s)"
                                    % (spec["role"], getattr(e, "code", type(e).__name__)))
            name = getattr(inner, "name", None)
            self.rec.add_call({"service": "map", "provider": name, "external": name not in E.OFFLINE_PROVIDERS,
                               "requests": int(meta.get("request_tiles", 1)), "purpose": "view:" + spec["role"],
                               "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
            if self.store:
                buf = io.BytesIO(); img.save(buf, "PNG")
                self.save(V.VIEW_KIND, buf.getvalue(), "png", sig,
                          {"meta": meta, "role": spec["role"], "label": spec["label"], "offset_m": spec["offset_m"],
                           "format": "PNG", "pixel_sha256": E.pixel_hash(img)})
            out.append({**spec, "image": img, "meta": meta})
        return out

    def osm_geometry(self, pg):
        """Centerline/station/lateral of the work reference from the OSM elements this run used (pure functions)."""
        if self._osm_geo is not None or self.osm_elements is None: return self._osm_geo
        from tcp_planner.orchestration import pipeline as app
        from tcp_planner.data_sources import osm_overpass as osm_adapter
        from tcp_planner.geometry.local_frame import signed_lateral
        osm = osm_adapter.extract_evidence(self.osm_elements, pg, app.load_config())
        d, s0, lat = signed_lateral(osm["centerline_enu"], (0.0, 0.0))
        self._osm_geo = {"osm": osm, "centerline_enu": osm["centerline_enu"], "work_station_m": s0, "lateral_m": lat}
        return self._osm_geo

    def grounding(self, context):
        """Inputs for grounded_v2: deterministic work side (diagnostic C3 only) and optional OSM claims."""
        if self.vision_mode != "grounded_v2": return None
        from tcp_planner.orchestration import pipeline as app
        from tcp_planner.geometry.local_frame import at
        pg = self.analysis[1] if self.analysis else None
        geo = self.osm_geometry(pg) if pg else None
        g = {"mode": "grounded_v2", "geo_side": None, "claims": None,
             "lane_width_plausible_m": app.load_config()["fusion"].get("lane_width_plausible_m")}
        if geo:
            mn = app.load_config()["fusion"]["work_side_min_lateral_m"]
            g["geo_side"] = None if abs(geo["lateral_m"]) < mn else ("LEFT" if geo["lateral_m"] > 0 else "RIGHT")
        if self.osm_claims and geo:
            W, H, mpp = context["image_width_px"], context["image_height_px"], context["metres_per_pixel"]
            mapped = {"intersections": "PUBLIC_ROAD", "roundabouts": "PUBLIC_ROAD", "ramps": "PUBLIC_ROAD",
                      "driveways": "DRIVEWAY_OR_SERVICE", "crosswalks": "CROSSWALK"}
            claims = []
            for kind, cls in mapped.items():
                for f in geo["osm"]["features"].get(kind, []):
                    (x, y), _ = at(geo["centerline_enu"], f["station_m"])
                    px, py = W / 2 + x / mpp, H / 2 - y / mpp
                    if not (0 <= px < W and 0 <= py < H): continue
                    side = f.get("side")
                    claims.append({"claim_id": f"OSM-{len(claims) + 1}", "mapped_as": cls, "highway": f.get("highway"),
                                   "osm_kind": kind, "osm_id": f.get("way_id") or f.get("node_id"),
                                   "image_1_px": [round(px, 1), round(py, 1)],
                                   "side_hint": f"{side.lower()} side of the selected road" if side in ("LEFT", "RIGHT", "BOTH")
                                   else "side not mapped"})
            g["claims"] = claims
        return g

    def try_reuse(self, kind, sig, allow_kind=None):
        """Verified artifact for this exact request, or None (a rejection is recorded with its reason).
        allow_kind: the reuse permission that covers this kind (agent crops are imagery: allowed with "map")."""
        if not (self.replay and self.replay.allows(allow_kind or kind)): return None
        try:
            found, reason = self.replay.find(kind, sig)
        except Exception as e:
            found, reason = None, f"reuse check failed ({type(e).__name__})"
        if found is None:
            self.rec.event(event="evidence", action="reuse_rejected", kind=kind, span=self.rec.span(), reason=reason,
                           source_run=self.replay.parent)
        return found

    def strict_block(self, kind, error_cls):
        """Strict replay: no verified saved artifact for this exact request -> fail closed instead of calling the provider."""
        if not self.strict: return
        self.rec.event(event="evidence", action="strict_replay_blocked", kind=kind, span=self.rec.span(),
                       source_run=self.replay.parent if self.replay else None)
        raise error_cls("REPLAY_EVIDENCE_REQUIRED", f"strict replay: no verified saved {kind} artifact matches this "
                                                    "request; the provider is not called")

    def accept(self, found):
        self.store.reference(found, self.rec.span())

    def reject(self, kind, reason):
        self.rec.event(event="evidence", action="reuse_rejected", kind=kind, span=self.rec.span(), reason=reason,
                       source_run=self.replay.parent if self.replay else None)

    def save(self, *a):
        if self.store is None: return
        try: self.store.save(*a, self.rec.span())
        except Exception as e:
            self.rec.event(event="evidence", action="save_failed", kind=a[0], reason=type(e).__name__)


class EvidenceMapProvider:
    """Real map provider + diagnostics + persistence at acquisition + verified replay for resumed runs."""

    def __init__(self, inner, ev):
        self._inner = inner; self._ev = ev; self.last_reused = False; self.purpose = None

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def fetch_context(self, project_geometry, half_extent_m, size_px):
        from tcp_planner.storage import evidence_store as E
        ev, inner = self._ev, self._inner
        if ev.rec.span() == E.ANALYSIS_SPANS["map"]:
            ev.analysis = (inner, project_geometry, half_extent_m)
        sig = E.map_signature(inner, project_geometry, half_extent_m, size_px) if ev.store else None
        found = ev.try_reuse("map", sig) if sig else None
        if found is not None:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(E.read_bytes(found))) as im: img = im.convert("RGB")
                meta = found["metadata"]["meta"]
                if img.size != (int(size_px), int(size_px)) or any(k not in meta for k in E.MAP_META_REQUIRED) \
                        or E.pixel_hash(img) != found["metadata"].get("pixel_sha256"):
                    raise ValueError("saved image or georeference metadata incomplete")
                ev.accept(found)
                return img, dict(meta)
            except Exception as e:
                ev.reject("map", f"saved map artifact failed validation ({e})")
        from tcp_planner.contracts import MapProviderError
        ev.strict_block("map", MapProviderError)
        t0 = time.perf_counter()
        try:
            img, meta = inner.fetch_context(project_geometry, half_extent_m, size_px)
        except Exception as e:
            _record(ev.rec, e, getattr(inner, "name", None), t0)
            raise
        name = getattr(inner, "name", None)
        ev.rec.add_call({"service": "map", "provider": name, "external": name not in E.OFFLINE_PROVIDERS,
                         "requests": int(meta.get("request_tiles", 1)) if isinstance(meta, dict) else 1,
                         "purpose": "sheet aerial (display only)" if ev.rec.span() == "tcp.sheet.render" else "analysis map",
                         "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
        if sig:
            buf = io.BytesIO(); img.save(buf, "PNG")
            ev.save("map", buf.getvalue(), "png", sig,
                    {"meta": meta, "format": "PNG", "width": img.size[0], "height": img.size[1],
                     "pixel_sha256": E.pixel_hash(img), "geometry_hash": sig["geometry_hash"]})
        return img, meta

    def fetch_view(self, lat, lon, zoom, size_px):
        """Agent crop (and its sharpness-check companion): persisted at acquisition, reused on resume when the exact
        request matches a verified saved crop, recorded as a map call of the vision stage."""
        from tcp_planner.storage import evidence_store as E
        ev, inner = self._ev, self._inner
        name = getattr(inner, "name", None)
        sig = ({"kind": "map_crop", "provider": name, "scale_model": getattr(inner, "SCALE_MODEL", None),
                "api_version": getattr(inner, "API_VERSION", None), "zoom": int(zoom), "lat": round(float(lat), 7),
                "lon": round(float(lon), 7), "size_px": int(size_px)} if ev.store else None)
        found = ev.try_reuse("map_crop", sig, allow_kind="map") if sig else None
        if found is not None:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(E.read_bytes(found))) as im: img = im.convert("RGB")
                if E.pixel_hash(img) != found["metadata"].get("pixel_sha256"): raise ValueError("pixel hash mismatch")
                ev.accept(found); self.last_reused = True
                return img, dict(found["metadata"]["meta"])
            except Exception as e:
                ev.reject("map_crop", f"saved crop failed validation ({e})")
        from tcp_planner.contracts import MapProviderError
        ev.strict_block("map_crop", MapProviderError)
        t0 = time.perf_counter()
        try:
            img, meta = inner.fetch_view(lat, lon, zoom, size_px)
        except Exception as e:
            _record(ev.rec, e, name, t0)
            raise
        ev.rec.add_call({"service": "map", "provider": name, "external": name not in E.OFFLINE_PROVIDERS,
                         "requests": int(meta.get("request_tiles", 1)), "purpose": f"{self.purpose or 'agent crop'} (zoom {int(zoom)})",
                         "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
        if sig:
            buf = io.BytesIO(); img.save(buf, "PNG")
            ev.save("map_crop", buf.getvalue(), "png", sig, {"meta": meta, "format": "PNG", "pixel_sha256": E.pixel_hash(img)})
        return img, meta


class EvidenceOsmSource:
    """OSM fetch (real API or injected source) + diagnostics + persistence + verified replay."""

    def __init__(self, fetch, ev, source):
        self._fetch = fetch; self._ev = ev; self._source = source

    def __call__(self, lat, lon, radius_m):
        from tcp_planner.storage import evidence_store as E
        ev = self._ev
        sig = E.osm_signature(self._source, lat, lon, radius_m) if ev.store else None
        found = ev.try_reuse("osm", sig) if sig else None
        if found is not None:
            try:
                elements = json.loads(E.read_bytes(found).decode("utf-8"))
                if not isinstance(elements, list): raise ValueError("not a list of OSM elements")
                ev.accept(found); ev.osm_elements = elements
                return elements
            except Exception as e:
                ev.reject("osm", f"saved OSM artifact failed validation ({e})")
        from tcp_planner.contracts import OsmError
        ev.strict_block("osm", OsmError)
        t0 = time.perf_counter()
        try:
            elements = self._fetch(lat, lon, radius_m)
        except Exception as e:
            _record(ev.rec, e, "osm_api" if self._source == "osm_api" else self._source, t0)
            raise
        ev.osm_elements = elements
        ev.rec.add_call({"service": "osm", "provider": self._source, "external": self._source == "osm_api",
                         "requests": 1, "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
        if sig:
            ev.save("osm", json.dumps(elements, sort_keys=True).encode("utf-8"), "json", sig,
                    {"element_count": len(elements)})
        return elements


class EvidenceVisionProvider:
    """Vision provider + persistence of the (sanitized) result + verified replay when resuming after AI."""

    def __init__(self, inner, ev):
        self._inner = inner; self._ev = ev

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def analyze(self, image, context, views=None, grounding=None):
        from tcp_planner.storage import evidence_store as E
        from tcp_planner.audit.provider_diagnostics import sanitize, sanitize_obj
        from tcp_planner.ai.vision_provider import validate_observation
        from tcp_planner.contracts import ProviderError
        ev = self._ev
        agent_call = str((grounding or {}).get("mode", "")).startswith("agent_")
        if not agent_call:  # legacy UI evidence modes; agent calls bring their own views and request from the pipeline
            views = None
            if ev.evidence_mode == "multi":
                if not getattr(self._inner, "supports_views", False):
                    raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "AI provider %s does not accept multi-resolution views"
                                        % getattr(self._inner, "name", "?"))
                views = ev.views(context)  # identical for every model: reused from the evidence set when verified
            grounding = ev.grounding(context)
            if grounding and not getattr(self._inner, "supports_views", False):
                raise ProviderError("AI_EVIDENCE_UNAVAILABLE", "AI provider %s does not support grounded_v2"
                                    % getattr(self._inner, "name", "?"))
        sig = E.ai_signature(image, context, views) if ev.store else None
        if sig and grounding and not agent_call:
            from tcp_planner.ai import grounded_vision as G
            sig.update(vision_mode="grounded_v2", annotation=G.ANNOTATION,
                       claims_hash=E.signature_hash({"claims": grounding.get("claims")}))
        if sig and agent_call: sig["vision_mode"] = grounding["mode"]
        if sig and hasattr(self._inner, "request_fingerprint"):
            try:  # prompt, schema and image-bytes hashes + model + profile: any change forces a new model call
                sig["request"] = self._inner.request_fingerprint(image, context, views=views, grounding=grounding)
            except Exception as e:
                sig["request"] = {"unavailable": type(e).__name__}  # cannot match a saved artifact -> new call
        found = ev.try_reuse("ai", sig) if sig else None
        if found is not None:
            try:
                doc = json.loads(E.read_bytes(found).decode("utf-8"))
                if doc.get("status") != "OK": raise ValueError("saved AI result is a failure")
                result = doc["result"]; validate_observation(result["observation"])
                ev.accept(found)
                return result
            except Exception as e:
                ev.reject("ai", f"saved AI artifact failed validation ({getattr(e, 'code', '') or e})")
        ev.strict_block("ai", ProviderError)
        t0 = time.perf_counter()
        meta = {"provider": getattr(self._inner, "name", None), "profile": getattr(self._inner, "profile", None),
                "deployment": getattr(self._inner, "deployment", None), "backend": getattr(self._inner, "api", None),
                "evidence_mode": "multi" if views else "single",
                "vision_mode": grounding["mode"] if agent_call else ev.vision_mode,
                "osm_claims": bool(grounding and grounding.get("claims") is not None),
                "centerline_views": ev.centerline_views,
                "views": [{"role": v["role"], "pixel_sha256": E.pixel_hash(v["image"])} for v in views or []],
                "request": (sig or {}).get("request")}
        try:
            if grounding: result = self._inner.analyze(image, context, views=views, grounding=grounding)
            elif views: result = self._inner.analyze(image, context, views=views)
            else: result = self._inner.analyze(image, context)
        except Exception as e:
            details = getattr(e, "details", None) or {}
            if meta["provider"] == "foundry":  # Foundry calls report usage through the provider result/error
                ev.rec.add_usage({"provider": "foundry", "profile": meta["profile"], "deployment": meta["deployment"],
                                  "requested_model": meta["deployment"], "error": getattr(e, "code", type(e).__name__),
                                  "call": meta["vision_mode"],
                                  "usage": details.get("usage"), "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
            doc = {"status": "ERROR", "error_code": getattr(e, "code", type(e).__name__),
                   "message": sanitize(getattr(e, "message", e)), "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                   "details": sanitize_obj(details),
                   **meta}
            if sig: ev.save("ai", json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"), "json", sig, meta)
            raise
        if meta["provider"] == "foundry":
            ev.rec.add_usage({"provider": "foundry", "profile": meta["profile"], "deployment": meta["deployment"],
                              "requested_model": meta["deployment"], "response_model": result.get("model"),
                              "call": meta["vision_mode"],
                              "usage": result.get("usage"), "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
        doc = {"status": "OK", "duration_ms": round((time.perf_counter() - t0) * 1000, 1), **meta,
               "result": sanitize_obj(result)}
        if sig: ev.save("ai", json.dumps(doc, indent=2, sort_keys=True).encode("utf-8"), "json", sig, meta)
        return result


def _install_anthropic_usage(rec):
    try:
        import anthropic
    except Exception as e:
        rec.note("usage recording (anthropic SDK)", e)
        return
    def wrap(create, endpoint, provider):
        def observed_create(*a, **k):
            t0 = time.perf_counter()
            try:
                resp = create(*a, **k)
            except Exception as e:
                rec.add_usage({"provider": provider, "endpoint": endpoint, "requested_model": k.get("model"),
                               "error": type(e).__name__, "usage": None,
                               "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
                raise
            try:
                u = getattr(resp, "usage", None)
                rec.add_usage({"provider": provider, "endpoint": endpoint, "requested_model": k.get("model"),
                               "response_model": getattr(resp, "model", None),
                               "stop_reason": getattr(resp, "stop_reason", None),
                               "usage": u.model_dump(mode="json") if u is not None else None,
                               "duration_ms": round((time.perf_counter() - t0) * 1000, 1)})
            except Exception as e:
                rec.note("usage record", e)
            return resp
        return observed_create

    def recording(base, provider):
        class UsageRecording(base):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                try:
                    self.messages.create = wrap(self.messages.create, "messages", provider)
                    self.beta.messages.create = wrap(self.beta.messages.create, "beta.messages", provider)
                except Exception as e:
                    rec.note("usage recording (client wrap)", e)
        return UsageRecording

    anthropic.Anthropic = recording(anthropic.Anthropic, "anthropic")
    # Foundry usage is recorded from the provider result (EvidenceVisionProvider), not by wrapping its SDK client.


def _run_context(run_dir, req, rec):  # run_dir is only kept as a label of the context; records are read by run_id
    """Evidence context for this run; resumed runs (ui/resume.json) also get a verified replay source."""
    from tcp_planner.storage.evidence_store import ReplaySource, sha256_file
    adv = (req.get("request") or {}).get("advanced") or {}
    ctx = {"run_dir": run_dir, "run_id": req.get("run_id") or os.path.basename(run_dir), "replay": None,
           "ai_provider": None, "evidence_mode": adv.get("evidence_mode") or "single",
           "vision_mode": adv.get("vision_mode") or "baseline", "osm_claims": bool(adv.get("osm_claims")),
           "centerline_views": bool(adv.get("centerline_views"))}
    if adv.get("ai_profile"): os.environ["TCP_FOUNDRY_PROFILE"] = adv["ai_profile"]
    try:
        from tcp_planner.orchestration.pipeline import CONFIG_PATH
        rec.write("deps", {"config_sha256": sha256_file(CONFIG_PATH)})
    except Exception as e:
        rec.note("deps record", e)
    from tcp_planner.storage import run_records
    resume = run_records.read(ctx["run_id"], "resume")
    if resume:
        ctx["replay"] = ReplaySource(resume["parent_run_id"], resume.get("reuse_kinds", []),
                                     resume.get("extra_sources", []))
        ctx["ai_provider"] = resume.get("ai_provider")
        ctx["evidence_mode"] = resume.get("evidence_mode") or ctx["evidence_mode"]
        for k in ("vision_mode", "osm_claims", "centerline_views"):
            if k in resume: ctx[k] = resume[k]
        ctx["strict_replay"] = resume.get("strict_replay") is True  # SME revision runs only
        if resume.get("ai_profile"): os.environ["TCP_FOUNDRY_PROFILE"] = resume["ai_profile"]
    return ctx


def prepare_views(comparison_id):
    """Acquire the fixed multi-resolution view set ONCE for a comparison, before any model runs, so every
    multi-resolution child reuses identical images. Uses the source run's verified analysis imagery request and
    OSM evidence (no new analysis-imagery or OSM call). Same .env / TLS initialisation as the CLI."""
    from tcp_planner.orchestration import pipeline as app
    from tcp_planner.data_sources import osm_overpass as osm_adapter
    from tcp_planner.orchestration import offline_scenarios as offline
    from tcp_planner.site_model.fusion import reference_bearing
    from tcp_planner.storage import evidence_store as E
    from tcp_planner.audit.provider_diagnostics import sanitize
    from tcp_planner.storage import run_records
    cid = comparison_id; cdir = run_records.run_root(cid); rec = Recorder(cid)
    doc = run_records.read(cid, "comparison")
    src = doc["source_run_id"]; src_dir = run_records.run_root(src)
    rec.write("prep", {"state": "RUNNING", "started_at": now_iso()})
    try:
        app.load_env_file(); app.use_os_trust_store()

        def analysis(kind):
            cands = [e for e in E.load_manifest(src) if e.get("kind") == kind
                     and e.get("producer_span") == E.ANALYSIS_SPANS[kind]]
            r = E.resolve(src, cands[-1]) if cands else None
            problem = E.verify_file(r) if cands else "no saved %s artifact" % kind
            if problem: raise RuntimeError("source %s evidence: %s" % (kind, problem))
            return r
        m, o = analysis("map"), analysis("osm")
        with open(os.path.join(src_dir, "output", "project_geometry.json"), encoding="utf-8") as f: pg = json.load(f)
        if E.geometry_hash(pg) != m["signature"]["geometry_hash"]: raise RuntimeError("source geometry hash mismatch")
        elements = json.loads(E.read_bytes(o).decode("utf-8"))
        bearing = round(reference_bearing(osm_adapter.extract_evidence(elements, pg, app.load_config())), 1)
        name = m["signature"]["provider"]
        if name == "offline_synthetic":
            provider = offline.build(run_records.read(src, "request")["request"]["offline_scenario"])["map_provider"]
        else:
            provider = app.get_map_provider(name)
        for k in ("scale_model", "api_version"):
            if getattr(provider, k.upper(), None) != m["signature"].get(k):
                raise RuntimeError("source imagery %s differs from the current provider (legacy/incompatible evidence)" % k)
        from tcp_planner.orchestration.run_relations import evidence_holders
        others = [c for c in evidence_holders(src) if c != os.path.basename(cdir)]
        ev = _Evidence(rec, {"run_dir": cdir, "run_id": os.path.basename(cdir), "evidence_mode": "multi",
                             "replay": E.ReplaySource(src, ["map_view"], others)})
        ev.analysis = (provider, pg, m["signature"]["half_extent_m"]); ev.osm_elements = elements
        rec.open_spans.append("tcp.prep.views")
        views = []
        for centerline in doc.get("view_plans") or [False]:  # every plan a variant needs, acquired (or reused) once
            ev.centerline_views = bool(centerline); ev._osm_geo = None
            views += ev.views({"reference_bearing_deg": bearing})
        rec.write("prep", {"state": "FINISHED", "ok": True, "ended_at": now_iso(), "bearing_deg": bearing,
                                "views": [v["role"] for v in views]})
        return True
    except Exception as e:
        rec.write("prep", {"state": "FINISHED", "ok": False, "ended_at": now_iso(),
                                "error": sanitize("%s: %s" % (getattr(e, "code", type(e).__name__), getattr(e, "message", e)))})
        return False


PATH_FLAGS = ("--out", "--kml", "--sme-revision", "--zone")


def resolve_argv(argv):
    """The stored argv holds run-relative keys after the path flags (D-77); give the pipeline real paths under the
    current runs folder."""
    from tcp_planner.storage import run_records
    return [run_records.resolve(a) if i and argv[i - 1] in PATH_FLAGS else a for i, a in enumerate(argv)]


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    from tcp_planner.storage import run_records
    from tcp_planner.storage.run_store import RUN_ID_RE
    prepare = bool(argv) and argv[0] == "--prepare-views"
    target = argv[1] if prepare and len(argv) > 1 else argv[0] if argv and not prepare else None
    if not target or not RUN_ID_RE.match(target):  # a run id, never a folder: the folder is found under the runs folder
        print("error: the runner takes a run id (for example 20261029-120000-abcdef), not a folder", file=sys.stderr)
        return 2
    if prepare: return 0 if prepare_views(target) else 1
    run_id = target; run_dir = run_records.run_root(run_id)
    if run_records.is_legacy(run_id):
        print(run_records.LEGACY_MESSAGE); return 2
    req = run_records.read(run_id, "request")
    rec = Recorder(run_id)
    started = now_iso(); t0 = time.perf_counter()
    rec.write("process", {"state": "RUNNING", "started_at": started, "pid": os.getpid()})
    rec.event(event="process_started", durable=True)
    exit_code, unhandled = None, None
    try:
        install_observers(rec, _run_context(run_dir, req, rec))
        from tcp_planner.orchestration import pipeline as app
        sys.argv[0] = "cli.py"  # argparse names the program from argv[0]; match the CLI in its messages
        exit_code = app.main(resolve_argv(req["argv"]))
    except SystemExit as e:  # argparse usage errors exit here, exactly as on the CLI
        exit_code = 0 if e.code is None else e.code if isinstance(e.code, int) else 1
    except BaseException as e:  # an unhandled exception ends the CLI with exit code 1; same here
        from tcp_planner.audit.provider_diagnostics import sanitize
        for line in traceback.format_exc().splitlines():  # stdout.log is shown in the UI: no URLs/queries/keys
            print(sanitize(line))
        exit_code, unhandled = 1, {"error_code": "UNHANDLED_EXCEPTION", "message": sanitize(f"{type(e).__name__}: {e}")}
    finally:
        sys.stdout.flush()
        rec.write_final("process", {"state": "FINISHED", "started_at": started, "ended_at": now_iso(),
                                    "runtime_ms": round((time.perf_counter() - t0) * 1000, 1),
                                    "exit_code": exit_code, "unhandled_error": unhandled})
        rec.event(event="process_finished", exit_code=exit_code, durable=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
