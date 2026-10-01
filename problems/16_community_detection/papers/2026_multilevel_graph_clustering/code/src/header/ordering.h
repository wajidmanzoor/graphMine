// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <Kokkos_Core.hpp>
#include "memory_store.hpp"
#include "core_types.h"

namespace jet_community {

namespace ordering {
    // define internal types
    using ordinal_t = typename matrix_t::ordinal_type;
    using mem_t = memory_store;
    // on the RTX 5090, I change MID_CUTOFF to 32 for best performance
    // I found 64 to be better for the B200
    // for other GPUs, you can experiment yourself
    constexpr ordinal_t MID_CUTOFF = 64;
    constexpr ordinal_t LARGE_CUTOFF = 128;
    constexpr ordinal_t MASSIVE_CUTOFF = 15000;

    void generate_orderings(mem_t& mem, const matrix_t& g);
}

}