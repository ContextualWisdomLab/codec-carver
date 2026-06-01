## 2026-05-28 - [Sentinel Fixes: Temp Files & Injection]
**Vulnerability:** Predictable Temp Files (CWE-377) and Insecure Default Permissions (CWE-276), plus Command Injection via FFmpeg Filtergraph (CWE-20).
**Learning:** Python's `Path.with_name` plus a suffix string to make a temp file opens a race condition because it's predictable and the permissions default to system `umask` which might expose secret `0600` data. Additionally, interpolating variables directly into FFmpeg filtergraph strings allows arbitrary filter injection.
**Prevention:** Use `tempfile.mkstemp` which generates unguessable names and creates the file with secure `0600` permissions automatically. Use strict regex allow-lists for string parameters passed into complex shell-like arguments such as FFmpeg's `-af`.

## 2026-05-29 - [Sentinel: Unsafe Metadata Copying]
**Vulnerability:** Use of `shutil.copymode(source, dest)` preserves potentially dangerous permission bits (setuid, setgid, sticky).
**Learning:** Utilities that copy file metadata (like `shutil.copymode`) can inadvertently transfer elevated execution privileges from an untrusted source to a generated output. This can lead to privilege escalation if the destination file is later executed.
**Prevention:** Explicitly mask file permissions when restoring metadata. Use `os.chmod(dest, stat.S_IMODE(source_stat.st_mode) & 0o777)` to ensure only standard read/write/execute permissions are copied, dropping the setuid, setgid, and sticky bits.
## 2025-05-31 - FastMCP/FastAPI Leakage and Validation Missing
**Vulnerability:** Information Exposure and Missing Input Validation. Exceptions raised in `saas_web.py` were directly captured, cast to string via `str(e)`, and returned in API responses (`{"error": str(e)}`). This can expose internal server state, stack traces, and local filesystem paths to users. Furthermore, `target_bytes` and `file.filename` lacked explicit validation before being utilized in paths and backend calls.
**Learning:** Even internal or temporary applications using lightweight frameworks like FastAPI need explicit try/catch blocks that log full traces *internally* using `logger.error(..., exc_info=True)` and return only generic messages to the client. Similarly, implicit framework typing is insufficient; manual sanity checks (like `target_bytes > 0` or missing filenames) prevent unexpected backend behavior or DOS loops.
**Prevention:**
- Catch unhandled exceptions securely: log on the server and return a generic UI message.
- Validate all incoming parameters (size bounds, strings, paths) before utilization.
