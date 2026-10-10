#include "internal.hpp"
#include "exact_number.hpp"

#include <algorithm>
#include <chrono>
#include <mutex>

#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
#include "backends/maximal_cliques/backend.hpp"
#include "backends/maximum_clique_backend.hpp"
#include "backends/k_clique_backend.hpp"
#include "backends/k_core_backend.hpp"
#include "backends/betweenness_centrality_backend.hpp"
#endif

namespace graphmine::runtime {
namespace {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
// Several collected artifacts retain process-global host state. Serialize
// their kernel entry points; CPU materialization stays outside this lock.
std::timed_mutex original_mutex;
std::unique_lock<std::timed_mutex> lock_original(Work& work) {
  work.tick(0); std::unique_lock<std::timed_mutex> lock(original_mutex, std::defer_lock);
  const auto maximum = std::chrono::steady_clock::time_point::max();
  const auto available = std::chrono::duration<double>(maximum - work.started).count();
  const auto deadline = work.timeout_seconds >= available ? maximum : work.started + std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::duration<double>(work.timeout_seconds));
  if (!lock.try_lock_until(deadline)) throw Failure("resource_limit", "Original backend admission deadline exceeded");
  work.tick(0); return lock;
}
void status(const Status& value) {
  if (value.ok()) return;
  const auto code = value.code() == StatusCode::resource_exhausted ? "resource_limit"
      : value.code() == StatusCode::unsupported ? "unsupported_input"
      : value.code() == StatusCode::backend_unavailable ? "backend_unavailable"
      : value.code() == StatusCode::correctness_mismatch ? "correctness_mismatch" : "backend_failure";
  throw Failure(code, value.message());
}
CsrGraph csr(const MiningGraph& adj, Work& work) {
  CsrGraph result; result.offsets.push_back(0);
  for (const auto& row : adj) { work.tick(row.size() + 1); result.neighbors.insert(result.neighbors.end(), row.begin(), row.end()); result.offsets.push_back(result.neighbors.size()); }
  return result;
}
#endif
}

json::array original_mining_backends(const std::string& operation) {
  json::array output;
  auto add = [&](const char* id, bool compiled, const char* execution) {
    output.push_back(json::object{{"id", id}, {"device", "gpu"}, {"compiled", compiled}, {"execution", execution}});
  };
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  if (operation == "maximal-cliques") {
    add("rdmce", detail::rdmce_backend_compiled(), "original GPU count plus bounded native materialization");
    add("mce-gpu", detail::mce_gpu_backend_compiled(), "original GPU count plus bounded native materialization");
    add("g2-aimd", detail::g2_aimd_backend_compiled(), "original GPU count plus bounded native materialization");
  } else if (operation == "maximum-clique") {
    add("cuda-ms", detail::cuda_ms_backend_compiled(), "original GPU witness plus native optimality proof");
    add("gpu-maximum-clique", detail::gpu_maximum_clique_backend_compiled(), "original GPU witness plus native optimality proof");
    add("maximum-clique-on-gpu", detail::maximum_clique_on_gpu_backend_compiled(), "original GPU witness plus native optimality proof");
  } else if (operation == "k-cliques") {
    add("graphset", detail::graphset_kclique_backend_compiled(), "original GPU count plus optional bounded native materialization");
    add("gamma", detail::gamma_kclique_backend_compiled(), "repaired original GPU count plus optional bounded native materialization");
    add("kcgpu", detail::kcgpu_backend_compiled(), "repaired original GPU count plus optional bounded native materialization");
  } else if (operation == "k-core") add("kcore-gpu", detail::kcore_gpu_backend_compiled(), "original GPU peeling kernels");
  else if (operation == "betweenness-centrality") add("turbo-bc", detail::turbobc_backend_compiled(), "original all-source GPU Brandes kernels, float32 accumulation");
#else
  const auto identifiers = operation == "maximal-cliques" ? std::vector<const char*>{"rdmce", "mce-gpu", "g2-aimd"}
      : operation == "maximum-clique" ? std::vector<const char*>{"cuda-ms", "gpu-maximum-clique", "maximum-clique-on-gpu"}
      : operation == "k-cliques" ? std::vector<const char*>{"graphset", "gamma", "kcgpu"}
      : operation == "betweenness-centrality" ? std::vector<const char*>{"turbo-bc"} : std::vector<const char*>{"kcore-gpu"};
  for (const auto id : identifiers) add(id, false, "not linked in this standalone build");
#endif
  return output;
}

