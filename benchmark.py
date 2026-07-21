import os
import timeit
import tempfile
from pathlib import Path
import media_shrinker

def setup_files(temp_dir):
    root = Path(temp_dir)
    # Create some files
    for i in range(1000):
        (root / f"file_{i}.mp4").write_text("a")

    # Exclude half of them
    exclude = [root / f"file_{i}.mp4" for i in range(500)]
    return str(root), exclude

temp_dir = tempfile.mkdtemp()
root, exclude = setup_files(temp_dir)

def test_original():
    list(media_shrinker.find_candidates(root, exclude_paths=exclude))

print("Original:", timeit.timeit(test_original, number=10))
