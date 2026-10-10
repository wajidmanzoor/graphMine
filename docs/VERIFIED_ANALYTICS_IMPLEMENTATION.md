# Verified CPU/GPU analytics implementation

Branch: `feat/verified-cpu-gpu-workflows`.

## Requested outcome

An interface through which people unfamiliar with graph mining can ask about
their data, select CPU-only, GPU-only, or automatic execution, and receive
results computed by declared library algorithms and predefined visualizations.
Normal, Interactive, and Expert modes share the same correctness checks.
Implement the useful review recommendations and commit the work on this branch.

**User architecture clarification (2026-10-10):** the executable algorithm core
must be C++/CUDA for both CPU and GPU. This includes the original native
implementations, direct native cuGraph integrations, and native equivalents of
the CPU capabilities reviewed in YiGraph. Python is a wrapper around this core,
with the same problem/family catalog, parameters and results. Existing Python
algorithm integrations are migration references and test oracles; their passing
tests do **not** satisfy the native CPU coverage requirement. Native migration
takes priority over adding further Python algorithm implementations.
The user also requires cuDF for tabular file loading and no NetworkX plotting.
The native reader therefore links libcudf; the Python wrapper calls that reader.
Browser rendering continues to use Cytoscape and predefined JavaScript views.

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
| A2 | C++/CUDA core: graph objects, algorithm families and backend dispatch; thin Python wrapper using the identical native catalog | Standalone C++ consumers and CLI run without Python; wrapper/core catalog and result parity; agent uses the native core |
| A3 | Native CPU implementation for all 70 problem contracts and fallbacks for existing operations | Per-contract native coverage inventory, independent result checks, CPU-only runs without GPU access; Python algorithms count only as reference evidence |
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

1. Preserve existing work and the Python reference oracles; establish the
   standalone C++/CUDA runtime, shared family catalog and thin Python binding.
2. Migrate CPU algorithms, cuGraph integrations and original native backends
   into that runtime with independent native checks and matching build evidence.
3. Connect native capabilities and cuDF ingestion to the agent, routing,
   queries, workflows, table projections, recovery, examples and MCP tools.
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

### Diffusion, layout and sparsification checkpoint

- Added three CPU profiles, bringing coverage to **62 executable operations
  across 60 of 70 problem contracts**. Influence maximization computes exact
  expectations and seed-set optima for independent cascade and linear threshold
  with explicit work budgets. Rational comparisons preserve differences hidden
  by rounded displayed expectations. Fixed thresholds, parallel edges and
  zero-threshold activation have declared semantics.
- Force-directed layout uses the explicit NetworkX Fruchterman–Reingold force
  method in 2D/3D and recomputes its distance-regularized potential and force
  residual. A one-iteration equation oracle includes the 500-vertex method-switch
  boundary. Fixed iteration count zero preserves supplied coordinates; null
  iteration limits and other force models are not advertised as supported.
  The browser displays computed coordinates with uniform scale and labels a
  3D result's XY projection while preserving all coordinates in the result.
- Static spectral sparsification uses effective-resistance sampling and
  importance reweighting. Grounded generalized eigenvalues check quadratic-form
  distortion across all vectors; numerical diagnostics are distinguished from
  the algebraic identity/zero cases. Exact component checks prevent a rounded
  zero eigenvalue from accepting a lost bridge under any strict epsilon<1
  target. Unmet targets and numerically unresolved systems are rejected.
- The new suite contributes **2,525 independent checks**: every three-vertex
  directed graph under both stochastic diffusion models, all 27 fixed-threshold
  assignments on those graphs, graph-atlas force/energy and spectral comparisons,
  typed IDs, tiny probability distinctions, resource failures and unsupported
  parameters. Uniform-threshold expectations are verified by integrating
  threshold intervals, independently of the live-edge implementation. Spectral
  references use an orthogonal eigenbasis rather than grounded solves.
- The full `cpu-diffusion-geometry.xml` run passed **22,136 tests** with GPUs
  hidden. Both `gpu-*-diffusion-geometry.xml` reports passed **1,546 tests** on
  their respective devices, with no failures/skips. The audit now references
  these reports; dependency and contract checks pass.
- Application/planner runs passed **34 tests** on both working-tree and staged
  application sources. Firefox runs passed **seven tests** on both versions,
  including the computed-coordinate view, with Node absent from the server PATH.
  Reports include source snapshots; the staged snapshots match Git's index.
  The authored model transport remains an integration test rather than an LLM
  accuracy result.
