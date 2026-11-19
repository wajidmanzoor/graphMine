# Outputs, completeness, and provenance

Read the result envelope before consuming an operation's arrays or tables.

A successful native request returns structured JSON. An unsuccessful request returns an `error` object with a code and message. A successful allocation through the C ABI does not by itself mean the algorithm succeeded: inspect the JSON response.

The operation contract defines its required outputs. Examples include a count, a vertex set, paths, a partition, scores, a matrix, or a canonical graph. Optional materialization can add witnesses or collections when supported. Use the [explorer](../problem/explorer.md) to inspect each operation's output ports and parameters.

## Do not infer completeness from array length

A backend may compute a full count while materializing only a bounded number of witnesses. A collection limit does not necessarily limit the calculation itself. Use the returned per-output completeness and truncation metadata; do not reinterpret a bounded list as exhaustive.

For optimization, a feasible witness and an objective value do not prove optimality. Inspect `optimal`, explicit bounds, and the selected quality profile. [Guarantees](../problem/guarantees.md) explains these distinctions.

## Preserve the evidence

Keep the input snapshot, operation, parameter values, implementation identity, normalization summary, and result metadata with an exported result. Diagnostics explain limits, rejected profiles, or computation failures. They are part of interpreting a run, not a replacement for its contract.

Numerical operations can have tolerances; iterative and learned operations can have seed or stopping parameters. A reproducible rerun must preserve those settings as well as the graph.
