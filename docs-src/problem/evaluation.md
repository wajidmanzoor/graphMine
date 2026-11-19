# How GraphMine is evaluated

Distinguish choosing the right calculation, computing it correctly, and completing a usable workflow.

## Routing accuracy

A routing evaluation checks whether a question selects the intended family, formal problem, operation, and semantic parameters. Ambiguous questions should produce a useful clarification rather than an arbitrary choice. Fixtures also check that equivalent choices are deduplicated and quality badges match the actual operation.

The repository contains authored routing and clarification cases. A current, independently held-out end-to-end routing accuracy figure is not established by the native validation reports below, so this page does not present one. A score from an older model or test protocol should not be described as the current app’s accuracy.

## Correctness and CPU/GPU agreement

Reference suites compare native results with independent implementations or directly checkable properties: clique feasibility, counts, shortest-path distances, flow conservation, partitions, objective values, bounds, and output completeness. CPU/GPU comparisons must account for valid alternative witnesses, ordering, and declared numerical tolerances.

The following are historical test-run totals from November 17, 2026. Different GPU runs can contain different applicable tests; the counts are not interchangeable coverage measures.

| Recorded suite | Date | Passed | Failed / errors | Skipped |
| --- | --- | ---: | ---: | ---: |
| Native binding tests | 2026-11-17 | 148 / 148 | 0 / 0 | 0 |
| CPU completion tests | 2026-11-17 | 168 / 168 | 0 / 0 | 0 |
| Original GPU profile tests, run A | 2026-11-17 | 33 / 33 | 0 / 0 | 0 |
| Original GPU profile tests, run B | 2026-11-17 | 34 / 34 | 0 / 0 | 0 |

Source: [native validation records at the recorded revision](https://github.com/wajidmanzoor/graphMine/tree/8d8487ade4bbfa3518fe12c059d9e2c87f8afd10/validation/family_routing_runtime). The [public evidence summary](../assets/evaluation.json) includes the source revision and source-file hashes, with machine metadata omitted.

These passing cases support their tested profiles and inputs. They do not prove that every algorithm is correct for every graph or that a new build has matching validation evidence.

## Evaluation inputs and workflow checks

The native suites use small deterministic graphs, boundary cases, generated cases, and problem-specific reference inputs. App tests cover choice cards, parameter validation, saved inputs, result views, persistence, and exports using example fixtures. Some browser tests replay fixed computed results to isolate view behavior; they are not model-accuracy measurements.

Performance work measures end-to-end latency, solver time, memory, failures, and the effect of input size and structure. A speed comparison needs matching inputs, parameters, quality, and completeness. The public technical note makes no new speedup claim, and this page does not turn a development benchmark into a general performance guarantee.
