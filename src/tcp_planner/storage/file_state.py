"""StateStore on plain files (D-84: the MVP stores state in files only).

Layout under the store root:
  <root>/<key>.state.json      one record, envelope {key, version, schema_version, value}, canonical JSON, replaced atomically
  <root>/<stream>.events.jsonl one event per line {seq, schema_version, event}, append-only

Safety across processes on one machine:
- Every write runs entirely under a lock file (<target>.lock) created with O_CREAT|O_EXCL. The lock holds the owner's
  pid, a timestamp and a random token. A lock older than stale_lock_s is stale and is taken over: renamed away, so two
  takers can not both win.
- Immediately before os.replace (and before an event append) the writer re-checks that the lock file still carries its
  own pid, timestamp and token. If not, it aborts without writing and retries the whole operation under a new lock.
- os.replace and reads retry on PermissionError (another process, OneDrive or antivirus holding the file).
- Reads take no lock and never create files or folders. A reader sees the old or the new record, never a mix, because
  the replace is atomic. A reader skips an incomplete last event line (a writer is mid-append).

Local disks only: lock files are not reliable on network shares.
"""
import json, os, time, uuid

from tcp_planner.storage.interfaces import (StateStore, StateRecord, StateExists, StateMissing, StaleHead, StorageError,
                                            validate_key)

STATE_SUFFIX = ".state.json"
EVENTS_SUFFIX = ".events.jsonl"
LOCK_SUFFIX = ".lock"
TMP_PREFIX = ".tmp-"
REPLACE_BACKOFF_S = (0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.4, 0.4)  # 10 tries, about 2 s in all
LOCK_RETRIES = 3  # whole-operation retries after a lost lock


class LockLost(StorageError):
    code = "LOCK_LOST"


def _now(): return time.time()
def _sleep(s): time.sleep(s)


def _dump(obj):
    try: return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e: raise StorageError(f"value is not JSON serializable: {e}") from e


def _retry_permission(fn):
    for delay in REPLACE_BACKOFF_S:
        try: return fn()
        except PermissionError: _sleep(delay)
    try: return fn()
    except PermissionError as e: raise StorageError(f"file stayed locked by another process: {e}") from e


def _read_lock(path):
    """The lock's owner record, or None when the file is missing or unreadable. A PermissionError (another process has
    the file open at this instant) is retried first, so a brief clash is never mistaken for a lost lock."""
    def read():
        try:
            with open(path, "rb") as f: return f.read()
        except (FileNotFoundError, NotADirectoryError): return None
    try: raw = _retry_permission(read)
    except StorageError: return None
    try: return json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError: return None


class _Lock:
    def __init__(self, path, meta): self.path = path; self.meta = meta

    def owned(self):
        return _read_lock(self.path) == self.meta

    def assert_owned(self):
        if not self.owned(): raise LockLost(f"lock {os.path.basename(self.path)} was taken over")

    def release(self):
        if self.owned():
            try: _retry_permission(lambda: os.remove(self.path))  # a contender may have the file open for a moment
            except (StorageError, OSError): pass


