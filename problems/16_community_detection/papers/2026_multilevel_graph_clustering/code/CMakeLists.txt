# Copyright 2026 Michael S. Gilbert II
# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.28)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
project(jetcluster CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED True)

#ALL DEVICE BUILDS
find_package(KokkosKernels REQUIRED)
add_compile_options(-Wall -Wextra -Wshadow)
#add_compile_options(-g -DDEBUG)

add_subdirectory(src)
add_subdirectory(app)