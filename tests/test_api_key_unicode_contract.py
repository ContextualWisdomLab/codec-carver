import asyncio
import os
import unittest
from unittest.mock import patch

try:
    import saas_web
    from starlette.requests import Request
    from starlette.responses import Response

    _HAS_WEB_STACK = True
except ImportError:  # pragma: no cover - optional integration dependency boundary
    _HAS_WEB_STACK = False


@unittest.skipUnless(_HAS_WEB_STACK, "web integration dependencies are not installed")
class TestUnicodeApiKeyContract(unittest.TestCase):
    """Exercise API-key authentication from the raw ASGI header boundary."""

    @staticmethod
    def _request(raw_api_key: bytes) -> "Request":
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "https",
                "path": "/shrink",
                "raw_path": b"/shrink",
                "query_string": b"",
                "headers": [(b"x-api-key", raw_api_key)],
                "client": ("127.0.0.1", 12345),
                "server": ("codec-carver.test", 443),
            }
        )

    def test_configured_unicode_key_matches_its_raw_utf8_header(self) -> None:
        reached_handler = False

        async def call_next(_request: "Request") -> "Response":
            nonlocal reached_handler
            reached_handler = True
            return Response(status_code=204)

        configured_key = "안녕"
        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": configured_key}):
            response = asyncio.run(
                saas_web.require_api_key(
                    self._request(configured_key.encode("utf-8")),
                    call_next,
                )
            )

        self.assertTrue(
            reached_handler,
            "a valid configured Unicode key must not be rejected after ASGI header decoding",
        )
        self.assertEqual(response.status_code, 204)

    def test_different_raw_utf8_key_is_rejected(self) -> None:
        async def call_next(_request: "Request") -> "Response":
            self.fail("invalid credentials must not reach the protected handler")

        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "안녕"}):
            response = asyncio.run(
                saas_web.require_api_key(
                    self._request("다름".encode("utf-8")),
                    call_next,
                )
            )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
