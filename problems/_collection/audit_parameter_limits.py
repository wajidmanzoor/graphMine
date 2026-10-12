#!/usr/bin/env python3
"""Rebuild the source/contract audit. This script never executes a GPU algorithm."""

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
DATE = "2026-10-09"
STEM = "parameter_limit_audit_2026_10_09"


def read(path):
    return json.loads((ROOT / path).read_text())


def paper(number, ident, filename):
    folder = next((ROOT / "problems").glob(f"{number:02d}_*"))
    return str((folder / "papers" / ident / filename).relative_to(ROOT))


def evidence(path, anchor):
    p = ROOT / path
    lines = p.read_text(errors="replace").splitlines()
    matches = [i for i, line in enumerate(lines, 1) if anchor in line]
    if not matches:
        raise ValueError(f"Audit evidence changed: {path}: {anchor}")
    return {"path": path, "line": matches[0], "anchor": anchor,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def ref(path, anchor):
    return (path, anchor)


NATIVE = []
RESEARCH = []


def native(operation, limits, why, change, *refs):
    NATIVE.append(dict(operation_id=operation, limits=limits, reason=why,
                       expansion_work=change, references=list(refs)))


def research(numbers, title, limits, why, change, *refs):
    RESEARCH.append(dict(problem_numbers=numbers, title=title, limits=limits,
                         reason=why, expansion_work=change, references=list(refs)))


B = "library/src/backends/"
S = "library/src/problems/"
R = S + "repaired_algorithms.cpp"
E = S + "validated_expansion.cpp"
SRC = "problems/_sources/"
CG = SRC + "cugraph-5931900cf6be/"

native("maximal-cliques",
       "MCE-GPU, G2-AIMD and RDMCE provide GPU totals; returned clique memberships use a common host enumerator. G2-AIMD rejects maximum degree >=100,000 and uses a 16,000,000-entry buffer. All retain finite index/count types.",
       "The count interface does not expose GPU membership lists. G2-AIMD has a fixed per-warp temporary array; its degree cap protects that storage. These are output/integration and memory-layout limits, not a maximum clique order of five.",
       "Expose GPU output buffers or streaming; redesign G2-AIMD scratch allocation before raising its degree bound. Result limits need not reduce the GPU count work.",
       ref(S + "maximal_cliques.cpp", "clique sets are materialized"),
       ref(B + "maximal_cliques/g2_aimd_backend.cu", "maximum_degree >= TEMPSIZE"),
       ref(B + "maximal_cliques/g2_aimd_backend.cu", "maximum_buffer_entries"))
native("maximum-clique",
       "CUDA-MS and Maximum-Clique-on-GPU return one optimum and reject all-ties mode. GPUMaximumClique can return ties. CUDA-MS allocates dense adjacency; the other adapters also retain 32-bit indices.",
       "The repaired two backends retain one best witness. A search that prunes ties cannot produce all optimum cliques by changing only the output schema. Dense adjacency adds quadratic storage.",
       "Retain equal-bound branches and emit multiple witnesses for all-ties support; change the dense representation for larger CUDA-MS graphs. The single-witness restriction does not make the repaired optimum approximate.",
       ref(S + "maximum_clique.cpp", "return_all_ties"),
       ref(B + "cuda_ms.cpp", "dense adjacency matrix size overflow"),
       ref(B + "gpu_maximum_clique_backend.cu", "32-bit graph indices"))
native("k-cliques",
       "KCGPU/GAMMA: k=3..5 on the nontrivial GPU path. GraphSet: k=3..6. Common k=2 counts edges; native k>n returns zero. GraphSet also requires oriented degree <=1,280. Agent preflight rejects k above the selected backend cap even for trivial k>n requests.",
       "KCGPU's five is a local validation cap: its paper evaluates k=7 and 10. GAMMA's integration cap is five although the collected source sets embedding_max_length=7. GraphSet selects a source kernel documented k<=6, with fixed-depth/20-word-per-level scratch. The 1,280 bound is 20*64. Neither five nor six is a mathematical bound on clique counting.",
       "Validate KCGPU at larger k with independent counts and overflow checks; audit GAMMA's seven-slot buffers/packed constraints; extend or replace the selected GraphSet kernel. Registry evidence and current C++ tests cover k=3,4,5, so acceptance of GraphSet k=6 is not itself evidence of a k=6 numerical test. Enumeration/per-vertex counts currently use host materialization after the GPU count.",
       ref(B + "kcgpu.cu", "k < 3 || k > 5"), ref(B + "gamma_kclique.cu", "k < 3 || k > 5"),
       ref(B + "graphset_kclique.cu", "k < 3 || k > 6"),
       ref(B + "graphset_kclique.cu", "20U * 64U"),
       ref(paper(3, "2024_gamma", "code/utils.h"), "#define embedding_max_length 7"),
       ref(paper(3, "2023_graphset", "code/gpu/gpu_kclique.cu"), "// k <= 6"),
       ref("library/tests/k_cliques_test.cpp", "{3, 13}, {4, 5}, {5, 1}"),
       ref(S + "k_cliques.cpp", "materialize_k_cliques"))
native("quasi-cliques",
       "cuQC requires 0.5 <= minimum_degree_ratio <= 1, minimum_size >=2, and signed 32-bit graph sizes. This adapter selects one GPU; the source also has a distributed variant.",
       "The paper deliberately restricts gamma>=0.5. Its diameter-two property justifies two-hop candidate pruning. Below that threshold, retaining the same pruning can discard valid results. This is an algorithmic assumption, not just an arbitrary validation boundary.",
       "Generalize the pruning proof and implementation for gamma<0.5. The current result_limit truncates results after cuQC has generated them, so it is not a computation budget.",
       ref(S + "quasi_cliques.cpp", "minimum_degree_ratio < 0.5"),
       ref(paper(4, "2025_cuqc", "code/main.cu"), "d_diameter_pruning"),
       ref(S + "quasi_cliques.cpp", "const std::uint64_t total = backend.quasi_cliques.size()"))
native("k-core",
       "KCoreGPU computes a full unweighted undirected core vector; requested_k has no artificial five/six maximum. Indices and CSR offsets are unsigned 32-bit.",
       "requested_k filters an already computed decomposition. A threshold above degeneracy legitimately produces an empty core. Directed or weighted core definitions require different semantics.",
       "Use wider graph storage for index scale; expose a separately specified directed/weighted variant if needed.",
       ref(S + "k_core.cpp", "SupportReport KCore::supports"),
       ref(B + "kcore_gpu.cu", "KCoreGPU CSR offset exceeds 32 bits"))
native("maximal-bicliques",
       "cuMBE supplies a GPU count and common host membership enumeration. Requires a declared valid bipartition, signed 32-bit backend sizes, CUDA cooperative launch and >=512 threads per block.",
       "GPU synchronization and temporary storage depend on that launch model. Size filters and membership output are handled by the common enumerator, not by a generic GPU listing API.",
       "Add GPU membership streaming and validate filtered counts; port synchronization for unsupported devices.",
       ref(B + "cumbe.cu", "cooperative-kernel launch support"),
       ref(B + "cumbe.cu", "at least 512 threads"),
       ref(S + "maximal_bicliques.cpp", "state.minimum_left_size = options.minimum_left_size"))
native("triangle-counting",
       "ToT/WeTriC count triangles only. Listings and participation use host materialization. ToT uses signed 32-bit graph indices; WeTriC unsigned 32-bit. WeTriC matrix length must be a positive multiple of 64, and spread must fit device shared memory.",
       "Three vertices define the objective, not a tunable clique-size cap. WeTriC's layout packs adjacency and sizes per-block scratch as (2*128*spread+1)*4 bytes. Its upstream help says divisible by 32 while this adapter requires 64; the adapter is stricter.",
       "Expose listing kernels if GPU enumeration is required. Verify the 32-versus-64 layout discrepancy before relaxing the adapter. Planner metadata currently gives only a minimum for matrix length, so some accepted plans fail native validation.",
       ref(B + "wetric.cu", "adjacency_matrix_length % 64"),
       ref(B + "wetric.cu", "2ULL * 128ULL * spread"),
       ref(paper(10, "2025_wetric", "code/tc.cu"), "must be divisble by 32"),
       ref(B + "tot.cu", "signed 32-bit graph indices"))
native("dynamic-triangle-counting",
       "EDTC handles normalized edge insertion/deletion batches; GPU outputs are change counts. Full before/after listings are materialized on the host. Vertices, CSR and batch indices are unsigned 32-bit; net count change is checked against signed 64-bit range.",
       "This is an update-counting interface, not a general temporal motif solver or a persistent streaming database. Batch normalization defines repeated-edge behavior.",
       "Widen storage and add incremental GPU result emission for larger or listing-heavy workloads.",
       ref(B + "edtc.cu", "unsigned 32-bit vertex, offset, and batch indices"),
       ref(S + "dynamic_triangle_counting.cpp", "net triangle change exceeds signed 64-bit"))
native("graph-motifs",
       "Connected undirected motifs of 3 or 4 vertices only. GraphMiner and DuMato require induced mode; GraphSet requires non-induced mode. Counts use fixed motif-class mappings; optional instances/participation use a host materializer.",
       "The adapters expose small fixed-size kernels and class tables rather than the complete pattern capabilities of each framework. Induced and non-induced occurrence counts differ.",
       "Wire larger generated kernels, canonical class mappings and automorphism corrections; validate induced and non-induced semantics independently.",
       ref(S + "graph_motifs.cpp", "validated motif backends support connected"),
       ref(B + "g2miner_motif.cu", "motif_size < 3 || motif_size > 4"),
       ref(B + "dumato_motif.cu", "motif_size == 3 ? 2U : 6U"),
       ref(S + "graph_motifs.cpp", "GraphSet was validated for non-induced motifs only"))
native("subgraph-isomorphism",
       "gMatch: <=16 query vertices, <=32,767 data vertices, connected undirected query, vertex-label equality and non-induced matching. initial_match_capacity must fit a positive int; output listing is a host stage.",
       "The selected source defines QVMAX=16 and uses signed short candidate lengths. The data-vertex bound conservatively ensures no candidate set exceeds a signed short. This is a chosen bitmap/build representation, not an inherent subgraph-isomorphism bound.",
       "Use wider candidate storage, resize all query arrays and review 32-bit masks before raising limits. Add explicit induced/directed/edge-label predicates for those objectives. A larger initial_match_capacity does not lift the structural caps.",
       ref(S + "subgraph_isomorphism.cpp", "query_graph.vertex_count() > 16"),
       ref(S + "subgraph_isomorphism.cpp", "data_graph.vertex_count() > SHRT_MAX"),
       ref(paper(13, "2026_gmatch", "code/bitmap/params.h"), "#define QVMAX 16"),
       ref(paper(13, "2026_gmatch", "code/bitmap/params.h"), "#define CandLen_t short"))
native("temporal-motif-mining",
       "Everest/Mayura expose only the directed feed-forward triangle. Integer timestamps are required; time span plus requested window must fit INT_MAX after rebasing timestamps.",
       "Only one query-generated pattern was integrated. Temporal ordering and shape are compiled into that kernel. The 32-bit relative-time representation limits span, not the absolute date.",
       "Integrate the upstream query-generation/co-mining machinery and per-pattern correctness tests; widen timestamp arithmetic end to end for larger spans.",
       ref(S + "temporal_motif_mining.cpp", "only support feed_forward_triangle"),
       ref(S + "temporal_motif_mining.cpp", "timestamp span plus max_time_span"))
native("community-detection",
       "All four active backends expose unweighted undirected modularity clustering. No public resolution/objective/iteration options. The pLouvain/pLeiden/pLeiden+ adapter passes resolution 1.0; gLeiden fills unit edge weights. Signed 32-bit graph indices.",
       "The integration fixes the model and solver settings even where upstream structures support more options. These are heuristics; a modularity score is not a proof of globally optimal clustering.",
       "Add weights and resolution to the API, transport them into kernels, and recompute the same weighted/resolution objective in output validation. Merely adding a UI parameter would leave the current score calculation wrong.",
       ref(S + "community_detection.cpp", "accept unweighted graphs only"),
       ref(B + "pggc.cpp", "modularity objective(matrix, weighted.vtx_w, 1.0, true)"),
       ref(B + "gleiden.cu", "upstream.wts_out[edge] = 1.0"))
native("betweenness-centrality",
       "TurboBC exposes all-source, unweighted, undirected vertex betweenness with signed 32-bit CSR indices. Weighted shortest paths, source sampling and other centralities are absent from this operation.",
       "The adapter sends topology to the unweighted path and exposes no distance weights or source-selection options. Agent planning rejects weighted intent, but the direct C++ supports() function does not reject nonunit edge weights before simple-graph conversion: those callers can receive topology-only scores.",
       "Make direct-API weight handling explicit; integrate weighted or sampled kernels as separate supported modes. GPU memory and index limits still apply to the current all-source run.",
       ref(S + "betweenness_centrality.cpp", "SupportReport BetweennessCentrality::supports"),
       ref(S + "betweenness_centrality.cpp", "graph.simple_undirected"),
       ref(B + "turbobc.cu", "signed 32-bit CSR indices"),
       ref("agent/graphmine_agent/planning.py", "Other weighted analyses remain unsupported"))
native("connected-components",
       "ECL-SCC exposes weak and strong connectivity with common caps of 1,000,000 vertices and 10,000,000 input edges, one GPU, and bounded worker execution.",
       "The numeric caps are integration resource limits. Weak components use an undirected/symmetric representation; strongly connected components preserve direction. They are distinct semantics, not approximate and exact modes.",
       "Benchmark and check memory/index/output sizes before changing worker caps; no parameter k is missing here.",
       ref(E, "validated adapter limit: 1,000,000 vertices"),
       ref(E, "SupportReport ConnectedComponents::supports"))
native("max-flow-min-cut",
       "Directed edge capacities only; nonnegative integers with total non-loop capacity <=1,000,000,000. No fractional or vertex capacities. Common worker caps also apply.",
       "The upstream flow/capacity/excess path uses signed int. The total-capacity guard conservatively prevents overflow; it is not a mathematical maximum-flow restriction. Vertex capacities need a graph transformation.",
       "Audit/widen all arithmetic and residual buffers; define exact fractional representation or scaling explicitly. Do not silently round capacities.",
       ref(E, "sum of non-loop capacities must be <= 1,000,000,000"),
       ref(E, "supports nonnegative integer capacities only"))
native("linear-assignment",
       "HungarianCUDA: complete square bipartite minimum-cost perfect assignment, <=64 vertices per side, integer costs 0..999. No sparse, rectangular, negative-cost or other matching modes.",
       "This worker is compiled with _n_=64, and upstream device arrays depend on that compile-time dimension. The adapter initializes costs to a 1,000 sentinel and accepts only smaller values; dummy padding uses a 100,000,000 penalty. These chosen integer bounds are not the mathematical range of Hungarian assignment.",
       "Use dynamic arrays or additional validated sizes, review integer/padding bounds, and add explicit rectangular/infeasible-edge semantics. The collected cuGraph assignment is an alternative research lead, not an installed replacement.",
       ref("library/cmake/ValidatedExpansion.cmake", "_n_=64"),
       ref(E, "costs must be integers in [0,999]"),
       ref("library/tools/prepare_expansion_workers.py", "100000000"))
native("transitive-closure",
       "GDlog exposes full reflexive materialized closure for <=1,024 vertices; no persistent reachability index or selected-pair query mode.",
       "The wrapper copies every reachable pair to host text/JSON and explicitly caps the collector at 1,024 squared pairs. Quadratic output, not graph reachability theory, motivates the integration bound.",
       "Provide streamed output, compact bitsets, or selected-pair/index modes; then change collector, API and resource checks together.",
       ref(E, "limited to 1024 vertices"),
       ref("library/tools/prepare_expansion_workers.py", "relation->tuple_counts > 1024ULL*1024ULL"))
native("butterfly-counting",
       "GraphMiner and GAMMA return only global K2,2 counts on a declared undirected bipartition; no instances, vertex/edge participation or alpha/beta cores.",
       "The adapters reduce a square/C4 count to butterflies. A global total contains insufficient information to recover which vertices/edges participated. Decomposition is another algorithm.",
       "Add per-embedding/per-edge accumulation or a listing path and implement peeling separately for cores. Do not reuse a total as membership output.",
       ref(E, "reuses existing GraphMiner square kernel"),
       ref(R, "C4 embeddings / 8"))
native("k-truss",
       "AccTD exposes full per-edge truss numbers for simple unweighted undirected input, subject to worker/index limits. No artificial small-k cap.",
       "Full decomposition computes all truss levels. This differs from collected cuGraph fixed-k extraction and Hornet fixed-k/maximum-k interfaces, which do not by themselves emit all edge trussness values.",
       "Use the existing full vector to select a requested truss; add weighted/directed definitions separately if required.",
       ref(R, "exact full per-edge truss decomposition"))
native("densest-subgraph",
       "The CDS public API fixes k=2 and returns unweighted edge count / selected vertex count. No clique-order parameter, weighted objective, minimum-cardinality variant or fixed-cardinality variant is exposed.",
       "The wrapper passes the literal string 2 to CDS, insists the returned k equals 2, and recomputes only induced edges. Problem 05 itself specifies edge density. The repaired standalone CLI already supports clique density and has recorded k=3,4,5,6 tests. This is incomplete higher-order integration, not a missing CDS algorithm.",
       "Add a clique-order contract/parameter, forward k, return clique_count/order, and check the witness using k-cliques. Expose the existing exact path without relabeling edge density as clique density. Fixed-cardinality densest-k-subgraph (problem 06) is a different task.",
       ref(R, 'invoke_worker("cds",{path.string(),"2"'),
       ref(R, 'integer(output.at("k"))==2'),
       ref("problems/05_densest_subgraph/problem.json", "total induced edge value"),
       ref("validation/algorithm_repairs/cds/README.md", "`k=5,6`"))
native("maximal-biclique-counting",
       "MBE-GPU exposes only an exact global count from the scheduled single-GPU variant. No memberships, partition-size filters, bitmap or multi-GPU mode.",
       "The repaired worker exports a count; its other upstream variants were not validated as this executable profile. This count-only operation is intentionally separate from cuMBE membership output.",
       "Add a verified output/filter path or integrate the appropriate upstream variant with separate evidence.",
       ref("catalog/repaired_profiles.json", "no vertex-set enumeration, size filters"),
       ref(R, "MaximalBicliqueCounting::run"))
native("personalized-pagerank",
       "kPAR: one seed, outgoing directed unweighted walks, restart probability exactly 0.2; epsilon 0.01..0.5, random_seed <=INT_MAX, approximate output with no certified error bound. Agent top_k <=1,000,000; worker outputs min(k,n).",
       "The source uses ALPHA_DEFAULT=0.2 inside propagation and index construction, not just as a CLI default. The narrower epsilon interval is a validated integration range; standalone parsing permits 0<epsilon<1. Random-walk indexes bind graph, alpha and epsilon.",
       "Thread alpha consistently through all kernels and rebuild indexes; validate other epsilon ranges. Multiple-seed distributions, weighted walks and exact convergence need additional paths. Approximate epsilon must not be advertised as a proven per-run error bound.",
       ref(paper(21, "2020_kpar", "code/src/util/config.h"), "ALPHA_DEFAULT = 0.2"),
       ref(paper(21, "2020_kpar", "code/src/algo/GtopkRrw.cuh"), "reserve += ALPHA_DEFAULT"),
       ref(R, "validated range [0.01,0.5]"),
       ref(paper(21, "2020_kpar", "code/src/main.cu"), "epsilon must be finite and strictly between 0 and 1"))
native("group-steiner-tree",
       "GPU4GST: 1..16 nonempty groups, nonnegative integer weights <=2^53-1 through the public graph format, conservative tree-cost bound <2^58, no hop/diameter constraint.",
       "The selected TrimCDP-WB variant indexes vertex-by-group-subset states using width=2^groups and 32-bit queues. Sixteen is a checked/validated profile bound, with exponential state growth behind it. The public weight limit preserves exact integers through double; 2^58 is the worker's infinity sentinel.",
       "Review state growth/index width and memory before increasing group count; use integer-preserving transport for wider weights. Integrate the separate hop-constrained variant to support hop limits.",
       ref(R, "group count must be in [1,16]"),
       ref(R, "GST requires explicit integer weights in [0,2^53-1]"),
       ref("validation/algorithm_repairs/gpu4gst/repair.patch", "+    int width = 1 << G, V = g->vert_count;"),
       ref("validation/algorithm_repairs/gpu4gst/README.md", "distinct 2^58 infinity value"))
native("influence-maximization",
       "SuperFuseR exposes independent cascade only, explicit probabilities [0,1], sample_count 32..65,536 in multiples of 32, one physical GPU, and no certified approximation guarantee.",
       "The selected kernels simulate/sketch independent live-edge cascades. Warp-oriented sampling explains the 32 alignment; the upper bound is a validated resource profile and vertex-by-sample state consumes memory. Empirical quality checks do not prove a general guarantee. Linear threshold is a different diffusion process.",
       "Expand resource/validation coverage for more samples and multi-GPU operation; implement a bound/certificate rather than setting guarantee_met=true. Other collected frameworks have other diffusion modes but are not integrated here.",
       ref(R, "sample_count must be a multiple of 32"),
       ref("validation/algorithm_repairs/superfuser/README.md", "vertex/sample state"),
       ref("validation/algorithm_repairs/superfuser/README.md", "not a general approximation guarantee"))

research([64], "PyTorch Cluster CUDA kNN",
         "Kernel neighbor count <=100. The default knn_graph(loop=False) requests k+1, making its effective user k ceiling 99.",
         "Each CUDA query has fixed best_dist[100] and best_idx[100] arrays. Removing the assertion would overrun storage; the extra neighbor allows self removal.",
         "Redesign top-k storage/selection or choose another backend; preserve non-self and duplicate-vector semantics.",
         ref(SRC + "torch_cluster-e9a855c284b4/csrc/cuda/knn_cuda.cu", "best_dist[100]"),
         ref(SRC + "torch_cluster-e9a855c284b4/torch_cluster/knn.py", "k if loop else k + 1"))
research([64], "Faiss GPU flat kNN",
         "Native selection max k is 2,048 for the modern CUDA build (1,024 in its older compiler branch); the cuVS-backed selection branch permits 16,384. A self-removing k+1 adapter consumes one slot.",
         "The limit belongs to the compiled GPU top-k selection implementation. It is not a universal nearest-neighbor limit and varies with backend configuration.",
         "Use a different selection/merge strategy or supported backend; test the actual build and exact non-self output, including ties.",
         ref(SRC + "faiss-07979b10e64d/faiss/gpu/impl/IndexUtils.cu", "return 16384"),
         ref(SRC + "faiss-07979b10e64d/faiss/gpu/utils/DeviceDefs.cuh", "#define GPU_MAX_SELECTION_K 2048"))
research([63], "CuPy Laplacian eigensolvers",
         "Lanczos eigsh requires 0<k<n; generalized M/Minv and non-normal modes are not supported in this entry point. LOBPCG switches to dense solving when n-constraints <5*block_size and rejects constraints in that fallback.",
         "These are partial-spectrum solver/subspace restrictions. Full dense eigh is a separate collected algorithm. Sparse shift-invert factorization and the small Ritz solve can involve CPU work.",
         "Dispatch to a solver matching the requested eigenpair count, constraints and GPU requirements; build the Laplacian and check residuals/nullspace explicitly.",
         ref(SRC + "cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py", "if k >= n:"),
         ref(SRC + "cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_eigen.py", "Minv is not yet supported"),
         ref(SRC + "cupy-379a2bedbca9/cupyx/scipy/sparse/linalg/_lobpcg.py", "if (n - sizeY) < (5 * sizeX):"))
research([43], "GARDENIA coloring",
         "The pinned implementation defines MAXCOLOR=128 and uses fixed color bitsets; it cannot be advertised as unrestricted distance-1 coloring.",
         "This is an implementation palette assumption, not a guarantee that every graph is colorable with 128 colors, or a minimum-color solver.",
         "Add dynamically sized palettes or an explicit overflow/fallback path and test graphs requiring more colors.",
         ref(SRC + "gardenia-5894df11cf47/include/common.h", "MAXCOLOR 128"))
research([68], "GraphMiner/Pangolin frequent subgraph mining",
         "Single-host MNI support and count output only. Inspected GPU aggregation specializes to three-vertex embeddings; GraphMiner has an 8,000-pattern bitset allocation and Pangolin 21,251. Generic-looking k arguments are not evidence of arbitrary pattern support.",
         "Aggregation contains n<4 / n==3 assertions and fixed small/middle/large vertex domains. General larger-pattern canonicalization/aggregation is absent from this path. This also differs from graph-transaction support in problem 14.",
         "Expose explicit supported pattern bounds, guard pattern capacity, implement general canonicalization/domain support and listing before promising broader mining.",
         ref(SRC + "graphminer-2a76e3f612e4/src/fsm/gpu_base.cu", "#define MAX_NUM_PATTERNS 8000"),
         ref(SRC + "graphminer-2a76e3f612e4/src/fsm/gpu_base.cu", "assert(n == 3)"),
         ref(SRC + "graphminer-2a76e3f612e4/src/pangolin/fsm/fsm.h", "#define MAX_NUM_PATTERNS 21251"),
         ref(SRC + "graphminer-2a76e3f612e4/src/pangolin/fsm/base.cu", "assert(n == 3)"))
research([7, 8, 10], "cuGraph structural kernels",
         "Core numbers and k-truss require symmetric, non-multigraph input. cuGraph k_truss returns a requested subgraph, not all edge trussness; triangle APIs do not provide triangle memberships.",
         "The algorithms assume simple undirected topology, and output interfaces expose only their specific primitive. A paper/source pair does not supply the missing decomposition or listing stage.",
         "Normalize under an explicit contract and implement missing output stages; use AccTD for the currently integrated full truss decomposition.",
         ref(CG + "cpp/src/cores/core_number_impl.cuh", "!graph_view.is_multigraph()"),
         ref(CG + "cpp/src/community/k_truss_impl.cuh", "graph_view.is_symmetric()"))
research([16], "cuGraph ECG settings",
         "This pinned ECG source enforces 0<resolution<=1, 0<threshold<=1, ensemble_size>=1 and min_weight>=0.",
         "These are specific entry-point guards. The resolution cap should not be attributed to modularity theory or copied onto every Louvain/Leiden implementation. The min_weight error message says positive although the code permits zero.",
         "Expose the exact selected implementation's ranges and verify alternatives when resolution>1 is needed.",
         ref(CG + "cpp/src/community/ecg_impl.cuh", "resolution > 0.0 && resolution <= 1.0"),
         ref(CG + "cpp/src/community/ecg_impl.cuh", "min_weight >= weight_t{0.0}"))
research([18, 21], "cuGraph iterative centrality/PPR",
         "Katz and PageRank check alpha in [0,1] and nonnegative tolerances; personalization needs positive total mass. Katz convergence also depends on attenuation relative to the adjacency spectral radius.",
         "A syntactically accepted iteration parameter is not a convergence certificate. For PageRank alpha denotes continuation/damping; kPAR's alpha=0.2 denotes restart, so identical numbers do not mean identical walks.",
         "Map parameter conventions, dangling behavior and tolerances explicitly; check convergence and validate scores. Treat the Katz spectral-radius statement as the mathematical convergence condition, not an additional source-enforced check.",
         ref(CG + "cpp/src/centrality/katz_centrality_impl.cuh", "(alpha >= 0.0) && (alpha <= 1.0)"),
         ref(CG + "cpp/src/link_analysis/pagerank_impl.cuh", "personalization_sum > 0.0"))
research([38, 39, 40], "cuGraph traversals",
         "Direction-optimizing BFS requires a symmetric graph; SSSP/OD reject negative weights when expensive validation is enabled. The collected OD distances entry point is single-GPU.",
         "Direction-optimizing traversal and nonnegative relaxation rely on those graph assumptions. The OD source has an explicit compile-time multi-GPU exclusion; cuGraph as a library having multi-GPU support does not make every algorithm multi-GPU.",
         "Select an appropriate path algorithm and input representation; distinguish optional expensive validation from unconditional guards.",
         ref(CG + "cpp/src/traversal/bfs_impl.cuh", "input graph should be symmetric for direction optimizing BFS"),
         ref(CG + "cpp/src/traversal/sssp_impl.cuh", "num_negative_edge_weights == 0"),
         ref(CG + "cpp/src/traversal/od_shortest_distances_impl.cuh", "We currently do not support multi-GPU"))
research([48], "cuGraph ego extraction",
         "The pinned C++ ego APIs require 0<radius<n; one overload also requires 0<number_of_sources<n. Edge masks are unsupported in the inspected path.",
         "These are implementation/API preconditions. A radius-zero ego consisting only of its seed is mathematically valid, so it needs an adapter/trivial path rather than a claim that the task is undefined.",
         "Implement radius-zero/empty/all-seed boundary cases explicitly and select supported edge-mask handling.",
         ref(CG + "cpp/src/community/egonet_impl.cuh", "radius > 0"))
research([19, 46], "cuGraph masked graphs",
         "The inspected similarity wrappers and random-walk entry points reject a graph with an edge mask.",
         "The selected implementation does not support that storage/view mode. This is unrelated to the existence of Jaccard, cosine, Sorensen, overlap or random-walk algorithms.",
         "Materialize the intended filtered graph or use a supported view while preserving IDs and weights.",
         ref(CG + "cpp/src/link_prediction/jaccard_impl.cuh", "!graph_view.has_edge_mask()"),
         ref(CG + "cpp/src/sampling/random_walks_impl.cuh", "!graph_view.has_edge_mask()"))
research([44, 54, 55, 62, 66, 69], "Objective and pipeline restrictions",
         "Greedy matching is approximate; HySpecPro's public driver is two-way; dyGRASS needs an initial sparsifier and updates; quotient/coarsening routines need an assignment; learned MIS/MVC lack optimum certificates. Component-aware MVC may report size/decision without a witness.",
         "These limitations come from the selected objective, input pipeline or output contract. They cannot be removed by increasing a numeric parameter. Hybrid CPU initialization/decoding is present in several releases.",
         "Implement the missing stages, choose a matching algorithm, and state approximate versus exact output explicitly. Per-record notes and source paths are retained in the JSON inventory.",
         ref(paper(54, "2026_hyspecpro", "metadata.json"), "two-way partitioning"),
         ref(paper(55, "2025_dygrass_incremental", "metadata.json"), "initial sparsifier"),
         ref(paper(66, "2023_difusco_mis", "metadata.json"), "feasibility does not certify optimality"))
research([12, 14, 17, 24, 26, 27, 32, 34, 37, 49, 57, 58, 59], "Missing output or different mathematical task",
         "Examples: graphlet counts omit vertex orbits; local PPR omits community selection; signed-balance releases emit statistics rather than minimum-frustration certificates; approximate GED is not exact GED; chordless cycles, circuit timing and sparse fused lasso are restricted/different objectives.",
         "A related implementation or paper does not automatically solve every mode in its problem statement. Some folders have no runnable GPU source, so there is no verifiable parameter envelope to lift.",
         "Keep missing modes unavailable until a complete pipeline with matching outputs is integrated. The per-record inventory retains semantic-fit and artifact availability without treating either as runtime correctness.",
         ref(paper(12, "2022_g2miner_enumeration", "metadata.json"), "No per-vertex orbit counts"),
         ref(paper(49, "2019_graphblast_lgc", "metadata.json"), "not a selected community"),
         ref(paper(59, "2014_gunrock_sparse_fused_lasso", "metadata.json"), "Extra vertex sparsity penalty"))


INTRO = """# Parameter and objective limit audit

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
"""


def link(ev):
    return f"[{ev['path']}:{ev['line']}](../../{ev['path']}#L{ev['line']})"


def render_finding(row, title):
    lines = [f"### {title}", "", row["limits"], "",
             "**Why:** " + row["reason"], "",
             "**What expansion requires:** " + row["expansion_work"], "",
             "Evidence: " + "; ".join(link(ev) for ev in row["evidence"]) + ".", ""]
    return lines


GUARD = re.compile(r"(?:raise (?:ValueError|NotImplementedError)|TORCH_CHECK|RAFT_EXPECTS|CUGRAPH_EXPECTS|AT_ASSERT|FAISS_THROW|assert\(|unsupported|not supported|only supports|must be|must have|#define.*MAX|constexpr.*MAX|[a-zA-Z_]max_length\s*=)")


def main():
    registry = read("catalog/backend_registry.json")
    catalog = read("graphmine_catalog.json")
    instructions = {o["id"]: o for o in read("agent/program_instructions.json")["operations"]}
    ops = {o["id"]: o for o in registry["operations"]}
    assert len(NATIVE) == len(ops) == 24
    assert {r["operation_id"] for r in NATIVE} == set(ops)
    assert sum(len(o["backends"]) for o in ops.values()) == 38
    for row in NATIVE:
        o = ops[row["operation_id"]]
        row["problem_id"] = o["research_problem"]
        row["backends"] = [b["id"] for b in o["backends"]]
        row["planner_parameters"] = instructions[o["id"]].get("parameters", {})
        row["planner_backend_constraints"] = instructions[o["id"]].get("backend_constraints", {})
    for row in NATIVE + RESEARCH:
        row["evidence"] = [evidence(*r) for r in row.pop("references")]

    runtime_by_paper = {}
    for o in catalog["operations"]:
        for b in o.get("backend_details", []):
            for a in b.get("source_artifacts", []):
                runtime_by_paper.setdefault((a["problem_id"], a["paper_id"]), []).append(
                    {"operation_id": o["id"], "backend_id": b["id"]})
    records, problems = [], []
    for directory in sorted((ROOT / "problems").glob("[0-9][0-9]_*")):
        spec = json.loads((directory / "problem.json").read_text())
        problem_records = []
        for path in sorted((directory / "papers").glob("*/metadata.json")):
            meta = json.loads(path.read_text())
            sources = []
            for entry in meta.get("code_entrypoints", []):
                p = path.parent / "code" / entry
                item = {"path": str(p.relative_to(ROOT)), "exists": p.is_file()}
                if p.is_file():
                    item["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
                    item["guard_candidates"] = []
                    if p.suffix not in {".md", ".txt"}:
                        lines = p.read_text(errors="replace").splitlines()
                        for i, line in enumerate(lines):
                            if GUARD.search(line):
                                item["guard_candidates"].append({"line": i + 1,
                                    "context": "\n".join(lines[max(0, i - 1):i + 4])})
                sources.append(item)
            runtime = runtime_by_paper.get((spec["problem_id"], meta["paper_id"]), [])
            record = dict(problem_id=spec["problem_id"], paper_id=meta["paper_id"],
                          title=meta["title"], metadata_path=str(path.relative_to(ROOT)),
                          metadata_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          code_url=meta.get("code_url"), publication_url=meta.get("publication_url"),
                          semantic_fit=meta.get("semantic_fit"), existing_notes=meta.get("notes"),
                          gpu_scope=meta.get("gpu_scope"), entrypoints=sources,
                          runtime_connections=runtime,
                          review_level="native_adapter_and_metadata" if runtime else
                          "metadata_and_entrypoint_guard_screen" if any(s["exists"] for s in sources) else
                          "metadata_only_no_declared_local_entrypoint",
                          unknowns="No new execution; no exhaustive audit of transitive kernels. An absent numeric guard does not imply unlimited support.")
            records.append(record)
            problem_records.append(meta["paper_id"])
        problems.append(dict(problem_id=spec["problem_id"], directory=directory.name,
                             name=spec["name"], problem_inputs=spec.get("problem_inputs", []),
                             graph_requirements=spec.get("graph_input", {}).get("requirements", {}),
                             records=problem_records,
                             runtime_operations=[r["operation_id"] for r in NATIVE if r["problem_id"] == spec["problem_id"]],
                             research_findings=[r["title"] for r in RESEARCH if int(directory.name[:2]) in r["problem_numbers"]]))
    assert len(problems) == 70 and len(records) == 219
    counts = dict(problem_contracts=70, research_records=219, exposed_operations=24,
                  backend_choices=38,
                  records_with_declared_local_entrypoints=sum(any(s["exists"] for s in r["entrypoints"]) for r in records),
                  declared_entrypoints_read=sum(s["exists"] for r in records for s in r["entrypoints"]),
                  source_guard_candidates=sum(len(s.get("guard_candidates", [])) for r in records for s in r["entrypoints"]),
                  evidence_anchors_checked=sum(len(r["evidence"]) for r in NATIVE + RESEARCH),
                  new_gpu_runs=0)
    audit = dict(date=DATE, scope="static working-tree audit; collected paper metadata is not runtime support",
                 counts=counts, native_findings=NATIVE, research_findings=RESEARCH,
                 problem_inventory=problems, research_inventory=records)
    (OUT / (STEM + ".json")).write_text(json.dumps(audit, indent=2) + "\n")
    lines = [INTRO]
    for row in NATIVE:
        lines.extend(render_finding(row, row["operation_id"] + " — " + ", ".join(row["backends"])))
    lines.extend(["## Additional collected implementations", "",
                  "These are source-level research findings, not claims of newly executable GraphMine backends.", ""])
    for row in RESEARCH:
        lines.extend(render_finding(row, row["title"]))
    lines.extend(["## Shared limits and misleading signals", "",
        "* Worker profiles impose one GPU, at most 1,000,000 vertices / 10,000,000 input edges, bounded timeout/output, and further algorithm-specific limits. These are not performance guarantees at those sizes.",
        "* Counts and index widths are separate. Even a graph fitting 32-bit vertex IDs can have a clique/embedding count exceeding 64 bits. Raising k requires an overflow policy, not just a larger accepted integer.",
        "* A result limit often bounds returned rows only. k-clique materialization still traverses all matches for consistency/participation; cuQC truncates after generation. GPU count kernels can still do the full work.",
        "* Collection `semantic_fit=exact` describes alignment with a problem family. It is not an exact-optimization or runtime-correctness certificate. Older metadata can describe pre-repair behavior; current native profiles and versioned repair evidence take precedence.",
        "* GraphSet's catalog tag records k=3..5 validation while native/agent acceptance extends to six. That distinction should be represented explicitly rather than treating either number as a universal capability claim.",
        "* WeTriC's planner accepts arbitrary positive matrix lengths, while native code requires a multiple of 64. Direct TurboBC callers can pass weights that are lost in topology conversion, although agent weighted-intent checks reject that request.", "",
        "## Work to prioritize", "",
        "1. Expose CDS clique order and generalize its result/certificate contract; existing standalone higher-order evidence makes this the clearest missing integration.",
        "2. Expand KCGPU and GAMMA validation with known-count higher-k graphs, relabeling, sparse/dense cases, overflow checks and CUDA sanitizers; separately reconcile GraphSet's accepted and tested ranges.",
        "3. Make supported range, tested range, objective, GPU/host stages, count/listing behavior and resource limits explicit per backend. Correct planner/native discrepancies before claiming wider support.",
        "4. Add general motif generation, temporal patterns and weighted/resolution community options as complete features, with matching output validation.",
        "5. Redesign fixed candidate/palette/top-k buffers and assignment/reachability output paths where broader workloads require it. Treat these as engineering changes with boundary tests, not simple removal of guards.", "",
        "## Complete inventory", "",
        f"[{STEM}.json]({STEM}.json) contains every problem and research record, entry-point hashes, candidate guard context, planner parameter schemas and {counts['evidence_anchors_checked']} checked evidence anchors. Raw guard matches can belong to other functions in shared files; confirmed findings above were reviewed in context.", "",
        "| Problem | Research records screened | Exposed operations |", "|---|---:|---|"])
    for p in problems:
        lines.append(f"| [{p['directory']}](../{p['directory']}/problem.json) | {len(p['records'])} | {', '.join(p['runtime_operations']) or 'None; research collection only'} |")
    lines.extend(["", "Validation of this audit: all operation/backend inventory counts, source anchors and evidence paths are checked by the generator. Algorithm behavior was not changed.", ""])
    (OUT / (STEM + ".md")).write_text("\n".join(lines))
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
