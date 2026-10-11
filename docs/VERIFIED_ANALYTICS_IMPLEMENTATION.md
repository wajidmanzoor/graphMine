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

### Native cuDF uploads and C++ graph construction

- CSV and edge-list uploads now invoke the libcudf-enabled native executable
  through a bounded isolated process. The Python CSV parser and Python graph
  construction routines were removed from this path. The native CLI, thin
  binding and application share the same reader and construction contract.
  Existing Cytoscape/browser views continue to render results without NetworkX.
- cuDF handles file access and GPU parsing, including headers. C++ validates
  UTF-8, quote structure and record widths before parsing, since cuDF otherwise
  tolerates and discards excess fields. Original header names must be nonempty
  and unique. CSV values remain strings until the declared compatibility
  construction profile maps them to canonical graph records.
- Construction preserves lexical IDs, labels, types, scalar attributes,
  parallel records and loops; it checks conflicting vertex attributes,
  duplicate edge IDs and native numeric bounds. Explicit string-ID mode is
  available through the native API. Headers, comments, tab/space/comma edge
  lists and optional weight/timestamp fields are supported. Input hashes,
  implementation hashes and resolved mapping stay in provenance.
- A tab-separated regression exposed cuDF's whitespace delimiter behavior;
  tabs are now normalized only outside quoted fields. Strict reader tests
  reproduce excess/missing columns, malformed quotes, invalid UTF-8 and lossy
  integer conversion. **64 native ingestion/construction tests and 19 binding
  tests passed**, without skips. The staged native build also passed all
  **19,981 CPU/GPU oracle requests** from the prior checkpoint, and installed
  C/C++ consumers ran without Python or CUDA dependencies in the CPU core.
- Application acceptance passed **41 tests in the working tree and 25 in the
  exact staged app**, including real cuDF uploads, API graph previews, failure
  cleanup and timeout/result-size bounds. The working tree additionally retains
  16 pre-existing streaming tests. Source, configuration and binary snapshots
  stayed unchanged during the passing runs.
- Clean staged startup exposed an existing inconsistency: the committed
  densest-subgraph instructions lacked `clique_order` and `clique_count`, which
  the committed manifest already required. Only these output names were
  synchronized; the other uncommitted catalog repairs were preserved.
- Reference evidence was refreshed for the wrapper update: **29,769 CPU tests
  and 1,546 tests on each GPU passed**, with matching source, contract and
  dependency hashes. This remains reference evidence, separate from native
  algorithm coverage. Latest reports are under `validation/native_ingestion`
  and `validation/python_analytics/*-native-ingestion*`; the native audit records
  build configuration, resolved dependency hashes and the staged app sources.

This completes the cuDF upload path for the current bounded delimited-file
profile. Native formal-problem integration remains **2 of 70** in the shared
runtime. The public reference algorithm API and application algorithm worker,
other native backends, exact-number support, multi-table/task-aware projections
and all other open review acceptance requirements still need migration or
completion. The overall goal remains active.

### Native reference algorithms and numeric input boundaries

- Added native C++ CPU profiles for single-/many-source weighted paths,
  minimum/maximum spanning forests, weak/strong connected components,
  topological sort, PageRank, personalized PageRank and all eight local link
  scores. Alongside BFS and triangles, **10 of 70 formal problems now have
  profiles in the shared runtime**. Other profiles of those problems and the
  remaining formal problems still require migration.
- Weighted paths, forests, both connectivity modes, PageRank, supported
  personalized variants and Jaccard call libcugraph directly through its C API.
  Unsupported GPU variants select native CPU in auto mode with a reason;
  explicit GPU requests fail. The same registered definitions provide native
  dispatch, capability cards and Python family methods.
- CPU path costs and forest totals use exact rationals over admitted binary64
  weights, with exact fields and explicit rounded displays. Reachable values
  above floating range remain rational objects rather than null/unreachable.
  Large integer cutoff values retain their exact value. Native input storage
  still needs wider ID/integer/rational support before the remaining exact
  query and graph-comparison profiles can migrate.
- Raw JSON validation now rejects overflowing integer literals before
  Boost.JSON can convert them to doubles, and rejects duplicate/escaped
  duplicate keys. Both native requests and CLI graph/parameter files use this
  boundary. This prevents distinct oversized integers from collapsing to an
  identical graph fingerprint.
