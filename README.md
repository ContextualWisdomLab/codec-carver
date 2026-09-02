# Codec Carver

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/codec-carver)

**Turn long recordings into reviewable, metadata-preserved audio assets without overwriting the originals.**

Codec Carver is a local-first audio curation toolkit. Its primary job is to inspect long recordings, plan bounded conversions, and write generated outputs to a separate location while preserving source metadata and provenance. The repository also contains optional web, MCP, transcription, and evidence-backed audio-library workflows built around the same “inspect first, mutate explicitly” boundary.

> **Commercial runtime status:** Codec Carver source is MIT-licensed, but the current conversion/probing path requires FFmpeg/FFprobe. Upstream FFmpeg is LGPL-2.1-or-later by default and can become GPL-2.0-or-later depending on the build, which is outside ContextualWisdomLab's inbound commercial-license policy. Issue [#513](https://github.com/ContextualWisdomLab/codec-carver/issues/513) owns replacement of that execution boundary. Until it is resolved, do not present the current FFmpeg-backed conversion path as a commercially approved deployment.

## What it does

Codec Carver keeps four user-visible responsibilities distinct:

| Job | Current responsibility |
| --- | --- |
| Carve recordings | Plan size- and duration-bounded generated audio while preserving originals. |
| Preserve evidence | Retain source metadata, conversion reports, content identity, and mutation history needed to review what happened. |
| Curate libraries | Inventory recordings, reconcile Sony TMK/VAD timing evidence, identify exact duplicates, and stage recoverable rename/quarantine plans. |
| Add optional understanding | Produce local transcripts, speaker-aware evidence, and description/title candidates when an explicitly configured model profile is available. |

The default mutation posture is conservative: source files are not overwritten, generated output belongs in a separate directory, irreversible deletion is not the normal cleanup path, and advanced library mutations require an explicit execution step after planning and revalidation.

## Current maturity

`pyproject.toml` records source version `0.1.0`. The repository currently has **no published GitHub release**, so that version is source metadata rather than an immutable supported release.

The protected `main` branch contains substantial conversion and audio-library functionality, but commercial completion is blocked by the FFmpeg/FFprobe license boundary in #513. Optional model packages and model weights also retain their own licenses and must be evaluated independently from Codec Carver's MIT grant.

## Quick start for source development

Codec Carver requires Python 3.10 or newer.

