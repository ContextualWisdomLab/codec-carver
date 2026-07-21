import os
import stat
import timeit
import tempfile
import shutil
from pathlib import Path

temp_dir = tempfile.mkdtemp()
root = Path(temp_dir)
for i in range(10):
    d = root / f"dir_{i}"
    d.mkdir()
    for j in range(100):
        (d / f"file_{j}.mp4").write_text("a")

exclude_paths = [root / f"dir_{i}" for i in range(5)]
exclude_dir_prefixes = ()
size_limit_bytes = 0
include_under_limit = True

def test_optimized():
    excluded = tuple(Path(item).resolve() for item in exclude_paths)
    excluded_prefixes = tuple(prefix.casefold() for prefix in exclude_dir_prefixes)
    candidates = []

    excluded_exact_strs = tuple(str(p) for p in excluded)
    excluded_prefix_strs = tuple(s + os.sep for s in excluded_exact_strs)
    excluded_exact_set = frozenset(excluded_exact_strs)

    # walk through dirs using os.scandir for fewer stat calls and better performance
    dirs_to_visit = [str(root)]

    # define SUPPORTED_EXTS_TUPLE inside for test
    SUPPORTED_EXTS_TUPLE = (
        ".3gp",
        ".3gpp",
        ".ac3",
        ".aiff",
        ".amr",
        ".au",
        ".flac",
        ".m4a",
        ".mid",
        ".mp3",
        ".mxf",
        ".opus",
        ".ra",
        ".wav",
        ".weba",
        ".aac",
        ".asx",
        ".caf",
        ".dts",
        ".mka",
        ".ogg",
        ".wma",
        ".avi",
        ".flv",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".webm",
        ".wmv",
        ".ts",
    )

    while dirs_to_visit:
        current_dir = dirs_to_visit.pop()

        if excluded_exact_strs:
            try:
                resolved_dir_str = os.path.realpath(current_dir)
            except OSError:
                continue

            if resolved_dir_str in excluded_exact_set or resolved_dir_str.startswith(
                excluded_prefix_strs
            ):
                continue
        else:
            resolved_dir_str = current_dir

        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        d_name = entry.name
                        if d_name.casefold().startswith(excluded_prefixes):
                            continue

                        if excluded_exact_strs:
                            try:
                                is_symlink = entry.is_symlink()
                            except OSError:
                                continue

                            if not is_symlink:
                                resolved_d_str = os.path.join(resolved_dir_str, d_name)
                            else:
                                try:
                                    resolved_d_str = os.path.realpath(entry.path)
                                except OSError:
                                    continue

                            if resolved_d_str in excluded_exact_set or resolved_d_str.startswith(
                                excluded_prefix_strs
                            ):
                                continue

                        dirs_to_visit.append(entry.path)

                    elif entry.is_file(follow_symlinks=False):
                        f_name = entry.name
                        if not f_name.lower().endswith(SUPPORTED_EXTS_TUPLE):
                            continue

                        if excluded_exact_strs:
                            resolved_file_str = os.path.join(resolved_dir_str, f_name)
                            if (
                                resolved_file_str in excluded_exact_set
                                or resolved_file_str.startswith(excluded_prefix_strs)
                            ):
                                continue

                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue

                        if include_under_limit or size > size_limit_bytes:
                            candidates.append((Path(entry.path), size))
        except OSError:
            continue

    root_prefix = root.as_posix()
    if not root_prefix.endswith("/"):
        root_prefix += "/"

    return sorted(
        candidates,
        key=lambda item: item[0].as_posix().removeprefix(root_prefix).casefold(),
    )


import media_shrinker
def test_original():
    list(media_shrinker.find_candidates(str(root), exclude_paths=exclude_paths))

print("Original:", timeit.timeit(test_original, number=100))
print("Optimized:", timeit.timeit(test_optimized, number=100))

shutil.rmtree(temp_dir)