- Exhaustive GPU testing reproduced a libcugraph SSSP stall on one directed
  zero-weight edge. All-zero length graphs now use native GPU BFS reachability
  with exact zero distances. Mixed lengths still use libcugraph SSSP, with
  an acyclic tight-edge witness tree and explicit cost bounds. GPU forests use
  weight-order ranks to avoid upstream arithmetic overflow without changing
  the optimal edge order. PageRank independently verifies its residual and
  keeps full score ports complete when only its displayed ranking is capped.
- **39,231 native oracle requests passed** against frozen standalone CPU and
  exact staged GPU builds, including both physical GPUs and the original
  ToT/WeTriC regressions. Oracles use independent shortest-path matrices,
  exhaustive edge subsets, connectivity/witness checks, dense linear solves
  and local adjacency formulas. **30 binding/CLI, 64 native ingestion, 41
  working-app and 25 staged-app tests passed**, with no skips or failures.
  Installed C/C++ consumers run without Python or CUDA on the CPU path.
- Reports are under `validation/native_reference`; the audit checks source,
  binary, configuration and resolved dependency hashes and updates
  `catalog/native_runtime_coverage.json`. Existing Python reference package
  sources were unchanged, so their prior matching evidence remains applicable.

The application's algorithm worker and public reference API still await the
native migration. This checkpoint does not complete the overall goal. Keep
the remaining native profiles/backends, native evidence gate, seven missing
formal integrations, table projections/joins, interaction and recovery work,
external/model evaluation, MCP/examples, two-GPU scheduling/caching and scale
validation in scope.


### Native mining integration checkpoint

- The standalone core now implements profiles for **16 of 70 formal problems**.
  Added native C++ maximal cliques, maximum clique, fixed-size clique counting
  and enumeration, core decomposition, maximum independent set and minimum
  vertex cover. The same native catalog supplies Python family methods and
  parameter/result contracts. CPU search, complement construction and output
  materialization have explicit candidate, output and deadline budgets.
- Linked ten original GPU implementations directly into the shared runtime:
  RDMCE, MCE-GPU, G2-AIMD, CUDA-MS, GPUMaximumClique,
  Maximum-Clique-on-GPU, GraphSet, GAMMA, KCGPU and KCoreGPU. Added the native
  libcugraph core-number API. Maximum witnesses receive a native optimality
  check; count kernels retain bounded C++ materialization where requested.
  Incomplete memberships cannot claim to be complete workflow inputs.
- Integrated the existing KCGPU depth/Pascal-table repair and GAMMA comparison
  and synchronization repairs. Added backend-specific clique-order and count
  admission, isolated-vertex handling, clean CLI JSON, library-safe error
  helpers and device restoration. Core-number tests caught double-counted
  undirected degrees in the initial cuGraph call; outgoing degree fixes it.
- The strengthened wrapper comparison caught shared inline build metadata
  mixing CPU and GPU provenance. Catalog/hash data now belongs to each DSO.
  A mixed-backend regression also caught GAMMA's redundant Thrust root filter
  failing after GraphSet. Eligible roots now come from the native CSR, with
  both backend orders/device orders exercised by the wrapper tests. Initial
  failed binding reports are retained alongside corrected acceptance evidence.
- Installed C and C++ examples now execute algorithms with Python unavailable
  and CUDA hidden. The root CMake build was exported from the exact index;
  unrelated pre-existing working changes were preserved. The evidence audit
  permits a differing working root build file only when the tested export
  matches the index exactly.

- Final acceptance: **83,624 native requests passed** (45,872 CPU;
  18,876 per GPU), plus **8 depth/admission checks**, **88 binding/CLI tests**,
  **64 cuDF construction tests**, and **41 working-app / 25 staged-app tests**.
  K514 memcheck and K12 seven-clique racecheck reported no errors or hazards on
  either GPU. Installed C/C++ algorithm calls passed without Python or CUDA.
  There are no skipped acceptance cases; the app reports retain the existing
  Starlette deprecation warning.

Acceptance reports for this checkpoint are under `validation/native_mining`;
`catalog/native_runtime_coverage.json` records their source, binary, dependency
and device evidence. These reports are a migration checkpoint, not an
application execution gate or a claim that the whole goal is complete.

