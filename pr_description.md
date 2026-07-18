💡 What: 배치 파일 업로드 시 총 용량이 백엔드 제한(5 GiB)을 초과하는지 클라이언트에서 미리 검증하도록 변경
🎯 Why: 사용자가 긴 업로드 시간을 기다린 후 서버에서 거부되는 문제를 방지하여 UX 개선
📸 Before/After: 크기 초과 시 즉각적인 인라인 에러 메시지 표시
♿ Accessibility: aria-invalid='true' 및 setCustomValidity를 통한 접근성 개선 피드백 제공
