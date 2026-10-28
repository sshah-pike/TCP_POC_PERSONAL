"""StateStore on SQLite (WAL). Safe across the UI server and worker processes: every write is one IMMEDIATE transaction."""
import json, os, sqlite3

from tcp_planner.storage.interfaces import (StateStore, StateRecord, StateExists, StateMissing, StaleHead, StorageError,
                                            validate_key)

_COLS = "key, version, schema_version, value"


def _dump(value):
    if not isinstance(value, dict): raise StorageError("state values must be JSON objects")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class SqliteStateStore(StateStore):
    def __init__(self, path, timeout_s=30.0):
        self.path = os.path.abspath(path); self.timeout_s = timeout_s
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, version INTEGER NOT NULL, "
                      "schema_version INTEGER NOT NULL, value TEXT NOT NULL)")
            c.execute("CREATE TABLE IF NOT EXISTS events (stream TEXT NOT NULL, seq INTEGER NOT NULL, "
                      "schema_version INTEGER NOT NULL, event TEXT NOT NULL, PRIMARY KEY (stream, seq))")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=self.timeout_s, isolation_level=None)
        c.execute("PRAGMA busy_timeout=%d" % int(self.timeout_s * 1000))
        return _Closing(c)

    @staticmethod
    def _rec(row):
        return StateRecord(key=row[0], version=row[1], schema_version=row[2], value=json.loads(row[3]))

    def get(self, key):
        with self._conn() as c:
            row = c.execute(f"SELECT {_COLS} FROM state WHERE key=?", (validate_key(key),)).fetchone()
        return self._rec(row) if row else None

    def put_new(self, key, value, schema_version):
        validate_key(key); text = _dump(value)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM state WHERE key=?", (key,)).fetchone():
                c.execute("ROLLBACK"); raise StateExists(key)
            c.execute("INSERT INTO state VALUES (?,?,?,?)", (key, 1, int(schema_version), text))
            c.execute("COMMIT")
        return StateRecord(key, 1, int(schema_version), json.loads(text))

    def compare_and_set(self, key, expected_version, value, schema_version):
        validate_key(key); text = _dump(value)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT version FROM state WHERE key=?", (key,)).fetchone()
            if row is None:
                c.execute("ROLLBACK"); raise StateMissing(key)
            if row[0] != expected_version:
                c.execute("ROLLBACK"); raise StaleHead(f"{key}: expected version {expected_version}, found {row[0]}")
            c.execute("UPDATE state SET version=?, schema_version=?, value=? WHERE key=?",
                      (row[0] + 1, int(schema_version), text, key))
            c.execute("COMMIT")
        return StateRecord(key, row[0] + 1, int(schema_version), json.loads(text))

    def list(self, prefix=""):
        if prefix: validate_key(prefix)
        with self._conn() as c:
            rows = c.execute(f"SELECT {_COLS} FROM state ORDER BY key").fetchall()
        # whole-segment prefix match in Python: keys never contain LIKE wildcards worth escaping around
        return [self._rec(r) for r in rows if not prefix or r[0] == prefix or r[0].startswith(prefix + "/")]

    def append_event(self, stream, event, schema_version):
        validate_key(stream); text = _dump(event)
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            seq = (c.execute("SELECT MAX(seq) FROM events WHERE stream=?", (stream,)).fetchone()[0] or 0) + 1
            c.execute("INSERT INTO events VALUES (?,?,?,?)", (stream, seq, int(schema_version), text))
            c.execute("COMMIT")
        return seq

    def events(self, stream, after=0):
        with self._conn() as c:
            rows = c.execute("SELECT seq, schema_version, event FROM events WHERE stream=? AND seq>? ORDER BY seq",
                             (validate_key(stream), int(after))).fetchall()
        return [{"seq": r[0], "schema_version": r[1], "event": json.loads(r[2])} for r in rows]


class _Closing:
    """sqlite3's own context manager ends a transaction but does not close; close the connection on exit."""
    def __init__(self, conn): self.c = conn
    def __enter__(self): return self.c
    def __exit__(self, *exc): self.c.close(); return False
