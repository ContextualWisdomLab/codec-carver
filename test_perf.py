import timeit
import os

excluded_exact_strs = tuple(f"/path/to/excluded/dir{i}" for i in range(100))
excluded_prefix_strs = tuple(s + os.sep for s in excluded_exact_strs)

resolved_dir_str = "/path/to/excluded/dir50/subdir"

def old_way():
    return any(
        resolved_dir_str == ex_exact or resolved_dir_str.startswith(ex_pref)
        for ex_exact, ex_pref in zip(excluded_exact_strs, excluded_prefix_strs)
    )

excluded_exact_set = frozenset(excluded_exact_strs)
excluded_prefix_tuple = excluded_prefix_strs

def new_way():
    return resolved_dir_str in excluded_exact_set or resolved_dir_str.startswith(excluded_prefix_tuple)

print("Old:", timeit.timeit(old_way, number=10000))
print("New:", timeit.timeit(new_way, number=10000))

print("Same result:", old_way() == new_way())
