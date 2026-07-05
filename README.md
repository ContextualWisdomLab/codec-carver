# Codec Carver

Python CLI for carving long recordings into metadata-preserved FLAC/Opus files.

Convert supported audio recordings to FLAC or, only when needed to fit each output under a target size, high-bitrate Opus. The tool preserves originals and writes generated files to a separate output directory. Each generated output is kept below the configured size target and below four hours; longer sources are split at long silence intervals when possible.

## Verified command for this folder

Run from `media_shrink_tool/`:

```bash
python3 media_shrinker.py .. \
  --execute \
  --download-icloud \
  --include-under-limit \
  --flac-all \
  --exclude-dir-prefix split_over \
  --max-duration-seconds 14400 \
  --workers 2 \
  --ffmpeg-threads 0 \
  --output-dir under_2gb \
  --report under_2gb/conversion_report.json
```

Outputs are written under `../under_2gb/`. Existing generated output directories and `split_over*` directories should be excluded from scans to avoid reconverting generated media. Files under 2GB are included by default; use `--over-limit-only` only when intentionally processing oversized sources exclusively.

## Duration splitting

- `--max-duration-seconds 14400` keeps every generated file below four hours.
- When a source is at or above that duration, the tool runs FFmpeg `silencedetect` and prefers the latest safe point inside a long silence before the four-hour boundary.
- If no suitable silence is detected before a boundary, the tool hard-splits just under the configured maximum so the duration rule is still enforced.
- Split outputs are named with part suffixes, for example `meeting.wav.part0001.flac`, `meeting.wav.part0002.flac`.
- Tune silence detection with `--silence-noise` and `--silence-min-duration-seconds` when recordings need stricter or looser silence boundaries.

## Output format

- `--format auto` (default) keeps the original behaviour: FLAC for lossless (or `--flac-all`) input, high-bitrate Opus otherwise.
- `--format flac` / `--format opus` force that codec.
- `--format aac` (`.m4a`) and `--format mp3` produce broadly-compatible lossy output fitted to the target size — useful for players/devices that don't handle FLAC or Opus.

## Safety notes

- Source files selected by the scan are protected from deletion or overwrite; keep `--output-dir` as a generated-only directory so excluded originals are never mistaken for stale generated outputs.
- Generated output names include the original filename and suffix, for example `clip.wav.flac` and `clip.m4a.flac`, so same-stem inputs cannot collide during parallel conversion.
- For lossy sources, `--flac-all` first creates FLAC to avoid additional loss; if that output exceeds the target size, the generated FLAC is removed and a high-bitrate Opus output is created instead.
- Filesystem metadata preservation is best effort: permissions, nanosecond access/modified times, extended attributes, and macOS creation date are copied when the operating system allows it.
- Video-containing files with supported container extensions are rejected; this tool preserves audio recordings only.
- For real media runs, keep `--output-dir` as a generated-only directory such as `under_2gb` and avoid `--overwrite` unless that directory contains no original source files.

## Verification

```bash
python3 -m unittest discover -s tests
python3 -m py_compile media_shrinker.py
```
