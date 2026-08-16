"""Contract tests for the stdlib API credential registry."""

from __future__ import annotations

import hmac
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from credential_registry import (
    MAX_CREDENTIAL_COUNT,
    MAX_KEY_BYTES,
    CredentialPolicyError,
    CredentialRegistry,
    CredentialValidationError,
    bootstrap_registry_from_mapping,
    digest_api_key,
    parse_transport_keys,
)

T0 = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(days=30)


class CredentialRegistryTestCase(unittest.TestCase):
    """Fresh SQLite registry on a temporary file."""

    def setUp(self) -> None:
        """Create an isolated registry file for each test."""

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = os.path.join(self._tmp.name, "api_credentials.db")
        self.registry = CredentialRegistry(self.db_path)


class TestParseTransportKeys(unittest.TestCase):
    """Transport text is comma-separated and never read on the request path."""

    def test_strips_whitespace_and_drops_empty_entries(self) -> None:
        """Buyers can paste `key-a, key-b` and both keys import."""

        self.assertEqual(parse_transport_keys("  key-a , , key-b  "), ["key-a", "key-b"])

    def test_blank_transport_is_empty(self) -> None:
        """Unset or whitespace-only transport leaves the registry empty."""

        self.assertEqual(parse_transport_keys(""), [])
        self.assertEqual(parse_transport_keys(" , ,"), [])


class TestImportAndVerify(CredentialRegistryTestCase):
    """Import stores digests; verify compares UTF-8 SHA-256 without plaintext."""

    def test_imported_key_verifies_and_wrong_key_does_not(self) -> None:
        """A meeting-upload client with the issued key is accepted; a guess is not."""

        self.registry.import_plaintext_keys(["meeting-upload-key"], now=T0, source="test")
        self.assertTrue(self.registry.verify_api_key("meeting-upload-key", now=T0))
        self.assertFalse(self.registry.verify_api_key("guessed-key", now=T0))
        self.assertFalse(self.registry.verify_api_key("", now=T0))

    def test_non_ascii_key_round_trips(self) -> None:
        """UTF-8 keys used by non-English operators verify on the same code path."""

        key = "업로드-키-αβγ"
        self.registry.import_plaintext_keys([key], now=T0, source="test")
        self.assertTrue(self.registry.verify_api_key(key, now=T0))
        self.assertFalse(self.registry.verify_api_key("업로드-키-αβγ\u0000", now=T0))

    def test_hostile_header_types_and_overlong_values_are_false(self) -> None:
        """A hostile X-API-Key must 401, never raise into the web worker."""

        self.registry.import_plaintext_keys(["stable-key"], now=T0, source="test")
        self.assertFalse(self.registry.verify_api_key(None, now=T0))
        self.assertFalse(self.registry.verify_api_key(b"stable-key", now=T0))
        self.assertFalse(self.registry.verify_api_key("x" * (MAX_KEY_BYTES + 1), now=T0))

    def test_verify_compares_every_active_digest(self) -> None:
        """No first-match short-circuit: every stored digest is visited."""

        keys = ["alpha-key", "bravo-key", "charlie-key"]
        self.registry.import_plaintext_keys(keys, now=T0, source="test")
        calls: list[tuple[str, str]] = []
        real = hmac.compare_digest

        def counting_compare(left: str, right: str) -> bool:
            """Count compare_digest visits while preserving real comparison."""

            calls.append((left, right))
            return real(left, right)

        with patch("credential_registry.hmac.compare_digest", side_effect=counting_compare):
            self.assertTrue(self.registry.verify_api_key("alpha-key", now=T0))

        self.assertEqual(len(calls), 3)

    def test_public_records_and_repr_omit_plaintext(self) -> None:
        """Listings, repr, and audit rows must not echo the issued secret."""

        secret = "SUPER-SECRET-KEY-VALUE"
        self.registry.import_plaintext_keys([secret], now=T0, source="bootstrap")
        public = self.registry.list_public_records()
        blob = repr(self.registry) + str(public) + str(self.registry.audit_events())
        self.assertNotIn(secret, blob)
        self.assertEqual(len(public), 1)
        self.assertEqual(public[0]["lifecycle_state"], "active")
        self.assertNotIn("key_digest", public[0])
        self.assertTrue(self.registry.has_active_credentials(now=T0))

    def test_bootstrap_is_idempotent(self) -> None:
        """Re-running the env transport import does not duplicate or revive revoked keys."""

        raw = "keep-key,drop-later"
        first = self.registry.bootstrap_from_transport(raw, now=T0, source="env")
        second = self.registry.bootstrap_from_transport(raw, now=T1, source="env")
        self.assertEqual(first, 2)
        self.assertEqual(second, 0)
        self.registry.revoke("drop-later", now=T1)
        third = self.registry.bootstrap_from_transport(raw, now=T2, source="env")
        self.assertEqual(third, 0)
        self.assertFalse(self.registry.verify_api_key("drop-later", now=T2))
        self.assertTrue(self.registry.verify_api_key("keep-key", now=T2))


