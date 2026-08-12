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
  File Provider can leave that flag stale after the logical bytes are already
  readable; Rust therefore records whether staging used a materialized read,
  a secure direct read through the stale flag, or coordinated iCloud access.
- Low-disk runs process one remote recording at a time. Rust streams the iCloud
  source into system scratch while hashing the same byte stream, GPU inference
  reads that local stage, and the stage is deleted after the checkpoint.
- Exact duplicates are grouped only by the full content hash. The earliest
  available recording time is retained on the group.
- Sony TMK markers such as `[00075:00.00]` are interpreted as minute-based
  offsets and joined to audio by directory and normalized stem. Rust preserves
  the complete ordered offset vector, not only its count and final value.
- An audio record's `tmk_path` must resolve to an inventory record whose kind is
  exactly `tmk`; TMK records cannot themselves carry `tmk_path`. This typed
  relationship prevents a crafted sidecar link from authorizing an audio move.
- `hydrate-tmk` fetches unresolved iCloud TMK sidecars concurrently, atomically
  checkpoints each hash/marker result, and never refetches a sidecar whose
  metadata is already complete even if iCloud restores its dataless flag.
  Its four-worker, 60-second defaults bound File Provider backpressure; reruns
  select only sidecars still lacking a hash or marker count. A separate
  idempotent synchronization pass propagates already verified markers into
  linked transcript sidecars without rehashing them, and rejects transcript
  SHA-256 mismatches instead of overwriting foreign evidence.
- A transcript binds its primary TMK provenance with `tmk_path`, the
  content-verified `tmk_sha256`, and its ordered marker vector. Unverified
  sidecar identities never enter this field, and hydration repairs older
  transcript sidecars idempotently.
- `stream-transcribe` consumes only checkpointed TMK metadata. An unresolved
  sidecar is retained as `tmk_error` evidence and cannot block GPU audio work.
- On MLX, verified internal TMK offsets divide a long recording into bounded
  decode ranges with one-second overlap. The persistent pinned model processes
  those ranges serially on Metal; segment midpoint ownership removes overlap
  duplicates and converts timestamps back to the recording-global timeline.
- If a recording exceeds ten minutes without usable TMK offsets, MLX creates
  deterministic five-minute ranges instead. Those ranges use the same overlap,
  global timestamp restoration, and owner-only resumable checkpoints; TMK
  ranges remain authoritative whenever they exist.
- Streaming order is based on the live macOS dataless flag rather than stale
  inventory state, so locally resident audio reaches the GPU before iCloud work.
- Before a dataless stage, Rust first tries the same component-by-component,
  `O_NOFOLLOW` descriptor read used for a local source. This avoids a
  `realpath(3)`/File Provider wait when the dataless bit is stale and accepts
  the path only after the complete advertised byte count is copied. The stage
  JSON exposes `read_mode=direct_read_stale_dataless_flag` for this case. If
  that read is unavailable or incomplete, Rust calls Foundation's supported
  `FileManager.startDownloadingUbiquitousItem` API and coordinates the read with
  `NSFileCoordinator`; the stage then reports
  `read_mode=coordinated_icloud`. This does not rely on the undocumented and
  ineffective-on-current-macOS `brctl download` command; materialized files
  retain the direct fast path.
- The macOS `fileproviderctl evaluate` probe is also bounded to ten seconds and
  requires a successful child exit plus complete recognized flags before direct
  reading is eligible. A spawn failure, timeout, wait/output error, abnormal
  exit, non-zero status, or malformed flag set remains unknown provider state.
  Unknown state is never reclassified from filesystem metadata and always fails
  closed into the Foundation-coordinated path; it cannot turn a stale dataless
  read into an unbounded wait.
- Python monitors the Rust PID-specific partial file. Its 420-second stall
  deadline resets on every size change, bounding a stuck File Provider without
  terminating a large source that is still copying and hashing normally. A
  separate absolute deadline at four times the stall setting bounds repeated
  premature-EOF retries even if reported byte progress never stops.
