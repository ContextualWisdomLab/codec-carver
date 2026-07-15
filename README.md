# Codec Carver

Python CLI for carving long recordings into metadata-preserved FLAC/Opus files.

Convert supported audio recordings to FLAC or, only when needed to fit each output under a target size, high-bitrate Opus. The tool preserves originals and writes generated files to a separate output directory. Each generated output is kept below the configured size target and below four hours; longer sources are split at long silence intervals when possible.

## Install

Requires Python 3.10+ and `ffmpeg`/`ffprobe` on `PATH`.

```bash
pip install -e .            # CLI core (stdlib only)
pip install -e ".[web]"     # + FastAPI upload service
pip install -e ".[mcp]"     # + MCP server
```

This installs the `codec-carver` console command:

```bash
codec-carver /path/to/recordings --execute --output-dir under_2gb
```

## Web service (Docker)

```bash
docker build -t codec-carver .
docker run -p 8000:8000 codec-carver   # upload UI at http://localhost:8000
```

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

## Config file for repeat workflows

Instead of re-typing long flag sets, store them once in a `.codec-carver.json` file in the scan root (checked first) or the current working directory:

```json
{
    "flac_all": true,
    "exclude_dir_prefix": ["split_over"],
    "max_duration_seconds": 14400,
    "workers": 2,
    "output_dir": "under_2gb"
}
```

Then repeat runs collapse to `python3 media_shrinker.py .. --execute --download-icloud`.

- Keys map 1:1 to CLI options with dashes replaced by underscores (`--target-bytes` becomes `target_bytes`).
- Explicit CLI flags always override config values; without a config file, behavior is identical to a plain invocation.
- `root` and `--execute` are intentionally not configurable: the config file is discovered via the scan root, and a config file must never silently turn a dry run into a real conversion.
- Unknown keys, wrong value types, and malformed JSON abort with a clear error listing the valid keys.
- JSON is used instead of TOML because the stdlib TOML parser requires Python 3.11+, while this project also supports Python 3.10.

## Duration splitting

- `--max-duration-seconds 14400` keeps every generated file below four hours.
- When a source is at or above that duration, the tool runs FFmpeg `silencedetect` and prefers the latest safe point inside a long silence before the four-hour boundary.
- If no suitable silence is detected before a boundary, the tool hard-splits just under the configured maximum so the duration rule is still enforced.
- Split outputs are named with part suffixes, for example `meeting.wav.part0001.flac`, `meeting.wav.part0002.flac`.
- Tune silence detection with `--silence-noise` and `--silence-min-duration-seconds` when recordings need stricter or looser silence boundaries.

## Metadata tagging

- `--set-title`, `--set-artist`, `--set-album`, and `--set-comment` stamp the corresponding tags on every generated output, so archived files stay searchable in players and music libraries.
- Generated commands already copy source metadata with `-map_metadata 0`; the `--set-*` values are injected after it, so each provided key overrides that specific source tag while all other source metadata is preserved (standard ffmpeg semantics).
- When none of the `--set-*` options are passed, generated ffmpeg commands are byte-identical to the untagged behavior.
- Values are passed to ffmpeg as single argv items without a shell, so spaces, quotes, and other special characters are safe as given.

```bash
python3 media_shrinker.py .. --execute \
  --set-album "Board Meetings 2026" \
  --set-comment "archived by codec-carver"
```

## Output format

- `--format auto` (default) keeps the original behaviour: FLAC for lossless (or `--flac-all`) input, high-bitrate Opus otherwise.
- `--format flac` / `--format opus` force that codec.
- `--format aac` (`.m4a`) and `--format mp3` produce broadly-compatible lossy output fitted to the target size — useful for players/devices that don't handle FLAC or Opus.

## Transcription (optional)

Turn each shrunk recording into searchable text. With `--transcribe`, a text and
JSON transcript sidecar is written next to every generated audio file
(`recording.wav.flac` → `recording.wav.flac.txt` / `.json`):

```bash
python3 media_shrinker.py .. --execute --output-dir under_2gb --transcribe
```

Transcription is opt-in and uses [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper),
imported lazily. Install it to enable the feature:

```bash
pip install faster-whisper        # then pass --transcribe
```

If it is not installed, conversion runs normally and transcription is skipped
with a `TRANSCRIBE_SKIP` notice. A failing transcript never aborts a conversion.
Choose a model with `--transcribe-model` (default `base`).

## GPU audio-library curation (Python API + Rust backend)

The audio-library workflow standardizes recording names from recording time,
known location, transcript content, and SHA-256; parses Sony `.tmk` markers; and
quarantines exact duplicates. Byte-heavy scanning and mutations run in Rust,
while Python keeps one GPU Whisper model loaded for the batch. Ollama is never
used and GPU mode does not fall back to CPU.