class TestValidation(CredentialRegistryTestCase):
    """Bootstrap rejects empty, duplicate, overlong, over-count, and control keys."""

    def test_empty_and_control_and_overlong_rejected_without_echo(self) -> None:
        """Operators get an actionable error that does not repeat the secret."""

        secret = "bad\x00key-material"
        with self.assertRaises(CredentialValidationError) as empty:
            self.registry.import_plaintext_keys([""], now=T0, source="test")
        with self.assertRaises(CredentialValidationError) as control:
            self.registry.import_plaintext_keys([secret], now=T0, source="test")
        with self.assertRaises(CredentialValidationError) as huge:
            self.registry.import_plaintext_keys(["k" * (MAX_KEY_BYTES + 1)], now=T0, source="test")
        self.assertNotIn(secret, str(control.exception))
        self.assertIn("empty", str(empty.exception))
        self.assertIn("control", str(control.exception))
        self.assertIn("maximum", str(huge.exception))

    def test_duplicates_and_over_count_rejected(self) -> None:
        """A pasted list cannot silently collapse or exceed the bounded set."""

        with self.assertRaises(CredentialValidationError) as dup:
            self.registry.import_plaintext_keys(["same-key", "same-key"], now=T0, source="test")
        self.assertNotIn("same-key", str(dup.exception))
        too_many = [f"issued-key-{index:02d}" for index in range(MAX_CREDENTIAL_COUNT + 1)]
        with self.assertRaises(CredentialValidationError) as count:
            self.registry.import_plaintext_keys(too_many, now=T0, source="test")
        self.assertIn("at most", str(count.exception))


class TestRotationExpiryAndRevoke(CredentialRegistryTestCase):
    """Zero-downtime rotation keeps current+next valid until revoke or expiry."""

    def test_rotated_key_still_verifies_until_revoked(self) -> None:
        """Cut over to the next key without dropping in-flight clients."""

        self.registry.import_plaintext_keys(["current-key"], now=T0, source="test")
        self.registry.rotate("current-key", "next-key", now=T1)
        self.assertTrue(self.registry.verify_api_key("current-key", now=T1))
        self.assertTrue(self.registry.verify_api_key("next-key", now=T1))
        states = {row["lifecycle_state"] for row in self.registry.list_public_records()}
        self.assertEqual(states, {"rotated", "active"})
        self.registry.revoke("current-key", now=T2)
        self.assertFalse(self.registry.verify_api_key("current-key", now=T2))
        self.assertTrue(self.registry.verify_api_key("next-key", now=T2))

    def test_expired_key_does_not_verify(self) -> None:
        """A time-bounded contractor key stops working after expires_at."""

        self.registry.import_plaintext_keys(
            ["contractor-key"],
            now=T0,
            source="test",
            expires_at=T1,
        )
        self.assertTrue(self.registry.verify_api_key("contractor-key", now=T0))
        self.assertFalse(self.registry.verify_api_key("contractor-key", now=T2))
        self.assertFalse(self.registry.has_active_credentials(now=T2))


