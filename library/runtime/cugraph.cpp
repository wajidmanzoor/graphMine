#include <cuda_runtime_api.h>
#include <cugraph_c/array.h>
#include <cugraph_c/graph.h>
#include <cugraph_c/resource_handle.h>
#include <cugraph_c/traversal_algorithms.h>

#include <cugraph_c/version_config.hpp>
#include <iomanip>
#include <limits>
#include <memory>
#include <numeric>
#include <sstream>

#include "internal.hpp"

namespace graphmine::runtime {
namespace {
template <class T, void (*Free)(T*)>
using Owned = std::unique_ptr<T, decltype(Free)>;
struct Error {
  cugraph_error_t* value = nullptr;
  ~Error() {
    if (value) cugraph_error_free(value);
  }
  void check(cugraph_error_code_t status) {
    if (status != CUGRAPH_SUCCESS)
      throw Failure(
          status == CUGRAPH_ALLOC_ERROR ? "resource_limit" : "backend_failure",
          value ? cugraph_error_message(value) : "libcugraph failed without an error message");
  }
};
struct Device {
  int previous = 0;
  explicit Device(int selected) {
    if (cudaGetDevice(&previous) != cudaSuccess || cudaSetDevice(selected) != cudaSuccess)
      throw Failure("backend_unavailable", "Cannot select requested CUDA device");
  }
  ~Device() { cudaSetDevice(previous); }
};
struct Array {
  Owned<cugraph_type_erased_device_array_t, cugraph_type_erased_device_array_free> value{
      nullptr, cugraph_type_erased_device_array_free};
  Owned<cugraph_type_erased_device_array_view_t, cugraph_type_erased_device_array_view_free> view{
      nullptr, cugraph_type_erased_device_array_view_free};
  Array(const cugraph_resource_handle_t* handle, const std::vector<std::int32_t>& data) {
    Error error;
    cugraph_type_erased_device_array_t* output = nullptr;
    const auto status =
        cugraph_type_erased_device_array_create(handle, data.size(), INT32, &output, &error.value);
    value.reset(output);
    error.check(status);
    view.reset(cugraph_type_erased_device_array_view(value.get()));
    if (!view) throw Failure("resource_limit", "libcugraph array view allocation failed");
    if (!data.empty())
      error.check(cugraph_type_erased_device_array_view_copy_from_host(
          handle, view.get(), reinterpret_cast<const byte_t*>(data.data()), &error.value));
  }
};
std::vector<std::int32_t> copy(const cugraph_resource_handle_t* handle,
                               cugraph_type_erased_device_array_view_t* view) {
  Owned<cugraph_type_erased_device_array_view_t, cugraph_type_erased_device_array_view_free> owned(
      view, cugraph_type_erased_device_array_view_free);
  require(view != nullptr && cugraph_type_erased_device_array_view_type(view) == INT32,
          "Unexpected libcugraph result array type");
  std::vector<std::int32_t> result(cugraph_type_erased_device_array_view_size(view));
  Error error;
  if (!result.empty())
    error.check(cugraph_type_erased_device_array_view_copy_to_host(
        handle, reinterpret_cast<byte_t*>(result.data()), view, &error.value));
  return result;
}
}  // namespace

bool cugraph_compiled() noexcept { return true; }
std::string cugraph_version() { return CUGRAPH_VERSION; }

std::vector<Search> cugraph_bfs(const Graph& graph, const std::vector<VertexIndex>& sources,
                                std::optional<std::uint64_t> depth, int device, Work& work) {
  if (graph.vertex_count() >= INT32_MAX)
    throw Failure("unsupported_input",
                  "This libcugraph BFS profile requires fewer than INT32_MAX vertices");
  Device selected(device);
  const auto adj = adjacency(graph, work);
  std::vector<std::int32_t> src, dst, ids(graph.vertex_count());
  std::iota(ids.begin(), ids.end(), 0);
  for (VertexIndex u = 0; u < adj.size(); ++u)
    for (const auto v : adj[u]) {
      work.tick();
      src.push_back(static_cast<std::int32_t>(u));
      dst.push_back(static_cast<std::int32_t>(v));
    }
  if (src.size() >= INT32_MAX)
    throw Failure("unsupported_input",
                  "This libcugraph BFS profile requires fewer than INT32_MAX arcs");
  Owned<cugraph_resource_handle_t, cugraph_free_resource_handle> handle(
      cugraph_create_resource_handle(nullptr), cugraph_free_resource_handle);
  if (!handle) throw Failure("resource_limit", "libcugraph resource allocation failed");
  Array vertices(handle.get(), ids), starts(handle.get(), src), ends(handle.get(), dst);
  cugraph_graph_properties_t properties{graph.directed() ? FALSE : TRUE, FALSE};
  cugraph_graph_t* raw_graph = nullptr;
  Error error;
  const auto status = cugraph_graph_create_with_times_sg(
      handle.get(), &properties, vertices.view.get(), starts.view.get(), ends.view.get(), nullptr,
      nullptr, nullptr, nullptr, nullptr, FALSE, TRUE, FALSE, FALSE, FALSE, TRUE, &raw_graph,
      &error.value);
  Owned<cugraph_graph_t, cugraph_graph_free> gpu_graph(raw_graph, cugraph_graph_free);
  error.check(status);
  std::vector<Search> results;
  for (const auto source : sources) {
    work.tick();
    Array seeds(handle.get(), {static_cast<std::int32_t>(source)});
    cugraph_paths_result_t* raw_result = nullptr;
    // libcugraph narrows the iteration bound internally. SIZE_MAX wraps and
    // prematurely stops a search; no shortest simple path needs n hops.
    const auto effective_depth =
        std::min<std::uint64_t>(depth.value_or(graph.vertex_count()), graph.vertex_count());
    const auto state = cugraph_bfs(handle.get(), gpu_graph.get(), seeds.view.get(), FALSE,
                                   static_cast<std::size_t>(effective_depth), TRUE, TRUE,
                                   &raw_result, &error.value);
    Owned<cugraph_paths_result_t, cugraph_paths_result_free> paths(raw_result,
                                                                   cugraph_paths_result_free);
    error.check(state);
    // Result accessors allocate views; copy releases each view before the result.
    auto vertices_out = copy(handle.get(), cugraph_paths_result_get_vertices(paths.get()));
    auto distances = copy(handle.get(), cugraph_paths_result_get_distances(paths.get()));
    auto predecessors = copy(handle.get(), cugraph_paths_result_get_predecessors(paths.get()));
    require(vertices_out.size() == graph.vertex_count() &&
                distances.size() == vertices_out.size() &&
                predecessors.size() == vertices_out.size(),
            "libcugraph returned an incomplete vertex mapping");
    Search result{std::vector<std::int64_t>(graph.vertex_count(), -1),
                  std::vector<std::int64_t>(graph.vertex_count(), -1)};
    std::vector<bool> seen(graph.vertex_count(), false);
    for (std::size_t i = 0; i < vertices_out.size(); ++i) {
      work.tick();
      const auto v = vertices_out[i];
      require(v >= 0 && static_cast<std::size_t>(v) < graph.vertex_count() && !seen[v],
              "libcugraph returned an invalid vertex mapping");
      seen[v] = true;
      if (distances[i] >= 0 && distances[i] < INT32_MAX &&
          (!depth || static_cast<std::uint64_t>(distances[i]) <= *depth)) {
        result.distances[v] = distances[i];
        if (distances[i] > 0) {
          require(predecessors[i] >= 0 &&
                      static_cast<std::size_t>(predecessors[i]) < graph.vertex_count(),
                  "libcugraph returned an invalid predecessor");
          result.predecessors[v] = predecessors[i];
        }
      }
    }
    results.push_back(std::move(result));
  }
  return results;
}
}  // namespace graphmine::runtime
