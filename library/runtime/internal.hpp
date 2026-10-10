#pragma once

#include <boost/json.hpp>
#include <chrono>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "graphmine/graph.hpp"

namespace graphmine::runtime {
namespace json = boost::json;

struct Failure : std::runtime_error {
  std::string code;
  Failure(std::string category, std::string message)
      : std::runtime_error(std::move(message)), code(std::move(category)) {}
};
inline void require(bool condition, const std::string& message) {
  if (!condition) throw Failure("invalid_input", message);
}

struct Work {
  std::uint64_t max_candidates = 2000000;
  std::uint64_t max_output_items = 100000;
  double timeout_seconds = 60;
  std::uint64_t candidates = 0;
  std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
  void tick(std::uint64_t amount = 1);
  void output(std::uint64_t count);
};

struct Search {
  std::vector<std::int64_t> distances;
  std::vector<std::int64_t> predecessors;
};

struct Arc { VertexIndex target; double weight; };
struct WeightedGraph {
  std::vector<std::vector<Arc>> rows;
  bool directed = false;
};
struct WeightedSearch {
  std::vector<double> distances;
  std::vector<std::int64_t> predecessors;
};
WeightedGraph weighted_graph(const Graph& graph, bool weighted, bool nonnegative,
                             const std::string& aggregation, const std::string& direction,
                             Work& work);
double number(const json::value& value, const std::string& context);
bool boolean(const json::object& values, const char* key, bool initial);
json::object result_port(const char* type, json::value value, bool complete = true);

json::object object(const json::value& value, const std::string& context);
json::value strict_json(std::string_view raw);
void fields(const json::object& value, std::initializer_list<std::string_view> allowed,
            std::initializer_list<std::string_view> required = {});
std::string string(const json::value& value, const std::string& context);
std::uint64_t uint(const json::value& value, const std::string& context);
ExternalId external_id(const json::value& value);
json::value id_json(const ExternalId& value);
Graph parse_graph(const json::value& value);
std::vector<std::vector<VertexIndex>> adjacency(const Graph& graph, Work& work);
Search cpu_bfs(const std::vector<std::vector<VertexIndex>>& adjacency,
               VertexIndex source, std::optional<std::uint64_t> depth, Work& work);

bool cugraph_compiled() noexcept;
bool gpu_available(int device) noexcept;
std::string cugraph_version();
json::object gpu_description(int device);
struct DeviceScope {
  int previous = 0;
  explicit DeviceScope(int device);
  ~DeviceScope();
  DeviceScope(const DeviceScope&) = delete;
  DeviceScope& operator=(const DeviceScope&) = delete;
};
std::vector<Search> cugraph_bfs(const Graph& graph,
                              const std::vector<VertexIndex>& sources,
                              std::optional<std::uint64_t> depth, int device, Work& work);
std::vector<WeightedSearch> cugraph_shortest_paths(const WeightedGraph& graph,
    const std::vector<VertexIndex>& sources, int device, Work& work);
std::vector<std::pair<VertexIndex, VertexIndex>> cugraph_spanning_forest(
    const WeightedGraph& graph, bool maximum, int device, Work& work);
std::vector<std::vector<VertexIndex>> cugraph_components(
    const WeightedGraph& graph, bool strong, int device, Work& work);
std::vector<double> cugraph_pagerank(const WeightedGraph& graph,
    const std::vector<double>& personalization, double alpha, double tolerance,
    std::uint64_t iterations, int device, Work& work);
std::vector<double> cugraph_jaccard(const WeightedGraph& graph,
    const std::vector<std::pair<VertexIndex, VertexIndex>>& pairs, int device, Work& work);
std::vector<std::uint32_t> cugraph_core_numbers(const WeightedGraph&, int, Work&);
using MiningGraph = std::vector<std::vector<VertexIndex>>;
json::array original_mining_backends(const std::string& operation);
std::uint64_t original_maximal_count(const MiningGraph&, const std::string&, int, Work&);
std::vector<VertexIndex> original_maximum_clique(const MiningGraph&, const std::string&, int, Work&);
std::uint64_t original_k_clique_count(const MiningGraph&, std::uint32_t, const std::string&, int, Work&);
std::vector<std::uint32_t> original_core_numbers(const MiningGraph&, int, Work&);

json::object bfs(const Graph& graph, const json::object& args,
                 const std::string& backend, int device, Work& work);
json::object triangles(const Graph& graph, const json::object& args,
                       const std::string& backend, int device, Work& work);
bool original_triangles_compiled(const std::string& backend);
using NativeAlgorithm = json::object (*)(const Graph&, const json::object&, const std::string&, int, Work&);
NativeAlgorithm operation_handler(const std::string& operation);
std::string gpu_support_reason(const std::string& operation, const Graph& graph, const json::object& args);
std::string backend_support_reason(const std::string& operation, const std::string& backend, const Graph&, const json::object&, Work&);
json::object shortest_paths(const Graph&, const json::object&, const std::string&, int, Work&);
json::object many_shortest_paths(const Graph&, const json::object&, const std::string&, int, Work&);
json::object spanning_forest(const Graph&, const json::object&, const std::string&, int, Work&);
json::object components(const Graph&, const json::object&, const std::string&, int, Work&);
json::object topological(const Graph&, const json::object&, const std::string&, int, Work&);
json::object pagerank(const Graph&, const json::object&, const std::string&, int, Work&);
json::object personalized_pagerank(const Graph&, const json::object&, const std::string&, int, Work&);
json::object link_prediction(const Graph&, const json::object&, const std::string&, int, Work&);
json::object maximal_cliques(const Graph&, const json::object&, const std::string&, int, Work&);
json::object maximum_clique(const Graph&, const json::object&, const std::string&, int, Work&);
json::object k_cliques(const Graph&, const json::object&, const std::string&, int, Work&);
json::object core_numbers(const Graph&, const json::object&, const std::string&, int, Work&);
json::object maximum_independent_set(const Graph&, const json::object&, const std::string&, int, Work&);
json::object minimum_vertex_cover(const Graph&, const json::object&, const std::string&, int, Work&);
json::array operation_cards();
json::object catalog();
json::object execute(const json::object& request);
bool cudf_compiled() noexcept;
json::object read_csv(const json::object& request);
json::object read_graph_file(const json::object& request);
}  // namespace graphmine::runtime
