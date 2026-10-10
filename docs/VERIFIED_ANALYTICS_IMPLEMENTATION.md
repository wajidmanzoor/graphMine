# Verified CPU/GPU analytics implementation

Branch: `feat/verified-cpu-gpu-workflows`.

## Requested outcome

An interface through which people unfamiliar with graph mining can ask about
their data, select CPU-only, GPU-only, or automatic execution, and receive
results computed by declared library algorithms and predefined visualizations.
Normal, Interactive, and Expert modes share the same correctness checks.
Implement the useful review recommendations and commit the work on this branch.

The collection currently contains 70 formal problem contracts. CPU coverage
means a documented executable implementation for each contract, including
problems without a usable GPU implementation, and CPU alternatives for existing
GPU operations. A partial implementation, a different mathematical objective,
or a diagnostic that only checks output shape does not establish that coverage.
Numerical methods, approximate algorithms, learned models, and visualization
layouts must declare what their results do and do not establish.

## Requirements and acceptance evidence

| ID | Requirement | Evidence required before completion |
|---|---|---|
| A1 | Separate branch; commit all implementation, contracts, and required evidence | Branch and commits inspected; no uncommitted implementation changes |
| A2 | cuGraph-like organization: graph objects, algorithm families, backend dispatch, separate native implementation | Public library imports, install/CLI tests, agent actually uses library |
| A3 | CPU implementation for all 70 problem contracts and fallbacks for existing operations | Per-contract coverage inventory, independent result checks, CPU-only runs without GPU access |
| A4 | cuGraph GPU integrations | Actual GPU execution, independent small-graph oracles, device/version evidence, supported-parameter checks |
| A5 | Family-first, then exact-problem routing | Separate constrained stages; ambiguity and wrong-family recovery tests; held-out routing evaluation |
| A6 | Normal / Interactive / Expert modes | Normal executes validated plans; Interactive reviews/edits before execution; Expert accepts explicit validated plans; browser/API tests |
| A7 | Improved graph/result/workflow visualization without a Node.js runtime | Browser renders predefined views and modes with Node unavailable; visual inspection, accessibility and data-binding checks |
| R1 | Typed dependent workflows | Static DAG/port checks and runtime checks on actual derived inputs; cancellation; dependent-output numerical tests |
| R2 | Deterministic lookup, neighbors, filtering, joins, aggregates, bounded paths, subgraphs | Independent expected outputs, typed-ID preservation, direction and empty-result tests |
| R3 | Capability-aware family/operation cards | Planner sees executable parameters and explicit mathematical objectives; catalog consistency tests |
| R4 | Curated CPU/GPU reference tier | BFS, SSSP, PageRank, Jaccard, MST and remaining contract integrations with independent tests |
| R5 | Inspectable/editable plans | Editing revalidates; no execution of an unapproved Interactive plan; clear graph/parameter scope |
| R6 | Structured bounded recovery | Preserve requested semantics; retry only affected steps; unsupported inputs remain explicit |
| R7 | Bounded summaries, full result access, completeness propagation | Truncated or count-only output cannot masquerade as complete input; result pagination/export tests |
| R8 | Task-aware graph construction from tables | Explicit schema, joins, direction, weight meaning, duplicate aggregation and time-window tests |
| R9 | Workflow and external evaluation | Full conversation and workflow result checks, held-out cases, small-graph oracles, larger-graph runs |
| R10 | MCP access to the same validated API | Tool discovery/execution tests; no arbitrary code or alternative validation path |
| R11 | Reviewed-example retrieval | Only approved examples; provenance and held-out exclusion tests |
| B1 | Executable capabilities connected to evidence | Source/dependency/profile hashes, known-failure exclusion, research/build/test/agent states distinguished |
| B2 | Memory-aware scheduling across two GPUs | Actual device assignment, memory admission, LLM reservation, cancellation and concurrent-job tests |
| B3 | Reusable graph representations and reproducibility | Content/semantics/version cache keys, invalidation tests, original IDs, complete execution records |
| B4 | Larger graphs alongside small oracles | Graphalytics-compatible reference comparisons and end-to-end latency/memory evidence for applicable algorithms |

The review's longer-term RL training and federated database work are research
directions, not prerequisites proposed for this implementation. No paper's
reported score substitutes for local integration tests.

## Implementation sequence

1. Preserve existing work; establish the public Python library, input/result
   contracts, device policy, family modules, and evidence inventory.
2. Implement and validate CPU coverage and cuGraph integration in an isolated
   environment, retaining native GPU implementations through an adapter.
3. Connect library capabilities to the agent, routing, queries, workflows,
   table projections, recovery, examples, and MCP tools.
4. Implement the three modes and predefined browser visualizations; integrate
   device selection, workflow review, completeness and provenance.
5. Complete scheduler/cache work, full regression and correctness sweeps,
   browser checks, external scale evaluation, documentation and commits.

## Current evidence and open work

- Separate branch created from the existing working tree. Earlier changes are
  present and must be preserved; no previous changes have been discarded.
- Both RTX 6000 Ada GPUs are available. A new `.venv-analytics` environment keeps
  CPU/cuGraph dependencies separate from the existing agent environment.
- YiGraph source confirms Normal, Interactive, and Expert modes. Its interaction
  ideas will be implemented using our own code and existing browser libraries.
- Implementation and requirement-by-requirement verification remain open.

### First library checkpoint

- Added the installable `python/graphmine` library, graph objects, family modules,
  strict operation parameters, CPU/GPU dispatch, typed result ports and source,
  dependency and device provenance. The existing application is not switched
  to this library yet.
- Added 27 CPU operations and 13 cuGraph profiles, including direct cuGraph
  minimum/maximum spanning forests. cuGraph 26.10.0 and NetworkX 3.7 run in the
  isolated environment on both RTX 6000 Ada GPUs.
- Latest recorded suite: 5,617 CPU tests passed with GPUs hidden; 1,546 tests
  passed on each GPU. The 208 atlas graphs are split between GPUs. Each GPU
  also runs the same 194 weighted/directed/boundary test cases, so the sum of
  GPU test executions is not a count of distinct fixtures.
- Fixed adapter defects exposed by the oracles: k-truss ID renumbering,
  small-graph betweenness normalization, empty Jaccard candidate sets,
  PageRank precision/edgeless boundaries, and NetworkX graph-constructor
  auto-dispatch that otherwise bypassed CPU-only selection.
- Test XML and per-run source/dependency snapshots are in
  `validation/python_analytics/`. Initial failed runs are retained separately.
- All remaining problem integrations, the native adapter, evidence-based
  planner gating, application modes, routing, workflows, UI, scheduler,
  projections, MCP, retrieval and scale evaluation are still required.
