GPU graph research collection — internet and library sweep
=============================================================

Current inventory: 70 problems and 219 research/implementation records. This sweep added 10 problems and 85 records.

This is a research collection. A local source snapshot or paper does not establish buildability, correctness, performance, or library/agent integration. Existing validated backends retain their separate evidence.

The target is three eligible local GPU implementations with research papers. Distinct implementations may share a framework paper; this is not a count of independent publications. Documentation-only code is retained but does not satisfy the paper target. Building blocks and mismatched objectives do not count. Legacy records are reconciled against actual files and reviewed implementation paths; this does not replace their runtime validation history.

| Problem | Records | Local code | Local PDFs | Reviewed pairs / 3 | Legacy records |
|---|---:|---:|---:|---:|---:|
| [01_maximal_clique_enumeration](../01_maximal_clique_enumeration/problem.json) | 3 | 3 | 1 | 1/3 | 3 |
| [02_maximum_clique](../02_maximum_clique/problem.json) | 3 | 3 | 3 | 3/3 | 3 |
| [03_k_clique_counting_enumeration](../03_k_clique_counting_enumeration/problem.json) | 3 | 3 | 2 | 2/3 | 3 |
| [04_quasi_clique_mining](../04_quasi_clique_mining/problem.json) | 1 | 1 | 1 | 1/3 | 1 |
| [05_densest_subgraph](../05_densest_subgraph/problem.json) | 1 | 0 | 1 | 0/3 | 1 |
| [06_densest_k_subgraph](../06_densest_k_subgraph/problem.json) | 0 | 0 | 0 | 0/3 | 0 |
| [07_k_core_decomposition](../07_k_core_decomposition/problem.json) | 4 | 4 | 3 | 3/3 | 1 |
| [08_k_truss_decomposition](../08_k_truss_decomposition/problem.json) | 3 | 3 | 2 | 1/3 | 1 |
| [09_maximal_biclique_enumeration](../09_maximal_biclique_enumeration/problem.json) | 3 | 1 | 3 | 1/3 | 3 |
| [10_triangle_counting_listing](../10_triangle_counting_listing/problem.json) | 7 | 7 | 4 | 4/3 | 3 |
| [11_graph_motif_counting](../11_graph_motif_counting/problem.json) | 3 | 3 | 2 | 2/3 | 3 |
| [12_graphlet_counting](../12_graphlet_counting/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [13_subgraph_isomorphism](../13_subgraph_isomorphism/problem.json) | 1 | 1 | 1 | 1/3 | 1 |
| [14_frequent_subgraph_mining](../14_frequent_subgraph_mining/problem.json) | 0 | 0 | 0 | 0/3 | 0 |
| [15_temporal_motif_mining](../15_temporal_motif_mining/problem.json) | 2 | 2 | 2 | 2/3 | 2 |
| [16_community_detection](../16_community_detection/problem.json) | 5 | 5 | 1 | 1/3 | 2 |
| [17_overlapping_community_detection](../17_overlapping_community_detection/problem.json) | 0 | 0 | 0 | 0/3 | 0 |
| [18_centrality_influential_node_mining](../18_centrality_influential_node_mining/problem.json) | 8 | 8 | 5 | 5/3 | 1 |
| [19_link_prediction](../19_link_prediction/problem.json) | 4 | 4 | 0 | 0/3 | 0 |
| [20_graph_anomaly_detection](../20_graph_anomaly_detection/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [21_personalized_pagerank_rwr](../21_personalized_pagerank_rwr/problem.json) | 4 | 4 | 3 | 3/3 | 1 |
| [22_max_flow_min_cut](../22_max_flow_min_cut/problem.json) | 3 | 1 | 3 | 1/3 | 3 |
| [23_butterfly_counting_bipartite](../23_butterfly_counting_bipartite/problem.json) | 4 | 2 | 4 | 2/3 | 4 |
| [24_graph_edit_distance_mcs](../24_graph_edit_distance_mcs/problem.json) | 2 | 1 | 2 | 1/3 | 2 |
| [25_network_alignment](../25_network_alignment/problem.json) | 6 | 3 | 3 | 3/3 | 3 |
| [26_hop_constrained_cycle_path_enumeration](../26_hop_constrained_cycle_path_enumeration/problem.json) | 3 | 1 | 1 | 0/3 | 2 |
| [27_group_steiner_tree](../27_group_steiner_tree/problem.json) | 3 | 2 | 1 | 0/3 | 3 |
| [28_influence_maximization](../28_influence_maximization/problem.json) | 4 | 3 | 3 | 2/3 | 4 |
| [29_simrank_vertex_similarity](../29_simrank_vertex_similarity/problem.json) | 1 | 0 | 0 | 0/3 | 1 |
| [30_balanced_graph_partitioning](../30_balanced_graph_partitioning/problem.json) | 3 | 0 | 1 | 0/3 | 3 |
| [31_bipartite_matching_assignment](../31_bipartite_matching_assignment/problem.json) | 3 | 2 | 1 | 0/3 | 2 |
| [32_signed_network_structural_balance](../32_signed_network_structural_balance/problem.json) | 2 | 2 | 2 | 0/3 | 2 |
| [33_transitive_closure_reachability](../33_transitive_closure_reachability/problem.json) | 3 | 1 | 3 | 1/3 | 3 |
| [34_entity_resolution_blocking](../34_entity_resolution_blocking/problem.json) | 1 | 0 | 1 | 0/3 | 1 |
| [35_connected_components](../35_connected_components/problem.json) | 7 | 6 | 5 | 4/3 | 2 |
| [36_graph_layout_force_directed](../36_graph_layout_force_directed/problem.json) | 2 | 2 | 1 | 1/3 | 1 |
| [37_null_model_significance_testing](../37_null_model_significance_testing/problem.json) | 0 | 0 | 0 | 0/3 | 0 |
| [38_breadth_first_search](../38_breadth_first_search/problem.json) | 5 | 5 | 4 | 4/3 | 0 |
| [39_single_source_shortest_paths](../39_single_source_shortest_paths/problem.json) | 5 | 5 | 4 | 4/3 | 0 |
| [40_many_source_shortest_paths](../40_many_source_shortest_paths/problem.json) | 4 | 4 | 3 | 3/3 | 0 |
| [41_spanning_tree_forest](../41_spanning_tree_forest/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [42_maximal_independent_set](../42_maximal_independent_set/problem.json) | 5 | 5 | 4 | 4/3 | 0 |
| [43_vertex_coloring](../43_vertex_coloring/problem.json) | 4 | 4 | 3 | 3/3 | 0 |
| [44_general_graph_weighted_matching](../44_general_graph_weighted_matching/problem.json) | 6 | 4 | 3 | 3/3 | 0 |
| [45_topological_sort](../45_topological_sort/problem.json) | 3 | 2 | 2 | 0/3 | 0 |
| [46_random_walk_generation](../46_random_walk_generation/problem.json) | 4 | 4 | 3 | 3/3 | 0 |
| [47_neighborhood_sampling](../47_neighborhood_sampling/problem.json) | 4 | 4 | 3 | 3/3 | 0 |
| [48_induced_subgraph_ego_extraction](../48_induced_subgraph_ego_extraction/problem.json) | 5 | 5 | 3 | 3/3 | 0 |
| [49_seeded_local_community_detection](../49_seeded_local_community_detection/problem.json) | 3 | 3 | 3 | 0/3 | 0 |
| [50_node_embedding](../50_node_embedding/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [51_knowledge_graph_embedding](../51_knowledge_graph_embedding/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [52_node_classification_regression](../52_node_classification_regression/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [53_graph_classification_regression](../53_graph_classification_regression/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [54_hypergraph_partitioning](../54_hypergraph_partitioning/problem.json) | 5 | 5 | 3 | 3/3 | 0 |
| [55_spectral_graph_sparsification](../55_spectral_graph_sparsification/problem.json) | 3 | 2 | 3 | 2/3 | 0 |
| [56_biconnected_components](../56_biconnected_components/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [57_temporal_fastest_paths](../57_temporal_fastest_paths/problem.json) | 3 | 0 | 1 | 0/3 | 0 |
| [58_top_k_critical_paths_dag](../58_top_k_critical_paths_dag/problem.json) | 3 | 0 | 3 | 0/3 | 0 |
| [59_graph_signal_denoising](../59_graph_signal_denoising/problem.json) | 3 | 1 | 3 | 0/3 | 0 |
| [60_graph_based_geolocation](../60_graph_based_geolocation/problem.json) | 3 | 3 | 2 | 2/3 | 0 |
| [61_widest_paths](../61_widest_paths/problem.json) | 1 | 1 | 0 | 0/3 | 0 |
| [62_graph_coarsening](../62_graph_coarsening/problem.json) | 3 | 3 | 1 | 1/3 | 0 |
| [63_graph_laplacian_eigenpairs](../63_graph_laplacian_eigenpairs/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [64_knn_graph_construction](../64_knn_graph_construction/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [65_hypergraph_node_learning](../65_hypergraph_node_learning/problem.json) | 3 | 3 | 3 | 3/3 | 0 |
| [66_maximum_independent_set](../66_maximum_independent_set/problem.json) | 3 | 2 | 3 | 2/3 | 0 |
| [67_persistent_homology](../67_persistent_homology/problem.json) | 1 | 1 | 1 | 1/3 | 0 |
| [68_single_graph_frequent_subgraph_mining](../68_single_graph_frequent_subgraph_mining/problem.json) | 2 | 2 | 2 | 2/3 | 0 |
| [69_minimum_vertex_cover](../69_minimum_vertex_cover/problem.json) | 3 | 2 | 3 | 2/3 | 0 |
| [70_graph_condensation](../70_graph_condensation/problem.json) | 3 | 3 | 3 | 3/3 | 0 |

Libraries and upstream projects with new records
------------------------------------------------

| Source project | Newly added records | Pinned revision |
|---|---:|---|
| [apsp_blocked_lic](https://github.com/MTB90/cuda-floyd_warshall) | 1 | `c21f114eb4da` |
| [cugraph](https://github.com/rapidsai/cugraph) | 29 | `5931900cf6be` |
| [cupy](https://github.com/cupy/cupy) | 3 | `379a2bedbca9` |
| [cuvs](https://github.com/rapidsai/cuvs) | 1 | `24b0b17069ee` |
| [dgl](https://github.com/dmlc/dgl) | 1 | `3d16000b4170` |
| [dhg](https://github.com/iMoonLab/DeepHypergraph) | 3 | `b4f80211c217` |
| [difusco](https://github.com/Edward-Sun/DIFUSCO) | 1 | `65eb3b7bde76` |
| [dynamic_mis](https://github.com/LIONS-EPFL/dynamic-MIS) | 2 | `32462fa7fb4b` |
| [faiss](https://github.com/facebookresearch/faiss) | 1 | `07979b10e64d` |
| [fastpartitioner](https://github.com/sparcityeu/FastPartitioner) | 1 | `6697fcbe5bd9` |
| [graphblast](https://github.com/gunrock/graphblast) | 4 | `f56f9677276c` |
| [graphminer](https://github.com/chenxuhao/GraphMiner) | 5 | `2a76e3f612e4` |
| [graphslim](https://github.com/Emory-Melody/GraphSlim) | 3 | `2a120ed49e50` |
| [gunrock](https://github.com/gunrock/gunrock) | 4 | `748f79e66cc2` |
| [gunrock_legacy](https://github.com/gunrock/gunrock) | 1 | `386d04450b9a` |
| [hornet](https://github.com/hornet-gt/hornet) | 8 | `2441ccabd44a` |
| [hyspecpro](https://github.com/NVlabs/HySpecPro) | 1 | `1e9db172ce26` |
| [mg_mis](https://github.com/burtscher/MG-MIS) | 1 | `db7fb2355ac6` |
| [mvc_components](https://github.com/HusseinAmro/component-aware-vertex-cover-gpu) | 1 | `9adba41659d3` |
| [nvgraph](https://github.com/rapidsai/nvgraph) | 2 | `1ea93b51387b` |
| [pyg](https://github.com/pyg-team/pytorch_geometric) | 1 | `79d33965a40b` |
| [pygmtools](https://github.com/Thinklab-SJTU/pygmtools) | 3 | `5b7b3f84a345` |
| [pygod](https://github.com/pygod-team/pygod) | 3 | `c84dccafa9bf` |
| [ripserplusplus](https://github.com/simonzhang00/ripser-plusplus) | 1 | `30243c0c752d` |
| [torch_cluster](https://github.com/rusty1s/pytorch_cluster) | 2 | `e9a855c284b4` |

Search coverage and limitations
-------------------------------

The sweep combined official library APIs, pinned implementation files, author repositories, publication pages, and targeted searches for missing problems. It does not claim exhaustive coverage of the entire internet.

[Library coverage and research decisions](sweep_additions_2026_10_09.json) · [Repository searches](repository_search_2026_10_09.json) · [Full inventory](research_inventory_2026_10_09.json) · [Change totals](sweep_result_2026_10_09.json)

Incomplete targets
------------------

- **01_maximal_clique_enumeration**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **03_k_clique_counting_enumeration**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **04_quasi_clique_mining**: Only cuQC is currently paired with verified local GPU source and paper; no two further matching GPU quasi-clique artifacts were verified.
- **05_densest_subgraph**: The existing CDS source reference lacks a detected redistribution license. Densest-subgraph optimization is not interchangeable with k-core peeling.
- **06_densest_k_subgraph**: No licensed public GPU implementation matching fixed-cardinality densest-k-subgraph was verified. Clique and unrestricted density objectives do not satisfy this contract.
- **08_k_truss_decomposition**: Fixed-k truss extraction is not a complete trussness decomposition; library building blocks and the available decomposition artifacts are listed separately.
- **09_maximal_biclique_enumeration**: MBE-GPU source references are present but redistribution license terms were not detected; cuMBE remains a separate artifact.
- **11_graph_motif_counting**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **13_subgraph_isomorphism**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **14_frequent_subgraph_mining**: The contract uses support across a collection of graph transactions. GraphMiner/Pangolin use single-graph MNI support and are cataloged separately in problem 68.
- **15_temporal_motif_mining**: Everest and Mayura remain the two verified local temporal motif artifacts; static motif counters do not honor temporal ordering/window semantics.
- **16_community_detection**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **17_overlapping_community_detection**: The current contract is k-clique percolation. Generic overlapping community models and ordinary Louvain/Leiden are not equivalent; no matching public GPU artifact was verified.
- **19_link_prediction**: cuGraph provides verified GPU similarity/link-score code, but no associated research PDF was verified for these library implementations. Documentation does not count as a research paper.
- **22_max_flow_min_cut**: Some older GPU max-flow source references lack a detected license or public source release; their publication records remain explicit.
- **23_butterfly_counting_bipartite**: Some butterfly-counting papers lack a verified public GPU artifact; rectangle kernels require inspection of bipartite and counting semantics before they qualify.
- **24_graph_edit_distance_mcs**: Graph matching/alignment optimizes a different objective from certified GED/MCS. Public fast-GED source exists in the older workspace; license and semantic review remain explicit.
- **26_hop_constrained_cycle_path_enumeration**: cuGraph simple cycles is documented, but no associated research PDF was verified; cycle-only routines do not implement all bounded-path modes.
- **27_group_steiner_tree**: Ordinary terminal Steiner tree handles only singleton groups, and circuit-specific routing does not establish unrestricted group Steiner support.
- **28_influence_maximization**: Fewer than three eligible local GPU implementation/research-paper pairs; individual records state missing artifacts or variant restrictions.
- **29_simrank_vertex_similarity**: No new verified GPU SimRank artifact was found. Jaccard, cosine and learned embeddings do not solve the SimRank fixed-point objective.
- **30_balanced_graph_partitioning**: Public GPU partitioning references were reviewed, but a new complete licensed code-and-paper trio was not verified. Hypergraph partitioning and unconstrained modularity are distinct problems.
- **31_bipartite_matching_assignment**: Weighted dense assignment and unweighted bipartite cardinality matching are explicit variants; the cuGraph legacy implementation has documentation but no paired GPU research PDF.
- **32_signed_network_structural_balance**: GraphB+ and ECL-SGB source availability is restored where licensed; fewer than three independent implementation records have a verified local paper.
- **33_transitive_closure_reachability**: GDlog supplies GPU transitive-closure evaluation. Paper-only references remain incomplete; repeated BFS building blocks are not recorded as a fabricated new upstream algorithm.
- **34_entity_resolution_blocking**: HyperBlocker is a real GPU blocking artifact, but no license was detected for redistribution of a new snapshot. Similarity search alone is not the full entity-resolution blocking contract.
- **36_graph_layout_force_directed**: GPU ForceAtlas2 implementations are available; the library-only cuGraph entry has no paired GPU research paper.
- **37_null_model_significance_testing**: No matching GPU end-to-end degree-preserving null-ensemble significance artifact was verified. R-MAT generators, random walks and independent edge sampling do not preserve the required degree sequence.
- **45_topological_sort**: cuGraph has CUDA topological levels, but no paired research PDF was verified. DGL topological traversal falls back to CPU, and TopoGPU solves a restricted image-derived DAG.
- **49_seeded_local_community_detection**: PPR/diffusion kernels omit the required seed-containing conductance sweep and community result. They remain building blocks, not complete local-community algorithms.
- **55_spectral_graph_sparsification**: dyGRASS incremental and decremental variants require an initial sparsifier. No third licensed GPU source-and-paper pair was verified; GraphSlim sparsification uses CPU NetworKit.
- **57_temporal_fastest_paths**: The temporal path papers were reviewed, but no matching public GPU source release was verified. Static SSSP cannot replace time-respecting earliest-arrival/fastest-path semantics.
- **58_top_k_critical_paths_dag**: G-PathGen has a research PDF but no verified public source release. Circuit-specific bounded path analysis and CPPR are different/restricted tasks.
- **59_graph_signal_denoising**: No complete matching GPU graph-signal denoising solver was verified. Sparse fused-lasso primitives and learned node classifiers do not establish the specified denoising objective.
- **60_graph_based_geolocation**: Gunrock geolocation and HB-Geo are paired. GT-Geo source is available but its associated publisher PDF could not be collected from a verified open source.
- **61_widest_paths**: The archived nvGRAPH widest-path implementation is local; its manual is documentation, so the research-paper target remains open.
- **62_graph_coarsening**: GPU quotient construction is available in cuGraph, nvGRAPH and PyG. Only PyG currently has a paired framework PDF; supplied assignment and clustering generation are separate stages.
- **66_maximum_independent_set**: Dynamic-MIS and DIFUSCO are paired heuristic implementations. pCQO has a paper but its referenced branch/license availability prevents a new redistributable source snapshot.
- **67_persistent_homology**: Ripser++ is a verified hybrid GPU artifact. CPU Ripser/GUDHI and image-only persistence routines do not create two additional matching GPU pairs.
- **68_single_graph_frequent_subgraph_mining**: Two upstream GPU MNI mining implementations are included. Their count-only interfaces and compiled size limits remain explicit; transaction-support mining is separate.
- **69_minimum_vertex_cover**: Two eligible implementations are collected. The older parallel vertex-cover repository has no detected license and is retained as a reference only.

Verification
------------

Run `python3 problems/_collection/validate.py` for the expansion and `python3 problems/_collection/validate_sweep.py` for all problems, source hashes, publication references, new schemas, and generated inventory consistency.

No third-party code is compiled or executed by either collection validator. See [collection checks](validation_sweep_2026_10_09.json) and [catalog regression checks](catalog_checks_2026_10_09.json) for the actual scope and results.
