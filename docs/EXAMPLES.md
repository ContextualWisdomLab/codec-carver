# Codec Carver — Examples

Copy-pasteable recipes for real situations. Codec Carver preserves audio: it
converts recordings to **FLAC** (lossless), and only falls back to **Opus** when
that is needed to fit each output under a target size. Originals are never
touched — generated files go to a separate output directory.

All commands run the CLI directly:

```bash
python3 media_shrinker.py <folder> [options]
```

> **Dry run is the default.** Without `--execute`, the tool only lists what it
> *would* convert and prints `TOTAL_SELECTED=<n>`. Add `--execute` to actually
> write files.

Sizes are given in **plain bytes** (`--target-bytes`, `--size-limit-bytes`).
Handy values:

| Target | Bytes |
| --- | --- |
| Discord (free) 25 MB | `25000000` |
| Gmail / most email 25 MB | `25000000` |
| Slack free 1 GB-ish per file, but keep small | `50000000` |
| Default target | `1900000000` (1.9 GB) |

---

## 1. Shrink a folder of lecture / meeting / podcast recordings

Preview first (dry run), then execute:

```bash
# See what would be selected — nothing is written
python3 media_shrinker.py ~/Recordings

# Actually convert
python3 media_shrinker.py ~/Recordings --execute
```

Outputs land in `~/Recordings/under_2gb/` and a JSON summary is written to
`~/Recordings/under_2gb/conversion_report.json`. The folder is scanned
recursively; every supported audio file is processed by default.

Put outputs somewhere else:

```bash
python3 media_shrinker.py ~/Recordings --execute \
  --output-dir ~/Recordings/shrunk \
  --report ~/Recordings/shrunk/report.json
```

## 2. Fit a target size (Discord, email)

The tool keeps each output **below `--target-bytes`**. To target Discord's
25 MB free-upload limit:

```bash
python3 media_shrinker.py ~/clips --execute --target-bytes 25000000
```

If a lossless FLAC would exceed the target, Codec Carver automatically
re-encodes that file to Opus to fit. If even Opus can't get under the target,
the generated file is discarded and the item is reported as `too_large`
(see Troubleshooting).

## 3. Force FLAC vs. let Opus fall back

- **Default:** lossless sources → FLAC; already-lossy sources (MP3, AAC, …) →
  Opus. FLAC is downgraded to Opus per-file only when needed to hit the target.
- **Force FLAC everywhere**, including lossy input, with `--flac-all`:

```bash
python3 media_shrinker.py ~/Recordings --execute --flac-all
```

Note: `--flac-all` still yields to the size target — if a forced-FLAC output
exceeds `--target-bytes`, it is replaced by an Opus encode.

## 4. Recordings longer than 4 hours (splitting)

Any source at or above `--max-duration-seconds` (default `14400` = 4 h) is split
into multiple outputs. The tool runs FFmpeg `silencedetect` and prefers to cut
inside a long silence before the boundary, so splits fall on natural pauses.

```bash
# Default 4-hour cap
python3 media_shrinker.py ~/day-long-recordings --execute

# Cut into ~2-hour pieces instead
python3 media_shrinker.py ~/day-long-recordings --execute \
  --max-duration-seconds 7200
```

Tune what counts as a usable silence for the split point:

```bash
python3 media_shrinker.py ~/recordings --execute \
  --silence-noise -30dB \
  --silence-min-duration-seconds 1.5
```

## 5. Dry run vs. execute

```bash
# Dry run (default): prints one DRY-RUN line per selected file + a count
python3 media_shrinker.py ~/Recordings

# Execute: converts and writes the JSON report
python3 media_shrinker.py ~/Recordings --execute
```

After `--execute`, the summary line reports
`converted=<n>  failed_or_too_large=<n>`, and the full per-file status is in the
report JSON.

## 6. Useful extras

```bash
# Only process files ABOVE the size limit (default also converts smaller ones)
python3 media_shrinker.py ~/Recordings --execute --over-limit-only

# Change the "large file" threshold used for selection (bytes)
python3 media_shrinker.py ~/Recordings --execute --size-limit-bytes 500000000

# Skip generated/working folders (repeatable)
python3 media_shrinker.py ~/Recordings --execute \
  --exclude-dir-prefix split_over --exclude-dir-prefix under_2gb

# Parallelism: 2 concurrent ffmpeg jobs, let ffmpeg pick its own threads
python3 media_shrinker.py ~/Recordings --execute --workers 2 --ffmpeg-threads 0

# Overwrite existing generated outputs instead of skipping them
python3 media_shrinker.py ~/Recordings --execute --overwrite

# macOS: materialize iCloud-offloaded files before reading (uses brctl)
python3 media_shrinker.py ~/Recordings --execute --download-icloud
```

---

## Troubleshooting

**`ffmpeg not found: ffmpeg`** — FFmpeg (and `ffprobe`) must be installed and on
your `PATH`. Install it, e.g. `brew install ffmpeg` (macOS) or
`sudo apt install ffmpeg` (Debian/Ubuntu). If it lives somewhere non-standard,
point the tool at it:

```bash
python3 media_shrinker.py ~/Recordings --execute \
  --ffmpeg /opt/homebrew/bin/ffmpeg --ffprobe /opt/homebrew/bin/ffprobe
```

**`... has no audio stream`** — the file has no audio track to preserve, so it
can't be converted. This is expected for silent/video-only files; skip it.

**`... contains video; this tool is configured for audio preservation`** — Codec
Carver preserves audio only and rejects sources that carry a video track (e.g.
a screen-recording `.mp4` with picture). Extract the audio first, then run the
tool on the audio file.

**Output too large (`too_large` in the report)** — even after falling back to
Opus, the encode couldn't fit under `--target-bytes`, so the generated file was
discarded. This usually means the target is smaller than what the source's
duration allows at a reasonable bitrate. Either raise `--target-bytes`, or split
the recording into shorter pieces with a lower `--max-duration-seconds` so each
segment fits.

**Nothing gets converted** — remember dry run is the default; add `--execute`.
Also check that files are above/below your `--size-limit-bytes` selection and
that they aren't inside an excluded (`--exclude-dir-prefix`) or output directory.

### Report statuses

The JSON report records one status per generated segment:

| Status | Meaning |
| --- | --- |
| `converted` | Written successfully, under target and duration limits |
| `skipped_existing` | A valid output already existed |
| `too_large` | Output stayed above `--target-bytes` (discarded) |
| `too_long` | Output segment still at/above `--max-duration-seconds` (discarded) |
| `duration_mismatch` | Output length didn't match the planned segment (discarded) |
| `failed` | Conversion raised an error (e.g. no audio, contains video) |
