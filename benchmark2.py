import os
import timeit
import tempfile
import shutil
from pathlib import Path
import media_shrinker

def setup_files(temp_dir):
    root = Path(temp_dir)
    # Create 10000 files
    for i in range(10000):
        (root / f"file_{i}.mp4").write_text("a")

    # Exclude all of them via directory
    # exclude = [root] # wait, if we exclude root it skips early
    # Exclude all by exact paths
    exclude = [root / f"file_{i}.mp4" for i in range(10000)]
    return str(root), exclude

temp_dir = tempfile.mkdtemp()
root, exclude = setup_files(temp_dir)

def test_original():
    list(media_shrinker.find_candidates(root, exclude_paths=exclude))

print("Original:", timeit.timeit(test_original, number=10))
shutil.rmtree(temp_dir)
