cmake_minimum_required(VERSION 3.24)

project(GraphMine VERSION 0.1.0 LANGUAGES C CXX)

include(CheckLanguage)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

option(GRAPHMINE_BUILD_TESTS "Build GraphMine tests" ON)
option(GRAPHMINE_BUILD_EXAMPLES "Build GraphMine examples" ON)
option(GRAPHMINE_BUILD_CLI
       "Build the precompiled graphmine run-many command line interface" ON)
option(GRAPHMINE_ENABLE_CUDA_BACKENDS
       "Enable validated CUDA backends (individual options still apply)" ON)
option(GRAPHMINE_ENABLE_RDMCE "Build the validated RDMCE backend" ON)
option(GRAPHMINE_ENABLE_MCE_GPU "Build the validated mce-gpu backend" ON)
option(GRAPHMINE_ENABLE_G2_AIMD "Build the validated G2-AIMD backend" ON)
option(GRAPHMINE_ENABLE_KCOREGPU "Build the validated KCoreGPU backend" ON)
option(GRAPHMINE_ENABLE_CUDAMS "Build the validated CUDA-MS backend" ON)
option(GRAPHMINE_ENABLE_GPU_MAXIMUM_CLIQUE
       "Build the validated GPUMaximumClique backend" ON)
option(GRAPHMINE_ENABLE_MAXIMUM_CLIQUE_ON_GPU
       "Build the validated Maximum-Clique-on-GPU backend" ON)
option(GRAPHMINE_ENABLE_TOT "Build the validated ToT backend" ON)
option(GRAPHMINE_ENABLE_WETRIC "Build the validated WeTriC backend" ON)
option(GRAPHMINE_ENABLE_EDTC "Build the validated EDTC backend" ON)
option(GRAPHMINE_ENABLE_GRAPHSET_KCLIQUE
       "Build the validated GraphSet k-clique backend" ON)
option(GRAPHMINE_ENABLE_KCGPU "Build the validated KCGPU backend" ON)
option(GRAPHMINE_ENABLE_GAMMA_KCLIQUE
       "Build the validated GAMMA k-clique backend" ON)
option(GRAPHMINE_ENABLE_TURBOBC "Build the validated TurboBC backend" ON)
option(GRAPHMINE_ENABLE_CUMBE "Build the validated cuMBE backend" ON)
option(GRAPHMINE_ENABLE_CUQC "Build the validated cuQC backend" ON)
option(GRAPHMINE_ENABLE_GMATCH "Build the validated gMatch backend" ON)
option(GRAPHMINE_ENABLE_GRAPHMINER_MOTIF
       "Build the validated GraphMiner/G2Miner motif backend" ON)
option(GRAPHMINE_ENABLE_GRAPHSET_MOTIF
       "Build the validated GraphSet motif backend" ON)
option(GRAPHMINE_ENABLE_DUMATO_MOTIF
       "Build the validated DuMato motif backend" ON)
option(GRAPHMINE_ENABLE_EVEREST
       "Build the validated Everest temporal-motif backend" ON)
option(GRAPHMINE_ENABLE_MAYURA
       "Build the validated Mayura temporal-motif backend" ON)
option(GRAPHMINE_ENABLE_GLEIDEN
       "Build the validated gLeiden community backend" ON)
option(GRAPHMINE_ENABLE_PGGC
       "Build the validated parallel Louvain/Leiden community backends" ON)
if(NOT GRAPHMINE_ENABLE_CUDA_BACKENDS)
  set(GRAPHMINE_ENABLE_RDMCE OFF)
  set(GRAPHMINE_ENABLE_MCE_GPU OFF)
  set(GRAPHMINE_ENABLE_G2_AIMD OFF)
  set(GRAPHMINE_ENABLE_KCOREGPU OFF)
  set(GRAPHMINE_ENABLE_CUDAMS OFF)
  set(GRAPHMINE_ENABLE_GPU_MAXIMUM_CLIQUE OFF)
  set(GRAPHMINE_ENABLE_MAXIMUM_CLIQUE_ON_GPU OFF)
  set(GRAPHMINE_ENABLE_TOT OFF)
  set(GRAPHMINE_ENABLE_WETRIC OFF)
  set(GRAPHMINE_ENABLE_EDTC OFF)
  set(GRAPHMINE_ENABLE_GRAPHSET_KCLIQUE OFF)
  set(GRAPHMINE_ENABLE_KCGPU OFF)
  set(GRAPHMINE_ENABLE_GAMMA_KCLIQUE OFF)
  set(GRAPHMINE_ENABLE_TURBOBC OFF)
  set(GRAPHMINE_ENABLE_CUMBE OFF)
  set(GRAPHMINE_ENABLE_CUQC OFF)
  set(GRAPHMINE_ENABLE_GMATCH OFF)
  set(GRAPHMINE_ENABLE_GRAPHMINER_MOTIF OFF)
  set(GRAPHMINE_ENABLE_GRAPHSET_MOTIF OFF)
  set(GRAPHMINE_ENABLE_DUMATO_MOTIF OFF)
  set(GRAPHMINE_ENABLE_EVEREST OFF)
  set(GRAPHMINE_ENABLE_MAYURA OFF)
  set(GRAPHMINE_ENABLE_GLEIDEN OFF)
  set(GRAPHMINE_ENABLE_PGGC OFF)
endif()
set(GRAPHMINE_TOT_CUDA_ARCHITECTURES "70" CACHE STRING
    "CUDA architectures for ToT (tensor cores require compute capability 7.0+)")
set(GRAPHMINE_WETRIC_CUDA_ARCHITECTURES "70" CACHE STRING
    "CUDA architectures for WeTriC (block-scoped atomics require 6.0+)")
set(GRAPHMINE_EDTC_CUDA_ARCHITECTURES "native" CACHE STRING
    "CUDA architectures for EDTC")
set(GRAPHMINE_CUQC_CUDA_ARCHITECTURES "native" CACHE STRING
    "CUDA architectures for cuQC's 1024-thread expansion kernel")
set(GRAPHMINE_GMATCH_CUDA_ARCHITECTURES "native" CACHE STRING
    "CUDA architectures for gMatch")
set(GRAPHMINE_GRAPHSET_MOTIF_CUDA_ARCHITECTURES "70" CACHE STRING
    "CUDA architectures for GraphSet motif counting")
set(GRAPHMINE_DUMATO_MOTIF_CUDA_ARCHITECTURES "native" CACHE STRING
    "CUDA architectures for DuMato motif counting")
set(GRAPHMINE_MCE_GPU_CUDA_ARCHITECTURES "80-real;80-virtual" CACHE STRING
    "CUDA architectures for mce-gpu (the validated kernels target Ampere PTX)")
set(GRAPHMINE_G2_AIMD_CUDA_ARCHITECTURES "native" CACHE STRING
    "CUDA architectures for G2-AIMD")
set(GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_CUDA_ARCHITECTURES
    "86-real;86-virtual" CACHE STRING
    "CUDA architectures for Maximum-Clique-on-GPU (validated Ampere PTX path)")
set(GRAPHMINE_GPU_MAXIMUM_CLIQUE_CUDA_ARCHITECTURES
    "89-real;89-virtual" CACHE STRING
    "CUDA architectures for GPUMaximumClique (validated Ada path)")
set(GRAPHMINE_EVEREST_CUDA_ARCHITECTURES "89-real;89-virtual" CACHE STRING
    "CUDA architectures for Everest (validated Ada path)")
set(GRAPHMINE_MAYURA_CUDA_ARCHITECTURES "89-real;89-virtual" CACHE STRING
    "CUDA architectures for Mayura (validated Ada path)")
set(GRAPHMINE_GLEIDEN_CUDA_ARCHITECTURES "89-real;89-virtual" CACHE STRING
    "CUDA architectures for gLeiden (validated Ada path)")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(graphmine_core
  src/core/graph.cpp
)
add_library(GraphMine::core ALIAS graphmine_core)

target_include_directories(graphmine_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)
target_compile_features(graphmine_core PUBLIC cxx_std_17)
set_target_properties(graphmine_core PROPERTIES
  EXPORT_NAME core
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_CUDA_AVAILABLE OFF)
if(GRAPHMINE_ENABLE_RDMCE OR GRAPHMINE_ENABLE_MCE_GPU OR
   GRAPHMINE_ENABLE_G2_AIMD OR
   GRAPHMINE_ENABLE_KCOREGPU OR
   GRAPHMINE_ENABLE_CUDAMS OR GRAPHMINE_ENABLE_GPU_MAXIMUM_CLIQUE OR
   GRAPHMINE_ENABLE_MAXIMUM_CLIQUE_ON_GPU OR GRAPHMINE_ENABLE_TOT OR
   GRAPHMINE_ENABLE_WETRIC OR GRAPHMINE_ENABLE_EDTC OR
   GRAPHMINE_ENABLE_GRAPHSET_KCLIQUE OR
   GRAPHMINE_ENABLE_KCGPU OR GRAPHMINE_ENABLE_GAMMA_KCLIQUE OR
   GRAPHMINE_ENABLE_TURBOBC OR GRAPHMINE_ENABLE_CUMBE OR
   GRAPHMINE_ENABLE_CUQC OR GRAPHMINE_ENABLE_GMATCH OR
   GRAPHMINE_ENABLE_GRAPHMINER_MOTIF OR GRAPHMINE_ENABLE_GRAPHSET_MOTIF OR
   GRAPHMINE_ENABLE_DUMATO_MOTIF OR GRAPHMINE_ENABLE_EVEREST OR
   GRAPHMINE_ENABLE_MAYURA OR GRAPHMINE_ENABLE_GLEIDEN OR
   GRAPHMINE_ENABLE_PGGC)
  check_language(CUDA)
  if(CMAKE_CUDA_COMPILER)
    enable_language(CUDA)
    find_package(CUDAToolkit REQUIRED)
    if(NOT TARGET CUDA::cudadevrt)
      find_library(GRAPHMINE_CUDADEVRT_LIBRARY NAMES cudadevrt
        HINTS ${CUDAToolkit_LIBRARY_DIR}
        REQUIRED
      )
      add_library(CUDA::cudadevrt STATIC IMPORTED)
      set_target_properties(CUDA::cudadevrt PROPERTIES
        IMPORTED_LOCATION "${GRAPHMINE_CUDADEVRT_LIBRARY}"
      )
    endif()
    if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
      set(CMAKE_CUDA_ARCHITECTURES native)
    endif()
    set(GRAPHMINE_CUDA_AVAILABLE ON)
  else()
    message(WARNING "CUDA was not found; CUDA backends will not be built")
  endif()
