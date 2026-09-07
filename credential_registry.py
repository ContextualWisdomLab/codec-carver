"""Stdlib-only API credential registry for request-time authentication.

Environment variables may populate this store during an explicit bootstrap
step. Request handlers must call :meth:`CredentialRegistry.verify_api_key`
and must not read ``CODEC_CARVER_API_KEYS`` themselves.

Callers pass ``now`` explicitly. The store never calls ``datetime.now()``.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import threading
import unicodedata
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime

#: Allowed credential lifecycle states.
VALID_LIFECYCLE_STATES = frozenset({"active", "rotated", "revoked"})

#: Hard cap on stored credentials so comparison work stays bounded.
MAX_CREDENTIAL_COUNT = 16

#: Maximum UTF-8 size of a plaintext key or ``X-API-Key`` header.
MAX_KEY_BYTES = 256

#: Hosts that count as loopback for the explicit development mode.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

_CREDENTIAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_credentials (
    credential_id TEXT PRIMARY KEY,
    key_digest TEXT NOT NULL UNIQUE,
    lifecycle_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    key_label TEXT NOT NULL
)
"""

_EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS credential_events (
    event_id TEXT PRIMARY KEY,
    credential_id TEXT,
    event_type TEXT NOT NULL,
    event_at TEXT NOT NULL,
    actor_label TEXT NOT NULL,
    FOREIGN KEY (credential_id) REFERENCES api_credentials (credential_id)
)
"""

_POLICY_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_policies (
    policy_name TEXT PRIMARY KEY,
    policy_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_PUBLIC_COLUMNS = (
    "credential_id",
    "lifecycle_state",
    "created_at",
    "updated_at",
    "expires_at",
    "key_label",
)


class CredentialValidationError(ValueError):
    """Raised when bootstrap text cannot become a stored credential."""


class CredentialPolicyError(ValueError):
    """Raised when a listen address violates the credential policy."""


def parse_transport_keys(raw: str) -> list[str]:
    """Split comma-separated bootstrap text into stripped candidate keys.

    Args:
        raw: Transport string, typically the value of
            ``CODEC_CARVER_API_KEYS`` during startup only.

    Returns:
        Non-empty key strings in the order they appeared.
    """

    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def digest_api_key(plaintext: str) -> str:
    """Return the hex SHA-256 digest of ``plaintext`` encoded as UTF-8.

    Args:
        plaintext: Issued API key. Must already be validated.

    Returns:
        64-character lowercase hexadecimal digest.
    """

    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _reject_control_characters(plaintext: str) -> None:
    """Reject Unicode general-category Control and format characters.

    Args:
        plaintext: Candidate key.

    Raises:
        CredentialValidationError: If any character is a control or format
            character. The exception text never includes ``plaintext``.
    """

    for char in plaintext:
        if unicodedata.category(char).startswith("C"):
            raise CredentialValidationError(
                "control characters are not allowed in credentials"
            )


def _validated_digest(plaintext: str) -> str:
    """Validate one plaintext key and return its digest.

    Args:
        plaintext: Candidate key after whitespace strip.

    Returns:
        Hex SHA-256 digest.

    Raises:
        CredentialValidationError: If the key is empty, overlong, or contains
            control characters.
    """

    if not plaintext:
        raise CredentialValidationError("empty credential is not allowed")
    raw = plaintext.encode("utf-8")
    if len(raw) > MAX_KEY_BYTES:
        raise CredentialValidationError(
            "credential exceeds the maximum UTF-8 length"
        )
    _reject_control_characters(plaintext)
    return digest_api_key(plaintext)


class CredentialRegistry:
    """Durable, thread-safe API credential store backed by SQLite WAL.

    Args:
        db_path: Filesystem path of the SQLite database. ``":memory:"`` is
            rejected because each operation opens a fresh connection.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the store and create the 3NF schema if needed.

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
            conn.execute(_CREDENTIAL_SCHEMA)
            conn.execute(_EVENT_SCHEMA)
            conn.execute(_POLICY_SCHEMA)

    def __repr__(self) -> str:
        """Return a redacted summary that never includes key material."""

        return f"CredentialRegistry(db_path={self._db_path!r})"

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
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _record_event(
        self,
        conn: sqlite3.Connection,
        credential_id: str | None,
        event_type: str,
        now: datetime,
        actor_label: str,
    ) -> None:
        """Append one audit row that never stores a plaintext key.

        Args:
            conn: Open connection inside the caller lock.
            credential_id: Affected credential primary key, or ``None``
                for policy-only events.
            event_type: ``imported``, ``rotated``, ``revoked``, or
                ``policy_updated``.
            now: Event timestamp.
            actor_label: Non-secret source such as ``env`` or ``test``.
        """

        conn.execute(
            "INSERT INTO credential_events (event_id, credential_id, "
            "event_type, event_at, actor_label) VALUES (?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                credential_id,
                event_type,
                now.isoformat(),
                actor_label,
            ),
        )

    def import_plaintext_keys(
        self,
        keys: list[str],
        *,
        now: datetime,
        source: str,
        expires_at: datetime | None = None,
    ) -> int:
        """Insert new active credentials from already-split plaintext keys.

        Existing digests are left unchanged so bootstrap is idempotent and
        a revoked key stays revoked.

        Args:
            keys: Plaintext keys. Duplicates in this list are rejected.
            now: Timestamp for ``created_at`` / ``updated_at``.
            source: Non-secret actor label written to ``credential_events``.
            expires_at: Optional expiry applied only to newly inserted rows.

        Returns:
            Count of newly inserted rows.

        Raises:
            CredentialValidationError: If any key is empty, duplicated in
                ``keys``, overlong, contains control characters, or the
                bounded set would exceed :data:`MAX_CREDENTIAL_COUNT`.
        """

        digests: list[str] = []
        seen: set[str] = set()
        for key in keys:
            digest = _validated_digest(key)
            if digest in seen:
                raise CredentialValidationError(
                    "duplicate credential in the import list"
                )
            seen.add(digest)
            digests.append(digest)

        inserted = 0
        expiry = expires_at.isoformat() if expires_at is not None else None
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM api_credentials"
            ).fetchone()[0]
            known = {
                row["key_digest"]
                for row in conn.execute("SELECT key_digest FROM api_credentials")
            }
            new_digests = [digest for digest in digests if digest not in known]
            if existing + len(new_digests) > MAX_CREDENTIAL_COUNT:
                raise CredentialValidationError(
                    f"at most {MAX_CREDENTIAL_COUNT} credentials may be stored"
                )
            for digest in new_digests:
                credential_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO api_credentials (credential_id, key_digest, "
                    "lifecycle_state, created_at, updated_at, expires_at, "
                    "key_label) VALUES (?, ?, 'active', ?, ?, ?, ?)",
                    (
                        credential_id,
                        digest,
                        now.isoformat(),
                        now.isoformat(),
                        expiry,
                        digest[:8],
                    ),
                )
                self._record_event(conn, credential_id, "imported", now, source)
                inserted += 1
        return inserted

    def bootstrap_from_transport(
        self,
        raw: str,
        *,
        now: datetime,
        source: str = "transport",
    ) -> int:
        """Parse bootstrap text and import new keys idempotently.

        Args:
            raw: Comma-separated transport string.
            now: Import timestamp.
            source: Non-secret actor label.

        Returns:
            Count of newly inserted rows.
        """

        return self.import_plaintext_keys(
            parse_transport_keys(raw),
            now=now,
            source=source,
        )

    def rotate(self, current_plaintext: str, next_plaintext: str, *, now: datetime) -> None:
        """Mark ``current_plaintext`` rotated and insert ``next_plaintext``.

        The rotated key remains valid until :meth:`revoke` so in-flight
        clients can finish while operators distribute the next key.

        Args:
            current_plaintext: Key already stored as ``active``.
            next_plaintext: Replacement key to insert as ``active``.
            now: Transition timestamp.

        Raises:
            KeyError: If the current key is not stored.
            CredentialValidationError: If the next key is invalid or already
                stored.
        """

        current_digest = _validated_digest(current_plaintext)
        next_digest = _validated_digest(next_plaintext)
        with self._lock, self._connect() as conn:
            current = conn.execute(
                "SELECT credential_id FROM api_credentials "
                "WHERE key_digest = ?",
                (current_digest,),
            ).fetchone()
            if current is None:
                raise KeyError("current credential is not in the registry")
            existing_next = conn.execute(
                "SELECT credential_id FROM api_credentials "
                "WHERE key_digest = ?",
                (next_digest,),
            ).fetchone()
            if existing_next is not None:
                raise CredentialValidationError(
                    "next credential is already stored"
                )
            total = conn.execute(
                "SELECT COUNT(*) FROM api_credentials"
            ).fetchone()[0]
            if total + 1 > MAX_CREDENTIAL_COUNT:
                raise CredentialValidationError(
                    f"at most {MAX_CREDENTIAL_COUNT} credentials may be stored"
                )
            conn.execute(
                "UPDATE api_credentials SET lifecycle_state = 'rotated', "
                "updated_at = ? WHERE credential_id = ?",
                (now.isoformat(), current["credential_id"]),
            )
            self._record_event(
                conn, current["credential_id"], "rotated", now, "rotate"
            )
            next_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO api_credentials (credential_id, key_digest, "
                "lifecycle_state, created_at, updated_at, expires_at, "
                "key_label) VALUES (?, ?, 'active', ?, ?, NULL, ?)",
                (
                    next_id,
                    next_digest,
                    now.isoformat(),
                    now.isoformat(),
                    next_digest[:8],
                ),
            )
            self._record_event(conn, next_id, "imported", now, "rotate")

    def revoke(self, plaintext: str, *, now: datetime) -> None:
        """Mark a stored key revoked so it no longer verifies.

        Args:
            plaintext: Key to revoke.
            now: Revocation timestamp.

        Raises:
            KeyError: If the key is not stored.
        """

        digest = _validated_digest(plaintext)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT credential_id FROM api_credentials WHERE key_digest = ?",
                (digest,),
            ).fetchone()
            if row is None:
                raise KeyError("credential is not in the registry")
            conn.execute(
                "UPDATE api_credentials SET lifecycle_state = 'revoked', "
                "updated_at = ? WHERE credential_id = ?",
                (now.isoformat(), row["credential_id"]),
            )
            self._record_event(conn, row["credential_id"], "revoked", now, "revoke")

    def _usable_rows(
        self, conn: sqlite3.Connection, now: datetime
    ) -> list[sqlite3.Row]:
        """Return active or rotated rows that have not expired at ``now``.

        Args:
            conn: Open connection.
            now: Comparison timestamp.

        Returns:
            Rows with ``credential_id`` and ``key_digest``.
        """

        rows = conn.execute(
            "SELECT credential_id, key_digest, expires_at FROM api_credentials "
            "WHERE lifecycle_state IN ('active', 'rotated')"
        ).fetchall()
        now_text = now.isoformat()
        usable: list[sqlite3.Row] = []
        for row in rows:
            expires_at = row["expires_at"]
            if expires_at is not None and expires_at <= now_text:
                continue
            usable.append(row)
        return usable

    def _usable_digests(self, conn: sqlite3.Connection, now: datetime) -> list[str]:
        """Return digests that may still authenticate at ``now``.

        Args:
            conn: Open connection.
            now: Comparison timestamp.

        Returns:
            Digests for ``active`` and ``rotated`` rows that have not expired.
        """

        return [row["key_digest"] for row in self._usable_rows(conn, now)]

    def verify_api_key(self, provided: object, *, now: datetime) -> str | None:
        """Return the matching ``credential_id``, or ``None``.

        Comparison always visits every usable digest. Hostile or overlong
        headers return ``None`` instead of raising. The identifier is the
        stable handle usage metering should store instead of plaintext.

        Args:
            provided: ``X-API-Key`` value. Non-strings are rejected.
            now: Comparison timestamp used for expiry.

        Returns:
            The matching credential primary key, or ``None``.
        """

        if not isinstance(provided, str):
            return None
        raw = provided.encode("utf-8")
        if not raw or len(raw) > MAX_KEY_BYTES:
            return None
        try:
            _reject_control_characters(provided)
        except CredentialValidationError:
            return None
        provided_digest = digest_api_key(provided)
        with self._lock, self._connect() as conn:
            rows = self._usable_rows(conn, now)
        matched_id: str | None = None
        for row in rows:
            if hmac.compare_digest(provided_digest, row["key_digest"]):
                matched_id = row["credential_id"]
        return matched_id

    def has_active_credentials(self, *, now: datetime) -> bool:
        """Return True when at least one usable credential exists.

        Args:
            now: Comparison timestamp used for expiry.

        Returns:
            True if verify could succeed for some issued key.
        """

        with self._lock, self._connect() as conn:
            return bool(self._usable_digests(conn, now))

    def list_public_records(self) -> list[dict[str, str | None]]:
        """Return non-secret credential rows for operators.

        Returns:
            Dicts with ``credential_id``, lifecycle, timestamps, and
            ``key_label``. Digests and plaintext are omitted.
        """

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT credential_id, lifecycle_state, created_at, "
                "updated_at, expires_at, key_label FROM api_credentials "
                "ORDER BY created_at, credential_id"
            ).fetchall()
        return [{key: row[key] for key in _PUBLIC_COLUMNS} for row in rows]

    def audit_events(self) -> list[dict[str, str]]:
        """Return audit rows that never contain credential values.

        Returns:
            Event dicts ordered by ``event_at`` then ``event_id``.
        """

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id, credential_id, event_type, event_at, "
                "actor_label FROM credential_events "
                "ORDER BY event_at, event_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_loopback_development(self, enabled: bool, *, now: datetime) -> None:
        """Record the explicit loopback-only development policy.

        Args:
            enabled: True to allow an empty registry on loopback binds.
            now: Policy timestamp.
        """

        value = "1" if enabled else "0"
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_policies (policy_name, policy_value, "
                "updated_at) VALUES ('loopback_development', ?, ?) "
                "ON CONFLICT(policy_name) DO UPDATE SET "
                "policy_value = excluded.policy_value, "
                "updated_at = excluded.updated_at",
                (value, now.isoformat()),
            )
            self._record_event(
                conn,
                None,
                "policy_updated",
                now,
                "loopback_development",
            )

    def loopback_development_enabled(self) -> bool:
        """Return True when loopback development mode is stored as enabled.

        Returns:
            False when the policy row is missing or set to ``0``.
        """

        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT policy_value FROM runtime_policies "
                "WHERE policy_name = 'loopback_development'"
            ).fetchone()
        return bool(row) and row["policy_value"] == "1"

    def ensure_listen_policy(self, host: str, *, now: datetime) -> None:
        """Refuse a non-loopback bind when no usable credentials exist.

        Args:
            host: Intended bind address (``0.0.0.0``, ``127.0.0.1``, …).
            now: Timestamp used to decide whether credentials are usable.

        Raises:
            CredentialPolicyError: If the bind is public and the registry
                has no usable key, or loopback development is off.
        """

        if self.has_active_credentials(now=now):
            return
        normalized = (host or "").strip().lower()
        if self.loopback_development_enabled() and normalized in LOOPBACK_HOSTS:
            return
        raise CredentialPolicyError(
            "this bind requires configured API credentials; "
            "import keys or enable loopback development on 127.0.0.1"
        )


def bootstrap_registry_from_mapping(
    transport: Mapping[str, str],
    *,
    now: datetime,
    db_path: str,
) -> CredentialRegistry:
    """Create a registry and import keys from a bootstrap mapping.

    Args:
        transport: Mapping that may contain ``CODEC_CARVER_API_KEYS`` and
            ``CODEC_CARVER_LOOPBACK_DEV``. This is the only approved env
            read surface; pass ``os.environ`` from a named startup hook.
        now: Bootstrap timestamp.
        db_path: SQLite file for the registry.

    Returns:
        The populated :class:`CredentialRegistry`.
    """

    registry = CredentialRegistry(db_path)
    registry.bootstrap_from_transport(
        transport.get("CODEC_CARVER_API_KEYS", ""),
        now=now,
        source="transport",
    )
    if transport.get("CODEC_CARVER_LOOPBACK_DEV") == "1":
        registry.set_loopback_development(True, now=now)
    bind_host = transport.get("CODEC_CARVER_BIND_HOST")
    if bind_host:
        registry.ensure_listen_policy(bind_host, now=now)
    return registry
