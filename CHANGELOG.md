# Changelog

## [Unreleased]
### Added
- 다중 파일 업로드 선택 시 즉각적인 파일 개수 피드백 및 제한 초과 경고 메시지 추가
- 일괄 업로드 폼에 대상 바이트 프리셋 버튼과 총 파일 크기 미리보기를 추가하여 사용성을 개선했습니다.

## [Unreleased]
### Changed
- ⚡ Bolt: `JobStore`에서 각 연결마다 실행되던 중복된 `PRAGMA journal_mode=WAL` 실행을 초기화 시 1회 실행으로 변경하여 성능 향상 (연결 당 속도 약 6% 개선 측정됨).