endif()

set(GRAPHMINE_HAS_RDMCE OFF)
if(GRAPHMINE_ENABLE_RDMCE AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_RDMCE ON)
endif()

set(GRAPHMINE_HAS_MCE_GPU OFF)
if(GRAPHMINE_ENABLE_MCE_GPU AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_MCE_GPU ON)
endif()

set(GRAPHMINE_HAS_G2_AIMD OFF)
if(GRAPHMINE_ENABLE_G2_AIMD AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_G2_AIMD ON)
endif()

set(GRAPHMINE_HAS_KCOREGPU OFF)
if(GRAPHMINE_ENABLE_KCOREGPU AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_KCOREGPU ON)
endif()

set(GRAPHMINE_MCE_GPU_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/01_maximal_clique_enumeration/papers/2023_parallelizing_mce/code")

if(GRAPHMINE_HAS_MCE_GPU)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_mce_gpu STATIC
    src/backends/maximal_cliques/mce_gpu_backend.cu
  )
  target_include_directories(graphmine_backend_mce_gpu
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_MCE_GPU_ROOT}/include
      ${GRAPHMINE_MCE_GPU_ROOT}/mce
  )
  target_link_libraries(graphmine_backend_mce_gpu
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_definitions(graphmine_backend_mce_gpu
    PRIVATE GRAPHMINE_LIBRARY
  )
  target_compile_features(graphmine_backend_mce_gpu PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_mce_gpu PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_MCE_GPU_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_mce_gpu STATIC
    src/backends/maximal_cliques/mce_gpu_backend_stub.cpp
  )
  target_include_directories(graphmine_backend_mce_gpu
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_mce_gpu PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_mce_gpu PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_G2_AIMD_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/01_maximal_clique_enumeration/papers/2024_g2_aimd/code")

if(GRAPHMINE_HAS_G2_AIMD)
  find_package(OpenMP REQUIRED)
  find_package(Threads REQUIRED)
  set(GRAPHMINE_G2_AIMD_BLISS_SOURCES
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/defs.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/graph.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/partition.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/orbit.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/uintseqhash.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/heap.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/timer.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/utils.cc
    ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73/bliss/bliss_C.cc
  )
  add_library(graphmine_backend_g2_aimd STATIC
    src/backends/maximal_cliques/g2_aimd_backend.cu
    ${GRAPHMINE_G2_AIMD_BLISS_SOURCES}
  )
  target_include_directories(graphmine_backend_g2_aimd
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_G2_AIMD_ROOT}
      ${GRAPHMINE_G2_AIMD_ROOT}/third_party/bliss-0.73
  )
  target_link_libraries(graphmine_backend_g2_aimd
    PUBLIC graphmine_core
    PRIVATE
      CUDA::cudart
      CUDA::cudadevrt
      OpenMP::OpenMP_CXX
      Threads::Threads
  )
  target_compile_definitions(graphmine_backend_g2_aimd
    PRIVATE GRAPHMINE_LIBRARY
  )
  target_compile_options(graphmine_backend_g2_aimd PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--maxrregcount=64>
  )
  target_compile_features(graphmine_backend_g2_aimd PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_g2_aimd PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_G2_AIMD_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_g2_aimd STATIC
    src/backends/maximal_cliques/g2_aimd_backend_stub.cpp
  )
  target_include_directories(graphmine_backend_g2_aimd
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_g2_aimd PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_g2_aimd PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_HAS_CUDAMS OFF)
if(GRAPHMINE_ENABLE_CUDAMS AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_CUDAMS ON)
endif()

set(GRAPHMINE_HAS_GPU_MAXIMUM_CLIQUE OFF)
if(GRAPHMINE_ENABLE_GPU_MAXIMUM_CLIQUE AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GPU_MAXIMUM_CLIQUE ON)
endif()

set(GRAPHMINE_HAS_MAXIMUM_CLIQUE_ON_GPU OFF)
if(GRAPHMINE_ENABLE_MAXIMUM_CLIQUE_ON_GPU AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_MAXIMUM_CLIQUE_ON_GPU ON)
endif()

set(GRAPHMINE_HAS_TOT OFF)
if(GRAPHMINE_ENABLE_TOT AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_TOT ON)
endif()

set(GRAPHMINE_HAS_WETRIC OFF)
if(GRAPHMINE_ENABLE_WETRIC AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_WETRIC ON)
endif()

set(GRAPHMINE_HAS_EDTC OFF)
if(GRAPHMINE_ENABLE_EDTC AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_EDTC ON)
endif()

set(GRAPHMINE_HAS_GRAPHSET_KCLIQUE OFF)
if(GRAPHMINE_ENABLE_GRAPHSET_KCLIQUE AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GRAPHSET_KCLIQUE ON)
endif()

set(GRAPHMINE_HAS_KCGPU OFF)
if(GRAPHMINE_ENABLE_KCGPU AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_KCGPU ON)
endif()

set(GRAPHMINE_HAS_GAMMA_KCLIQUE OFF)
if(GRAPHMINE_ENABLE_GAMMA_KCLIQUE AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GAMMA_KCLIQUE ON)
endif()

set(GRAPHMINE_HAS_TURBOBC OFF)
if(GRAPHMINE_ENABLE_TURBOBC AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_TURBOBC ON)
endif()

set(GRAPHMINE_HAS_CUMBE OFF)
if(GRAPHMINE_ENABLE_CUMBE AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_CUMBE ON)
endif()

set(GRAPHMINE_HAS_CUQC OFF)
if(GRAPHMINE_ENABLE_CUQC AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_CUQC ON)
endif()

set(GRAPHMINE_HAS_GMATCH OFF)
if(GRAPHMINE_ENABLE_GMATCH AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GMATCH ON)
endif()

set(GRAPHMINE_HAS_GRAPHMINER_MOTIF OFF)
if(GRAPHMINE_ENABLE_GRAPHMINER_MOTIF AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GRAPHMINER_MOTIF ON)
endif()

set(GRAPHMINE_HAS_GRAPHSET_MOTIF OFF)
if(GRAPHMINE_ENABLE_GRAPHSET_MOTIF AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GRAPHSET_MOTIF ON)
endif()

set(GRAPHMINE_HAS_DUMATO_MOTIF OFF)
if(GRAPHMINE_ENABLE_DUMATO_MOTIF AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_DUMATO_MOTIF ON)
endif()

set(GRAPHMINE_HAS_EVEREST OFF)
if(GRAPHMINE_ENABLE_EVEREST AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_EVEREST ON)
endif()

set(GRAPHMINE_HAS_MAYURA OFF)
if(GRAPHMINE_ENABLE_MAYURA AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_MAYURA ON)
endif()

set(GRAPHMINE_HAS_GLEIDEN OFF)
if(GRAPHMINE_ENABLE_GLEIDEN AND GRAPHMINE_CUDA_AVAILABLE)
  set(GRAPHMINE_HAS_GLEIDEN ON)
endif()

set(GRAPHMINE_HAS_PGGC OFF)
if(GRAPHMINE_ENABLE_PGGC AND GRAPHMINE_CUDA_AVAILABLE)
  find_package(KokkosKernels QUIET)
  if(TARGET Kokkos::kokkos AND TARGET Kokkos::kokkoskernels)
    set(GRAPHMINE_HAS_PGGC ON)
  else()
    message(WARNING
      "Kokkos/KokkosKernels were not found; parallel Louvain/Leiden "
      "backends will not be built")
  endif()
endif()

set(GRAPHMINE_RDMCE_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/01_maximal_clique_enumeration/papers/2026_rdmce/code/RDMCE")

if(GRAPHMINE_HAS_RDMCE)
  add_library(graphmine_backend_rdmce STATIC
    src/backends/maximal_cliques/rdmce_backend.cu
    ${GRAPHMINE_RDMCE_ROOT}/src/common.cu
    ${GRAPHMINE_RDMCE_ROOT}/src/context_gpu.cu
    ${GRAPHMINE_RDMCE_ROOT}/src/graph_gpu.cu
    ${GRAPHMINE_RDMCE_ROOT}/src/graph.cc
  )
  target_include_directories(graphmine_backend_rdmce
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_RDMCE_ROOT}/include
      ${GRAPHMINE_RDMCE_ROOT}/src
  )
  target_link_libraries(graphmine_backend_rdmce
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  # Upstream artifacts commonly define global Graph/Timer-style symbols. Give
  # each backend a private symbol prefix so independently valid components can
  # coexist in one application without ODR/linker collisions.
  target_compile_definitions(graphmine_backend_rdmce
    PRIVATE Graph=GraphMineRdmceGraph
  )
  target_compile_features(graphmine_backend_rdmce PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_rdmce PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_rdmce STATIC
    src/backends/maximal_cliques/rdmce_backend_stub.cpp
  )
  target_include_directories(graphmine_backend_rdmce
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_rdmce PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_rdmce PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_KCOREGPU_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/07_k_core_decomposition/papers/2023_accelerating_k_core_gpu/code")

if(GRAPHMINE_HAS_KCOREGPU)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_kcoregpu STATIC
    src/backends/kcore_gpu.cu
    ${GRAPHMINE_KCOREGPU_ROOT}/src/gpu_memory_allocation.cu
    ${GRAPHMINE_KCOREGPU_ROOT}/src/graph.cpp
  )
  target_include_directories(graphmine_backend_kcoregpu
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_KCOREGPU_ROOT}/inc
      ${GRAPHMINE_KCOREGPU_ROOT}/src
  )
  target_link_libraries(graphmine_backend_kcoregpu
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_definitions(graphmine_backend_kcoregpu
    PRIVATE Graph=GraphMineKCoreGraph
  )
  target_compile_features(graphmine_backend_kcoregpu PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_kcoregpu PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_kcoregpu STATIC
    src/backends/kcore_gpu_stub.cpp
  )
  target_include_directories(graphmine_backend_kcoregpu
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_kcoregpu PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_kcoregpu PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_k_core
  src/problems/k_core.cpp
)
add_library(GraphMine::k_core ALIAS graphmine_k_core)
target_include_directories(graphmine_k_core
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_k_core
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_kcoregpu
)
target_compile_features(graphmine_k_core PUBLIC cxx_std_17)
set_target_properties(graphmine_k_core PROPERTIES
  EXPORT_NAME k_core
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_CUDAMS_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/02_maximum_clique/papers/2019_maximum_clique_cuda/code")

if(GRAPHMINE_HAS_CUDAMS)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_cuda_ms STATIC
    src/backends/cuda_ms.cpp
    ${GRAPHMINE_CUDAMS_ROOT}/arrays.c
    ${GRAPHMINE_CUDAMS_ROOT}/bitops.c
    ${GRAPHMINE_CUDAMS_ROOT}/random.c
    ${GRAPHMINE_CUDAMS_ROOT}/motzkin.c
    ${GRAPHMINE_CUDAMS_ROOT}/motzkin_cpu.c
    ${GRAPHMINE_CUDAMS_ROOT}/motzkin_cuda.cu
  )
  target_include_directories(graphmine_backend_cuda_ms
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_CUDAMS_ROOT}
      ${CUDAToolkit_INCLUDE_DIRS}
  )
  target_link_libraries(graphmine_backend_cuda_ms
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX m
  )
  target_compile_features(graphmine_backend_cuda_ms PUBLIC cxx_std_17)
  target_compile_options(graphmine_backend_cuda_ms PRIVATE
    $<$<COMPILE_LANGUAGE:C>:-ffast-math;-fopenmp>
  )
  set_target_properties(graphmine_backend_cuda_ms PROPERTIES
    C_STANDARD 99
    C_STANDARD_REQUIRED ON
    C_EXTENSIONS ON
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_cuda_ms STATIC
    src/backends/cuda_ms_stub.cpp
  )
  target_include_directories(graphmine_backend_cuda_ms
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_cuda_ms PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_cuda_ms PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/02_maximum_clique/papers/2024_maximum_clique_many_core_gpu/code")

if(GRAPHMINE_HAS_MAXIMUM_CLIQUE_ON_GPU)
  add_library(graphmine_backend_maximum_clique_on_gpu STATIC
    src/backends/maximum_clique_on_gpu_backend.cu
  )
  target_include_directories(graphmine_backend_maximum_clique_on_gpu
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_ROOT}/include
      ${GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_ROOT}/mcp
  )
  target_link_libraries(graphmine_backend_maximum_clique_on_gpu
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_definitions(graphmine_backend_maximum_clique_on_gpu
    PRIVATE GRAPHMINE_LIBRARY
  )
  target_compile_features(graphmine_backend_maximum_clique_on_gpu
    PUBLIC cxx_std_17
  )
  set_target_properties(graphmine_backend_maximum_clique_on_gpu PROPERTIES
    CUDA_STANDARD 20
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES
      "${GRAPHMINE_MAXIMUM_CLIQUE_ON_GPU_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_maximum_clique_on_gpu STATIC
    src/backends/maximum_clique_on_gpu_stub.cpp
  )
  target_include_directories(graphmine_backend_maximum_clique_on_gpu
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_maximum_clique_on_gpu
    PUBLIC graphmine_core
  )
  set_target_properties(graphmine_backend_maximum_clique_on_gpu PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/02_maximum_clique/papers/2023_maximum_clique_enumeration_gpu/code")

if(GRAPHMINE_HAS_GPU_MAXIMUM_CLIQUE)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_gpu_maximum_clique STATIC
    src/backends/gpu_maximum_clique_backend.cu
    ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/cliqueMerging.cu
    ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock/gunrock/util/str_to_T.cu
    ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock/gunrock/util/test_utils.cu
    ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock/gunrock/util/error_utils.cu
  )
  target_include_directories(graphmine_backend_gpu_maximum_clique
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}
      ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock
      ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock/externals/moderngpu/src
      ${GRAPHMINE_GPU_MAXIMUM_CLIQUE_ROOT}/gunrock/externals/rapidjson/include
  )
  target_link_libraries(graphmine_backend_gpu_maximum_clique
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_definitions(graphmine_backend_gpu_maximum_clique PRIVATE
    GRAPHMINE_LIBRARY
    GIT_SHA1="2365400c7b4a172afdbf60c6c559a49e0567caac"
    GUNROCK_GIT_SHA1="9aad94e8d9992a083e939c198337d084322226f3"
  )
  target_compile_options(graphmine_backend_gpu_maximum_clique PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--extended-lambda;--expt-relaxed-constexpr>
  )
  target_compile_features(graphmine_backend_gpu_maximum_clique PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_gpu_maximum_clique PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES
      "${GRAPHMINE_GPU_MAXIMUM_CLIQUE_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_gpu_maximum_clique STATIC
    src/backends/gpu_maximum_clique_stub.cpp
  )
  target_include_directories(graphmine_backend_gpu_maximum_clique
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_gpu_maximum_clique
    PUBLIC graphmine_core
  )
  set_target_properties(graphmine_backend_gpu_maximum_clique PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_maximum_clique
  src/problems/maximum_clique.cpp
)
add_library(GraphMine::maximum_clique ALIAS graphmine_maximum_clique)
target_include_directories(graphmine_maximum_clique
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_maximum_clique
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_cuda_ms graphmine_backend_gpu_maximum_clique
          graphmine_backend_maximum_clique_on_gpu
)
target_compile_features(graphmine_maximum_clique PUBLIC cxx_std_17)
set_target_properties(graphmine_maximum_clique PROPERTIES
  EXPORT_NAME maximum_clique
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_TOT_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/10_triangle_counting_listing/papers/2025_tot_tensor_cores/code")

if(GRAPHMINE_HAS_TOT)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_tot STATIC
    src/backends/tot.cu
  )
  target_include_directories(graphmine_backend_tot
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_TOT_ROOT}/tot
  )
  target_link_libraries(graphmine_backend_tot
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_options(graphmine_backend_tot PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--extended-lambda;--expt-relaxed-constexpr>
  )
  target_compile_features(graphmine_backend_tot PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_tot PROPERTIES
    # The pinned ToT headers use std::string::ends_with internally. This is
    # isolated to the backend; GraphMine's public API remains C++17.
    CUDA_STANDARD 20
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_TOT_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_tot STATIC src/backends/tot_stub.cpp)
  target_include_directories(graphmine_backend_tot
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_tot PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_tot PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_WETRIC_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/10_triangle_counting_listing/papers/2025_wetric/code")

if(GRAPHMINE_HAS_WETRIC)
  add_library(graphmine_backend_wetric STATIC src/backends/wetric.cu)
  target_include_directories(graphmine_backend_wetric
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_WETRIC_ROOT}
  )
  target_link_libraries(graphmine_backend_wetric
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_features(graphmine_backend_wetric PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_wetric PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_WETRIC_CUDA_ARCHITECTURES}"
    # The complete WeTriC artifact is included in one translation unit.  A
    # self-contained fat binary avoids duplicate cudadevrt registration
    # symbols when several independently device-linked static backends are
    # consumed by one executable.
    CUDA_SEPARABLE_COMPILATION OFF
    CUDA_RESOLVE_DEVICE_SYMBOLS OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_wetric STATIC src/backends/wetric_stub.cpp)
  target_include_directories(graphmine_backend_wetric
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_wetric PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_wetric PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_triangle_counting
  src/problems/triangle_counting.cpp
)
add_library(GraphMine::triangle_counting ALIAS graphmine_triangle_counting)
target_include_directories(graphmine_triangle_counting
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_triangle_counting
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_tot graphmine_backend_wetric
)
target_compile_features(graphmine_triangle_counting PUBLIC cxx_std_17)
set_target_properties(graphmine_triangle_counting PROPERTIES
  EXPORT_NAME triangle_counting
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_EDTC_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/10_triangle_counting_listing/papers/2026_edtc/code")

if(GRAPHMINE_HAS_EDTC)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_edtc STATIC
    src/backends/edtc.cu
    ${GRAPHMINE_EDTC_ROOT}/tricount.cu
  )
  target_include_directories(graphmine_backend_edtc
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_EDTC_ROOT}
  )
  target_link_libraries(graphmine_backend_edtc
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_definitions(graphmine_backend_edtc PRIVATE
    GRAPHMINE_LIBRARY
    OFFSET_32
    tricount=graphmine_edtc_tricount
    MyPow=graphmine_edtc_pow
  )
  set_source_files_properties(${GRAPHMINE_EDTC_ROOT}/tricount.cu PROPERTIES
    COMPILE_DEFINITIONS
      "Graph=GraphMineEdtcGraph;Edge=GraphMineEdtcEdge;UpdateEdge=GraphMineEdtcUpdateEdge;gpuAssert=graphmine_edtc_gpu_assert;Generate_InitD=graphmine_edtc_generate_init_d;Generate_InitA=graphmine_edtc_generate_init_a;Generate_bucket_count=graphmine_edtc_generate_bucket_count;Generate_hash=graphmine_edtc_generate_hash;Generate_limit=graphmine_edtc_generate_limit;Generate_updates_degree=graphmine_edtc_generate_updates_degree;Split_hash=graphmine_edtc_split_hash;Split_updates=graphmine_edtc_split_updates;TC_kernel_large=graphmine_edtc_kernel_large;TC_kernel_small=graphmine_edtc_kernel_small;TC_kernel=graphmine_edtc_kernel"
  )
  target_compile_features(graphmine_backend_edtc PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_edtc PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_EDTC_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_edtc STATIC src/backends/edtc_stub.cpp)
  target_include_directories(graphmine_backend_edtc
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_edtc PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_edtc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_dynamic_triangle_counting
  src/problems/dynamic_triangle_counting.cpp
)
add_library(GraphMine::dynamic_triangle_counting ALIAS
            graphmine_dynamic_triangle_counting)
target_include_directories(graphmine_dynamic_triangle_counting
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_dynamic_triangle_counting
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_edtc
)
target_compile_features(graphmine_dynamic_triangle_counting PUBLIC cxx_std_17)
set_target_properties(graphmine_dynamic_triangle_counting PROPERTIES
  EXPORT_NAME dynamic_triangle_counting
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_GRAPHSET_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/03_k_clique_counting_enumeration/papers/2023_graphset/code")

if(GRAPHMINE_HAS_GRAPHSET_KCLIQUE)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_graphset_kclique STATIC
    src/backends/graphset_kclique.cu
    ${GRAPHMINE_GRAPHSET_ROOT}/gpu/gpu_kclique.cu
  )
  target_include_directories(graphmine_backend_graphset_kclique
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GRAPHSET_ROOT}
      ${GRAPHMINE_GRAPHSET_ROOT}/include
      ${GRAPHMINE_GRAPHSET_ROOT}/gpu
  )
  target_compile_definitions(graphmine_backend_graphset_kclique PRIVATE
    GRAPHMINE_LIBRARY
    k_clique_counting=graphmine_graphset_k_clique_counting
    dev_sum=graphmine_graphset_kclique_dev_sum
    start_ptr=graphmine_graphset_kclique_start_ptr
  )
  target_compile_options(graphmine_backend_graphset_kclique PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--maxrregcount=64>
  )
  target_link_libraries(graphmine_backend_graphset_kclique
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_features(graphmine_backend_graphset_kclique PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_graphset_kclique PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_graphset_kclique STATIC
    src/backends/graphset_kclique_stub.cpp
  )
  target_include_directories(graphmine_backend_graphset_kclique
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_graphset_kclique
    PUBLIC graphmine_core
  )
  set_target_properties(graphmine_backend_graphset_kclique PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_KCGPU_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/03_k_clique_counting_enumeration/papers/2022_parallel_k_clique_counting/code")

if(GRAPHMINE_HAS_KCGPU)
  add_library(graphmine_backend_kcgpu STATIC src/backends/kcgpu.cu)
  target_include_directories(graphmine_backend_kcgpu
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_KCGPU_ROOT}/include
      ${GRAPHMINE_KCGPU_ROOT}/kcore
      ${GRAPHMINE_KCGPU_ROOT}/kclique
  )
  target_compile_definitions(graphmine_backend_kcgpu PRIVATE
    CUDA
    NOT_IMPL
    GRAPHMINE_LIBRARY
    THRUST_IGNORE_CUB_VERSION_CHECK
    KCCOUNT=GraphMineKcgpuKcCount
    MAXDEG=GraphMineKcgpuMaxDegree
    PARTSIZE=GraphMineKcgpuPartSize
    NUMPART=GraphMineKcgpuNumPart
    MAXLEVEL=GraphMineKcgpuMaxLevel
    NUMDIVS=GraphMineKcgpuNumDivs
    CBPSM=GraphMineKcgpuBlocksPerSm
  )
  target_link_libraries(graphmine_backend_kcgpu
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart
  )
  target_compile_features(graphmine_backend_kcgpu PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_kcgpu PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION OFF
    CUDA_RESOLVE_DEVICE_SYMBOLS OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_kcgpu STATIC src/backends/kcgpu_stub.cpp)
  target_include_directories(graphmine_backend_kcgpu
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_kcgpu PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_kcgpu PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_GAMMA_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/03_k_clique_counting_enumeration/papers/2024_gamma/code")

if(GRAPHMINE_HAS_GAMMA_KCLIQUE)
  add_library(graphmine_backend_gamma_kclique STATIC
    src/backends/gamma_kclique.cu
    ${GRAPHMINE_GAMMA_ROOT}/log.cpp
  )
  target_include_directories(graphmine_backend_gamma_kclique
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GAMMA_ROOT}
  )
  target_compile_definitions(graphmine_backend_gamma_kclique PRIVATE
    GRAPHMINE_LIBRARY
    CSRGraph=GraphMineGammaCSRGraph
    EmbeddingList=GraphMineGammaEmbeddingList
    access_mode_controller=GraphMineGammaAccessController
    expand_constraint=GraphMineGammaExpandConstraint
    Clock=GraphMineGammaClock
    Edge=GraphMineGammaEdge
    is_valid=GraphMineGammaIsValid
    all_vid=graphmine_gamma_all_vid
    all_idx=graphmine_gamma_all_idx
    all_einfo=graphmine_gamma_all_einfo
    mem_head=graphmine_gamma_mem_head
    set_validation=graphmine_gamma_set_validation
    expand=graphmine_gamma_expand
    expand_in_batch=graphmine_gamma_expand_in_batch
    expand_dynamic=graphmine_gamma_expand_dynamic
    expand_dynamic_by_edge=graphmine_gamma_expand_dynamic_by_edge
    emb_compaction=graphmine_gamma_emb_compaction
    check_valid_ftr_num=graphmine_gamma_check_valid_ftr_num
    memory_page_split_identify=graphmine_gamma_memory_page_split_identify
    set_access_mode=graphmine_gamma_set_access_mode
    accumulate_vertex_access_time=graphmine_gamma_accumulate_access
    count_total_access_nbr=graphmine_gamma_count_total_access
    extend_alloc=graphmine_gamma_extend_alloc
    extend_insert_indevice=graphmine_gamma_extend_insert
    extend_indevice=graphmine_gamma_extend_indevice
    expand_kernel=graphmine_gamma_expand_kernel
    check_emb_validation=graphmine_gamma_check_emb_validation
    expand_kernel_by_edge=graphmine_gamma_expand_kernel_by_edge
    log_set_udata=graphmine_gamma_log_set_udata
    log_set_lock=graphmine_gamma_log_set_lock
    log_set_fp=graphmine_gamma_log_set_fp
    log_set_level=graphmine_gamma_log_set_level
    log_set_quiet=graphmine_gamma_log_set_quiet
    log_log=graphmine_gamma_log_log
  )
  target_link_libraries(graphmine_backend_gamma_kclique
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart
  )
  target_compile_features(graphmine_backend_gamma_kclique PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_gamma_kclique PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION OFF
    CUDA_RESOLVE_DEVICE_SYMBOLS OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_gamma_kclique STATIC
    src/backends/gamma_kclique_stub.cpp
  )
  target_include_directories(graphmine_backend_gamma_kclique
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_gamma_kclique PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_gamma_kclique PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_k_cliques src/problems/k_cliques.cpp)
add_library(GraphMine::k_cliques ALIAS graphmine_k_cliques)
target_include_directories(graphmine_k_cliques
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_k_cliques
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_graphset_kclique graphmine_backend_kcgpu
          graphmine_backend_gamma_kclique
)
target_compile_features(graphmine_k_cliques PUBLIC cxx_std_17)
set_target_properties(graphmine_k_cliques PROPERTIES
  EXPORT_NAME k_cliques
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_TURBOBC_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/18_centrality_influential_node_mining/papers/2021_turbobc/code/TurboBC")

if(GRAPHMINE_HAS_TURBOBC)
  add_library(graphmine_backend_turbobc STATIC
    src/backends/turbobc.cu
    ${GRAPHMINE_TURBOBC_ROOT}/bcgpugcsc_sc.cu
  )
  target_include_directories(graphmine_backend_turbobc
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_TURBOBC_ROOT}
  )
  target_compile_definitions(graphmine_backend_turbobc PRIVATE
    GRAPHMINE_LIBRARY
    bc_gpu_ug_csc_sc=graphmine_turbobc_compute
    spMVBFSscKernel=graphmine_turbobc_spmv_bfs_kernel
    spMVBCscKernel=graphmine_turbobc_spmv_bc_kernel
    bfsFunctionsKernel=graphmine_turbobc_bfs_functions_kernel
    deltaUKernel=graphmine_turbobc_delta_u_kernel
    deltaKernel=graphmine_turbobc_delta_kernel
    bcKernel=graphmine_turbobc_accumulate_kernel
  )
  target_link_libraries(graphmine_backend_turbobc
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart
  )
  target_compile_features(graphmine_backend_turbobc PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_turbobc PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_turbobc STATIC
    src/backends/turbobc_stub.cpp
  )
  target_include_directories(graphmine_backend_turbobc
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_turbobc PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_turbobc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_betweenness_centrality
  src/problems/betweenness_centrality.cpp
)
add_library(GraphMine::betweenness_centrality ALIAS
  graphmine_betweenness_centrality)
target_include_directories(graphmine_betweenness_centrality
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_betweenness_centrality
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_turbobc
)
target_compile_features(graphmine_betweenness_centrality PUBLIC cxx_std_17)
set_target_properties(graphmine_betweenness_centrality PROPERTIES
  EXPORT_NAME betweenness_centrality
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_CUMBE_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/09_maximal_biclique_enumeration/papers/2024_cumbe/code")

if(GRAPHMINE_HAS_CUMBE)
  add_library(graphmine_backend_cumbe STATIC src/backends/cumbe.cu)
  target_include_directories(graphmine_backend_cumbe
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_CUMBE_ROOT}
  )
  target_compile_definitions(graphmine_backend_cumbe PRIVATE
    GRAPHMINE_LIBRARY
    P_ptr=graphmine_cumbe_p_ptr
    done=graphmine_cumbe_done
    my_memset_order=graphmine_cumbe_memset_order
    my_memset_sort=graphmine_cumbe_memset_sort
    cmp=graphmine_cumbe_degree_compare
    CUDA_GLOBAL_EXTENSION=graphmine_cumbe_global_extension
    CUDA_MBE_cuMBE=graphmine_cumbe_kernel
  )
  target_link_libraries(graphmine_backend_cumbe
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart
  )
  target_compile_features(graphmine_backend_cumbe PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_cumbe PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_cumbe STATIC src/backends/cumbe_stub.cpp)
  target_include_directories(graphmine_backend_cumbe
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_cumbe PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_cumbe PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_maximal_bicliques
  src/problems/maximal_bicliques.cpp
)
add_library(GraphMine::maximal_bicliques ALIAS graphmine_maximal_bicliques)
target_include_directories(graphmine_maximal_bicliques
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_maximal_bicliques
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_cumbe
)
target_compile_features(graphmine_maximal_bicliques PUBLIC cxx_std_17)
set_target_properties(graphmine_maximal_bicliques PROPERTIES
  EXPORT_NAME maximal_bicliques
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_CUQC_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/04_quasi_clique_mining/papers/2025_cuqc/code")

if(GRAPHMINE_HAS_CUQC)
  add_library(graphmine_backend_cuqc STATIC
    ${GRAPHMINE_CUQC_ROOT}/main.cu
  )
  target_include_directories(graphmine_backend_cuqc
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_CUQC_ROOT}
  )
  # These are the exact bounded workspace dimensions used for correctness
  # validation. They preserve cuQC's static-buffer design without imposing its
  # 80-GB benchmark defaults on every library consumer.
  target_compile_definitions(graphmine_backend_cuqc PRIVATE
    GRAPHMINE_LIBRARY
    BLOCK_SIZE=256
    NUM_OF_BLOCKS=32
    TASKS_SIZE=2500000
    TASKS_PER_WARP=32
    BUFFER_SIZE=6250000
    BUFFER_OFFSET_SIZE=500000
    CLIQUES_SIZE=200000
    CLIQUES_OFFSET_SIZE=500000
    WCLIQUES_SIZE=4096
    WCLIQUES_OFFSET_SIZE=512
    WTASKS_SIZE=10240
    WTASKS_OFFSET_SIZE=512
    WVERTICES_SIZE=1280
  )
  target_link_libraries(graphmine_backend_cuqc
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart
  )
  target_compile_features(graphmine_backend_cuqc PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_cuqc PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_CUQC_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION OFF
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_cuqc STATIC src/backends/cuqc_stub.cpp)
  target_include_directories(graphmine_backend_cuqc
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_cuqc PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_cuqc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_quasi_cliques src/problems/quasi_cliques.cpp)
add_library(GraphMine::quasi_cliques ALIAS graphmine_quasi_cliques)
target_include_directories(graphmine_quasi_cliques
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_quasi_cliques
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_cuqc
)
target_compile_features(graphmine_quasi_cliques PUBLIC cxx_std_17)
set_target_properties(graphmine_quasi_cliques PROPERTIES
  EXPORT_NAME quasi_cliques
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_GMATCH_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/13_subgraph_isomorphism/papers/2026_gmatch/code/bitmap")

if(GRAPHMINE_HAS_GMATCH)
  add_library(graphmine_backend_gmatch STATIC
    src/backends/gmatch.cu
    ${GRAPHMINE_GMATCH_ROOT}/graph.cu
    ${GRAPHMINE_GMATCH_ROOT}/candidate.cu
    ${GRAPHMINE_GMATCH_ROOT}/join_bfs.cu
    ${GRAPHMINE_GMATCH_ROOT}/join_bfs_dfs.cu
  )
  target_include_directories(graphmine_backend_gmatch
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GMATCH_ROOT}
  )
  # Isolate the artifact's generic global C++/CUDA symbols so gMatch can be
  # linked beside the other independently authored research backends.
  target_compile_definitions(graphmine_backend_gmatch PRIVATE
    GRAPHMINE_LIBRARY
    THRUST_IGNORE_DEPRECATED_CPP_DIALECT
  )
  set(GRAPHMINE_GMATCH_SYMBOL_DEFINITIONS
    Graph=GraphMineGmatchGraph
    Graph_GPU=GraphMineGmatchGraphGpu
    candidate_graph=GraphMineGmatchCandidateGraph
    candidate_graph_GPU=GraphMineGmatchCandidateGraphGpu
    MemPool=GraphMineGmatchMemPool
    MemManager=GraphMineGmatchMemManager
    partial_props=GraphMineGmatchPartialProps
    idle_queue=GraphMineGmatchIdleQueue
    stk_elem_fixed=GraphMineGmatchStackFixed
    stk_elem_cand=GraphMineGmatchStackCandidates
    stk_elem=GraphMineGmatchStackElement
    const_edge_offset=graphmine_gmatch_const_edge_offset
    bitmap_offset=graphmine_gmatch_bitmap_offset
  )
  set_property(SOURCE
    ${GRAPHMINE_GMATCH_ROOT}/graph.cu
    ${GRAPHMINE_GMATCH_ROOT}/candidate.cu
    ${GRAPHMINE_GMATCH_ROOT}/join_bfs.cu
    ${GRAPHMINE_GMATCH_ROOT}/join_bfs_dfs.cu
    APPEND PROPERTY COMPILE_DEFINITIONS
      ${GRAPHMINE_GMATCH_SYMBOL_DEFINITIONS}
  )
  target_link_libraries(graphmine_backend_gmatch
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_features(graphmine_backend_gmatch PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_gmatch PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_GMATCH_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_gmatch STATIC src/backends/gmatch_stub.cpp)
  target_include_directories(graphmine_backend_gmatch
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_gmatch PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_gmatch PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_subgraph_isomorphism
  src/problems/subgraph_isomorphism.cpp
)
add_library(GraphMine::subgraph_isomorphism ALIAS
  graphmine_subgraph_isomorphism)
target_include_directories(graphmine_subgraph_isomorphism
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_subgraph_isomorphism
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_gmatch
)
target_compile_features(graphmine_subgraph_isomorphism PUBLIC cxx_std_17)
set_target_properties(graphmine_subgraph_isomorphism PROPERTIES
  EXPORT_NAME subgraph_isomorphism
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_G2MINER_MOTIF_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/11_graph_motif_counting/papers/2022_g2miner/code")

if(GRAPHMINE_HAS_GRAPHMINER_MOTIF)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_graphminer_motif STATIC
    src/backends/g2miner_motif.cu
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/motif/gpu_base.cu
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/common/graph.cc
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/common/VertexSet.cc
  )
  target_include_directories(graphmine_backend_graphminer_motif
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_G2MINER_MOTIF_ROOT}/include
      ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/motif
      ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/motif/gpu_kernels
  )
  target_compile_definitions(graphmine_backend_graphminer_motif PRIVATE
    GRAPHMINE_LIBRARY
    USE_GPU
  )
  set(GRAPHMINE_G2MINER_MOTIF_SYMBOL_DEFINITIONS
    Graph=GraphMineG2MotifGraph
    GraphGPU=GraphMineG2MotifGraphGpu
    VertexSet=GraphMineG2MotifVertexSet
    MotifSolver=graphmine_g2_motif_solver
  )
  set_property(SOURCE
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/motif/gpu_base.cu
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/common/graph.cc
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/common/VertexSet.cc
    APPEND PROPERTY COMPILE_DEFINITIONS
      ${GRAPHMINE_G2MINER_MOTIF_SYMBOL_DEFINITIONS}
      GRAPHMINE_LIBRARY
      USE_GPU
  )
  set_property(SOURCE
    ${GRAPHMINE_G2MINER_MOTIF_ROOT}/src/motif/gpu_base.cu
    APPEND PROPERTY COMPILE_DEFINITIONS
      clear=graphmine_g2_motif_clear
  )
  target_link_libraries(graphmine_backend_graphminer_motif
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_features(graphmine_backend_graphminer_motif PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_graphminer_motif PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "70"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_graphminer_motif STATIC
    src/backends/g2miner_motif_stub.cpp
  )
  target_include_directories(graphmine_backend_graphminer_motif
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_graphminer_motif
    PUBLIC graphmine_core
  )
  set_target_properties(graphmine_backend_graphminer_motif PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_GRAPHSET_MOTIF_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/11_graph_motif_counting/papers/2023_graphset/code")

if(GRAPHMINE_HAS_GRAPHSET_MOTIF)
  find_package(OpenMP REQUIRED)
  set(GRAPHMINE_GRAPHSET_MOTIF_UPSTREAM_SOURCES
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/gpu/gpu_mc.cu
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/graph.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/dataloader.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/pattern.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/prefix.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/schedule_IEP.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/vertex_set.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/motif_generator.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/common.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/disjoint_set_union.cpp
    ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/set_operation.cpp
  )
  add_library(graphmine_backend_graphset_motif STATIC
    src/backends/graphset_motif.cu
    ${GRAPHMINE_GRAPHSET_MOTIF_UPSTREAM_SOURCES}
  )
  target_include_directories(graphmine_backend_graphset_motif
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}
      ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/include
      ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/gpu
  )
  target_compile_definitions(graphmine_backend_graphset_motif PRIVATE
    GRAPHMINE_LIBRARY
  )
  set(GRAPHMINE_GRAPHSET_MOTIF_SYMBOL_DEFINITIONS
    Bitmap=GraphMineGraphsetMotifBitmap
    DataLoader=GraphMineGraphsetMotifDataLoader
    DataType=GraphMineGraphsetMotifDataType
    DisjointSetUnion=GraphMineGraphsetMotifDisjointSetUnion
    Graph=GraphMineGraphsetMotifGraph
    Graphmpi=GraphMineGraphsetMotifGraphmpi
    LabeledGraph=GraphMineGraphsetMotifLabeledGraph
    MotifGenerator=GraphMineGraphsetMotifGenerator
    Pattern=GraphMineGraphsetMotifPattern
    PatternType=GraphMineGraphsetMotifPatternType
    Prefix=GraphMineGraphsetMotifPrefix
    Schedule_IEP=GraphMineGraphsetMotifSchedule
    TimeInterval=GraphMineGraphsetMotifTimeInterval
    VertexSet=GraphMineGraphsetMotifVertexSet
    allTime=graphmine_graphset_motif_all_time
    tmpTime=graphmine_graphset_motif_tmp_time
    get_wall_time=graphmine_graphset_motif_get_wall_time
    PatternType_printer=graphmine_graphset_motif_pattern_type_printer
    is_equal_adj_mat=graphmine_graphset_motif_is_equal_adj_mat
    GetDataType=graphmine_graphset_motif_get_data_type
    read_int=graphmine_graphset_motif_read_int
    read_unsigned_int=graphmine_graphset_motif_read_unsigned_int
    long_add=graphmine_graphset_motif_long_add
    erase_edge=graphmine_graphset_motif_erase_edge
    reduce_edges_for_clique=graphmine_graphset_motif_reduce_edges_for_clique
    degree_orientation_init=graphmine_graphset_motif_degree_orientation_init
    degeneracy_orientation_init=graphmine_graphset_motif_degeneracy_orientation_init
    get_intersection_size=graphmine_graphset_motif_get_intersection_size
  )
  set_property(SOURCE ${GRAPHMINE_GRAPHSET_MOTIF_UPSTREAM_SOURCES}
    APPEND PROPERTY COMPILE_DEFINITIONS
      GRAPHMINE_LIBRARY
      ${GRAPHMINE_GRAPHSET_MOTIF_SYMBOL_DEFINITIONS}
  )
  set_property(SOURCE ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/gpu/gpu_mc.cu
    APPEND PROPERTY COMPILE_DEFINITIONS
      GPUDeviceContext=GraphMineGraphsetMotifGpuDeviceContext
      GraphDeviceContext=GraphMineGraphsetMotifGraphDeviceContext
      LabeledGraphDeviceContext=GraphMineGraphsetMotifLabeledGraphDeviceContext
      GPUSchedule=GraphMineGraphsetMotifGpuSchedule
      GPUVertexSet=GraphMineGraphsetMotifGpuVertexSet
      PatternMatchingDeviceContext=GraphMineGraphsetMotifDeviceContext
      gpu_pattern_matching=graphmine_graphset_motif_kernel
      GPU_pattern_matching_final_in_exclusion=graphmine_graphset_motif_final_iep
      remove_anti_edge_vertices=graphmine_graphset_motif_remove_anti_edges
      intersection2=graphmine_graphset_motif_intersection2
      unordered_subtraction_size=graphmine_graphset_motif_subtraction_size
      triple_unordered_subtraction_size=graphmine_graphset_motif_triple_subtraction_size
      dev_alloc_and_copy=graphmine_graphset_motif_device_alloc_copy
      print_parameter=graphmine_graphset_motif_print_parameter
  )
  set_property(SOURCE ${GRAPHMINE_GRAPHSET_MOTIF_ROOT}/src/set_operation.cpp
    APPEND PROPERTY COMPILE_OPTIONS -march=native
  )
  target_compile_options(graphmine_backend_graphset_motif PRIVATE
    $<$<COMPILE_LANGUAGE:CUDA>:--maxrregcount=64>
  )
  target_link_libraries(graphmine_backend_graphset_motif
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_features(graphmine_backend_graphset_motif PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_graphset_motif PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_GRAPHSET_MOTIF_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_graphset_motif STATIC
    src/backends/graphset_motif_stub.cpp
  )
  target_include_directories(graphmine_backend_graphset_motif
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_graphset_motif PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_graphset_motif PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_DUMATO_MOTIF_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/11_graph_motif_counting/papers/2024_dumato/code")

if(GRAPHMINE_HAS_DUMATO_MOTIF)
  set(GRAPHMINE_DUMATO_MOTIF_UPSTREAM_SOURCES
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/motifs_DM_WCLB.cu
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/DuMatoCPU.cu
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/Graph.cpp
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/QuickMapping.cpp
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/EnumerationHelper.cpp
  )
  add_library(graphmine_backend_dumato_motif STATIC
    src/backends/dumato_motif.cu
    ${GRAPHMINE_DUMATO_MOTIF_UPSTREAM_SOURCES}
  )
  target_include_directories(graphmine_backend_dumato_motif
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main
  )
  target_compile_definitions(graphmine_backend_dumato_motif PRIVATE
    GRAPHMINE_LIBRARY
    GRAPHMINE_DUMATO_DICTIONARY_DIR="${GRAPHMINE_DUMATO_MOTIF_ROOT}/dictionaries"
    cudaAssert=graphmine_dumato_motif_cuda_assert
  )
  set(GRAPHMINE_DUMATO_MOTIF_SYMBOL_DEFINITIONS
    DataCPU=GraphMineDumatoMotifDataCpu
    DataGPU=GraphMineDumatoMotifDataGpu
    DuMatoCPU=GraphMineDumatoMotifCpu
    DuMatoGPU=GraphMineDumatoMotifGpu
    EnumerationHelper=GraphMineDumatoMotifEnumerationHelper
    GPULocalVariables=GraphMineDumatoMotifGpuLocalVariables
    Graph=GraphMineDumatoMotifGraph
    QuickMapping=GraphMineDumatoMotifQuickMapping
  )
  set_property(SOURCE ${GRAPHMINE_DUMATO_MOTIF_UPSTREAM_SOURCES}
    APPEND PROPERTY COMPILE_DEFINITIONS
      GRAPHMINE_LIBRARY
      GRAPHMINE_DUMATO_DICTIONARY_DIR="${GRAPHMINE_DUMATO_MOTIF_ROOT}/dictionaries"
      cudaAssert=graphmine_dumato_motif_cuda_assert
      ${GRAPHMINE_DUMATO_MOTIF_SYMBOL_DEFINITIONS}
  )
  set_property(SOURCE
    ${GRAPHMINE_DUMATO_MOTIF_ROOT}/src/main/motifs_DM_WCLB.cu
    APPEND PROPERTY COMPILE_DEFINITIONS
      motifs=graphmine_dumato_motif_kernel
  )
  target_link_libraries(graphmine_backend_dumato_motif
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_features(graphmine_backend_dumato_motif PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_dumato_motif PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_DUMATO_MOTIF_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_dumato_motif STATIC
    src/backends/dumato_motif_stub.cpp
  )
  target_include_directories(graphmine_backend_dumato_motif
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_dumato_motif PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_dumato_motif PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_graph_motifs src/problems/graph_motifs.cpp)
add_library(GraphMine::graph_motifs ALIAS graphmine_graph_motifs)
target_include_directories(graphmine_graph_motifs
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_graph_motifs
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_graphminer_motif
          graphmine_backend_graphset_motif
          graphmine_backend_dumato_motif
)
target_compile_features(graphmine_graph_motifs PUBLIC cxx_std_17)
set_target_properties(graphmine_graph_motifs PROPERTIES
  EXPORT_NAME graph_motifs
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_EVEREST_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/15_temporal_motif_mining/papers/2024_everest/code")

if(GRAPHMINE_HAS_EVEREST)
  add_library(graphmine_backend_everest STATIC src/backends/everest.cu)
  target_include_directories(graphmine_backend_everest
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_EVEREST_ROOT}/include
      ${GRAPHMINE_EVEREST_ROOT}/system/.tmp
  )
  target_link_libraries(graphmine_backend_everest
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_features(graphmine_backend_everest PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_everest PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_EVEREST_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_everest STATIC src/backends/everest_stub.cpp)
  target_include_directories(graphmine_backend_everest
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_everest PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_everest PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_MAYURA_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/15_temporal_motif_mining/papers/2025_mayura/code/GPU-co-mining")

if(GRAPHMINE_HAS_MAYURA)
  add_library(graphmine_backend_mayura STATIC src/backends/mayura.cu)
  target_include_directories(graphmine_backend_mayura
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_MAYURA_ROOT}/include
      ${GRAPHMINE_MAYURA_ROOT}/system/.tmp
  )
  target_link_libraries(graphmine_backend_mayura
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt
  )
  target_compile_features(graphmine_backend_mayura PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_mayura PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_MAYURA_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_mayura STATIC src/backends/mayura_stub.cpp)
  target_include_directories(graphmine_backend_mayura
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_mayura PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_mayura PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_temporal_motif_mining
  src/problems/temporal_motif_mining.cpp
)
add_library(GraphMine::temporal_motif_mining ALIAS
            graphmine_temporal_motif_mining)
target_include_directories(graphmine_temporal_motif_mining
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_temporal_motif_mining
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_everest graphmine_backend_mayura
)
target_compile_features(graphmine_temporal_motif_mining PUBLIC cxx_std_17)
set_target_properties(graphmine_temporal_motif_mining PROPERTIES
  EXPORT_NAME temporal_motif_mining
  POSITION_INDEPENDENT_CODE ON
)

set(GRAPHMINE_GLEIDEN_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/16_community_detection/papers/2026_gleiden/code")

if(GRAPHMINE_HAS_GLEIDEN)
  find_package(OpenMP REQUIRED)
  add_library(graphmine_backend_gleiden STATIC
    src/backends/gleiden.cu
    ${GRAPHMINE_GLEIDEN_ROOT}/leiden.cpp
    ${GRAPHMINE_GLEIDEN_ROOT}/leiden.cu
  )
  target_include_directories(graphmine_backend_gleiden
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_GLEIDEN_ROOT}
  )
  target_compile_definitions(graphmine_backend_gleiden PRIVATE
    GRAPHMINE_LIBRARY
  )
  target_link_libraries(graphmine_backend_gleiden
    PUBLIC graphmine_core
    PRIVATE CUDA::cudart CUDA::cudadevrt OpenMP::OpenMP_CXX
  )
  target_compile_features(graphmine_backend_gleiden PUBLIC cxx_std_17)
  set_target_properties(graphmine_backend_gleiden PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "${GRAPHMINE_GLEIDEN_CUDA_ARCHITECTURES}"
    CUDA_SEPARABLE_COMPILATION ON
    CUDA_RESOLVE_DEVICE_SYMBOLS ON
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_gleiden STATIC src/backends/gleiden_stub.cpp)
  target_include_directories(graphmine_backend_gleiden
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_gleiden PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_gleiden PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

set(GRAPHMINE_PGGC_ROOT
  "${CMAKE_CURRENT_SOURCE_DIR}/../problems/16_community_detection/papers/2026_multilevel_graph_clustering/code")

if(GRAPHMINE_HAS_PGGC)
  add_library(graphmine_backend_pggc STATIC
    src/backends/pggc.cpp
    ${GRAPHMINE_PGGC_ROOT}/src/leidenR.cpp
    ${GRAPHMINE_PGGC_ROOT}/src/contract.cpp
    ${GRAPHMINE_PGGC_ROOT}/src/local_mover.cpp
    ${GRAPHMINE_PGGC_ROOT}/src/clustering_methods.cpp
    ${GRAPHMINE_PGGC_ROOT}/src/ordering.cpp
  )
  target_include_directories(graphmine_backend_pggc
    PRIVATE
      ${CMAKE_CURRENT_SOURCE_DIR}/include
      ${CMAKE_CURRENT_SOURCE_DIR}/src
      ${GRAPHMINE_PGGC_ROOT}/interface
      ${GRAPHMINE_PGGC_ROOT}/src
  )
  target_link_libraries(graphmine_backend_pggc
    PUBLIC graphmine_core
    PRIVATE Kokkos::kokkos Kokkos::kokkoskernels CUDA::cudart
  )
  target_compile_features(graphmine_backend_pggc PUBLIC cxx_std_20)
  set_target_properties(graphmine_backend_pggc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
else()
  add_library(graphmine_backend_pggc STATIC src/backends/pggc_stub.cpp)
  target_include_directories(graphmine_backend_pggc
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include ${CMAKE_CURRENT_SOURCE_DIR}/src
  )
  target_link_libraries(graphmine_backend_pggc PUBLIC graphmine_core)
  set_target_properties(graphmine_backend_pggc PROPERTIES
    POSITION_INDEPENDENT_CODE ON
  )
endif()

add_library(graphmine_community_detection
  src/problems/community_detection.cpp
)
add_library(GraphMine::community_detection ALIAS graphmine_community_detection)
target_include_directories(graphmine_community_detection
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_community_detection
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_gleiden graphmine_backend_pggc
)
target_compile_features(graphmine_community_detection PUBLIC cxx_std_17)
set_target_properties(graphmine_community_detection PROPERTIES
  EXPORT_NAME community_detection
  POSITION_INDEPENDENT_CODE ON
)

add_library(graphmine_maximal_cliques
  src/problems/maximal_cliques.cpp
)
add_library(GraphMine::maximal_cliques ALIAS graphmine_maximal_cliques)
target_include_directories(graphmine_maximal_cliques
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
  PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(graphmine_maximal_cliques
  PUBLIC graphmine_core
  PRIVATE graphmine_backend_rdmce graphmine_backend_mce_gpu
          graphmine_backend_g2_aimd
)
target_compile_features(graphmine_maximal_cliques PUBLIC cxx_std_17)
set_target_properties(graphmine_maximal_cliques PROPERTIES
  EXPORT_NAME maximal_cliques
  POSITION_INDEPENDENT_CODE ON
)

if(GRAPHMINE_BUILD_CLI)
  find_path(GRAPHMINE_BOOST_JSON_INCLUDE_DIR boost/json.hpp)
  if(NOT GRAPHMINE_BOOST_JSON_INCLUDE_DIR)
    message(FATAL_ERROR
      "GRAPHMINE_BUILD_CLI=ON requires Boost.JSON headers (boost/json.hpp)")
  endif()
  add_executable(graphmine_cli src/cli/graphmine.cpp)
  set_target_properties(graphmine_cli PROPERTIES OUTPUT_NAME graphmine)
  target_include_directories(graphmine_cli
    PRIVATE ${GRAPHMINE_BOOST_JSON_INCLUDE_DIR}
  )
  target_compile_features(graphmine_cli PRIVATE cxx_std_17)
  target_link_libraries(graphmine_cli PRIVATE
    GraphMine::maximal_cliques
    GraphMine::maximum_clique
    GraphMine::k_cliques
    GraphMine::quasi_cliques
    GraphMine::k_core
    GraphMine::maximal_bicliques
    GraphMine::triangle_counting
    GraphMine::dynamic_triangle_counting
    GraphMine::graph_motifs
    GraphMine::subgraph_isomorphism
    GraphMine::temporal_motif_mining
    GraphMine::community_detection
    GraphMine::betweenness_centrality
  )
endif()

if(GRAPHMINE_BUILD_EXAMPLES)
  add_executable(graphmine_maximal_cliques_example
    examples/maximal_cliques.cpp
  )
  target_link_libraries(graphmine_maximal_cliques_example
    PRIVATE GraphMine::maximal_cliques
  )
endif()

if(GRAPHMINE_BUILD_TESTS)
  enable_testing()
  add_executable(graphmine_graph_test tests/graph_test.cpp)
  target_link_libraries(graphmine_graph_test PRIVATE GraphMine::core)
  add_test(NAME graphmine_graph_test COMMAND graphmine_graph_test)

  if(GRAPHMINE_BUILD_CLI)
    add_test(NAME graphmine_cli_list_test COMMAND graphmine_cli list)
    add_test(NAME graphmine_cli_validate_test
             COMMAND graphmine_cli validate
                     --graph ${CMAKE_CURRENT_SOURCE_DIR}/examples/data/triangle.json)
    add_test(NAME graphmine_cli_triangle_run_test
             COMMAND graphmine_cli run triangle-counting
                     --graph ${CMAKE_CURRENT_SOURCE_DIR}/examples/data/triangle.json
                     --backend tot --list-instances)
    if(NOT GRAPHMINE_HAS_TOT)
      set_tests_properties(graphmine_cli_triangle_run_test
                           PROPERTIES DISABLED TRUE)
    endif()
  endif()

  add_executable(graphmine_maximal_cliques_test tests/maximal_cliques_test.cpp)
  target_link_libraries(graphmine_maximal_cliques_test
    PRIVATE GraphMine::maximal_cliques
  )
  add_test(NAME graphmine_maximal_cliques_test
           COMMAND graphmine_maximal_cliques_test)
  if(NOT GRAPHMINE_HAS_RDMCE OR NOT GRAPHMINE_HAS_MCE_GPU OR
     NOT GRAPHMINE_HAS_G2_AIMD)
    set_tests_properties(graphmine_maximal_cliques_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_k_core_test tests/k_core_test.cpp)
  target_link_libraries(graphmine_k_core_test PRIVATE GraphMine::k_core)
  add_test(NAME graphmine_k_core_test COMMAND graphmine_k_core_test)
  if(NOT GRAPHMINE_HAS_KCOREGPU)
    set_tests_properties(graphmine_k_core_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_maximum_clique_test tests/maximum_clique_test.cpp)
  target_link_libraries(graphmine_maximum_clique_test
    PRIVATE GraphMine::maximum_clique
  )
  add_test(NAME graphmine_maximum_clique_test
           COMMAND graphmine_maximum_clique_test)
  if(NOT GRAPHMINE_HAS_CUDAMS OR NOT GRAPHMINE_HAS_GPU_MAXIMUM_CLIQUE OR
     NOT GRAPHMINE_HAS_MAXIMUM_CLIQUE_ON_GPU)
    set_tests_properties(graphmine_maximum_clique_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_triangle_counting_test
    tests/triangle_counting_test.cpp
  )
  target_link_libraries(graphmine_triangle_counting_test
    PRIVATE GraphMine::triangle_counting
  )
  add_test(NAME graphmine_triangle_counting_test
           COMMAND graphmine_triangle_counting_test)
  if(NOT GRAPHMINE_HAS_TOT OR NOT GRAPHMINE_HAS_WETRIC)
    set_tests_properties(graphmine_triangle_counting_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_dynamic_triangle_counting_test
    tests/dynamic_triangle_counting_test.cpp
  )
  target_link_libraries(graphmine_dynamic_triangle_counting_test
    PRIVATE GraphMine::dynamic_triangle_counting
  )
  add_test(NAME graphmine_dynamic_triangle_counting_test
           COMMAND graphmine_dynamic_triangle_counting_test)
  if(NOT GRAPHMINE_HAS_EDTC)
    set_tests_properties(graphmine_dynamic_triangle_counting_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_k_cliques_test tests/k_cliques_test.cpp)
  target_link_libraries(graphmine_k_cliques_test PRIVATE GraphMine::k_cliques)
  add_test(NAME graphmine_k_cliques_test COMMAND graphmine_k_cliques_test)
  if(NOT GRAPHMINE_HAS_GRAPHSET_KCLIQUE OR NOT GRAPHMINE_HAS_KCGPU OR
     NOT GRAPHMINE_HAS_GAMMA_KCLIQUE)
    set_tests_properties(graphmine_k_cliques_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_betweenness_centrality_test
    tests/betweenness_centrality_test.cpp
  )
  target_link_libraries(graphmine_betweenness_centrality_test
    PRIVATE GraphMine::betweenness_centrality
  )
  add_test(NAME graphmine_betweenness_centrality_test
           COMMAND graphmine_betweenness_centrality_test)
  if(NOT GRAPHMINE_HAS_TURBOBC)
    set_tests_properties(graphmine_betweenness_centrality_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_maximal_bicliques_test
    tests/maximal_bicliques_test.cpp
  )
  target_link_libraries(graphmine_maximal_bicliques_test
    PRIVATE GraphMine::maximal_bicliques
  )
  add_test(NAME graphmine_maximal_bicliques_test
           COMMAND graphmine_maximal_bicliques_test)
  if(NOT GRAPHMINE_HAS_CUMBE)
    set_tests_properties(graphmine_maximal_bicliques_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_quasi_cliques_test tests/quasi_cliques_test.cpp)
  target_link_libraries(graphmine_quasi_cliques_test
    PRIVATE GraphMine::quasi_cliques
  )
  add_test(NAME graphmine_quasi_cliques_test
           COMMAND graphmine_quasi_cliques_test)
  if(NOT GRAPHMINE_HAS_CUQC)
    set_tests_properties(graphmine_quasi_cliques_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_subgraph_isomorphism_test
    tests/subgraph_isomorphism_test.cpp
  )
  target_link_libraries(graphmine_subgraph_isomorphism_test
    PRIVATE GraphMine::subgraph_isomorphism
  )
  add_test(NAME graphmine_subgraph_isomorphism_test
           COMMAND graphmine_subgraph_isomorphism_test)
  if(NOT GRAPHMINE_HAS_GMATCH)
    set_tests_properties(graphmine_subgraph_isomorphism_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_graph_motifs_test tests/graph_motifs_test.cpp)
  target_link_libraries(graphmine_graph_motifs_test
    PRIVATE GraphMine::graph_motifs
  )
  add_test(NAME graphmine_graph_motifs_test
           COMMAND graphmine_graph_motifs_test)
  if(NOT GRAPHMINE_HAS_GRAPHMINER_MOTIF OR NOT GRAPHMINE_HAS_GRAPHSET_MOTIF OR
     NOT GRAPHMINE_HAS_DUMATO_MOTIF)
    set_tests_properties(graphmine_graph_motifs_test PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_temporal_motif_mining_test
    tests/temporal_motif_mining_test.cpp
  )
  target_link_libraries(graphmine_temporal_motif_mining_test
    PRIVATE GraphMine::temporal_motif_mining
  )
  add_test(NAME graphmine_temporal_motif_mining_test
           COMMAND graphmine_temporal_motif_mining_test)
  if(NOT GRAPHMINE_HAS_EVEREST OR NOT GRAPHMINE_HAS_MAYURA)
    set_tests_properties(graphmine_temporal_motif_mining_test
                         PROPERTIES DISABLED TRUE)
  endif()

  add_executable(graphmine_community_detection_test
    tests/community_detection_test.cpp
  )
  target_link_libraries(graphmine_community_detection_test
    PRIVATE GraphMine::community_detection
  )
  add_test(NAME graphmine_community_detection_test
           COMMAND graphmine_community_detection_test)
  if(NOT GRAPHMINE_HAS_GLEIDEN OR NOT GRAPHMINE_HAS_PGGC)
    set_tests_properties(graphmine_community_detection_test
                         PROPERTIES DISABLED TRUE)
  endif()
endif()

install(TARGETS
  graphmine_core
  graphmine_maximal_cliques
  graphmine_backend_rdmce
  graphmine_backend_mce_gpu
  graphmine_backend_g2_aimd
  graphmine_k_core
  graphmine_backend_kcoregpu
  graphmine_maximum_clique
  graphmine_backend_cuda_ms
  graphmine_backend_gpu_maximum_clique
  graphmine_backend_maximum_clique_on_gpu
  graphmine_triangle_counting
  graphmine_backend_tot
  graphmine_backend_wetric
  graphmine_dynamic_triangle_counting
  graphmine_backend_edtc
  graphmine_k_cliques
  graphmine_backend_graphset_kclique
  graphmine_backend_kcgpu
  graphmine_backend_gamma_kclique
  graphmine_betweenness_centrality
  graphmine_backend_turbobc
  graphmine_maximal_bicliques
  graphmine_backend_cumbe
  graphmine_quasi_cliques
  graphmine_backend_cuqc
  graphmine_subgraph_isomorphism
  graphmine_backend_gmatch
  graphmine_graph_motifs
  graphmine_backend_graphminer_motif
  graphmine_backend_graphset_motif
  graphmine_backend_dumato_motif
  graphmine_temporal_motif_mining
  graphmine_backend_everest
  graphmine_backend_mayura
  graphmine_community_detection
  graphmine_backend_gleiden
  graphmine_backend_pggc
  EXPORT GraphMineTargets
  ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
  LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
  RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT GraphMineTargets
  FILE GraphMineTargets.cmake
  NAMESPACE GraphMine::
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/GraphMine
)

set(GRAPHMINE_CONFIG_NEEDS_CUDA ${GRAPHMINE_CUDA_AVAILABLE})
set(GRAPHMINE_CONFIG_NEEDS_OPENMP OFF)
if(GRAPHMINE_HAS_MCE_GPU OR GRAPHMINE_HAS_G2_AIMD OR
   GRAPHMINE_HAS_KCOREGPU OR GRAPHMINE_HAS_CUDAMS OR
   GRAPHMINE_HAS_GPU_MAXIMUM_CLIQUE OR GRAPHMINE_HAS_TOT OR
   GRAPHMINE_HAS_EDTC OR
   GRAPHMINE_HAS_GRAPHSET_KCLIQUE OR GRAPHMINE_HAS_GRAPHSET_MOTIF OR
   GRAPHMINE_HAS_GLEIDEN)
  set(GRAPHMINE_CONFIG_NEEDS_OPENMP ON)
endif()
set(GRAPHMINE_CONFIG_NEEDS_KOKKOS ${GRAPHMINE_HAS_PGGC})
configure_package_config_file(
  cmake/GraphMineConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/GraphMineConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/GraphMine
)
write_basic_package_version_file(
  ${CMAKE_CURRENT_BINARY_DIR}/GraphMineConfigVersion.cmake
  VERSION ${PROJECT_VERSION}
  COMPATIBILITY SameMajorVersion
)
install(FILES
  ${CMAKE_CURRENT_BINARY_DIR}/GraphMineConfig.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/GraphMineConfigVersion.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/GraphMine
)

if(GRAPHMINE_BUILD_CLI)
  install(TARGETS graphmine_cli
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
  )
endif()

install(FILES
  manifests/graphmine_manifest.json
  manifests/graphmine_catalog.json
  ../problems/graph_input.schema.json
  DESTINATION ${CMAKE_INSTALL_DATADIR}/graphmine
)
install(DIRECTORY examples/data/
  DESTINATION ${CMAKE_INSTALL_DATADIR}/graphmine/examples
)
