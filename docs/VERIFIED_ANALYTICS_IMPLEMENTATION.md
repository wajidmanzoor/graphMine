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

- Implementation commit: `cd3ec454` on the requested feature branch.
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

### CPU structural and optimization checkpoint

- CPU coverage is now 39 executable operations across 37 of the 70 problem
  contracts. The remaining 33 problem contracts still need CPU integrations.
  The new operations cover density, quasi-cliques, bicliques, butterflies,
  assignment, pattern matching/counting, communities, balanced partitioning
  and signed-network balance. Their precise objectives, limits and input
  conventions are in `CPU_REFERENCE_PROFILES.md`.
- Extended higher-order density without a fixed clique-order ceiling;
  graphlet classification now covers the complete atlas through seven vertices.
  Exact integer-capacity density optimization is distinguished from numerical
  HiGHS optimality certificates. Infeasible balance and matching constraints
  cannot be presented as successful feasible solutions.
- Corrected two ambiguous formal definitions: ordinary degree versus butterfly
  participation in bipartite cores, and structural balance versus zero weighted
  frustration when zero-cost edges exist. The embedded catalog/manifest
  definitions are synchronized with their source contracts.
- Latest full library report: **11,677 CPU tests passed**, with GPUs hidden;
  **1,546 cuGraph tests passed on each GPU**, with no skips. The new oracle cases
  include all 512 3-by-3 bipartite graphs, all 729 signed four-vertex graphs,
  atlas graphs through six vertices, directed patterns and weighted fixtures.
  Counts are test executions; parameter loops inside tests add further calls.
- `cpu-extended-initial.xml` retains the first 6,059-test pass on the new
  operations. Final reports are `cpu-extended.xml`, `gpu-0-extended.xml` and
  `gpu-1-extended.xml`. Metadata now includes formal contract/package hashes
  and the collected test selection. The audit checks dependency versions and
  generates per-operation profile hashes in addition to source hashes.
- Existing agent catalog/planning regression checks: 55 passed; nine native
  worker tests were skipped because that invocation did not configure a native
  test binary. These results are not an agent integration claim for the new
  Python layer.
- Derived graph ports now distinguish their own fingerprint from input lineage.
  Explicit SciPy provenance, malformed-parameter rejection and oversized GPU
  integer-weight handling were verified alongside the previous operations.
- The browser and agent still use the existing native path. All application,
  remaining CPU, native adapter, routing, workflow, scheduler, cache, MCP,
  reviewed-example retrieval and scale requirements above remain open.

### Numerical, construction and topology checkpoint

- CPU coverage is now **48 operations across 46 of 70 problem contracts**.
  Nine additional profiles cover Laplacian eigenpairs, signal denoising,
  nearest-neighbor graph construction, coarsening, hypergraph partitioning,
  SimRank, widest paths, critical DAG paths and flag-complex persistence.
  The remaining 24 problem contracts still need CPU integrations.
- Added validated `FeatureVectors` and `Hypergraph` input classes. Operation
  cards declare the accepted input kind. Result lineage distinguishes original
  input fingerprints from generated graph fingerprints, preserving typed IDs.
- Added CPU dependencies CVXPY 1.9.3, CLARABEL 0.11.1 and GUDHI 3.13.0 in the
  analytics environment. Updated reproducible dependency pins and included
  input-schema hashes in test evidence.
- Corrected balance-bound rounding for graph and hypergraph integer assignment
  models. Strict bounds are converted to the exact rational weight grid before
  optimization, preventing an infeasible extra vertex from being admitted by
  floating-point rounding.
- SimRank uses SciPy GMRES and an independently recomputed contraction error
  bound. NetworkX's internal relative stopping tolerance failed a tighter
  absolute-accuracy smoke check, so it is not the implementation for this
  profile. Denoising checks stationarity or a feasible primal-dual gap; spectral
  outputs check residuals and orthogonality.
- Persistent homology retains essential H0 intervals, expands sufficient
  cofaces for the requested dimensions, and discloses cutoff censoring. Tests
  verify the entire homology rank invariant over pairs of filtration levels
  using independent finite-field boundary algebra, not only final Betti counts.
