// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "memory_store.hpp"
#include "cluster_data.hpp"
#include "ExperimentLoggerUtil.hpp"
#include "weighted_graph.h"
#include "core_types.h"

namespace jet_community {
namespace clustering_methods {
    // define internal types
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using vtx_vt = typename Kokkos::View<ordinal_t*, Device>;
    using mem_t = memory_store;
    using wg_t = weighted_graph;
    using rfd_t = cluster_data;

    template <bool plus, bool improve>
    vtx_vt leiden_part(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input);

    template <bool constrained>
    vtx_vt louvain_part(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt constraint);

}
}