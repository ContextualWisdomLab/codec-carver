import transcript_search
idx = transcript_search.TranscriptIndex()
idx.add("test", [transcript_search.Segment(0, 1, "hello world")])
try:
    print(idx.search("hello "))
except Exception as e:
    print(f"Error: {e}")