class FileStateStore(StateStore):
    def __init__(self, root, stale_lock_s=30.0, lock_wait_s=60.0):
        self.root = os.path.abspath(root)
        self.stale_lock_s = float(stale_lock_s); self.lock_wait_s = float(lock_wait_s)
        self._pre_replace_hook = None  # test seam: called after the temp file is written, before the ownership check

    # ------------------------------------------------------------------ paths
    def _state_path(self, key): return os.path.join(self.root, *validate_key(key).split("/")) + STATE_SUFFIX
    def _events_path(self, stream): return os.path.join(self.root, *validate_key(stream).split("/")) + EVENTS_SUFFIX

    # ------------------------------------------------------------------ locking
    def _acquire(self, target):
        lock_path = target + LOCK_SUFFIX
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        deadline = _now() + self.lock_wait_s; delay = 0.005
        while True:
            meta = {"pid": os.getpid(), "ts": _now(), "token": uuid.uuid4().hex}
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o644)
            except (FileExistsError, PermissionError):
                self._take_over_if_stale(lock_path)
                if _now() > deadline: raise StorageError(f"could not acquire {os.path.basename(lock_path)}") from None
                _sleep(delay); delay = min(delay * 2, 0.1)
                continue
            with os.fdopen(fd, "wb") as f:
                f.write(_dump(meta).encode("utf-8"))  # no fsync: a lock only has to be visible to other processes
            return _Lock(lock_path, meta)

    def _take_over_if_stale(self, lock_path):
        seen = _read_lock(lock_path)
        try: ts = seen["ts"] if seen else os.path.getmtime(lock_path)  # unreadable: creator is mid-write, use the mtime
        except (OSError, KeyError, TypeError): return
        if _now() - ts <= self.stale_lock_s: return
        moved = f"{lock_path}.stale-{uuid.uuid4().hex}"
        try: os.rename(lock_path, moved)  # atomic: only one taker moves it
        except OSError: return
        if seen is not None and _read_lock(moved) != seen:
            try: os.rename(moved, lock_path)  # we moved a live lock taken a moment ago: put it back
            except OSError: pass            # (its owner re-checks before writing and aborts if it is gone)
            return
        try: os.remove(moved)
        except OSError: pass

    def _locked(self, target, fn):
        """Run fn(lock) under the lock on target; if the lock is lost mid-way, retry the whole operation."""
        for _ in range(LOCK_RETRIES):
            lock = self._acquire(target)
            try: return fn(lock)
            except LockLost: continue
            finally: lock.release()
        raise LockLost(f"lock on {os.path.basename(target)} was lost {LOCK_RETRIES} times; nothing was written")

    # ------------------------------------------------------------------ record IO
    def _read_envelope(self, path):
        def read():
            try:
                with open(path, "rb") as f: return f.read()
            except (FileNotFoundError, NotADirectoryError): return None
        raw = _retry_permission(read)
        if raw is None: return None
        try: env = json.loads(raw.decode("utf-8"))
        except ValueError as e: raise StorageError(f"state file {os.path.basename(path)} is not valid JSON: {e}") from e
        if not isinstance(env, dict) or not {"key", "version", "schema_version", "value"} <= set(env):
            raise StorageError(f"state file {os.path.basename(path)} is not a state record")
        return env

    @staticmethod
    def _record(env):
        return StateRecord(key=env["key"], version=env["version"], schema_version=env["schema_version"], value=env["value"])

    def _write_envelope(self, path, env, lock):
        data = (_dump(env) + "\n").encode("utf-8")
        tmp = os.path.join(os.path.dirname(path), f"{TMP_PREFIX}{uuid.uuid4().hex}")
        with open(tmp, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        try:
            if self._pre_replace_hook: self._pre_replace_hook()
            lock.assert_owned()  # still the owner immediately before the replace, or write nothing
            _retry_permission(lambda: os.replace(tmp, path))
        except BaseException:
            try: os.remove(tmp)
            except OSError: pass
            raise

    # ------------------------------------------------------------------ StateStore
    def get(self, key):
        env = self._read_envelope(self._state_path(key))
        return None if env is None else self._record(env)

    def put_new(self, key, value, schema_version):
        path = self._state_path(key); _dump(value)
        if not isinstance(value, dict): raise StorageError("state values must be JSON objects")

        def op(lock):
            if os.path.exists(path): raise StateExists(key)
            env = {"key": key, "version": 1, "schema_version": int(schema_version), "value": value}
            self._write_envelope(path, env, lock)
            return self._record(json.loads(_dump(env)))
        return self._locked(path, op)

    def compare_and_set(self, key, expected_version, value, schema_version):
        path = self._state_path(key); _dump(value)
        if not isinstance(value, dict): raise StorageError("state values must be JSON objects")

        def op(lock):
            cur = self._read_envelope(path)
            if cur is None: raise StateMissing(key)
            if cur["version"] != expected_version:
                raise StaleHead(f"{key}: expected version {expected_version}, found {cur['version']}")
            env = {"key": key, "version": cur["version"] + 1, "schema_version": int(schema_version), "value": value}
            self._write_envelope(path, env, lock)
            return self._record(json.loads(_dump(env)))
        return self._locked(path, op)

    def list(self, prefix=""):
        if prefix: validate_key(prefix)
        base = os.path.join(self.root, *prefix.split("/")) if prefix else self.root
        paths = []
        if os.path.isfile(base + STATE_SUFFIX): paths.append(base + STATE_SUFFIX)
        for d, _dirs, names in os.walk(base) if os.path.isdir(base) else ():
            paths += [os.path.join(d, n) for n in names if n.endswith(STATE_SUFFIX) and not n.startswith(TMP_PREFIX)]
        out = []
        for p in paths:
            env = self._read_envelope(p)
            if env is not None: out.append(self._record(env))
        return sorted(out, key=lambda r: r.key)

    def _event_lines(self, path):
        """[(parsed line, complete)] - the last line may be incomplete (no newline)."""
        def read():
            try:
                with open(path, "rb") as f: return f.read()
            except (FileNotFoundError, NotADirectoryError): return b""
        raw = _retry_permission(read)
        if not raw: return []
        parts = raw.split(b"\n")
        tail_incomplete = parts[-1] != b""
        lines = [p for p in parts[:-1]] + ([parts[-1]] if tail_incomplete else [])
        out = []
        for i, ln in enumerate(lines):
            complete = not (tail_incomplete and i == len(lines) - 1)
            try: ev = json.loads(ln.decode("utf-8"))
            except ValueError as e:
                if not complete: out.append((None, False)); continue
                raise StorageError(f"{os.path.basename(path)} line {i + 1} is not valid JSON: {e}") from e
            out.append((ev, complete))
        return out

    TAIL_BLOCK = 8192

    def _last_seq(self, path):
        """Sequence number of the last event, read from the file tail only (no full parse). 0 for a missing or empty
        file. A file that does not end in a newline holds a torn line: a writer refuses to build on it."""
        def read():
            try: f = open(path, "rb")
            except (FileNotFoundError, NotADirectoryError): return 0
            with f:
                size = f.seek(0, os.SEEK_END)
                if size == 0: return 0
                buf, pos = b"", size
                while True:
                    step = min(self.TAIL_BLOCK, pos); pos -= step
                    f.seek(pos); buf = f.read(step) + buf
                    if buf[-1:] != b"\n":
                        raise StorageError(f"{os.path.basename(path)} ends in a torn line; refusing to append")
                    cut = buf[:-1].rfind(b"\n")
                    if cut >= 0 or pos == 0: return buf[cut + 1:-1]
        last = _retry_permission(read)
        if last == 0: return 0
        try: return int(json.loads(last.decode("utf-8"))["seq"])
        except (ValueError, KeyError, TypeError) as e:
            raise StorageError(f"{os.path.basename(path)}: last line is not a valid event: {e}") from e

    def append_event(self, stream, event, schema_version, durable=False):
        """durable=True fsyncs the line before returning (state-changing events). The default flushes only: a progress
        event survives a process crash but may be lost in a power cut."""
        path = self._events_path(stream); _dump(event)
        if not isinstance(event, dict): raise StorageError("events must be JSON objects")

        def op(lock):
            seq = self._last_seq(path) + 1
            line = (_dump({"seq": seq, "schema_version": int(schema_version), "event": event}) + "\n").encode("utf-8")
            lock.assert_owned()
            with open(path, "ab") as f:
                f.write(line); f.flush()
                if durable: os.fsync(f.fileno())
            return seq
        return self._locked(path, op)

    def events(self, stream, after=0):
        return [{"seq": e["seq"], "schema_version": e["schema_version"], "event": e["event"]}
                for e, complete in self._event_lines(self._events_path(stream)) if complete and e["seq"] > after]
