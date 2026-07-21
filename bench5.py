import os
import stat
import timeit
import tempfile
import shutil
from pathlib import Path

temp_dir = tempfile.mkdtemp()
root = Path(temp_dir)
files = []
for i in range(1000):
    p = str(root / f"file_{i}.mp4")
    with open(p, "w") as f:
        f.write("a")
    files.append(p)

def test_lstat_and_mode():
    for f in files:
        try:
            st = os.lstat(f)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                continue
            size = st.st_size
        except OSError:
            pass

def test_lstat_and_mode_bitwise():
    for f in files:
        try:
            st = os.lstat(f)
            mode = st.st_mode
            if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                continue
            size = st.st_size
        except OSError:
            pass

print("test_lstat_and_mode:", timeit.timeit(test_lstat_and_mode, number=100))
print("test_lstat_and_mode_bitwise:", timeit.timeit(test_lstat_and_mode_bitwise, number=100))

shutil.rmtree(temp_dir)
