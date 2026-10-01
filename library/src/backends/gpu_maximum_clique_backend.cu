#include "backends/maximum_clique_backend.hpp"

#include <climits>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <cuda_runtime.h>

#include "cliqueMerging.cuh"

namespace graphmine::detail {
namespace {

std::mutex gpu_maximum_clique_mutex;

}  // namespace

bool gpu_maximum_clique_backend_compiled() noexcept { return true; }

MaximumCliqueBackendResult run_gpu_maximum_clique(
    const CsrGraph& graph, int device_id, std::uint32_t known_lower_bound,
    bool return_all_ties) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0, 0.0};
  }
  if (graph.vertex_count() > static_cast<std::size_t>(UINT_MAX) ||
      graph.neighbors.size() > static_cast<std::size_t>(UINT_MAX)) {
    return {{StatusCode::unsupported,
             "GPUMaximumClique uses unsigned 32-bit graph indices"},
            {}, 0, 0.0};
  }

  int device_count = 0;
  if (device_id < 0 || cudaGetDeviceCount(&device_count) != cudaSuccess ||
      device_id >= device_count || cudaSetDevice(device_id) != cudaSuccess) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for GPUMaximumClique"},
            {}, 0, 0.0};
  }

  try {
    std::lock_guard<std::mutex> lock(gpu_maximum_clique_mutex);
    std::vector<unsigned int> offsets;
    offsets.reserve(graph.offsets.size());
    for (const auto offset : graph.offsets) {
      offsets.push_back(static_cast<unsigned int>(offset));
    }
    std::vector<unsigned int> neighbors(graph.neighbors.begin(),
                                        graph.neighbors.end());

    // Use the validated defaults.  The caller's lower bound is verified by
    // the common facade rather than used for pruning because this API accepts
    // a size, not the corresponding clique vertices needed as a fallback.
    (void)known_lower_bound;
    std::vector<std::string> arguments = {
        "graphmine-gpu-maximum-clique",
        "--device=" + std::to_string(device_id),
        "--quiet=true",
        "--timing=none",
        "--num_runs=1",
        "--bfs=true",
        "--windowing=false",
        "--overall_perf=true",
    };
    std::vector<char*> argv;
    argv.reserve(arguments.size());
    for (auto& argument : arguments) argv.push_back(argument.data());

    clique_node* output = new clique_node();
    gpu_maximum_clique_library_result upstream_result;
    const auto error = findMaxCliquesGPU(
        "GraphMine in-memory maximum clique", static_cast<int>(argv.size()),
        argv.data(), &output, static_cast<unsigned int>(graph.vertex_count()),
        static_cast<unsigned int>(graph.neighbors.size()), offsets.data(),
        neighbors.data(), return_all_ties, &upstream_result);
    if (error != cudaSuccess) {
      if (output != nullptr) delete output;
      return {{StatusCode::execution_failed,
               std::string("GPUMaximumClique failed: ") +
                   cudaGetErrorString(error)},
              {}, 0, 0.0};
    }
    if (upstream_result.out_of_memory) {
      return {{StatusCode::resource_exhausted,
               "GPUMaximumClique exhausted GPU memory before completing its "
               "exact search"},
              {}, 0, upstream_result.elapsed_ms};
    }
    if (upstream_result.cliques.empty()) {
      return {{StatusCode::execution_failed,
               "GPUMaximumClique completed without a clique result"},
              {}, 0, upstream_result.elapsed_ms};
    }

    MaximumCliqueBackendResult result;
    result.status = Status::success();
    result.elapsed_ms = upstream_result.elapsed_ms;
    result.clique.assign(upstream_result.cliques.front().begin(),
                         upstream_result.cliques.front().end());
    result.relaxation_upper_size =
        static_cast<std::uint32_t>(result.clique.size());
    if (return_all_ties) {
      result.tied_cliques.reserve(upstream_result.cliques.size());
      for (auto& clique : upstream_result.cliques) {
        result.tied_cliques.emplace_back(clique.begin(), clique.end());
      }
    }
    return result;
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("GPUMaximumClique execution failed: ") +
                 error.what()},
            {}, 0, 0.0};
  }
}

}  // namespace graphmine::detail
