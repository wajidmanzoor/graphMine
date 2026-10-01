// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <limits>
#include <random>
#include <Kokkos_Core.hpp>
#include "KokkosSparse_CrsMatrix.hpp"
#include "KokkosSparse_SortCrs.hpp"
#include "Kokkos_UnorderedMap.hpp"
#include "memory_store.hpp"
#include "cluster_data.hpp"
#include "weighted_graph.h"
#include "core_types.h"

namespace jet_community {

namespace leidenR {
    // define internal types
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using vtx_vt = typename Kokkos::View<ordinal_t*, Device>;
    using mem_t = memory_store;
    using refine_data = cluster_data;
    using wg_t = weighted_graph;

    template <bool top, bool uniform>
    vtx_vt coarsen_leidenR(const wg_t wg,
        const vtx_vt& constraint,
        mem_t& mem,
        const refine_data& rfd,
        ordinal_t& coarse_vtx_count);

}

}