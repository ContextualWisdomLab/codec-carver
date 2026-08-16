"""SQLite-backed API credential registry for request-time authentication.

Runtime authentication reads only this registry. The process environment is
bootstrap transport: callers pass an explicit mapping into
:func:`bootstrap_from_mapping` at startup. Request handlers must not call
``os.getenv``.

Stored rows keep a SHA-256 digest of the UTF-8 key, a two-word table name
(``api_credentials``), and an explicit lifecycle. Callers pass ``now`` so
expiry and rotation stay deterministic in tests.

Example::

    store = CredentialRegistry("/var/lib/carver/api_credentials.db")
    bootstrap_from_mapping(store, {"CODEC_CARVER_API_KEYS": "alpha,beta"}, now=now)
    credential_id = store.verify(presented_header, now=now)
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime

#: Transport variable that may populate the registry at startup only.
BOOTSTRAP_ENV_NAME = "CODEC_CARVER_API_KEYS"

#: Allowed lifecycle values for ``api_credentials.lifecycle_status``.
VALID_LIFECYCLE_STATUSES = frozenset({"active", "rotated", "revoked"})

#: Maximum UTF-8 size of one API key (bootstrap or presented header).
MAX_KEY_BYTES = 256

#: Maximum number of keys accepted from one bootstrap mapping.
MAX_BOOTSTRAP_KEYS = 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id TEXT PRIMARY KEY,
    key_digest TEXT NOT NULL UNIQUE,
    lifecycle_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    rotated_at TEXT,
    revoked_at TEXT,
    expires_at TEXT
)
"""

_COLUMNS = (
    "credential_id",
    "key_digest",
    "lifecycle_status",
    "created_at",
    "updated_at",
    "rotated_at",
    "revoked_at",
    "expires_at",
)


class CredentialRegistryError(ValueError):
    """Raised when a registry mutation names an unknown credential."""


class InvalidApiKeyError(ValueError):
    """Raised when a bootstrap or register payload fails validation.

    The exception message names the broken rule only. It never includes the
    rejected secret.
    """


def digest_api_key(api_key: str) -> str:
    """Return the SHA-256 hex digest of ``api_key`` encoded as UTF-8.

    Args:
        api_key: Presented or configured secret.

    Returns:
        A 64-character hexadecimal digest used for storage and comparison.
    """

    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def parse_bootstrap_api_keys(raw: str) -> list[str]:
    """Parse a comma-separated bootstrap transport string.

    Args:
        raw: Operator-supplied transport payload. This function does not
            read the process environment.

    Returns:
        Distinct, stripped keys in the order they appeared.

    Raises:
        InvalidApiKeyError: If any key is empty after filtering only when
            a remaining key is malformed, duplicated, overlong, contains a
            control character, or the set exceeds :data:`MAX_BOOTSTRAP_KEYS`.
    """

    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if len(keys) > MAX_BOOTSTRAP_KEYS:
        raise InvalidApiKeyError("bootstrap API key count exceeds the maximum")
    seen: set[str] = set()
    for key in keys:
        _validate_api_key(key)
        if key in seen:
            raise InvalidApiKeyError("bootstrap API keys contain a duplicate")
        seen.add(key)
    return keys


def _validate_api_key(api_key: str) -> None:
    """Reject empty, overlong, or control-character secrets.

    Args:
        api_key: Candidate secret.

    Raises:
        InvalidApiKeyError: If the secret is not acceptable. The message
            never echoes ``api_key``.
    """

    if not api_key:
        raise InvalidApiKeyError("API key must not be empty")
    if any(ord(char) < 32 or ord(char) == 127 for char in api_key):
        raise InvalidApiKeyError("API key contains a control character")
    if len(api_key.encode("utf-8")) > MAX_KEY_BYTES:
        raise InvalidApiKeyError("API key exceeds the maximum encoded length")


def bootstrap_from_mapping(
    store: CredentialRegistry,
    mapping: Mapping[str, str],
    *,
    now: datetime,
) -> dict[str, str]:
    """Import keys from an explicit mapping into ``store``.

    Only :data:`BOOTSTRAP_ENV_NAME` is read from ``mapping``. The process
    environment is not consulted.

    Args:
        store: Destination registry.
        mapping: Bootstrap transport, typically a snapshot of ``os.environ``
            taken once at process start.
        now: Clock used for ``created_at`` / ``updated_at``.

    Returns:
        Mapping of plaintext bootstrap key to ``credential_id``. The return
        value is for the startup caller only; do not log it.
    """

    raw = mapping.get(BOOTSTRAP_ENV_NAME, "")
    imported: dict[str, str] = {}
    for key in parse_bootstrap_api_keys(raw):
        imported[key] = store.register(key, now=now)
    return imported


