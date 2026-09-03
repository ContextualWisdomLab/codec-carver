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
class TestApiKeyHeaderMultiplicity(unittest.TestCase):
    """Lock the credential boundary to exactly one raw X-API-Key header."""

    @staticmethod
    def _request(raw_headers: list[tuple[bytes, bytes]]) -> "Request":
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "https",
                "path": "/shrink",
                "raw_path": b"/shrink",
                "query_string": b"",
                "headers": raw_headers,
                "client": ("127.0.0.1", 12345),
                "server": ("codec-carver.test", 443),
            }
        )

    def _assert_duplicate_is_rejected(self, raw_values: list[bytes]) -> None:
        async def call_next(_request: "Request") -> "Response":
            self.fail("duplicated credentials must not reach the protected handler")

        request = self._request([(b"x-api-key", value) for value in raw_values])
        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "안녕"}):
            response = asyncio.run(saas_web.require_api_key(request, call_next))

        self.assertEqual(response.status_code, 401)

    def test_duplicate_api_key_headers_fail_closed_when_values_differ(self) -> None:
        self._assert_duplicate_is_rejected(
            ["안녕".encode("utf-8"), "다름".encode("utf-8")]
        )

    def test_duplicate_api_key_headers_fail_closed_when_values_match(self) -> None:
        value = "안녕".encode("utf-8")
        self._assert_duplicate_is_rejected([value, value])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
