#include <graphmine/graph.hpp>
#include <graphmine/problems/k_core.hpp>
#include <graphmine/problems/k_cliques.hpp>
#include <graphmine/problems/maximal_cliques.hpp>
#include <graphmine/problems/maximum_clique.hpp>
#include <graphmine/problems/triangle_counting.hpp>
#include <graphmine/problems/dynamic_triangle_counting.hpp>
#include <graphmine/problems/betweenness_centrality.hpp>
#include <graphmine/problems/maximal_bicliques.hpp>
#include <graphmine/problems/quasi_cliques.hpp>
#include <graphmine/problems/subgraph_isomorphism.hpp>
#include <graphmine/problems/graph_motifs.hpp>
#include <graphmine/problems/temporal_motif_mining.hpp>
#include <graphmine/problems/community_detection.hpp>

int main() {
  auto graph = graphmine::Graph::from_edges(
      "consumer", {0, 1, 2}, {{0, 1}, {1, 2}, {0, 2}});
  auto bipartite_graph = graphmine::Graph::from_edges(
      "bipartite-consumer", {0, 1, 2}, {{0, 1}, {0, 2}});
  graphmine::MaximalCliques algorithm;
  graphmine::MaximumClique maximum_clique;
  graphmine::KCore k_core;
  graphmine::KCliques k_cliques;
  graphmine::TriangleCounting triangle_counting;
  graphmine::DynamicTriangleCounting dynamic_triangle_counting;
  graphmine::BetweennessCentrality centrality;
  graphmine::MaximalBicliqueOptions biclique_options;
  biclique_options.left_partition = {0};
  graphmine::MaximalBicliques maximal_bicliques(biclique_options);
  graphmine::QuasiCliques quasi_cliques;
  graphmine::SubgraphIsomorphism subgraph_isomorphism;
  graphmine::GraphMotifOptions motif_options;
  motif_options.backend = graphmine::GraphMotifBackend::graphminer;
  motif_options.induced = true;
  graphmine::GraphMotifs graph_motifs(motif_options);
  graphmine::TemporalMotifMining temporal_motifs;
  graphmine::CommunityDetection communities;
  return algorithm.supports(graph).supported &&
                 maximum_clique.supports(graph).supported &&
                 k_core.supports(graph).supported &&
                 k_cliques.supports(graph).supported &&
                 triangle_counting.supports(graph).supported &&
                 dynamic_triangle_counting.supports(graph, {}).supported &&
                 centrality.supports(graph).supported &&
                 maximal_bicliques.supports(bipartite_graph).supported &&
                 quasi_cliques.supports(graph).supported &&
                 subgraph_isomorphism.supports(graph, graph).supported &&
                 graph_motifs.supports(graph, {graph}).supported &&
                 !graphmine::TemporalMotifMining::backends().empty() &&
                 communities.supports(graph).supported
             ? 0
             : 1;
}