class CredentialRegistry:
    """Durable, thread-safe store of hashed API credentials.

    Args:
        db_path: Filesystem path of the SQLite database. Created with the
            ``api_credentials`` schema if it does not exist. ``":memory:"``
            is rejected because each operation opens a fresh connection.
    """

    def __init__(self, db_path: str) -> None:
        """Open or create the registry file and ensure the schema exists.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            ValueError: If ``db_path`` is ``":memory:"``.
        """

        if db_path == ":memory:":
            raise ValueError(
                "CredentialRegistry requires a file path; ':memory:' "
                "databases do not survive the short-lived connections "
                "this store uses"
            )
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def __repr__(self) -> str:
        """Return a secret-free debug representation."""

        return f"CredentialRegistry(db_path={self._db_path!r})"

    def __str__(self) -> str:
        """Return the same secret-free text as :meth:`__repr__`."""

        return self.__repr__()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a short-lived WAL-mode connection.

        Yields:
            A ``sqlite3.Connection`` with row factory ``sqlite3.Row``.
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
    def _row_to_dict(row: sqlite3.Row) -> dict[str, str | None]:
        """Convert a registry row into a plaintext-free record dict.

        Args:
            row: A ``sqlite3.Row`` from ``api_credentials``.

        Returns:
            A dict with :data:`_COLUMNS` keys. The original secret is never
            present.
        """

        return {key: row[key] for key in _COLUMNS}

    @staticmethod
    def _compare_digests(left: str, right: str) -> bool:
        """Compare two hex digests with ``hmac.compare_digest``.

        Args:
            left: Presented digest.
            right: Stored digest.

        Returns:
            ``True`` when the digests are equal.
        """

        return hmac.compare_digest(left, right)

    @staticmethod
    def _is_verifiable(record: dict[str, str | None], now: datetime) -> bool:
        """Return whether ``record`` may authenticate at ``now``.

        Args:
            record: A row from :meth:`list_records`.
            now: Caller-supplied clock.

        Returns:
            ``True`` when the credential is ``active`` and not expired.
        """

        if record["lifecycle_status"] != "active":
            return False
        expires_at = record["expires_at"]
        if expires_at is None:
            return True
        return datetime.fromisoformat(expires_at) > now

    def register(
        self,
        api_key: str,
        *,
        now: datetime,
        expires_at: datetime | None = None,
    ) -> str:
        """Insert ``api_key`` as an active credential, or return the existing id.

        Args:
            api_key: Secret to hash and store. Never persisted in plaintext.
            now: Timestamp for ``created_at`` / ``updated_at`` on insert.
            expires_at: Optional expiry. ``None`` means no expiry.

        Returns:
            The ``credential_id`` for this digest.

        Raises:
            InvalidApiKeyError: If ``api_key`` fails validation.
        """

        _validate_api_key(api_key)
        key_digest = digest_api_key(api_key)
        timestamp = now.isoformat()
        expiry = expires_at.isoformat() if expires_at is not None else None
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT credential_id FROM api_credentials WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
            if existing is not None:
                return str(existing["credential_id"])
            credential_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO api_credentials ("
                " credential_id, key_digest, lifecycle_status,"
                " created_at, updated_at, expires_at"
                ") VALUES (?, ?, 'active', ?, ?, ?)",
                (credential_id, key_digest, timestamp, timestamp, expiry),
            )
        return credential_id

    def verify(self, presented_key: str, *, now: datetime) -> str | None:
        """Return the matching active credential id, or ``None``.

        Comparison walks every verifiable digest so a first-match hit is
        not a timing signal. Digests are UTF-8 SHA-256 hex strings, so
        ``hmac.compare_digest`` never sees mixed ``str``/``bytes``.

        Args:
            presented_key: Value of the ``X-API-Key`` header.
            now: Clock used for expiry.

        Returns:
            The matching ``credential_id``, or ``None`` when the header is
            missing, overlong, or does not match an active unexpired key.
        """

        if not presented_key:
            return None
        if len(presented_key.encode("utf-8")) > MAX_KEY_BYTES:
            return None
        presented_digest = digest_api_key(presented_key)
        matched_id: str | None = None
        for record in self.list_records():
            if not self._is_verifiable(record, now):
                continue
            stored_digest = record["key_digest"]
            assert stored_digest is not None
            if self._compare_digests(presented_digest, stored_digest):
                matched_id = record["credential_id"]
        return matched_id

    def has_active_credentials(self, *, now: datetime) -> bool:
        """Return whether any credential is verifiable at ``now``.

        Args:
            now: Caller-supplied clock.

        Returns:
            ``True`` when middleware should require a matching header.
        """

        return any(self._is_verifiable(record, now) for record in self.list_records())

    def get(self, credential_id: str) -> dict[str, str | None] | None:
        """Fetch one plaintext-free record.

        Args:
            credential_id: Registry identifier.

        Returns:
            The record dict, or ``None`` if the id is unknown.
        """

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_credentials WHERE credential_id = ?",
                (credential_id,),
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_records(self) -> list[dict[str, str | None]]:
        """List every credential without plaintext secrets.

        Returns:
            Records ordered by ``created_at`` then ``credential_id``.
        """

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_credentials"
                " ORDER BY created_at, credential_id"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def rotate(self, credential_id: str, next_api_key: str, *, now: datetime) -> str:
        """Retire ``credential_id`` and register ``next_api_key``.

        Args:
            credential_id: Current credential to mark ``rotated``.
            next_api_key: Replacement secret.
            now: Clock for ``rotated_at`` / ``updated_at``.

        Returns:
            The new ``credential_id``.

        Raises:
            CredentialRegistryError: If ``credential_id`` does not exist.
            InvalidApiKeyError: If ``next_api_key`` fails validation.
        """

        if self.get(credential_id) is None:
            raise CredentialRegistryError("credential does not exist")
        new_id = self.register(next_api_key, now=now)
        timestamp = now.isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE api_credentials SET lifecycle_status = 'rotated',"
                " updated_at = ?, rotated_at = ? WHERE credential_id = ?",
                (timestamp, timestamp, credential_id),
            )
        return new_id

    def revoke(self, credential_id: str, *, now: datetime) -> None:
        """Mark ``credential_id`` revoked so it can no longer verify.

        Args:
            credential_id: Credential to revoke.
            now: Clock for ``revoked_at`` / ``updated_at``.

        Raises:
            CredentialRegistryError: If ``credential_id`` does not exist.
        """

        timestamp = now.isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE api_credentials SET lifecycle_status = 'revoked',"
                " updated_at = ?, revoked_at = ? WHERE credential_id = ?",
                (timestamp, timestamp, credential_id),
            )
            if cursor.rowcount == 0:
                raise CredentialRegistryError("credential does not exist")
