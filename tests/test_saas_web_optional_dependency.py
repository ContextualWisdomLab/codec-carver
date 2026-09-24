"""Regression tests for optional web-dependency import classification."""

from __future__ import annotations

import builtins
import importlib.util
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


_TEST_MODULE = Path(__file__).with_name("test_saas_web.py")
_MISSING_MULTIPART = (
    'Form data requires "python-multipart" to be installed. '
    'You can install "python-multipart" with: pip install python-multipart'
)


def _run_test_module_with_import_failure(module_name: str, exc: Exception) -> dict:
    """Execute the web test module while one import raises ``exc``."""
    original_import = builtins.__import__

    def controlled_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == module_name or name.startswith(f"{module_name}."):
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=controlled_import):
        return runpy.run_path(str(_TEST_MODULE))


class TestOptionalWebDependencyImport(unittest.TestCase):
    """Keep optional dependency skips narrow and fail closed on real faults."""

    @unittest.skipUnless(
        importlib.util.find_spec("fastapi") is not None,
        "fastapi is required to exercise the multipart initialization boundary",
    )
    def test_missing_python_multipart_runtime_error_is_optional(self):
        namespace = _run_test_module_with_import_failure(
            "saas_web", RuntimeError(_MISSING_MULTIPART)
        )

        self.assertFalse(namespace["_HAS_FASTAPI"])

    def test_absent_fastapi_remains_optional(self):
        namespace = _run_test_module_with_import_failure(
            "fastapi", ImportError("No module named 'fastapi'")
        )

        self.assertFalse(namespace["_HAS_FASTAPI"])

    @unittest.skipUnless(
        importlib.util.find_spec("fastapi") is not None,
        "fastapi is required to exercise the web initialization boundary",
    )
    def test_unrelated_runtime_error_is_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, "database bootstrap failed"):
            _run_test_module_with_import_failure(
                "saas_web", RuntimeError("database bootstrap failed")
            )

    @unittest.skipUnless(
        importlib.util.find_spec("fastapi") is not None,
        "fastapi is required to exercise the web initialization boundary",
    )
    def test_corrupted_multipart_message_is_not_hidden(self):
        with self.assertRaisesRegex(RuntimeError, "multipart parser exploded"):
            _run_test_module_with_import_failure(
                "saas_web", RuntimeError("multipart parser exploded")
            )


if __name__ == "__main__":
    unittest.main()
