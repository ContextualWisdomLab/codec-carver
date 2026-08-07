# Changelog

## [Unreleased]

### Added
- 다중 파일 업로드 선택 시 즉각적인 파일 개수 피드백 및 제한 초과 경고 메시지 추가
- 일괄 업로드 폼에 대상 바이트 프리셋 버튼과 총 파일 크기 미리보기를 추가하여 사용성을 개선했습니다.

## [0.2.0] - 2026-08-07

### Added
- Overlapping long-form transcript chunks can now be reconciled into stable,
  recording-global anonymous speaker labels with cannot-link constraints.
- Added boundary-duplicate removal that requires speaker, time, and normalized
  text agreement while retaining source-chunk provenance.
- Added first-class simultaneous-speaker representation and union-based speech
  and overlap metrics.
- Added deterministic JSON, Markdown, RTTM, SRT, WebVTT, SHA-256 manifest, and
  CRC-verified ZIP artifact output.
- Added the `codec-carver-speakers` CLI and a versioned JSON input schema.
- Added a de-identified 47-minute Korean meeting regression topology.
- Added an hourly commercial-readiness workflow that delegates PR reconciliation
  to the immutable central scheduler and uses NIM-only bounded OpenCode roles
  when the PR queue is empty.
- Added architecture, ADR, doctoring, standards, evaluation, and automation
  documentation.

### Changed
- Updated the default diarization adapter to
  `pyannote/speaker-diarization-community-1` and pyannote.audio 4 result
  semantics while retaining injected and legacy backends.
- Replaced quadratic sorted transcript/turn alignment with a prefix-maximum
  interval index and binary search.
- Corrected project URLs and expanded the product description for the
  ContextualWisdomLab organization.

### Quality
- Added 100% line and branch coverage gates for `diarize.py` and every
  `speaker_timeline*.py` module.
- Added deterministic corrupt-archive, Unicode, overlap, contradictory-link,
  real-world topology, CLI, schema, and performance regression tests.
