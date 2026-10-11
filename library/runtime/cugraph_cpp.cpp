#include <cuda_runtime_api.h>

#include <algorithm>
#include <cugraph/algorithms.hpp>
#include <cugraph/graph_functions.hpp>
#include <numeric>
#include <raft/core/handle.hpp>
#include <raft/random/rng_state.hpp>
#include <rmm/device_uvector.hpp>

#include "internal.hpp"

namespace graphmine::runtime {
namespace {
void cuda_check(cudaError_t code) {
  if (code != cudaSuccess)
    throw Failure(code == cudaErrorMemoryAllocation ? "resource_limit" : "backend_failure",
                  cudaGetErrorString(code));
}
rmm::device_uvector<std::int32_t> device_copy(const std::vector<std::int32_t>& values,
                                              rmm::cuda_stream_view stream) {
  rmm::device_uvector<std::int32_t> output(values.size(), stream);
  if (!values.empty())
    cuda_check(cudaMemcpyAsync(output.data(), values.data(), values.size() * sizeof(std::int32_t),
                               cudaMemcpyHostToDevice, stream.value()));
  return output;
}
std::vector<std::int32_t> host_copy(const rmm::device_uvector<std::int32_t>& values,
                                    rmm::cuda_stream_view stream) {
  std::vector<std::int32_t> output(values.size());
  if (!values.is_empty())
    cuda_check(cudaMemcpyAsync(output.data(), values.data(), values.size() * sizeof(std::int32_t),
                               cudaMemcpyDeviceToHost, stream.value()));
  stream.synchronize();
  return output;
}
std::vector<VertexIndex> solve(const MiningGraph& input, std::uint64_t seed, int ordinal,
                               Work& work, bool coloring) {
  if (input.empty()) return {};
  if (input.size() >= INT32_MAX)
    throw Failure("unsupported_input",
                  "This cuGraph profile requires fewer than INT32_MAX vertices");
  std::vector<std::int32_t> ids(input.size()), src, dst;
  std::iota(ids.begin(), ids.end(), 0);
  for (VertexIndex u = 0; u < input.size(); ++u)
    for (const auto v : input[u]) {
      work.tick();
      src.push_back(u);
      dst.push_back(v);
    }
  if (src.empty()) {
    if (coloring) return std::vector<VertexIndex>(input.size(), 0);
    return std::vector<VertexIndex>(ids.begin(), ids.end());
  }
  if (src.size() >= INT32_MAX)
    throw Failure("unsupported_input", "This cuGraph profile requires fewer than INT32_MAX arcs");
  // Iterative calls cannot consult Work while executing. Charge a conservative
  // n*(n+m) scan bound before entering CUDA, then validate every returned value.
  const auto cost = input.size() + src.size();
  const auto remaining = work.max_candidates - std::min(work.candidates, work.max_candidates);
  if (input.size() > remaining / cost)
    throw Failure("resource_limit",
                  "cuGraph coloring/independent-set scan bound exceeds the work budget");
  work.tick(cost * input.size());
  DeviceScope device(ordinal);
  raft::handle_t handle;
  const auto stream = handle.get_stream();
  auto vertices = std::make_optional(device_copy(ids, stream));
  auto sources = device_copy(src, stream), targets = device_copy(dst, stream);
  auto [graph, properties, mapping] =
      cugraph::create_graph_from_edgelist<std::int32_t, std::int32_t, false, false>(
          handle, std::move(vertices), std::move(sources), std::move(targets), {},
          cugraph::graph_properties_t{true, false}, true, std::nullopt, std::nullopt, true);
  raft::random::RngState rng(seed);
  auto values = coloring ? cugraph::vertex_coloring(handle, graph.view(), rng)
                         : cugraph::maximal_independent_set(handle, graph.view(), rng);
  const auto raw = host_copy(values, stream);
  const auto map = host_copy(*mapping, stream);
  work.tick(0);
  if (map.size() != input.size())
    throw Failure("correctness_mismatch", "cuGraph renumbering omits vertices");
  std::vector<bool> seen(input.size(), false);
  for (const auto v : map) {
    if (v < 0 || static_cast<std::size_t>(v) >= input.size() || seen[v])
      throw Failure("correctness_mismatch", "Invalid cuGraph renumbering");
    seen[v] = true;
  }
  std::vector<VertexIndex> output;
  if (coloring) {
    if (raw.size() != input.size())
      throw Failure("correctness_mismatch", "cuGraph coloring omits vertices");
    output.resize(input.size());
    for (std::size_t i = 0; i < raw.size(); ++i) {
      if (raw[i] < 0 || static_cast<std::size_t>(raw[i]) >= input.size())
        throw Failure("correctness_mismatch", "Invalid cuGraph color");
      output[map[i]] = raw[i];
    }
  } else
    for (const auto v : raw) {
      if (v < 0 || static_cast<std::size_t>(v) >= map.size())
        throw Failure("correctness_mismatch", "Invalid cuGraph independent vertex");
      output.push_back(map[v]);
    }
  return output;
}
}  // namespace
bool cugraph_cpp_compiled() noexcept { return true; }
std::vector<VertexIndex> cugraph_maximal_independent(const MiningGraph& input, std::uint64_t seed,
                                                     int device, Work& work) {
  return solve(input, seed, device, work, false);
}
std::vector<std::uint32_t> cugraph_vertex_coloring(const MiningGraph& input, std::uint64_t seed,
                                                   int device, Work& work) {
  auto values = solve(input, seed, device, work, true);
  return {values.begin(), values.end()};
}
}  // namespace graphmine::runtime
