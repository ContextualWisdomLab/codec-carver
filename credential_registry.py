"""Process-local runtime credential registry for Codec Carver services.

Runtime request handlers must not consult mutable process environment variables
for credentials.  Deployment systems may still use environment variables as a
bootstrap transport, but the values are copied into this registry before request
handling begins.  Subsequent credential reads come only from the registry.

The registry deliberately keeps values in memory rather than persisting plaintext
credentials to the repository's SQLite job database.  A future external secret
manager can populate the same registry interface without changing callers.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

CODEC_CARVER_API_KEYS_ENV = "CODEC_CARVER_API_KEYS"
CODEC_CARVER_API_KEYS_NAME = "codec_carver_api_keys"


class CredentialRegistry:
    """Store runtime credentials behind a small thread-safe key/value boundary.

    Credential names must be non-empty after whitespace trimming. Values are
    copied as immutable strings, so callers never receive a mutable reference to
    registry state. Deleting an unknown name is intentionally idempotent to make
    bootstrap and rotation cleanup safe.
    """

    def __init__(self) -> None:
        """Create an empty credential registry protected by a re-entrant lock."""

        self._credential_values: dict[str, str] = {}
        self._credential_lock = threading.RLock()

    @staticmethod
    def _validated_name(name: str) -> str:
        """Return a normalized credential name or raise for an ambiguous name."""

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("credential name must not be blank")
        return normalized_name

    def set_credential(self, name: str, value: str) -> None:
        """Store ``value`` under ``name`` for subsequent runtime reads.

        Args:
            name: Stable application-level credential identifier.
            value: Credential material. Empty strings are preserved because an
                explicit empty bootstrap value differs from an absent transport.

        Raises:
            ValueError: If ``name`` is blank.
            TypeError: If ``value`` is not a string.
        """

        credential_name = self._validated_name(name)
        if not isinstance(value, str):
            raise TypeError("credential value must be a string")
        with self._credential_lock:
            self._credential_values[credential_name] = value

    def get_credential(self, name: str) -> str | None:
        """Return the credential stored under ``name``, or ``None`` when absent."""

        credential_name = self._validated_name(name)
        with self._credential_lock:
            return self._credential_values.get(credential_name)

    def delete_credential(self, name: str) -> None:
        """Remove ``name`` from the registry if present."""

        credential_name = self._validated_name(name)
        with self._credential_lock:
            self._credential_values.pop(credential_name, None)


CREDENTIAL_REGISTRY = CredentialRegistry()


def bootstrap_codec_carver_api_keys(
    environment: Mapping[str, str],
    *,
    registry: CredentialRegistry = CREDENTIAL_REGISTRY,
) -> None:
    """Copy API-key bootstrap transport into ``registry`` exactly when invoked.

    The function receives the environment mapping as an argument instead of
    reading :mod:`os` itself. This keeps the environment boundary explicit and
    testable. Request handlers do not call this function; the service bootstrap
    invokes it before serving requests. When the transport variable is absent,
    any prior registry entry is removed so a deliberate open-mode deployment can
    be represented without retaining stale credential material.

    Args:
        environment: Bootstrap key/value mapping, normally ``os.environ``.
        registry: Destination registry. The process-wide registry is the default;
            tests may inject an isolated instance.
    """

    if CODEC_CARVER_API_KEYS_ENV not in environment:
        registry.delete_credential(CODEC_CARVER_API_KEYS_NAME)
        return
    registry.set_credential(
        CODEC_CARVER_API_KEYS_NAME,
        environment[CODEC_CARVER_API_KEYS_ENV],
    )