- The remaining CPU contracts are frequent subgraph mining, graph edit
  distance/maximum common subgraph, node embedding, knowledge-graph embedding,
  node prediction, graph prediction, geolocation, hypergraph node learning,
  single-graph frequent subgraph mining and graph condensation. Native
  adaptation, deployed-model evaluation, deterministic queries/table operations,
  MCP, reviewed examples, memory-aware scheduling, representation caching and
  external-scale evaluation remain open. The overall goal is not complete.

### Frequent-pattern and graph-collection checkpoint

- Added two exact CPU profiles, bringing coverage to **64 operations across
  62 of 70 problem contracts**. Transaction mining measures presence across
  graphs; single-graph mining measures minimum-image support over all vertex
  embeddings. The profiles retain their different definitions and input kinds.
  Neither has a fixed five/six-edge cap. Candidate, time and output exhaustion
  fail without a completed enumeration claim.
- Transaction mining preserves direction and selected categorical types, and
  includes disconnected patterns and isolates. Explicit vertex bounds can
  include the empty pattern. MNI mining requires an undirected labeled host and
  connected patterns, including singletons. Count-only output has no pattern
  collection port. Requested image sets preserve the original typed host IDs.
- Added public `GraphCollection` inputs, a JSON schema, API/browser upload kind,
  and bounded per-transaction planning context. Transactions keep separate
  vertex namespaces. The fixed `pattern_graph` selector supplies a canonical
  pattern to downstream library calculations with its own graph fingerprint.
  The predefined browser view displays the selected pattern and labels its
  local vertex IDs; it does not identify them with host vertices.
- igraph 1.0.0 supplies BLISS canonicalization, with edge subdivision encoding
  for selected edge types. MNI uses NetworkX VF2 embeddings. Full canonical
  keys deduplicate patterns; hashes only name results. Added igraph/texttable
  dependency pins and igraph version provenance; the README records igraph's
  GPL-2.0-or-later license.
- The new suite contributes **2,300 checks**, including all 64 four-vertex
  graphs with all 16 two-label assignments under both matching modes, directed
  transaction shapes, independent complete pattern universes, brute-force
  injection/image-set references, decimal support boundaries, transaction
  multiplicity, disconnected patterns, seven/eight-edge patterns, normalization,
  budgets and dependent pattern graphs. The initial fixture incorrectly reused
  one mutable graph object for two transaction IDs; independent fixture copies
  fixed it. The corrected focused suite passed before the full regression.
- `cpu-frequent-patterns.xml` passed **24,436 tests** with CUDA hidden.
  `gpu-0-frequent-patterns.xml` and `gpu-1-frequent-patterns.xml` each passed
  **1,546 tests** on their physical devices. All three reports have zero
  failures/skips and current source/contract/dependency snapshots. The audit
  now references them. GPU coverage remains **13 cuGraph profiles**; the two
  new mining profiles are CPU integrations.
- Application/planner reports passed **39 tests** on both working-tree and
  staged application sources. Firefox reports passed **nine tests** on each
  source version, with Node absent from the server PATH. These cover graph-collection
  upload, pattern-specific views, pattern-to-degree workflows, MNI image IDs,
  count-only output, and all previous workspace cases. Authored model decisions
  remain transport/schema integration evidence, not deployed-model accuracy.
- Eight CPU contracts remain: graph edit distance/maximum common subgraph,
  node embedding, knowledge-graph embedding, node prediction, graph prediction,
  geolocation, hypergraph node learning and graph condensation. Native
  adaptation, deterministic queries/table construction, MCP, reviewed examples,
  deployed-model evaluation, memory-aware two-GPU scheduling, representation
  caching and external-scale validation remain open. This checkpoint does not
  complete the overall goal.

### Exact graph-comparison checkpoint

- Added `graph-edit-distance` and `maximum-common-subgraph`, bringing CPU
  coverage to **66 operations across 63 of 70 problem contracts**. Both preserve
  direction and selected categorical labels, with explicit loop/parallel-edge
  normalization. Their exact profiles have work budgets and no fixed small
  vertex ceiling. Approximate modes, custom predicates and timed incumbent
  results are not advertised.
- Edit distance uses NetworkX shortest paths on a rational correspondence-state
  DAG, with matching/isomorphism fast paths. Decimal cost differences and large
  integers survive optimization. Its rational cost port preserves numerator
  and denominator; a rounded browser value is marked with `≈` and cannot
  implicitly supply an ordinary numeric workflow parameter.
- Ordered edit scripts retain stable handles, source/target records, original
  typed IDs and exact per-edit charges. Independent replay checks endpoint
  existence, ID swaps, final graph reconstruction and total cost. Inserted and
  deleted vertices also appear in the complete correspondence.
