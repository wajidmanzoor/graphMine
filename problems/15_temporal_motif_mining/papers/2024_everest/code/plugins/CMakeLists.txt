
set(CMAKE_CUDA_SEPARABLE_COMPILATION OFF)

add_library(Baseline SHARED GPUWorkerBaseline.cu)
add_library(U0 SHARED GPUWorkerU0.cu)
add_library(U1 SHARED GPUWorkerU1.cu)
add_library(U1B SHARED GPUWorkerU1B.cu)
add_library(U2 SHARED GPUWorkerU2.cu)
add_library(U3 SHARED GPUWorkerU3.cu)
add_library(U3B SHARED GPUWorkerU3B.cu)

foreach(plugin Baseline U0 U1 U1B U2 U3 U3B)
  target_link_libraries(${plugin} PRIVATE fmt::fmt)
endforeach()

set(CMAKE_CUDA_SEPARABLE_COMPILATION ON)
