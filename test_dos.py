import requests

with open("test.txt", "wb") as f:
    f.write(b"a" * 1024 * 1024)

files = {"file": open("test.txt", "rb")}
data = {"target_bytes": 100}
print("ready")
