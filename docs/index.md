# Codec Carver

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/codec-carver)

Codec Carver turns long recordings into durable, metadata-preserving audio artifacts and provides evidence-aware tooling for organizing, transcribing, and reconciling recording libraries.

## What it does

- Converts supported recordings to FLAC or size-bounded Opus while preserving source metadata.
- Splits long recordings at safe duration boundaries, preferring detected silence when possible.
- Offers a Python CLI, an optional FastAPI upload surface, and an MCP integration.
- Provides a Rust-backed library-curation workflow for hashing, inventory, duplicate quarantine, TMK/VAD reconciliation, and bounded mutations.
- Supports optional transcription and evidence-backed description workflows while keeping source recordings intact.

## Quick start

Prerequisites are Python 3.10+ and `ffmpeg`/`ffprobe` on `PATH`.

```bash
pip install -e .
codec-carver /path/to/recordings --execute --output-dir under_2gb
```

For the optional web service:

```bash
pip install -e ".[web]"
docker build -t codec-carver .
docker run -p 8000:8000 codec-carver
```

Use the repository README for the product overview and common workflow. Detailed configuration, duration-splitting controls, metadata tagging, transcription, iCloud/TMK handling, and GPU/Rust library-curation procedures are preserved in the [advanced operations reference](advanced-operations.md).

## Architecture and operating model

The CLI owns conversion planning and execution. The library-curation path combines Python orchestration with a Rust backend for byte-heavy scanning and mutation work. Evidence and provenance are kept explicit so later TMK or transcription information can be reconciled without silently rewriting source history.

Architecture reference:

- [Segmentation and reconciliation](architecture/segmentation-reconciliation.md)
- [GPU transcription / Rust backend](architecture/gpu-transcription-rust-backend.md)

## Documentation

- [Repository README](https://github.com/ContextualWisdomLab/codec-carver/blob/main/README.md)
- [Advanced operations reference](advanced-operations.md)
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/codec-carver)

Follow the architecture and doctoring material under `docs/` for specific operational and safety contracts.

## Status and verification

The package metadata currently identifies source version `0.1.0`. Treat GitHub Releases and protected-branch history as the authority for shipped versions and release evidence; a source version or documentation commit alone is not a release. Likewise, this `docs/index.md` file is only a Pages source prerequisite until repository settings, deployment, and the live HTTPS page are independently verified.

## License

Codec Carver source declares the MIT license in `pyproject.toml`; this branch completes that existing source-license lineage with the root [MIT LICENSE](https://github.com/ContextualWisdomLab/codec-carver/blob/main/LICENSE). The MIT grant applies to Codec Carver-authored source and documentation. External tools and dependencies—including `ffmpeg`/`ffprobe`, Python/Rust packages, model runtimes, model weights, and provider services—retain their own licenses and terms and are not relicensed by this repository.
