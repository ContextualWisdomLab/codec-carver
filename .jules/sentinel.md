## 2026-05-28 - [Sentinel Fixes: Temp Files & Injection]
**Vulnerability:** Predictable Temp Files (CWE-377) and Insecure Default Permissions (CWE-276), plus Command Injection via FFmpeg Filtergraph (CWE-20).
**Learning:** Python's `Path.with_name` plus a suffix string to make a temp file opens a race condition because it's predictable and the permissions default to system `umask` which might expose secret `0600` data. Additionally, interpolating variables directly into FFmpeg filtergraph strings allows arbitrary filter injection.
**Prevention:** Use `tempfile.mkstemp` which generates unguessable names and creates the file with secure `0600` permissions automatically. Use strict regex allow-lists for string parameters passed into complex shell-like arguments such as FFmpeg's `-af`.

## 2026-05-29 - [Sentinel: Unsafe Metadata Copying]
**Vulnerability:** Use of `shutil.copymode(source, dest)` preserves potentially dangerous permission bits (setuid, setgid, sticky).
**Learning:** Utilities that copy file metadata (like `shutil.copymode`) can inadvertently transfer elevated execution privileges from an untrusted source to a generated output. This can lead to privilege escalation if the destination file is later executed.
**Prevention:** Explicitly mask file permissions when restoring metadata. Use `os.chmod(dest, stat.S_IMODE(source_stat.st_mode) & 0o777)` to ensure only standard read/write/execute permissions are copied, dropping the setuid, setgid, and sticky bits.
## 2026-05-31 - [Sentinel: Unhandled FastAPI Upload Vulnerability Leading to Temporary Directory Leak]
**Vulnerability:** Path edge cases in uploaded filenames (`.`, `..`, or empty strings) triggering unhandled exceptions (`IsADirectoryError`) before reaching cleanup blocks, causing unbounded temporary directory accumulation on disk (CWE-400 / CWE-770 Resource Exhaustion / DoS).
**Learning:** In FastAPI/Starlette, `file.filename` can be unsafe or empty. Using `Path(file.filename).name` may resolve to `.` or `..`, leading to OS-level exceptions when attempting to write data. If resource allocation (like `tempfile.mkdtemp()`) occurs outside the scope of the `try...finally` (or `BackgroundTasks` cleanup) that handles these errors, an attacker can intentionally leak resources by sending manipulated paths.
**Prevention:** Always place resource allocation inside or immediately before the associated `try...finally` block. Sanitize and validate filenames retrieved from `UploadFile.filename` by ensuring they are non-empty and are not relative references (`.` or `..`), providing a safe default fallback.

## 2026-06-07 - FFmpeg SSRF/LFI Vulnerability Fix
**Vulnerability:** Local File Inclusion and Server-Side Request Forgery via unrestricted FFmpeg/FFprobe protocols.
**Learning:** The application executed FFmpeg and FFprobe on user-supplied media files without protocol restrictions. Malicious files (like HLS playlists) could leverage protocols like `http` to exfiltrate data or access internal services.
**Prevention:** Always enforce `"-protocol_whitelist", "file,crypto,data"` before the input flag when invoking FFmpeg/FFprobe to restrict processing to safe local protocols.

## 2026-06-08 - Sentinel: Argument Injection in subprocess
**Vulnerability:** Argument Injection via filenames starting with hyphens in `subprocess.run` (CWE-88).
**Learning:** Even when avoiding `shell=True` and using argument lists for subprocesses, passing untrusted variables (like filenames) directly without an explicit argument flag (like `-i`) or delimiter (like `--`) allows those variables to be parsed as command-line options by the target utility if they begin with a hyphen (e.g., `-version`).
**Prevention:** Always place the explicit input flag (e.g., `-i` for `ffmpeg`/`ffprobe`) immediately preceding any variable file paths passed into an argument list. If an explicit flag is unavailable, use `--` to indicate the end of options before passing file paths, or ensure the path is absolute (thus starting with a directory separator, not a hyphen).
