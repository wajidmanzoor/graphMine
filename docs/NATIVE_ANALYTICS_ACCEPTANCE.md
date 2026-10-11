# Native library and workspace acceptance

The migration implements native CPU profiles for all **70 formal contracts**,
with **80 operations** in one C++/CUDA catalog. **23 operations** have GPU
profiles admitted on both locally tested RTX 6000 Ada devices. Each profile has
specific input, numerical and scaling limits; these counts do not imply every
literature variant or universal GPU support.

Implementation commits are `957dc206` (native library, thin Python runtime and
evidence) and `462ae1ca` (workspace, projections, scheduling, MCP and reviews).
Planner follow-ups are `f2430020` (one source per argument) and `92663fc6`
(output-port contracts and optional reasoning budget). The final app was tested
from an isolated export of `92663fc6`; unrelated earlier working-tree changes
remain separate.

## Requirements

| Requirement | Implementation and evidence |
| --- | --- |
| A1: branch and commits | `feat/verified-cpu-gpu-workflows`; the implementation commits above; `release-app-source.json` confirms 66 Python files matched the final app commit used by the isolated tests. |
| A2: standalone C++/CUDA, thin Python | Installed C/C++ consumers and CLI work with Python absent from PATH. Public Python workflows run under `python -S` without optional Python algorithm packages. The app uses the same native catalog and C ABI. `consumers.json`, `installed-gpu.json`, `public-package-isolation.json`, binding suite. |
| A3: all 70 native CPU contracts | `catalog/native_runtime_coverage.json` maps every formal contract. Native completion tests and baseline sweeps run with CUDA hidden on both CPU and GPU-linked builds. |
| A4/R4: GPU integrations and independent oracles | 44,884 native requests per physical GPU, including declared boundary rejections, plus independent small-graph checks and native provenance. cuGraph and original CUDA workers remain distinct profiles. |
| A5: family then exact operation | Separate constrained stages, semantic ambiguity checks, one bounded family reroute, and one validation repair. Authored tests cover recovery; final real-model evaluation is 16/20. Unattended language-planning reliability remains unproven; details below. |
| A6/R5: three modes and editable review | Normal executes validated plans; Interactive and Expert require approval. Edits invalidate approval. API and Firefox checks cover all three. |
| A7: browser without Node | Fourteen Firefox checks with Node absent from server PATH; desktop/mobile screenshots visually inspected; keyboard, labels, overflow and typed-ID binding assertions. |
| R1/R6: typed dependent workflows and recovery | Static DAG/port validation, native actual-input checks, completeness/namespace checks, persisted affected-step retry, cancellation and reviewed-hash checks. |
| R2: deterministic record queries | Seven native query operations with typed IDs, exact aggregates, filters, direction, empty results, joins, paths and subgraphs checked independently. |
| R3: truthful operation cards | Native descriptions, nested parameter schemas, input kinds, ports, numerical semantics and quality claims shared by C++, Python and planner. `NATIVE_COMPLETION_PROFILES.md`. |
| R7: bounded views and complete access | Preview bounds, typed port pagination and full export; truncated collections cannot supply complete dependencies. Complete counts remain distinct from unrequested enumeration. |
| R8: task-aware native table construction | cuDF file reads plus C++ typed IDs, many-to-one joins, weight meaning, duplicate policies, time windows, lineage and workspace scoping. Binding, API and browser checks. |
| R9: workflow and external evaluation | Actual worker workflows; published Graphalytics BFS/SSSP/WCC references; independent SNAP/synthetic checks; separate frozen model evaluation. |
| R10: MCP | Fourteen stdio tools use the same authenticated HTTP API and approval flow; lifecycle, discovery, execution and auth tests. No arbitrary-code tool. |
| R11: reviewed examples | Explicit approval with revision, workflow, input and result provenance; workspace/implementation scope; immutable evaluation marker and retrieval exclusion; revocation tests. |
| B1: evidence gate | Exact implementation, source, dependency, binary, profile and device hashes; stale/failed reports fail closed. Compile, research and verified execution states are distinct. |
| B2: two-GPU memory scheduling | Actual physical memory probes and concurrent native workers; admission estimates, LLM exclusion/reservation, CPU limits and cancellation. `hardware-admission-generation.json`. Declared large estimates exercise admission without claiming equivalent allocations. |
| B3: representations and reproducibility | Immutable bounded native representation cache keyed by content, semantics, implementation and representation version; accounting, invalidation and concurrency checks. Full workflow provenance and typed original IDs. |
| B4: larger graphs and cost | Sixty native comparisons and six full API runs with latency/RSS/GPU samples; scopes and limits below. |

## Native and application verification

Reports are under [`validation/native_final`](../validation/native_final).

| Check | Result |
| --- | --- |
| Native baseline suites, CPU build | 129,073 passed requests |
| Native baseline suites, GPU-linked build on CPU with CUDA hidden | 129,073 passed requests |
| Native baseline suites, physical GPU 0 / GPU 1 | 44,884 / 44,884 passed requests |
| Native completion, CPU / GPU-linked build with CUDA hidden | 127 / 127 passed tests |
| Thin binding, cuDF ingestion and file projection | 214 passed tests |
| CUDA sanitizers | 36 checks passed, including explicit rejected boundaries |
| Python reference oracles and public native workflows | 29,785 passed tests; reference algorithms do not establish native coverage |
| App, current working sources / isolated final committed sources | 77 / 77 passed checks |
| Physical-GPU app execution and admission | 3 passed checks |
| Firefox workspace without Node | 14 passed checks |
| Published and larger native graph comparisons | 60 passed runs |
| Full API, isolated committed app | 6 passed runs |

