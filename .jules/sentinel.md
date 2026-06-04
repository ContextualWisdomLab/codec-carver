## 2026-05-28 - [Sentinel Fixes: Temp Files & Injection]
**Vulnerability:** Predictable Temp Files (CWE-377) and Insecure Default Permissions (CWE-276), plus Command Injection via FFmpeg Filtergraph (CWE-20).
**Learning:** Python's `Path.with_name` plus a suffix string to make a temp file opens a race condition because it's predictable and the permissions default to system `umask` which might expose secret `0600` data. Additionally, interpolating variables directly into FFmpeg filtergraph strings allows arbitrary filter injection.
**Prevention:** Use `tempfile.mkstemp` which generates unguessable names and creates the file with secure `0600` permissions automatically. Use strict regex allow-lists for string parameters passed into complex shell-like arguments such as FFmpeg's `-af`.

## 2026-05-29 - [Sentinel: Unsafe Metadata Copying]
**Vulnerability:** Use of `shutil.copymode(source, dest)` preserves potentially dangerous permission bits (setuid, setgid, sticky).
**Learning:** Utilities that copy file metadata (like `shutil.copymode`) can inadvertently transfer elevated execution privileges from an untrusted source to a generated output. This can lead to privilege escalation if the destination file is later executed.
**Prevention:** Explicitly mask file permissions when restoring metadata. Use `os.chmod(dest, stat.S_IMODE(source_stat.st_mode) & 0o777)` to ensure only standard read/write/execute permissions are copied, dropping the setuid, setgid, and sticky bits.

## 2024-06-04 - Prevent SSRF and LFI in FFmpeg integrations
**Vulnerability:** Invoking `ffmpeg` and `ffprobe` via `subprocess.run` without restricting protocols allows maliciously crafted user-uploaded media files or playlists to perform Server-Side Request Forgery (SSRF) and Local File Inclusion (LFI).
**Learning:** `ffmpeg` and `ffprobe` support various protocols (like `http`, `file`, etc.) by default. If a user uploads a malicious HLS playlist (`.m3u8`), it could contain URLs to internal services or local file paths (like `file:///etc/passwd`). When `ffmpeg` or `ffprobe` parses this, it will attempt to fetch those resources.
**Prevention:** Always include the `"-protocol_whitelist", "file,crypto,data"` arguments before the input flag (`-i` for `ffmpeg`, or before the input path for `ffprobe`) when invoking these tools in the codebase to restrict them to only safe, local protocols.
