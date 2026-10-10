#pragma once

#include <cstddef>
#include <stdexcept>
#include <string>
#include <string_view>

namespace graphmine::runtime {

// The native runtime owns parsing, contracts, dispatch and computation. The
// same request protocol is used by C++ consumers, the CLI and language bindings.
// A response is either a result object or {"error":{"code":...,"message":...}}.
// No Python interpreter, Python package or generated code is used by this API.
std::string request(std::string_view json_request);
int abi_version() noexcept;

}  // namespace graphmine::runtime
