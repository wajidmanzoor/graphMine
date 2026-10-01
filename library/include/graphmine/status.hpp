#pragma once

#include <string>
#include <utility>

namespace graphmine {

enum class StatusCode {
  ok = 0,
  invalid_argument,
  unsupported,
  backend_unavailable,
  execution_failed,
  correctness_mismatch,
  resource_exhausted,
  internal_error,
};

class Status {
 public:
  Status() = default;
  Status(StatusCode code, std::string message)
      : code_(code), message_(std::move(message)) {}

  static Status success() { return {}; }

  [[nodiscard]] bool ok() const noexcept { return code_ == StatusCode::ok; }
  [[nodiscard]] StatusCode code() const noexcept { return code_; }
  [[nodiscard]] const std::string& message() const noexcept { return message_; }

 private:
  StatusCode code_ = StatusCode::ok;
  std::string message_;
};

}  // namespace graphmine
