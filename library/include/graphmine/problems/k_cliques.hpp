#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "graphmine/backend.hpp"
#include "graphmine/execution.hpp"
#include "graphmine/graph.hpp"

namespace graphmine {

enum class KCliqueBackend {
  automatic,
  kcgpu,
  graphset,
  gamma,
};

struct KCliqueOptions {
  std::uint32_t k = 3;
  KCliqueBackend backend = KCliqueBackend::automatic;
  bool enumerate = false;
  bool include_per_vertex_counts = false;
  std::optional<std::uint64_t> result_limit;
  bool allow_directed_projection = false;
  ExecutionOptions execution;
};

struct VertexKCliqueCount {
  ExternalId vertex;
  std::uint64_t count = 0;
};

struct KCliqueOutput {
  std::uint64_t count = 0;
  bool complete = true;
  std::optional<std::vector<std::vector<ExternalId>>> cliques;
  std::optional<std::vector<VertexKCliqueCount>> per_vertex_count;
};

class KCliques {
 public:
  explicit KCliques(KCliqueOptions options = {});

  [[nodiscard]] SupportReport supports(const Graph& graph) const;
  [[nodiscard]] ExecutionResult<KCliqueOutput> run(const Graph& graph) const;
  [[nodiscard]] const KCliqueOptions& options() const noexcept {
    return options_;
  }

  [[nodiscard]] static std::vector<BackendInfo> backends();

 private:
  KCliqueOptions options_;
};

[[nodiscard]] const char* to_string(KCliqueBackend backend) noexcept;

}  // namespace graphmine