- Latest complete reports: `cpu-numerical.xml` has **14,800 passes** with CUDA
  hidden; `gpu-0-numerical.xml` and `gpu-1-numerical.xml` each have **1,546 passes**,
  with no skips. The first 3,121-check numerical sweep is retained separately.
  New tests also cover signed/large-weight DAG ranking, capacity-zero
  reachability, all small hypergraphs, feature symmetrization and quotient
  aggregation. Every previous library operation was rerun in the full suite.
- These profiles are library integrations. They are not yet connected to the
  existing native agent/browser. Remaining CPU coverage and every open
  application/routing/workflow/UI/scheduling/evaluation requirement above remain
  part of the active goal.

### Sampling, temporal and local-analysis checkpoint

- CPU coverage is now **55 operations across 53 of 70 problem contracts**.
  Seven new integrations cover random walks, neighborhood sampling, temporal
  journey objectives, bounded paths/cycles, temporal motifs, null-model
  significance and seeded local communities. Seventeen problem contracts
  still need a CPU integration. Operation cards continue to disclose the
  supported profile rather than claiming every formal parameter variant.
- Walks and neighborhoods use NumPy sampling with recorded seeds, explicit
  direction/parallel-edge/zero-weight semantics and validated fanouts.
  Normalization supports large integer weight ratios; a positive probability
  that underflows float64 is rejected instead of silently becoming zero.
- Temporal paths optimize fastest duration or earliest arrival separately and
  retain edge witnesses plus exact rational objective values. Temporal motifs
  preserve event identity and support total/partial precedence, equal-time
  policy, attribute predicates and induced occurrence windows. Counts remain
  exhaustive when instance listings are capped.
- Bounded path/cycle caps retain the shortest qualifying results and propagate
  incomplete collection status. Fixed-degree null sampling uses complete
  rejection of nonsimple configuration samples, with complementary sampling
  for dense inputs, explicit budgets, and invariants checked for every sample.
  The local-community profile returns an actual seed-containing community and
  recomputed conductance; its diffusion/sweep method is labeled heuristic.
- Latest reports: `cpu-temporal.xml` has **16,556 passes** with CUDA hidden;
  `gpu-0-temporal.xml` and `gpu-1-temporal.xml` each have **1,546 passes**, with
  zero failures or skips. All prior library operations were rerun. New oracles
  include exhaustive event journeys, vertex/event injections, cycle/path
  permutations, independent PageRank equations and conductance recomputation,
  per-sample graph invariants, and deterministic sampling-frequency checks.
- The initial new-profile run had four fixture-construction errors because
  parallel edges had not been declared in fixture metadata; 1,742 cases passed.
  After fixture correction, 1,752 focused tests passed. Four further input
  validation cases are included in the final full sweep. Both earlier reports
  are retained separately and are not the current-source acceptance evidence.
- Lint, formatting, package dependency checks, formal-contract synchronization
  and the source/dependency evidence audit pass. The audit now points to the
  three latest full regression reports and records all new capability cards.
- These are library integrations. The existing agent/browser still uses its
  native execution path. Remaining CPU coverage and all open application,
  routing, workflow, modes, visualization, scheduling, caching, MCP, reviewed
  example retrieval and scale evaluation requirements remain in the active
  goal.

### Connection, comparison and record-analysis checkpoint

- CPU coverage is now **59 operations across 57 of 70 problem contracts**.
  Four additional integrations cover group Steiner trees, global network
  alignment, entity blocking/resolution and reference-based graph anomalies.
  Thirteen problem contracts still need CPU integrations. Local many-to-one
  alignment and arbitrary learned anomaly models are not advertised as
  executable variants of these profiles.
- Group Steiner uses a binary tree model and separated connectivity cuts,
  verifies group/required-vertex coverage and tree structure, and retains the
  correct cheapest original parallel edge. Alignment optimizes an injective
  mapping covering the smaller graph and recomputes conserved-edge and prior
  contributions. Weighted edge conservation is explicitly defined as the
  minimum of the two normalized nonnegative edge weights.
- Entity rules use RapidFuzz 3.14.6 unit edit distance, declared typed equality,
  token overlap and exact numeric differences. Resolution supports transitive
  components and globally optimized unit candidate-pair disagreement. Rules
  retain provenance and missing-field semantics; no arbitrary expressions or
  trained-model guesses are executed. RapidFuzz is now a pinned CPU dependency
  included in provenance and the evidence audit.
