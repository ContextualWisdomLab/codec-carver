🚨 **Severity:** CRITICAL
💡 **Vulnerability:** `media_shrinker.py`의 `convert_file` 함수가 `Path.relative_to()`를 해결되지 않은 경로에 직접 적용해, `..` 세그먼트 또는 symlink escape가 루트 경계 검증을 우회할 수 있었습니다.
🎯 **Impact:** 루트 밖 입력 파일이 변환 대상으로 들어오면 의도하지 않은 파일 읽기 및 출력 경로 계획으로 이어질 수 있습니다.
🔧 **Fix:** source/root를 한 번만 `resolve()`한 뒤 resolved source가 resolved root 아래인지 검사하고, 실패 시 내부 경로를 노출하지 않는 `MediaShrinkerError`로 중단합니다. 기존 Sentinel 보안 학습 이력은 유지하고 새 path traversal 항목만 추가했습니다.
✅ **Verification:**
1. `python3 -m pytest tests/test_security_path_traversal.py -q` → 2 passed.
2. `python3 -m pytest -q` → 145 passed.
3. `python3 -m py_compile media_shrinker.py saas_web.py mcp_driver.py job_store.py && python3 -m unittest discover -s tests -v` → 145 tests OK.
