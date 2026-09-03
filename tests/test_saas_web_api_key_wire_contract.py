import asyncio
import json
import os
import unittest
from unittest.mock import patch

try:
    from fastapi import Request
    import saas_web

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


@unittest.skipUnless(
    _HAS_FASTAPI, "fastapi not installed (optional integration dependency)"
)
class TestApiKeyWireContract(unittest.TestCase):
    @patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "short,a-much-longer-key"})
    def test_arbitrary_high_bit_header_bytes_are_rejected_without_500(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/shrink",
                "headers": [(b"x-api-key", b"\xff")],
            }
        )

        async def should_not_run(_request):
            raise AssertionError("invalid credentials must not reach the endpoint")

        response = asyncio.run(saas_web.require_api_key(request, should_not_run))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.body),
            {"error": "Invalid or missing API key"},
        )
        self.assertNotIn(b"\xff", response.body)

    @patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "short,a-much-longer-key"})
    def test_configured_key_lengths_keep_exact_authorization_semantics(self):
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/shrink",
                "headers": [(b"x-api-key", b"a-much-longer-key")],
            }
        )

        async def accepted(_request):
            from fastapi.responses import JSONResponse

            return JSONResponse({"status": "ok"})

        response = asyncio.run(saas_web.require_api_key(request, accepted))
        self.assertEqual(response.status_code, 200)
