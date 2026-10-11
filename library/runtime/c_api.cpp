#include <cstdlib>
#include <cstring>

#include "graphmine/runtime.hpp"
#include "graphmine/runtime_c.h"

extern "C" int graphmine_runtime_abi_version(void) { return graphmine::runtime::abi_version(); }
extern "C" int graphmine_runtime_request(const char* request, size_t length, char** response,
                                         size_t* response_length) {
  if (!response || !response_length || (!request && length)) return -1;
  *response = nullptr;
  *response_length = 0;
  try {
    const auto result =
        graphmine::runtime::request(std::string_view(request ? request : "", length));
    auto* output = static_cast<char*>(std::malloc(result.size() + 1));
    if (!output) return -1;
    std::memcpy(output, result.c_str(), result.size() + 1);
    *response = output;
    *response_length = result.size();
    return 0;
  } catch (...) {
    return -1;
  }
}
extern "C" void graphmine_runtime_free(void* response) { std::free(response); }