- MCS maximizes vertex count. Its induced variant uses VF2; the non-induced
  variant allows disconnected/edgeless results and uses maximum label matching.
  It does not claim to maximize common edges. The graph port is a usable
  downstream input. A discovered identity collision was fixed by incorporating
  both parent fingerprints; workflow tests reject vertex bindings between
  otherwise identical-looking results from separate datasets.
- The comparison suite adds **4,662 checks**, including all 361 pairs of
  atlas graphs through four vertices, all 4,096 pairs of three-vertex directed
  graphs, both MCS modes, varied labels and edit costs, zero/large/tiny costs,
  typed identities, normalization and budget failures. Independent references
  enumerate partial injections without the production matching/path routines.
- `cpu-graph-pair.xml` passed **29,098 tests** with GPUs hidden.
  `gpu-0-graph-pair.xml` and `gpu-1-graph-pair.xml` each passed **1,546 tests** on
  their physical GPUs. No failures or skips occurred. The regenerated audit
  confirms current source, contract and dependency snapshots. GPU coverage
  remains **13 cuGraph profiles**; these two comparison integrations use CPU.
- API/planner runs passed **40 tests** on both working-tree and staged
  application sources. Firefox runs passed **10 tests** on both versions, with
  Node absent from the server PATH. They verify exact-cost transport/display,
  edit-script paging, common-subgraph workflows and all prior workspace cases.
  Final screenshots were inspected, and indexed sources match the recorded
  staged snapshots. The model transport remains authored integration evidence,
  not a deployed-model accuracy measurement.
- Seven CPU contracts remain: node embedding, knowledge-graph embedding,
  node prediction, graph prediction, geolocation, hypergraph node learning and
  graph condensation. Native adaptation, deterministic queries/table
  construction, MCP, reviewed examples, deployed-model evaluation,
  memory-aware two-GPU scheduling, representation caching and external-scale
  validation remain open. The overall goal remains active.

### Review integration resumed: canonical record queries

The resumed user goal is to finish the review-based integration on this feature
branch. The A1–A7, R1–R11 and B1–B4 requirements above remain the acceptance
scope; algorithm coverage alone does not complete it. The review's P0 query
and workflow-evaluation gaps take priority in the resumed work.

- Added seven CPU utilities: `node-lookup`, `edge-filter`, `neighbors`,
  `common-neighbors`, `query-paths`, `graph-aggregate` and `query-subgraph`.
  Their contracts are documented in `RECORD_QUERIES.md` and advertised in
  the new **Look up & summarize records** family. CPU problem coverage remains
  **66 algorithm operations across 63 of 70 formal problems**; the seven
  utilities are counted separately. The total executable CPU operation count
  is now **73**. GPU coverage remains **13 cuGraph profiles**.
- Literal nested predicates and actual input fields are validated before
  queueing; derived records are checked at execution. Original typed vertex
  and edge IDs, parallel records, loops, direction and attributes survive
  filtering and extraction. New edge-ID ports bind only to the same source
  graph. Graph fingerprints and completeness checks continue through dependent
  query-to-algorithm workflows.
- Aggregates retain exact rational values, including decimal sums and averages
  and integers beyond JavaScript's safe range. Top-vertex workflow selection
  and chart ordering use those values. The browser marks rounded displays and
  links lookup rows to their original vertices. Capped output retains exact
  counts, remains incomplete, and offers narrowing guidance.
- The final CPU regression passed **29,769 tests**, including **671 query
  checks**, with GPUs hidden. Both GPU shards passed **1,546 tests** each.
  Reports are `cpu-record-queries.xml` and `gpu-*-record-queries.xml`; no failures
  or skips occurred, sources stayed unchanged during execution, and the updated
  capability audit verifies all source/contract/dependency hashes. Oracles cover
  exhaustive small directed path and neighbor universes, parallel/loop/typed-ID
  cases, exact expected aggregates, cross-dataset rejection, empty scopes and
  schema/default mutation isolation.
- Review found two scope defects after the first focused run: neighborhood
  extraction originally applied explicit edge IDs only to output, and vertex-
  record aggregation initialized groups before filtering. Both were reproduced,
  repaired and covered by new regression cases. The initial CPU sweep was
  deliberately stopped; it is not acceptance evidence. Final reports above
  test the repaired sources.
- API/planner/evaluation acceptance passed **54 tests** on both the working
  tree and the staged application. This includes real CPU/GPU workers, all
  three execution modes, query-to-graph-to-algorithm dependencies, pagination,
  preflight rejection and the original workflow/route regressions.
