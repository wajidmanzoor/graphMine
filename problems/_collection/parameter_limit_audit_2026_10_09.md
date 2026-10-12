# Parameter and objective limit audit

Date: 2026-10-09. Scope: the current `graphMine-repo` working tree, including local repairs.

**Several limits are imposed by GraphMine's integration, even when the research algorithm supports more. Others are real constraints of the selected implementation or mathematical variant.** This audit separates the public contract, selected source, and recorded validation. It does not remove limits or certify larger workloads.

The two reported cases:

* **k-cliques:** KCGPU and GAMMA reject nontrivial k>5 in the adapters; GraphSet rejects k>6. The [KCGPU paper](https://arxiv.org/abs/2104.13209) reports k=7 and k=10 experiments. GAMMA's collected source has a seven-vertex embedding limit, while the selected GraphSet source is documented k<=6. Local numerical evidence found for the three integrated counting paths covers k=3,4,5. Acceptance, tested range, and paper capability are different facts.
* **CDS density:** the [upstream CDS description](https://github.com/wajidmanzoor/CDS) defines `rho_k(S) = number_of_k_cliques(G[S]) / |S|`. k=2 gives edge density; k=3 gives triangle density. Our adapter hard-codes 2 in its invocation **and** witness check. The repaired standalone evidence includes higher-order k=3..6 cases. Exposing that capability remains integration work; the paper did not restrict the method to edges.

Clique-order density is also different from **densest-k-subgraph**, where k is the required number of selected vertices. Neither is the normalized connection fraction `2|E(S)|/(|S|(|S|-1))`.

The reasons fall into five groups: (1) API or selected-mode omissions, (2) a range tested locally, (3) fixed buffers, masks, integer types or launch layouts, (4) graph/objective assumptions, and (5) resource/output limits. Combinatorial growth explains the need for resource management, but does not explain an arbitrary universal k=5 ceiling. For example, K_n contains binomial(n,k) k-cliques, so emitting every instance can be expensive even when counting is practical.

## Coverage and confidence

All 70 problem contracts and all 219 record metadata files were screened. All 24 executable operations / 38 registered backend choices were traced through their parameter definitions and native adapters. Declared source entry points were additionally scanned for restrictions, with targeted follow-up into headers, workers and kernels. The JSON companion records each entry point, its hash, candidate guards and review level.

This is a **static source/contract audit**, with existing test evidence inspected. No new GPU numerical test, build, benchmark or sanitizer run was performed. A source guard scan is not a proof that every transitive kernel is safe. Missing source and unreviewed transitive limits are explicitly left unknown. Shared source files can contain guards for other algorithms; raw candidate guards are not automatically attributed to the recorded algorithm.

## Exposed operations

Every backend choice is included below. Source references identify the current working-tree evidence; the JSON stores file hashes and line numbers.

### maximal-cliques — mce-gpu, g2-aimd, rdmce

MCE-GPU, G2-AIMD and RDMCE provide GPU totals; returned clique memberships use a common host enumerator. G2-AIMD rejects maximum degree >=100,000 and uses a 16,000,000-entry buffer. All retain finite index/count types.

**Why:** The count interface does not expose GPU membership lists. G2-AIMD has a fixed per-warp temporary array; its degree cap protects that storage. These are output/integration and memory-layout limits, not a maximum clique order of five.

**What expansion requires:** Expose GPU output buffers or streaming; redesign G2-AIMD scratch allocation before raising its degree bound. Result limits need not reduce the GPU count work.

Evidence: [library/src/problems/maximal_cliques.cpp:393](../../library/src/problems/maximal_cliques.cpp#L393); [library/src/backends/maximal_cliques/g2_aimd_backend.cu:90](../../library/src/backends/maximal_cliques/g2_aimd_backend.cu#L90); [library/src/backends/maximal_cliques/g2_aimd_backend.cu:122](../../library/src/backends/maximal_cliques/g2_aimd_backend.cu#L122).

### maximum-clique — cuda-ms, gpu-maximum-clique, maximum-clique-on-gpu

CUDA-MS and Maximum-Clique-on-GPU return one optimum and reject all-ties mode. GPUMaximumClique can return ties. CUDA-MS allocates dense adjacency; the other adapters also retain 32-bit indices.

**Why:** The repaired two backends retain one best witness. A search that prunes ties cannot produce all optimum cliques by changing only the output schema. Dense adjacency adds quadratic storage.

**What expansion requires:** Retain equal-bound branches and emit multiple witnesses for all-ties support; change the dense representation for larger CUDA-MS graphs. The single-witness restriction does not make the repaired optimum approximate.

Evidence: [library/src/problems/maximum_clique.cpp:131](../../library/src/problems/maximum_clique.cpp#L131); [library/src/backends/cuda_ms.cpp:58](../../library/src/backends/cuda_ms.cpp#L58); [library/src/backends/gpu_maximum_clique_backend.cu:34](../../library/src/backends/gpu_maximum_clique_backend.cu#L34).

### k-cliques — kcgpu, graphset, gamma

KCGPU/GAMMA: k=3..5 on the nontrivial GPU path. GraphSet: k=3..6. Common k=2 counts edges; native k>n returns zero. GraphSet also requires oriented degree <=1,280. Agent preflight rejects k above the selected backend cap even for trivial k>n requests.

**Why:** KCGPU's five is a local validation cap: its paper evaluates k=7 and 10. GAMMA's integration cap is five although the collected source sets embedding_max_length=7. GraphSet selects a source kernel documented k<=6, with fixed-depth/20-word-per-level scratch. The 1,280 bound is 20*64. Neither five nor six is a mathematical bound on clique counting.

**What expansion requires:** Validate KCGPU at larger k with independent counts and overflow checks; audit GAMMA's seven-slot buffers/packed constraints; extend or replace the selected GraphSet kernel. Registry evidence and current C++ tests cover k=3,4,5, so acceptance of GraphSet k=6 is not itself evidence of a k=6 numerical test. Enumeration/per-vertex counts currently use host materialization after the GPU count.

Evidence: [library/src/backends/kcgpu.cu:44](../../library/src/backends/kcgpu.cu#L44); [library/src/backends/gamma_kclique.cu:62](../../library/src/backends/gamma_kclique.cu#L62); [library/src/backends/graphset_kclique.cu:30](../../library/src/backends/graphset_kclique.cu#L30); [library/src/backends/graphset_kclique.cu:91](../../library/src/backends/graphset_kclique.cu#L91); [problems/03_k_clique_counting_enumeration/papers/2024_gamma/code/utils.h:41](../../problems/03_k_clique_counting_enumeration/papers/2024_gamma/code/utils.h#L41); [problems/03_k_clique_counting_enumeration/papers/2023_graphset/code/gpu/gpu_kclique.cu:1](../../problems/03_k_clique_counting_enumeration/papers/2023_graphset/code/gpu/gpu_kclique.cu#L1); [library/tests/k_cliques_test.cpp:37](../../library/tests/k_cliques_test.cpp#L37); [library/src/problems/k_cliques.cpp:71](../../library/src/problems/k_cliques.cpp#L71).

### quasi-cliques — cuqc

cuQC requires 0.5 <= minimum_degree_ratio <= 1, minimum_size >=2, and signed 32-bit graph sizes. This adapter selects one GPU; the source also has a distributed variant.

**Why:** The paper deliberately restricts gamma>=0.5. Its diameter-two property justifies two-hop candidate pruning. Below that threshold, retaining the same pruning can discard valid results. This is an algorithmic assumption, not just an arbitrary validation boundary.

**What expansion requires:** Generalize the pruning proof and implementation for gamma<0.5. The current result_limit truncates results after cuQC has generated them, so it is not a computation budget.

Evidence: [library/src/problems/quasi_cliques.cpp:130](../../library/src/problems/quasi_cliques.cpp#L130); [problems/04_quasi_clique_mining/papers/2025_cuqc/code/main.cu:427](../../problems/04_quasi_clique_mining/papers/2025_cuqc/code/main.cu#L427); [library/src/problems/quasi_cliques.cpp:215](../../library/src/problems/quasi_cliques.cpp#L215).

### k-core — kcore-gpu

KCoreGPU computes a full unweighted undirected core vector; requested_k has no artificial five/six maximum. Indices and CSR offsets are unsigned 32-bit.

**Why:** requested_k filters an already computed decomposition. A threshold above degeneracy legitimately produces an empty core. Directed or weighted core definitions require different semantics.

**What expansion requires:** Use wider graph storage for index scale; expose a separately specified directed/weighted variant if needed.

Evidence: [library/src/problems/k_core.cpp:74](../../library/src/problems/k_core.cpp#L74); [library/src/backends/kcore_gpu.cu:56](../../library/src/backends/kcore_gpu.cu#L56).

### maximal-bicliques — cumbe

cuMBE supplies a GPU count and common host membership enumeration. Requires a declared valid bipartition, signed 32-bit backend sizes, CUDA cooperative launch and >=512 threads per block.

**Why:** GPU synchronization and temporary storage depend on that launch model. Size filters and membership output are handled by the common enumerator, not by a generic GPU listing API.

**What expansion requires:** Add GPU membership streaming and validate filtered counts; port synchronization for unsupported devices.

Evidence: [library/src/backends/cumbe.cu:185](../../library/src/backends/cumbe.cu#L185); [library/src/backends/cumbe.cu:190](../../library/src/backends/cumbe.cu#L190); [library/src/problems/maximal_bicliques.cpp:264](../../library/src/problems/maximal_bicliques.cpp#L264).

### triangle-counting — tot, wetric

ToT/WeTriC count triangles only. Listings and participation use host materialization. ToT uses signed 32-bit graph indices; WeTriC unsigned 32-bit. WeTriC matrix length must be a positive multiple of 64, and spread must fit device shared memory.

**Why:** Three vertices define the objective, not a tunable clique-size cap. WeTriC's layout packs adjacency and sizes per-block scratch as (2*128*spread+1)*4 bytes. Its upstream help says divisible by 32 while this adapter requires 64; the adapter is stricter.

**What expansion requires:** Expose listing kernels if GPU enumeration is required. Verify the 32-versus-64 layout discrepancy before relaxing the adapter. Planner metadata currently gives only a minimum for matrix length, so some accepted plans fail native validation.

Evidence: [library/src/backends/wetric.cu:72](../../library/src/backends/wetric.cu#L72); [library/src/backends/wetric.cu:88](../../library/src/backends/wetric.cu#L88); [problems/10_triangle_counting_listing/papers/2025_wetric/code/tc.cu:451](../../problems/10_triangle_counting_listing/papers/2025_wetric/code/tc.cu#L451); [library/src/backends/tot.cu:24](../../library/src/backends/tot.cu#L24).

### dynamic-triangle-counting — edtc

EDTC handles normalized edge insertion/deletion batches; GPU outputs are change counts. Full before/after listings are materialized on the host. Vertices, CSR and batch indices are unsigned 32-bit; net count change is checked against signed 64-bit range.

**Why:** This is an update-counting interface, not a general temporal motif solver or a persistent streaming database. Batch normalization defines repeated-edge behavior.

**What expansion requires:** Widen storage and add incremental GPU result emission for larger or listing-heavy workloads.

Evidence: [library/src/backends/edtc.cu:28](../../library/src/backends/edtc.cu#L28); [library/src/problems/dynamic_triangle_counting.cpp:334](../../library/src/problems/dynamic_triangle_counting.cpp#L334).

### graph-motifs — graphminer, graphset, dumato

Connected undirected motifs of 3 or 4 vertices only. GraphMiner and DuMato require induced mode; GraphSet requires non-induced mode. Counts use fixed motif-class mappings; optional instances/participation use a host materializer.

**Why:** The adapters expose small fixed-size kernels and class tables rather than the complete pattern capabilities of each framework. Induced and non-induced occurrence counts differ.

**What expansion requires:** Wire larger generated kernels, canonical class mappings and automorphism corrections; validate induced and non-induced semantics independently.

Evidence: [library/src/problems/graph_motifs.cpp:360](../../library/src/problems/graph_motifs.cpp#L360); [library/src/backends/g2miner_motif.cu:36](../../library/src/backends/g2miner_motif.cu#L36); [library/src/backends/dumato_motif.cu:62](../../library/src/backends/dumato_motif.cu#L62); [library/src/problems/graph_motifs.cpp:336](../../library/src/problems/graph_motifs.cpp#L336).

### subgraph-isomorphism — gmatch

gMatch: <=16 query vertices, <=32,767 data vertices, connected undirected query, vertex-label equality and non-induced matching. initial_match_capacity must fit a positive int; output listing is a host stage.

**Why:** The selected source defines QVMAX=16 and uses signed short candidate lengths. The data-vertex bound conservatively ensures no candidate set exceeds a signed short. This is a chosen bitmap/build representation, not an inherent subgraph-isomorphism bound.

**What expansion requires:** Use wider candidate storage, resize all query arrays and review 32-bit masks before raising limits. Add explicit induced/directed/edge-label predicates for those objectives. A larger initial_match_capacity does not lift the structural caps.

Evidence: [library/src/problems/subgraph_isomorphism.cpp:209](../../library/src/problems/subgraph_isomorphism.cpp#L209); [library/src/problems/subgraph_isomorphism.cpp:212](../../library/src/problems/subgraph_isomorphism.cpp#L212); [problems/13_subgraph_isomorphism/papers/2026_gmatch/code/bitmap/params.h:22](../../problems/13_subgraph_isomorphism/papers/2026_gmatch/code/bitmap/params.h#L22); [problems/13_subgraph_isomorphism/papers/2026_gmatch/code/bitmap/params.h:12](../../problems/13_subgraph_isomorphism/papers/2026_gmatch/code/bitmap/params.h#L12).

### temporal-motif-mining — everest, mayura

Everest/Mayura expose only the directed feed-forward triangle. Integer timestamps are required; time span plus requested window must fit INT_MAX after rebasing timestamps.

**Why:** Only one query-generated pattern was integrated. Temporal ordering and shape are compiled into that kernel. The 32-bit relative-time representation limits span, not the absolute date.

**What expansion requires:** Integrate the upstream query-generation/co-mining machinery and per-pattern correctness tests; widen timestamp arithmetic end to end for larger spans.

Evidence: [library/src/problems/temporal_motif_mining.cpp:83](../../library/src/problems/temporal_motif_mining.cpp#L83); [library/src/problems/temporal_motif_mining.cpp:148](../../library/src/problems/temporal_motif_mining.cpp#L148).

### community-detection — gleiden, parallel-louvain, parallel-leiden, parallel-leiden-plus

All four active backends expose unweighted undirected modularity clustering. No public resolution/objective/iteration options. The pLouvain/pLeiden/pLeiden+ adapter passes resolution 1.0; gLeiden fills unit edge weights. Signed 32-bit graph indices.

**Why:** The integration fixes the model and solver settings even where upstream structures support more options. These are heuristics; a modularity score is not a proof of globally optimal clustering.

**What expansion requires:** Add weights and resolution to the API, transport them into kernels, and recompute the same weighted/resolution objective in output validation. Merely adding a UI parameter would leave the current score calculation wrong.

Evidence: [library/src/problems/community_detection.cpp:146](../../library/src/problems/community_detection.cpp#L146); [library/src/backends/pggc.cpp:163](../../library/src/backends/pggc.cpp#L163); [library/src/backends/gleiden.cu:102](../../library/src/backends/gleiden.cu#L102).

### betweenness-centrality — turbo-bc

TurboBC exposes all-source, unweighted, undirected vertex betweenness with signed 32-bit CSR indices. Weighted shortest paths, source sampling and other centralities are absent from this operation.

**Why:** The adapter sends topology to the unweighted path and exposes no distance weights or source-selection options. Agent planning rejects weighted intent, but the direct C++ supports() function does not reject nonunit edge weights before simple-graph conversion: those callers can receive topology-only scores.

**What expansion requires:** Make direct-API weight handling explicit; integrate weighted or sampled kernels as separate supported modes. GPU memory and index limits still apply to the current all-source run.

Evidence: [library/src/problems/betweenness_centrality.cpp:38](../../library/src/problems/betweenness_centrality.cpp#L38); [library/src/problems/betweenness_centrality.cpp:64](../../library/src/problems/betweenness_centrality.cpp#L64); [library/src/backends/turbobc.cu:44](../../library/src/backends/turbobc.cu#L44); [agent/graphmine_agent/planning.py:19](../../agent/graphmine_agent/planning.py#L19).

### connected-components — ecl-scc

ECL-SCC exposes weak and strong connectivity with common caps of 1,000,000 vertices and 10,000,000 input edges, one GPU, and bounded worker execution.

**Why:** The numeric caps are integration resource limits. Weak components use an undirected/symmetric representation; strongly connected components preserve direction. They are distinct semantics, not approximate and exact modes.

**What expansion requires:** Benchmark and check memory/index/output sizes before changing worker caps; no parameter k is missing here.

Evidence: [library/src/problems/validated_expansion.cpp:49](../../library/src/problems/validated_expansion.cpp#L49); [library/src/problems/validated_expansion.cpp:187](../../library/src/problems/validated_expansion.cpp#L187).

### max-flow-min-cut — ecl-maxflow

Directed edge capacities only; nonnegative integers with total non-loop capacity <=1,000,000,000. No fractional or vertex capacities. Common worker caps also apply.

**Why:** The upstream flow/capacity/excess path uses signed int. The total-capacity guard conservatively prevents overflow; it is not a mathematical maximum-flow restriction. Vertex capacities need a graph transformation.

**What expansion requires:** Audit/widen all arithmetic and residual buffers; define exact fractional representation or scaling explicitly. Do not silently round capacities.

Evidence: [library/src/problems/validated_expansion.cpp:121](../../library/src/problems/validated_expansion.cpp#L121); [library/src/problems/validated_expansion.cpp:117](../../library/src/problems/validated_expansion.cpp#L117).

### linear-assignment — hungarian-cuda

HungarianCUDA: complete square bipartite minimum-cost perfect assignment, <=64 vertices per side, integer costs 0..999. No sparse, rectangular, negative-cost or other matching modes.

**Why:** This worker is compiled with _n_=64, and upstream device arrays depend on that compile-time dimension. The adapter initializes costs to a 1,000 sentinel and accepts only smaller values; dummy padding uses a 100,000,000 penalty. These chosen integer bounds are not the mathematical range of Hungarian assignment.

**What expansion requires:** Use dynamic arrays or additional validated sizes, review integer/padding bounds, and add explicit rectangular/infeasible-edge semantics. The collected cuGraph assignment is an alternative research lead, not an installed replacement.

Evidence: [library/cmake/ValidatedExpansion.cmake:41](../../library/cmake/ValidatedExpansion.cmake#L41); [library/src/problems/validated_expansion.cpp:151](../../library/src/problems/validated_expansion.cpp#L151); [library/tools/prepare_expansion_workers.py:71](../../library/tools/prepare_expansion_workers.py#L71).

### transitive-closure — gdlog

GDlog exposes full reflexive materialized closure for <=1,024 vertices; no persistent reachability index or selected-pair query mode.

**Why:** The wrapper copies every reachable pair to host text/JSON and explicitly caps the collector at 1,024 squared pairs. Quadratic output, not graph reachability theory, motivates the integration bound.

**What expansion requires:** Provide streamed output, compact bitsets, or selected-pair/index modes; then change collector, API and resource checks together.

Evidence: [library/src/problems/validated_expansion.cpp:250](../../library/src/problems/validated_expansion.cpp#L250); [library/tools/prepare_expansion_workers.py:94](../../library/tools/prepare_expansion_workers.py#L94).

### butterfly-counting — graphminer, gamma-butterfly

GraphMiner and GAMMA return only global K2,2 counts on a declared undirected bipartition; no instances, vertex/edge participation or alpha/beta cores.

**Why:** The adapters reduce a square/C4 count to butterflies. A global total contains insufficient information to recover which vertices/edges participated. Decomposition is another algorithm.

**What expansion requires:** Add per-embedding/per-edge accumulation or a listing path and implement peeling separately for cores. Do not reuse a total as membership output.

Evidence: [library/src/problems/validated_expansion.cpp:277](../../library/src/problems/validated_expansion.cpp#L277); [library/src/problems/repaired_algorithms.cpp:269](../../library/src/problems/repaired_algorithms.cpp#L269).

### k-truss — acctd

AccTD exposes full per-edge truss numbers for simple unweighted undirected input, subject to worker/index limits. No artificial small-k cap.

**Why:** Full decomposition computes all truss levels. This differs from collected cuGraph fixed-k extraction and Hornet fixed-k/maximum-k interfaces, which do not by themselves emit all edge trussness values.

**What expansion requires:** Use the existing full vector to select a requested truss; add weighted/directed definitions separately if required.

Evidence: [library/src/problems/repaired_algorithms.cpp:173](../../library/src/problems/repaired_algorithms.cpp#L173).

### densest-subgraph — cds

The CDS public API fixes k=2 and returns unweighted edge count / selected vertex count. No clique-order parameter, weighted objective, minimum-cardinality variant or fixed-cardinality variant is exposed.

**Why:** The wrapper passes the literal string 2 to CDS, insists the returned k equals 2, and recomputes only induced edges. Problem 05 itself specifies edge density. The repaired standalone CLI already supports clique density and has recorded k=3,4,5,6 tests. This is incomplete higher-order integration, not a missing CDS algorithm.

**What expansion requires:** Add a clique-order contract/parameter, forward k, return clique_count/order, and check the witness using k-cliques. Expose the existing exact path without relabeling edge density as clique density. Fixed-cardinality densest-k-subgraph (problem 06) is a different task.

Evidence: [library/src/problems/repaired_algorithms.cpp:181](../../library/src/problems/repaired_algorithms.cpp#L181); [library/src/problems/repaired_algorithms.cpp:182](../../library/src/problems/repaired_algorithms.cpp#L182); [problems/05_densest_subgraph/problem.json:6](../../problems/05_densest_subgraph/problem.json#L6); [validation/algorithm_repairs/cds/README.md:103](../../validation/algorithm_repairs/cds/README.md#L103).

### maximal-biclique-counting — mbe-gpu

MBE-GPU exposes only an exact global count from the scheduled single-GPU variant. No memberships, partition-size filters, bitmap or multi-GPU mode.

**Why:** The repaired worker exports a count; its other upstream variants were not validated as this executable profile. This count-only operation is intentionally separate from cuMBE membership output.

**What expansion requires:** Add a verified output/filter path or integrate the appropriate upstream variant with separate evidence.

Evidence: [catalog/repaired_profiles.json:30](../../catalog/repaired_profiles.json#L30); [library/src/problems/repaired_algorithms.cpp:192](../../library/src/problems/repaired_algorithms.cpp#L192).

### personalized-pagerank — kpar

kPAR: one seed, outgoing directed unweighted walks, restart probability exactly 0.2; epsilon 0.01..0.5, random_seed <=INT_MAX, approximate output with no certified error bound. Agent top_k <=1,000,000; worker outputs min(k,n).

**Why:** The source uses ALPHA_DEFAULT=0.2 inside propagation and index construction, not just as a CLI default. The narrower epsilon interval is a validated integration range; standalone parsing permits 0<epsilon<1. Random-walk indexes bind graph, alpha and epsilon.

**What expansion requires:** Thread alpha consistently through all kernels and rebuild indexes; validate other epsilon ranges. Multiple-seed distributions, weighted walks and exact convergence need additional paths. Approximate epsilon must not be advertised as a proven per-run error bound.

Evidence: [problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/util/config.h:34](../../problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/util/config.h#L34); [problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/algo/GtopkRrw.cuh:272](../../problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/algo/GtopkRrw.cuh#L272); [library/src/problems/repaired_algorithms.cpp:125](../../library/src/problems/repaired_algorithms.cpp#L125); [problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/main.cu:66](../../problems/21_personalized_pagerank_rwr/papers/2020_kpar/code/src/main.cu#L66).

### group-steiner-tree — gpu4gst

GPU4GST: 1..16 nonempty groups, nonnegative integer weights <=2^53-1 through the public graph format, conservative tree-cost bound <2^58, no hop/diameter constraint.

**Why:** The selected TrimCDP-WB variant indexes vertex-by-group-subset states using width=2^groups and 32-bit queues. Sixteen is a checked/validated profile bound, with exponential state growth behind it. The public weight limit preserves exact integers through double; 2^58 is the worker's infinity sentinel.

**What expansion requires:** Review state growth/index width and memory before increasing group count; use integer-preserving transport for wider weights. Integrate the separate hop-constrained variant to support hop limits.

Evidence: [library/src/problems/repaired_algorithms.cpp:140](../../library/src/problems/repaired_algorithms.cpp#L140); [library/src/problems/repaired_algorithms.cpp:147](../../library/src/problems/repaired_algorithms.cpp#L147); [validation/algorithm_repairs/gpu4gst/repair.patch:2475](../../validation/algorithm_repairs/gpu4gst/repair.patch#L2475); [validation/algorithm_repairs/gpu4gst/README.md:42](../../validation/algorithm_repairs/gpu4gst/README.md#L42).

### influence-maximization — superfuser

SuperFuseR exposes independent cascade only, explicit probabilities [0,1], sample_count 32..65,536 in multiples of 32, one physical GPU, and no certified approximation guarantee.

**Why:** The selected kernels simulate/sketch independent live-edge cascades. Warp-oriented sampling explains the 32 alignment; the upper bound is a validated resource profile and vertex-by-sample state consumes memory. Empirical quality checks do not prove a general guarantee. Linear threshold is a different diffusion process.

**What expansion requires:** Expand resource/validation coverage for more samples and multi-GPU operation; implement a bound/certificate rather than setting guarantee_met=true. Other collected frameworks have other diffusion modes but are not integrated here.

Evidence: [library/src/problems/repaired_algorithms.cpp:131](../../library/src/problems/repaired_algorithms.cpp#L131); [validation/algorithm_repairs/superfuser/README.md:148](../../validation/algorithm_repairs/superfuser/README.md#L148); [validation/algorithm_repairs/superfuser/README.md:103](../../validation/algorithm_repairs/superfuser/README.md#L103).

## Additional collected implementations

These are source-level research findings, not claims of newly executable GraphMine backends.

### PyTorch Cluster CUDA kNN

Kernel neighbor count <=100. The default knn_graph(loop=False) requests k+1, making its effective user k ceiling 99.

**Why:** Each CUDA query has fixed best_dist[100] and best_idx[100] arrays. Removing the assertion would overrun storage; the extra neighbor allows self removal.

**What expansion requires:** Redesign top-k storage/selection or choose another backend; preserve non-self and duplicate-vector semantics.

Evidence: [problems/_sources/torch_cluster-e9a855c284b4/csrc/cuda/knn_cuda.cu:44](../../problems/_sources/torch_cluster-e9a855c284b4/csrc/cuda/knn_cuda.cu#L44); [problems/_sources/torch_cluster-e9a855c284b4/torch_cluster/knn.py:132](../../problems/_sources/torch_cluster-e9a855c284b4/torch_cluster/knn.py#L132).

### Faiss GPU flat kNN

Native selection max k is 2,048 for the modern CUDA build (1,024 in its older compiler branch); the cuVS-backed selection branch permits 16,384. A self-removing k+1 adapter consumes one slot.

**Why:** The limit belongs to the compiled GPU top-k selection implementation. It is not a universal nearest-neighbor limit and varies with backend configuration.

**What expansion requires:** Use a different selection/merge strategy or supported backend; test the actual build and exact non-self output, including ties.

Evidence: [problems/_sources/faiss-07979b10e64d/faiss/gpu/impl/IndexUtils.cu:23](../../problems/_sources/faiss-07979b10e64d/faiss/gpu/impl/IndexUtils.cu#L23); [problems/_sources/faiss-07979b10e64d/faiss/gpu/utils/DeviceDefs.cuh:39](../../problems/_sources/faiss-07979b10e64d/faiss/gpu/utils/DeviceDefs.cuh#L39).

### CuPy Laplacian eigensolvers

Lanczos eigsh requires 0<k<n; generalized M/Minv and non-normal modes are not supported in this entry point. LOBPCG switches to dense solving when n-constraints <5*block_size and rejects constraints in that fallback.

**Why:** These are partial-spectrum solver/subspace restrictions. Full dense eigh is a separate collected algorithm. Sparse shift-invert factorization and the small Ritz solve can involve CPU work.

**What expansion requires:** Dispatch to a solver matching the requested eigenpair count, constraints and GPU requirements; build the Laplacian and check residuals/nullspace explicitly.

Evidence: [problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py:182](../../problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py#L182); [problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py:165](../../problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py#L165); [problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_lobpcg.py:294](../../problems/_sources/cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_lobpcg.py#L294).

### GARDENIA coloring

The pinned implementation defines MAXCOLOR=128 and uses fixed color bitsets; it cannot be advertised as unrestricted distance-1 coloring.

**Why:** This is an implementation palette assumption, not a guarantee that every graph is colorable with 128 colors, or a minimum-color solver.

**What expansion requires:** Add dynamically sized palettes or an explicit overflow/fallback path and test graphs requiring more colors.

Evidence: [problems/_sources/gardenia-5894df11cf47/include/common.h:65](../../problems/_sources/gardenia-5894df11cf47/include/common.h#L65).

### GraphMiner/Pangolin frequent subgraph mining

Single-host MNI support and count output only. Inspected GPU aggregation specializes to three-vertex embeddings; GraphMiner has an 8,000-pattern bitset allocation and Pangolin 21,251. Generic-looking k arguments are not evidence of arbitrary pattern support.

**Why:** Aggregation contains n<4 / n==3 assertions and fixed small/middle/large vertex domains. General larger-pattern canonicalization/aggregation is absent from this path. This also differs from graph-transaction support in problem 14.

**What expansion requires:** Expose explicit supported pattern bounds, guard pattern capacity, implement general canonicalization/domain support and listing before promising broader mining.

Evidence: [problems/_sources/graphminer-2a76e3f612e4/src/fsm/gpu_base.cu:18](../../problems/_sources/graphminer-2a76e3f612e4/src/fsm/gpu_base.cu#L18); [problems/_sources/graphminer-2a76e3f612e4/src/fsm/gpu_base.cu:261](../../problems/_sources/graphminer-2a76e3f612e4/src/fsm/gpu_base.cu#L261); [problems/_sources/graphminer-2a76e3f612e4/src/pangolin/fsm/fsm.h:12](../../problems/_sources/graphminer-2a76e3f612e4/src/pangolin/fsm/fsm.h#L12); [problems/_sources/graphminer-2a76e3f612e4/src/pangolin/fsm/base.cu:235](../../problems/_sources/graphminer-2a76e3f612e4/src/pangolin/fsm/base.cu#L235).

### cuGraph structural kernels

Core numbers and k-truss require symmetric, non-multigraph input. cuGraph k_truss returns a requested subgraph, not all edge trussness; triangle APIs do not provide triangle memberships.

**Why:** The algorithms assume simple undirected topology, and output interfaces expose only their specific primitive. A paper/source pair does not supply the missing decomposition or listing stage.

**What expansion requires:** Normalize under an explicit contract and implement missing output stages; use AccTD for the currently integrated full truss decomposition.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/cores/core_number_impl.cuh:71](../../problems/_sources/cugraph-5931900cf6be/cpp/src/cores/core_number_impl.cuh#L71); [problems/_sources/cugraph-5931900cf6be/cpp/src/community/k_truss_impl.cuh:174](../../problems/_sources/cugraph-5931900cf6be/cpp/src/community/k_truss_impl.cuh#L174).

### cuGraph ECG settings

This pinned ECG source enforces 0<resolution<=1, 0<threshold<=1, ensemble_size>=1 and min_weight>=0.

**Why:** These are specific entry-point guards. The resolution cap should not be attributed to modularity theory or copied onto every Louvain/Leiden implementation. The min_weight error message says positive although the code permits zero.

**What expansion requires:** Expose the exact selected implementation's ranges and verify alternatives when resolution>1 is needed.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/community/ecg_impl.cuh:52](../../problems/_sources/cugraph-5931900cf6be/cpp/src/community/ecg_impl.cuh#L52); [problems/_sources/cugraph-5931900cf6be/cpp/src/community/ecg_impl.cuh:44](../../problems/_sources/cugraph-5931900cf6be/cpp/src/community/ecg_impl.cuh#L44).

### cuGraph iterative centrality/PPR

Katz and PageRank check alpha in [0,1] and nonnegative tolerances; personalization needs positive total mass. Katz convergence also depends on attenuation relative to the adjacency spectral radius.

**Why:** A syntactically accepted iteration parameter is not a convergence certificate. For PageRank alpha denotes continuation/damping; kPAR's alpha=0.2 denotes restart, so identical numbers do not mean identical walks.

**What expansion requires:** Map parameter conventions, dangling behavior and tolerances explicitly; check convergence and validate scores. Treat the Katz spectral-radius statement as the mathematical convergence condition, not an additional source-enforced check.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/centrality/katz_centrality_impl.cuh:61](../../problems/_sources/cugraph-5931900cf6be/cpp/src/centrality/katz_centrality_impl.cuh#L61); [problems/_sources/cugraph-5931900cf6be/cpp/src/link_analysis/pagerank_impl.cuh:212](../../problems/_sources/cugraph-5931900cf6be/cpp/src/link_analysis/pagerank_impl.cuh#L212).

### cuGraph traversals

Direction-optimizing BFS requires a symmetric graph; SSSP/OD reject negative weights when expensive validation is enabled. The collected OD distances entry point is single-GPU.

**Why:** Direction-optimizing traversal and nonnegative relaxation rely on those graph assumptions. The OD source has an explicit compile-time multi-GPU exclusion; cuGraph as a library having multi-GPU support does not make every algorithm multi-GPU.

**What expansion requires:** Select an appropriate path algorithm and input representation; distinguish optional expensive validation from unconditional guards.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/bfs_impl.cuh:204](../../problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/bfs_impl.cuh#L204); [problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/sssp_impl.cuh:209](../../problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/sssp_impl.cuh#L209); [problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/od_shortest_distances_impl.cuh:446](../../problems/_sources/cugraph-5931900cf6be/cpp/src/traversal/od_shortest_distances_impl.cuh#L446).

### cuGraph ego extraction

The pinned C++ ego APIs require 0<radius<n; one overload also requires 0<number_of_sources<n. Edge masks are unsupported in the inspected path.

**Why:** These are implementation/API preconditions. A radius-zero ego consisting only of its seed is mathematically valid, so it needs an adapter/trivial path rather than a claim that the task is undefined.

**What expansion requires:** Implement radius-zero/empty/all-seed boundary cases explicitly and select supported edge-mask handling.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/community/egonet_impl.cuh:223](../../problems/_sources/cugraph-5931900cf6be/cpp/src/community/egonet_impl.cuh#L223).

### cuGraph masked graphs

The inspected similarity wrappers and random-walk entry points reject a graph with an edge mask.

**Why:** The selected implementation does not support that storage/view mode. This is unrelated to the existence of Jaccard, cosine, Sorensen, overlap or random-walk algorithms.

**What expansion requires:** Materialize the intended filtered graph or use a supported view while preserving IDs and weights.

Evidence: [problems/_sources/cugraph-5931900cf6be/cpp/src/link_prediction/jaccard_impl.cuh:23](../../problems/_sources/cugraph-5931900cf6be/cpp/src/link_prediction/jaccard_impl.cuh#L23); [problems/_sources/cugraph-5931900cf6be/cpp/src/sampling/random_walks_impl.cuh:894](../../problems/_sources/cugraph-5931900cf6be/cpp/src/sampling/random_walks_impl.cuh#L894).

### Objective and pipeline restrictions

Greedy matching is approximate; HySpecPro's public driver is two-way; dyGRASS needs an initial sparsifier and updates; quotient/coarsening routines need an assignment; learned MIS/MVC lack optimum certificates. Component-aware MVC may report size/decision without a witness.

**Why:** These limitations come from the selected objective, input pipeline or output contract. They cannot be removed by increasing a numeric parameter. Hybrid CPU initialization/decoding is present in several releases.

**What expansion requires:** Implement the missing stages, choose a matching algorithm, and state approximate versus exact output explicitly. Per-record notes and source paths are retained in the JSON inventory.

Evidence: [problems/54_hypergraph_partitioning/papers/2026_hyspecpro/metadata.json:21](../../problems/54_hypergraph_partitioning/papers/2026_hyspecpro/metadata.json#L21); [problems/55_spectral_graph_sparsification/papers/2025_dygrass_incremental/metadata.json:16](../../problems/55_spectral_graph_sparsification/papers/2025_dygrass_incremental/metadata.json#L16); [problems/66_maximum_independent_set/papers/2023_difusco_mis/metadata.json:20](../../problems/66_maximum_independent_set/papers/2023_difusco_mis/metadata.json#L20).

### Missing output or different mathematical task

Examples: graphlet counts omit vertex orbits; local PPR omits community selection; signed-balance releases emit statistics rather than minimum-frustration certificates; approximate GED is not exact GED; chordless cycles, circuit timing and sparse fused lasso are restricted/different objectives.

**Why:** A related implementation or paper does not automatically solve every mode in its problem statement. Some folders have no runnable GPU source, so there is no verifiable parameter envelope to lift.

**What expansion requires:** Keep missing modes unavailable until a complete pipeline with matching outputs is integrated. The per-record inventory retains semantic-fit and artifact availability without treating either as runtime correctness.

Evidence: [problems/12_graphlet_counting/papers/2022_g2miner_enumeration/metadata.json:20](../../problems/12_graphlet_counting/papers/2022_g2miner_enumeration/metadata.json#L20); [problems/49_seeded_local_community_detection/papers/2019_graphblast_lgc/metadata.json:16](../../problems/49_seeded_local_community_detection/papers/2019_graphblast_lgc/metadata.json#L16); [problems/59_graph_signal_denoising/papers/2014_gunrock_sparse_fused_lasso/metadata.json:16](../../problems/59_graph_signal_denoising/papers/2014_gunrock_sparse_fused_lasso/metadata.json#L16).

## Shared limits and misleading signals

* Worker profiles impose one GPU, at most 1,000,000 vertices / 10,000,000 input edges, bounded timeout/output, and further algorithm-specific limits. These are not performance guarantees at those sizes.
* Counts and index widths are separate. Even a graph fitting 32-bit vertex IDs can have a clique/embedding count exceeding 64 bits. Raising k requires an overflow policy, not just a larger accepted integer.
* A result limit often bounds returned rows only. k-clique materialization still traverses all matches for consistency/participation; cuQC truncates after generation. GPU count kernels can still do the full work.
* Collection `semantic_fit=exact` describes alignment with a problem family. It is not an exact-optimization or runtime-correctness certificate. Older metadata can describe pre-repair behavior; current native profiles and versioned repair evidence take precedence.
* GraphSet's catalog tag records k=3..5 validation while native/agent acceptance extends to six. That distinction should be represented explicitly rather than treating either number as a universal capability claim.
* WeTriC's planner accepts arbitrary positive matrix lengths, while native code requires a multiple of 64. Direct TurboBC callers can pass weights that are lost in topology conversion, although agent weighted-intent checks reject that request.

## Work to prioritize

1. Expose CDS clique order and generalize its result/certificate contract; existing standalone higher-order evidence makes this the clearest missing integration.
2. Expand KCGPU and GAMMA validation with known-count higher-k graphs, relabeling, sparse/dense cases, overflow checks and CUDA sanitizers; separately reconcile GraphSet's accepted and tested ranges.
3. Make supported range, tested range, objective, GPU/host stages, count/listing behavior and resource limits explicit per backend. Correct planner/native discrepancies before claiming wider support.
4. Add general motif generation, temporal patterns and weighted/resolution community options as complete features, with matching output validation.
5. Redesign fixed candidate/palette/top-k buffers and assignment/reachability output paths where broader workloads require it. Treat these as engineering changes with boundary tests, not simple removal of guards.

## Complete inventory

[parameter_limit_audit_2026_10_09.json](parameter_limit_audit_2026_10_09.json) contains every problem and research record, entry-point hashes, candidate guard context, planner parameter schemas and 104 checked evidence anchors. Raw guard matches can belong to other functions in shared files; confirmed findings above were reviewed in context.

| Problem | Research records screened | Exposed operations |
|---|---:|---|
| [01_maximal_clique_enumeration](../01_maximal_clique_enumeration/problem.json) | 3 | maximal-cliques |
| [02_maximum_clique](../02_maximum_clique/problem.json) | 3 | maximum-clique |
| [03_k_clique_counting_enumeration](../03_k_clique_counting_enumeration/problem.json) | 3 | k-cliques |
| [04_quasi_clique_mining](../04_quasi_clique_mining/problem.json) | 1 | quasi-cliques |
| [05_densest_subgraph](../05_densest_subgraph/problem.json) | 1 | densest-subgraph |
| [06_densest_k_subgraph](../06_densest_k_subgraph/problem.json) | 0 | None; research collection only |
| [07_k_core_decomposition](../07_k_core_decomposition/problem.json) | 4 | k-core |
| [08_k_truss_decomposition](../08_k_truss_decomposition/problem.json) | 3 | k-truss |
| [09_maximal_biclique_enumeration](../09_maximal_biclique_enumeration/problem.json) | 3 | maximal-bicliques, maximal-biclique-counting |
| [10_triangle_counting_listing](../10_triangle_counting_listing/problem.json) | 7 | triangle-counting, dynamic-triangle-counting |
| [11_graph_motif_counting](../11_graph_motif_counting/problem.json) | 3 | graph-motifs |
| [12_graphlet_counting](../12_graphlet_counting/problem.json) | 3 | None; research collection only |
| [13_subgraph_isomorphism](../13_subgraph_isomorphism/problem.json) | 1 | subgraph-isomorphism |
| [14_frequent_subgraph_mining](../14_frequent_subgraph_mining/problem.json) | 0 | None; research collection only |
| [15_temporal_motif_mining](../15_temporal_motif_mining/problem.json) | 2 | temporal-motif-mining |
| [16_community_detection](../16_community_detection/problem.json) | 5 | community-detection |
| [17_overlapping_community_detection](../17_overlapping_community_detection/problem.json) | 0 | None; research collection only |
| [18_centrality_influential_node_mining](../18_centrality_influential_node_mining/problem.json) | 8 | betweenness-centrality |
| [19_link_prediction](../19_link_prediction/problem.json) | 4 | None; research collection only |
| [20_graph_anomaly_detection](../20_graph_anomaly_detection/problem.json) | 3 | None; research collection only |
| [21_personalized_pagerank_rwr](../21_personalized_pagerank_rwr/problem.json) | 4 | personalized-pagerank |
| [22_max_flow_min_cut](../22_max_flow_min_cut/problem.json) | 3 | max-flow-min-cut |
| [23_butterfly_counting_bipartite](../23_butterfly_counting_bipartite/problem.json) | 4 | butterfly-counting |
| [24_graph_edit_distance_mcs](../24_graph_edit_distance_mcs/problem.json) | 2 | None; research collection only |
| [25_network_alignment](../25_network_alignment/problem.json) | 6 | None; research collection only |
| [26_hop_constrained_cycle_path_enumeration](../26_hop_constrained_cycle_path_enumeration/problem.json) | 3 | None; research collection only |
| [27_group_steiner_tree](../27_group_steiner_tree/problem.json) | 3 | group-steiner-tree |
| [28_influence_maximization](../28_influence_maximization/problem.json) | 4 | influence-maximization |
| [29_simrank_vertex_similarity](../29_simrank_vertex_similarity/problem.json) | 1 | None; research collection only |
| [30_balanced_graph_partitioning](../30_balanced_graph_partitioning/problem.json) | 3 | None; research collection only |
| [31_bipartite_matching_assignment](../31_bipartite_matching_assignment/problem.json) | 3 | linear-assignment |
| [32_signed_network_structural_balance](../32_signed_network_structural_balance/problem.json) | 2 | None; research collection only |
| [33_transitive_closure_reachability](../33_transitive_closure_reachability/problem.json) | 3 | transitive-closure |
| [34_entity_resolution_blocking](../34_entity_resolution_blocking/problem.json) | 1 | None; research collection only |
| [35_connected_components](../35_connected_components/problem.json) | 7 | connected-components |
| [36_graph_layout_force_directed](../36_graph_layout_force_directed/problem.json) | 2 | None; research collection only |
| [37_null_model_significance_testing](../37_null_model_significance_testing/problem.json) | 0 | None; research collection only |
| [38_breadth_first_search](../38_breadth_first_search/problem.json) | 5 | None; research collection only |
| [39_single_source_shortest_paths](../39_single_source_shortest_paths/problem.json) | 5 | None; research collection only |
| [40_many_source_shortest_paths](../40_many_source_shortest_paths/problem.json) | 4 | None; research collection only |
| [41_spanning_tree_forest](../41_spanning_tree_forest/problem.json) | 3 | None; research collection only |
| [42_maximal_independent_set](../42_maximal_independent_set/problem.json) | 5 | None; research collection only |
| [43_vertex_coloring](../43_vertex_coloring/problem.json) | 4 | None; research collection only |
| [44_general_graph_weighted_matching](../44_general_graph_weighted_matching/problem.json) | 6 | None; research collection only |
| [45_topological_sort](../45_topological_sort/problem.json) | 3 | None; research collection only |
| [46_random_walk_generation](../46_random_walk_generation/problem.json) | 4 | None; research collection only |
| [47_neighborhood_sampling](../47_neighborhood_sampling/problem.json) | 4 | None; research collection only |
| [48_induced_subgraph_ego_extraction](../48_induced_subgraph_ego_extraction/problem.json) | 5 | None; research collection only |
| [49_seeded_local_community_detection](../49_seeded_local_community_detection/problem.json) | 3 | None; research collection only |
| [50_node_embedding](../50_node_embedding/problem.json) | 3 | None; research collection only |
| [51_knowledge_graph_embedding](../51_knowledge_graph_embedding/problem.json) | 3 | None; research collection only |
| [52_node_classification_regression](../52_node_classification_regression/problem.json) | 3 | None; research collection only |
| [53_graph_classification_regression](../53_graph_classification_regression/problem.json) | 3 | None; research collection only |
| [54_hypergraph_partitioning](../54_hypergraph_partitioning/problem.json) | 5 | None; research collection only |
| [55_spectral_graph_sparsification](../55_spectral_graph_sparsification/problem.json) | 3 | None; research collection only |
| [56_biconnected_components](../56_biconnected_components/problem.json) | 3 | None; research collection only |
| [57_temporal_fastest_paths](../57_temporal_fastest_paths/problem.json) | 3 | None; research collection only |
| [58_top_k_critical_paths_dag](../58_top_k_critical_paths_dag/problem.json) | 3 | None; research collection only |
| [59_graph_signal_denoising](../59_graph_signal_denoising/problem.json) | 3 | None; research collection only |
| [60_graph_based_geolocation](../60_graph_based_geolocation/problem.json) | 3 | None; research collection only |
| [61_widest_paths](../61_widest_paths/problem.json) | 1 | None; research collection only |
| [62_graph_coarsening](../62_graph_coarsening/problem.json) | 3 | None; research collection only |
| [63_graph_laplacian_eigenpairs](../63_graph_laplacian_eigenpairs/problem.json) | 3 | None; research collection only |
| [64_knn_graph_construction](../64_knn_graph_construction/problem.json) | 3 | None; research collection only |
| [65_hypergraph_node_learning](../65_hypergraph_node_learning/problem.json) | 3 | None; research collection only |
| [66_maximum_independent_set](../66_maximum_independent_set/problem.json) | 3 | None; research collection only |
| [67_persistent_homology](../67_persistent_homology/problem.json) | 1 | None; research collection only |
| [68_single_graph_frequent_subgraph_mining](../68_single_graph_frequent_subgraph_mining/problem.json) | 2 | None; research collection only |
| [69_minimum_vertex_cover](../69_minimum_vertex_cover/problem.json) | 3 | None; research collection only |
| [70_graph_condensation](../70_graph_condensation/problem.json) | 3 | None; research collection only |

Validation of this audit: all operation/backend inventory counts, source anchors and evidence paths are checked by the generator. Algorithm behavior was not changed.
