#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class KCoreBackend {
  automatic,
  kcore_gpu,
};

enum class KCoreOptionalOutput : std::uint32_t {
  none = 0,
  requested_core_vertices = 1U << 0U,
  requested_core_edges = 1U << 1U,
  peeling_order = 1U << 2U,
};

constexpr KCoreOptionalOutput operator|(KCoreOptionalOutput lhs,
                                        KCoreOptionalOutput rhs) {
  return static_cast<KCoreOptionalOutput>(static_cast<std::uint32_t>(lhs) |
                                          static_cast<std::uint32_t>(rhs));
}

constexpr bool has_output(KCoreOptionalOutput outputs,
                          KCoreOptionalOutput output) {
  return (static_cast<std::uint32_t>(outputs) &
          static_cast<std::uint32_t>(output)) != 0U;
}

struct KCoreOptions {
  KCoreBackend backend = KCoreBackend::automatic;
  std::optional<std::uint32_t> requested_k;
  KCoreOptionalOutput optional_outputs = KCoreOptionalOutput::none;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexCoreNumber {
  ExternalId vertex;
  std::uint32_t core_number = 0;
};

struct KCoreOutput {
  std::vector<VertexCoreNumber> core_number_by_vertex;
  std::uint32_t degeneracy = 0;
  std::optional<std::vector<ExternalId>> requested_core_vertices;
  std::optional<std::vector<ExternalId>> requested_core_edges;
  std::optional<std::vector<ExternalId>> peeling_order;
};

class KCore {
 public:
  explicit KCore(KCoreOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<KCoreOutput> run(const Graph& graph) const;
  [[nodiscard]] const KCoreOptions& options() const noexcept { return options_; }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  KCoreOptions options_;
};

[[nodiscard]] const char* to_string(KCoreBackend backend) noexcept;

}  // namespace graphmine
