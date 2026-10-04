# Algorithm and agent catalog expansion — 2026-10-04

The agent now recognizes **all 37 problem definitions**. It exposes **18
operations covering 17 problem families**; the other **20 families** remain
recognized but unavailable. The runtime registers 31 backend choices. Existing
agent exclusions for CUDA-MS and Maximum-Clique-on-GPU are preserved.

## Why five runnable additions?

The new research collection contains **17 problem definitions**, with **37 paper
records and 19 local code snapshots** across those definitions. A problem
definition or paper is not itself a runnable, correct implementation.

The artifact screening recorded five validated profiles, four correctness
failures, four partial passes, four build blockers, two artifacts that do not
implement the requested contract, and 18 paper records without local code.
The null-model significance definition has no paper/code artifact to screen.
These counts describe artifacts; several artifacts belong to the same problem.

Only the five bounded profiles below cleared the public-library correctness
gate. Partial passes establish only the checks actually performed. For example,
correct scalar flow values do not validate a required flow/cut certificate,
and a few passing influence simulations do not establish the requested quality
guarantee. The [screening report](../validation/gpu_correctness_expansion/VALIDATION_REPORT.md)
retains failures, dependency blockers, raw results and promotion evidence.

## Executable profiles

| Agent operation | Backend | Supported meaning and limits |
|---|---|---|
| `connected-components` | ECL-SCC | Exact weak or strong connectivity; choose `connectivity_mode` explicitly. Directed or undirected input; canonical component labels and sizes. |
| `max-flow-min-cut` | ECL-MaxFlow | Directed flow between two different existing vertices; nonnegative integer edge capacities; total non-loop capacity at most 1 billion. Returns a certified flow/cut. No vertex capacities or fractional capacities. |
| `linear-assignment` | HungarianGPU | Minimum-cost perfect assignment only. Complete square undirected bipartite graph, at most 64 entities per side, integer costs 0–999. No sparse, rectangular, maximum-weight or general matching mode. |
| `transitive-closure` | GDlog | Full materialized directed reachability, including reflexive pairs, on at most 1,024 vertices. No reusable index or separate query mode. |
| `butterfly-counting` | GraphMiner | Exact global count on an undirected bipartite graph. No per-vertex/per-edge counts or alpha/beta-core decomposition. |

Assignment and butterfly input must declare `attributes.side` as `left` or
`right` on every vertex. Edges must cross the two sides. The agent does not guess
side labels or silently drop invalid relationships. Expansion inputs are also
bounded to 1 million vertices and 10 million input edges, with the tighter
assignment and closure limits taking precedence.

The [native API guide](../library/docs/validated_expansion.md) describes C++ types,
normalization, CLI usage, isolated workers and installation. Source commits,
hashes and licenses are preserved in
[PROVENANCE.json](../library/src/backends/expansion/upstream/PROVENANCE.json)
and [THIRD_PARTY.md](../THIRD_PARTY.md).

## Routing, planning and results

`graphmine_catalog.json` embeds every formal problem specification exactly.
Its `library_support` records distinguish availability from the narrower
executable profiles and retain the screening reason for an unavailable family.
The router receives those profiles together with all 37 problem identities.
The broader research specification does not authorize unsupported modes.

`agent/program_instructions.json` is the executable parameter allowlist.
Connectivity mode and flow endpoints are required semantic inputs. Integer and
string IDs remain distinct: the string ID `"0"` is not the integer ID `0`.
Missing required inputs produce clarification; invalid profiles cannot execute.
New operations use the existing selector's single-backend fallback. No new
performance ranking is claimed.

For flow or assignment, an explicitly selected `weight_attribute` such as
`attributes.capacity` or `attributes.cost` is copied into the native edge
`weight` field **after filtering**, only in the job's execution copy. Use
`weight_usage=other` for these meanings. The original upload is retained.
If no field is selected, the native `weight` field is used. Missing, negative,
fractional or out-of-range values are not guessed, rounded or rescaled.
`unit_capacity=true` is allowed only for an explicitly requested all-ones flow;
it cannot replace a request to use supplied capacities. Other operations still
do not gain weighted centrality, path lengths or weighted community detection.