```bash
cargo build --release --manifest-path rust-core/Cargo.toml
python3.12 -m venv .venv
.venv/bin/pip install -e ".[transcribe-mlx]"  # Apple Silicon / Metal

codec-carver-library /path/to/recordings inventory --threads 4
codec-carver-library /path/to/recordings hydrate-tmk --workers 4
codec-carver-library /path/to/recordings stream-transcribe --accelerator mlx
# Add --word-timestamps only when word-level audit evidence is required.
codec-carver-library /path/to/recordings plan
# When iCloud has not supplied every source, mutate only fully ready recordings
# and preserve the unresolved paths as explicit deferred evidence.
codec-carver-library /path/to/recordings plan --defer-unready
codec-carver-library /path/to/recordings apply          # validation only
codec-carver-library /path/to/recordings apply --execute
```

`stream-transcribe` is the low-disk iCloud mode: Rust streams one remote file to
system scratch while calculating SHA-256, Metal/CUDA transcribes that local
stage, and Python atomically checkpoints before removing the stage. Already
local files stay local. Run `hydrate-tmk` first when iCloud holds Sony sidecars:
it reads the tiny TMK files concurrently, checkpoints each SHA-256 and marker
summary, and backfills any existing transcript sidecars. A later dataless flag
does not cause the same TMK to be downloaded again. Four workers and a 60-second
per-file timeout are the defaults because higher iCloud File Provider concurrency
can delay every placeholder; rerunning resumes only unresolved sidecars.
`stream-transcribe` never blocks an audio recording on an unresolved TMK: it uses
hydrated markers when present and records `tmk_error` evidence otherwise.
On macOS, Rust requests every dataless item through Foundation's supported
`FileManager.startDownloadingUbiquitousItem` API, then coordinates the read with
`NSFileCoordinator` and performs the single-pass copy-and-hash inside the
coordinated accessor. The coordinator is required by current File Provider
domains to keep `isDownloadRequested`/`isDownloading` active; already-local
files keep the direct fast path. The implementation does not depend on the
undocumented `brctl download` command. If Finder and the coordinated native
request both remain at zero bytes, inspect File Provider with
`fileproviderctl check` before an operator-approved repair.
After a durable transcript checkpoint, Rust also releases the local source
blocks through `FileManager.evictUbiquitousItem`; no `brctl evict` subprocess is
used. Eviction is optional cleanup, so a native eviction error is recorded in
`eviction_failures` without converting a completed transcription into a failure.
At startup it samples the live macOS dataless flag and drains currently local
audio before remote placeholders, keeping the GPU fed while iCloud catches up.
Rust stage monitoring resets its deadline whenever the partial grows; the
default 120-second stall limit skips only placeholders making no byte progress,
not large files that are actively copying and hashing. File Provider can expose
the logical source size before any bytes are readable; Rust rejects such a
premature short/empty EOF, and Python retries it only until the same bounded
zero-progress deadline instead of accepting the empty-file SHA-256.
Planning rejects recordings without SHA-256 or transcript evidence by default.
`--defer-unready` keeps those paths unchanged and lists them in
`deferred_paths`, allowing verified subsets to proceed without inventing a
placeholder description.
Every rescan archives the previous inventory by its SHA-256. If iCloud evicts a
previously hashed recording, same-path/same-size evidence, executed mutation
journals, and transcript sidecars restore its full hash with an explicit
`sha256_source` instead of silently discarding identity.
Transcripts are keyed by the full SHA-256 under
`.codec-carver/transcripts/`, so exact copies are inferred only once. Ultra-short
low-confidence words remain auditable in JSON but do not enter standardized
filenames. For long meetings, filename descriptions come from a deterministic
corpus-central phrase rather than only the opening segments: per-segment topic
frequency, Korean particle normalization, and repetition/stock-phrase filters
keep the name compact and representative without another model call. Once a
name has a valid recording timestamp, known location, and matching SHA prefix,
later extractor improvements preserve it instead of renaming the library again.
Duplicate files move to the recoverable
`.codec-carver/quarantine/exact-duplicates/` tree; no irreversible deletion is
performed by default.

The importable API is `audio_library.AudioLibrary`. The architecture, evidence
precedence, filename contract, and primary research/standards sources are in
[`docs/architecture/gpu-transcription-rust-backend.md`](docs/architecture/gpu-transcription-rust-backend.md).

## Safety notes

- Source files selected by the scan are protected from deletion or overwrite; keep `--output-dir` as a generated-only directory so excluded originals are never mistaken for stale generated outputs.
- Generated output names include the original filename and suffix, for example `clip.wav.flac` and `clip.m4a.flac`, so same-stem inputs cannot collide during parallel conversion.
- For lossy sources, `--flac-all` first creates FLAC to avoid additional loss; if that output exceeds the target size, the generated FLAC is removed and a high-bitrate Opus output is created instead.
- Filesystem metadata preservation is best effort: permissions, nanosecond access/modified times, extended attributes, and macOS creation date are copied when the operating system allows it.
- Video-containing files with supported container extensions are rejected unless
  `--allow-video` is set to extract their audio track.
- For real media runs, keep `--output-dir` as a generated-only directory such as `under_2gb` and avoid `--overwrite` unless that directory contains no original source files.

## Verification

```bash
python3 -m unittest discover -s tests
python3 -m py_compile media_shrinker.py
```
