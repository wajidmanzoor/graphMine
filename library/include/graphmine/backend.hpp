#pragma once

#include <string>
#include <vector>

namespace graphmine {

/// Describes one selectable implementation and the capabilities compiled into
/// the current GraphMine binary.
struct BackendInfo {
  std::string id;
  std::string display_name;
  std::string problem;
  std::string source_commit;
  bool compiled = false;
  bool validated = false;
  std::vector<std::string> capabilities;
};

/// Result of checking an input against an algorithm and backend contract.
struct SupportReport {
  bool supported = false;
  std::string reason;
};

}  // namespace graphmine
