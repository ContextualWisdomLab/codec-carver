import unittest
import os
import asyncio

try:
    from starlette.requests import Request
    from saas_web import require_api_key
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(_HAS_FASTAPI, "fastapi not installed (optional integration dependency)")
class TestSecurityAuth(unittest.IsolatedAsyncioTestCase):
    async def test_auth_compare_digest_unicode(self):
        os.environ["CODEC_CARVER_API_KEYS"] = "mysecretkey"

        scope = {
            "type": "http",
            "method": "POST",
            "url": "/shrink",
            "headers": [(b"x-api-key", "ñ".encode("utf-8"))],
            "path": "/shrink"
        }
        request = Request(scope)

        async def call_next_mock(request):
            class MockResponse:
                def __init__(self):
                    self.status_code = 200
            return MockResponse()

        response = await require_api_key(request, call_next_mock)
        self.assertEqual(response.status_code, 401)
