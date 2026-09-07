"""Per-credential usage metering and monthly quota enforcement.

This module sits between request-time authentication (*which credential*
called) and billing (*how much* they used). It records conversion count,
input bytes, and output bytes in SQLite and enforces monthly quotas.

Design notes:

* Storage is stdlib :mod:`sqlite3` in WAL mode so readers never block the
  writer and counters survive process restarts.
* Rows are keyed by ``credential_id`` from
  :meth:`credential_registry.CredentialRegistry.verify_api_key`, never by
  plaintext API keys.
* Usage is bucketed by *billing period*, a ``"YYYY-MM"`` string derived
  from a caller-supplied :class:`datetime.datetime`. Callers pass ``now``
  explicitly (the module never calls ``datetime.now()`` itself) so tests
  are deterministic and month boundaries stay explicit.
* Every operation opens a short-lived connection, which combined with a
  process-level lock makes :class:`UsageStore` safe to share across threads.

Example::

    store = UsageStore("/var/lib/carver/usage.db")
    now = datetime.now(timezone.utc)
    store.check_quota(credential_id, now, max_conversions=100)
    store.record(
        credential_id, input_bytes=len(payload), output_bytes=len(result), now=now
    )
"""

from __future__ import annotations

import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

__all__ = [
    "MAX_CREDENTIAL_ID_BYTES",
    "QuotaExceededError",
    "UsageStore",
    "seconds_until_next_period",
]

