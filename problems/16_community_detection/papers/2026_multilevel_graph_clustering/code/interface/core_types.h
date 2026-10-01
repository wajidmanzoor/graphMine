// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <Kokkos_Core.hpp>
#include "KokkosSparse_CrsMatrix.hpp"

// needs to be big enough to hold total vertex count
using ordinal_t = int32_t;
// needs to be big enough to hold total edge count
using edge_offset_t = int32_t;
// needs to hold edge cuts per-vertex
// may need to be as large as edge_offset_t, but can get away with being smaller in some cases
using value_t = edge_offset_t;

using Device = Kokkos::Cuda;
using matrix_t = typename KokkosSparse::CrsMatrix<value_t, ordinal_t, Device, void, edge_offset_t>;