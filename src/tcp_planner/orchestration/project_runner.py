"""Project orchestrator (slice S3): one KML (or point) -> one project -> one child run per zone.

Everything here is idempotent, so a retry, a double click or a server restart never duplicates a run:
  1. Run records the request on the project (zones for the current inputs, the zone set it was asked for) and reserves
     a run id on every zone that has none. Both happen inside one compare-and-set update of the project record, so two
     callers cannot reserve two ids for the same zone.
  2. A reserved id becomes a run folder (write-once zone input, then the request record, which is the commit point).
     A reserved id whose run was never built is built on the next attempt; an existing request is never rewritten.
  3. A built run that was never started is started. A run with a process record, or alive, is left alone.
Above project.max_zones nothing is reserved or started until the cap is approved (the approval names the zone count it
covers). At most project.max_parallel_zone_runs runs are active at once; the rest queue and start as running ones
finish. Within a zone the pipeline order is unchanged: imagery, OSM, then AI.

One orchestrator thread per project runs in the server process (S3 Q5-A). Two processes driving the same project at the
same time is not supported: the lock below is per process (known limit, CLAUDE.md).
"""
import copy, datetime, hashlib, json, os, subprocess, sys, threading, time

from tcp_planner.orchestration import projects as P
from tcp_planner.orchestration.pipeline import load_config
from tcp_planner.rules.rule_pack_loader import load_rule_pack
from tcp_planner.storage import run_records as records, run_store as store, stores
from tcp_planner.storage.interfaces import StateExists
from tcp_planner.storage.project_store import ProjectStore

SCHEMA_VERSION = 1
STREAM_SCHEMA = 1
_LOCKS, _LOCKS_GUARD = {}, threading.Lock()


