add_library(graphmine_validated_expansion src/problems/validated_expansion.cpp)
add_library(GraphMine::validated_expansion ALIAS graphmine_validated_expansion)
target_include_directories(graphmine_validated_expansion PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_link_libraries(graphmine_validated_expansion PUBLIC graphmine_core PRIVATE graphmine_graph_motifs)
target_compile_features(graphmine_validated_expansion PUBLIC cxx_std_17)
set_target_properties(graphmine_validated_expansion PROPERTIES EXPORT_NAME validated_expansion POSITION_INDEPENDENT_CODE ON)

set(GRAPHMINE_HAS_EXPANSION_WORKERS OFF)
set(GRAPHMINE_EXPANSION_CUDA_ARCHITECTURES "89-real;89-virtual" CACHE STRING
  "CUDA architectures for the expansion workers (validated on Ada SM89)")
set(expansion_upstream "${CMAKE_CURRENT_SOURCE_DIR}/src/backends/expansion/upstream")
if(GRAPHMINE_ENABLE_VALIDATED_EXPANSION AND GRAPHMINE_CUDA_AVAILABLE)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  set(expansion_generated "${CMAKE_CURRENT_BINARY_DIR}/expansion-generated")
  file(GLOB_RECURSE expansion_inputs CONFIGURE_DEPENDS "${expansion_upstream}/*")
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_expansion_workers.py" ${expansion_inputs})
  execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/tools/prepare_expansion_workers.py" "${expansion_generated}"
    RESULT_VARIABLE expansion_prepare_result OUTPUT_VARIABLE expansion_prepare_output ERROR_VARIABLE expansion_prepare_error)
  if(NOT expansion_prepare_result EQUAL 0)
    message(FATAL_ERROR "Cannot prepare pinned expansion workers: ${expansion_prepare_error}")
  endif()
  foreach(pair IN ITEMS "ecl-scc,ecl_scc" "ecl-maxflow,ecl_flow" "hungarian-cuda,hungarian" "gdlog,gdlog_tc")
    string(REPLACE "," ";" fields "${pair}")
    list(GET fields 0 name)
    list(GET fields 1 source)
    add_executable(graphmine_worker_${source} "${expansion_generated}/${source}.cu")
    set_target_properties(graphmine_worker_${source} PROPERTIES
      OUTPUT_NAME "graphmine-worker-${name}"
      RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/workers"
      CUDA_ARCHITECTURES "${GRAPHMINE_EXPANSION_CUDA_ARCHITECTURES}"
      CUDA_STANDARD 17 CUDA_STANDARD_REQUIRED ON)
    add_dependencies(graphmine_validated_expansion graphmine_worker_${source})
    install(TARGETS graphmine_worker_${source} RUNTIME DESTINATION "${CMAKE_INSTALL_LIBEXECDIR}/graphmine")
  endforeach()
  target_include_directories(graphmine_worker_ecl_scc PRIVATE "${expansion_upstream}/ecl_scc/source")
  target_include_directories(graphmine_worker_ecl_flow PRIVATE "${expansion_upstream}/ecl_flow/lib" "${expansion_upstream}/ecl_flow/src")
  target_compile_definitions(graphmine_worker_hungarian PRIVATE _n_=64 _range_=100)
  file(GLOB gdlog_sources CONFIGURE_DEPENDS "${expansion_upstream}/gdlog/src/*.cu")
  target_sources(graphmine_worker_gdlog_tc PRIVATE ${gdlog_sources})
  target_include_directories(graphmine_worker_gdlog_tc PRIVATE "${expansion_upstream}/gdlog/include")
  set_target_properties(graphmine_worker_gdlog_tc PROPERTIES CUDA_STANDARD 20 CUDA_SEPARABLE_COMPILATION ON)
  set(GRAPHMINE_HAS_EXPANSION_WORKERS ON)
endif()
target_compile_definitions(graphmine_validated_expansion PRIVATE
  GRAPHMINE_HAS_EXPANSION_WORKERS=$<BOOL:${GRAPHMINE_HAS_EXPANSION_WORKERS}>
  GRAPHMINE_WORKER_BUILD_DIR="${CMAKE_CURRENT_BINARY_DIR}/workers"
  GRAPHMINE_WORKER_INSTALL_DIR="${CMAKE_INSTALL_FULL_LIBEXECDIR}/graphmine")
install(TARGETS graphmine_validated_expansion EXPORT GraphMineTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR} LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(DIRECTORY "${expansion_upstream}/" DESTINATION "${CMAKE_INSTALL_DATADIR}/doc/graphmine/expansion"
  FILES_MATCHING PATTERN "LICENSE*" PATTERN "PROVENANCE.json")
