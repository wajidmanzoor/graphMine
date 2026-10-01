// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include "io/header/parse_args.h"
#include "weighted_graph.h"
#include "cluster_data.hpp"

namespace jet_community {
    
    std::unique_ptr<cluster_data> get_objective(const weighted_graph wg, const base_args args){
        switch(args.obj_type){
            case Objective::Modularity:
                return std::make_unique<modularity>(wg.mtx, wg.vtx_w, args.lambda_multiplier, true);
            case Objective::WModularity:
                return std::make_unique<modularity>(wg.mtx, wg.vtx_w, args.lambda_multiplier, wg.edge_uniform);
            case Objective::NLCC:
                return std::make_unique<normalized_lcc>(wg.mtx, wg.vtx_w, args.lambda_multiplier, wg.edge_uniform);
            case Objective::CPM:
                return std::make_unique<constant_potts>(wg.mtx, wg.vtx_w, args.lambda_multiplier);
            default:
                return std::make_unique<cluster_data>(wg.mtx, wg.vtx_w, args.lambda_multiplier);
        }
    }

    bool uses_edge_weights(const base_args args) {
        if(args.obj_type == Objective::Modularity || args.obj_type == Objective::CPM){
            return true;
        }
        return false;
    }
}