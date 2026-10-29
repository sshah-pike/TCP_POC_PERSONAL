"""Local HTTP API + static host for the TCP Planner web UI (standard library only).

    python -m tcp_planner.web_api.server [--port 8765]        ->  http://127.0.0.1:8765

Binds to 127.0.0.1 only. Never reads or returns .env contents or credentials; the pipeline child
process loads .env itself exactly as the CLI does.

GET  /api/meta                          form choices (from the rule pack, config and offline module)
GET  /api/runs                          run history
POST /api/runs                          refused (400): only a project starts runs
GET|POST /api/projects[/...]            projects: one run per zone (tcp_planner.web_api.project_routes)
POST /api/runs/<id>/stop                stop a running run (ends its runner process; recorded as STOPPED)
GET  /api/runs/<id>                     run state (stages, decision, outputs, cost)
GET  /api/runs/<id>/files/<name>        a file the pipeline wrote to runs/<id>/output/
GET  /*                                 built UI from apps/web/dist
GET|POST /api/assistant/*               SME Review Assistant (tcp_planner.review.assistant.routes; off unless TCP_SME_ASSISTANT_ENABLED=true)
"""
import argparse, json, mimetypes, os, shutil, subprocess, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, unquote

from tcp_planner.storage import run_store as store, run_records as records, stores
from tcp_planner.storage.interfaces import ArtifactMissing

WEB_DIST = os.path.join(store.PROJECT_ROOT, "apps", "web", "dist")
MAX_BODY = 10 * 1024 * 1024
ASSISTANT_MAX_BODY = 64 * 1024  # assistant requests are small structured JSON
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CONTENT_TYPES = {".json": "application/json", ".txt": "text/plain; charset=utf-8", ".png": "image/png",
                 ".jpg": "image/jpeg", ".pdf": "application/pdf", ".dxf": "application/dxf",
                 ".dwg": "application/acad", ".kml": "application/vnd.google-earth.kml+xml"}
ATTACHMENT_EXT = {".dxf", ".dwg", ".kml"}

LIVE = {}  # run_id -> Popen
LIVE_LOCK = threading.Lock()
STOPPED = set()  # run ids stopped by the user (the reaper records them as RUN_STOPPED)


def live_ids():
    with LIVE_LOCK: return set(LIVE)


class _ServerLauncher:
    """What the project orchestrator needs from this server: start a run's worker, and which runs are alive."""
    def launch(self, run_id): return launch(run_id)

    def live_ids(self): return live_ids()


_RUNNER = None


def project_runner():
    """The one project orchestrator of this server process (S3 Q5-A: its threads run here)."""
    global _RUNNER
    with LIVE_LOCK:
        if _RUNNER is None:
            from tcp_planner.orchestration.project_runner import ProjectRunner
            _RUNNER = ProjectRunner(_ServerLauncher())
    return _RUNNER


def _check_ai_profile(adv):
    _ai_choice({"ai_profile": adv["ai_profile"]})


def start_run(payload):
    """Only a project starts runs (S3, D-59): road type, speed, traffic volume and lane closure are typed per project and
    Run stays closed until every one is. Resume and comparison runs start from an existing run, not from here."""
    raise store.BadRequest("runs start from a project: POST /api/projects with the KML, point or offline scenario, type the "
                           "four start fields with POST /api/projects/<id>/inputs, then POST /api/projects/<id>/run")


def _ai_choice(payload):
    """Validate a requested AI provider / Foundry profile against what is configured (no free text)."""
    from tcp_planner.ai.foundry_provider import profile_catalog
    prov, prof = payload.get("ai_provider") or None, payload.get("ai_profile") or None
    if prov and prov not in store.AI_PROVIDERS: raise store.BadRequest("unknown AI provider")
    if prof:
        if not any(p["name"] == prof and p["available"] for p in profile_catalog()):
            raise store.BadRequest(f"Foundry profile {prof!r} is not available")
        prov = prov or "foundry"
    return prov, prof


def start_resume(parent_id, payload):
    from tcp_planner.orchestration import run_relations as relations
    prov, prof = _ai_choice(payload)
    run_id, rdir = relations.create_resume_run(parent_id, str(payload.get("stage") or ""), prof, prov,
                                               evidence_mode=str(payload.get("evidence_mode") or "single"),
                                               vision_mode=str(payload.get("vision_mode") or "baseline"),
                                               osm_claims=payload.get("osm_claims") is True,
                                               centerline_views=payload.get("centerline_views") is True)
    return launch(run_id)


