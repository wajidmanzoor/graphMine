cmake_minimum_required(VERSION 3.11)

# project(gpuHgrPar)
# find_package(CUDA QUIET REQUIRED)
project(gpuHgrPar LANGUAGES CXX CUDA)
enable_language(CUDA)

# set(CMAKE_BUILD_TYPE "Debug")
# set(CMAKE_CUDA_FLAGS_DEBUG "-g") # -G
# set(CMAKE_CUDA_FLAGS "-G") # “-G”选项会生成带有调试信息的CUDA二进制文件
# set(CMAKE_CUDA_FLAGS_DEBUG "-O0 -g -lineinfo")
set(CMAKE_CUDA_FLAGS_RELEASE "-O3")

set(
    CUDA_NVCC_FLAGS "${CUDA_NVCC_FLAGS} "#-g -G -lineinfo" 
    # -g -G -O3#
    -O3 -lineinfo -fopenmp 
    # -gencode=arch=compute_90, code=sm_90 --expt-extended-lambda
    # -arch=compute_86;-code=sm_86
    -gencode=arch=compute_86,code=sm_86
)

# set(CUDA_NVCC_FLAGS "${CUDA_NVCC_FLAGS}; --Wno-deprecated-gpu-targets")
# set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -O3 -lineinfo -fopenmp -gencode arch=compute_86,code=sm_86") # --ptxas-options=-v for register and shared mem usage
# set(CMAKE_CUDA_ARCHITECTURES 90)

# add_definitions(
#     -Wno-unused-parameter # -Werror
#     -w -fPIC
# )
# set(CMAKE_VERBOSE_MAKEFILE ON)
# add_compile_options(-std=c++17)
# set(CMAKE_CXX_FLAGS "-std=c++17" ${CMAKE_CXX_FLAGS})
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include_directories(
    kernels/
    include/
    utility/
    no_uvm_impl/
    no_uvm_impl/non-deterministic/
    use_uvm_impl/
    .
)

set(GPU_HGR_PAR_SOURCE_FILES
    kernels/coarsening_kernels.cuh
    kernels/coarsening_kernels.cu
    kernels/construction_kernels.cuh
    kernels/construction_kernels.cu
    kernels/partitioning_kernels.cuh
    kernels/partitioning_kernels.cu
    kernels/refinement_kernels.cuh
    kernels/refinement_kernels.cu
    
    include/partitioning_impl.h
    include/refinement_impl.h
    include/projection.cuh
    include/coarsening_impl.h
    include/construction_impl.h
    include/graph.h

    utility/utils.cuh
    utility/utils.cu
    utility/param_config.h
    utility/param_config.cc
    utility/validation.cuh
    utility/validation.cu

    no_uvm_impl/non-deterministic/nondeterministic_coarsen_no_uvm_kernels.cuh
    no_uvm_impl/non-deterministic/nondeterministic_coarsen_no_uvm_kernels.cu
    no_uvm_impl/non-deterministic/nondeterministic_coarsen_no_uvm.cu

    no_uvm_impl/use_no_uvm.cuh
    no_uvm_impl/coarsen_brute_force.cu
    no_uvm_impl/coarsen_no_uvm_kernels.cuh
    no_uvm_impl/coarsen_no_uvm_kernels_opt.cu
    no_uvm_impl/coarsen_no_uvm_kernels.cu
    no_uvm_impl/coarsen_no_uvm.cu
    no_uvm_impl/partition_no_uvm_kernels.cuh
    no_uvm_impl/partition_no_uvm_kernels.cu
    no_uvm_impl/partition_no_uvm.cu
    no_uvm_impl/refinement_no_uvm_kernels.cuh
    no_uvm_impl/refinement_no_uvm_kernels.cu
    no_uvm_impl/refinement_no_uvm.cu
    no_uvm_impl/use_no_uvm.cu
    no_uvm_impl/kway_partition_no_uvm.cu
    no_uvm_impl/kway_partition_no_uvm_kernels.cuh

    # coarsening.cu
    # construction.cu
    # partitioning_base.cu
    # partitioning_opt1.cu
    # partitioning_opt2.cu
    # refinement_base.cu
    # refinement_opt1.cu
    # refinement_opt2.cu
    # refinement_opt3.cu
    # refinement_opt4.cu
    # projection.cu

    use_uvm_impl/coarsening.cu
    use_uvm_impl/construction.cu
    use_uvm_impl/partitioning_base.cu
    use_uvm_impl/partitioning_opt1.cu
    use_uvm_impl/partitioning_opt2.cu
    use_uvm_impl/refinement_base.cu
    use_uvm_impl/refinement_opt1.cu
    use_uvm_impl/refinement_opt2.cu
    use_uvm_impl/refinement_opt3.cu
    use_uvm_impl/refinement_opt4.cu
    use_uvm_impl/projection.cu

    main.cu
)

file(GLOB SRC_FILES ./* kernels/* include/* utility/* no_uvm_impl/* no_uvm_impl/non-deterministic/* use_uvm_impl/*)

# link_directories(
#     /usr/lib/gcc/x86_64-linux-gnu/9/libstdc++fs.a
# )

# cuda_add_executable(
add_executable(
    gHyPart
    ${GPU_HGR_PAR_SOURCE_FILES}
    # ${SRC_FILES}
)

# target_compile_options(gHyPart PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:
#                         --generate-line-info 
#                         -gencode arch=compute_86,code=sm_86>
#                         )

find_package(OpenMP REQUIRED)
set_target_properties(
    gHyPart PROPERTIES CUDA_ARCHITECTURES "86;86"
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED OFF
    CXX_EXTENSIONS OFF
)
# -lcudadevrt 
target_link_libraries(
    gHyPart -lstdc++fs -lcusparse OpenMP::OpenMP_CXX
)
