# Copyright 2026 Michael S. Gilbert II
# SPDX-License-Identifier: Apache-2.0
add_executable(plouvain cluster_main.cpp)
add_executable(pleiden cluster_main.cpp)
add_executable(pleiden+ cluster_main.cpp)
add_executable(meme memetic_clustering.cpp)
add_executable(verify_obj verify_objective.cpp)
add_library(io OBJECT io/io_mtx.cpp io/io_metis.cpp io/parse_args.cpp io/vertex_weighting.cpp)

set(TARGETS plouvain pleiden pleiden+ verify_obj meme io)
set(TARGETS_FOR_IO plouvain pleiden pleiden+ verify_obj meme)
set(TARGETS_FOR_CLUSTER plouvain pleiden pleiden+ meme)

foreach(prog IN LISTS TARGETS)
    target_include_directories(${prog} PRIVATE ${CMAKE_SOURCE_DIR}/interface)
endforeach(prog)

target_compile_definitions(pleiden PUBLIC LEIDEN)
target_compile_definitions(pleiden+ PUBLIC LEIDEN LEIDEN_PLUS)
target_compile_definitions(meme PUBLIC LEIDEN_PLUS)
foreach(prog IN LISTS TARGETS)
    target_link_libraries(${prog} PRIVATE Kokkos::kokkos Kokkos::kokkoskernels)
endforeach()
foreach(prog IN LISTS TARGETS_FOR_CLUSTER)
    target_link_libraries(${prog} PRIVATE cluster)
endforeach(prog)
foreach(prog IN LISTS TARGETS_FOR_IO)
    target_link_libraries(${prog} PRIVATE io)
endforeach(prog)