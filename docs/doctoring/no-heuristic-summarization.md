# Doctoring note: heuristic-free summarization boundary

## Symptom

The legacy extractive summarizer presented a deterministic result but its determinism did not make the selection evidence-based. It manually removed a small English stopword list, averaged corpus-local word frequencies, selected a fixed number of highest-scoring sentences, and resolved equal scores by source position. The module itself also described sentence splitting as heuristic.

Each rule affected output membership. None had repository-local calibration, an acceptance study for Codec Carver transcripts, a registered statistical decision rule, or an authoritative standard establishing it as the production selector.

## Root cause

A convenience summarizer was treated as harmless local text processing even though it performed a quality/prioritization decision. The absence of an external model or network call obscured that the algorithm was still deciding which evidence to retain and which evidence to discard.

## Repair contract

For non-empty text, `summarize_text` and `summarize_segments` now fail closed with `SummarizationPolicyUnavailable`. Empty input remains a lossless no-op. `max_sentences` remains only as a compatibility argument with a `None` default and does not enable selection.

This repair intentionally does **not** replace one unvalidated selector with another. Re-enabling automatic summarization requires all of the following to be reviewable together:

1. an explicit research- or standard-backed selection algorithm;
2. a use-case-specific evaluation design for Codec Carver transcript distributions;
3. executable provenance for every threshold, weight, sampling rule, and tie policy;
4. uncertainty/failure handling that fails closed when required evidence is unavailable;
5. when model/LLM output is involved, ContextualWisdomLab/fast-mlsirm as the statistical/psychometric response-quality and calibration boundary.

## Verification

RED contract commit: `dbac11ca0f7187dddd03acbc7425978e255a6762`.

The production repair removes the frequency scorer, hand-curated stopword list, heuristic sentence splitter from the selection path, fixed five-sentence default, and positional tie-break. Hosted current-head checks remain the merge authority.

## References

Tabassi, E. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.100-1

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1
