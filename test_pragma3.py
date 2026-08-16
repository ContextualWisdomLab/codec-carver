import sqlite3
import time
import os
import contextlib

class JobStoreBefore:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
        import threading
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, output_path TEXT, output_name TEXT, error TEXT, temp_dir TEXT)")

    import contextlib as cl
    @cl.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, job_id: str) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None


class JobStoreAfter:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
        import threading
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript("PRAGMA journal_mode=WAL;\nCREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, output_path TEXT, output_name TEXT, error TEXT, temp_dir TEXT)")

    import contextlib as cl
    @cl.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            # Removed PRAGMA here
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get(self, job_id: str) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None

if os.path.exists("test_b.db"): os.remove("test_b.db")
if os.path.exists("test_a.db"): os.remove("test_a.db")

store_b = JobStoreBefore("test_b.db")
start = time.time()
for i in range(10000):
    store_b.get("foo")
print("Before:", time.time() - start)

store_a = JobStoreAfter("test_a.db")
start = time.time()
for i in range(10000):
    store_a.get("foo")
print("After:", time.time() - start)
