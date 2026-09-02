# Summarization evidence boundary

## Decision

Codec Carver does not own an inferred transcript-importance model by default. Automatic removal, ranking, or prioritization of transcript content is disabled until a validated selector and evaluation design are adopted through review.

`summary.py` is therefore an evidence boundary rather than a hidden quality model:

- empty input returns an empty `Summary` without selection;
- non-empty text or segment input raises `SummarizationPolicyUnavailable`;
- the compatibility `max_sentences` parameter has no repository-authored default and cannot authorize ranking;
- there is no stopword weighting, word-frequency score, positional tie-break, or heuristic sentence segmentation in the production selection path.

## Ownership and ecosystem boundary

Codec Carver owns lossless audio/video carving and transcript-adjacent representation plumbing. It may expose transcript material, but it must not invent an unvalidated importance model merely to compress it.

If a future summarizer invokes an LLM, provider choice remains owned by `ContextualWisdomLab/contextual-orchestrator`; response-quality calibration/evaluation must involve `ContextualWisdomLab/fast-mlsirm`. Neither dependency is needed for the present fail-closed boundary because no model inference or quality score is performed.

## Re-entry criteria

Automatic summarization can be re-enabled only when the PR contains the algorithmic authority, applicable research/standard references, executable evaluation/calibration evidence, deterministic audit provenance, and failure behavior. Any threshold or tie policy must come from that authority rather than a repository convenience constant.

See `docs/doctoring/no-heuristic-summarization.md` and `docs/product-technical-gap-baseline.md` for RCA and live gap state.
