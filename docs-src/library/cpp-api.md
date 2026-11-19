# C++ and C API

Call the current native runtime from a compiled program without a Python interpreter.

## C++ request interface

```cpp
#include <graphmine/runtime.hpp>
#include <iostream>

int main() {
    std::cout << graphmine::runtime::request(
        R"({"command":"catalog"})"
    );
}
```

`request(std::string_view)` accepts the same JSON protocol used by the CLI and bindings. `abi_version()` returns the runtime ABI version. A calculation request supplies `command: "run"`, `operation`, `graph`, `parameters`, and `device`; inspect the response for an `error` object.

```cmake
cmake_minimum_required(VERSION 3.24)
project(MyGraphTool LANGUAGES CXX)
find_package(GraphMineRuntime CONFIG REQUIRED)
add_executable(my_graph_tool main.cpp)
target_link_libraries(my_graph_tool PRIVATE GraphMine::runtime)
```

Point `CMAKE_PREFIX_PATH` at the prefix used by `cmake --install`. The [native consumer examples](https://github.com/wajidmanzoor/graphMine/tree/main/library/examples/native_runtime) include a complete maximum-clique request and a C consumer.

## C allocation and errors

Include `graphmine/runtime_c.h`. Call `graphmine_runtime_request` with the input bytes and length, plus output pointer and length arguments. A return value of `0` means the response was allocated; algorithm failures are still represented inside that response. `-1` indicates invalid output pointers or allocation failure. Release the returned allocation with `graphmine_runtime_free`, including when the JSON contains an error.

[Open the generated API and source reference](code-reference.md) for signatures, types, and implementation files. [Input formats](graph-format.md) and [outputs](outputs.md) describe the protocol's data contracts.
