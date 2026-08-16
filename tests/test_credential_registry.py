"""Tests for the SQLite API credential registry.

These cases follow the buyer-facing contract in issues #329 and #373:
bootstrap may read a transport environment mapping once; request-time
verification reads only hashed material from ``api_credentials``.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from credential_registry import (
    BOOTSTRAP_ENV_NAME,
    CredentialRegistry,
    CredentialRegistryError,
    InvalidApiKeyError,
    bootstrap_from_mapping,
    digest_api_key,
    parse_bootstrap_api_keys,
)

T0 = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(days=1)


class CredentialRegistryTestCase(unittest.TestCase):
    """Base fixture: a fresh registry on a temporary SQLite file."""

    def setUp(self) -> None:
        """Create an isolated registry file for each test."""

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "api_credentials.db")
        self.store = CredentialRegistry(self.db_path)


class TestParseBootstrapApiKeys(unittest.TestCase):
    """The comma-separated transport string is parsed without reading os.environ."""

    def test_strips_whitespace_and_drops_empty_entries(self) -> None:
        """Operators can paste `` a ,, b ,`` and still get two keys."""

        self.assertEqual(parse_bootstrap_api_keys(" a ,, b ,"), ["a", "b"])

    def test_empty_or_whitespace_only_is_no_keys(self) -> None:
        """An unset-equivalent transport string must not invent credentials."""

        self.assertEqual(parse_bootstrap_api_keys(""), [])
        self.assertEqual(parse_bootstrap_api_keys(" , ,"), [])

    def test_rejects_control_characters(self) -> None:
        """A key with a newline or NUL is a configuration error, not a secret."""

        with self.assertRaises(InvalidApiKeyError):
            parse_bootstrap_api_keys("good-key,bad\nkey")
        with self.assertRaises(InvalidApiKeyError):
            parse_bootstrap_api_keys("bad\x00key")

    def test_rejects_duplicates(self) -> None:
        """Duplicate bootstrap keys are a rotation mistake, not two identities."""

        with self.assertRaises(InvalidApiKeyError):
            parse_bootstrap_api_keys("alpha,alpha")

    def test_rejects_overlong_key(self) -> None:
        """Oversized keys are rejected before they reach the digest column."""

        with self.assertRaises(InvalidApiKeyError):
            parse_bootstrap_api_keys("k" * 257)

    def test_rejects_too_many_keys(self) -> None:
        """A bounded set keeps comparison work predictable."""

        payload = ",".join(f"key-{i:02d}" for i in range(33))
        with self.assertRaises(InvalidApiKeyError):
            parse_bootstrap_api_keys(payload)


class TestRegisterAndVerify(CredentialRegistryTestCase):
    """Register stores a digest; verify compares UTF-8 digests across the set."""

    def test_register_verify_roundtrip(self) -> None:
        """A freshly registered key authenticates and returns a stable id."""

        credential_id = self.store.register("secret-key", now=T0)
        self.assertEqual(self.store.verify("secret-key", now=T0), credential_id)
        record = self.store.get(credential_id)
        assert record is not None
        self.assertEqual(record["lifecycle_status"], "active")
        self.assertEqual(record["key_digest"], digest_api_key("secret-key"))
        self.assertNotIn("secret-key", record.values())

    def test_wrong_key_returns_none(self) -> None:
        """A non-matching header follows the same 401 path as a missing header."""

        self.store.register("secret-key", now=T0)
        self.assertIsNone(self.store.verify("wrong-key", now=T0))
        self.assertIsNone(self.store.verify("", now=T0))

    def test_non_ascii_key_roundtrip(self) -> None:
        """UTF-8 keys must verify; hostile Unicode must not raise TypeError."""

        key = "키-α-🔑"
        credential_id = self.store.register(key, now=T0)
        self.assertEqual(self.store.verify(key, now=T0), credential_id)
        self.assertIsNone(self.store.verify("키-α-🔑x", now=T0))

    def test_verify_does_not_short_circuit(self) -> None:
        """Every active digest is compared so first-match timing is not a signal."""

        first = self.store.register("key-one", now=T0)
        self.store.register("key-two", now=T0)
        compared: list[str] = []
        original = self.store._compare_digests

        def tracking(left: str, right: str) -> bool:
            compared.append(right)
            return original(left, right)

        self.store._compare_digests = tracking  # type: ignore[method-assign]
        self.assertEqual(self.store.verify("key-one", now=T0), first)
        self.assertEqual(len(compared), 2)

    def test_overlong_presented_key_is_rejected_without_lookup(self) -> None:
        """A huge X-API-Key is a 401, not a digest DoS against the registry."""

        self.store.register("secret-key", now=T0)
        self.assertIsNone(self.store.verify("k" * 257, now=T0))

    def test_list_records_never_includes_plaintext(self) -> None:
        """Admin listings expose identifiers and lifecycle, never the secret."""

        self.store.register("secret-key", now=T0)
        listing = self.store.list_records()
        self.assertEqual(len(listing), 1)
        blob = repr(listing) + str(listing)
        self.assertNotIn("secret-key", blob)
        self.assertIn("key_digest", listing[0])
        self.assertIn("credential_id", listing[0])

    def test_repr_hides_secrets(self) -> None:
        """``repr`` of the registry must not echo a registered key."""

        self.store.register("secret-key", now=T0)
        self.assertNotIn("secret-key", repr(self.store))
        self.assertNotIn("secret-key", str(self.store))

    def test_duplicate_register_is_idempotent(self) -> None:
        """Re-importing the same key during bootstrap does not create a second row."""

        first = self.store.register("secret-key", now=T0)
        second = self.store.register("secret-key", now=T1)
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_records()), 1)

    def test_memory_path_rejected(self) -> None:
        """Short-lived connections cannot share an in-memory SQLite database."""

        with self.assertRaises(ValueError):
            CredentialRegistry(":memory:")

    def test_register_rejects_empty_key(self) -> None:
        """An empty secret is a configuration error, not an open credential."""

        with self.assertRaises(InvalidApiKeyError):
            self.store.register("", now=T0)


class TestLifecycle(CredentialRegistryTestCase):
    """Rotated, revoked, and expired credentials must not authenticate."""

    def test_rotated_key_no_longer_verifies(self) -> None:
        """After rotation the previous secret is retired and the next one works."""

        old_id = self.store.register("old-key", now=T0)
        new_id = self.store.rotate(old_id, "new-key", now=T1)
        self.assertNotEqual(old_id, new_id)
        self.assertIsNone(self.store.verify("old-key", now=T1))
        self.assertEqual(self.store.verify("new-key", now=T1), new_id)
        self.assertEqual(self.store.get(old_id)["lifecycle_status"], "rotated")

    def test_revoked_key_no_longer_verifies(self) -> None:
        """Revocation is immediate at the supplied clock."""

        credential_id = self.store.register("secret-key", now=T0)
        self.store.revoke(credential_id, now=T1)
        self.assertIsNone(self.store.verify("secret-key", now=T1))
        self.assertEqual(self.store.get(credential_id)["lifecycle_status"], "revoked")

    def test_expired_key_no_longer_verifies(self) -> None:
        """Expiry is evaluated from the caller-supplied clock, not wall time."""

        credential_id = self.store.register("secret-key", now=T0, expires_at=T1)
        self.assertEqual(self.store.verify("secret-key", now=T0), credential_id)
        self.assertIsNone(self.store.verify("secret-key", now=T2))

    def test_has_active_credentials_respects_expiry(self) -> None:
        """Middleware fail-open only when no verifiable credential remains."""

        self.assertFalse(self.store.has_active_credentials(now=T0))
        self.store.register("secret-key", now=T0, expires_at=T1)
        self.assertTrue(self.store.has_active_credentials(now=T0))
        self.assertFalse(self.store.has_active_credentials(now=T2))

    def test_rotate_unknown_id_raises(self) -> None:
        """Rotation of a missing id is an operator error."""

        with self.assertRaises(CredentialRegistryError):
            self.store.rotate("missing", "new-key", now=T1)

    def test_revoke_unknown_id_raises(self) -> None:
        """Revocation of a missing id is an operator error."""

        with self.assertRaises(CredentialRegistryError):
            self.store.revoke("missing", now=T1)


class TestBootstrapFromMapping(CredentialRegistryTestCase):
    """Env is transport into the registry; the mapping is passed explicitly."""

    def test_bootstrap_imports_keys_and_is_idempotent(self) -> None:
        """A second bootstrap with the same transport does not duplicate rows."""

        mapping = {BOOTSTRAP_ENV_NAME: "key-one,key-two"}
        first = bootstrap_from_mapping(self.store, mapping, now=T0)
        second = bootstrap_from_mapping(self.store, mapping, now=T1)
        self.assertEqual(sorted(first), sorted(second))
        self.assertEqual(len(self.store.list_records()), 2)
        self.assertEqual(self.store.verify("key-one", now=T1), first["key-one"])
        self.assertEqual(self.store.verify("key-two", now=T1), first["key-two"])

    def test_bootstrap_ignores_other_environ_keys(self) -> None:
        """Only the named transport variable is read from the mapping."""

        bootstrap_from_mapping(
            self.store,
            {"OTHER": "not-a-key", BOOTSTRAP_ENV_NAME: "only-this"},
            now=T0,
        )
        self.assertIsNone(self.store.verify("not-a-key", now=T0))
        self.assertIsNotNone(self.store.verify("only-this", now=T0))

    def test_bootstrap_does_not_read_process_environment(self) -> None:
        """A process-level secret must not leak into the registry unless mapped."""

        previous = os.environ.get(BOOTSTRAP_ENV_NAME)
        os.environ[BOOTSTRAP_ENV_NAME] = "process-secret"
        try:
            bootstrap_from_mapping(self.store, {}, now=T0)
            self.assertIsNone(self.store.verify("process-secret", now=T0))
            self.assertFalse(self.store.has_active_credentials(now=T0))
        finally:
            if previous is None:
                os.environ.pop(BOOTSTRAP_ENV_NAME, None)
            else:
                os.environ[BOOTSTRAP_ENV_NAME] = previous

    def test_empty_mapping_leaves_registry_open(self) -> None:
        """Local default remains fail-open until an operator bootstraps keys."""

        bootstrap_from_mapping(self.store, {}, now=T0)
        self.assertFalse(self.store.has_active_credentials(now=T0))


class TestConcurrency(CredentialRegistryTestCase):
    """Concurrent verifies during register must not raise or drop a valid key."""

    def test_concurrent_verify_during_register(self) -> None:
        """Readers keep working while another thread inserts a digest."""

        self.store.register("seed-key", now=T0)
        errors: list[BaseException] = []

        def reader() -> None:
            try:
                for _ in range(40):
                    self.store.verify("seed-key", now=T0)
                    self.store.verify("missing", now=T0)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for thread in threads:
            thread.start()
        self.store.register("late-key", now=T1)
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertIsNotNone(self.store.verify("late-key", now=T1))


class TestExceptionsDoNotLeakSecrets(CredentialRegistryTestCase):
    """Logs, exceptions, and reprs must stay free of presented key material."""

    def test_invalid_key_error_does_not_echo_secret(self) -> None:
        """Validation errors name the rule, not the rejected secret."""

        secret = "leak-me-please\x01"
        with self.assertRaises(InvalidApiKeyError) as caught:
            parse_bootstrap_api_keys(secret)
        self.assertNotIn("leak-me-please", str(caught.exception))
        self.assertNotIn("leak-me-please", repr(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
