import os
import stat
from pathlib import Path

def os_walk_scandir(top):
    dirs_to_visit = [top]

    while dirs_to_visit:
        current_dir = dirs_to_visit.pop(0)
        dirnames = []
        filenames = []

        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        dirnames.append(entry.name)
                    elif entry.is_file(follow_symlinks=False):
                        filenames.append(entry.name)
        except OSError:
            continue

        yield current_dir, dirnames, filenames

        for d in dirnames:
            dirs_to_visit.append(os.path.join(current_dir, d))

# Actually in `find_candidates` it mutates `dirnames` to control recursion
