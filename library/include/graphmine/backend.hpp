#pragma once

#include <string>
#include <vector>

namespace graphmine {

struct BackendInfo {
  std::string id;
  std::string display_name;
  std::string problem;
  std::string source_commit;
  bool compiled = false;
  bool validated = false;
  std::vector<std::string> capabilities;
};

struct SupportReport {
  bool supported = false;
  std::string reason;
};

}  // namespace graphmine
