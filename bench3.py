import timeit
s = "test_file_name_very_long.MP4"
t = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".flac", ".opus", ".wav", ".aac")
t_both = tuple(ext for ext in t) + tuple(ext.upper() for ext in t)

def test1():
    s.lower().endswith(t)

def test2():
    s.endswith(t_both)

print("test1:", timeit.timeit(test1, number=1000000))
print("test2:", timeit.timeit(test2, number=1000000))
