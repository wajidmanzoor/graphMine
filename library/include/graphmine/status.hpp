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
  /// Constructs a successful status.
  Status() = default;

  /// Constructs a status with an explicit code and diagnostic message.
  Status(StatusCode code, std::string message)
      : code_(code), message_(std::move(message)) {}

  /// Returns a successful status value.
  static Status success() { return {}; }

  /// Returns true only when the status code is StatusCode::ok.
  [[nodiscard]] bool ok() const noexcept { return code_ == StatusCode::ok; }

  /// Returns the machine-readable status code.
  [[nodiscard]] StatusCode code() const noexcept { return code_; }

  /// Returns the human-readable diagnostic, which is empty on success.
  [[nodiscard]] const std::string& message() const noexcept { return message_; }

 private:
  StatusCode code_ = StatusCode::ok;
  std::string message_;
};

}  // namespace graphmine
