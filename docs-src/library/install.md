# Build and install the library

Build a local CPU runtime, run a small graph calculation, and prepare to use the same API with optional CUDA backends.

## Requirements

Use a C++17 compiler, CMake 3.24 or newer, Python 3 for build-time catalog generation, Boost.JSON, OpenSSL, LAPACK, and ICU development libraries. CUDA is optional for the standalone CPU runtime. The calculation itself does not require a Python interpreter.

On Debian or Ubuntu:

```sh
sudo apt install git build-essential cmake python3-dev python3-venv \
  libboost-json-dev libssl-dev liblapack-dev libicu-dev

git clone https://github.com/wajidmanzoor/graphMine.git
cd graphMine
```

## Build

=== "CPU"

    ```sh
    cmake -S library/runtime -B build/native-cpu -DCMAKE_BUILD_TYPE=Release
    cmake --build build/native-cpu -j4
    ctest --test-dir build/native-cpu --output-on-failure
    build/native-cpu/graphmine-native catalog
    build/native-cpu/graphmine-native run triangle-counting \
      library/examples/data/triangle.json --device cpu
    ```

    This example contains one triangle. Reduce build parallelism if memory is limited.

=== "CPU and CUDA"

    Configure the `library` project to include its optional CUDA implementations, together with the native runtime:

    ```sh
    cmake -S library -B build/native-cuda \
      -DGRAPHMINE_BUILD_NATIVE_RUNTIME=ON -DCMAKE_BUILD_TYPE=Release
    cmake --build build/native-cuda -j4
    build/native-cuda/runtime/graphmine-native catalog
    ```

    This is a starting configuration, not a promise that every optional backend will compile. Individual backends require their declared toolkit and native dependencies. The [CMake options](https://github.com/wajidmanzoor/graphMine/blob/main/library/CMakeLists.txt) and [backend profiles](backends.md) identify the available integrations. Inspect your resulting catalog before choosing one.

## Install for native consumers

```sh
cmake --install build/native-cpu --prefix "$PWD/build/install"
```

CMake consumers use `find_package(GraphMineRuntime CONFIG REQUIRED)` and link `GraphMine::runtime`. See the [C++ and C API](cpp-api.md) for a complete consumer example.

## Check your build

`ctest` checks the native tests included by the build. The repository also has independent Python oracle and completion suites; these are validation dependencies, not alternative execution engines.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e 'python/graphmine[reference,test]'
```

To generate CPU reference evidence for this build:

```python
from pathlib import Path
from tools.validate_native_runtime import validate

validate(
    Path("build/native-cpu").resolve(),
    "cpu", 0,
    Path("validation/local-cpu").resolve(),
)
```

Run this Python snippet from the repository root after activating the environment. Preserve the generated evidence with the tested build. Source or dependency changes require fresh validation; a report from a different binary is not evidence for yours.
