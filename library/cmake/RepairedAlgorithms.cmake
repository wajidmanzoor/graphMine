option(GRAPHMINE_ENABLE_REPAIRED_WORKERS "Enable prepared, validated repair workers" ON)
set(GRAPHMINE_REPAIRED_WORKER_DIR "${CMAKE_CURRENT_SOURCE_DIR}/repaired-workers" CACHE PATH
    "Workers created by tools/prepare_repaired_workers.py")
find_path(GRAPHMINE_BOOST_JSON_INCLUDE_DIR boost/json.hpp REQUIRED)
add_library(graphmine_json STATIC src/core/json.cpp)
target_include_directories(graphmine_json PRIVATE ${GRAPHMINE_BOOST_JSON_INCLUDE_DIR})
set_target_properties(graphmine_json PROPERTIES EXPORT_NAME json POSITION_INDEPENDENT_CODE ON)

add_library(graphmine_repaired_algorithms src/problems/repaired_algorithms.cpp)
add_library(GraphMine::repaired_algorithms ALIAS graphmine_repaired_algorithms)
target_include_directories(graphmine_repaired_algorithms PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src ${GRAPHMINE_BOOST_JSON_INCLUDE_DIR})
target_link_libraries(graphmine_repaired_algorithms PUBLIC graphmine_core PRIVATE graphmine_json)
target_compile_features(graphmine_repaired_algorithms PUBLIC cxx_std_17)
set_target_properties(graphmine_repaired_algorithms PROPERTIES EXPORT_NAME repaired_algorithms POSITION_INDEPENDENT_CODE ON)
set(GRAPHMINE_HAS_REPAIRED_WORKERS OFF)
if(GRAPHMINE_ENABLE_REPAIRED_WORKERS AND GRAPHMINE_ENABLE_CUDA_BACKENDS AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_REPAIRED_WORKERS ON)
  foreach(name IN ITEMS acctd mbe-gpu cds kpar gamma-butterfly gpu4gst superfuser)
    set(worker "${GRAPHMINE_REPAIRED_WORKER_DIR}/graphmine-worker-${name}")
    if(EXISTS "${worker}")
      configure_file("${worker}" "${CMAKE_CURRENT_BINARY_DIR}/workers/graphmine-worker-${name}" COPYONLY)
      install(PROGRAMS "${worker}" DESTINATION "${CMAKE_INSTALL_LIBEXECDIR}/graphmine")
    else()
      message(STATUS "Repaired ${name} worker unavailable: run library/tools/prepare_repaired_workers.py")
    endif()
  endforeach()
endif()
target_compile_definitions(graphmine_repaired_algorithms PRIVATE
  GRAPHMINE_HAS_REPAIRED_WORKERS=$<BOOL:${GRAPHMINE_HAS_REPAIRED_WORKERS}>
  GRAPHMINE_WORKER_BUILD_DIR="${CMAKE_CURRENT_BINARY_DIR}/workers"
  GRAPHMINE_WORKER_INSTALL_DIR="${CMAKE_INSTALL_FULL_LIBEXECDIR}/graphmine")
install(TARGETS graphmine_repaired_algorithms graphmine_json EXPORT GraphMineTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR} LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR})