std::uint64_t original_maximal_count(const MiningGraph& adj, const std::string& backend, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  // The artifacts' count-only entry points need isolates removed. Their
  // singleton maximal cliques are restored without changing external IDs.
  std::vector<VertexIndex> mapping(adj.size(), adj.size()); VertexIndex count = 0; std::uint64_t isolated = 0;
  for (VertexIndex v = 0; v < adj.size(); ++v) { work.tick(); if (adj[v].empty()) ++isolated; else mapping[v] = count++; }
  MiningGraph compact(count);
  for (VertexIndex v = 0; v < adj.size(); ++v) for (const auto u : adj[v]) { work.tick(); compact[mapping[v]].push_back(mapping[u]); }
  if (!count) return isolated;
  auto input = csr(compact, work); auto lock = lock_original(work); detail::BackendCountResult result;
  if (backend == "rdmce") result = detail::run_rdmce_count(input, device);
  else if (backend == "mce-gpu") result = detail::run_mce_gpu_count(input, device);
  else if (backend == "g2-aimd") result = detail::run_g2_aimd_count(input, device);
  else throw Failure("invalid_input", "Unknown original maximal-clique backend");
  status(result.status); work.tick(0);
  if (result.count > UINT64_MAX - isolated) throw Failure("resource_limit", "Original maximal-clique count exceeds uint64");
  return result.count + isolated;
#else
  throw Failure("backend_unavailable", "Original mining backends are not linked");
#endif
}

std::vector<VertexIndex> original_maximum_clique(const MiningGraph& adj, const std::string& backend, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  if (adj.empty()) return {};
  if (std::all_of(adj.begin(), adj.end(), [](const auto& row) { return row.empty(); })) return {0};
  if (backend == "cuda-ms") work.tick(static_cast<std::uint64_t>(adj.size()) * adj.size());
  auto input = csr(adj, work); auto lock = lock_original(work); detail::MaximumCliqueBackendResult result;
  if (backend == "cuda-ms") result = detail::run_cuda_ms(input, device);
  else if (backend == "gpu-maximum-clique") result = detail::run_gpu_maximum_clique(input, device);
  else if (backend == "maximum-clique-on-gpu") result = detail::run_maximum_clique_on_gpu(input, device);
  else throw Failure("invalid_input", "Unknown original maximum-clique backend");
  status(result.status); work.tick(0); return result.clique;
#else
  throw Failure("backend_unavailable", "Original mining backends are not linked");
#endif
}

std::uint64_t original_k_clique_count(const MiningGraph& adj, std::uint32_t k, const std::string& backend, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  auto input = csr(adj, work); auto lock = lock_original(work); detail::KCliqueBackendResult result;
  if (backend == "graphset") result = detail::run_graphset_kclique(input, k, device);
  else if (backend == "gamma") result = detail::run_gamma_kclique(input, k, device);
  else if (backend == "kcgpu") result = detail::run_kcgpu(input, k, device);
  else throw Failure("invalid_input", "Unknown original k-clique backend");
  status(result.status); work.tick(0); return result.count;
#else
  throw Failure("backend_unavailable", "Original mining backends are not linked");
#endif
}

std::vector<std::uint32_t> original_core_numbers(const MiningGraph& adj, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  if (std::all_of(adj.begin(), adj.end(), [](const auto& row) { return row.empty(); })) return std::vector<std::uint32_t>(adj.size(), 0);
  auto input = csr(adj, work); auto lock = lock_original(work); const auto result = detail::run_kcore_gpu(input, device);
  status(result.status); work.tick(0); return result.core_numbers;
#else
  throw Failure("backend_unavailable", "Original mining backends are not linked");
#endif
}
std::vector<double> original_betweenness(const MiningGraph& adj, int device, Work& work) {
#ifdef GRAPHMINE_NATIVE_ORIGINAL_MINING
  if (adj.size() < 3 || std::all_of(adj.begin(), adj.end(), [](const auto& row) { return row.empty(); })) return std::vector<double>(adj.size(), 0);
  std::uint64_t cost = adj.size(); for (const auto& row : adj) cost += row.size();
  const auto remaining = work.max_candidates - std::min(work.candidates, work.max_candidates);
  if (adj.size() > remaining / cost) throw Failure("resource_limit", "All-source TurboBC exceeds the GPU work budget");
  work.tick(cost * adj.size());
  auto input = csr(adj, work); auto lock = lock_original(work); const auto result = detail::run_turbobc(input, device);
  status(result.status); work.tick(0); return result.scores;
#else
  throw Failure("backend_unavailable", "Original TurboBC is not linked");
#endif
}
}  // namespace graphmine::runtime
