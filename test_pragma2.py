import sqlite3
import time
import os
import contextlib

class JobStore2:
    def __init__(self, db_path: str) -> None:
        self._db_path = str(db_path)
        import threading
        self._lock = threading.Lock()
        with contextlib.closing(sqlite3.connect(self._db_path, timeout=30.0)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, output_path TEXT, output_name TEXT, error TEXT, temp_dir TEXT)")

    import contextlib as cl
    @cl.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
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

if os.path.exists("test2.db"):
    os.remove("test2.db")

store = JobStore2("test2.db")
start = time.time()
for i in range(1000):
    store.get("foo")
print("After optimization:", time.time() - start)
