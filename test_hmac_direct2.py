from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import hmac
import os
import uvicorn
import threading
import time
import socket

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
        print(f"Server caught exception: {repr(e)}")
        return JSONResponse(status_code=500, content={"error": repr(e)})
    return await call_next(request)

@app.get("/")
def read_root():
    return {"Hello": "World"}

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(1)

# Manually send a raw HTTP request with non-ASCII header
req = b"GET / HTTP/1.1\r\nHost: localhost:8000\r\nx-api-key: \xff\r\n\r\n"
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.connect(("127.0.0.1", 8000))
s.sendall(req)
resp = s.recv(4096)
print(resp.decode("latin-1"))
s.close()
