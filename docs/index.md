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

See the repository README for configuration, duration splitting, metadata tagging, transcription, and the GPU/Rust library-curation workflow.

## Architecture and operating model

The CLI owns conversion planning and execution. The library-curation path combines Python orchestration with a Rust backend for byte-heavy scanning and mutation work. Evidence and provenance are kept explicit so later TMK or transcription information can be reconciled without silently rewriting source history.

Architecture reference:

- [Segmentation and reconciliation](architecture/segmentation-reconciliation.md)

## Documentation

Start with the [repository README](../README.md), then follow the architecture and doctoring material under `docs/` for specific operational and safety contracts. DeepWiki provides an additional navigable view of the repository:

- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/codec-carver)

## Releases and verification

Use GitHub Releases and the repository's protected-branch history as the source of truth for shipped versions. A documentation source commit is not, by itself, evidence that a GitHub Pages deployment is live; publication should be verified from the repository's live Pages state before treating this page as a deployed site.
