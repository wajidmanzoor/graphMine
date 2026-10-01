#include "backends/temporal_motif_cuda_runner.cuh"

#include <limits>
#include <string>

#define GRAPHMINE_RAW_LIBRARY
#define _HELPERS_
#define __OLD_TMOFIT_LIGHT_INCLUDE_DATA_H_
#define gpuErrchk(answer)                                                \
  graphmine::detail::temporal_cuda::check((answer), #answer)
#define reduceEarlyIdx graphmine_everest_reduce_early_index
#define TContext GraphMineEverestContext
#define firstLarger graphmine_everest_first_larger
#define probeEnd graphmine_everest_probe_end
#define dumpContext graphmine_everest_dump_context
#define MotifMatching_Expand graphmine_everest_expand
#define MotifMatching_dispatch graphmine_everest_dispatch
#define TMotifMatchingGPUImpl graphmine_everest_execute_generated
#include "GPUWorkerDyn.cu"
#undef TMotifMatchingGPUImpl
#undef MotifMatching_dispatch
#undef MotifMatching_Expand
#undef dumpContext
#undef probeEnd
#undef firstLarger
#undef TContext
#undef reduceEarlyIdx
#undef gpuErrchk
#undef __OLD_TMOFIT_LIGHT_INCLUDE_DATA_H_
#undef _HELPERS_
#undef GRAPHMINE_RAW_LIBRARY

namespace graphmine::detail {

bool everest_backend_compiled() noexcept { return true; }

TemporalMotifBackendResult run_everest(
    const TemporalMotifBackendInput& input, int device_id) {
  if (input.events.empty()) return {Status::success(), 0, 0.0};

  int device_count = 0;
  auto code = cudaGetDeviceCount(&device_count);
  if (code != cudaSuccess || device_id < 0 || device_id >= device_count) {
    return {{StatusCode::backend_unavailable,
             "requested CUDA device is unavailable for Everest"},
            0, 0.0};
  }

  try {
    temporal_cuda::check(cudaSetDevice(device_id),
                         "selecting the Everest CUDA device");
    cudaDeviceProp properties{};
    temporal_cuda::check(cudaGetDeviceProperties(&properties, device_id),
                         "reading Everest CUDA device properties");

    constexpr int block_size = 96;
    int blocks_per_sm = 0;
    temporal_cuda::check(
        cudaOccupancyMaxActiveBlocksPerMultiprocessor(
            &blocks_per_sm, graphmine_everest_dispatch, block_size, 0),
        "computing Everest dispatch occupancy");
    const int dispatch_blocks = blocks_per_sm * properties.multiProcessorCount;
    temporal_cuda::check(
        cudaOccupancyMaxActiveBlocksPerMultiprocessor(
            &blocks_per_sm, graphmine_everest_expand, block_size, 0),
        "computing Everest expansion occupancy");
    const int expansion_blocks = blocks_per_sm * properties.multiProcessorCount;

    return temporal_cuda::execute<GraphMineEverestContext>(
        input, device_id, dispatch_blocks, expansion_blocks, block_size,
        "Everest", [](const auto& invocation) {
          return graphmine_everest_execute_generated(
              invocation.dispatch_blocks, invocation.expansion_blocks,
              invocation.block_size, invocation.work, invocation.delta,
              invocation.events, invocation.event_count,
              invocation.incoming_events, invocation.incoming_offsets,
              invocation.outgoing_events, invocation.outgoing_offsets,
              nullptr, nullptr, invocation.motif,
              invocation.motif_edge_count, invocation.yield,
              invocation.source, invocation.offload,
              invocation.offload_top, invocation.next_offload_top,
              invocation.offload_width, invocation.count);
        });
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string("Everest setup failed: ") + error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail
