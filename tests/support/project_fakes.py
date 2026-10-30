"""Launchers for the project orchestrator tests (S3). Both have the two methods the orchestrator uses:
launch(run_id) and live_ids().

FakeLauncher       no pipeline: records launches, counts how many runs are active at once, and finishes runs by hand
                   or at once with a chosen outcome (writes the process and result records and plan.json like a worker)
InProcLauncher     runs the real worker in-process (tests.integration.web_api.inproc), one run after another
"""
import json, os, threading

from tcp_planner.storage import run_records as records, run_store as store

OK = {"decision": "SUPPORTED_AUTO", "exit_code": 0, "draft": True}
REVIEW = {"decision": "REVIEW_REQUIRED", "exit_code": 3, "draft": False}
CRASH = {"decision": None, "exit_code": 1, "draft": False, "error": {"error_code": "UNHANDLED_EXCEPTION", "message": "forced"}}


class FakeLauncher:
    def __init__(self, auto=None):
        """auto: None (finish runs by hand), one outcome for every run, or a list of outcomes in launch order."""
        self.auto = auto; self.live, self.launched = set(), []
        self.max_active = 0; self._lock = threading.Lock()

    def launch(self, run_id):
        with self._lock:
            self.launched.append(run_id); self.live.add(run_id); self.max_active = max(self.max_active, len(self.live))
        records.write(run_id, "process", {"state": "RUNNING", "pid": 0})
        if self.auto is not None:
            n = len(self.launched) - 1
            self.finish(run_id, self.auto[n] if isinstance(self.auto, list) else self.auto)

    def live_ids(self):
        with self._lock: return set(self.live)

    def finish(self, run_id, outcome=OK):
        out = store.run_path(run_id, "output")
        if outcome.get("draft"):
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "plan.json"), "w", encoding="utf-8") as f: json.dump({"plan_id": "P-" + run_id}, f)
        if outcome.get("decision") or outcome.get("error"):
            records.write(run_id, "result", {k: v for k, v in (("decision", outcome.get("decision")), ("reason_codes", []),
                                                               ("error", outcome.get("error"))) if v is not None})
        records.write(run_id, "process", {"state": "FINISHED", "exit_code": outcome["exit_code"], "runtime_ms": 1.0,
                                          "unhandled_error": outcome.get("error")})
        with self._lock: self.live.discard(run_id)


class InProcLauncher:
    """Runs the real worker in this process when launch() is called, so the run has finished when it returns."""
    def __init__(self):
        self.launched = []

    def launch(self, run_id):
        from tests.integration.web_api import inproc
        self.launched.append(run_id)
        inproc.run(store.run_path(run_id))

    def live_ids(self):
        return set()
