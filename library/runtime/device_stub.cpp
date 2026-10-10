#include "internal.hpp"
namespace graphmine::runtime {
DeviceScope::DeviceScope(int) { throw Failure("backend_unavailable", "CUDA is not linked"); }
DeviceScope::~DeviceScope() = default;
bool gpu_available(int) noexcept { return false; }
json::object gpu_description(int) { return {}; }
}
