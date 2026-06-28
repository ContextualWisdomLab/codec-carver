🚨 **Severity:** MEDIUM
💡 **Vulnerability:** Content Security Policy Allows Unsafe Inline Scripts (CWE-79).
🎯 **Impact:** The Content-Security-Policy header in `saas_web.py` previously included `'unsafe-inline'` in both `style-src` and `script-src` directives. This bypasses critical XSS protections, allowing an attacker to execute malicious scripts if any stored or reflected XSS vulnerabilities exist, potentially leading to session hijacking or data theft.
🔧 **Fix:** Implemented a nonce-based CSP for scripts. Removed `'unsafe-inline'` from `script-src` and replaced it with a dynamically generated `nonce`. The inline `<script>` tag in the HTML template was updated to include this `nonce` attribute, ensuring that only the authorized inline script executes while blocking malicious injected scripts.
✅ **Verification:** Ran test suite via `python3 -m pytest tests --cov=. --cov-fail-under=100`. All tests passed and coverage requirement is met.
