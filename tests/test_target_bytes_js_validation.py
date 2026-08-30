"""JavaScript behavior regression tests for target-size validation."""

import json
import shutil
import subprocess
import unittest

try:
    from fastapi.testclient import TestClient

    from saas_web import app

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

_HAS_NODE = shutil.which("node") is not None


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class TargetBytesJavascriptValidationTests(unittest.TestCase):
    """Keep both target-size fields on complete JavaScript numeric semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    @staticmethod
    def _javascript_number(raw_value: str) -> float | None:
        """Evaluate the exact ``Number(input.value)`` parser used by the UI."""

        node = shutil.which("node")
        if node is None:  # Defensive guard for direct helper calls.
            raise unittest.SkipTest("Node.js is unavailable")
        script = (
            f"const input = {{value: {json.dumps(raw_value)}}}; "
            "const val = Number(input.value); "
            "process.stdout.write(Number.isNaN(val) ? 'null' : JSON.stringify(val));"
        )
        result = subprocess.run(
            [node, "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def test_both_target_handlers_use_complete_numeric_value(self) -> None:
        """Both single and batch handlers must avoid integer-prefix truncation."""

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertEqual(html.count("const val = Number(this.value);"), 2)
        self.assertNotIn("const val = parseInt(this.value, 10);", html)

    @unittest.skipUnless(_HAS_NODE, "Node.js unavailable; UI parser contract still runs")
    def test_fractional_value_over_limit_is_not_truncated(self) -> None:
        """A fractional value just above 5 GiB remains above the limit."""

        value = self._javascript_number("5368709120.5")
        self.assertEqual(value, 5368709120.5)
        self.assertGreater(value, 5 * 1024 * 1024 * 1024)

    @unittest.skipUnless(_HAS_NODE, "Node.js unavailable; UI parser contract still runs")
    def test_exponent_value_over_limit_is_not_truncated(self) -> None:
        """Exponent-form number input preserves its complete numeric value."""

        value = self._javascript_number("6e9")
        self.assertEqual(value, 6_000_000_000)
        self.assertGreater(value, 5 * 1024 * 1024 * 1024)

    @unittest.skipUnless(_HAS_NODE, "Node.js unavailable; UI parser contract still runs")
    def test_nonnumeric_value_remains_invalid(self) -> None:
        """Nonnumeric input continues to produce JavaScript NaN semantics."""

        self.assertIsNone(self._javascript_number("not-a-number"))


if __name__ == "__main__":
    unittest.main()
