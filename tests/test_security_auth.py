import pytest
from starlette.requests import Request
from saas_web import require_api_key
import os

@pytest.mark.asyncio
async def test_auth_compare_digest_unicode():
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
    assert response.status_code == 401
