# Copyright 2026 Michael S. Gilbert II
# SPDX-License-Identifier: Apache-2.0
add_library(cluster OBJECT)
target_sources(cluster PRIVATE
    leidenR.cpp
    contract.cpp
    local_mover.cpp
    clustering_methods.cpp
    ordering.cpp)
#target_compile_definitions(cluster PRIVATE EXTRA_TIMING)
target_include_directories(cluster PRIVATE ${CMAKE_SOURCE_DIR}/interface)
target_link_libraries(cluster PRIVATE Kokkos::kokkos Kokkos::kokkoskernels)