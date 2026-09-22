import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi.responses import Response

    import saas_web

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class TestApiKeyUnicode(unittest.TestCase):
    """Non-ASCII API keys must not escape authentication as exceptions."""

    @staticmethod
    def _request(api_key: str):
        return SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/shrink"),
            headers={"x-api-key": api_key},
        )

    def test_non_ascii_untrusted_key_is_rejected_without_exception(self):
        async def fail_if_called(_request):
            raise AssertionError("invalid credentials must not reach the handler")

        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "secret-key"}):
            response = asyncio.run(
                saas_web.require_api_key(self._request("café"), fail_if_called)
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.body, b'{"error":"Invalid or missing API key"}')

    def test_non_ascii_configured_key_can_match(self):
        async def call_next(_request):
            return Response(status_code=204)

        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "clé-secrète"}):
            response = asyncio.run(
                saas_web.require_api_key(self._request("clé-secrète"), call_next)
            )

        self.assertEqual(response.status_code, 204)


if __name__ == "__main__":
    unittest.main()
