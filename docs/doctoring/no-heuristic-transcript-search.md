# Doctoring note: heuristic-free transcript retrieval boundary

## Symptom

The legacy `TranscriptIndex.search` mixed exact-looking Boolean retrieval with locally authored preference rules. Text was tokenized by a repository regex, matches were scored by summed query-term frequency, and equal scores were ordered by recording identifier and timestamp. The rarest-postings-first implementation also made the code look like an optimization-only concern even though the emitted `score` and final sort were user-visible relevance decisions.

No repository evidence established term-frequency sum, the lexical tokenizer, or the tie policy as valid measures of transcript relevance for Codec Carver's corpus. Open performance PRs that preserve the same score/order therefore cannot cure the semantic defect.

## Repair contract

The owner boundary now keeps only lossless segment storage and JSON sidecar loading. Non-empty `tokenize()` and `TranscriptIndex.search()` fail closed with `SearchPolicyUnavailable`. No token counts, relevance scores, ranked results, fallback ranker, or tie-break are generated.

RED contract commit: `c042d1884625b8b371708d9d6d0aade917e2903c`.

Re-entry requires an explicit retrieval algorithm, use-case-specific evaluation/calibration evidence, executable provenance for admission/scoring/ties, uncertainty/failure handling, and a documented corpus/query evaluation design. If the path is used for RAG or model response generation, evaluation must involve ContextualWisdomLab/fast-mlsirm; LLM execution remains owned by ContextualWisdomLab/contextual-orchestrator.

## References

Tabassi, E. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.100-1

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1