Remaining requirements include native profiles for the other **54 formal
problems**, remaining profiles/backends within the sixteen integrated problems,
extended exact numeric storage, the native application worker and evidence
gate, plus all unfinished A/R/B items above: task-aware projections and joins,
interaction/routing/recovery, model/external evaluation, MCP and reviewed
examples, two-GPU admission/cancellation, reusable representations and scale
validation. cuDF remains the tabular reader and Cytoscape remains the browser
visualization path. The overall goal remains active.


### Native structure and centrality checkpoint

- The standalone core now exposes **20 operations covering profiles for 18 of
  70 formal problems**. New C++ implementations cover biconnected edge blocks,
  full truss decomposition, degree centrality and exact all-source betweenness.
  Direct native libcugraph adds truss extraction and betweenness; original
  TurboBC is linked through the same C++/CUDA runtime.
- Biconnected outputs include edge blocks, cut vertices, bridges and isolates.
  Truss results include all per-edge numbers, the maximum truss number and
  optional selection. Both retain original IDs when collapsing parallel edges.
  Degree and betweenness expose full scores and rankings; PageRank also gains
  the formal ranking and score-definition outputs. CPU betweenness uses exact
  rational arithmetic over admitted binary64 lengths and unbounded path counts.
- GPU betweenness remains an unweighted numerical profile. Normalization is
  consistent across C++, libcugraph and TurboBC; precision is disclosed. Native
  admission checks reject shortest-path counts beyond signed int32 capacity.
  This prevents a reproduced libcugraph error on a 66-vertex layered graph:
  the unguarded raw-score sum was 21,609 instead of 21,857. Auto selection uses
  exact C++ for that input; explicit GPU requests report unsupported input.
- Full regression evidence contains **125,924 passing native requests**
  (68,344 CPU, 28,790 per GPU), **8 original mining depth/admission checks**,
  **8 centrality sanitizer runs**, **104 binding/CLI tests**, **64 native cuDF
  construction tests**, and **41 working-app / 25 staged-app acceptance tests**.
  CUDA memcheck/initcheck report zero errors on both centrality backends and
  both devices. The app tests retain the existing Starlette warning.
- Independent oracles enumerate edge subsets and simple paths. Larger checks
  include a 20,000-vertex path, K64 and layered graphs with enormous path counts;
  typed IDs, reordered vertex records, duplicate edges, strict parameters and
  budgets are exercised. Installed C/C++ consumers run without Python on PATH
  or visible CUDA devices. Source, binary and dependency snapshots are checked;
  all 1,023 GPU source hashes match the exact Git index.

Reports are under `validation/native_structure`, including the retained
pre-admission failure. `catalog/native_runtime_coverage.json` records the
current native evidence. The Python wrapper obtains the same family catalog
and results from the core. Tabular ingestion remains native cuDF and browser
rendering remains Cytoscape.

The goal remains **active**. Required work includes native coverage for the
remaining **52 formal problems**, unimplemented contract variants within
migrated problems, migration of the reference API/application algorithm
worker, and all unfinished A/R/B requirements above. Passing native profile
checks does not establish completion of the full formal contracts or the
review integration.

### Native matching and flow checkpoint

- The standalone C++/CUDA core now exposes **23 operations covering profiles
  for 21 of 70 formal problems**. New CPU implementations provide general
  maximum-weight matching, bipartite cardinality/weight/cost matching, and
  maximum flow/minimum cut. The Python wrapper obtains these operations from
  the same native family catalog and invokes the same C ABI.
- Weighted Blossom uses checked exact integer scaling of admitted binary64
  weights. Bipartite matching uses exact residual costs and explicitly reports
  infeasible required coverage. Both preserve selected original edge IDs.
  Iterative exact Dinic supports fractional capacities, exact parallel sums,
  undirected arcs, and optional typed-ID vertex capacities, including terminal
  limits. Mixed edge/vertex cut certificates are now defined consistently in
  the authoritative flow contract and its four embedded copies.
- Original ECL-MaxFlow and Hungarian CUDA kernels execute in isolated native
  workers. Their profiles disclose integral capacity/cost, size, and objective
  restrictions. C++ certifies flow conservation/cut equality and assignment
  optimality. Worker failures are explicit; precise deadlines kill and reap
  workers. Unsupported variants can select native CPU before a GPU run starts.
