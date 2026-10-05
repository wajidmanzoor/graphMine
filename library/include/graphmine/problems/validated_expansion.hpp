#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

// Research executables are isolated: a CUDA error, exit(), or timeout becomes
// an ExecutionResult failure instead of terminating the calling application.
struct IsolatedBackendOptions {
  ExecutionOptions execution;
  std::uint32_t timeout_seconds = 60;
  // Empty selects GRAPHMINE_WORKER_DIR, the build tree, or installed workers.
  std::string worker_directory;
};

enum class ConnectivityMode { weakly_connected, strongly_connected };
struct ConnectedComponentsOptions : IsolatedBackendOptions {
  ConnectivityMode connectivity_mode = ConnectivityMode::strongly_connected;
};
struct VertexComponent { ExternalId vertex; std::uint32_t component; };
struct ConnectedComponentsOutput {
  std::vector<VertexComponent> component_assignment;
  std::uint32_t component_count = 0;
  std::vector<std::uint64_t> component_sizes;
};
class ConnectedComponents {
 public:
  explicit ConnectedComponents(ConnectedComponentsOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<ConnectedComponentsOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private:
  ConnectedComponentsOptions options_;
};

struct MaxFlowOptions : IsolatedBackendOptions {
  ExternalId source;
  ExternalId sink;
  bool unit_capacity = false;
};
struct EdgeFlow { ExternalId edge; std::int64_t flow; };
struct MaxFlowOutput {
  std::int64_t max_flow_value = 0;
  std::int64_t min_cut_value = 0;
  std::vector<ExternalId> min_cut_edges;
  std::vector<ExternalId> source_side_vertices;
  std::vector<EdgeFlow> flow_assignment;
  bool optimal = false;
};
class MaxFlowMinCut {
 public:
  explicit MaxFlowMinCut(MaxFlowOptions options) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<MaxFlowOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private:
  MaxFlowOptions options_;
};

// This API deliberately requires a complete square assignment. Each vertex
// declares attributes.side = "left" or "right"; each cost is an integer [0,999].
struct LinearAssignmentOptions : IsolatedBackendOptions {};
struct LinearAssignmentOutput {
  std::vector<ExternalId> matching_edges;
  std::uint32_t matching_size = 0;
  std::int64_t objective_value = 0;
  bool feasible = true;
  bool optimal = true;
};
class LinearAssignment {
 public:
  explicit LinearAssignment(LinearAssignmentOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<LinearAssignmentOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private:
  LinearAssignmentOptions options_;
};

struct ReachabilityOptions : IsolatedBackendOptions {};
struct ReachablePair { ExternalId source; ExternalId target; };
struct ReachabilityOutput {
  std::vector<ReachablePair> reachable_pairs;
  std::uint64_t reachable_pair_count = 0;
  bool complete = true;
};
class TransitiveClosure {
 public:
  explicit TransitiveClosure(ReachabilityOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<ReachabilityOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private:
  ReachabilityOptions options_;
};

struct ButterflyOptions : IsolatedBackendOptions { std::string backend = "graphminer"; };
struct ButterflyOutput { std::uint64_t butterfly_count = 0; bool complete = true; };
class ButterflyCounting {
 public:
  explicit ButterflyCounting(ButterflyOptions options = {}) : options_(std::move(options)) {}
  SupportReport supports(const Graph&) const;
  ExecutionResult<ButterflyOutput> run(const Graph&) const;
  static std::vector<BackendInfo> backends();
 private:
  ButterflyOptions options_;
};

}  // namespace graphmine
