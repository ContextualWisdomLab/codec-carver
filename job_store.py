"""SQLite-backed durable store for asynchronous conversion jobs.

``saas_web.py`` persists each upload-and-shrink request here so status
survives process restart and is visible to a worker. The store is
stdlib-only (``sqlite3`` with WAL journaling).

Design notes:

- Every public method opens a short-lived connection guarded by a lock,
  so a single ``JobStore`` instance is safe to share across threads.
- WAL mode allows concurrent readers alongside a writer, which suits a
  web process polling job status while a worker updates it.
- Callers pass ``now`` (a :class:`datetime.datetime`) explicitly; the
  store never calls ``datetime.now()`` itself, keeping tests
  deterministic.
- The physical table is ``conversion_jobs``. Single-word legacy
  ``jobs`` files are copied forward on open. See
  ``docs/doctoring/conversion-jobs-schema.md``.

Example:
    >>> from datetime import datetime, timezone
    >>> store = JobStore("/tmp/conversion_jobs.db")  # doctest: +SKIP
    >>> store.create("job-1", temp_dir="/tmp/job-1",
    ...              now=datetime.now(timezone.utc))  # doctest: +SKIP
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

#: Allowed conversion-job lifecycle states.
VALID_STATUSES = frozenset({"queued", "processing", "done", "failed"})

_CONVERSION_JOBS_TABLE = "conversion_jobs"
_LEGACY_JOBS_TABLE = "jobs"
_LEGACY_JOBS_COLUMNS = (
    "id",
    "status",
    "created_at",
    "updated_at",
    "output_path",
    "output_name",
    "error",
    "temp_dir",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversion_jobs (
    job_id         TEXT PRIMARY KEY,
    job_status     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    output_path    TEXT,
    output_name    TEXT,
    error_message  TEXT,
    temp_dir       TEXT
)
"""

_COLUMNS = (
    "job_id",
    "job_status",
    "created_at",
    "updated_at",
    "output_path",
    "output_name",
    "error_message",
    "temp_dir",
)


def _list_user_tables(conn: sqlite3.Connection) -> set[str]:
    """Return user table names stored in ``conn``.

    Args:
        conn: Open SQLite connection.

    Returns:
        The set of table names from ``sqlite_master``.
    """
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in rows}


def _list_table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    """Return column names for ``table_name`` in declaration order.

    Args:
        conn: Open SQLite connection.
        table_name: Table to inspect. Only ``jobs`` or
            ``conversion_jobs`` are accepted so the PRAGMA cannot be
            pointed at an attacker-chosen identifier.

    Returns:
        Column names as declared in the table.

    Raises:
        ValueError: If ``table_name`` is not one of the store tables.
    """
    if table_name not in {_CONVERSION_JOBS_TABLE, _LEGACY_JOBS_TABLE}:
        raise ValueError(f"refusing to inspect unexpected table {table_name!r}")
    rows = conn.execute(f"PRAGMA table_info({table_name})")
    return tuple(row[1] for row in rows)


