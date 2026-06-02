## 2024-05-28 - Avoid O(N^2) Path.resolve() in Batch Processing
**Learning:** Python's `pathlib.Path.resolve()` is relatively slow because it touches the filesystem to follow symlinks and resolve relative paths. When dealing with a batch operation (e.g., scanning large directories of media files), calculating protected files via `any(target == src.resolve() for src in sources)` on every check leads to massive O(N^2) CPU overhead.
**Action:** Pre-resolve the entire list of candidate paths once into a `frozenset` at the beginning of the batch process. Pass this resolved set down the call stack so that collision/protection checks become O(1) hash map lookups instead of triggering millions of unnecessary disk access operations.

## 2024-05-29 - [Optimization of Directory Traversal using os.walk]
**Learning:** `Path.rglob()` loads the entire file tree recursively without allowing pruning. This is computationally expensive, especially when filtering excludes entire directories and deep folder paths.
**Action:** Replace `rglob` with `os.walk`, modifying `dirnames` in-place to prune excluded folders directly, resulting in orders of magnitude speedups depending on search depth and amount of un-traversable folders.

## 2024-05-29 - [Unit Test Add: _first_int in media_shrinker]
**Learning:** Even simple utility functions like `_first_int` benefit from explicit tests of edge cases, particularly their exception handling blocks which often go uncovered. Placing tests before `if __name__ == "__main__":` ensures compatibility with all test execution methods.
**Action:** Always verify test file structure when appending new test classes to ensure they run correctly within the target test framework and script execution paradigms.

## 2024-05-15 - Unsafe Path Resolution Optimization
**Learning:** `Path.is_symlink()` only checks if the final path component is a symlink, missing symlinks in parent directories. Using it to conditionally skip `Path.resolve()` is dangerous and can break collision detection logic.
**Action:** Always prefer resolving paths fully or rely on caller-provided pre-resolved data structures rather than trying to build conditional bypasses for `Path.resolve()`.

## 2026-05-30 - [Optimize file size discovery to prevent redundant disk I/O]
**Learning:** Calling `stat()` multiple times per file for file size in a large directory tree is inefficient. Passing down the size determined during the candidate gathering phase skips redundant I/O operations and speeds up the entire media shrinking run when evaluating thousands of files.
**Action:** When walking directory trees and checking file sizes to filter out targets, capture and propagate these sizes in memory if downstream functions need them, instead of statting files a second time.

## 2024-05-30 - Converting CLI tool to MCP and SaaS Web Service
**Learning:** When building FastAPI apps that wrap heavy, blocking synchronous tasks (like audio/video conversion using subprocesses), do NOT use `async def` for the endpoint function. Using a synchronous `def` allows FastAPI to run the blocking task in a threadpool, preventing the event loop from stalling. Also, handle file uploads cleanly with streaming (`shutil.copyfileobj(file.file, f)`) instead of `await file.read()` to avoid OOM issues on large media files.
**Action:** Always evaluate whether wrapped library functions block I/O. If they do, expose them via synchronous `def` route handlers in FastAPI. Use `shutil.copyfileobj` for large file uploads.

## 2024-06-02 - Avoid O(N) Path.resolve() inside os.walk()
**Learning:** Calling `pathlib.Path.resolve()` on every individual file during an `os.walk` iteration creates massive I/O overhead because Python traces and `lstat`s every component of the path for symlink resolution. If we verify that a file itself is not a symlink, its resolved path is simply the resolved parent directory combined with the filename.
**Action:** When filtering files during a directory walk, resolve the parent directory once per iteration. For each file, substitute the expensive `file.resolve()` with `resolved_parent_dir / filename` to drastically reduce syscalls from O(number of files) to O(number of directories).