- Python preserves `subprocess.TimeoutExpired` compatibility with a typed
  `StageTimeoutError`. Batch checkpoints include the stable
  `stage_source_stalled` code, timeout, maximum observed staged bytes, and a
  retryable flag, while the human message names FileProvider/CloudKit as the
  materialization layer to inspect.
- A failed streaming stage refreshes only the recording's live
  `materialized` flag from the current File Provider state. It never treats a
  prior SHA as newly verified; content evidence can become current again only
  after a successful Rust stage and byte/hash check.
- After the transcript and inventory checkpoint are durable, the Rust `evict`
  command calls Foundation's `FileManager.evictUbiquitousItem` directly. The
  Python API records a native eviction problem separately in `eviction_failures`;
  optional low-disk cleanup cannot erase or fail completed transcription work.
- Rust compares the staged byte count with the source logical size before
  publishing a SHA-256. A premature File Provider EOF is reported as
  `STAGE_SOURCE_NOT_READY`; Python retries that condition only while bytes make
  progress or until the same stall deadline expires.
- Mutation planning fails closed when SHA-256 or transcripts are unresolved;
  an explicit deferred mode changes only ready recordings and serializes every
  untouched source path instead of fabricating a transcript description.
- If a readable source still reports the macOS File Provider `dataless` bit,
  mutation planning performs one fresh Rust stage into private scratch and
  verifies the complete staged SHA-256 before authorizing a rename or quarantine.
  The short-lived proof descriptor is closed immediately; it never rewrites the
  inventory's live `materialized` flag and does not replace Rust's source recheck
  during apply. A missing source, placeholder-only hash, provider stall, or
  staged-byte mismatch remains deferred.
- Rust parses standardized timestamps and optional location components
  idempotently. Python archives prior inventories. An executed mutation journal
  restores SHA-256 identity continuity because Rust checked the source before
  the move, but that restored value is still an unverified hint until current
  bytes are opened and hashed again. The same rule applies to a matching
  transcript sidecar or unchanged prior path and byte size.
- Standard names use
  `YYYY-MM-DD_HH-MM-SS__location?__transcript-description__sha256-12.ext`.
- Long-transcript descriptions can use a pinned local Gemma model to extract a
  central idea, outcome, confidence, and cited transcript segments before a
  second pass forms the title. Generic keyword lists and low-confidence analyses
  are rejected. Evidence IDs must be anchored transcript labels, every claim
  term must occur in the cited segments, and every title term must be composed
  from transcript terms rather than model-authored claims. Deterministic
  extractive topic density remains the failure-safe.
- Whisper-segment control whitespace is flattened before Python assigns
  evidence labels. Labeled evidence must be the exact contiguous sequence
  `S001`, `S002`, and so on, and title grounding preserves source token
  boundaries rather than accepting arbitrary cross-token substrings.
- Every existing name is compared with the complete timestamp, known-location,
  transcript-derived description, extension, and SHA suffix recomputed from
  current evidence. Drift is always reported, but changing an already-standard
  path requires explicit refresh authorization.
- Mutations are dry-run by default. Python recomputes the exact authorized
  operation list from the current inventory and transcript evidence; Rust then
  rehashes every audio and TMK source before any move. Execution rejects
  hashless, changed, unlisted, absolute/parent, missing, existing-destination,
  and duplicate-destination operations. Rust holds an exclusive lock on the
  library root throughout validation and execution, traverses and creates
  parents relative to no-follow directory descriptors, and uses atomic
  no-overwrite descriptor-relative rename primitives. A failed batch rolls
  completed moves back in reverse order through the same guarded path. Python
  permits execution only through the concrete descriptor-safe `RustBackend`.
- Exact duplicates leave the active library through a recoverable
  `.codec-carver/quarantine/exact-duplicates/<sha256>/...` move. Nothing is
  irreversibly deleted by the default workflow.