def _migrate_legacy_jobs_table(conn: sqlite3.Connection) -> None:
    """Copy a one-word ``jobs`` table into ``conversion_jobs`` and drop it.

    Args:
        conn: Open SQLite connection that already has ``conversion_jobs``.

    Raises:
        ValueError: If ``jobs`` exists but its columns are not the
            historical schema this store used to write.
    """
    tables = _list_user_tables(conn)
    if _LEGACY_JOBS_TABLE not in tables:
        return
    columns = _list_table_columns(conn, _LEGACY_JOBS_TABLE)
    if columns != _LEGACY_JOBS_COLUMNS:
        raise ValueError(
            "legacy jobs table has unexpected columns "
            f"{columns!r}; expected {_LEGACY_JOBS_COLUMNS!r}"
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO conversion_jobs (
            job_id, job_status, created_at, updated_at,
            output_path, output_name, error_message, temp_dir
        )
        SELECT id, status, created_at, updated_at,
               output_path, output_name, error, temp_dir
        FROM jobs
        """
    )
    conn.execute("DROP TABLE jobs")


class DuplicateJobError(ValueError):
    """Raised by :meth:`JobStore.create` when the job id already exists."""


class JobStore:
    """Durable, thread-safe conversion-job store backed by SQLite.

    Multiple processes may open independent ``JobStore`` instances on the
    same ``db_path``; SQLite's file locking plus WAL mode keeps their
    reads and writes consistent. Within one process, a single instance
    may be shared freely across threads.

    Args:
        db_path: Filesystem path of the SQLite database. Created (along
            with the schema) if it does not exist. ``":memory:"`` is not
            supported because each operation opens a fresh connection,
            which would discard an in-memory database every time.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the store and create or migrate the schema.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            ValueError: If ``db_path`` is ``":memory:"``, or if a legacy
                ``jobs`` table exists with an unexpected column set.
        """
        if db_path == ":memory:":
            raise ValueError(
                "JobStore requires a file path; ':memory:' databases do "
                "not survive the short-lived connections this store uses"
            )
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            _migrate_legacy_jobs_table(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a new WAL-mode connection to the underlying database.

        Yields:
            A short-lived ``sqlite3.Connection`` with WAL journaling and
            a row factory that yields ``sqlite3.Row`` objects.
        """
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _validate_status(status: str) -> None:
        """Reject statuses outside the allowed lifecycle set.

        Args:
            status: Candidate status string.

        Raises:
            ValueError: If ``status`` is not one of ``VALID_STATUSES``.
        """
        if status not in VALID_STATUSES:
            allowed = ", ".join(sorted(VALID_STATUSES))
            raise ValueError(
                f"invalid status {status!r}; must be one of: {allowed}"
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a database row into a plain conversion-job dict.

        Args:
            row: A ``sqlite3.Row`` from the ``conversion_jobs`` table.

        Returns:
            A dict with the keys ``job_id``, ``job_status``,
            ``created_at``, ``updated_at``, ``output_path``,
            ``output_name``, ``error_message``, and ``temp_dir``.
        """
        return {key: row[key] for key in _COLUMNS}

    def create(self, job_id: str, *, temp_dir: str, now: datetime) -> None:
        """Insert a new conversion job in the ``queued`` state.

        Args:
            job_id: Unique identifier for the job.
            temp_dir: Working directory associated with the job (stored
                so a cleanup pass can remove it later).
            now: Timestamp recorded as both ``created_at`` and
                ``updated_at`` (ISO 8601 via ``datetime.isoformat()``).

        Raises:
            DuplicateJobError: If a job with ``job_id`` already exists.
                (Subclass of ``ValueError``, so callers may catch either.)
        """
        timestamp = now.isoformat()
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO conversion_jobs (job_id, job_status,"
                    " created_at, updated_at, temp_dir)"
                    " VALUES (?, 'queued', ?, ?, ?)",
                    (job_id, timestamp, timestamp, temp_dir),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateJobError(
                    f"job {job_id!r} already exists"
                ) from exc

    def set_status(
        self,
        job_id: str,
        status: str,
        *,
        now: datetime,
        output_path: str | None = None,
        output_name: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a job's status, timestamp, and optional result fields.

        Only the fields passed as non-``None`` keyword arguments are
        overwritten; previously stored values for ``output_path``,
        ``output_name``, and ``error_message`` are preserved otherwise.

        Args:
            job_id: Identifier of the job to update.
            status: New status; one of ``queued``, ``processing``,
                ``done``, or ``failed``.
            now: Timestamp recorded as ``updated_at``.
            output_path: Path of the finished output file, if any.
            output_name: Client-facing download name, if any.
            error_message: Human-readable failure message, if any.

        Raises:
            ValueError: If ``status`` is not allowed.
            KeyError: If no job with ``job_id`` exists.
        """
        self._validate_status(status)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE conversion_jobs SET job_status = ?, updated_at = ?,"
                " output_path = COALESCE(?, output_path),"
                " output_name = COALESCE(?, output_name),"
                " error_message = COALESCE(?, error_message)"
                " WHERE job_id = ?",
                (status, now.isoformat(), output_path, output_name,
                 error_message, job_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"job {job_id!r} does not exist")

    def get(self, job_id: str) -> dict | None:
        """Fetch a single conversion job by id.

        Args:
            job_id: Identifier of the job to look up.

        Returns:
            The job as a dict (see :meth:`_row_to_dict` for keys), or
            ``None`` if no such job exists.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversion_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_jobs(self, status: str | None = None) -> list[dict]:
        """List conversion jobs, optionally filtered by status.

        Args:
            status: If given, only jobs in this state are returned; must
                be one of the allowed statuses.

        Returns:
            Jobs as dicts, ordered by ``created_at`` then ``job_id`` for
            a stable listing.

        Raises:
            ValueError: If ``status`` is given but not allowed.
        """
        with self._lock, self._connect() as conn:
            if status is None:
                rows = conn.execute(
                    "SELECT * FROM conversion_jobs"
                    " ORDER BY created_at, job_id"
                ).fetchall()
            else:
                self._validate_status(status)
                rows = conn.execute(
                    "SELECT * FROM conversion_jobs WHERE job_status = ?"
                    " ORDER BY created_at, job_id",
                    (status,),
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def delete(self, job_id: str) -> None:
        """Remove a conversion-job record if it exists.

        Deleting an unknown id is a no-op, so cleanup passes can call
        this without checking existence first.

        Args:
            job_id: Identifier of the job to remove.
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM conversion_jobs WHERE job_id = ?", (job_id,)
            )
