"""Regression tests for the runtime credential-registry boundary."""

from __future__ import annotations

import unittest

from credential_registry import (
    CODEC_CARVER_API_KEYS_ENV,
    CODEC_CARVER_API_KEYS_NAME,
    CredentialRegistry,
    bootstrap_codec_carver_api_keys,
)


class CredentialRegistryTests(unittest.TestCase):
    """Prove runtime credentials are decoupled from mutable process environment."""

    def setUp(self) -> None:
        """Create an isolated registry for every test."""

        self.registry = CredentialRegistry()

    def test_set_get_and_delete_credential(self) -> None:
        """A credential can be stored, retrieved, and removed atomically."""

        self.assertIsNone(self.registry.get_credential("service_api_key"))
        self.registry.set_credential("service_api_key", "secret-value")
        self.assertEqual(self.registry.get_credential("service_api_key"), "secret-value")
        self.registry.delete_credential("service_api_key")
        self.assertIsNone(self.registry.get_credential("service_api_key"))

    def test_blank_credential_name_is_rejected(self) -> None:
        """Blank registry names fail closed instead of creating ambiguous entries."""

        with self.assertRaises(ValueError):
            self.registry.set_credential("   ", "secret-value")
        with self.assertRaises(ValueError):
            self.registry.get_credential("")
        with self.assertRaises(ValueError):
            self.registry.delete_credential("\t")

    def test_non_string_credential_value_is_rejected(self) -> None:
        """Registry values must remain immutable strings suitable for secret transport."""

        with self.assertRaises(TypeError):
            self.registry.set_credential("service_api_key", object())  # type: ignore[arg-type]

    def test_bootstrap_copies_api_keys_without_following_environment_mutation(self) -> None:
        """Environment transport is copied once; later mutation cannot change runtime state."""

        environment = {CODEC_CARVER_API_KEYS_ENV: "alpha,beta"}
        bootstrap_codec_carver_api_keys(environment, registry=self.registry)
        environment[CODEC_CARVER_API_KEYS_ENV] = "attacker-replacement"

        self.assertEqual(
            self.registry.get_credential(CODEC_CARVER_API_KEYS_NAME),
            "alpha,beta",
        )

    def test_bootstrap_removes_runtime_value_when_transport_is_absent(self) -> None:
        """An absent bootstrap value clears any previously registered API-key bundle."""

        self.registry.set_credential(CODEC_CARVER_API_KEYS_NAME, "old-key")
        bootstrap_codec_carver_api_keys({}, registry=self.registry)

        self.assertIsNone(self.registry.get_credential(CODEC_CARVER_API_KEYS_NAME))

    def test_bootstrap_preserves_empty_transport_for_open_mode_parsing(self) -> None:
        """An explicit empty bootstrap value remains distinguishable from a missing entry."""

        bootstrap_codec_carver_api_keys(
            {CODEC_CARVER_API_KEYS_ENV: ""},
            registry=self.registry,
        )

        self.assertEqual(self.registry.get_credential(CODEC_CARVER_API_KEYS_NAME), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
