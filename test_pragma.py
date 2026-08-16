import sqlite3
from job_store import JobStore
import time
import os

if os.path.exists("test.db"):
    os.remove("test.db")

store = JobStore("test.db")
start = time.time()
for i in range(1000):
    store.get("foo")
print("Before optimization:", time.time() - start)
