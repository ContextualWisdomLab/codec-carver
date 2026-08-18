"""Buyer-facing validation-copy contracts for target-size inputs."""

from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient

    import saas_web

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class TargetBytesActionCopyTests(unittest.TestCase):
    """Keep invalid target-size feedback actionable and assistive-tech visible."""

    def test_target_size_errors_tell_the_customer_how_to_recover(self) -> None:
        """Require correction guidance rather than descriptive limit-only errors."""
        html = TestClient(saas_web.app).get("/").text

        max_message = (
            "const maxTargetMessage = 'Enter a target size of ' + limitText + "
            "' or less.';"
        )
        self.assertEqual(html.count(max_message), 2)
        self.assertEqual(html.count("preview.innerText = maxTargetMessage;"), 2)
        self.assertEqual(html.count("this.setCustomValidity(maxTargetMessage);"), 2)
        self.assertEqual(
            html.count("Enter a target size greater than 0 bytes."),
            4,
        )
        self.assertNotIn("Cannot exceed ' + limitText", html)
        self.assertNotIn("Must be greater than 0.", html)


if __name__ == "__main__":
    unittest.main()
