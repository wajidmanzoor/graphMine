#include "internal.hpp"
namespace graphmine::runtime {
bool cudf_compiled() noexcept { return false; }
json::object read_csv(const json::object&) {
  throw Failure("backend_unavailable", "libcudf file reading is not linked in this native build");
}
}  // namespace graphmine::runtime