Directed flow, directed closure and strong connectivity preserve edge direction.
Weak connectivity deliberately ignores direction. The expansion operations do
not accept the generic directed-to-undirected projection flag.

The agent never exposes `worker_directory` or arbitrary executable paths to a
model. It sets the worker timeout to at most 60 seconds and the job deadline,
and keeps workers in the job's process group so cancellation terminates them.
Standalone native callers retain isolated worker groups and native timeouts.

Computed answers now include component groups, flow/cut values, assignment
pairs and costs, reachability counts and butterfly counts. Claims come from
native results and original records; profile limitations remain visible.

## Does this require LLM training?

**No training is inherently required to add a library tool.** The base model is
given the updated problem catalog, profile restrictions and parameter schema at
inference time. Native algorithms, validation, execution and result checks are
implemented in code.

The existing routing adapter was evaluated with an older 20-problem prompt.
Its frozen prompt, schema and weight binding are preserved. An expanded catalog
marked `expanded-37-v1` is deliberately routed through the base model, even if a
legacy adapter URL is configured. This is an explicit contract choice, not an
adapter-error fallback. Deployment/status metadata reports the actual router.
Legacy requests retain the existing adapter identity checks. The updated adapter
server rejects expanded-contract requests instead of claiming coverage it lacks.

No weights were changed and no training or model deployment was started. The
local model endpoint was offline during this integration, so **new
natural-language routing accuracy has not been measured**. The old adapter
scores do not apply to the expanded catalog. Evaluate the new cases first;
consider fine-tuning only if measured routing/planning errors persist after
improving the tool descriptions and examples.

## Verification and reproduction

The public native replay passed 99/99 correctness and rejection checks on the
packaged CLI. All 337 agent tests pass, as do 22 native CUDA regressions and five tests with
CUDA disabled. Agent tests cover schema allowlists, typed IDs, weight mapping,
profile limits, base-versus-adapter routing, actual GPU execution through the API,
grounded answers and worker cancellation. See the integration evidence in
[the verification report](../validation/agent_catalog_expansion/REPORT.md).

```bash
node tools/build_catalog.mjs
cmake -S library -B library/build -DCMAKE_BUILD_TYPE=Release
cmake --build library/build --target graphmine_cli graphmine_validated_expansion_test -j4
python3 validation/gpu_correctness_expansion/validate_library.py library/build/graphmine
GRAPHMINE_EXPANSION_TEST_BINARY="$PWD/library/build/graphmine" \
  .venv/bin/python -m pytest agent/tests -q
ctest --test-dir library/build --output-on-failure
```

The native replay requires NumPy, SciPy and NetworkX. Optional Kokkos backends
still need their documented dependencies. Workers default to the validated Ada
SM89 architecture; other architectures require their own build and validation.

The separate [66-case expansion holdout](../agent/evaluation/expansion_query_cases.json)
covers each new operation in all nine domains, all 12 unavailable new families,
and nine unsupported variants. It is evaluation-only. Historical v1 datasets,
training files and reports are unchanged; their original scope is recorded in
[legacy_catalog_scope.json](../agent/evaluation/legacy_catalog_scope.json).
When the configured base model is running, evaluate the new routing set with:

```bash
GRAPHMINE_LLM_ENABLED=true .venv/bin/graphmine-agent evaluate-routing \
  --cases agent/evaluation/expansion_query_cases.json \
  --split expansion_held_out_evaluation \
  --output agent/evaluation/reports/expansion-routing.json
```

Offline mode supports exact problem/operation names with explicit API parameters;
it does not certify natural-language routing quality.

## Status of all 17 added problem definitions

