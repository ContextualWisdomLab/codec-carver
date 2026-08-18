from datetime import datetime, timezone
import tempfile
import time
from usage_metering import UsageStore

def benchmark_usage():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        store = UsageStore(f.name)
        now = datetime.now(timezone.utc)

        start = time.time()
        for i in range(100):
            store.record("test_key", input_bytes=100, output_bytes=100, now=now)
        end = time.time()
        print(f"UsageStore 100 records: {end - start:.4f}s")

benchmark_usage()