def start_comparison(payload):
    from tcp_planner.orchestration import run_relations as relations
    profiles = payload.get("profiles") or []
    if not isinstance(profiles, list): raise store.BadRequest("profiles must be a list")
    modes = payload.get("modes") or ["single"]
    if not isinstance(modes, list): raise store.BadRequest("modes must be a list")
    variants = payload.get("variants")
    if variants is not None and not (isinstance(variants, list) and all(isinstance(v, dict) for v in variants)):
        raise store.BadRequest("variants must be a list of objects")
    cid = relations.create_comparison(str(payload.get("source_run_id") or ""), [str(p) for p in profiles],
                                      [str(m) for m in modes], variants)

    def run():  # shared multi-resolution views first (one acquisition), then every model as its own child run
        doc = records.read(cid, "comparison")
        if doc.get("needs_views"):
            with open(store.run_path(cid, "ui", "prep.log"), "w", encoding="utf-8") as log:
                subprocess.call([sys.executable, "-m", "tcp_planner.orchestration.run_worker", "--prepare-views",
                                 cid],  # the worker takes a run id and finds the folder itself
                                cwd=store.PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"))
        for rid in relations.create_children(cid): launch(rid)

    threading.Thread(target=run, daemon=True).start()
    return cid


def stop_run(run_id):
    """End a running run's runner process. Outputs written so far stay; a model request already sent may still be
    billed by the provider."""
    store.run_path(run_id)  # validates the id
    with LIVE_LOCK:
        proc = LIVE.get(run_id)
        if proc is None: raise store.BadRequest("run is not running")
        STOPPED.add(run_id)
    proc.terminate()
    return {"run_id": run_id, "stopping": True}


def launch(run_id):
    """Start the worker for a run by its id; the worker resolves the run folder under the runs folder itself (D-77)."""
    log = open(os.path.join(store.run_path(run_id, "ui"), "stdout.log"), "w", encoding="utf-8")
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "tcp_planner.orchestration.run_worker", run_id],
                            cwd=store.PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    with LIVE_LOCK: LIVE[run_id] = proc

    def reap():
        proc.wait(); log.close()
        with LIVE_LOCK: stopped = run_id in STOPPED
        err = ({"error_code": store.RUN_STOPPED, "message": "run stopped by the user"} if stopped else
               {"error_code": "RUNNER_TERMINATED", "message": f"runner process exited with code {proc.returncode}"})

        def finish(prev):  # runner died before recording its end (or the user stopped it): record the end, once
            prev = prev or {}
            if not stopped and prev.get("state") == "FINISHED": return None
            return {**prev, "state": "FINISHED", "exit_code": proc.returncode, "ended_at": store._now(),
                    "unhandled_error": err}
        try: records.update(run_id, "process", finish)  # compare-and-set: never overwrites the runner's own record
        except Exception as e: print(f"[server] could not record the end of run {run_id}: {type(e).__name__}: {e}", flush=True)
        with LIVE_LOCK: LIVE.pop(run_id, None); STOPPED.discard(run_id)

    threading.Thread(target=reap, daemon=True).start()
    return run_id