def _lock(project_id):
    with _LOCKS_GUARD: return _LOCKS.setdefault(project_id, threading.RLock())


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class SubprocessLauncher:
    """Starts run_worker processes (the CLI `project` command). The web server has its own launcher with the same two
    methods: launch(run_id) and live_ids()."""

    def __init__(self):
        self.procs = {}

    def launch(self, run_id):
        log = open(os.path.join(store.run_path(run_id, "ui"), "stdout.log"), "w", encoding="utf-8")
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        proc = subprocess.Popen([sys.executable, "-m", "tcp_planner.orchestration.run_worker", run_id],
                                cwd=store.PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
        self.procs[run_id] = (proc, log)

    def live_ids(self):
        live = set()
        for rid, (proc, log) in list(self.procs.items()):
            if proc.poll() is None: live.add(rid); continue
            log.close(); del self.procs[rid]

            def finish(prev, code=proc.returncode):  # the runner died before recording its end: record it once
                prev = prev or {}
                if prev.get("state") == "FINISHED": return None
                return {**prev, "state": "FINISHED", "exit_code": code, "ended_at": store._now(),
                        "unhandled_error": {"error_code": "RUNNER_TERMINATED",
                                            "message": f"runner process exited with code {code}"}}
            records.update(rid, "process", finish)
        return live


class ProjectRunner:
    def __init__(self, launcher, *, poll_s=0.5, config=None):
        cfg = config or load_config()
        self.launcher = launcher; self.poll_s = poll_s
        self.max_zones = cfg["project"]["max_zones"]
        self.max_parallel = cfg["project"]["max_parallel_zone_runs"]
        self._threads = {}

    # ------------------------------------------------------------ helpers
    @property
    def projects(self):
        return ProjectStore(stores.state(), stores.artifacts())

    def _event(self, project_id, **ev):
        stores.state().append_event(f"projects/{project_id}", {"at": _now(), **ev}, STREAM_SCHEMA)

    @staticmethod
    def road_types():
        return load_rule_pack().road_types()  # Q13: the choices come from the rule pack

    # ------------------------------------------------------------ create / reopen
    def open_or_create(self, *, name, kind, locations, upload=None, advanced=None, offline_scenario=None):
        """The project of this input. The same usable geometry reopens the same project (Q2-B); a new file is kept as
        another write-once input and the display labels follow the latest upload, each recording which upload it
        followed. kind: KML, COORDINATES or OFFLINE. upload: (file name, bytes) or None. -> (record, created)."""
        pid = P.project_id_for(locations, offline_scenario)
        with _lock(pid):
            ps = self.projects
            created = ps.get(pid) is None
            if created:
                source = {"kind": kind}
                if offline_scenario: source["offline_scenario"] = offline_scenario
                rec = P.new_record(name=name, source=source, locations=locations, advanced=advanced)
                try: ps.create(pid, rec)
                except StateExists: created = False
            ref = None
            if upload:
                file_name, data = upload
                sha = hashlib.sha256(data).hexdigest()
                ref = ps.put_input(pid, f"{sha[:12]}-{file_name}", data)

            def apply(cur):
                cur = copy.deepcopy(cur)
                if ref is not None:
                    if not any(i["sha256"] == ref.sha256 for i in cur["inputs"]):
                        cur["inputs"].append({**ref.to_dict(), "uploaded_at": _now()})
                    cur["name"] = name
                    cur["locations"] = [l.to_dict() for l in locations]
                    cur["labels"] = {l.location_id: {"text": l.display_label, "input_sha256": ref.sha256,
                                                     "input_key": ref.uri} for l in locations}
                return cur
            rec = ps.update(pid, apply)
            self._event(pid, event="project_created" if created else "project_reopened",
                        input_sha256=ref.sha256 if ref else None)
            return self.view(pid), created

    # ------------------------------------------------------------ SME edits
    def set_inputs(self, project_id, **edits):
        """Start fields, apply-to-all and Select TA (projects.set_inputs). Zones are rebuilt, so a changed zone shows its
        new inputs at once and a zone that already ran gets a new version (its old run stays)."""
        road_types = self.road_types()
        with _lock(project_id):
            def apply(cur):
                new = P.set_inputs(copy.deepcopy(cur), road_types, **edits)
                new["zones"] = P.build_zones(new, project_id)
                return new
            self.projects.update(project_id, apply)
            self._event(project_id, event="inputs_changed", fields=sorted(k for k, v in edits.items() if v not in (None, False)))
            return self._store_status(project_id)

    # ------------------------------------------------------------ run
    def run(self, project_id, *, background=True):
        """Ask for the project's zones to run. Raises ProjectInputError START_FIELDS_MISSING while a field is empty (no
        code fills one) and NO_RUNNABLE_ZONE when no zone can run. Over the cap nothing is reserved or started. Safe
        to call again: nothing that exists is created twice. -> the project view."""
        with _lock(project_id):
            def apply(cur):
                cur = copy.deepcopy(cur)
                miss = P.missing_fields(cur)
                if miss:
                    raise P.ProjectInputError("START_FIELDS_MISSING", "road type, speed, traffic volume and lane closure "
                                              "must be typed for every location before Run", {"missing": miss})
                cur["zones"] = P.build_zones(cur, project_id)
                if not P.runnable_zones(cur["zones"]):
                    raise P.ProjectInputError("NO_RUNNABLE_ZONE", "no work Point to run (lines and polygons run from S14)")
                cur["run_request"] = {"zones_hash": P.zones_hash(cur["zones"]), "requested_at": _now()}
                if P.cap_cleared(cur, self.max_zones):
                    for z in P.runnable_zones(cur["zones"]):
                        if z["current_run_id"] is None:
                            z["current_run_id"] = store.reserve_run_id(); z["run_ids"].append(z["current_run_id"])
                return cur
            self.projects.update(project_id, apply)
            self._event(project_id, event="run_requested")
        if background: self.start(project_id)
        else: self.drive(project_id)
        return self.view(project_id)

    def approve_cap(self, project_id, actor=None, *, background=True):
        """One click: the runnable zone count above the cap is approved, then the project runs."""
        with _lock(project_id):
            def apply(cur):
                cur = copy.deepcopy(cur)
                if not P.cap_exceeded(cur.get("zones") or [], self.max_zones):
                    raise P.ProjectInputError("CAP_NOT_EXCEEDED", "the project is within the zone cap")
                cur["cap_approval"] = {"zone_count": len(P.runnable_zones(cur["zones"])), "approved_at": _now(),
                                       "actor": actor or "UI click"}
                return cur
            self.projects.update(project_id, apply)
            self._event(project_id, event="cap_approved", actor=actor or "UI click")
        return self.run(project_id, background=background)

    # ------------------------------------------------------------ scheduling
    def start(self, project_id):
        """The orchestrator thread of the project (one at a time)."""
        with _LOCKS_GUARD:
            th = self._threads.get(project_id)
            if th is not None and th.is_alive(): return th
            th = self._threads[project_id] = threading.Thread(target=self._drive_safely, args=(project_id,), daemon=True)
        th.start(); return th

    def _drive_safely(self, project_id):
        try: self.drive(project_id)
        except Exception as e:  # never die silently: the project event stream keeps the reason
            try: self._event(project_id, event="orchestrator_error", error=f"{type(e).__name__}: {e}")
            except Exception: pass
            print(f"[orchestrator] project {project_id}: {type(e).__name__}: {e}", flush=True)

    def drive(self, project_id):
        """Build and start the zone runs, at most max_parallel at once, until every one has finished."""
        while not self._pass(project_id): time.sleep(self.poll_s)
        return self.view(project_id)

    def _pass(self, project_id):
        """One scheduling step. True when nothing is left to build, start or wait for."""
        with _lock(project_id):
            rec = self.projects.get(project_id)
            if rec is None or not rec.get("run_request") or not P.cap_cleared(rec, self.max_zones): return True
            live = self.launcher.live_ids()
            active, queued = 0, []
            for z in P.runnable_zones(rec["zones"]):
                rid = z["current_run_id"]
                if rid is None: continue
                if self._materialize(project_id, rec, z): self._event(project_id, event="zone_run_created", zone_id=z["zone_id"], run_id=rid)
                s = self._classify(rid, live)
                if s == P.ACTIVE: active += 1
                elif s == P.QUEUED: queued.append(z)
            started = 0
            for z in queued[:max(0, self.max_parallel - active)]:
                self.launcher.launch(z["current_run_id"]); started += 1
                self._event(project_id, event="zone_run_started", zone_id=z["zone_id"], run_id=z["current_run_id"])
            self._store_status(project_id)
            return not started and not active and not queued

    @staticmethod
    def _classify(run_id, live):
        proc = records.read(run_id, "process") or {}
        if proc.get("state") == "FINISHED": return P.FINISHED
        if run_id in live: return P.ACTIVE
        if proc: return P.FINISHED  # RUNNING on disk but not alive: the runner is gone (shown as FAILED / interrupted)
        return P.QUEUED

    # ------------------------------------------------------------ one zone run
    def _materialize(self, project_id, rec, zone):
        """Build the run of a reserved id unless it exists. True when this call built it."""
        rid = zone["current_run_id"]
        if records.read(rid, "request") is not None: return False
        store.ensure_run_dirs(rid)
        zi = P.zone_engine_input(rec, zone, project_id)
        ref = stores.artifacts().put(f"{rid}/input/zone_input.json",
                                     json.dumps(zi, indent=2, sort_keys=True).encode("utf-8"), "application/json")
        adv = rec.get("advanced") or {}
        offline = (rec["source"].get("offline_scenario") if rec["source"]["kind"] == P.OFFLINE else None)
        flags, adv_request = store.advanced_args(adv, online=offline is None)
        argv = ["--zone", ref.uri] + (["--offline", offline] if offline else []) + flags + ["--out", f"{rid}/output"]
        sf = zi["start_fields"]
        request = {"input_type": "offline" if offline else "zone",
                   "project": {"project_id": project_id, "zone_id": zone["zone_id"], "zone_version": zone["version"],
                               "lineage_key": zone["lineage_key"]},
                   "zone_input_key": ref.uri,
                   "operator": {"road_type": sf["road_type"], "speed": sf["posted_speed_mph"],
                                "requires_lane_closure": sf["lane_closure"] is True, "traffic_volume": sf["traffic_volume"],
                                "ta_hypothesis": zi["zone"]["ta_hypothesis"], "options": []},
                   "advanced": adv_request}
        if offline: request.update(offline_scenario=offline, offline_input="coordinates")
        try: records.create(rid, "request", {"run_id": rid, "created_at": store._now(), "argv": argv, "request": request})
        except StateExists: return False  # another caller built it first
        return True

    # ------------------------------------------------------------ views
    def zone_states(self, rec, live=None):
        live = self.launcher.live_ids() if live is None else live
        out = {}
        for z in P.runnable_zones(rec.get("zones") or []):
            rid = z["current_run_id"]
            if rid is None: continue
            if records.read(rid, "request") is None: out[rid] = {"state": P.QUEUED, "drafted": False, "decision": None}; continue
            s = self._classify(rid, live)
            if s != P.FINISHED: out[rid] = {"state": s, "drafted": False, "decision": None}; continue
            st = store.build_state(rid, with_lineage=False) or {}
            out[rid] = {"state": P.FINISHED, "drafted": bool(st.get("draft_generated")), "decision": st.get("decision"),
                        "service_error": st.get("service_error")}
        return out

    def _store_status(self, project_id):
        """Save the rolled-up status on the record when it changed. -> the status."""
        rec = self.projects.get(project_id)
        status = P.roll_up(rec, self.zone_states(rec), self.max_zones)
        if status != rec.get("status"):
            def apply(cur):
                cur = copy.deepcopy(cur); cur["status"] = status; return cur
            self.projects.update(project_id, apply)
            self._event(project_id, event="status", status=status)
        return status

    def view(self, project_id):
        """The project record with its current status, zone run states and what is still missing before Run."""
        rec = self.projects.get(project_id)
        if rec is None: return None
        states = self.zone_states(rec)
        return {**rec, "status": P.roll_up(rec, states, self.max_zones), "zone_runs": states,
                "missing_fields": P.missing_fields(rec), "max_zones": self.max_zones,
                "cap_cleared": P.cap_cleared(rec, self.max_zones)}

    def list(self):
        return [{"project_id": r["project_id"], "name": r["name"], "created_at": r["created_at"],
                 "status": self.view(r["project_id"])["status"], "zones": len(r.get("zones") or [])}
                for r in self.projects.list()]
