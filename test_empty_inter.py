import transcript_search
import traceback
idx = transcript_search.TranscriptIndex()
class Seg:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text
idx.add("1", [Seg(0, 1, "hello")])
try:
    idx.search("")
except ValueError:
    print("Caught ValueError as expected")
except Exception as e:
    traceback.print_exc()

try:
    print(idx.search("hello"))
    print(idx.search("world"))
except Exception as e:
    traceback.print_exc()