class TestListenPolicy(CredentialRegistryTestCase):
    """Non-loopback binds fail closed unless credentials exist."""

    def test_public_bind_without_keys_fails_closed(self) -> None:
        """Do not publish 0.0.0.0 until an operator imported keys."""

        with self.assertRaises(CredentialPolicyError) as ctx:
            self.registry.ensure_listen_policy("0.0.0.0", now=T0)
        self.assertIn("credentials", str(ctx.exception))

    def test_loopback_development_allows_empty_registry(self) -> None:
        """Local `127.0.0.1` work is explicit, not an accidental open bind."""

        self.registry.set_loopback_development(True, now=T0)
        self.registry.ensure_listen_policy("127.0.0.1", now=T0)
        with self.assertRaises(CredentialPolicyError):
            self.registry.ensure_listen_policy("0.0.0.0", now=T0)

    def test_public_bind_succeeds_after_import(self) -> None:
        """Once keys exist, the SaaS UI may listen on all interfaces."""

        self.registry.import_plaintext_keys(["prod-key"], now=T0, source="test")
        self.registry.ensure_listen_policy("0.0.0.0", now=T0)


class TestConcurrencyAndStorageRules(CredentialRegistryTestCase):
    """Readers stay consistent; table names stay two-word snake_case."""

    def test_concurrent_verifies_during_rotate(self) -> None:
        """In-flight uploads keep working while the next key is inserted."""

        self.registry.import_plaintext_keys(["live-key"], now=T0, source="test")
        errors: list[str] = []

        def hammer() -> None:
            """Verify the live key from a worker thread."""

            for _ in range(40):
                if not self.registry.verify_api_key("live-key", now=T0):
                    errors.append("live-key rejected")

        workers = [threading.Thread(target=hammer) for _ in range(4)]
        for worker in workers:
            worker.start()
        self.registry.rotate("live-key", "next-live-key", now=T1)
        for worker in workers:
            worker.join()
        self.assertEqual(errors, [])
        self.assertTrue(self.registry.verify_api_key("next-live-key", now=T1))

    def test_schema_uses_two_word_tables_and_rejects_memory(self) -> None:
        """Org naming: api_credentials / credential_events / runtime_policies."""

        with self.registry._connect() as conn:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("api_credentials", names)
        self.assertIn("credential_events", names)
        self.assertIn("runtime_policies", names)
        self.assertTrue(all("_" in name or name.startswith("sqlite_") for name in names))
        with self.assertRaises(ValueError):
            CredentialRegistry(":memory:")

    def test_digest_is_hex_sha256_of_utf8(self) -> None:
        """Verification material is a 64-character SHA-256 hex digest."""

        digest = digest_api_key("meeting-upload-key")
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in digest))

    def test_rotate_and_revoke_unknown_keys_raise(self) -> None:
        """Operators get a KeyError they can act on, not a stack of key text."""

        self.registry.import_plaintext_keys(["known-key"], now=T0, source="test")
        with self.assertRaises(KeyError):
            self.registry.rotate("missing-key", "next-key", now=T1)
        with self.assertRaises(KeyError):
            self.registry.revoke("missing-key", now=T1)
        with self.assertRaises(CredentialValidationError):
            self.registry.rotate("known-key", "known-key", now=T1)

    def test_bootstrap_mapping_applies_loopback_and_bind_policy(self) -> None:
        """Startup transport can enable loopback mode and check the bind host."""

        empty_path = os.path.join(self._tmp.name, "empty.db")
        empty = bootstrap_registry_from_mapping(
            {"CODEC_CARVER_LOOPBACK_DEV": "1"},
            now=T0,
            db_path=empty_path,
        )
        self.assertTrue(empty.loopback_development_enabled())
        empty.ensure_listen_policy("127.0.0.1", now=T0)
        populated = bootstrap_registry_from_mapping(
            {
                "CODEC_CARVER_API_KEYS": "prod-key",
                "CODEC_CARVER_BIND_HOST": "0.0.0.0",
            },
            now=T0,
            db_path=self.db_path,
        )
        self.assertTrue(populated.verify_api_key("prod-key", now=T0))
        full = [f"issued-key-{index:02d}" for index in range(MAX_CREDENTIAL_COUNT)]
        capped_path = os.path.join(self._tmp.name, "capped.db")
        capped = CredentialRegistry(capped_path)
        capped.import_plaintext_keys(full, now=T0, source="test")
        with self.assertRaises(CredentialValidationError):
            capped.rotate(full[0], "overflow-next-key", now=T1)
        capped.set_loopback_development(False, now=T1)
        self.assertFalse(capped.loopback_development_enabled())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
