# Exact, heuristic, and learned results

Read a result's quality, completeness, and provenance before treating it as an answer.

| Quality | Promise | What it does not establish |
| --- | --- | --- |
| Exact | A completed computation meets the operation's exact contract, including an optimum when that contract requires one. | That the chosen problem matches your real-world intent. |
| Heuristic | A method returns a feasible or useful candidate under its stated rules. Any bound must be reported explicitly. | A global optimum without a certificate. |
| Learned | A model produces predictions, scores, or representations under the selected profile. | Ground-truth labels or guaranteed real-world accuracy. |
| Parameter/backend dependent | The selected settings and implementation determine the guarantee. | A single quality label for every possible run. |

An approximate method is not automatically a certified approximation. Look for an explicit bound. CPU and GPU describe where work runs, not its mathematical quality. In particular, the current `densest-subgraph` profile is exact; a second label does not turn it into a different approximate method.

## Complete computation and complete collection

A total count can be complete while a list of matching items is capped. Conversely, a partial search may not establish a complete count or a proven optimum. Inspect the status of each returned collection and any `optimal`, bound, truncation, or completeness fields.

!!! warning "A preview is not the whole result"
    A graph view can show fewer vertices than the calculation used. A download can also contain a bounded collection. Use the result metadata to distinguish a display limit from an incomplete computation.

## What gets checked?

The runtime checks input types, direction, weights, partitions, parameters, and supported implementation profiles. Normalization is recorded. Operations perform contract-specific checks, such as verifying a returned clique, recomputing an objective, or validating a flow. Independent oracle suites provide separate development evidence. No finite test suite is a proof for all possible inputs.

The application checks that a result is eligible for use and that an explanation is grounded in returned facts. When a generated explanation fails grounding checks, it can show a deterministic factual explanation instead. See [the question-to-answer sequence](../how-it-works/from-question-to-answer.md).

## Provenance

A reproducible answer identifies the input snapshot, operation, parameters, implementation, normalization, and result status. Keep the result JSON and its input together. A named dataset can have several saved versions; its name alone does not identify the exact input used.

[Output fields and diagnostics](../library/outputs.md) explains the library side of these records.
