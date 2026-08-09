from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
import hmac
import os

app = FastAPI()

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    configured_keys = ["secret-key"]
    provided_key = request.headers.get("x-api-key", "")
    if not any(
        hmac.compare_digest(provided_key, key) for key in configured_keys
    ):
        return JSONResponse(status_code=401, content={"error": "Invalid"})
    return await call_next(request)

@app.get("/")
def read_root():
    return {"Hello": "World"}

client = TestClient(app, raise_server_exceptions=False)
response = client.get("/", headers={"x-api-key": b"\xff".decode("latin-1")})
print(f"Status Code: {response.status_code}")
if response.status_code == 500:
    print("Vulnerability confirmed!")
