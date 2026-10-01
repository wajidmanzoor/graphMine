cmake_minimum_required(VERSION 3.18)
project(g2-aimd VERSION 1.0 LANGUAGES CXX CUDA)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Auto-detect architecture and enable native optimization
set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -g")
set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -O3 -funroll-loops")

# Try to detect and use native optimization with fallback option
if(NOT CMAKE_BUILD_TYPE STREQUAL "Debug")
    include(CheckCXXCompilerFlag)
    CHECK_CXX_COMPILER_FLAG("-march=native" COMPILER_SUPPORTS_MARCH_NATIVE)
    if(COMPILER_SUPPORTS_MARCH_NATIVE)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -march=native")
        message(STATUS "Using native architecture optimization")
    else()
        message(STATUS "Native architecture optimization not supported, using default flags")
    endif()
endif()

# Set CUDA compilation options
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} -Xptxas -v -maxrregcount 64")

# Use native CUDA architecture detection
set(CMAKE_CUDA_ARCHITECTURES native)

# Include directories
include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/bliss-0.73
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/MPMCQueue/include
)

# Find and link BLISS library
find_library(BLISS_LIBRARY
    NAMES bliss
    HINTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/bliss-0.73/bliss
    REQUIRED
)

if(NOT BLISS_LIBRARY)
    message(FATAL_ERROR "BLISS library not found. Please ensure it's built in third_party/bliss-0.73/bliss")
endif()

# Link thread library
find_package(Threads REQUIRED)

# -------------- Required kmeans applications ----------------
set(REQUIRED_BINARIES preprocess kcore)

foreach(BINARY IN LISTS REQUIRED_BINARIES)
    add_executable(${BINARY} kmeans/${BINARY}.cpp)
    target_link_libraries(${BINARY}
        PRIVATE
        ${BLISS_LIBRARY}
        Threads::Threads
    )
    target_include_directories(${BINARY}
        PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/third_party/bliss-0.73
    )
    # Set output directory
    set_target_properties(${BINARY} PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin
    )
endforeach()

# -------------- app_BK application ----------------
file(GLOB APP_BK_SOURCES
    app_BK/main.cu
    app_BK/BK.h
)

add_executable(bk ${APP_BK_SOURCES})

# Set CUDA specific properties
source_group(TREE ${CMAKE_CURRENT_SOURCE_DIR} FILES ${APP_BK_SOURCES})
set_target_properties(bk PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/bin
)

# Link necessary libraries
target_link_libraries(bk
    PRIVATE
    ${BLISS_LIBRARY}
    Threads::Threads
    OpenMP::OpenMP_CXX
)

# Find OpenMP
find_package(OpenMP)
if(OpenMP_CXX_FOUND)
    target_link_libraries(bk PRIVATE OpenMP::OpenMP_CXX)
endif()

# -------------- Installation targets ----------------
install(TARGETS ${REQUIRED_BINARIES} bk
    RUNTIME DESTINATION bin
)

# -------------- Build information print ----------------
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "CUDA architectures: ${CMAKE_CUDA_ARCHITECTURES}")
message(STATUS "C++ compiler flags: ${CMAKE_CXX_FLAGS}")
message(STATUS "CUDA compiler flags: ${CMAKE_CUDA_FLAGS}")
message(STATUS "Will build executables: ${REQUIRED_BINARIES} bk")