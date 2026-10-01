cmake_minimum_required(VERSION 3.26)
project(SubgraphMatching LANGUAGES CUDA CXX)

set(CMAKE_VERBOSE_MAKEFILE ON)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Wall -pthread -march=native")

set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)

set(CMAKE_CUDA_ARCHITECTURES "89")
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Wno-deprecated-gpu-targets")

find_package(CUDAToolkit REQUIRED)

add_library(graph_objects SHARED graph.cu graph.h)
target_include_directories(graph_objects PUBLIC ${CUDAToolkit_INCLUDE_DIRS})
target_compile_definitions(graph_objects PRIVATE THRUST_IGNORE_DEPRECATED_CPP_DIALECT)
target_link_libraries(graph_objects PRIVATE CUDA::cudart_static)

add_library(join_objects SHARED candidate.cu candidate.h join_bfs.cu join_bfs_dfs.cu join.h)
target_include_directories(join_objects PUBLIC ${CUDAToolkit_INCLUDE_DIRS})
target_compile_definitions(join_objects PRIVATE THRUST_IGNORE_DEPRECATED_CPP_DIALECT)
target_link_libraries(join_objects PRIVATE CUDA::cudart_static)

set_target_properties(graph_objects join_objects PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
    POSITION_INDEPENDENT_CODE ON)

add_executable(SubgraphMatching main.cu)
target_link_libraries(SubgraphMatching PRIVATE graph_objects join_objects CUDA::cudart_static)