- Anomaly features cover vertices, original edge instances and declared
  induced subgraphs. Normality populations are separate from candidates and
  may use another graph or supplied baseline statistics. Tests verify features,
  population standardization, contribution formulas, typed-ID tie ordering,
  constant columns and stable centering around large numeric offsets. Scores
  remain relative to the chosen normality reference, not ground-truth labels.
- The initial focused suite passed **2,618 checks**. Additional tiny-cost probes
  then exposed a shared solver issue: an alignment with priors 1e-9 and 2e-9
  could choose the smaller prior; a Steiner instance with optimal cost 2e-12
  could return cost 5e-12. The binary wrapper now reduces an exact rational
  objective grid when supported, otherwise normalizes coefficient scale, and
  converts solver evidence back to original units. Integer objective differences
  remain preserved. A second focused suite passed **2,626 checks**, including
  these regressions down to cost scale 1e-200 and a large-integer distinction.
- Latest complete reports: `cpu-comparison.xml` has **19,251 passes** with CUDA
  hidden; `gpu-0-comparison.xml` and `gpu-1-comparison.xml` each have **1,546
  passes**, with no failures or skips. All previous operations were rerun after
  the shared optimization change. New references enumerate tree edge subsets,
  all injective mappings for the graph-pair fixtures, edit-distance dynamic
  programs, all partitions for 729 signed four-record instances, and direct
  feature/score formulas. The final sweep includes 69 further feature and input
  boundary cases beyond the second focused report.
- Source/dependency/contract freshness, dependency consistency, lint, formatting
  and formal-contract synchronization pass. The audit points to the latest full
  reports; earlier focused reports are retained separately as historical evidence.
- The agent/browser is still on its native execution path. All remaining CPU,
  library-to-agent, family-routing, workflow, mode/UI, scheduling/cache, MCP,
  reviewed-example and external-scale requirements remain open.

### Typed workflows and application API checkpoint

- The application now calls the Python library through isolated workflow
  workers. New authenticated endpoints support Normal, Interactive and Expert
  execution policies, plan revisions, approval hashes, current-revision result
  access, port pagination and cancellation. The existing chat/browser and native
  job API remain on their earlier execution path; browser mode integration is
  still open. See `TYPED_ANALYTICS_WORKFLOWS.md` for the exact API and limits.
- All 59 operation cards declare possible output ports. DAG validation checks
  references, cycles, accepted parameters and binding types; execution checks
  actual port availability, completeness and graph identity. Original typed IDs
  survive dependent graph extraction. Failed dependencies are marked blocked
  while independent steps can complete.
- The capability endpoint and worker require current Python correctness
  evidence: report/metadata hashes, source/contract inventories and bytes,
  dependency/Python versions, complete test collection and audited profile
  hashes. The execution worker checks the reviewed plan and evidence again.
  Automatic steps lacking current GPU evidence use CPU. This gate covers the
  Python integrations; unification with native/research evidence remains open.
- A SQLite ledger saves immutable revision input snapshots and execution state.
  Approval is reset on every revision, including identical-content revisions.
  Trusted local successful steps can be reused only with matching resolved
  inputs, parameters, implementation/dependencies, device policy and result
  hash. Corrupt entries are recomputed. Restarted work is marked interrupted.
  This supplies manual affected-step recovery; automatic bounded recovery and
  graph-representation caching remain open.
- Worker process groups permit cancellation/deadlines during native calls.
  CPU workers hide CUDA devices. The current analytics queue is serial and uses
  the configured graph GPU when requested; memory-aware two-GPU scheduling and
  LLM memory admission remain open.
- Latest full reports: `cpu-workflows.xml` has **19,505 passes** with CUDA hidden;
  `gpu-0-workflows.xml` and `gpu-1-workflows.xml` each have **1,546 passes**, with
  no failures or skips. The 254 new focused checks include independent peeling
  and linear-algebra oracles for dependent workflows across atlas graphs through
  six vertices, malformed/type/cycle checks, incomplete collections, namespace
  errors, cache invalidation and evidence rejection.
