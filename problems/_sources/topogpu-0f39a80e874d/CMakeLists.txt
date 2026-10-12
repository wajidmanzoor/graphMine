cmake_minimum_required(VERSION 3.24)
project(topoGPU LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

if(NOT CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 61 75 80 86 89 90 90-virtual)
endif()

find_package(CUDAToolkit REQUIRED)
find_package(OpenMP REQUIRED COMPONENTS CXX)

set(TOPOGPU_SOURCES
  src/main.cpp
  src/fileIO.cpp
  src/util.cpp
  src/morse_boundary.cu
  src/morse_matching.cu
  src/topo.cu
  src/topo_batch.cu
  src/util_cu.cu)

add_executable(topoGPU ${TOPOGPU_SOURCES})

target_include_directories(topoGPU PRIVATE
  ${CMAKE_SOURCE_DIR}/src
  ${CMAKE_SOURCE_DIR}/third_party
  ${CMAKE_SOURCE_DIR}/third_party/phat/include)

target_compile_definitions(topoGPU PRIVATE ENABLE_THRUST=1)
target_link_libraries(topoGPU PRIVATE CUDA::cudart OpenMP::OpenMP_CXX)

# CUDA flags
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} --use_fast_math")
if(MSVC)
  set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xcompiler=/openmp")
else()
  set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xcompiler=-fopenmp")
endif()