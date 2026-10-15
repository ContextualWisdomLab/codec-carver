from transcript_search import TranscriptIndex, Segment, Match

idx = TranscriptIndex()
idx.add("test1", [Segment(0, 1, "hello world"), Segment(1, 2, "hello")])

candidates = idx._postings["hello"]

# In Python, `&` operation on two sets returns a NEW set.
s1 = {1, 2, 3}
s2 = {2, 3, 4}
s3 = s1 & s2

print("s1 is the same as before:", s1 == {1, 2, 3})
print("s3 is a new set:", id(s1) != id(s3))

# Wait, the code reviewer is saying that if there's only 1 word in the query...
# unique_terms = ["hello"]
# candidates is None
# term = "hello"
# postings = self._postings.get("hello")
# candidates = postings if candidates is None else candidates & postings
# candidates becomes a reference to the internal `postings` set!
# AND THEN `candidates` is not modified any further inside the `search` method!
# BUT! `candidates` is NEVER returned to the caller!
# The method only iterates over `candidates` to generate a list of `Match` objects.
# See:
# for position in candidates or ():
#     entry = self._entries[position]
#     score = sum(...)
#     matches.append(...)
# return matches
# So `candidates` is NOT exposed to the caller. It is purely local to the `search` method.
# Therefore, it cannot be mutated by the caller.

# Let's double check this logic.
