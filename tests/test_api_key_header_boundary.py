import unittest
import asyncio
import json
import os
from unittest.mock import patch
from fastapi import Request
from saas_web import require_api_key

class TestApiKeyHeaderBoundary(unittest.TestCase):
    def test_raw_asgi_non_ascii_boundary(self):
        # Track if call_next was invoked
        call_next_invoked = False

        async def mock_call_next(request: Request):
            nonlocal call_next_invoked
            call_next_invoked = True
            return None

        # Raw ASGI scope with obs-text/non-ASCII byte b'\xff'
        scope = {
            'type': 'http',
            'method': 'POST',
            'path': '/shrink',
            'headers': [(b'x-api-key', b'\xff')]
        }
        request = Request(scope)

        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "secret-key"}):
            response = asyncio.run(require_api_key(request, mock_call_next))

        # Assert 401 Unauthorized
        self.assertEqual(response.status_code, 401)

        # Assert exact JSON body
        self.assertEqual(json.loads(response.body), {"error": "Invalid or missing API key"})

        # Assert no secret reflection
        self.assertNotIn(b"secret-key", response.body)

        # Assert call_next was NOT invoked
        self.assertFalse(call_next_invoked)
