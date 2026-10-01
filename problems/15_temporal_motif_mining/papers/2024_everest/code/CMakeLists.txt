cmake_minimum_required(VERSION 3.18)
# set(CMAKE_VERBOSE_MAKEFILE ON)

# Use compilers selected by CMake/the caller.  The artifact originally pinned
# author-local CUDA 11.4 and GCC 9 paths, which makes it impossible to build on
# otherwise compatible CUDA installations.

set(CMAKE_CUDA_SEPARABLE_COMPILATION ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

project(TMotifGPU
        VERSION 0.1 
        DESCRIPTION "GPU implementation of temporal motif matching" 
        LANGUAGES CXX CUDA)


if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CUDA_STANDARD 17)

set(CMAKE_CXX_FLAGS "-Wall -Wextra -export-dynamic")
set(CMAKE_CXX_FLAGS_DEBUG "-g")
set(CMAKE_CXX_FLAGS_RELEASE "-O3")
set(CMAKE_CUDA_FLAGS_DEBUG "-lineinfo")
set(CMAKE_CUDA_FLAGS_RELEASE "-O3 -lineinfo")

# for fast graph parsing
# find_package(OpenMP)

find_package(Boost REQUIRED COMPONENTS system iostreams)
set_property(TARGET Boost::iostreams PROPERTY INTERFACE_INCLUDE_DIRECTORIES "${Boost_INCLUDE_DIRS}")
include_directories(${Boost_INCLUDE_DIR} ${pybind11_INCLUDE_DIR})

include(FetchContent)

FetchContent_Declare(
        Range-v3
        GIT_REPOSITORY https://github.com/ericniebler/range-v3
        GIT_TAG 0.12.0
)

FetchContent_MakeAvailable(Range-v3)

# FetchContent_Declare(
#   mimalloc
#   GIT_REPOSITORY https://github.com/microsoft/mimalloc.git
#   GIT_TAG v2.0.9
# )
# FetchContent_MakeAvailable(mimalloc)

# pybind11 =================================================================== #
find_package(pybind11 CONFIG QUIET)
if(NOT pybind11_FOUND)
  FetchContent_Declare(
    pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG v2.11.1
  )
  FetchContent_MakeAvailable(pybind11)
endif()

FetchContent_Declare(fmt
  GIT_REPOSITORY https://github.com/fmtlib/fmt.git
  GIT_TAG 10.2.1
)
FetchContent_MakeAvailable(fmt)

#---------------------------------------------------------------------------


include_directories(include ${pybind11_INCLUDE_DIRS})

if(NOT CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES "86")
endif()


add_subdirectory(plugins)
add_subdirectory(src)
