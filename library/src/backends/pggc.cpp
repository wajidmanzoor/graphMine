#include "backends/community_detection_backend.hpp"

#include <chrono>
#include <cstdlib>
#include <cstdint>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include <cuda_runtime.h>
#include <Kokkos_Core.hpp>

#include "ExperimentLoggerUtil.hpp"
#include "cluster_data.hpp"
#include "clustering_methods.h"
#include "core_types.h"
#include "memory_store.hpp"
#include "weighted_graph.h"

namespace graphmine::detail {
namespace {

using PggcVertexView = Kokkos::View<ordinal_t*, Device>;
using PggcOffsetView = Kokkos::View<edge_offset_t*, Device>;
using PggcWeightView = Kokkos::View<value_t*, Device>;

std::mutex pggc_mutex;

struct KokkosRuntime {
  bool owned = false;
  bool finalizer_registered = false;
  int device_id = -1;
};

KokkosRuntime& runtime() {
  // Deliberately process-lived: Kokkos installs CUDA runtime teardown state
  // during initialize().  Registering our finalizer afterwards makes it run
  // before that state is destroyed.
  static auto* state = new KokkosRuntime;
  return *state;
}

void ensure_kokkos(int device_id) {
  auto& state = runtime();
  if (!Kokkos::is_initialized()) {
    Kokkos::InitializationSettings settings;
    settings.set_device_id(device_id);
    Kokkos::initialize(settings);
    state.owned = true;
    state.device_id = device_id;
    if (!state.finalizer_registered) {
      std::atexit([] {
        auto& final_state = runtime();
        if (final_state.owned && Kokkos::is_initialized()) {
          Kokkos::finalize();
        }
      });
      state.finalizer_registered = true;
    }
    return;
  }
  if (state.device_id < 0) {
    int active_device = -1;
    if (cudaGetDevice(&active_device) == cudaSuccess) {
      state.device_id = active_device;
    }
  }
  if (state.device_id >= 0 && state.device_id != device_id) {
    throw std::invalid_argument(
        "the Kokkos CUDA runtime is already initialized on another device");
  }
}

matrix_t make_matrix(const CsrGraph& graph) {
  const auto vertex_count = static_cast<ordinal_t>(graph.vertex_count());
  const auto arc_count = static_cast<edge_offset_t>(graph.neighbors.size());

  PggcOffsetView offsets_device(
      Kokkos::ViewAllocateWithoutInitializing("GraphMine row offsets"),
      static_cast<std::size_t>(vertex_count) + 1U);
  PggcVertexView neighbors_device(
      Kokkos::ViewAllocateWithoutInitializing("GraphMine neighbors"),
      static_cast<std::size_t>(arc_count));
  auto offsets_host = Kokkos::create_mirror_view(offsets_device);
  auto neighbors_host = Kokkos::create_mirror_view(neighbors_device);
  for (ordinal_t vertex = 0; vertex <= vertex_count; ++vertex) {
    offsets_host(vertex) = static_cast<edge_offset_t>(graph.offsets[vertex]);
  }
  for (edge_offset_t edge = 0; edge < arc_count; ++edge) {
    neighbors_host(edge) = static_cast<ordinal_t>(graph.neighbors[edge]);
  }
  Kokkos::deep_copy(offsets_device, offsets_host);
  Kokkos::deep_copy(neighbors_device, neighbors_host);

  using GraphType = typename matrix_t::staticcrsgraph_type;
  GraphType topology(neighbors_device, offsets_device);
  PggcWeightView no_explicit_weights;
  return matrix_t("GraphMine community graph", vertex_count,
                  no_explicit_weights, topology);
}

PggcWeightView make_degree_weights(const CsrGraph& graph) {
  PggcWeightView weights(
      Kokkos::ViewAllocateWithoutInitializing("GraphMine vertex degrees"),
      graph.vertex_count());
  auto host = Kokkos::create_mirror_view(weights);
  for (std::size_t vertex = 0; vertex < graph.vertex_count(); ++vertex) {
    host(static_cast<ordinal_t>(vertex)) = static_cast<value_t>(
        graph.offsets[vertex + 1U] - graph.offsets[vertex]);
  }
  Kokkos::deep_copy(weights, host);
  return weights;
}

}  // namespace

bool pggc_backend_compiled() noexcept { return true; }

CommunityDetectionBackendResult run_pggc(const CsrGraph& graph,
                                          int device_id,
                                          PggcAlgorithm algorithm) {
  if (graph.vertex_count() == 0) {
    return {Status::success(), {}, 0.0, 0.0};
  }
  if (graph.vertex_count() >
          static_cast<std::size_t>(std::numeric_limits<ordinal_t>::max()) ||
      graph.neighbors.size() > static_cast<std::size_t>(
                                   std::numeric_limits<edge_offset_t>::max())) {
    return {{StatusCode::unsupported,
             "parallel multilevel clustering uses signed 32-bit graph "
             "indices"},
            {}, std::nullopt, 0.0};
  }

  int device_count = 0;
  if (cudaGetDeviceCount(&device_count) != cudaSuccess || device_id < 0 ||
      device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for parallel multilevel "
             "clustering"},
            {}, std::nullopt, 0.0};
  }

  try {
    std::lock_guard<std::mutex> lock(pggc_mutex);
    if (!Kokkos::is_initialized()) {
      const auto code = cudaSetDevice(device_id);
      if (code != cudaSuccess) {
        throw std::runtime_error(cudaGetErrorString(code));
      }
    }
    ensure_kokkos(device_id);

    const auto started = std::chrono::steady_clock::now();
    auto matrix = make_matrix(graph);
    jet_community::weighted_graph weighted;
    weighted.mtx = matrix;
    weighted.vtx_w = make_degree_weights(graph);
    weighted.edge_uniform = true;

    modularity objective(matrix, weighted.vtx_w, 1.0, true);
    memory_store memory(matrix, objective);
    jet_community::ExperimentLoggerUtil<value_t> experiment;
    PggcVertexView unused_constraint;
    PggcVertexView partition;
    switch (algorithm) {
      case PggcAlgorithm::parallel_louvain:
        partition = jet_community::clustering_methods::louvain_part<false>(
            memory, weighted, objective, experiment, unused_constraint);
        break;
      case PggcAlgorithm::parallel_leiden:
        partition = jet_community::clustering_methods::leiden_part<false,
                                                                      false>(
            memory, weighted, objective, experiment, unused_constraint);
        break;
      case PggcAlgorithm::parallel_leiden_plus:
        partition = jet_community::clustering_methods::leiden_part<true,
                                                                      false>(
            memory, weighted, objective, experiment, unused_constraint);
        break;
    }
    Kokkos::fence();
    const auto partition_host = Kokkos::create_mirror_view(partition);
    Kokkos::deep_copy(partition_host, partition);

    std::vector<std::uint32_t> labels(graph.vertex_count());
    for (std::size_t vertex = 0; vertex < labels.size(); ++vertex) {
      const auto label = partition_host(static_cast<ordinal_t>(vertex));
      if (label < 0 || label >= static_cast<ordinal_t>(graph.vertex_count())) {
        return {{StatusCode::correctness_mismatch,
                 "parallel multilevel clustering returned an invalid label"},
                {}, std::nullopt, 0.0};
      }
      labels[vertex] = static_cast<std::uint32_t>(label);
    }
    const auto native_modularity = objective.get_objective();
    const auto finished = std::chrono::steady_clock::now();
    return {Status::success(), std::move(labels), native_modularity,
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("parallel multilevel clustering failed: ") +
                 error.what()},
            {}, std::nullopt, 0.0};
  }
}

}  // namespace graphmine::detail
