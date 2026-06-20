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

## 2026-06-09 - [Sentinel: FFmpeg Argument Injection Vulnerability Fix]
**Vulnerability:** Argument injection via maliciously crafted filenames.
**Learning:** Command-line utilities (like `ffprobe`) interpret arguments starting with a hyphen (e.g., `-version`, `-help`) as options. If user input (like a file path) is directly passed to the command list without an explicit input flag (like `-i`), a maliciously named file could inject arguments and alter the command execution flow, even with `shell=False`.
**Prevention:** When passing file paths to command-line tools like `ffmpeg` or `ffprobe` via `subprocess.run`, explicitly use the input flag (e.g., `-i`) immediately before the file path. This prevents argument injection vulnerabilities where a filename starting with a hyphen (e.g., `-version`) is misinterpreted as a command-line option.

## 2026-06-15 - [Sentinel: Uncontrolled Resource Consumption in Uploads]
**Vulnerability:** Uncontrolled Resource Consumption (CWE-400) / Missing input length limits via unbound file uploads.
**Learning:** Using `shutil.copyfileobj` blindly copies an uploaded stream directly to disk without size constraints. An attacker could upload an infinitely large file or a file large enough to exhaust server storage space, causing a Denial of Service.
**Prevention:** Do not use unbounded `shutil.copyfileobj` for web uploads. Implement chunked reads and track bytes written, raising an exception safely if a predefined strict maximum file size is exceeded.

## 2026-06-20 - [Sentinel: FastAPI request size limits]
**Vulnerability:** Uncontrolled Resource Consumption (CWE-400) via oversized HTTP request bodies.
**Learning:** A `Content-Length` check rejects known-oversized requests early, but requests without a usable length header still need byte counting while the ASGI body stream is consumed.
**Prevention:** Validate malformed or negative `Content-Length` values, reject declared oversized requests with `413`, and wrap the request receive function so chunked or lengthless uploads cannot exceed the same global limit.

## 2026-06-25 - [Sentinel: Unsafe Subprocess Paths leading to Argument Injection]
**Vulnerability:** Argument Injection via relative paths starting with a hyphen in command-line utilities.
**Learning:** Even when `ffmpeg` inputs are protected by `-i`, the output paths, as well as arguments to other utilities like `brctl` and `SetFile`, can be maliciously crafted to start with `-` and be interpreted as options if relative paths are used.
**Prevention:** Always convert file paths passed to `subprocess.run` to their absolute forms (e.g., `path.absolute()`) when a tool does not support an explicit input flag or `--` delimiter, to guarantee the argument begins with a directory separator.
