# Phase 5 production candidate

Google search is disabled by default and explicitly disabled in every host
environment. Later retrieval work is saved in
[Deferred Google search](../../docs/DEFERRED_GOOGLE_SEARCH.md). The remaining
Phase 0–5 changes include grounded answers, citations, clarification, options,
typed biclique partitions, and the existing production account and result fixes.

Validation on the final application sources:

- 1597 agent checks passed; 50 explicit integration opt-ins skipped.
- 29,800 Python library checks, 64 browser checks, and 82 deployment/Studio checks passed.
- All 11 live model acceptance cases passed, covering all nine lanes and disabled search.
- The pinned native runtime passed its CPU/GPU oracles and admits all 82 CPU operations and 59 GPU profiles.

`report.json` identifies the tested code and native pins. The four agent batches
cover every collected test exactly once. Per-run records verify unchanged source
hashes. `disabled-search-acceptance.json` checks the exact availability message,
absence of a search link and executable operation, and current-turn citations.
The expected disabled status accounts for the live report's one deterministic
grounding fallback; no answer-writer call was made for that request.

The original frozen 60-case study is unchanged and remains a historical Phase 5
measurement. This is a separate acceptance subset, not a new 60-case benchmark.
Files prefixed `diagnostic-` retain setup errors, the interrupted serial run, and
the first authored smoke-case schema error. `report.json` explains each; final
results use the corrected isolated setup without changing application code.

The deployment controller must still validate the exact candidate, back up
production data, and promote it. Its private `last-promotion.json` records the
actual deployment and backup; this candidate report does not claim deployment
has already occurred. Frontend tests, type checking, and API contracts are also
required by that controller gate. Model and database services stay running.
