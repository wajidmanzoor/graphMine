#include "internal.hpp"
#include <cuda_runtime_api.h>
#include <iomanip>
#include <sstream>
namespace graphmine::runtime {
DeviceScope::DeviceScope(int device) {
  if (cudaGetDevice(&previous) != cudaSuccess || cudaSetDevice(device) != cudaSuccess)
    throw Failure("backend_unavailable", "Cannot select CUDA device");
}
DeviceScope::~DeviceScope() { cudaSetDevice(previous); }
bool gpu_available(int device) noexcept {
  int count = 0;
  return device >= 0 && cudaGetDeviceCount(&count) == cudaSuccess && device < count;
}
json::object gpu_description(int device) {
  cudaDeviceProp props;
  if (cudaGetDeviceProperties(&props, device) != cudaSuccess)
    throw Failure("backend_unavailable", "Cannot inspect selected CUDA device");
  int runtime = 0, driver = 0;
  cudaRuntimeGetVersion(&runtime); cudaDriverGetVersion(&driver);
  std::ostringstream uuid;
  for (int i = 0; i < 16; ++i) {
    if (i == 4 || i == 6 || i == 8 || i == 10) uuid << '-';
    uuid << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(static_cast<unsigned char>(props.uuid.bytes[i]));
  }
  return {{"device_ordinal", device}, {"name", props.name}, {"uuid", "GPU-" + uuid.str()},
          {"cuda_runtime", runtime}, {"cuda_driver", driver}};
}
}
