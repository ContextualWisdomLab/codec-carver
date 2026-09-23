import asyncio
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
class TestApiKeyUnicodeComparison(unittest.TestCase):
    @staticmethod
    def _request(api_key: str):
        return SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/jobs/missing"),
            headers={"x-api-key": api_key},
        )

    @staticmethod
    async def _call_next(_request):
        return Response(status_code=204)

    def test_non_ascii_untrusted_key_is_rejected_without_compare_digest_error(self):
        request = self._request("clé")

        with patch.object(
            saas_web, "get_configured_api_keys", return_value=["secret-key"]
        ):
            response = asyncio.run(saas_web.require_api_key(request, self._call_next))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.body, b'{"error":"Invalid or missing API key"}')

    def test_matching_non_ascii_key_reaches_handler(self):
        request = self._request("clé")

        with patch.object(
            saas_web, "get_configured_api_keys", return_value=["clé"]
        ):
            response = asyncio.run(saas_web.require_api_key(request, self._call_next))

        self.assertEqual(response.status_code, 204)
