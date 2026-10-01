# Set the minimum required version of CMake
cmake_minimum_required(VERSION 3.25)

# Set the project name and specify CUDA language
project(RDMCE LANGUAGES CXX CUDA)

# First try to find CUDA toolkit without setting any paths
find_package(CUDAToolkit QUIET)

# If CUDA toolkit not found, provide clear instructions
if(NOT CUDAToolkit_FOUND)
    message(WARNING "CUDA Toolkit not found automatically.")
    message("Please set CUDA_TOOLKIT_ROOT_DIR to your CUDA installation path, e.g.:")
    message("  cmake -DCUDA_TOOLKIT_ROOT_DIR=/path/to/your/cuda ..")
    
    # Optionally set a cache variable to make it easier for users
    set(CUDA_TOOLKIT_ROOT_DIR "" CACHE PATH "Path to CUDA toolkit installation")
    
    # Now try again with user-provided path if any
    find_package(CUDAToolkit REQUIRED)
endif()

# Set the C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Include project headers
include_directories(${PROJECT_SOURCE_DIR}/include)

# Use native CUDA architecture detection (CMake 3.24+)
set(CMAKE_CUDA_ARCHITECTURES native)

# Collect all source files
file(GLOB_RECURSE SOURCES "src/*.cc" "src/*.cpp" "src/*.cu" "main.cc")

# Create executable
add_executable(${PROJECT_NAME} ${SOURCES})

# Enable RDC (Relocatable Device Code)
set_target_properties(${PROJECT_NAME} PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
)

# Link CUDA libraries using modern CMake targets
target_link_libraries(${PROJECT_NAME} PRIVATE CUDA::cudart)

if(DEFINED BLOCK_PER_SM)
    target_compile_definitions(${PROJECT_NAME} PRIVATE BLOCK_PER_SM=${BLOCK_PER_SM})
endif()

if(DEFINED WARP_PER_BLOCK)
    target_compile_definitions(${PROJECT_NAME} PRIVATE WARP_PER_BLOCK=${WARP_PER_BLOCK})
endif()

if(DEFINED TASK_SHARE_BOUND)
    target_compile_definitions(${PROJECT_NAME} PRIVATE TASK_SHARE_BOUND=${TASK_SHARE_BOUND})
endif()

if(DEFINED EXPAND_R)
    if(NOT EXPAND_R)
        target_compile_definitions(${PROJECT_NAME} PRIVATE "-UEXPAND_R")
    else()
        target_compile_definitions(${PROJECT_NAME} PRIVATE EXPAND_R)
    endif()
endif()

# Set optimization flags based on compiler
if (CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native")
elseif (CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /O2")
endif()

# Set CUDA optimization flags
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -O3")