def meta():
    from tcp_planner.orchestration import offline_scenarios as offline
    from tcp_planner.orchestration.pipeline import load_config, DWT_CONFIG_PATH
    from tcp_planner.sheets.dwt_renderer import MODES
    from tcp_planner.contracts import APP_VERSION
    from tcp_planner.rules.rule_pack_loader import load_rule_pack
    from tcp_planner.orchestration import projects as P
    out = {"app_version": APP_VERSION, "offline_scenarios": list(offline.SCENARIOS), "offline_aliases": offline.ALIASES,
           "start_fields": list(P.START_FIELDS), "traffic_volumes": list(P.TRAFFIC_VOLUMES), "ta_choices": list(P.TA_CHOICES),
           "map_providers": list(store.UI_MAP_PROVIDERS), "ai_providers": list(store.UI_AI_PROVIDERS),
           "dwt_modes": list(MODES), "dwt_config_present": os.path.isfile(DWT_CONFIG_PATH),
           "road_types": [], "supported_road_types": [], "rule_pack": None, "rule_pack_error": None,
           "pricing_source": store.load_pricing().get("source"), "foundry_profiles": [],
           "resume_stages": [s[0] for s in store.STAGES]}
    try:
        from tcp_planner.ai.foundry_provider import profile_catalog
        out["foundry_profiles"] = profile_catalog()
    except Exception as e:
        out["foundry_profiles_error"] = type(e).__name__
    try:
        cfg = load_config(); out["supported_road_types"] = cfg["supported_road_types"]
        out["max_zones"] = cfg["project"]["max_zones"]; out["max_parallel_zone_runs"] = cfg["project"]["max_parallel_zone_runs"]
    except Exception as e: out["config_error"] = getattr(e, "code", type(e).__name__)
    try:
        pack = load_rule_pack()
        out["road_types"] = pack.road_types()
        out["rule_pack"] = {"id": pack.id, "version": pack.version, "status": pack.status, "hash": pack.hash,
                            "selected_ta": pack.selected_ta()}
    except Exception as e:  # displayed only; the pipeline itself fails closed on the same problem
        out["rule_pack_error"] = {"error_code": getattr(e, "code", type(e).__name__), "message": str(getattr(e, "message", e))}
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "tcp-ui"

    def log_message(self, fmt, *args):  # quiet: no request lines (URLs may carry run ids only, but keep console clean)
        pass

    # ---------------- helpers ----------------
    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host in ALLOWED_HOSTS: return True
        self._json({"error": "forbidden host"}, 403); return False

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def _send(self, name, data, download=False):
        ext = os.path.splitext(name)[1].lower()
        ctype = CONTENT_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        if download or ext in ATTACHMENT_EXT:
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(name)}"')
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, download=False):
        with open(path, "rb") as f: data = f.read()
        return self._send(path, data, download)

    def _artifact(self, uri, download=False):
        """Serve a stored artifact by key, hash-free (the manifest check happens in the caller)."""
        return self._send(uri, stores.artifacts().get(uri), download)

    # ---------------- routes ----------------
    def do_GET(self):
        if not self._host_ok(): return
        url = urlsplit(self.path); parts = [unquote(p) for p in url.path.split("/") if p]
        if parts[:2] == ["api", "assistant"]:
            return self._assistant("GET", parts[2:], url.query, None)
        if parts[:2] == ["api", "projects"]:
            return self._project("GET", parts[2:], None)
        try:
            if parts[:1] == ["api"]:
                if parts == ["api", "meta"]: return self._json(meta())
                if parts == ["api", "runs"]: return self._json(store.list_runs(live_ids()))
                if len(parts) == 3 and parts[1] == "runs":
                    st = store.build_state(parts[2], live_ids())
                    return self._json(st) if st else self._json({"error": "run not found"}, 404)
                if len(parts) == 4 and parts[1] == "runs" and parts[3] == "resume-preview":
                    from tcp_planner.orchestration import run_relations as relations
                    q = parse_qs(url.query)
                    prov, prof = _ai_choice({"ai_provider": (q.get("ai_provider") or [None])[0],
                                             "ai_profile": (q.get("ai_profile") or [None])[0]})
                    return self._json(relations.resume_preview(parts[2], (q.get("stage") or [""])[0], prof, prov,
                                                               (q.get("evidence_mode") or ["single"])[0]))
                if parts == ["api", "labels"]:
                    from tcp_planner.evaluation import ground_truth_labels as labels
                    return self._json(labels.list_labels())
                if len(parts) == 3 and parts[1] == "labels":
                    from tcp_planner.evaluation import ground_truth_labels as labels
                    doc = labels.get(parts[2])
                    return self._json(doc) if doc else self._json({"error": "label not found"}, 404)
                if len(parts) == 4 and parts[1] == "comparisons" and parts[3] == "evaluation":
                    from tcp_planner.evaluation import comparison_scoring as evaluation
                    rep = evaluation.evaluate_comparison(parts[2])
                    return self._json(rep) if rep else self._json({"error": "comparison not found"}, 404)
                if parts == ["api", "comparisons"]:
                    from tcp_planner.orchestration import run_relations as relations
                    return self._json(relations.list_comparisons())
                if len(parts) == 3 and parts[1] == "comparisons":
                    from tcp_planner.orchestration import run_relations as relations
                    rep = relations.comparison_state(parts[2], live_ids())
                    return self._json(rep) if rep else self._json({"error": "comparison not found"}, 404)
                if len(parts) == 5 and parts[1] == "runs" and parts[3] == "evidence":
                    from tcp_planner.storage.evidence_store import load_manifest, evidence_key
                    name = parts[4]; store.run_path(parts[2])  # validates the run id
                    saved = {e["file"] for e in load_manifest(parts[2]) if e.get("mode") == "saved"}
                    if name in saved:  # only files this run's manifest lists
                        try: return self._artifact(evidence_key(parts[2], name), "download" in parse_qs(url.query))
                        except ArtifactMissing: pass
                    return self._json({"error": "file not found"}, 404)
                if len(parts) == 5 and parts[1] == "runs" and parts[3] == "files":
                    out_dir = store.run_path(parts[2], "output"); name = parts[4]
                    # only a plain file name that the pipeline actually wrote
                    if name in os.listdir(out_dir) and os.path.isfile(os.path.join(out_dir, name)):
                        return self._file(os.path.join(out_dir, name), "download" in parse_qs(url.query))
                    return self._json({"error": "file not found"}, 404)
                return self._json({"error": "not found"}, 404)
            return self._static(url.path)
        except store.BadRequest as e:
            return self._json({"error": str(e)}, 400)
        except (FileNotFoundError, NotADirectoryError):
            return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._host_ok(): return
        path = urlsplit(self.path).path; parts = [unquote(p) for p in path.split("/") if p]
        if parts[:2] == ["api", "assistant"]:
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"error": "Content-Type must be application/json"}, 415)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > ASSISTANT_MAX_BODY: return self._json({"error": "request body missing or too large"}, 413)
            try:
                payload = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json({"error": "invalid JSON"}, 400)
            if not isinstance(payload, dict): return self._json({"error": "JSON object expected"}, 400)
            return self._assistant("POST", parts[2:], urlsplit(self.path).query, payload)
        if parts[:2] == ["api", "projects"]:
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json({"error": "Content-Type must be application/json"}, 415)
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY: return self._json({"error": "request body too large"}, 413)
            try: payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            except (ValueError, UnicodeDecodeError): return self._json({"error": "invalid JSON"}, 400)
            if not isinstance(payload, dict): return self._json({"error": "JSON object expected"}, 400)
            return self._project("POST", parts[2:], payload)
        route =("run" if path == "/api/runs" else "comparison" if path == "/api/comparisons"
                 else "stop" if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "stop"
                 else "resume" if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "resume"
                 else "label_confirm" if len(parts) == 4 and parts[:2] == ["api", "labels"] and parts[3] == "confirm"
                 else "label_revoke" if len(parts) == 4 and parts[:2] == ["api", "labels"] and parts[3] == "revoke" else None)
        if route is None: return self._json({"error": "not found"}, 404)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json({"error": "Content-Type must be application/json"}, 415)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY: return self._json({"error": "request body missing or too large"}, 413)
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(payload, dict): raise store.BadRequest("JSON object expected")
            if route == "stop": return self._json(stop_run(parts[2]))
            if route == "comparison": return self._json({"comparison_id": start_comparison(payload)}, 201)
            if route in ("label_confirm", "label_revoke"):
                from tcp_planner.evaluation import ground_truth_labels as labels
                if route == "label_revoke":
                    return self._json(labels.revoke(parts[2], payload.get("reviewer"), payload.get("reason")))
                edits = payload.get("edits") or {}
                if not isinstance(edits, dict): raise store.BadRequest("edits must be an object")
                return self._json(labels.confirm(parts[2], payload.get("reviewer"), payload.get("reason"), edits))
            if route == "resume": return self._json({"run_id": start_resume(parts[2], payload)}, 201)
            return self._json({"run_id": start_run(payload)}, 201)
        except (ValueError, UnicodeDecodeError):
            return self._json({"error": "invalid JSON"}, 400)
        except records.LegacyRunReadOnly as e:
            return self._json({"error": str(e), "error_code": e.code}, 409)
        except store.BadRequest as e:
            return self._json({"error": str(e)}, 400)

    def _project(self, method, parts, payload):
        from tcp_planner.web_api import project_routes
        status, body = project_routes.dispatch(method, parts, payload, project_runner(), check_ai=_check_ai_profile)
        return self._json(body, status)

    def _assistant(self, method, parts, query, payload):
        """SME Review Assistant routes (tcp_planner.review.assistant.routes); unavailable unless TCP_SME_ASSISTANT_ENABLED=true."""
        from tcp_planner.review.assistant import routes as assistant_api
        status, kind, body = assistant_api.dispatch(method, parts, parse_qs(query or ""), payload,
                                                    {"X-TCP-Session": self.headers.get("X-TCP-Session")})
        if kind == "file":
            return self._file(body["path"], body.get("download", False))
        return self._json(body, status)

    def _static(self, path):
        if not os.path.isdir(WEB_DIST):
            body = (b"<h3>TCP POC Runner UI is not built.</h3><p>Run <code>npm install</code> and "
                    b"<code>npm run build</code> in <code>apps/web</code>, or use <code>npm run dev</code>.</p>")
            self.send_response(200); self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        root = os.path.realpath(WEB_DIST)
        target = os.path.realpath(os.path.join(root, unquote(path).lstrip("/")))
        if not target.startswith(root + os.sep) or not os.path.isfile(target):
            target = os.path.join(root, "index.html")  # SPA fallback
        return self._file(target)


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind the same port and silently share it with a stale one;
    # without it a second start fails with "address in use" instead.
    allow_reuse_address = os.name != "nt"


def make_server(port=8765):
    return _Server(("127.0.0.1", port), Handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description="TCP POC Runner - local UI server")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    srv = make_server(a.port)
    print(f"TCP POC Runner: http://127.0.0.1:{a.port}   (runs stored in {store.runs_dir()})", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally: srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