- Firefox acceptance passed **12 tests** on both the working tree and staged
  application, with Node absent from the server PATH. Final result screenshots
  confirm typed-ID row linking, graph selection, exact aggregate fractions and
  marked rounded displays. A stale-result wait in the new browser test was
  corrected before these final runs. Indexed sources match the recorded staged
  snapshots; all final reports have zero failures and skips.
- Added 20 assistant-authored development probes under
  `graphmine_agent.learning.analytics_queries`: ten lookups and ten dependent
  workflows sharing a small fictional fixture. The isolated reference replay
  passed **20/20**, with operation, normalized-parameter, wiring, completion and
  output-value grading. The grader rejects ID-type changes, truncation,
  mismatched parameters and extra operations. This is application execution
  evidence, not real-model accuracy, human labels, held-out or external-benchmark
  evidence. No training data was changed. `--mode model` requires an explicitly
  enabled model endpoint and retains the planning trace.

Remaining review work includes joins and multi-table construction (R2/R8),
additional workflow selection/clarification behavior (R1/R5), richer operation
cards and schema mapping (R3), automatic bounded affected-step recovery (R6),
per-port planning summaries (R7), deployed-model and external evaluation (R9),
MCP and its client guide (R10), and approved-example retrieval (R11). Seven CPU
problem integrations, native/unified evidence, scheduler/cache work and scale
verification remain required under A3/B1–B4. Existing browser modes, routing
and workflow execution are implemented, but their remaining review acceptance
details must still be verified before the overall goal can be complete.

### Standalone native runtime and cuDF checkpoint

The user's C++/CUDA clarification replaces the Python-first implementation
sequence. This checkpoint establishes the native boundary; it does not count
the existing Python implementations as native CPU coverage.

- Added `libgraphmine_runtime`, a public C++ API, a versioned C ABI and the
  standalone `graphmine-native` executable. Installed C and C++ consumers run
  without Python on PATH and with GPUs hidden. The CPU shared library has no
  Python or CUDA linkage. Original `Graph` storage and native triangle backends
  are reused.
- One embedded taxonomy assigns all 70 formal problems and record queries to
  31 families. The thin Python binding obtains operations, parameters and
  family membership from that native catalog. CPU/GPU selection and algorithm
  execution occur inside C++. Unmigrated problems remain explicitly pending.
- Native CPU breadth-first search and triangle counting are implemented.
  BFS calls libcugraph directly on GPU; triangle counting links the original
  ToT and WeTriC CUDA backends. This is **2 of 70 formal problems** in the new
  shared runtime, not a claim about the coverage of older native entry points.
- Native oracle requests passed: **13 contract checks**, **4,608 BFS and 2,048
  triangle requests on CPU**, **4,608 BFS and 2,048 ToT requests on GPU 0**, and
  **4,608 BFS and 2,048 WeTriC requests on GPU 1**. BFS uses independent all-pairs
  distance oracles over exhaustive small graphs; triangles use brute-force
  triple enumeration over all 1,024 undirected five-vertex graphs.
- Fixed libcugraph's effective unlimited-depth bound, which had wrapped when
  passed as `SIZE_MAX`, and suppressed original ToT timing prints only when
  compiled into the library so CLI stdout remains valid JSON. GPU calls restore
  the caller's device selection. Final original-backend checks ran against an
  export of exactly the staged sources, including the selective root CMake
  changes; unrelated working-tree repairs were preserved.
- Refreshed the existing Python reference inventory after adding the wrapper:
  **29,769 CPU tests and 1,546 tests on each GPU passed**, with zero skips and
  unchanged source/contract snapshots. Reports are `cpu-native-wrapper.xml`
  and `gpu-*-native-wrapper.xml`. These keep the current application's reference
  gate consistent while migration proceeds; they do not add native coverage.
- The libcudf CSV reader preserves string IDs, large numeric text, quoted
  fields, multiline values and Unicode. It enforces declared columns and row
  limits and reports explicit failure when cuDF is unavailable. **19 binding
  and ingestion tests passed**, including both GPUs, standalone CLI parity,
  concurrent calls, original-backend stdout and device restoration. No
  NetworkX plotting was added; rendering remains in the existing browser views.
- Native evidence is recorded under `validation/native_runtime/` and audited
  in `catalog/native_runtime_coverage.json`. It includes source inventories,
  binary and resolved native dependency hashes. This inventory is not yet the
  application's execution gate. Build and usage instructions are in
  `NATIVE_CORE_MIGRATION.md`.

The existing public `graphmine.run`, application worker and web upload endpoint
still await native migration. Remaining work includes all other profiles,
native exact-number support for rational operations, cuDF-backed table
construction, application evidence gating, and the open review requirements
above. The overall goal remains incomplete.
