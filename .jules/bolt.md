## 2026-05-31 - Path Resolution Bottleneck
**Learning:** Calling `Path.resolve()` for every file inside an `os.walk` loop incurs expensive system calls, turning file enumeration from $O(N)$ into a huge performance drag, especially over networked storage or very large directories.
**Action:** Resolve the parent directory once per `os.walk` iteration, and then use simple concatenation (`resolved_parent / filename`) for leaf nodes to compute their resolved path, being careful to only fall back to `Path.resolve()` on the full path if the child node itself is a symlink.
