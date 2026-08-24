"""Regression contract for server-authoritative target-size UI limits."""

import asyncio
import unittest

try:
    import saas_web

    _HAS_WEB = True
except (ImportError, RuntimeError):
    saas_web = None
    _HAS_WEB = False


@unittest.skipUnless(_HAS_WEB, "web integration dependencies are unavailable")
class TestTargetLimitContract(unittest.TestCase):
    """Keep client target-size validation bound to the server authority."""

    def test_rendered_ui_uses_server_target_limit(self):
        """Render both target controls from MAX_TARGET_BYTES without literals."""

        previous_limit = saas_web.MAX_TARGET_BYTES
        saas_web.MAX_TARGET_BYTES = 12_345
        try:
            html = asyncio.run(saas_web.get_ui())
        finally:
            saas_web.MAX_TARGET_BYTES = previous_limit

        self.assertEqual(html.count('max="12345"'), 2)
        self.assertIn("const MAX_TARGET_BYTES = 12345;", html)
        self.assertEqual(html.count("val > MAX_TARGET_BYTES"), 2)
        self.assertEqual(html.count("formatBinaryBytes(MAX_TARGET_BYTES)"), 2)
        self.assertNotIn("5368709120", html)


if __name__ == "__main__":
    unittest.main()
