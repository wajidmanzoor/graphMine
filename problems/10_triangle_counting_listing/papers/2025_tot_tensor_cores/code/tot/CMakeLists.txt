add_library(totlib INTERFACE)

# target_include_directories(bmplib INTERFACE .)
# Use this instead
target_include_directories(totlib
  INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
)

target_link_libraries(totlib INTERFACE
  OpenMP::OpenMP_CXX
)


target_compile_options(totlib INTERFACE
  $<$<CONFIG:Debug>:-G -g>
  $<$<COMPILE_LANGUAGE:CUDA>:
  -Xcompiler=-fopenmp # OpenMP flags for CUDA compiler
  --extended-lambda
  --expt-relaxed-constexpr
  -w # Suppress warning -- though warning is usually helpful
  >
)
