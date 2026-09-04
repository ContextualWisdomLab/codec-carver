# Changelog

## [Unreleased]
### Added
- 다중 파일 업로드 선택 시 즉각적인 파일 개수 피드백 및 제한 초과 경고 메시지 추가
- 일괄 업로드 폼에 대상 바이트 프리셋 버튼과 총 파일 크기 미리보기를 추가하여 사용성을 개선했습니다.
- 클라이언트 측 폼 검증 시 하드코딩된 '5 GiB' 텍스트를 동적으로 변환되도록 수정하고 일괄 업로드 폼에 최대 크기(MAX_UPLOAD_BYTES) 검증 피드백을 추가했습니다.
- 자동 요약 선택의 연구·측정 근거가 마련되기 전까지 fail-closed하도록 하는 summarization evidence boundary와 RCA 문서를 추가했습니다.
- transcript retrieval의 token admission·relevance ranking·tie policy가 검증되기 전까지 fail-closed하도록 하는 retrieval evidence boundary와 RCA 문서를 추가했습니다.

### Changed
- 과거 순수 영숫자 token fast-path equivalence 증거는 구현 동등성 기록으로만 보존하고, transcript summarization/search의 production decision 근거로는 폐기했습니다. [`docs/doctoring/token-fast-path-equivalence.md`](docs/doctoring/token-fast-path-equivalence.md)에 superseded 상태와 범위를 기록했습니다.
- 검증되지 않은 stopword/빈도 점수/고정 5문장/위치 tie-break 기반 transcript summarizer를 제거했습니다. 비어 있지 않은 입력은 검증된 selection/evaluation contract가 존재할 때까지 `SummarizationPolicyUnavailable`로 fail closed하며, `max_sentences`는 기본값 없는 호환 인자만 유지합니다.
- transcript search의 Unicode-regex tokenization, summed term-frequency `score`, result ranking 및 recording/time tie-break를 production decision authority에서 제거했습니다. 원본 segment 저장/JSON loading은 유지하되 비어 있지 않은 tokenization/search는 검증된 retrieval/evaluation contract가 존재할 때까지 `SearchPolicyUnavailable`로 fail closed합니다.

### Fixed
- 단일·일괄 대상 크기 입력을 비웠을 때 이전 custom validity와 `aria-invalid` 상태를 즉시 초기화해 현재 필수 입력 상태를 정확히 전달합니다.
- 업로드 파일명의 경로 구분자를 정규화하여 POSIX에서도 Windows 형식의 클라이언트 경로가 일관된 basename으로 기록되도록 수정했습니다.
