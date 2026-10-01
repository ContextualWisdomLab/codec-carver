## 2026-10-01 - Sentinel Fix for `httpx2` vulnerability
**Learning:** `httpx2` versions prior to 2.13.1 have vulnerabilities (e.g. CVE-2026-84380).
**Action:** When asked to fix `httpx2` vulnerabilities, use version 2.13.1 and regenerate the lock files, ensuring all python version-specific locks are handled carefully if required.
