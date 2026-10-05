#pragma once
#include "graphmine/problems/validated_expansion.hpp"

namespace graphmine {

struct EdgeTrussNumber { ExternalId edge; std::uint32_t truss_number; };
struct KTrussOptions : IsolatedBackendOptions {};
struct KTrussOutput {
  std::vector<EdgeTrussNumber> truss_number_by_edge;
  std::uint32_t maximum_truss_number = 0;
};
class KTruss {
 public:
  explicit KTruss(KTrussOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<KTrussOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: KTrussOptions options_;
};

// Exact unweighted edge density |E(S)|/|S|. No fixed-cardinality constraint.
struct DensestSubgraphOptions : IsolatedBackendOptions {};
struct DensestSubgraphOutput {
  std::vector<ExternalId> vertices;
  double density = 0;
  std::uint64_t induced_edge_value = 0;
  bool optimal = true;
};
class DensestSubgraph {
 public:
  explicit DensestSubgraph(DensestSubgraphOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<DensestSubgraphOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: DensestSubgraphOptions options_;
};

// Counts nonempty maximal bicliques; does not materialize their vertex sets.
// Every vertex declares attributes.side as left or right.
struct MaximalBicliqueCountingOptions : IsolatedBackendOptions {};
struct MaximalBicliqueCountingOutput { std::uint64_t total_count = 0; bool complete = true; };
class MaximalBicliqueCounting {
 public:
  explicit MaximalBicliqueCounting(MaximalBicliqueCountingOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<MaximalBicliqueCountingOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: MaximalBicliqueCountingOptions options_;
};

struct RankedVertex { ExternalId vertex; double score; std::uint32_t rank; };
struct PersonalizedPageRankOptions : IsolatedBackendOptions {
  ExternalId seed_vertex;
  std::uint32_t top_k = 10;
  double epsilon = 0.01;
  std::uint32_t random_seed = 20261004;
};
struct PersonalizedPageRankOutput {
  std::vector<RankedVertex> ranked_vertices;
  double restart_probability_used = 0.2;
  double epsilon_used = 0.01;
  bool complete = false;
  bool approximate = true;
  // A measured test tolerance is not a certified per-run error bound.
  bool error_bound_certified = false;
};
class PersonalizedPageRank {
 public:
  explicit PersonalizedPageRank(PersonalizedPageRankOptions options) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<PersonalizedPageRankOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: PersonalizedPageRankOptions options_;
};

struct GroupSteinerTreeOptions : IsolatedBackendOptions {
  std::vector<std::vector<ExternalId>> groups;
};
struct GroupSteinerTreeOutput {
  std::vector<ExternalId> tree_edges, selected_vertices;
  std::int64_t tree_weight = 0;
  bool feasible = false;
  bool optimal = true;
};
class GroupSteinerTree {
 public:
  explicit GroupSteinerTree(GroupSteinerTreeOptions options) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<GroupSteinerTreeOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: GroupSteinerTreeOptions options_;
};

struct InfluenceMaximizationOptions : IsolatedBackendOptions {
  std::uint32_t seed_set_size = 1;
  std::uint32_t sample_count = 256;
  std::uint64_t random_seed = 42;
};
struct InfluenceMaximizationOutput {
  std::vector<ExternalId> seed_set;
  double expected_spread = 0;
  std::vector<double> prefix_spread;
  std::uint32_t sample_count = 0;
  bool guarantee_met = false;
};
class InfluenceMaximization {
 public:
  explicit InfluenceMaximization(InfluenceMaximizationOptions options) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<InfluenceMaximizationOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: InfluenceMaximizationOptions options_;
};

// Alternative butterfly backend used by ButterflyCounting when selected.
class GammaButterflyCounting {
 public:
  explicit GammaButterflyCounting(IsolatedBackendOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<ButterflyOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private: IsolatedBackendOptions options_;
};
} // namespace graphmine
