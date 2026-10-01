#pragma once

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <cuda_runtime.h>

#include "backends/temporal_motif_backend.hpp"

namespace graphmine::detail::temporal_cuda {

struct RawTemporalEdge {
  int u = 0;
  int v = 0;
  int t = 0;
};

struct RawMotifEdgeInfo {
  int baseNode = 0;
  int constraintNode = 0;
  int mappedNodes = 0;
  const int* arrR = nullptr;
  const int* arrV = nullptr;
  int io = 0;
  bool newNode = false;
};

inline void check(cudaError_t code, const std::string& operation) {
  if (code != cudaSuccess) {
    throw std::runtime_error(operation + ": " + cudaGetErrorString(code));
  }
}

template <typename T>
class DeviceBuffer {
 public:
  DeviceBuffer() = default;
  explicit DeviceBuffer(std::size_t count) { allocate(count); }
  DeviceBuffer(const DeviceBuffer&) = delete;
  DeviceBuffer& operator=(const DeviceBuffer&) = delete;

  ~DeviceBuffer() {
    if (data_ != nullptr) cudaFree(data_);
  }

  void allocate(std::size_t count) {
    if (count == 0) return;
    check(cudaMalloc(&data_, sizeof(T) * count), "allocating CUDA memory");
    size_ = count;
  }

  void zero() {
    if (data_ != nullptr) {
      check(cudaMemset(data_, 0, sizeof(T) * size_),
            "clearing CUDA memory");
    }
  }

  void copy_from(const std::vector<T>& source) {
    if (source.size() != size_) {
      throw std::logic_error("CUDA buffer size does not match host input");
    }
    if (!source.empty()) {
      check(cudaMemcpy(data_, source.data(), sizeof(T) * source.size(),
                       cudaMemcpyHostToDevice),
            "copying temporal motif input to CUDA");
    }
  }

  T* get() noexcept { return data_; }
  const T* get() const noexcept { return data_; }

