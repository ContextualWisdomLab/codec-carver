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
**Prevention:** Resolve file paths before passing them to `subprocess.run` when a tool does not support an explicit input flag or `--` delimiter. Absolute paths use a root, drive, or UNC prefix rather than a leading hyphen, so they cannot be parsed as command-line options.

## 2026-06-25 - [Sentinel: Strix CI Command Injection False Positives]
**Vulnerability:** CI security scanners (like Strix) falsely reporting command injection vulnerabilities when `shell=False` is omitted.
**Learning:** Some static analysis security tools flag `subprocess.run` calls as vulnerable to command injection if the `shell` argument is missing, even when the command is passed safely as a list of strings.
**Prevention:** Explicitly include `shell=False` in all `subprocess.run` calls, even when passing arguments as a list, to prevent false positive command injection alerts from CI security scanners like Strix.

## 2026-07-05 - [Sentinel: Fix Argument Injection Vulnerability]
**Vulnerability:** Argument Injection via relative paths starting with a hyphen in command-line utilities (CWE-88).
**Learning:** Even when `ffmpeg` inputs are protected by `-i`, command-line utilities (like `ffprobe` and `ffmpeg` filters) can interpret user input (like a file path) starting with a hyphen (e.g., `-version.wav`) as options if passed as a relative path.
**Prevention:** File paths must be converted to absolute paths using `.resolve()` before they are passed to `subprocess.run`. This prefixes the path with a root, drive, or UNC prefix rather than a leading hyphen, thereby averting the possibility of argument injection.
## 2026-07-06 - [Sentinel: Uncontrolled Resource Consumption (DoS) via Subprocess Timeouts]
**Vulnerability:** Uncontrolled Resource Consumption (CWE-400) via missing subprocess timeouts.
**Learning:** `subprocess.run` calls without explicit `timeout` arguments can cause the application to hang indefinitely if the spawned process (e.g., `ffmpeg`, `ffprobe`, `brctl`) deadlocks or takes an unreasonable amount of time due to maliciously crafted input files or underlying system issues.
**Prevention:** Always specify an explicit, appropriate `timeout` parameter for `subprocess.run` calls (e.g., 60s for probes/metadata, 3600s+ for intensive processing) and handle the resulting `subprocess.TimeoutExpired` exception to ensure the application fails securely and releases resources.

## 2026-07-09 - [Sentinel: FastAPI Missing Defense-in-Depth Headers]
**Vulnerability:** Missing defense-in-depth security headers like `Referrer-Policy` and `Permissions-Policy`.
**Learning:** To enhance security in FastAPI applications, missing HTTP response headers could leak referrers or give access to APIs (e.g. geolocation) without explicit intent.
**Prevention:** Implement an `@app.middleware('http')` function to globally inject defense-in-depth security headers such as `Content-Security-Policy`, `X-Frame-Options`, `Strict-Transport-Security`, `X-Content-Type-Options`, `X-XSS-Protection`, `Referrer-Policy` (e.g., `strict-origin-when-cross-origin`), and `Permissions-Policy` (e.g., `geolocation=(), microphone=(), camera=()`).

