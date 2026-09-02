# Product / technical gap baseline

## 2026-09-02 — automatic transcript summarization selection

**Live evidence.** Protected `main@a8e4956fc667782a15276eb04b8f379b4887201f` selected transcript sentences with a repository-authored English stopword set, average term-frequency score, fixed five-sentence default, and earlier-position tie-break. Those rules changed which source statements survived into an output summary. Repository code search found no production caller outside `summarize.py` and its tests, and no open PR owning a research-backed replacement.

**Causal owner.** `codec-carver/summarize.py` owns the selection boundary. This is not a `contextual-orchestrator`, provider, or downstream STT defect.

**Repair.** PR #515 adds a RED contract first, removes the ranking/stopword/sentence-splitting selection path, removes the repository-authored output-length default, preserves lossless empty-input handling, and fails closed for non-empty text or transcript segments. The compatibility `max_sentences` argument remains accepted but has no default and cannot authorize selection.

**Evidence boundary.** No alternative summarization ranking is substituted because this repository currently has no validated use-case-specific summarization measurement design establishing one. A future implementation must provide an explicit algorithm and executable evaluation provenance before automatic selection is re-enabled. If that future path is model/LLM based, response-quality measurement must use the ContextualWisdomLab/fast-mlsirm quality/calibration boundary rather than a locally weighted judge score.

**Verification state.** The RED commit is `dbac11ca0f7187dddd03acbc7425978e255a6762`. Production and focused-test repair follows on the same non-force branch. Hosted exact-head checks are authoritative; queued or predecessor-head results are non-passing.

## Standards / research basis

NIST treats trustworthy AI deployment as dependent on reliable measurement and evaluation and frames testing, evaluation, verification, and validation (TEVV) as an explicit lifecycle activity. These sources support the fail-closed governance decision when a production selector lacks validated measurement evidence; they are not presented as a transcript-summarization algorithm.

- Tabassi, E. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0)* (NIST AI 100-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.100-1
- Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall, P., & Roberts, K. (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile* (NIST AI 600-1). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1