- `agent-workflows.xml` has **15 passing checks** against the working tree;
  `agent-workflows-index.xml` has the same **15 passes** against the staged
  application sources. The report's source hashes match the staged Git blobs.
  These exercise the actual CPU library through the application,
  plus explicitly synthetic process/ledger fault injection. The checks cover
  three API modes, stale approvals/evidence, revision changes, numerical results,
  pagination, cancellation, deadlines, restart ownership, CPU isolation and reuse
  after a failed dependency. GPU workflows also ran serially on both physical
  devices, checking recorded device assignment and numerical results.
  Source/dependency metadata accompanies both reports.
- CPU algorithm coverage remains **57 of 70 problem contracts**, with **13 CPU
  integrations still required**. Native adaptation, family routing, natural
  language workflow planning, browser modes/visuals, deterministic queries/table
  construction, MCP, reviewed-example retrieval, memory-aware scheduling and
  external-scale evaluation all remain part of the active goal.

### Browser workspace and family routing checkpoint

- `/` now opens a library-backed workspace with Normal, Interactive and Expert
  modes. `/classic` retains the earlier native workspace. The new page uses
  local Cytoscape and plain JavaScript/CSS, with no Node runtime or build step.
  Its score/group charts, graph layouts, linked selection and paged tables are
  fixed renderers. A model cannot generate algorithm or visualization code on
  this path. This implements the interaction ideas using our own code; no
  YiGraph source or visual assets were copied.
- A family decision precedes exact-operation selection and typed workflow
  planning. Shortlists come from executable evidence-checked cards and accepted
  parameter schemas. One wrong-family reroute and one contract-based plan repair
  are allowed. Follow-ups receive the previous reviewed plan only within their
  current workspace. Planning does not approve or execute a workflow.
- Interactive plans expose step settings, dependency sources and input scope.
  Edits create a new revision requiring approval. Expert plans use the same
  engine and checks. Additional uploaded graphs can bind pattern/comparison
  parameters. Workspace changes clear previous results and pending plan text.
- Full result downloads preserve typed IDs and adjacent integers larger than
  JavaScript's safe integer range. Graph previews are bounded independently of
  computation. Outside-preview selections are disclosed; raw previews are
  labeled when shortened. Completed steps remain accessible after cancellation
  or interruption. Retained-output completeness is separate from table paging.
- Browser testing exposed a real completeness error: capped `k-cliques`
  enumeration had an incomplete groups port but a complete operation flag.
  The flag now propagates to triangle listing and workflows. Triangle listing's
  groups port is also declared in the capability schema. An independent
  combination oracle adds 106 cases across atlas graphs through five vertices.
- After the shared-library fix, the complete `cpu-workspace.xml` run passed
  **19,611 checks** with CUDA hidden. `gpu-0-workspace.xml` and
  `gpu-1-workspace.xml` each passed **1,546 checks** with no failures/skips.
  Both fixture shards and the repeated weighted/directed/boundary cases ran.
- `agent-workspace.xml` and `agent-workspace-index.xml` each passed **34
  checks**, including actual CPU/GPU execution, schema constraints, rerouting,
  bounded repair, follow-up isolation and failed-workflow step access. These
  reports include source/dependency snapshots. Planning decisions are authored
  test fixtures; this does not establish a real model's routing accuracy.
- `browser-workspace.xml` and `browser-workspace-index.xml` each passed **six
  Firefox checks** against the working tree and staged application sources,
  respectively. The server PATH contains no Node and the native executable is
  absent. Tests cover modes, approval/editing, dependent numerical results,
  lossless IDs and export, bounded preview/paging, cross-input pattern matching,
  workspace reset and the question-planning HTTP path. The latter uses an
  authored model transport. Desktop and narrow-screen screenshots were visually
  inspected. Two existing `/classic` browser regressions also passed on the
  working tree using their synthetic native executable fixture.
- CPU coverage remains **59 operations across 57 of 70 contracts**. Thirteen
  CPU integrations, native adaptation/unified evidence, deployed-model routing
  and conversation evaluation, deterministic queries/table construction, MCP,
  reviewed examples, memory-aware two-GPU scheduling, representation caching
  and external-scale validation remain part of the active goal. The earlier
  native workspace has not been migrated to the new execution policy.
