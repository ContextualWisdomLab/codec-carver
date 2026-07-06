"""SQLite-backed durable job store for the async web job API.

The web service's job endpoints (``POST /jobs`` -> ``GET /jobs/{id}`` ->
``GET /jobs/{id}/result``) need to remember job state between requests.
Keeping that state in a per-process dict loses every job on restart and
breaks status polling as soon as the app runs with more than one worker
process. This module persists jobs in a small SQLite database instead:

* Job state survives process restarts and crashes.
* Multiple worker processes on the same host share one consistent view
  (SQLite WAL mode allows concurrent readers alongside a single writer).
* Jobs orphaned by a dead process can be detected and failed explicitly
  (`recover_interrupted`), and old terminal jobs can be swept together
  with their on-disk workspaces (`purge_stale`).

The database location defaults to a per-host path under the system temp
directory; production deployments should point ``CODEC_CARVER_JOB_DB`` at
a persistent volume.
"""

import contextlib
import os
import sqlite3
import tempfile
import time
from pathlib import Path

#: Environment variable that overrides the job database location.
DB_PATH_ENV = "CODEC_CARVER_JOB_DB"

#: Job states considered "in flight". Jobs found in these states at process
#: startup were orphaned by a previous process, because background workers do
#: not survive a restart.
ACTIVE_STATUSES = ("queued", "processing")

#: Job states that will never change again.
TERMINAL_STATUSES = ("done", "failed")

#: Default retention for terminal jobs before `purge_stale` reaps them.
DEFAULT_RETENTION_SECONDS = 24 * 60 * 60

#: Columns callers may set through `create` / `update`. Everything else is
#: managed by the store itself.
_MUTABLE_FIELDS = frozenset(
    {"status", "temp_dir", "output_path", "output_name", "error"}
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    temp_dir    TEXT,
    output_path TEXT,
    output_name TEXT,
    error       TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
)
"""


def default_db_path() -> Path:
    """Return the job database path, honouring the ``CODEC_CARVER_JOB_DB`` env var.

    The fallback lives under the system temp directory so the service works
    with zero configuration and all worker processes on a host agree on the
    location. Deployments that must survive host reboots should set the env
    var to a path on a persistent volume.
    """
    configured = os.environ.get(DB_PATH_ENV)
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "codec-carver" / "jobs.db"


class JobStore:
    """Durable job-state store backed by a single SQLite database file.

    Every operation opens a short-lived connection, so one instance may be
    shared freely across threads, and separate processes pointed at the same
    path see a single consistent store.
    """

    def __init__(self, db_path: Path | str):
        """Create the store, its parent directory, and the schema if missing."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    @contextlib.contextmanager
    def _connect(self):
        """Yield a short-lived WAL connection wrapped in one transaction.

        The connection is committed on success, rolled back on error, and
        always closed, so no file handles outlive the operation.
        """
        conn = sqlite3.connect(self.db_path, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, job_id: str, **fields) -> None:
        """Insert a new job row. Unknown fields raise ``ValueError``."""
        self._check_fields(fields)
        fields.setdefault("status", "queued")
        now = time.time()
        columns = ["job_id", "created_at", "updated_at", *fields]
        placeholders = ", ".join("?" for _ in columns)
        values = [job_id, now, now, *fields.values()]
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )

    def get(self, job_id: str) -> dict | None:
        """Return one job as a dict, or ``None`` if the id is unknown."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def all_jobs(self) -> list[dict]:
        """Return every job row, oldest first. Intended for ops and tests."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def update(self, job_id: str, **fields) -> bool:
        """Update mutable fields on a job; return ``False`` for unknown ids."""
        self._check_fields(fields)
        if not fields:
            return self.get(job_id) is not None
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = [*fields.values(), time.time(), job_id]
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at = ? WHERE job_id = ?",
                values,
            )
            return cursor.rowcount > 0

    def delete(self, job_id: str) -> dict | None:
        """Remove a job and return its final row, or ``None`` if unknown.

        Returning the row lets callers release resources the job owned
        (its temp workspace) exactly once, even under concurrent deletes:
        only one caller observes the row.
        """
        with self._connect() as conn:
            row = conn.execute(
                "DELETE FROM jobs WHERE job_id = ? RETURNING *", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def recover_interrupted(self) -> list[dict]:
        """Fail every queued/processing job left behind by a dead process.

        Background workers die with the process that spawned them, so any job
        still marked active when a fresh process starts will never progress.
        Marking them ``failed`` turns silent hangs into an honest error for
        polling clients. Returns the affected rows (post-update) so the caller
        can clean up their temp workspaces.
        """
        placeholders = ", ".join("?" for _ in ACTIVE_STATUSES)
        with self._connect() as conn:
            rows = conn.execute(
                f"UPDATE jobs SET status = 'failed', "
                f"error = 'Interrupted by service restart', updated_at = ? "
                f"WHERE status IN ({placeholders}) RETURNING *",
                (time.time(), *ACTIVE_STATUSES),
            ).fetchall()
        return [dict(row) for row in rows]

    def purge_stale(
        self, max_age_seconds: float = DEFAULT_RETENTION_SECONDS
    ) -> list[dict]:
        """Delete terminal jobs untouched for ``max_age_seconds``.

        Finished jobs whose results are never downloaded would otherwise keep
        their rows (and, for ``done`` jobs, their output workspaces) forever.
        Returns the deleted rows so the caller can remove those workspaces.
        """
        cutoff = time.time() - max_age_seconds
        placeholders = ", ".join("?" for _ in TERMINAL_STATUSES)
        with self._connect() as conn:
            rows = conn.execute(
                f"DELETE FROM jobs WHERE status IN ({placeholders}) "
                f"AND updated_at < ? RETURNING *",
                (*TERMINAL_STATUSES, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _check_fields(fields: dict) -> None:
        """Reject field names outside the mutable-column whitelist."""
        unknown = set(fields) - _MUTABLE_FIELDS
        if unknown:
            raise ValueError(f"Unknown job fields: {sorted(unknown)}")