#: Maximum UTF-8 size of a stored credential primary key.
MAX_CREDENTIAL_ID_BYTES = 128

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_periods (
    credential_id TEXT NOT NULL,
    billing_period TEXT NOT NULL,
    conversion_count INTEGER NOT NULL DEFAULT 0,
    input_bytes INTEGER NOT NULL DEFAULT 0,
    output_bytes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (credential_id, billing_period)
)
"""


class QuotaExceededError(Exception):
    """Raised when a credential has exhausted its quota for the period.

    Attributes:
        credential_id: The billed credential primary key. Never a
            plaintext API key.
        limit_name: Which limit was exceeded (``"max_conversions"`` or
            ``"max_bytes"``).
        limit: The configured limit value.
        used: The usage value that met or exceeded the limit.
    """

    def __init__(
        self, credential_id: str, limit_name: str, limit: int, used: int
    ) -> None:
        """Store the quota-violation details and build a readable message.

        Args:
            credential_id: Credential whose quota was exceeded.
            limit_name: Name of the exceeded limit.
            limit: Configured maximum for that limit.
            used: Current usage that hit the limit.
        """

        self.credential_id = credential_id
        self.limit_name = limit_name
        self.limit = limit
        self.used = used
        super().__init__(
            f"quota exceeded for credential {credential_id!r}: "
            f"{limit_name}={limit} reached (used={used})"
        )


def _period(now: datetime) -> str:
    """Return the monthly billing period for ``now`` as ``"YYYY-MM"``.

    Args:
        now: The instant to bucket. Naive or aware datetimes both work; the
            period is derived from the datetime's own year and month.

    Returns:
        The zero-padded period string, e.g. ``"2026-07"``.
    """

    return f"{now.year:04d}-{now.month:02d}"


def seconds_until_next_period(now: datetime) -> int:
    """Return seconds from ``now`` until the next monthly billing period.

    Operators can send this as ``Retry-After`` so a blocked customer knows
    when the next invoice bucket opens.

    Args:
        now: Current instant in the same tzinfo used for billing.

    Returns:
        At least ``1`` second. February starts at day 1 00:00:00 of ``now``.
    """

    year = now.year + (1 if now.month == 12 else 0)
    month = 1 if now.month == 12 else now.month + 1
    nxt = now.replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return max(1, int((nxt - now).total_seconds()))


def _validated_credential_id(credential_id: object) -> str:
    """Reject empty, overlong, or control-bearing credential identifiers.

    Args:
        credential_id: Value supplied by the caller. Must already be a
            registry primary key, not an API key.

    Returns:
        The validated identifier.

    Raises:
        ValueError: If the value is missing, overlong, or contains
            control characters. The exception text never includes secrets.
    """

    if not isinstance(credential_id, str) or not credential_id:
        raise ValueError("credential_id must be a non-empty string")
    if len(credential_id.encode("utf-8")) > MAX_CREDENTIAL_ID_BYTES:
        raise ValueError("credential_id exceeds the maximum UTF-8 length")
    for char in credential_id:
        if unicodedata.category(char).startswith("C"):
            raise ValueError("control characters are not allowed in credential_id")
    return credential_id


class UsageStore:
    """Durable per-credential usage counters with monthly quota checks.

    Each instance owns one SQLite database file. Connections are short-lived
    (opened per operation) and writes are serialized behind an internal lock,
    so a single instance may be shared freely across threads.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Open (creating if necessary) the usage database at ``db_path``.

        Args:
            db_path: Filesystem path for the SQLite database. The parent
                directory must already exist. ``":memory:"`` is rejected
                because each operation opens a fresh connection.

        Raises:
            ValueError: If the parent directory of ``db_path`` does not exist,
                ``db_path`` points at a directory, or ``db_path`` is
                ``":memory:"``.
        """

        if str(db_path) == ":memory:":
            raise ValueError(
                "UsageStore requires a file path; ':memory:' databases "
                "do not survive the short-lived connections this store uses"
            )
        path = Path(db_path)
        if path.is_dir():
            raise ValueError(f"db_path points at a directory, not a file: {path}")
        if not path.parent.is_dir():
            raise ValueError(
                "cannot create usage database: parent directory does not exist: "
                f"{path.parent}"
            )
        self._db_path = path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def __repr__(self) -> str:
        """Return a redacted summary that never includes credential values."""

        return f"UsageStore(db_path={str(self._db_path)!r})"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived WAL-mode connection.

        Yields:
            A ``sqlite3.Connection`` with ``Row`` factory enabled.
        """

        conn = sqlite3.connect(self._db_path, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        credential_id: str,
        *,
        input_bytes: int,
        output_bytes: int,
        now: datetime,
    ) -> None:
        """Record one completed conversion for ``credential_id``.

        Increments the credential's conversion count by one and adds the
        given byte counts to its running totals for the current monthly
        period. The write is durable once this method returns.

        Args:
            credential_id: Registry primary key that performed the work.
            input_bytes: Size of the input media in bytes (must be >= 0).
            output_bytes: Size of the converted output in bytes (>= 0).
            now: The current time, supplied by the caller for determinism.

        Raises:
            ValueError: If ``input_bytes`` or ``output_bytes`` is negative,
                or ``credential_id`` is invalid.
        """

        handle = _validated_credential_id(credential_id)
        if input_bytes < 0 or output_bytes < 0:
            raise ValueError("input_bytes and output_bytes must be non-negative")
        period = _period(now)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_periods (
                    credential_id, billing_period, conversion_count,
                    input_bytes, output_bytes
                )
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT (credential_id, billing_period) DO UPDATE SET
                    conversion_count = conversion_count + 1,
                    input_bytes = input_bytes + excluded.input_bytes,
                    output_bytes = output_bytes + excluded.output_bytes
                """,
                (handle, period, input_bytes, output_bytes),
            )

    def usage(self, credential_id: str, now: datetime) -> dict:
        """Return ``credential_id`` totals for the period containing ``now``.

        Args:
            credential_id: Registry primary key to look up.
            now: The current time; selects the monthly period to report.

        Returns:
            A dict with keys ``billing_period``, ``conversions``,
            ``input_bytes``, and ``output_bytes``. Unknown credentials
            report zero for all counters.

        Raises:
            ValueError: If ``credential_id`` is invalid.
        """

        handle = _validated_credential_id(credential_id)
        period = _period(now)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT conversion_count, input_bytes, output_bytes "
                "FROM usage_periods WHERE credential_id = ? AND billing_period = ?",
                (handle, period),
            ).fetchone()
        conversions, input_bytes, output_bytes = (
            (row["conversion_count"], row["input_bytes"], row["output_bytes"])
            if row
            else (0, 0, 0)
        )
        return {
            "billing_period": period,
            "conversions": conversions,
            "input_bytes": input_bytes,
            "output_bytes": output_bytes,
        }

    def check_quota(
        self,
        credential_id: str,
        now: datetime,
        *,
        max_conversions: int | None = None,
        max_bytes: int | None = None,
    ) -> bool:
        """Check whether ``credential_id`` may perform another conversion.

        Call this *before* doing work. A credential exactly at a limit is
        denied (the limit is the total number allowed, so the next request
        would exceed it).

        Args:
            credential_id: Registry primary key to check.
            now: The current time; selects the monthly period to check.
            max_conversions: Maximum conversions allowed per period, or
                ``None`` for unlimited.
            max_bytes: Maximum combined input+output bytes allowed per
                period, or ``None`` for unlimited.

        Returns:
            ``True`` if the credential is within all supplied limits.

        Raises:
            QuotaExceededError: If any supplied limit has been reached.
            ValueError: If ``credential_id`` is invalid.
        """

        current = self.usage(credential_id, now)
        if max_conversions is not None and current["conversions"] >= max_conversions:
            raise QuotaExceededError(
                credential_id,
                "max_conversions",
                max_conversions,
                current["conversions"],
            )
        total_bytes = current["input_bytes"] + current["output_bytes"]
        if max_bytes is not None and total_bytes >= max_bytes:
            raise QuotaExceededError(
                credential_id, "max_bytes", max_bytes, total_bytes
            )
        return True

    def reset(self, credential_id: str) -> None:
        """Delete all recorded usage for ``credential_id`` across periods.

        Admin operation, e.g. after a plan change or a billing dispute.

        Args:
            credential_id: Registry primary key whose usage rows to remove.

        Raises:
            ValueError: If ``credential_id`` is invalid.
        """

        handle = _validated_credential_id(credential_id)
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM usage_periods WHERE credential_id = ?",
                (handle,),
            )

    def all_usage(self, billing_period: str) -> dict:
        """Return usage for every credential active in ``billing_period``.

        Admin/billing-export operation. Keys are credential identifiers,
        never plaintext API keys.

        Args:
            billing_period: Monthly period to report, as ``"YYYY-MM"``.

        Returns:
            A dict mapping each credential with recorded usage in the
            period to its ``conversions``, ``input_bytes``, and
            ``output_bytes``.
        """

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT credential_id, conversion_count, input_bytes, "
                "output_bytes FROM usage_periods WHERE billing_period = ? "
                "ORDER BY credential_id",
                (billing_period,),
            ).fetchall()
        return {
            row["credential_id"]: {
                "conversions": row["conversion_count"],
                "input_bytes": row["input_bytes"],
                "output_bytes": row["output_bytes"],
            }
            for row in rows
        }
