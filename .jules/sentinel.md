## 2026-05-28 - [Sentinel Fixes: Temp Files & Injection]
**Vulnerability:** Predictable Temp Files (CWE-377) and Insecure Default Permissions (CWE-276), plus Command Injection via FFmpeg Filtergraph (CWE-20).
**Learning:** Python's `Path.with_name` plus a suffix string to make a temp file opens a race condition because it's predictable and the permissions default to system `umask` which might expose secret `0600` data. Additionally, interpolating variables directly into FFmpeg filtergraph strings allows arbitrary filter injection.
**Prevention:** Use `tempfile.mkstemp` which generates unguessable names and creates the file with secure `0600` permissions automatically. Use strict regex allow-lists for string parameters passed into complex shell-like arguments such as FFmpeg's `-af`.

## 2026-05-29 - [Sentinel: Unsafe Metadata Copying]
**Vulnerability:** Use of `shutil.copymode(source, dest)` preserves potentially dangerous permission bits (setuid, setgid, sticky).
**Learning:** Utilities that copy file metadata (like `shutil.copymode`) can inadvertently transfer elevated execution privileges from an untrusted source to a generated output. This can lead to privilege escalation if the destination file is later executed.
**Prevention:** Explicitly mask file permissions when restoring metadata. Use `os.chmod(dest, stat.S_IMODE(source_stat.st_mode) & 0o777)` to ensure only standard read/write/execute permissions are copied, dropping the setuid, setgid, and sticky bits.
## 2024-06-03 - [Sentinel: Path Traversal/IsADirectoryError via Empty/Relative Upload Filename]
**Vulnerability:** FastAPIs `UploadFile.filename` can resolve to empty string or relative path dots like `..`. When passed into `Path(filename).name`, it resolves to `..`, which then throws `IsADirectoryError` when attempting to open and write to the file. This skips the error handling if it is outside a try block and exposes unhandled exceptions and potentially leaks disk space with uncleaned temporary directories.
**Learning:** Using `Path(filename).name` isn't enough to sanitize a filename. An empty string evaluates to `.`, and paths like `../..` evaluate to `..` for their name. Always check if the resulting name is safe (e.g. not empty, `.`, or `..`) before opening a file for writing.
**Prevention:** Wrap file saving logic inside a try block with proper directory cleanup and perform validation like `if not safe_filename or safe_filename in {'.', '..'}: safe_filename = 'upload.bin'` to handle edge cases.
