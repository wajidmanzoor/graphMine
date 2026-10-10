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

json::object object(const json::value& value, const std::string& context);
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

json::object bfs(const Graph& graph, const json::object& args,
                 const std::string& backend, int device, Work& work);
json::object triangles(const Graph& graph, const json::object& args,
                       const std::string& backend, int device, Work& work);
bool original_triangles_compiled(const std::string& backend);
json::array operation_cards();
json::object catalog();
json::object execute(const json::object& request);
bool cudf_compiled() noexcept;
json::object read_csv(const json::object& request);
}  // namespace graphmine::runtime
