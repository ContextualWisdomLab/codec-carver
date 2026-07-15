# GPU transcription and Rust audio-library backend

## Context

Codec Carver now has two workloads with different performance characteristics:

1. Model inference needs Python integrations maintained by the MLX and
   faster-whisper projects.
2. Recursive discovery, SHA-256, Sony TMK parsing, duplicate grouping, and
   collision-safe filesystem mutations are byte-heavy systems work.

The audio-library path therefore uses a Python API over a Rust batch backend.
The existing conversion CLI remains compatible while this path becomes the
preferred interface for recording curation.

## Acceptance contract

- Every supported audio and TMK file has a full SHA-256 value when its bytes are
  locally available.
- A macOS iCloud `dataless` placeholder is reported, not opened indefinitely.
- Low-disk runs process one remote recording at a time. Rust streams the iCloud
  source into system scratch while hashing the same byte stream, GPU inference
  reads that local stage, and the stage is deleted after the checkpoint.
- Exact duplicates are grouped only by the full content hash. The earliest
  available recording time is retained on the group.
- Sony TMK markers such as `[00075:00.00]` are interpreted as minute-based
  offsets and joined to audio by directory and normalized stem.
- `hydrate-tmk` fetches unresolved iCloud TMK sidecars concurrently, atomically
  checkpoints each hash/marker result, and never refetches a sidecar whose
  metadata is already complete even if iCloud restores its dataless flag.
  Its four-worker, 60-second defaults bound File Provider backpressure; reruns
  select only sidecars still lacking a hash or marker count.
- `stream-transcribe` consumes only checkpointed TMK metadata. An unresolved
  sidecar is retained as `tmk_error` evidence and cannot block GPU audio work.
- Streaming order is based on the live macOS dataless flag rather than stale
  inventory state, so locally resident audio reaches the GPU before iCloud work.
- Python monitors the Rust PID-specific partial file. Its 120-second stage
  deadline resets on every size change, bounding a stuck File Provider without
  terminating a large source that is still copying and hashing normally.
- Mutation planning fails closed when SHA-256 or transcripts are unresolved;
  an explicit deferred mode changes only ready recordings and serializes every
  untouched source path instead of fabricating a transcript description.
- Rust parses standardized timestamps and optional location components
  idempotently. Python archives prior inventories and restores full SHA-256
  identity only from executed journals, matching transcript sidecars, or an
  unchanged prior path and byte size.
- Standard names use
  `YYYY-MM-DD_HH-MM-SS__location?__transcript-description__sha256-12.ext`.
- Mutations are dry-run by default. Execution rejects absolute/parent paths,
  missing sources, existing destinations, and duplicate destinations. A failed
  batch rolls completed moves back in reverse order.
- Exact duplicates leave the active library through a recoverable
  `.codec-carver/quarantine/exact-duplicates/<sha256>/...` move. Nothing is
  irreversibly deleted by the default workflow.
- GPU transcription never calls Ollama and never silently falls back to CPU.

## Runtime split

### Python API

`audio_library.AudioLibrary` owns model selection, persistent GPU model use,
transcript sidecars, deterministic description extraction, iCloud streaming
checkpoints, parallel one-time TMK hydration, and mutation-plan generation.

- Apple Silicon: `mlx-whisper` on the Metal GPU, defaulting to
  `mlx-community/whisper-large-v3-turbo-q4`.
- NVIDIA: `faster-whisper` on CUDA with FP16 compute.

MLX Whisper caches the loaded model within the process, so the library API keeps
one `GpuTranscriber` alive for the entire run.

Both backends disable previous-window conditioning to avoid repetition loops
and use greedy decoding (`temperature=0` on MLX, beam/best-of 1 on CUDA) to
avoid redundant search passes.
For throughput, word timestamps are opt-in (`--word-timestamps`). WAV headers
below 0.5 seconds skip model inference and receive a durable quality flag. When
word timestamps are enabled, an ultra-short segment below 0.5 seconds with mean
word probability below 0.25 remains in the JSON evidence with a
`low_confidence` flag but is excluded from usable text and filename descriptions.

### Rust backend

`rust-core/codec-carver-core` owns bounded-buffer SHA-256, parallel scans,
macOS dataless detection, filename/creation-time evidence, TMK decoding,
duplicate grouping, and guarded filesystem changes. A single-file `inspect`
command supports local single-file inspection. The `stage` command handles an
iCloud placeholder in one pass: it writes local system scratch and calculates
SHA-256 concurrently, verifies any existing staged content, and returns the
scratch path plus the original file record. A changed known hash stops
transcription.

## Evidence precedence

Recording time is selected in this order:

1. RFC 3339 timestamp embedded in a filename;
2. Sony compact `YYMMDD_HHMM` filename timestamp;
3. filesystem creation time;
4. filesystem modification time.

The manifest records `time_source` so weaker evidence is visible. Duplicate
groups carry the earliest timestamp found among byte-identical copies.

Location is retained only when it is present in the source filename/address.
The implementation does not reverse-geocode coordinates or invent a place.

## Durable local state

The library root contains a generated, excluded state directory:

```text
.codec-carver/
├── inventory.json
├── inventory-history/<inventory-sha256>.json
├── tmk-hydration-run.json
├── transcripts/<sha256>.json
├── transcripts/<sha256>.txt
├── mutation-plan.json
├── mutation-journal.json
└── quarantine/exact-duplicates/<sha256>/...
```

Transcripts are keyed by full SHA-256 so a renamed recording or duplicate copy
does not trigger a second inference run.

Large audio scratch is outside the iCloud library under the operating system
temporary directory. Only one recording is staged at a time, at least 512 MiB
of free-space headroom is required, and scratch deletion rejects paths outside
the library-specific staging root.

## Primary references

- Radford, A. et al. (2022), *Robust Speech Recognition via Large-Scale Weak
  Supervision*, arXiv:2212.04356. Repository copy:
  `docs/papers/2212.04356-whisper.pdf` (SHA-256
  `6337bde031b2f237547a977b022f831169a7e05b4d9047f29501166d83594566`).
- National Institute of Standards and Technology (2015), *Secure Hash Standard
  (SHS), FIPS PUB 180-4*. Repository copy:
  `docs/standards/NIST.FIPS.180-4.pdf` (SHA-256
  `0455b406d89648d20cbde375561e19c245b9815e894164c2670772e3d54deb82`).
- Apple ML Research, *MLX: An array framework for Apple silicon*, official
  implementation and software citation: <https://github.com/ml-explore/mlx>.
- Apple MLX Examples, *Speech recognition with Whisper in MLX*:
  <https://github.com/ml-explore/mlx-examples/tree/main/whisper>.
