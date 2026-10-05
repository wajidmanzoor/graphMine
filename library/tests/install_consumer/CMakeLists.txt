cmake_minimum_required(VERSION 3.24)
project(GraphMineInstallConsumer LANGUAGES CXX)

find_package(GraphMine 1.0 REQUIRED COMPONENTS
  maximal_cliques
  maximum_clique
  k_core
  triangle_counting
  dynamic_triangle_counting
  k_cliques
  betweenness_centrality
  maximal_bicliques
  quasi_cliques
  subgraph_isomorphism
  graph_motifs
  temporal_motif_mining
  community_detection
  validated_expansion
  repaired_algorithms
)

add_executable(graphmine_install_consumer main.cpp)
target_link_libraries(graphmine_install_consumer
  PRIVATE
    GraphMine::maximal_cliques
    GraphMine::maximum_clique
    GraphMine::k_core
    GraphMine::triangle_counting
    GraphMine::dynamic_triangle_counting
    GraphMine::k_cliques
    GraphMine::betweenness_centrality
    GraphMine::maximal_bicliques
    GraphMine::quasi_cliques
    GraphMine::subgraph_isomorphism
    GraphMine::graph_motifs
    GraphMine::temporal_motif_mining
    GraphMine::community_detection
    GraphMine::validated_expansion
    GraphMine::repaired_algorithms
)

add_executable(graphmine_repaired_install_consumer ../repaired_algorithms_test.cpp)
target_link_libraries(graphmine_repaired_install_consumer PRIVATE
  GraphMine::repaired_algorithms GraphMine::validated_expansion)
