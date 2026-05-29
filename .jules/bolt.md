## 2024-05-28 - Avoid O(N^2) Path.resolve() in Batch Processing
**Learning:** Python's `pathlib.Path.resolve()` is relatively slow because it touches the filesystem to follow symlinks and resolve relative paths. When dealing with a batch operation (e.g., scanning large directories of media files), calculating protected files via `any(target == src.resolve() for src in sources)` on every check leads to massive O(N^2) CPU overhead.
**Action:** Pre-resolve the entire list of candidate paths once into a `frozenset` at the beginning of the batch process. Pass this resolved set down the call stack so that collision/protection checks become O(1) hash map lookups instead of triggering millions of unnecessary disk access operations.

## 2024-05-29 - [Unit Test Add: _first_int in media_shrinker]
**Learning:** Even simple utility functions like `_first_int` benefit from explicit tests of edge cases, particularly their exception handling blocks which often go uncovered. Placing tests before `if __name__ == "__main__":` ensures compatibility with all test execution methods.
**Action:** Always verify test file structure when appending new test classes to ensure they run correctly within the target test framework and script execution paradigms.
