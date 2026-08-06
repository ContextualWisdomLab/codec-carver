import sys
from pathlib import Path

for wf_path in Path(".github/workflows").glob("*.yml"):
    content = wf_path.read_text()
    if "permissions:" in content and "contents: write" in content:
        content = content.replace("contents: write", "contents: read")
        wf_path.write_text(content)
        print(f"Patched {wf_path.name}")
