# Catalog explorer

Browse from a family to a formal problem, then inspect the compiled operations, parameters, and outputs. Use the [family guides](taxonomy.md#browse-the-families) for definitions and examples, or the [code reference](../library/code-reference.md) for implementation details.

## Browse the catalog

<div id="operations" class="catalog-explorer">
  <div class="catalog-controls">
    <label for="operation-search">Search the catalog</label>
    <input id="operation-search" type="search" placeholder="Problem, operation, or implementation" autocomplete="off">
    <label for="family-select">Family</label>
    <select id="family-select"><option value="">All families</option></select>
    <div class="filter-group" role="group" aria-label="Compiled device filter">
      <button type="button" data-filter="all" aria-pressed="true">All devices</button>
      <button type="button" data-filter="cpu" aria-pressed="false">CPU</button>
      <button type="button" data-filter="gpu" aria-pressed="false">GPU</button>
    </div>
  </div>
  <nav id="catalog-breadcrumb" aria-label="Catalog path"></nav>
  <p id="catalog-summary" role="status" aria-live="polite">Loading catalog…</p>
  <p id="catalog-error" hidden>Unable to load the catalog. Reload this page or download the JSON below.</p>
  <div id="operation-grid"></div>
  <dialog id="operation-dialog"><button type="button" data-dialog-close class="dialog-close">Close details</button><div id="dialog-content"></div></dialog>
  <p id="copy-toast" role="status" aria-live="polite"></p>
</div>

[Download catalog JSON](../catalog.json){ download="catalog.json" }

A compiled backend still needs compatible inputs and hardware. The application also checks matching validation evidence. Research references are labelled separately and do not imply executable support.

<!-- Generated catalog anchors -->
<div hidden>
<span id="family/records"></span>
<span id="family/paths"></span>
<span id="family/connectivity"></span>
<span id="family/dense"></span>
<span id="family/communities"></span>
<span id="family/importance"></span>
<span id="family/similarity"></span>
<span id="family/motifs"></span>
<span id="family/patterns"></span>
<span id="family/selection"></span>
<span id="family/preparation"></span>
<span id="family/spectral"></span>
<span id="family/statistics"></span>
<span id="family/learning"></span>
<span id="problem/graph_record_queries"></span>
<span id="problem/breadth_first_search"></span>
<span id="problem/single_source_shortest_paths"></span>
<span id="problem/many_source_shortest_paths"></span>
<span id="problem/widest_paths"></span>
<span id="problem/temporal_fastest_paths"></span>
<span id="problem/top_k_critical_paths_dag"></span>
<span id="problem/hop_constrained_cycle_path_enumeration"></span>
<span id="problem/transitive_closure_reachability"></span>
<span id="problem/topological_sort"></span>
<span id="problem/connected_components"></span>
<span id="problem/biconnected_components"></span>
<span id="problem/max_flow_min_cut"></span>
<span id="problem/spanning_tree_forest"></span>
<span id="problem/group_steiner_tree"></span>
<span id="problem/maximal_clique_enumeration"></span>
<span id="problem/maximum_clique"></span>
<span id="problem/k_clique_counting_enumeration"></span>
<span id="problem/maximal_biclique_enumeration"></span>
<span id="problem/quasi_clique_mining"></span>
<span id="problem/densest_subgraph"></span>
<span id="problem/densest_k_subgraph"></span>
<span id="problem/k_core_decomposition"></span>
<span id="problem/k_truss_decomposition"></span>
<span id="problem/community_detection"></span>
<span id="problem/seeded_local_community_detection"></span>
<span id="problem/overlapping_community_detection"></span>
<span id="problem/balanced_graph_partitioning"></span>
<span id="problem/hypergraph_partitioning"></span>
<span id="problem/signed_network_structural_balance"></span>
<span id="problem/centrality_influential_node_mining"></span>
<span id="problem/personalized_pagerank_rwr"></span>
<span id="problem/influence_maximization"></span>
<span id="problem/simrank_vertex_similarity"></span>
<span id="problem/link_prediction"></span>
<span id="problem/graph_edit_distance_mcs"></span>
<span id="problem/network_alignment"></span>
<span id="problem/triangle_counting_listing"></span>
<span id="problem/butterfly_counting_bipartite"></span>
<span id="problem/graphlet_counting"></span>
<span id="problem/graph_motif_counting"></span>
<span id="problem/temporal_motif_mining"></span>
<span id="problem/subgraph_isomorphism"></span>
<span id="problem/frequent_subgraph_mining"></span>
<span id="problem/single_graph_frequent_subgraph_mining"></span>
<span id="problem/bipartite_matching_assignment"></span>
<span id="problem/general_graph_weighted_matching"></span>
<span id="problem/maximal_independent_set"></span>
<span id="problem/maximum_independent_set"></span>
<span id="problem/minimum_vertex_cover"></span>
<span id="problem/vertex_coloring"></span>
<span id="problem/entity_resolution_blocking"></span>
<span id="problem/graph_coarsening"></span>
<span id="problem/induced_subgraph_ego_extraction"></span>
<span id="problem/knn_graph_construction"></span>
<span id="problem/spectral_graph_sparsification"></span>
<span id="problem/neighborhood_sampling"></span>
<span id="problem/random_walk_generation"></span>
<span id="problem/graph_layout_force_directed"></span>
<span id="problem/graph_laplacian_eigenpairs"></span>
<span id="problem/graph_signal_denoising"></span>
<span id="problem/persistent_homology"></span>
<span id="problem/graph_anomaly_detection"></span>
<span id="problem/null_model_significance_testing"></span>
<span id="problem/node_classification_regression"></span>
<span id="problem/graph_classification_regression"></span>
<span id="problem/hypergraph_node_learning"></span>
<span id="problem/graph_condensation"></span>
<span id="problem/graph_based_geolocation"></span>
<span id="problem/node_embedding"></span>
<span id="problem/knowledge_graph_embedding"></span>
</div>