Earlier failed and intentionally interrupted reports are retained with distinct
filenames. They are not admitted by the native execution gate. The binding run
named `binding-ingestion-projection-final.xml` accidentally used historical
default build paths; the successful final-build report is
`binding-ingestion-projection-verified.xml`. The final app reports are
`application-bounded-reasoning.xml` and `application-release-commit.xml`;
physical GPU evidence is `application-gpu-generation.xml` and
`hardware-admission-generation.json`. Final browser evidence is
`browser-release-commit.xml`, with screenshots in `browser-release-commit/`.
Hardware admission and the scale algorithms were unchanged by the final
planner-only follow-up.

## Scale measurements

`scale.json` covers official Graphalytics examples/reference inputs, SNAP
ca-CondMat (23,133 vertices, 93,497 undirected edges), and a seeded graph with
100,000 vertices and 500,000 weighted edges. Larger BFS, SSSP, components and
PageRank outputs were compared with independent SciPy/NetworkX calculations.
For PageRank, maximum absolute error on the 100,000-vertex graph was below
`3e-13` in these runs. Published Graphalytics PageRank uses a different stopping
profile and is not used as its oracle.

On the 100,000-vertex graph, native runs including loading and JSON processing
took approximately 2.2–3.7 seconds. The full process measurements were
approximately 2.5–4.4 seconds. Peak process RSS was about 0.82–1.29 GiB;
sampled GPU process memory was about 426–462 MiB. These measurements include
transport and evidence overhead and are not kernel-only speed comparisons.

`api-scale-release.json` measures upload, actual-input validation, submission,
native execution, full result retrieval and pagination through the authenticated
API using the exact committed app. It checks BFS distances and predecessor
witnesses independently and compares PageRank with the already independently
verified native reference. API latency was 24.3–25.7 seconds in these six runs
and includes repeated source/dependency evidence checks; no LLM planning time
is included.

GPU samples are observations at 100 ms intervals, not exact allocator peaks.
The local model occupied GPU 0 during measurements, and some local validation
work overlapped. These are reproducible local correctness/cost observations,
not a certified Graphalytics submission, exhaustive performance evaluation, or
evidence of a general GPU speedup. Pinned archive URLs/hashes and reproduction
commands are in the [workspace guide](ANALYTICS_WORKSPACE.md).

## Model evaluation

The frozen `heldout-suite.json` contains 20 assistant-authored questions over
new fictional graphs, including typed IDs, exact optima, directed capacities,
dependent input scope, follow-up context, wrong-family recovery and three
requests that should require more information. Answers use independent subset,
cut, path-relaxation and record calculations. The suite was frozen before its
first model run. It is a local held-out study, not an external NLP benchmark or
human annotation. Every case excludes reviewed examples and cannot become an
approved training/retrieval example.

The final `model-heldout-release.json` run used the exact committed app
`92663fc6`, Qwen/Qwen3.8-27B-FP8 revision
`017b9c7af6b5689d5dd426a76e0bc077eb5ca20a`, medium reasoning, a 1536-token
reasoning budget within 3072 completion tokens, temperature 0 and seed 0.
All source hashes remained unchanged during the run.

| Model run | Passed | Interpretation |
| --- | --- | --- |
| Earlier committed app, `model-heldout.json` | 17/20 (85%) | Baseline before the generation-format and catalog-context changes; no separate reasoning-token budget. |
| Final committed app, `model-heldout-release.json` | 16/20 (80%) | Same frozen suite, rerun after development-led changes; 13/17 calculation requests and 3/3 clarification cases passed. |

This is a repeated evaluation of the same frozen suite, not a second unseen
benchmark. The final result is reported even though it is lower than the
baseline. The changes enforce argument/port contracts and bound reasoning;
these measurements do not establish an accuracy improvement.

The four final failures stopped before execution. Minimum vertex cover returned
a contradictory unsupported decision; weighted shortest paths and neighbor
lookup returned empty operation selections; the dependent subgraph/triangle
request still had an unknown step reference after its one permitted repair.
All 17 executable reference cases passed independent native oracle checks in
`heldout-oracles.json`. These planning failures do not establish native algorithm
failures, and passing native validation alone does not prove a model understood
a person's intent.

Final question-to-decision/result timings ranged from 26.8 to 115.0 seconds, with
a median of 38.2 seconds. Some application/scale checks overlapped with the model
run. These are local observations, not a controlled speed comparison.

Development probes are retained separately and never counted as held-out
results. The earlier 20-case development run scored 7/20 under strict canonical
operation/parameter/wiring grading. Additional generation and inference-setting
probes are explicitly labeled development experiments. Their failures remain
available alongside successful runs; they are not training examples or native
execution-admission evidence.

The redesign, native migration and acceptance measurements are complete.
**Reliable unattended natural-language planning remains unproven**, particularly
for dependent workflows. Interactive review, explicit task selection and the
Expert workflow editor remain available through the same validated execution
path. Further model/routing work should be assessed on a fresh evaluation set.
