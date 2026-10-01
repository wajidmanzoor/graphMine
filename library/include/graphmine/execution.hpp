#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "graphmine/status.hpp"

namespace graphmine {

struct ExecutionOptions {
  std::vector<int> device_ids{0};
  bool collect_statistics = true;
};

struct ExecutionStatistics {
  double end_to_end_ms = 0.0;
  double backend_ms = 0.0;
  double output_materialization_ms = 0.0;
  std::optional<std::uint64_t> peak_gpu_bytes;
};

struct Provenance {
  std::string problem;
  std::string backend;
  std::string backend_version;
  std::string source_commit;
  std::string execution_path;
};

template <typename T>
class ExecutionResult {
 public:
  /// Constructs a successful result containing output and execution metadata.
  static ExecutionResult success(T output, Provenance provenance = {},
                                 ExecutionStatistics statistics = {},
                                 std::vector<std::string> warnings = {}) {
    ExecutionResult result;
    result.output_ = std::move(output);
    result.provenance_ = std::move(provenance);
    result.statistics_ = std::move(statistics);
    result.warnings_ = std::move(warnings);
    return result;
  }

  /// Constructs a failed result with no output value.
  static ExecutionResult failure(Status status,
                                 Provenance provenance = {},
                                 std::vector<std::string> warnings = {}) {
    ExecutionResult result;
    result.status_ = std::move(status);
    result.provenance_ = std::move(provenance);
    result.warnings_ = std::move(warnings);
    return result;
  }

  /// Returns true when execution succeeded and an output value is present.
  [[nodiscard]] bool ok() const noexcept {
    return status_.ok() && output_.has_value();
  }

  /// Returns the success or failure status.
  [[nodiscard]] const Status& status() const noexcept { return status_; }

  /// Returns the immutable output or throws std::logic_error on failure.
  [[nodiscard]] const T& value() const {
    if (!ok()) {
      throw std::logic_error("ExecutionResult has no value: " +
                             status_.message());
    }
    return *output_;
  }

  /// Returns the mutable output or throws std::logic_error on failure.
  [[nodiscard]] T& value() {
    if (!ok()) {
      throw std::logic_error("ExecutionResult has no value: " +
                             status_.message());
    }
    return *output_;
  }

  /// Returns the selected backend and preserved source provenance.
  [[nodiscard]] const Provenance& provenance() const noexcept {
    return provenance_;
  }

  /// Returns timing and optional GPU-memory statistics.
  [[nodiscard]] const ExecutionStatistics& statistics() const noexcept {
    return statistics_;
  }

  /// Returns nonfatal normalization and execution warnings.
  [[nodiscard]] const std::vector<std::string>& warnings() const noexcept {
    return warnings_;
  }

 private:
  Status status_;
  std::optional<T> output_;
  Provenance provenance_;
  ExecutionStatistics statistics_;
  std::vector<std::string> warnings_;
};

}  // namespace graphmine
