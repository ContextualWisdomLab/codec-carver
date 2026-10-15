import time
from transcript_search import TranscriptIndex, Segment, Match

idx = TranscriptIndex()
segments = []
for i in range(100000):
    segments.append(Segment(i, i+1, "hello world test performance optimization"))
idx.add("test1", segments)

candidates = idx._postings["hello"]

start = time.time()
for _ in range(100):
    entries = idx._entries
    matches = [
        Match(
            recording_id=(e := entries[p]).recording_id,
            start=e.start,
            end=e.end,
            text=e.text,
            score=1
        )
        for p in candidates
    ]
print("List comprehension with assignment expr:", time.time() - start)
