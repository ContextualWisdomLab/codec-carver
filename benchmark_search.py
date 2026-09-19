import time
from transcript_search import TranscriptIndex, Segment

def run_benchmark():
    idx = TranscriptIndex()
    # Create 100,000 synthetic segments to simulate a large transcript search space
    segments = [
        Segment(i * 1.0, i * 1.0 + 1.0, f"word{i % 100} word{i % 50} word{i % 10} hello world " * 10)
        for i in range(100000)
    ]

    print("Building index...")
    t0 = time.time()
    idx.add("rec1", segments)
    t1 = time.time()
    print(f"Indexing completed in {t1 - t0:.3f}s")

    print("\nRunning search benchmark (10 iterations)...")
    t0 = time.time()
    for _ in range(10):
        # We query for terms that are common in our synthetic dataset
        idx.search("hello world word5")
    t1 = time.time()

    print(f"Search benchmark completed in {t1 - t0:.3f}s")

if __name__ == '__main__':
    run_benchmark()
