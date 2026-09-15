## 2024-09-14 - Fix UI state synchronization for manual inputs
**Learning:** 수동으로 값을 입력할 때 스크립트에 의한 변경인지 확인하는 `!e.isTrusted` 조건을 사용하면 UI 상태 동기화가 깨집니다. 프리셋과 동일한 값을 직접 입력하더라도 프리셋 버튼이 활성화되어야 사용자에게 일관된 경험을 제공할 수 있습니다.
**Action:** `e.isTrusted` 이벤트 발생원이 아닌 실제 입력 값에 기반하여 UI 상태가 동기화되도록 이벤트 핸들러의 논리를 수정했습니다.
