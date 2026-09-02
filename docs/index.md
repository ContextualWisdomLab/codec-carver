# Codec Carver

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/ContextualWisdomLab/codec-carver)

Codec Carver is a local-first audio curation toolkit for turning long recordings into reviewable generated assets while preserving originals, metadata, content identity, and mutation evidence.

## Start here

- [Repository README](https://github.com/ContextualWisdomLab/codec-carver#readme) — product purpose, source-development quickstart, safety model, status, and licensing.
- [Segmentation reconciliation](architecture/segmentation-reconciliation.md) — TMK/VAD evidence precedence and late-evidence behavior.
- [GPU transcription + Rust backend](architecture/gpu-transcription-rust-backend.md) — advanced audio-library architecture, local model execution, mutation safety, and recovery.
- [GitHub Releases](https://github.com/ContextualWisdomLab/codec-carver/releases) — immutable release evidence when one exists.
- [FFmpeg license replacement #513](https://github.com/ContextualWisdomLab/codec-carver/issues/513) — current commercial-runtime blocker.
- [Ask DeepWiki](https://deepwiki.com/ContextualWisdomLab/codec-carver) — repository-grounded navigation and questions.

## Product boundary

The current source owns recording inspection, generated-output planning, metadata/provenance capture, exact-content identity, audio-library inventory and recoverable mutation planning. Optional web, MCP, transcription, diarization, and description adapters remain supporting surfaces; they do not change the authority of the original recording or grant third-party software/model licenses.

## Commercial status

Codec Carver original source metadata declares MIT and the public-surface branch adds the matching root MIT license text. The repository currently has no published GitHub release.

The current conversion/probing implementation requires FFmpeg/FFprobe. Because FFmpeg is LGPL/GPL-family software and ContextualWisdomLab does not accept that family as the supported commercial inbound baseline, the current conversion runtime is not commercially complete. The repository must replace that boundary under #513 rather than hide the dependency, select a particular LGPL build, or move it behind another process/container.

Optional packages, native runtimes, and model weights retain their own licenses and require profile-specific approval. The Codec Carver MIT grant never relicenses those third-party components.

## Publication truth

This page is a source documentation landing only. The repository currently reports GitHub Pages disabled. Source presence is not evidence of a published documentation site; any future Pages claim requires settings reconciliation, successful deployment, and live HTTPS verification.