## 2026-07-10 - [Sentinel: Media Source Path Traversal]
**Vulnerability:** Path traversal in `media_shrinker.py` via unresolved `..` segments or symlink escapes before deriving conversion output paths.
**Learning:** `Path.relative_to()` is only a lexical containment check unless both the source and root have first been resolved into canonical absolute paths. Relative paths and symlinks can otherwise bypass root-boundary assumptions.
**Prevention:** Resolve both source and root once, reject sources outside the resolved root with a sanitized `MediaShrinkerError`, and derive `rel_source` from the resolved paths before planning outputs.
## 2024-05-24 - hmac.compare_digest의 유니코드 예외 취약점 수정
**취약점:** `saas_web.py`의 `require_api_key` 미들웨어에서 API 키를 검증할 때 사용하는 `hmac.compare_digest`가 non-ASCII 문자가 포함된 문자열을 비교할 때 `TypeError`를 발생시키는 취약점이 있었습니다. 이는 공격자가 악의적인 헤더를 전송하여 500 서버 에러(DoS)를 유발할 수 있습니다.
**학습:** 파이썬의 `hmac.compare_digest()`는 non-ASCII 문자를 포함한 문자열 비교를 지원하지 않아 예외가 발생합니다. HTTP 헤더와 같이 사용자 입력을 직접 처리하는 미들웨어에서는 이러한 예외를 방지하기 위해 항상 문자열을 바이트로 변환한 후 비교해야 함을 배웠습니다.
**예방:** `hmac.compare_digest()`에 전달되는 모든 문자열 인자는 비교 전에 명시적으로 바이트로 인코딩(`.encode("utf-8")`)하여 안전하게 처리해야 합니다.
## 2024-05-25 - 임시 디렉토리 누적으로 인한 디스크 고갈(DoS) 취약점 수정
**취약점:** `saas_web.py`의 `/jobs` 엔드포인트에서 생성된 임시 디렉토리가 작업 결과 다운로드 시에만 삭제되도록 구현되어 있어, 공격자가 무수히 많은 작업을 요청하고 다운로드하지 않을 경우 디스크 공간이 고갈되는 서비스 거부(DoS) 취약점이 있었습니다.
**학습:** 백그라운드 작업에서 생성되는 리소스는 클라이언트의 후속 액션(다운로드 등)에만 의존해서는 안 되며, 작업 완료 시 즉시 정리할 수 있는 구조를 갖춰야 디스크 고갈 공격을 방지할 수 있음을 배웠습니다.
**예방:** 작업 완료 시 즉각적으로 결과물을 영구 저장소(`codec_carver_results`)로 이동한 후 무거운 임시 디렉토리는 바로 정리하고, 클라이언트가 결과를 가져간 후 영구 저장소의 파일만 삭제하도록 생명 주기를 분리하여 관리해야 합니다.

## 2026-08-07 - [Sentinel: Owned result storage and independent retention]
**Vulnerability:** 완료된 비동기 결과를 예측 가능한 공유 임시 디렉터리에 저장하고 다운로드에만 삭제를 의존하면, 선점된 디렉터리/경로 신뢰 문제와 다운로드하지 않는 반복 제출에 의한 디스크 고갈(CWE-377, CWE-400, CWE-770)이 발생할 수 있습니다.
**Learning:** 결과 저장소는 `tempfile.mkdtemp()`가 생성한 프로세스 소유의 예측 불가능한 루트를 단일 신뢰 경계로 재사용해야 합니다. 다운로드 후 삭제만으로는 보존 정책이 아니므로, 완료 시각을 기준으로 한 별도 TTL 정리가 신규 작업 수락 전과 작업 완료 후 실행되어야 합니다. 보존 정리는 저장된 경로가 소유 결과 루트 내부일 때만 파일을 삭제하며, 외부 경로를 가리키는 손상된 메타데이터는 파일을 건드리지 않고 만료 레코드만 제거합니다.
**Prevention:** 완료 결과의 기본 보존 기간은 24시간(`RESULT_RETENTION_SECONDS`)이며, 새 `/jobs` 요청을 수락하기 전에 만료 결과 정리가 성공해야 합니다. 각 작업 완료 후에도 같은 정리를 수행하므로 공격자가 결과를 다운로드하지 않아도 오래된 파일과 해당 `JobStore` 레코드는 함께 제거됩니다. 서비스가 완전히 유휴한 동안에는 TTL을 넘긴 파일이 다음 작업/결과 접근까지 남을 수 있지만 추가 디스크 소비도 발생하지 않습니다. 동기 배치 결과는 동일한 소유 루트에 이동한 뒤 응답 완료 시 즉시 삭제하며, 결과 루트 생성 또는 이동 실패 시 요청 작업공간을 정리하고 표준 오류 응답으로 실패합니다. 다운로드 후 `_cleanup_job` 삭제는 TTL과 별개의 보조 정리로 유지됩니다.