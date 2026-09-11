import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Request

import saas_web


class ApiKeyHeaderBoundaryTest(unittest.TestCase):
    def test_obs_text_api_key_is_rejected_without_reaching_downstream(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/shrink",
            "headers": [(b"x-api-key", b"\xff")],
        }
        request = Request(scope)
        call_next = AsyncMock()

        with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "secret-key"}):
            response = asyncio.run(saas_web.require_api_key(request, call_next))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            json.loads(response.body),
            {"error": "Invalid or missing API key"},
        )
        call_next.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