 private:
  T* data_ = nullptr;
  std::size_t size_ = 0;
};

template <typename Context>
struct Invocation {
  int dispatch_blocks = 0;
  int expansion_blocks = 0;
  int block_size = 96;
  int work = 0;
  int delta = 0;
  const RawTemporalEdge* events = nullptr;
  int event_count = 0;
  const int* incoming_events = nullptr;
  const int* incoming_offsets = nullptr;
  const int* outgoing_events = nullptr;
  const int* outgoing_offsets = nullptr;
  const RawMotifEdgeInfo* motif = nullptr;
  int motif_edge_count = 3;
  int* yield = nullptr;
  int* source = nullptr;
  Context* offload = nullptr;
  int* offload_top = nullptr;
  int* next_offload_top = nullptr;
  int* offload_width = nullptr;
  unsigned long long* count = nullptr;
};

template <typename Context, typename Runner>
TemporalMotifBackendResult execute(const TemporalMotifBackendInput& input,
                                   int device_id, int dispatch_blocks,
                                   int expansion_blocks, int block_size,
                                   const char* backend_name,
                                   Runner&& runner) {
  constexpr std::size_t kOffloadCapacity = 2092ULL * 96ULL;
  try {
    const auto started = std::chrono::steady_clock::now();

    std::vector<RawTemporalEdge> events;
    events.reserve(input.events.size());
    std::vector<int> incoming_offsets(
        static_cast<std::size_t>(input.vertex_count) + 1U, 0);
    std::vector<int> outgoing_offsets(
        static_cast<std::size_t>(input.vertex_count) + 1U, 0);
    for (const auto& event : input.events) {
      events.push_back({event.source, event.target, event.timestamp});
      ++outgoing_offsets[static_cast<std::size_t>(event.source) + 1U];
      ++incoming_offsets[static_cast<std::size_t>(event.target) + 1U];
    }
    for (std::size_t vertex = 1; vertex < incoming_offsets.size(); ++vertex) {
      incoming_offsets[vertex] += incoming_offsets[vertex - 1U];
      outgoing_offsets[vertex] += outgoing_offsets[vertex - 1U];
    }

    std::vector<int> incoming_events(events.size());
    std::vector<int> outgoing_events(events.size());
    auto incoming_cursor = incoming_offsets;
    auto outgoing_cursor = outgoing_offsets;
    for (std::size_t index = 0; index < events.size(); ++index) {
      incoming_events[static_cast<std::size_t>(
          incoming_cursor[static_cast<std::size_t>(events[index].v)]++)] =
          static_cast<int>(index);
      outgoing_events[static_cast<std::size_t>(
          outgoing_cursor[static_cast<std::size_t>(events[index].u)]++)] =
          static_cast<int>(index);
    }

    DeviceBuffer<RawTemporalEdge> events_device(events.size());
    DeviceBuffer<int> incoming_offsets_device(incoming_offsets.size());
    DeviceBuffer<int> outgoing_offsets_device(outgoing_offsets.size());
    DeviceBuffer<int> incoming_events_device(incoming_events.size());
    DeviceBuffer<int> outgoing_events_device(outgoing_events.size());
    events_device.copy_from(events);
    incoming_offsets_device.copy_from(incoming_offsets);
    outgoing_offsets_device.copy_from(outgoing_offsets);
    incoming_events_device.copy_from(incoming_events);
    outgoing_events_device.copy_from(outgoing_events);

    std::vector<RawMotifEdgeInfo> motif{
        {1, -2, 2, outgoing_offsets_device.get(),
         outgoing_events_device.get(), 1, true},
        {2, 0, 3, nullptr, nullptr, -1, false},
    };
    DeviceBuffer<RawMotifEdgeInfo> motif_device(motif.size());
    motif_device.copy_from(motif);

    DeviceBuffer<int> yield_device(1);
    DeviceBuffer<int> source_device(1);
    DeviceBuffer<Context> offload_device(kOffloadCapacity);
    DeviceBuffer<int> offload_top_device(1);
    DeviceBuffer<int> next_offload_top_device(1);
    DeviceBuffer<int> offload_width_device(kOffloadCapacity);
    DeviceBuffer<unsigned long long> count_device(1);
    yield_device.zero();
    source_device.zero();
    offload_device.zero();
    offload_top_device.zero();
    next_offload_top_device.zero();
    offload_width_device.zero();
    count_device.zero();

    Invocation<Context> invocation;
    invocation.dispatch_blocks = dispatch_blocks;
    invocation.expansion_blocks = expansion_blocks;
    invocation.block_size = block_size;
    invocation.work = static_cast<int>(events.size());
    invocation.delta = input.max_time_span;
    invocation.events = events_device.get();
    invocation.event_count = static_cast<int>(events.size());
    invocation.incoming_events = incoming_events_device.get();
    invocation.incoming_offsets = incoming_offsets_device.get();
    invocation.outgoing_events = outgoing_events_device.get();
    invocation.outgoing_offsets = outgoing_offsets_device.get();
    invocation.motif = motif_device.get();
    invocation.yield = yield_device.get();
    invocation.source = source_device.get();
    invocation.offload = offload_device.get();
    invocation.offload_top = offload_top_device.get();
    invocation.next_offload_top = next_offload_top_device.get();
    invocation.offload_width = offload_width_device.get();
    invocation.count = count_device.get();

    const auto count = runner(invocation);
    check(cudaDeviceSynchronize(),
          std::string("synchronizing ") + backend_name);
    const auto finished = std::chrono::steady_clock::now();
    return {Status::success(), static_cast<std::uint64_t>(count),
            std::chrono::duration<double, std::milli>(finished - started)
                .count()};
  } catch (const std::exception& error) {
    return {{StatusCode::execution_failed,
             std::string(backend_name) + " execution failed: " +
                 error.what()},
            0, 0.0};
  }
}

}  // namespace graphmine::detail::temporal_cuda

// The generated sources refer to these original artifact types by name.  The
// aliases avoid pulling their file/cache/Boost infrastructure into the
// library while preserving the exact layout consumed by the kernels.
namespace corelib {
using TemporalEdge = graphmine::detail::temporal_cuda::RawTemporalEdge;
using MotifEdgeInfoV1 = graphmine::detail::temporal_cuda::RawMotifEdgeInfo;
namespace data {}
}  // namespace corelib
