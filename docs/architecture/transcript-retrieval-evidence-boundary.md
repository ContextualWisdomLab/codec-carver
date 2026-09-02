# Transcript retrieval evidence boundary

## Decision

Codec Carver does not own a transcript relevance model by default. Protected-main term-frequency scoring and repository-authored result tie-breaking are removed from production authority. Until a validated retrieval design is adopted, the system may store and load timestamped transcript evidence but may not tokenize, rank, sample, or select non-empty retrieval results.

The runtime boundary is explicit:

- `TranscriptIndex.add` stores source text and timestamps without derived relevance features;
- `load_transcript_json` remains a lossless parser for the sidecar contract;
- non-empty `tokenize` and `TranscriptIndex.search` raise `SearchPolicyUnavailable`;
- `Match.score` is a compatibility field only and no production path synthesizes a score;
- no local fallback ranker or order preference is substituted.

## Ecosystem boundary

A future retrieval/RAG implementation must carry an explicit algorithm and executable evaluation provenance. RAG/model-response quality evaluation must involve `ContextualWisdomLab/fast-mlsirm`; any LLM execution or model selection must remain behind `ContextualWisdomLab/contextual-orchestrator` and its governed pool/privacy contract.

See `docs/doctoring/no-heuristic-transcript-search.md` and `docs/product-technical-gap-baseline.md` for RCA and current gap state.