- GPU transcription never calls Ollama and never silently falls back to CPU.
- Every materialized recording is rehashed before a cache hit, GPU call, or new
  mutation. Unverified placeholder evidence cannot form an exact-duplicate
  group or a new rename/quarantine operation.
- A standardized TMK filename may carry the linked audio SHA for pairing; the
  TMK's own SHA-256 is populated only from TMK bytes verified by Rust.
- Inventory paths, TMK links, digest-keyed transcript paths, and mutation paths
  are validated beneath the canonical library root. Symlinks and absolute,
  parent, Windows-drive, UNC, or malformed SHA values fail closed.
- `.codec-carver` and transcript directories are owner-only; JSON/text sidecars
  are mode `0600`. The state directory and unpredictable per-process scratch
  directory must be real directories rather than symlinks. Every transcript
  read opens the final SHA sidecar with `O_NOFOLLOW`; a symlink or non-regular
  entry is unavailable evidence and is never dereferenced.
- Every private state-directory component is created and opened relative to the
  preceding descriptor with `mkdirat`/`openat`, `O_DIRECTORY`, and
  `O_NOFOLLOW`. Intermediate ancestor swaps therefore cannot redirect durable
  state writes.
- Scratch cleanup unlinks a direct regular-file child relative to a no-follow
  directory descriptor, avoiding pathname containment check/use races.
- Before staged audio or TMK metadata is consumed, Python opens the reported
  direct scratch child relative to that descriptor with `O_NOFOLLOW` and
  requires exactly one link. Python confirms the name still identifies the
  opened inode, unlinks it, hashes the now-anonymous descriptor, and requires
  its real byte count and SHA-256 to match the backend record and any known
  inventory digest. The optional Rust `read_mode` is validated and copied to
  the transcript's `source.stage_read_mode` evidence; it does not overwrite
  the provider's live materialization flag in the inventory. MLX decoding and
  CUDA transcription consume that retained descriptor, so hardlinks and
  pathname replacement cannot change inference input.
- Rust opens every materialized audio path component with no-follow descriptors
  and the GPU consumes only a private copy hashed from that opened descriptor.
  Symlink swaps cannot redirect the GPU read after validation.
- Rust returns inventory and apply results over stdout. Python owns all durable
  state commits through descriptor-relative atomic replacement, never follows a
  final-name symlink, and recoverably quarantines partial or schema-invalid
  mutation journals instead of blocking future inventory runs.
  The standalone Rust `inventory --output` option is an explicitly opt-in
  diagnostic path and uses the same descriptor-relative, no-follow atomic
  writer; the Python API never supplies that option, so normal library state
  remains owned by Python.
- The Rust executable comes only from an integrity-pinned explicit path or a
  repository build and is checked for owner, mode, symlink, and SHA-256 drift.
  Python copies the exact bytes from a stable, no-follow source descriptor into
  a sealed owner-only execution inode and binds every Rust launch to that
  independent snapshot, so a later source-path replacement cannot redirect
  execution. `ffprobe` and MLX decoding `ffmpeg` come only from fixed approved
  system roots; ambient environment variables cannot change those allowlists.
  MLX receives the decoded waveform instead of a path, preventing
  its dependency from launching a bare PATH-resolved ffmpeg. Rust, ffprobe, and
  ffmpeg subprocesses receive a minimal environment without dynamic-loader
  injection variables. MLX-VLM preflight runs Python in isolated mode from the
  interpreter directory and verifies the resolved package is beneath that
  interpreter's prefix before any model import. Executed mutation-journal hashes
  remain unverified identity hints until current bytes are hashed again.
- The macOS GPU bootstrap sets a fixed system `PATH` before its first helper
  invocation, uses fixed absolute paths for native utilities, and executes `uv`
  only from a private runtime snapshot whose bytes match a reviewed SHA-256.
- Malformed-journal quarantine creates and opens `recovery` and
  `malformed-journals` relative to one verified state-directory descriptor.
  Each component uses no-follow directory operations, so an intermediate
  symlink cannot relocate state outside the library.

