# Ask questions and choose calculations

Choose an interpretation, review its parameters, and follow the calculation without needing to write an algorithm.

## Normal and Expert mode

| Mode | What you do |
| --- | --- |
| Normal | Ask a question, answer clarifications, and choose a proposed calculation. GraphMine validates the request and proceeds when the required choices are complete. |
| Expert | Inspect and edit the proposed workflow and parameters, validate it, and explicitly approve it before running. |

Both modes use the same formal contracts and native library. Expert mode exposes more control; it does not make an approximate result exact. The compute preference is separate: automatic selection prefers a compatible admitted GPU implementation and can use CPU when appropriate. Explicit CPU or GPU selection constrains the implementation.

## Read a choice card

**Family** gives the broad topic. **Problem** gives the formal question. **Operation** identifies the callable calculation. The **Exact**, **Heuristic**, or other quality badge tells you what the selected profile promises.

Read the interpretation and the difference between alternatives. **Use this option** confirms your choice. **Edit parameters** lets you inspect values such as a seed vertex, hop bound, group size, or requested number of results. A missing required value leads to a clarification or validation message.

Two settings of one operation can represent different computations. For densest subgraph, however, clique order changes what density counts; it does not fix the selected group's size. “Exactly ten vertices” is a different problem. See [densest subgraph](../problem/families/dense.md#densest_subgraph) and [densest k-subgraph](../problem/families/dense.md#densest_k_subgraph).

## Clarifications and follow-ups

If “important” is ambiguous, specify whether you mean many direct connections, high PageRank, or bridging shortest paths. If an operation needs a direction, weight meaning, or two-sided partition, provide it explicitly.

A follow-up can refer to the last answer or a selected result. Say whether you want to reuse the same input, analyze a returned subset, change a parameter, or compare a different question. Check the selected input and proposed operation again; a follow-up is still a new computation when it changes the calculation.

## Activity and Details

Use **Activity** to follow interpretation, validation, and execution. **Details** exposes the plan, parameters, recorded implementation, and diagnostic information associated with the answer. A status message is progress information; the result and its completeness fields establish what was computed.

If the app asks you to wait because the model is busy, avoid repeatedly resubmitting the same question. See [limits and waiting](limits.md).
