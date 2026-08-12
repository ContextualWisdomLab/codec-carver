from fastapi.testclient import TestClient
from saas_web import app

client = TestClient(app)
response = client.get("/")
print("Response OK:", response.status_code == 200)