```bash
git clone https://github.com/ContextualWisdomLab/codec-carver.git
cd codec-carver
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate `.venv\Scripts\activate` instead.

This installs the repository's Python source and declared runtime dependencies. It does **not** make an external codec binary or optional model profile commercially approved.

Run the source-level verification suite with:

```bash
python3 -m unittest discover -s tests
python3 -m py_compile media_shrinker.py
```

## CLI workflow

The primary CLI is `codec-carver`. A safe operating sequence is:

1. choose a source recording tree;
2. keep generated outputs in a dedicated output directory;
3. inspect the planned work before enabling mutation;
4. execute only after the source/output boundary is correct;
5. retain the generated report as the review record.

The historical FFmpeg-backed conversion command remains part of the current source implementation, but it is **not an approved commercial execution path while #513 is open**. Developers evaluating the existing behavior should read the architecture and issue evidence before installing or invoking FFmpeg.

Configuration can be stored in `.codec-carver.json`; explicit CLI options override file values, and configuration cannot silently turn a dry run into an executing mutation.

## Web and MCP surfaces

The repository exposes optional integration surfaces through package extras:

```bash
python -m pip install -e ".[web]"
python -m pip install -e ".[mcp]"
```

The web surface provides the upload-oriented application boundary, while the MCP surface lets an authorized host call Codec Carver capabilities without importing private implementation modules. These adapters do not change the underlying source/mutation or third-party license boundaries.

## Audio-library workflow

`codec-carver-library` is the higher-level curation surface for large recording collections. It separates evidence collection from mutation:

```bash
codec-carver-library /path/to/recordings inventory
codec-carver-library /path/to/recordings plan
codec-carver-library /path/to/recordings apply          # validation only
codec-carver-library /path/to/recordings apply --execute
```

The library workflow uses full SHA-256 content identity, keeps transcript/evidence state separate from raw recordings, treats late TMK evidence as a reconciliation event rather than silently rewriting history, and sends exact duplicates to a recoverable quarantine boundary rather than permanently deleting them by default.

For the detailed timing/evidence contract, see [segmentation reconciliation](docs/architecture/segmentation-reconciliation.md). For the Rust/GPU library architecture, model pinning, iCloud materialization, mutation safety, and recovery rules, see [GPU transcription and Rust backend architecture](docs/architecture/gpu-transcription-rust-backend.md).

## Optional transcription and model-assisted description

Transcription and description are optional capabilities, not prerequisites for basic source inspection or package import. Current source contains integrations for pinned Whisper-compatible, MOSS, and MLX model profiles.

Third-party Python packages, native runtimes, and model weights are **not** relicensed by Codec Carver. Their exact package/model revision and license must be approved for the intended distribution before a profile is treated as commercially supported. In particular, do not infer approval from a model name appearing in source or from the repository's MIT license.

The current MOSS-Transcribe-Diarize upstream model is published under Apache-2.0, while the pinned Whisper conversion advertises MIT terms; other model profiles can use different terms and remain independently reviewable. The README intentionally does not turn those implementation pins into blanket procurement approval.

## Safety model

Codec Carver's customer-facing safety contract is simpler than the implementation details behind it:

- **Originals stay authoritative.** Generated conversion output belongs in a separate destination.
- **Plan before mutation.** Library curation separates inventory/planning from `--execute`.
- **Identity is content-bound.** Exact-duplicate and transcript evidence use full SHA-256 identities rather than filenames alone.
- **Changed evidence fails closed.** Paths, content identities, TMK evidence, and mutation plans are revalidated rather than trusted indefinitely.
- **Deletion is recoverable by default.** Duplicate curation uses quarantine instead of routine irreversible deletion.
- **Local-first processing remains explicit.** Optional GPU/model work is designed around local evidence and pinned profiles; external services are not silently introduced as authority.

## Architecture

```text
recordings
   │
   ├── inspect / inventory / evidence
   │            │
   │            ├── conversion plan
   │            ├── transcript / timing evidence (optional)
   │            └── library curation plan
   │
   └── explicit execution
                │
                ├── generated output directory
                └── recoverable library mutation + journal
```

Python owns the user-facing orchestration and optional model workflows. The Rust backend handles byte-heavy inventory and mutation operations for the advanced audio-library path. External codec/model runtimes remain dependencies behind reviewed boundaries; they do not become part of Codec Carver's own licensing authority.

## Documentation

- [Public documentation landing](docs/index.md) — product, architecture, safety, and licensing navigation.
- [Segmentation reconciliation](docs/architecture/segmentation-reconciliation.md) — TMK/VAD evidence precedence and late-evidence reconciliation.
- [GPU transcription + Rust backend](docs/architecture/gpu-transcription-rust-backend.md) — advanced library architecture and evidence boundary.
- [FFmpeg commercial-license blocker #513](https://github.com/ContextualWisdomLab/codec-carver/issues/513) — required codec/probe replacement boundary.
- [GitHub Releases](https://github.com/ContextualWisdomLab/codec-carver/releases) — immutable release evidence when a release exists.

## Contributing

Keep product behavior and evidence claims separate from local operator history. New public behavior should update the relevant tests and architecture documentation, and new dependencies, native binaries, model weights, datasets, or assets must pass commercial-license/provenance review before they are recommended as supported product inputs.

Avoid adding machine-specific file paths, private recording names, one-off incident commands, or internal automation procedure to the public README. Put detailed operational and implementation evidence in the appropriate architecture/doctoring documentation instead.

## License

Codec Carver original source and documentation are licensed under the [MIT License](LICENSE), matching the existing `pyproject.toml` metadata.

That grant does not relicense FFmpeg/FFprobe, Python dependencies, model weights, model code, container bases, datasets, or other external assets. The current FFmpeg-backed execution path remains commercially blocked under ContextualWisdomLab policy until #513 is resolved.
