import timeit

s = "this is a string for string concatenation in loop test"
words = s.split()

def test_original():
    full_text = ""
    for w in words:
        full_text += w + " "
    return full_text.strip()

def test_optimized():
    return " ".join(words).strip()

print("Original:", timeit.timeit(test_original, number=1000000))
print("Optimized:", timeit.timeit(test_optimized, number=1000000))
