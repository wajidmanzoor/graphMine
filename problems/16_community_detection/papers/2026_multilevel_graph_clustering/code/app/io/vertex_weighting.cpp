// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include "header/parse_args.h"
#include "header/io_views.hpp"
#include "core_types.h"

namespace jet_community {
using wgt_view_t = Kokkos::View<value_t*, Device>;
using r_policy = Kokkos::RangePolicy<typename Device::execution_space>;

void degree_weighting(const matrix_t& g, wgt_view_t vweights){
    Kokkos::parallel_for("set v weights", r_policy(0, g.numRows()), KOKKOS_LAMBDA(const ordinal_t i){
        vweights(i) = g.graph.row_map(i + 1) - g.graph.row_map(i);
    });
}

void weighted_degree_weighting(const matrix_t& g, wgt_view_t vweights){
    Kokkos::parallel_for("set v weights", r_policy(0, g.numRows()), KOKKOS_LAMBDA(const ordinal_t i){
        value_t weighted_degree = 0;
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i + 1); j++){
            weighted_degree += g.values(j);
        }
        vweights(i) = weighted_degree;
    });
}

wgt_view_t get_vtx_weights(const matrix_t g, const base_args args){
    if(args.vw_file.size() > 0){
        return load_view<wgt_view_t>(g.numRows(), args.vw_file.c_str());
    } else {
        wgt_view_t vweights(Kokkos::ViewAllocateWithoutInitializing("vertex weights"), g.numRows());
        switch (args.obj_type){
            case Objective::Modularity:
                degree_weighting(g, vweights);
                break;
            case Objective::WModularity:
                weighted_degree_weighting(g, vweights);
                break;
            default:
                Kokkos::deep_copy(vweights, 1);
        }
        return vweights;
    }
}

}