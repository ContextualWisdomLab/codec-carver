import sys
import glob

def add_docstrings(filename):
    with open(filename, 'r') as f:
        source = f.read()

    lines = source.splitlines()

    insertions = []

    if lines and not lines[0].startswith('"""'):
        insertions.append((0, '"""Module docstring."""'))

    for i, line in enumerate(lines):
        if line.strip().startswith('class ') and line.endswith(':'):
            if i + 1 < len(lines) and not lines[i+1].strip().startswith('"""'):
                col_offset = len(line) - len(line.lstrip()) + 4
                insertions.append((i + 1, " " * col_offset + '"""Class docstring."""'))
        elif line.strip().startswith('def ') and line.endswith(':'):
            if i + 1 < len(lines) and not lines[i+1].strip().startswith('"""'):
                col_offset = len(line) - len(line.lstrip()) + 4
                insertions.append((i + 1, " " * col_offset + '"""Function docstring."""'))

    insertions.sort(key=lambda x: x[0], reverse=True)

    for line_idx, doc_str in insertions:
        lines.insert(line_idx, doc_str)

    with open(filename, 'w') as f:
        f.write("\n".join(lines) + "\n")

for fn in glob.glob("tests/*.py"):
    add_docstrings(fn)
