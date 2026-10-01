// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <Kokkos_Core.hpp>
#include "memory_store.hpp"
#include "weighted_graph.h"
#include "core_types.h"

namespace jet_community {

namespace contracter {

    // define internal types
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using vtx_view_t = Kokkos::View<ordinal_t*, Device>;
    using wg_t = weighted_graph;
    using mem_t = memory_store;

    template <bool uniform, bool pval_clone_valid>
    wg_t build_coarse_graph(const wg_t curr_level,
        const vtx_view_t vcmap,
        const ordinal_t nc,
        mem_t& mem);

}

}