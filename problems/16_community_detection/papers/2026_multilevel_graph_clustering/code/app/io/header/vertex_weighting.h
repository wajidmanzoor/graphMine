// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "core_types.h"

namespace jet_community {
    using wgt_view_t = Kokkos::View<value_t*, Device>;

    wgt_view_t get_vtx_weights(const matrix_t g, const base_args args);
}