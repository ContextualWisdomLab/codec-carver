"""SQLite-backed durable job store for async/worker job tracking.

The FastAPI layer uses this store for restart-safe asynchronous job state.
The store is stdlib-only, uses SQLite WAL journaling, and keeps each operation
on a short-lived connection so independent web/worker processes can share the
same database file.

Design notes:

- Every public operation is serialized per ``JobStore`` instance; SQLite
  coordinates independent processes.
- WAL mode allows concurrent readers while a writer updates durable job state.
- Callers pass ``now`` explicitly; the store never reads wall-clock time itself.
- Historical ``jobs(id, status, error, ...)`` databases are migrated in place to
  the semantic ``job_record(job_id, job_status, error_message, ...)`` schema.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

#: Allowed job lifecycle states.
VALID_STATUSES = frozenset({"queued", "processing", "done", "failed"})

_JOB_RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS job_record (
    job_id        TEXT PRIMARY KEY,
    job_status    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    output_path   TEXT,
    output_name   TEXT,
    error_message TEXT,
    temp_dir      TEXT
)
"""

_JOB_RECORD_COLUMNS = (
    "job_id",
    "job_status",
    "created_at",
    "updated_at",
    "output_path",
    "output_name",
    "error_message",
    "temp_dir",
)


class DuplicateJobError(ValueError):
    """Raised by :meth:`JobStore.create` when the job id already exists."""


class JobStore:
    """Durable, thread-safe job store backed by a SQLite database file.

    Multiple processes may open independent ``JobStore`` instances on the same
    ``db_path``. SQLite file locking plus WAL mode keeps reads and writes
    consistent; within one process, one instance may be shared across threads.

    Args:
        db_path: Filesystem path of the SQLite database. Created together with
            the semantic schema when absent. ``":memory:"`` is unsupported
            because each operation opens a fresh connection.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the durable store and migrate historical schema names."""

        if db_path == ":memory:":
            raise ValueError(
                "JobStore requires a file path; ':memory:' databases do "
                "not survive the short-lived connections this store uses"
            )
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        with self._connect() as connection:
            self._ensure_job_record_schema(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived WAL-mode connection with rollback on failure."""

        connection = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
        """Return whether ``table_name`` exists in the current SQLite schema."""

        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _job_record_column_names(connection: sqlite3.Connection) -> set[str]:
        """Return physical columns currently present on ``job_record``."""

        return {
            str(column_row[1])
            for column_row in connection.execute("PRAGMA table_info(job_record)")
        }

    def _ensure_job_record_schema(self, connection: sqlite3.Connection) -> None:
        """Create or atomically migrate the durable job-record schema.

        ``BEGIN IMMEDIATE`` serializes competing process startup writers. The
        migration uses SQLite metadata renames only, preserving rows and the
        primary-key index without copy/delete backfill. If both historical and
        semantic tables exist simultaneously, initialization fails closed
        rather than guessing which table owns durable state.
        """

        connection.execute("BEGIN IMMEDIATE")
        historical_table_exists = self._table_exists(connection, "jobs")
        semantic_table_exists = self._table_exists(connection, "job_record")
        if historical_table_exists and semantic_table_exists:
            raise RuntimeError(
                "ambiguous durable job schema: both jobs and job_record exist"
            )

        if historical_table_exists:
            connection.execute("ALTER TABLE jobs RENAME TO job_record")
            semantic_table_exists = True

        if not semantic_table_exists:
            connection.execute(_JOB_RECORD_SCHEMA)
            return

        column_names = self._job_record_column_names(connection)
        legacy_column_renames = (
            ("id", "job_id"),
            ("status", "job_status"),
            ("error", "error_message"),
        )
        for historical_column_name, semantic_column_name in legacy_column_renames:
            if (
                historical_column_name in column_names
                and semantic_column_name in column_names
            ):
                raise RuntimeError(
                    "ambiguous durable job schema: both "
                    f"{historical_column_name} and {semantic_column_name} exist"
                )
            if historical_column_name in column_names:
                connection.execute(
                    "ALTER TABLE job_record RENAME COLUMN "
                    f"{historical_column_name} TO {semantic_column_name}"
                )
                column_names.remove(historical_column_name)
                column_names.add(semantic_column_name)

        required_column_names = set(_JOB_RECORD_COLUMNS)
        if column_names != required_column_names:
            missing_column_names = sorted(required_column_names - column_names)
            unexpected_column_names = sorted(column_names - required_column_names)
            raise RuntimeError(
                "unsupported durable job schema after naming migration; "
                f"missing={missing_column_names!r}, "
                f"unexpected={unexpected_column_names!r}"
            )

    @staticmethod
    def _validate_job_status(job_status: str) -> None:
        """Reject job lifecycle states outside the allowed set."""

        if job_status not in VALID_STATUSES:
            allowed_job_statuses = ", ".join(sorted(VALID_STATUSES))
            raise ValueError(
                f"invalid job status {job_status!r}; must be one of: "
                f"{allowed_job_statuses}"
            )

    @staticmethod
    def _row_to_job_record(row: sqlite3.Row) -> dict:
        """Convert a SQLite row to the organization-owned semantic job record."""

        return {column_name: row[column_name] for column_name in _JOB_RECORD_COLUMNS}

    def create(self, job_id: str, *, temp_dir: str, now: datetime) -> None:
        """Insert a new durable job record in the ``queued`` state."""

        timestamp = now.isoformat()
        with self._lock, self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO job_record "
                    "(job_id, job_status, created_at, updated_at, temp_dir) "
                    "VALUES (?, 'queued', ?, ?, ?)",
                    (job_id, timestamp, timestamp, temp_dir),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateJobError(
                    f"job {job_id!r} already exists"
                ) from exc

    def set_status(
        self,
        job_id: str,
        job_status: str,
        *,
        now: datetime,
        output_path: str | None = None,
        output_name: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a job's lifecycle state, timestamp, and optional result data."""

        self._validate_job_status(job_status)
        with self._lock, self._connect() as connection:
            update_cursor = connection.execute(
                "UPDATE job_record SET job_status = ?, updated_at = ?,"
                " output_path = COALESCE(?, output_path),"
                " output_name = COALESCE(?, output_name),"
                " error_message = COALESCE(?, error_message)"
                " WHERE job_id = ?",
                (
                    job_status,
                    now.isoformat(),
                    output_path,
                    output_name,
                    error_message,
                    job_id,
                ),
            )
            if update_cursor.rowcount == 0:
                raise KeyError(f"job {job_id!r} does not exist")

    def get(self, job_id: str) -> dict | None:
        """Fetch one semantic durable job record by ``job_id``."""

        with self._lock, self._connect() as connection:
            job_row = connection.execute(
                "SELECT * FROM job_record WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job_record(job_row) if job_row is not None else None

    def list_jobs(self, job_status: str | None = None) -> list[dict]:
        """List durable job records, optionally filtered by ``job_status``."""

        with self._lock, self._connect() as connection:
            if job_status is None:
                job_rows = connection.execute(
                    "SELECT * FROM job_record ORDER BY created_at, job_id"
                ).fetchall()
            else:
                self._validate_job_status(job_status)
                job_rows = connection.execute(
                    "SELECT * FROM job_record WHERE job_status = ?"
                    " ORDER BY created_at, job_id",
                    (job_status,),
                ).fetchall()
        return [self._row_to_job_record(job_row) for job_row in job_rows]

    def delete(self, job_id: str) -> None:
        """Delete the durable job record for ``job_id`` when present."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM job_record WHERE job_id = ?",
                (job_id,),
            )
