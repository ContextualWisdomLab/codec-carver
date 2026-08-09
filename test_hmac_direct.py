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
    try:
        if not any(
            hmac.compare_digest(provided_key, key) for key in configured_keys
        ):
            return JSONResponse(status_code=401, content={"error": "Invalid"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": repr(e)})
    return await call_next(request)

@app.get("/")
def read_root():
    return {"Hello": "World"}

client = TestClient(app, raise_server_exceptions=False)
import requests
# Using requests to bypass httpx's strict ASCII header checks to see if the server handles it
try:
    response = requests.get("http://localhost:8000/", headers={"x-api-key": "안녕"})
    print(f"Status Code: {response.status_code}")
except Exception as e:
    print(e)
