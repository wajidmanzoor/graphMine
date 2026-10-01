// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <Kokkos_Core.hpp>
#include "core_types.h"

namespace jet_community {

// combines a crs matrix/graph with vertex weights
struct weighted_graph {
    using scalar_t = typename matrix_t::value_type;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;

    matrix_t mtx;
    wgt_vt vtx_w;
    // if edge_uniform is true
    // then it is unsafe to access mtx.values
    bool edge_uniform = true;
};

}