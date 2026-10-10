#include "internal.hpp"

#include <algorithm>
#include <limits>
#ifdef GRAPHMINE_NATIVE_OPTIMIZATION
#include "worker_process.hpp"
#include <dlfcn.h>
#endif

namespace graphmine::runtime {
namespace {
#ifdef GRAPHMINE_NATIVE_OPTIMIZATION
using namespace detail::isolated;
std::vector<std::int64_t> run_worker(const char* name, const char* marker, int device, Work& work,
    const TempDirectory& temp, std::vector<std::string> arguments) {
  work.tick(0); IsolatedBackendOptions options; options.execution.device_ids = {device};
  // Resolve relocatable installations from the shared library as well as the
  // executable. This also works when the caller is a Python ctypes wrapper.
  if (!std::getenv("GRAPHMINE_WORKER_DIR")) {
    Dl_info location{};
    if (dladdr(reinterpret_cast<const void*>(&original_optimization_backends), &location) && location.dli_fname) {
      auto candidate = fs::path(location.dli_fname).parent_path() / "../libexec/graphmine";
      if (fs::is_regular_file(candidate / (std::string("graphmine-worker-") + name))) options.worker_directory = candidate.string();
    }
  }
  const auto maximum = std::chrono::steady_clock::time_point::max();
  const auto available = std::chrono::duration<double>(maximum - work.started).count();
  const auto deadline = work.timeout_seconds >= available ? maximum : work.started +
      std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(work.timeout_seconds));
  try {
    const auto output = invoke_worker(name, std::move(arguments), options, temp, {}, deadline);
    work.tick(0); std::istringstream stream(output); std::string line;
    while (std::getline(stream, line)) if (line == marker || line.rfind(std::string(marker) + " ", 0) == 0) {
      std::istringstream row(line.substr(std::strlen(marker))); std::int64_t value; std::vector<std::int64_t> values;
      while (row >> value) { work.tick(); values.push_back(value); }
      if (!row.eof()) throw Failure("correctness_mismatch", "Invalid integer in CUDA worker result");
      return values;
    }
    throw Failure("correctness_mismatch", "CUDA worker returned no result marker");
  } catch (const BackendError& error) {
    throw Failure(error.code == StatusCode::resource_exhausted ? "resource_limit" :
                  error.code == StatusCode::backend_unavailable ? "backend_unavailable" : "backend_failure", error.what());
  }
}
#endif
}
json::array original_optimization_backends(const std::string& operation) {
#ifdef GRAPHMINE_NATIVE_OPTIMIZATION
  constexpr bool compiled = true;
#else
  constexpr bool compiled = false;
#endif
  if (operation == "max-flow-min-cut") return {json::object{{"id","ecl-maxflow"},{"device","gpu"},{"compiled",compiled},
      {"execution","isolated original CUDA flow worker with native exact flow and cut certification"}}};
  return {json::object{{"id","hungarian-cuda"},{"device","gpu"},{"compiled",compiled},
      {"execution","isolated original CUDA assignment worker with native exact optimality verification"}}};
}
std::vector<std::int64_t> original_flow(std::size_t n, const std::vector<IntegerFlowArc>& arcs,
    VertexIndex source, VertexIndex sink, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_OPTIMIZATION
  work.tick(n + arcs.size());
  if (arcs.empty() || std::none_of(arcs.begin(), arcs.end(), [](const auto& arc) { return arc.capacity > 0; })) return std::vector<std::int64_t>(arcs.size(), 0);
  if (n > 1000000 || arcs.size() > 10000000) throw Failure("unsupported_input", "ECL flow graph exceeds its admitted size");
  TempDirectory temp; const auto path = temp.path / "network.egr";
  std::vector<std::int32_t> data{static_cast<std::int32_t>(n), static_cast<std::int32_t>(arcs.size())};
  std::size_t index = 0;
  for (std::size_t v = 0; v <= n; ++v) { work.tick(); while (index < arcs.size() && arcs[index].source < v) ++index; data.push_back(index); }
  for (const auto& arc : arcs) { work.tick(); data.push_back(arc.target); }
  std::int64_t total = 0;
  for (const auto& arc : arcs) {
    work.tick(); if (arc.capacity < 0 || arc.capacity > 1000000000 - total) throw Failure("unsupported_input", "ECL flow total capacity exceeds 1e9");
    total += arc.capacity; data.push_back(arc.capacity);
  }
  { std::ofstream file(path, std::ios::binary); file.write(reinterpret_cast<const char*>(data.data()), data.size() * sizeof(std::int32_t));
    if (!file) throw Failure("backend_failure", "Cannot write native ECL flow input"); }
  auto values = run_worker("ecl-maxflow", "GRAPHMINE_FLOW", device, work, temp,
      {path.string(), std::to_string(source), std::to_string(sink), "1"});
  if (values.size() != arcs.size()) throw Failure("correctness_mismatch", "ECL flow vector has the wrong length");
  return values;
#else
  throw Failure("backend_unavailable", "Native CUDA flow worker was not compiled");
#endif
}
std::vector<std::size_t> original_assignment(const std::vector<std::vector<int>>& costs, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_OPTIMIZATION
  work.tick(costs.size() * costs.size()); if (costs.empty()) return {};
  if (costs.size() > 64) throw Failure("unsupported_input", "Hungarian CUDA supports at most 64 vertices per side");
  TempDirectory temp; const auto path = temp.path / "assignment.txt";
  { std::ofstream file(path); file << costs.size() << '\n';
    for (const auto& row : costs) {
      graphmine::runtime::require(row.size() == costs.size(), "Assignment matrix must be square");
      for (const auto cost : row) { graphmine::runtime::require(cost >= 0 && cost <= 999, "Assignment cost must be an integer in [0,999]"); file << cost << ' '; }
      file << '\n';
    }
    if (!file) throw Failure("backend_failure", "Cannot write native CUDA assignment input"); }
  const auto values = run_worker("hungarian-cuda", "GRAPHMINE_ASSIGNMENT", device, work, temp, {path.string()});
  if (values.size() != costs.size()) throw Failure("correctness_mismatch", "CUDA assignment has the wrong size");
  std::vector<bool> seen(costs.size(), false); std::vector<std::size_t> result;
  for (const auto column : values) {
    if (column < 0 || static_cast<std::size_t>(column) >= costs.size() || seen[column]) throw Failure("correctness_mismatch", "CUDA assignment is not a permutation");
    seen[column] = true; result.push_back(column);
  }
  return result;
#else
  throw Failure("backend_unavailable", "Native CUDA assignment worker was not compiled");
#endif
}
}  // namespace graphmine::runtime
