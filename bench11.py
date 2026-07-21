import timeit

def parse_original(raw_tags):
    return {
        key: value for key, value in
        (part.split("=", 1) for part in raw_tags if "=" in part)
    }

def parse_optimized(raw_tags):
    tags = {}
    for part in raw_tags:
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k] = v
    return tags

def parse_optimized_2(raw_tags):
    tags = {}
    for part in raw_tags:
        idx = part.find("=")
        if idx != -1:
            tags[part[:idx]] = part[idx+1:]
    return tags

raw_tags = ["title=test", "artist=me", "album=the album", "year=2023", "no_equals"] * 10

print("Original:", timeit.timeit(lambda: parse_original(raw_tags), number=100000))
print("Optimized:", timeit.timeit(lambda: parse_optimized(raw_tags), number=100000))
print("Optimized2:", timeit.timeit(lambda: parse_optimized_2(raw_tags), number=100000))
