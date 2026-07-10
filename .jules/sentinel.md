## 2025-02-27 - Fix path traversal in media converter
**Vulnerability:** Path traversal in `media_shrinker.py` via unresolved `..` relative paths.
**Learning:** `Path.relative_to()` allows relative paths containing `..` to pass if they are not first resolved into absolute logical paths, completely bypassing basic lexical checks.
**Prevention:** When implementing path traversal boundary checks, always call `.resolve()` first before calling `.is_relative_to()` to prevent lexical bypasses (e.g., `root/../etc`).