## Runtime split

### Python API

`audio_library.AudioLibrary` owns model selection, persistent GPU model use,
transcript sidecars, semantic and deterministic description extraction, iCloud
streaming checkpoints, parallel one-time TMK hydration, and mutation-plan
generation.

- Apple Silicon: `mlx-whisper` on the Metal GPU, fixed to
  `mlx-community/whisper-large-v3-turbo-q4` revision
  `660c343bbf4e52ac257f0b7d952e5388e6f93bef`.
- Apple Silicon filename topics: `mlx-vlm` with the pinned 4-bit Gemma 4 E2B
  instruct model. It runs after transcription as a separate batch so Whisper
  and Gemma do not need to occupy unified memory simultaneously.
  The runtime uses the released `mlx-vlm==0.6.4` wheel plus a narrow compatibility
  shim for the already-converted Gemma 4 audio-weight layout fixed upstream in
  PR #931 (`bc3461b13a636d7cb8213b0008d885a9965f1e69`).
- NVIDIA: `faster-whisper` on CUDA with FP16 compute, fixed to
  `dropbox-dash/faster-whisper-large-v3-turbo` revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`.

MLX Whisper caches the loaded model within the process, so the library API keeps
one `GpuTranscriber` alive for the entire run.

After Finder materializes a known placeholder, `inventory --path` refreshes only
the named baseline records through Rust `inspect` and atomically merges their
content hashes and TMK metadata in Python. A selected refresh never starts a
full tree walk, so repairing one recording cannot accidentally hydrate unrelated
multi-gigabyte iCloud files.
Before that refresh, `materialize --path` queues a native Foundation download
for each explicitly selected dataless audio/TMK path and returns without opening
or hashing the source. Its persisted result distinguishes an accepted request,
an already-local file, the current post-request dataless state, and a request
failure; accepting a request is never treated as proof that the bytes arrived.
For File Provider roots, `--state-dir` places mutable manifests, transcripts,
plans, and journals in a separate owner-only local directory. Recording and TMK
mutations remain rooted in the selected library, including SHA-addressed
quarantine destinations, while evidence state is insulated from cloud-version
rollback races.

For long Sony recordings, the Rust-provided TMK vector bounds each MLX waveform
decode instead of materializing the entire recording as one float array. This
reduces peak memory without reloading the model or switching away from GPU
inference; overlap protects speech at marker boundaries. Long recordings
without a usable TMK vector use deterministic five-minute boundaries, so an
interruption resumes from the last durable chunk instead of retranscribing the
whole file.

Both backends disable previous-window conditioning to avoid repetition loops
and use greedy decoding (`temperature=0` on MLX, beam/best-of 1 on CUDA) to
avoid redundant search passes.
For throughput, word timestamps are opt-in (`--word-timestamps`). WAV headers
below 0.5 seconds skip model inference and receive a durable quality flag. When
word timestamps are enabled, an ultra-short segment below 0.5 seconds with mean
word probability below 0.25 remains in the JSON evidence with a
`low_confidence` flag but is excluded from usable text and filename descriptions.
SHA identity alone is not sufficient for cache reuse: the sidecar must also
match the selected accelerator, allowlisted model, immutable model revision,
and requested language. A caller requesting word timestamps requires a cache
that recorded them, while a timestamped cache remains a valid evidence superset
for a caller that does not require them. Legacy sidecars without this pinned
runtime identity are retranscribed rather than silently reused.
The quality gate also receives the recording duration from the GPU adapter. A
result of at least 120 seconds in which the same non-acknowledgement fragment
appears at least twice, dominates a set with at most one trusted segment per 30
seconds, and supplies fewer than 20 lexical tokens is classified as
repetitive/background audio unless a sustained,
lexically diverse contextual run exists. This prevents isolated decoder text
over non-speech or background-media intervals from becoming an authoritative
meeting title while retaining every raw segment for audit. This conservative
false-positive filter follows the documented long-form/non-speech hallucination
risk in Yan et al. (IWSLT 2024) and the separate false-positive filtering
architecture evaluated by Bondarenko et al. (NAACL 2025).

The optional `describe` phase treats transcript text as escaped JSON data,
reserves part of its at-most-48-segment sample for problem, decision, and
purpose cues, including input simplification, incentives, counts, information
quality, use, empathy, benefits, and field interviews, and uses greedy
generation. It first requires a central idea,
concrete outcome, confidence, and valid segment IDs, then runs a separate title
pass so tools and frequent nouns do not displace the recording's actual
purpose. Explicit conclusion cues reserve mandatory evidence, and their exact
IDs plus neighboring context are carried through every model-repair pass.
Explicit means-to-purpose clauses such as `그래야` cannot be reduced to generic
workflow status. If the small model repeats an invalid repair, a deterministic
fallback may retain only concrete purpose words from its cited transcript lines
or join literal conclusion clauses, then rerun the same transcript-grounding
checks. A
deterministic scorer expands the evidence set until every claim term is
covered, generic-only titles and low confidence are rejected, and the complete
audit context is stored beside the title. Only anchored `[S###]` lines establish
segment identity. Central-idea and outcome terms are checked against those
cited lines, while title terms are checked directly against the transcript;
model-authored analysis cannot become its own grounding source. Whisper segment
newlines are flattened before labels are assigned, labels must remain
contiguous from `S001`, and compound title validation consumes complete source
terms without crossing token boundaries. Planning always compares the complete
current expected name and reports `description_drift_paths` independently of
authorization. `plan --refresh-standardized-path` authorizes reviewed paths;
`plan --refresh-description-drift` authorizes all detected drift. Dataless and
SHA-unverified authorized paths are reported as deferred and never mutate. The
portable filename budget is also semantic: an evidence-backed title is rejected
when NFD UTF-8 fitting would truncate it, rather than silently changing the
reviewed claim. The only accepted
model identifier and immutable Hub revision are
compiled in, tokenizer `trust_remote_code` is forced off, and old validation
versions are regenerated rather than relabeled. No Ollama server is used and
transcript text is not sent to a hosted inference API. A failed semantic
analysis is checkpointed as an explicit deferral; mutation planning cannot
silently replace it with the deterministic keyword fallback.

`AudioLibrary.review_description()` and the `review-description` CLI are the
evidence-preserving correction boundary for a reviewer who has inspected more
context than the bounded model sample. The API requires a content-verified
inventory record, an MLX transcript at a pinned model revision, and word
timestamps. It sorts and de-duplicates two to 64 one-based source segment IDs,
copies each segment's exact text and time range into a separate review-evidence
object, and validates every central-idea, outcome, and title term against that
bounded evidence. It does not rewrite the raw transcript. Korean grammatical
particles may join a filename clause only when at least three semantic terms in
that same token are transcript-derived; this permits a reviewed thesis rather
than forcing another noun list without admitting an unsupported claim.
Incomplete connective endings and deictic observations without an actionable
decision are rejected. A successful review replaces stale automatic title
fields atomically and records its source segment IDs, transcription
model/revision, and review time in private state.

### Rust backend

`rust-core/codec-carver-core` owns bounded-buffer SHA-256, parallel scans,
macOS dataless detection, filename/creation-time evidence, TMK decoding,
kind-separated audio/TMK duplicate grouping, and guarded filesystem changes.
The inventory keeps `duplicate_groups` for audio and `tmk_duplicate_groups` for
TMK sidecars separate; only current, content-verified bytes may enter either
group, so a stale File Provider SHA hint remains evidence but never authorizes
quarantine. A single-file `inspect`
command supports local single-file inspection. The `materialize` command
validates one regular, non-symlink library child and queues Foundation's native
iCloud download without waiting. The `stage` command first probes the source
through the component-by-component `openat`/`O_NOFOLLOW` path without
canonicalizing the File Provider file itself. A complete read is copied to
local scratch and hashed in one pass even when the provider's dataless bit is
stale; otherwise Foundation materialization and `NSFileCoordinator` provide the
coordinated path. The stage JSON returns the scratch path, source record, and
the read mode used. The `evict` command releases local iCloud blocks with Foundation
rather than a shell utility. A changed known hash stops transcription. Mutation
execution opens and locks the library root, reopens and hashes each source
through `openat`, traverses destination parents without following symlinks, and
uses macOS `renameatx_np(RENAME_EXCL)` or Linux
`renameat2(RENAME_NOREPLACE)`; rollback follows the same descriptor-relative
route. The Python API rejects mutation execution through mocks, wrappers, or
other injected backends, so path-name semantics cannot replace this Rust
boundary. The public Python `inspect`, `stage`, `materialize`, and `evict`
methods also reject absolute, parent, non-portable, and symlink-component paths
before constructing
native argv; Rust repeats its own descriptor-relative validation.

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
├── recovery/malformed-journals/*.json
└── quarantine/exact-duplicates/<sha256>/...
```

Transcripts are keyed by full SHA-256 so a renamed recording or duplicate copy
does not trigger a second inference run. The directory is `0700` and every
sidecar is `0600` because transcripts can contain sensitive conversations.
Consumers validate the embedded transcript SHA against the inventory record
before cache reuse, title planning, metadata backfill, or reconciliation; a
foreign sidecar is retried, rejected, or explicitly deferred rather than used.
Inventory and mutation backends return JSON to Python over stdout; only Python
persists these files with descriptor-relative atomic replacement. A malformed
journal is preserved in the recovery tree with a digest-bearing name and a
`state_recovery_events` entry before inventory continues.

Large audio scratch is outside the iCloud library in an unpredictable,
owner-only directory created directly under the resolved operating-system
temporary root. The bounded prefetch byte limit controls concurrent logical
size, at least 512 MiB of free-space headroom is required, and descriptor-based
scratch deletion accepts only direct regular-file children. A backend-reported
stage becomes usable only after Python has independently hashed that no-follow
child descriptor and matched its actual size and digest. Before hashing it
rejects any child with more than one hardlink and unlinks the identity-checked
name, then hands the retained anonymous descriptor directly to the media
decoder or CUDA runtime.

## Primary references

- Radford, A. et al. (2022), *Robust Speech Recognition via Large-Scale Weak
  Supervision*, arXiv:2212.04356. Repository copy:
  `docs/papers/2212.04356-whisper.pdf` (SHA-256
  `6337bde031b2f237547a977b022f831169a7e05b4d9047f29501166d83594566`).
- Yan, B. et al. (2024), *CMU's IWSLT 2024 Offline Speech Translation System:
  A Cascaded Approach For Long-Form Robustness*, IWSLT 2024,
  <https://doi.org/10.18653/v1/2024.iwslt-1.22>.
- Bondarenko, I. et al. (2025), *Pisets: A Robust Speech Recognition System for
  Lectures and Interviews*, NAACL 2025 Industry Track,
  <https://doi.org/10.18653/v1/2025.naacl-industry.74>.
- National Institute of Standards and Technology (2015), *Secure Hash Standard
  (SHS), FIPS PUB 180-4*. Repository copy:
  `docs/standards/NIST.FIPS.180-4.pdf` (SHA-256
  `0455b406d89648d20cbde375561e19c245b9815e894164c2670772e3d54deb82`).
- Apple ML Research, *MLX: An array framework for Apple silicon*, official
  implementation and software citation: <https://github.com/ml-explore/mlx>.
- Apple MLX Examples, *Speech recognition with Whisper in MLX*:
  <https://github.com/ml-explore/mlx-examples/tree/main/whisper>.
- Google AI for Developers, *Gemma models overview*:
  <https://ai.google.dev/gemma/docs>.
- MLX Community, pinned Gemma 4 E2B 4-bit model:
  <https://huggingface.co/mlx-community/gemma-4-e2b-it-4bit>.
