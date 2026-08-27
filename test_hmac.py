from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
import hmac
import traceback
import uvicorn
import httpx
import asyncio

app = FastAPI()

configured_keys = ["validkey"]

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    provided_key = request.headers.get("x-api-key", "")
    try:
        if not any(hmac.compare_digest(provided_key, key) for key in configured_keys):
            return JSONResponse(status_code=401, content={"error": "Invalid or missing API key"})
    except Exception as e:
        print("Exception:", e)
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": "Server error"})
    return await call_next(request)

@app.get("/test")
def test():
    return {"status": "ok"}

async def run_test():
    config = uvicorn.Config(app, port=8888, log_level="info")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    await asyncio.sleep(1) # wait for server to start

    # Use raw socket to bypass httpx ascii check
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 8888))

    # send raw bytes
    req = b"GET /test HTTP/1.1\r\nHost: 127.0.0.1:8888\r\nx-api-key: invalid\xc3\xb1\r\n\r\n"
    s.sendall(req)

    resp = s.recv(4096)
    print("Response:\n", resp.decode('latin1'))
    s.close()

    server.should_exit = True
    await task

if __name__ == "__main__":
    asyncio.run(run_test())
