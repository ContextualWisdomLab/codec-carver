from fastapi import Request
from starlette.testclient import TestClient
from saas_web import app
import os
from unittest.mock import patch

with patch.dict(os.environ, {"CODEC_CARVER_API_KEYS": "secret-key"}):
    client = TestClient(app)
    req = client.build_request("POST", "/shrink", headers=[(b"x-api-key", b"\xff")])
    response = client.send(req)
    print(response.status_code)
