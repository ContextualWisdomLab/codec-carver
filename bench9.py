import os
import stat
import timeit
import tempfile
import shutil
from pathlib import Path
import media_shrinker

temp_dir = tempfile.mkdtemp()
root = Path(temp_dir)
for i in range(10):
    d = root / f"dir_{i}"
    d.mkdir()
    for j in range(100):
        (d / f"file_{j}.mp4").write_text("a")

exclude_paths = [root / f"dir_{i}" for i in range(5)]

def test_original():
    list(media_shrinker.find_candidates(str(root), exclude_paths=exclude_paths))

def test_optimized():
    # Simulate caching os.lstat locally since Python does it
    pass

print("Original:", timeit.timeit(test_original, number=100))

shutil.rmtree(temp_dir)
