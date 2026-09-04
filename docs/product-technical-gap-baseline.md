# Product / technical gap baseline

## 2026-09-02 — automatic transcript summarization selection

**Live evidence.** Protected `main@a8e4956fc667782a15276eb04b8f379b4887201f` selected transcript sentences with a repository-authored English stopword set, average term-frequency score, fixed five-sentence default, heuristic sentence splitting, and earlier-position tie-break. Those rules changed which source statements survived into an output summary. Repository code search found no production caller outside `summarize.py` and its tests, and no open PR owning a research-backed replacement.

**Causal owner.** `codec-carver/summarize.py` owns the selection boundary. This is not a `contextual-orchestrator`, provider, or downstream STT defect.

**Repair.** PR #515 adds a RED contract first, removes the ranking/stopword/sentence-splitting selection path, removes the repository-authored output-length default, preserves lossless empty-input handling, and fails closed for non-empty text or transcript segments. The compatibility `max_sentences` argument remains accepted but has no default and cannot authorize selection.

**Evidence boundary.** No alternative summarization ranking is substituted because this repository currently has no validated use-case-specific summarization measurement design establishing one. A future implementation must provide an explicit algorithm and executable evaluation provenance before automatic selection is re-enabled. If that future path is model/LLM based, response-quality measurement must use the ContextualWisdomLab/fast-mlsirm quality/calibration boundary rather than a locally weighted judge score.

**Verification state.** The RED commit is `dbac11ca0f7187dddd03acbc7425978e255a6762`. Hosted exact-head checks are authoritative; queued or predecessor-head results are non-passing.

## 2026-09-02 — transcript retrieval ranking and token admission

**Live evidence.** The same protected head used a local Unicode-regex tokenizer, Boolean-AND term admission, summed term frequency as a `Match.score`, rarest-postings-first implementation ordering, and `recording_id` / timestamp tie-breaking. The score and tie policy determined result priority without a validated retrieval-quality model. Repository code search found no production caller outside `transcript_search.py` and its tests. Existing open performance PRs preserve these semantics and therefore do not own the no-heuristics repair.

**Causal owner.** `codec-carver/transcript_search.py` owns this local retrieval boundary. No downstream caller needs a compensating patch because none is present on protected main.

**Repair.** PR #515 adds RED commit `c042d1884625b8b371708d9d6d0aade917e2903c`, removes derived token counts, relevance scores, result sorting and tie-breaking from production, preserves lossless segment storage / JSON loading, and fails closed for non-empty tokenization or search until a validated retrieval/evaluation contract is adopted. This deliberately avoids substituting an unvalidated BM25/vector/LLM ranker.

**Future integration.** If retrieval becomes a RAG candidate-generation path, its response/retrieval-quality evaluation must involve `ContextualWisdomLab/fast-mlsirm`; if an LLM is used, model execution must route through `ContextualWisdomLab/contextual-orchestrator` under the caller's governed pool/privacy contract.

## Standards / research basis

NIST treats trustworthy AI deployment as dependent on reliable measurement and evaluation and frames testing, evaluation, verification, and validation (TEVV) as an explicit lifecycle activity. These sources support the fail-closed governance decision when a production selector lacks validated measurement evidence; they are not presented as summarization or retrieval algorithms.

- Tabassi, E. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.100-1
- Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1