- Installed CPU C/C++ consumers execute with Python off PATH and CUDA hidden.
  Installed CUDA CLI calls execute without Python on PATH; process traces
  confirm that installed native workers are selected. Installed wrapper/CLI
  parity is checked for both new GPU backends on both GPUs.
- A malformed-boolean GPU admission mismatch was corrected. A 20,000-vertex
  GPU flow path passes normally but exceeds the default 60-second deadline
  under memcheck. That instrumented timeout is retained as a known limitation;
  kernel memory/initialization checks separately exercise 256-vertex residual
  networks, the 1e9 capacity limit, and 64-by-64 assignment matrices.

Final acceptance: **167,891 native requests passed** (106,671 CPU and 30,610
on each GPU), including 12,740 CPU matching and 25,587 CPU flow checks. Each GPU
passes 751 assignment and 1,069 flow checks. There are **16 optimization kernel
sanitizer checks**, **8 centrality sanitizer runs**, **8 mining depth/admission
checks**, **117 binding/CLI tests**, **64 cuDF construction tests**, and **41
working-app / 25 staged-app tests**. The app reports retain the existing
Starlette warning; acceptance has no failures or skips. Installed GPU worker
traces and wrapper parity cover four backend/device combinations.

Reports are under `validation/native_optimization`.
`catalog/native_runtime_coverage.json` checks all report snapshots, 49 CPU and
1,060 GPU source files, nine CPU and eleven GPU binaries, generated worker
sources, and 32 resolved native dependencies. All GPU source hashes match the
exact Git index. The 169 pre-existing tracked modifications remain preserved.

The remaining **49 formal problems**, unfinished variants within migrated
problems, the native application worker/evidence gate, and the remaining A/R/B
requirements still need implementation and verification. The overall review
integration goal remains active.

### Native selection and sampling checkpoint (2026-10-11)

- The standalone core now exposes **28 operations covering supported profiles
  for 26 of 70 formal problems**. The five additions are maximal independent
  sets, vertex coloring, random walks, neighborhood sampling and induced/ego
  subgraphs. Their family methods come from the same native catalog in C++,
  the CLI and the thin Python wrapper.
- Maximal independent sets are verified for independence and maximality.
  Distance-1 and distance-2 colorings are verified on their conflict graphs;
  minimum color count is not claimed. Both have C++ CPU and direct libcugraph
  C++ implementations, preserve isolates and declare their simple projection.
- C++ walks and sampling use exact rational weights and integer rejection
  sampling. Walks retain direction, loops and repeated starts; GPU uniform
  and weighted walks use native libcugraph. Weighted node2vec, typed fanouts,
  replacement and exact temporal sampling are native CPU profiles. Unsupported
  explicit GPU variants fail; automatic selection records its CPU choice.
- Subgraphs retain original typed IDs, parallel records and nested properties.
  Ego discovery supports incoming/outgoing/undirected traversal. Derived graph
  ports now carry a fingerprint of the returned graph alongside input lineage,
  verified by chaining another native operation on that output.
- The new independent suites passed **50,950 requests**: **22,402 CPU** and
  **14,274 per GPU**. They cover exhaustive small graphs, seeded probability
  checks, exact timestamps, resource limits and a 257-vertex path plus an
  isolate. Four new CUDA memory/initialization runs passed; the 32 existing
  mining/centrality/optimization sanitizer or admission checks also passed.
- **139 binding/CLI checks**, **64 native cuDF construction checks**, and
  **41 working-app / 25 staged-app checks** passed without failures or skips.
  The app suites retain the existing Starlette deprecation warning. Installed
  C/C++ consumers run without Python or visible CUDA; installed optimization
  workers and wrapper parity pass on both GPUs.

Final acceptance, including all prior native regressions: **218,841 requests
passed** (**129,073 CPU**, **44,884 per GPU**). The complete source, binary,
dependency and report audit passed and updated
`catalog/native_runtime_coverage.json`. No acceptance checks failed or skipped.

Reports are under `validation/native_selection`. The source inventory covers
58 CPU files, 1,069 GPU files and 32 resolved native dependencies. The isolated
GPU build uses the committed root build configuration and preserves unrelated
working changes.

The remaining **44 formal problems**, unimplemented variants within migrated
problems, the native application algorithm worker/evidence gate, and the
remaining routing, recovery, table projection, MCP, reviewed-example,
scheduling/cache and scale-evaluation requirements remain open. This is a
native library checkpoint, not completion of the full redesign.
