# Runtime coverage and research gaps

Each row refers to one collected paper/artifact record. Passing a scoped check does not certify every feature in its paper. Collection integrity checks are recorded separately from execution.

| Problem | Artifact | Runtime status | Scope or remaining gap |
| --- | --- | --- | --- |
| balanced_graph_partitioning | 2024_gkway | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| balanced_graph_partitioning | 2024_hyperg | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| balanced_graph_partitioning | 2025_igkway | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| biconnected_components | 2026_fast_bcc_filter | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| biconnected_components | 2026_pea_bcc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| biconnected_components | 2026_wk_bcc_2018 | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| bipartite_matching_assignment | 2013_deveci_mcm_gpu | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| bipartite_matching_assignment | 2019_hungariangpu | runtime_checks_passed | linear-assignment/hungarian-cuda: 200 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| bipartite_matching_assignment | 2026_cugraph_hungarian | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| breadth_first_search | 2017_gardenia_direction_bfs | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| breadth_first_search | 2017_gunrock_bfs | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| breadth_first_search | 2018_hornet_bfs | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| breadth_first_search | 2019_graphblast_bfs | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| breadth_first_search | 2026_cugraph_bfs | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| butterfly_counting_bipartite | 2022_g2miner_reuse | runtime_checks_passed | butterfly-counting/graphminer: 512 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| butterfly_counting_bipartite | 2022_gamma_reuse | runtime_checks_passed | butterfly-counting/gamma-butterfly: 512 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| butterfly_counting_bipartite | 2022_gbfc | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| butterfly_counting_bipartite | 2024_gbc_biclique | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| centrality_influential_node_mining | 2017_gunrock_bc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| centrality_influential_node_mining | 2018_hornet_bc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| centrality_influential_node_mining | 2018_hornet_katz | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| centrality_influential_node_mining | 2019_graphblast_pr | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| centrality_influential_node_mining | 2021_turbobc | runtime_checks_passed | betweenness-centrality/turbo-bc: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| centrality_influential_node_mining | 2026_cugraph_betweenness | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| centrality_influential_node_mining | 2026_cugraph_eigenvector | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| centrality_influential_node_mining | 2026_cugraph_katz | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| community_detection | 2026_cugraph_ecg | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| community_detection | 2026_cugraph_leiden | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| community_detection | 2026_cugraph_louvain | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| community_detection | 2026_gleiden | runtime_checks_passed | community-detection/gleiden: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| community_detection | 2026_multilevel_graph_clustering | runtime_checks_passed | community-detection/parallel-louvain: 624 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction); community-detection/parallel-leiden: 624 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction); community-detection/parallel-leiden-plus: 624 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| connected_components | 2017_gunrock_cc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| connected_components | 2018_eclcc | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| connected_components | 2018_hornet_cc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| connected_components | 2019_graphblast_cc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| connected_components | 2023_eclscc | runtime_checks_passed | connected-components/ecl-scc: 368 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| connected_components | 2026_cugraph_scc | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| connected_components | 2026_cugraph_wcc | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| densest_subgraph | 2026_bound_tightened_dsd | runtime_checks_passed | densest-subgraph/cds: 1336 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| entity_resolution_blocking | 2025_hyperblocker | not_runtime_validated | An older workspace copy exists, but no detected redistribution license was verified; no new source copy was made. |
| general_graph_weighted_matching | 2012_dgl_greedy_matching | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| general_graph_weighted_matching | 2012_torch_cluster_greedy_matching | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| general_graph_weighted_matching | 2015_gpu_suitor_kepler | not_runtime_validated | No public upstream GPU implementation was verified. |
| general_graph_weighted_matching | 2018_bootcmatch_suitor | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| general_graph_weighted_matching | 2024_locally_dominant_gpu | not_runtime_validated | No public upstream GPU implementation was verified. |
| general_graph_weighted_matching | 2026_cugraph_weighted_matching | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| graph_anomaly_detection | 2024_pygod_anomalydae | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_anomaly_detection | 2024_pygod_cola | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_anomaly_detection | 2024_pygod_dominant | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_based_geolocation | 2017_gunrock_spatial_median | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_based_geolocation | 2026_gt_geo | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_based_geolocation | 2026_hb_geo | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_classification_regression | 2018_pyg_diffpool | runtime_checks_passed | pyg-diffpool: 58 passed / 0 failed (CUDA/CPU layer-output parity only; no trained graph classifier) |
| graph_classification_regression | 2018_pyg_gin | runtime_checks_passed | pyg-gin: 58 passed / 0 failed (Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim) |
| graph_classification_regression | 2019_pyg_sagpool | runtime_checks_passed | pyg-sagpool: 58 passed / 0 failed (CUDA/CPU pooling parity only; no trained graph classifier) |
| graph_coarsening | 2019_pyg_average_pool | runtime_checks_passed | pyg-average-pool: 288 passed / 0 failed (Exact quotient for supplied assignment, drop self-loops, mean features, sum weights; no clustering generation) |
| graph_coarsening | 2026_cugraph_quotient | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| graph_coarsening | 2026_nvgraph_contraction | not_runtime_validated | Pinned legacy nvGraph configure fails at cpp/CMakeLists.txt:113 (empty include path); no runtime evidence. |
| graph_condensation | 2022_graphslim_doscond | not_runtime_validated | No condensation training/evaluation integration; synthetic graph quality and downstream accuracy remain untested. |
| graph_condensation | 2022_graphslim_gcdm | not_runtime_validated | No condensation training/evaluation integration; synthetic graph quality and downstream accuracy remain untested. |
| graph_condensation | 2022_graphslim_gcond | not_runtime_validated | No condensation training/evaluation integration; synthetic graph quality and downstream accuracy remain untested. |
| graph_edit_distance_mcs | 2016_gpu_mcs_drug_discovery | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| graph_edit_distance_mcs | 2026_fast_ged | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_laplacian_eigenpairs | 2017_cupy_dense_eigh | runtime_checks_passed | cupy-dense-eigh: 301 passed / 0 failed (Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues) |
| graph_laplacian_eigenpairs | 2017_cupy_lanczos | runtime_checks_passed | cupy-lanczos: 300 passed / 0 failed (Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues) |
| graph_laplacian_eigenpairs | 2017_cupy_lobpcg | runtime_failures | cupy-lobpcg: 298 passed / 2 failed (Pinned upstream algorithm; independent NumPy eigenvalues, residuals, orthonormality, repeated zero eigenvalues) |
| graph_layout_force_directed | 2017_gpugraphlayout | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graph_layout_force_directed | 2026_cugraph_force_atlas2 | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| graph_motif_counting | 2022_g2miner | runtime_checks_passed | graph-motifs/graphminer: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| graph_motif_counting | 2023_graphset | runtime_checks_passed | graph-motifs/graphset: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| graph_motif_counting | 2024_dumato | runtime_checks_passed | graph-motifs/dumato: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| graph_signal_denoising | 2014_gtf_admm | not_runtime_validated | No public upstream GPU implementation was verified. |
| graph_signal_denoising | 2014_gtf_projected_newton | not_runtime_validated | No public upstream GPU implementation was verified. |
| graph_signal_denoising | 2014_gunrock_sparse_fused_lasso | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graphlet_counting | 2022_g2miner_enumeration | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graphlet_counting | 2022_g2miner_formula | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| graphlet_counting | 2022_pangolin | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| group_steiner_tree | 2021_gpusteiner_kmb | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| group_steiner_tree | 2022_gpu_vlsi_gst | not_runtime_validated | An older workspace copy exists, but no detected redistribution license was verified; no new source copy was made. |
| group_steiner_tree | 2025_gpu4gst | runtime_checks_passed | group-steiner-tree/gpu4gst: 160 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| hop_constrained_cycle_path_enumeration | 2014_gpu_chordless_cycles | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| hop_constrained_cycle_path_enumeration | 2022_gpu_elementary_circuits | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| hop_constrained_cycle_path_enumeration | 2026_cugraph_simple_cycles | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| hypergraph_node_learning | 2020_dhg_hgnn | runtime_checks_passed | dhg-hgnn: 100 passed / 0 failed (Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim); dhg-hgnn-formula: 100 passed / 0 failed (Independent dense NumPy incidence-matrix formula for HGNN convolution) |
| hypergraph_node_learning | 2020_dhg_hnhn | runtime_checks_passed | dhg-hnhn: 100 passed / 0 failed (Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim) |
| hypergraph_node_learning | 2020_dhg_hypergcn | runtime_checks_passed | dhg-hypergcn: 55 passed / 0 failed (Upstream model forward/backward, finite logits and gradients; HGNN/HNHN CPU parity; no training/generalization claim); dhg-hypergcn-domain-rejection: 45 passed / 0 failed (Expected rejection of singleton hyperedges; no model output) |
| hypergraph_partitioning | 2025_ghypart | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| hypergraph_partitioning | 2026_axon_cuda | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| hypergraph_partitioning | 2026_fastpartitioner | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| hypergraph_partitioning | 2026_hgnn_part | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| hypergraph_partitioning | 2026_hyspecpro | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| induced_subgraph_ego_extraction | 2019_dgl_node_subgraph | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| induced_subgraph_ego_extraction | 2019_pyg_induced_subgraph | runtime_checks_passed | pyg-induced-subgraph: 288 passed / 0 failed (Exact selected-vertex edge extraction; caller preserves isolated vertices) |
| induced_subgraph_ego_extraction | 2019_pyg_khop_subgraph | runtime_checks_passed | pyg-khop-subgraph: 288 passed / 0 failed (Exact undirected k-hop induced extraction) |
| induced_subgraph_ego_extraction | 2026_cugraph_egonet | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| induced_subgraph_ego_extraction | 2026_cugraph_induced_subgraph | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| influence_maximization | 2020_curipples | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| influence_maximization | 2021_gim | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| influence_maximization | 2021_superfuser | runtime_checks_passed | influence-maximization/superfuser: 184 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| influence_maximization | 2024_difuser | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| k_clique_counting_enumeration | 2022_parallel_k_clique_counting | runtime_checks_passed | k-cliques/kcgpu: 1252 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| k_clique_counting_enumeration | 2023_graphset | runtime_checks_passed | k-cliques/graphset: 916 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| k_clique_counting_enumeration | 2024_gamma | runtime_checks_passed | k-cliques/gamma: 1000 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| k_core_decomposition | 2017_gunrock_kcore | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| k_core_decomposition | 2018_hornet_kcore | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| k_core_decomposition | 2023_accelerating_k_core_gpu | runtime_checks_passed | k-core/kcore-gpu: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| k_core_decomposition | 2026_cugraph_core_number | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| k_truss_decomposition | 2018_hornet_ktruss | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| k_truss_decomposition | 2020_accelerating_truss_heterogeneous | runtime_checks_passed | k-truss/acctd: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| k_truss_decomposition | 2026_cugraph_k_truss | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| knn_graph_construction | 2017_faiss_flat_knn | runtime_checks_passed | faiss-flat-knn: 200 passed / 0 failed (Collected GPU FlatL2 search plus explicit self-ID removal, exact distances and tied-neighbor optimum vs NumPy) |
| knn_graph_construction | 2019_torch_cluster_knn | runtime_failures | torch-cluster-knn: 203 passed / 51 failed (Exact squared-Euclidean directed kNN, distinct IDs including tied/duplicate vectors) |
| knn_graph_construction | 2021_cuvs_nn_descent | not_runtime_validated | No compatible cuVS runtime or NN-descent adapter established; approximate recall remains untested. |
| knowledge_graph_embedding | 2014_dgl_ke_distmult | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| knowledge_graph_embedding | 2016_dgl_ke_complex | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| knowledge_graph_embedding | 2019_dgl_ke_rotate | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| link_prediction | 2026_cugraph_cosine | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| link_prediction | 2026_cugraph_jaccard | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| link_prediction | 2026_cugraph_overlap | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| link_prediction | 2026_cugraph_sorensen | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| many_source_shortest_paths | 2010_blocked_cuda_floyd_warshall | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| many_source_shortest_paths | 2023_tensor_floyd_warshall | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| many_source_shortest_paths | 2023_tensor_r_kleene | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| many_source_shortest_paths | 2026_cugraph_od_distances | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| max_flow_min_cut | 2025_ecl_maxflow | runtime_checks_passed | max-flow-min-cut/ecl-maxflow: 184 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| max_flow_min_cut | 2025_generalized_maxflow_gpu | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| max_flow_min_cut | 2025_wbpr | not_runtime_validated | An older workspace copy exists, but no detected redistribution license was verified; no new source copy was made. |
| maximal_biclique_enumeration | 2023_efficient_mbe_gpus | runtime_checks_passed | maximal-biclique-counting/mbe-gpu: 512 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximal_biclique_enumeration | 2024_cumbe | runtime_checks_passed | maximal-bicliques/cumbe: 512 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximal_biclique_enumeration | 2025_advanced_mbe_gpu_bitmaps | not_runtime_validated | An older workspace copy exists, but no detected redistribution license was verified; no new source copy was made. |
| maximal_clique_enumeration | 2023_parallelizing_mce | runtime_checks_passed | maximal-cliques/mce-gpu: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximal_clique_enumeration | 2024_g2_aimd | runtime_checks_passed | maximal-cliques/g2-aimd: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximal_clique_enumeration | 2026_rdmce | runtime_checks_passed | maximal-cliques/rdmce: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximal_independent_set | 2016_lonestargpu_mis | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| maximal_independent_set | 2018_ecl_mis | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| maximal_independent_set | 2019_graphblast_mis | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| maximal_independent_set | 2025_mg_mis | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| maximal_independent_set | 2026_cugraph_mis | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| maximum_clique | 2019_maximum_clique_cuda | runtime_checks_passed | maximum-clique/cuda-ms: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximum_clique | 2023_maximum_clique_enumeration_gpu | runtime_checks_passed | maximum-clique/gpu-maximum-clique: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximum_clique | 2024_maximum_clique_many_core_gpu | runtime_checks_passed | maximum-clique/maximum-clique-on-gpu: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| maximum_independent_set | 2023_difusco_mis | not_runtime_validated | Learned solver has no validated checkpoint/inference integration here; feasibility and solution quality remain untested. |
| maximum_independent_set | 2023_dynamic_mis | not_runtime_validated | Learned solver has no validated checkpoint/inference integration here; feasibility and solution quality remain untested. |
| maximum_independent_set | 2025_pcqo_reference | not_runtime_validated | Published refactor branch unavailable; default-branch snapshot has no detected top-level license. |
| minimum_vertex_cover | 2022_parallel_mvc_reference | not_runtime_validated | No detected top-level license; new source redistribution blocked. |
| minimum_vertex_cover | 2023_dynamic_mvc | not_runtime_validated | Learned solver has no validated checkpoint/inference integration here; feasibility and solution quality remain untested. |
| minimum_vertex_cover | 2026_component_aware_mvc | runtime_checks_passed | component-aware-mvc-hybrid: 288 passed / 0 failed (Exact optimum SIZE vs exhaustive subsets; upstream exports no cover witness); component-aware-mvc-stackonly: 288 passed / 0 failed (Exact optimum SIZE vs exhaustive subsets; upstream exports no cover witness) |
| neighborhood_sampling | 2020_csaw_neighbors | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| neighborhood_sampling | 2020_nextdoor_neighbors | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| neighborhood_sampling | 2021_skywalker_neighbors | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| neighborhood_sampling | 2026_cugraph_neighbor_sampling | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| network_alignment | 2015_hga_2n | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| network_alignment | 2023_cualign | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| network_alignment | 2024_gpu_local_network_alignment | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| network_alignment | 2024_pygmtools_ipfp | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| network_alignment | 2024_pygmtools_rrwm | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| network_alignment | 2024_pygmtools_sm | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| node_classification_regression | 2016_pyg_gcn | runtime_checks_passed | pyg-gcn: 58 passed / 0 failed (Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim) |
| node_classification_regression | 2017_pyg_gat | runtime_checks_passed | pyg-gat: 58 passed / 0 failed (Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim) |
| node_classification_regression | 2017_pyg_graphsage | runtime_checks_passed | pyg-graphsage: 58 passed / 0 failed (Collected model layer: CUDA/CPU output parity and finite backward gradients; no trained predictive-quality claim) |
| node_embedding | 2014_graphvite_deepwalk | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| node_embedding | 2015_graphvite_line | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| node_embedding | 2016_graphvite_node2vec | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| persistent_homology | 2020_ripserplusplus | runtime_failures | ripserplusplus-finite-bars: 100 passed / 0 failed (Hybrid upstream implementation vs independent F2 boundary reduction, finite intervals H0 through H2); ripserplusplus-essential-h0: 0 passed / 100 failed (Full barcode contract: Python export must include essential H0 interval) |
| personalized_pagerank_rwr | 2017_gunrock_ppr | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| personalized_pagerank_rwr | 2019_graphblast_seeded_diffusion | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| personalized_pagerank_rwr | 2020_kpar | runtime_checks_passed | personalized-pagerank/kpar: 184 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| personalized_pagerank_rwr | 2026_cugraph_personalized_pagerank | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| quasi_clique_mining | 2025_cuqc | runtime_checks_passed | quasi-cliques/cuqc: 624 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| random_walk_generation | 2020_csaw_walks | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| random_walk_generation | 2020_nextdoor_walks | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| random_walk_generation | 2021_skywalker_walks | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| random_walk_generation | 2026_cugraph_random_walks | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| seeded_local_community_detection | 2017_gunrock_ppr | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| seeded_local_community_detection | 2017_gunrock_regularized_ppr | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| seeded_local_community_detection | 2019_graphblast_lgc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| signed_network_structural_balance | 2021_graphbplus | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| signed_network_structural_balance | 2026_ecl_sgb | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| simrank_vertex_similarity | 2023_clipsim | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| single_graph_frequent_subgraph_mining | 2022_graphminer_mni | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_graph_frequent_subgraph_mining | 2022_pangolin_mni | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_source_shortest_paths | 2017_gardenia_delta_stepping | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_source_shortest_paths | 2017_gunrock_sssp | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_source_shortest_paths | 2018_hornet_sssp | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_source_shortest_paths | 2019_graphblast_sssp | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| single_source_shortest_paths | 2026_cugraph_sssp | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| spanning_tree_forest | 2016_lonestargpu_mst | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| spanning_tree_forest | 2017_gardenia_mst | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| spanning_tree_forest | 2017_gunrock_boruvka | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| spectral_graph_sparsification | 2024_ingrass_candidate | not_runtime_validated | No public upstream GPU implementation was verified. |
| spectral_graph_sparsification | 2025_dygrass_decremental | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| spectral_graph_sparsification | 2025_dygrass_incremental | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| subgraph_isomorphism | 2026_gmatch | runtime_checks_passed | subgraph-isomorphism/gmatch: 624 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| temporal_fastest_paths | 2019_temporal_eat | not_runtime_validated | No public upstream GPU implementation was verified. |
| temporal_fastest_paths | 2024_temporal_fastest | not_runtime_validated | No public upstream GPU implementation was verified. |
| temporal_fastest_paths | 2025_tempgraph | not_runtime_validated | No public upstream GPU implementation was verified. |
| temporal_motif_mining | 2024_everest | runtime_checks_passed | temporal-motif-mining/everest: 160 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| temporal_motif_mining | 2025_mayura | runtime_checks_passed | temporal-motif-mining/mayura: 160 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| top_k_critical_paths_dag | 2021_gpba | not_runtime_validated | No public upstream GPU implementation was verified. |
| top_k_critical_paths_dag | 2021_heterocppr | not_runtime_validated | No public upstream GPU implementation was verified. |
| top_k_critical_paths_dag | 2026_gpathgen | not_runtime_validated | No public upstream GPU implementation was verified. |
| topological_sort | 2017_nvidia_parallel_dag_dfs | not_runtime_validated | No public upstream GPU implementation was verified. |
| topological_sort | 2026_cugraph_topological_levels | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| topological_sort | 2026_topogpu_morse_sort | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| transitive_closure_reachability | 2021_atc | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| transitive_closure_reachability | 2024_gdlog | runtime_checks_passed | transitive-closure/gdlog: 184 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| transitive_closure_reachability | 2026_curpq | not_runtime_validated | No local verified GPU source in this checkout. Public-source availability and license restrictions are recorded in the sweep coverage. |
| triangle_counting_listing | 2017_gunrock_tc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| triangle_counting_listing | 2018_hornet_triangles | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| triangle_counting_listing | 2019_graphblast_tc | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| triangle_counting_listing | 2025_tot_tensor_cores | runtime_checks_passed | triangle-counting/tot: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| triangle_counting_listing | 2025_wetric | runtime_checks_passed | triangle-counting/wetric: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| triangle_counting_listing | 2026_cugraph_triangle_count | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| triangle_counting_listing | 2026_edtc | runtime_checks_passed | dynamic-triangle-counting/edtc: 208 passed / 0 failed (public CLI validated profile, including local repairs; not a paper-version reproduction) |
| vertex_coloring | 2016_gardenia_coloring | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| vertex_coloring | 2017_gunrock_coloring | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| vertex_coloring | 2019_graphblast_coloring | not_runtime_validated | Collected research source has no executable adapter and independent problem-specific runtime test in this sweep. |
| vertex_coloring | 2026_cugraph_coloring | not_runtime_validated | Pinned cuGraph requires CMake >=4, installed CMake is 3.28.3; no compatible RAPIDS build/runtime was established. |
| widest_paths | 2026_nvgraph_widest_path | not_runtime_validated | Pinned legacy nvGraph configure fails at cpp/CMakeLists.txt:113 (empty include path); no runtime evidence. |