| Problem | Agent availability | Artifact screening |
|---|---|---|
| [Personalized PageRank and Random Walk with Restart](../problems/21_personalized_pagerank_rwr/problem.json) | Recognized; unavailable | `2020_kpar`: correctness fail |
| [Maximum Flow and Minimum s-t Cut](../problems/22_max_flow_min_cut/problem.json) | `max-flow-min-cut` | `2025_ecl_maxflow`: validated profile; `2025_generalized_maxflow_gpu`: no local code; `2025_wbpr`: partial pass |
| [Butterfly Counting and (alpha,beta)-Core Decomposition on Bipartite Graphs](../problems/23_butterfly_counting_bipartite/problem.json) | `butterfly-counting` | `2022_g2miner_reuse`: validated profile; `2022_gamma_reuse`: correctness fail; `2022_gbfc`: no local code; `2024_gbc_biclique`: no local code |
| [Graph Edit Distance and Maximum Common Subgraph](../problems/24_graph_edit_distance_mcs/problem.json) | Recognized; unavailable | `2016_gpu_mcs_drug_discovery`: no local code; `2026_fast_ged`: build blocked |
| [Pairwise Network Alignment](../problems/25_network_alignment/problem.json) | Recognized; unavailable | `2015_hga_2n`: no local code; `2023_cualign`: no local code; `2024_gpu_local_network_alignment`: no local code |
| [Hop-Constrained Simple Path and Cycle Enumeration](../problems/26_hop_constrained_cycle_path_enumeration/problem.json) | Recognized; unavailable | `2014_gpu_chordless_cycles`: no local code; `2022_gpu_elementary_circuits`: no local code |
| [Group Steiner Tree](../problems/27_group_steiner_tree/problem.json) | Recognized; unavailable | `2021_gpusteiner_kmb`: partial pass; `2022_gpu_vlsi_gst`: partial pass; `2025_gpu4gst`: correctness fail |
| [Influence Maximization under Diffusion Models](../problems/28_influence_maximization/problem.json) | Recognized; unavailable | `2020_curipples`: build blocked; `2021_gim`: partial pass; `2021_superfuser`: correctness fail; `2024_difuser`: no local code |
| [SimRank and General Vertex-to-Vertex Structural Similarity](../problems/29_simrank_vertex_similarity/problem.json) | Recognized; unavailable | `2023_clipsim`: no local code |
| [Balanced k-Way Graph Partitioning](../problems/30_balanced_graph_partitioning/problem.json) | Recognized; unavailable | `2024_gkway`: no local code; `2024_hyperg`: no local code; `2025_igkway`: no local code |
| [Bipartite Matching and Linear Assignment](../problems/31_bipartite_matching_assignment/problem.json) | `linear-assignment` | `2013_deveci_mcm_gpu`: no local code; `2019_hungariangpu`: validated profile |
| [Signed Network Structural Balance and Frustration Minimization](../problems/32_signed_network_structural_balance/problem.json) | Recognized; unavailable | `2021_graphbplus`: artifact mismatch; `2026_ecl_sgb`: artifact mismatch |
| [Transitive Closure and Reachability Indexing](../problems/33_transitive_closure_reachability/problem.json) | `transitive-closure` | `2021_atc`: no local code; `2024_gdlog`: validated profile; `2026_curpq`: no local code |
| [Graph-Based Entity Resolution and Rule-Based Blocking](../problems/34_entity_resolution_blocking/problem.json) | Recognized; unavailable | `2025_hyperblocker`: build blocked |
| [Connected Components (Weakly and Strongly Connected)](../problems/35_connected_components/problem.json) | `connected-components` | `2018_eclcc`: no local code; `2023_eclscc`: validated profile |
| [Force-Directed Graph Layout](../problems/36_graph_layout_force_directed/problem.json) | Recognized; unavailable | `2017_gpugraphlayout`: build blocked |
| [Null-Model Significance Testing via Degree-Preserving Graph Randomization](../problems/37_null_model_significance_testing/problem.json) | Recognized; unavailable | No paper/code artifact cataloged |
