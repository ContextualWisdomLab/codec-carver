import timeit
import os

from pathlib import Path

root_str = "."

excluded_exact_strs = tuple(f"/path/to/excluded/dir{i}" for i in range(100))
excluded_prefix_strs = tuple(s + os.sep for s in excluded_exact_strs)
excluded_exact_set = frozenset(excluded_exact_strs)

def test_original():
    count = 0
    for dirpath_str, dirnames, filenames in os.walk(root_str):
        resolved_dir_str = os.path.abspath(dirpath_str)
        if excluded_exact_strs:
            if any(
                resolved_dir_str == ex_exact or resolved_dir_str.startswith(ex_pref)
                for ex_exact, ex_pref in zip(excluded_exact_strs, excluded_prefix_strs)
            ):
                dirnames[:] = []
                continue
        count += 1
    return count

def test_optimized():
    count = 0
    for dirpath_str, dirnames, filenames in os.walk(root_str):
        resolved_dir_str = os.path.abspath(dirpath_str)
        if excluded_exact_strs:
            if resolved_dir_str in excluded_exact_set or resolved_dir_str.startswith(excluded_prefix_strs):
                dirnames[:] = []
                continue
        count += 1
    return count

print("Original time:", timeit.timeit(test_original, number=100))
print("Optimized time:", timeit.timeit(test_optimized, number=100))
