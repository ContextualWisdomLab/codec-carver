🚨 **Severity:** CRITICAL
💡 **Vulnerability:** `media_shrinker.py` 파일의 `convert_file` 함수에서 소스 경로가 대상 작업 디렉토리(root) 내에 존재하는지 검증하지 않는 경로 탐색(Path Traversal) 취약점이 발견되었습니다. 만약 사용자가 조작된 상대 경로(예: `../../../etc/passwd`)나 악의적인 심볼릭 링크를 포함하여 입력할 경우, 시스템의 임의 파일에 접근하거나 생성된 결과물이 의도치 않은 위치에 저장될 수 있는 위험이 있었습니다.
🎯 **Impact:** 공격자가 어플리케이션이 실행되는 환경의 중요 시스템 파일을 읽거나 변조할 수 있으며, 최악의 경우 임의 코드 실행이나 심각한 정보 유출로 이어질 수 있습니다.
🔧 **Fix:** `Path.resolve()` 함수를 사용하여 심볼릭 링크 및 상대 경로(`..`)를 모두 해석한 절대 경로를 구한 뒤, `is_relative_to()`를 호출하여 실제 파일 시스템 상에서 입력 경로가 지정된 `root` 디렉토리 하위에 속하는지 엄격하게 검증하도록 방어 코드를 10줄 이내로 추가하였습니다. 조건을 만족하지 않으면 `ValueError`를 발생시켜 안전하게 차단합니다.
✅ **Verification:**
1. `tests/test_security_path_traversal.py` 파일에 공격 시나리오(예: `/tmp/outside.mp4`를 접근 시도)를 모사하는 단위 테스트를 추가했습니다.
2. `python3 -m unittest discover -s tests` 명령으로 테스트를 실행하여 차단 확인.
3. `coverage` 도구로 테스트 커버리지가 100% 유지됨을 확인.
