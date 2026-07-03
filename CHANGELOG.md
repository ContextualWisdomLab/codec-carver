# CHANGELOG

## [Unreleased]
- `media_shrinker.py`에서 `splitlines()` 대신 `re.finditer()`를 사용하도록 최적화하여 대용량 `ffmpeg` 로그 분석 시 메모리 할당을 줄였습니다. (성능 향상: O(N)에서 O(1) 메모리 사용)
