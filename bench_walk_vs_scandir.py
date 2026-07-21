import os
import timeit
import tempfile
import shutil
from pathlib import Path

temp_dir = tempfile.mkdtemp()
root = Path(temp_dir)

# Create 100 directories with 100 files each
for i in range(100):
    d = root / f"dir_{i}"
    d.mkdir()
    for j in range(100):
        (d / f"file_{j}.mp4").write_text("a")

def test_walk():
    count = 0
    for dirpath, dirnames, filenames in os.walk(str(root)):
        for f in filenames:
            if not f.endswith(".mp4"): continue
            p = os.path.join(dirpath, f)
            st = os.lstat(p)
            if not st.st_mode & 0o170000 == 0o100000: # isreg
                continue
            count += st.st_size
    return count

def test_scandir():
    count = 0
    dirs = [str(root)]
    while dirs:
        d = dirs.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".mp4"):
                        count += entry.stat(follow_symlinks=False).st_size
        except OSError:
            pass
    return count

print("walk:", timeit.timeit(test_walk, number=100))
print("scandir:", timeit.timeit(test_scandir, number=100))

shutil.rmtree(temp_dir)
