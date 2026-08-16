import sqlite3
import time
import os

from job_store import JobStore

if os.path.exists("test_b.db"): os.remove("test_b.db")

store_b = JobStore("test_b.db")
start = time.time()
for i in range(1000):
    store_b.get("foo")
print("Before:", time.time() - start)
