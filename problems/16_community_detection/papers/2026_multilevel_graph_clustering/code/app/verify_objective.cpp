// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
//
// Portions of this file are derived from the Jet: Multilevel Graph Partitioning project.
// Original license and copyright notices are retained below.
// ***********************************************************************
// 
// Jet: Multilevel Graph Partitioning
//
// Copyright 2023 National Technology & Engineering Solutions of Sandia, LLC
// (NTESS). 
// 
// Under the terms of Contract DE-AC04-94AL85000 with Sandia Corporation,
// the U.S. Government retains certain rights in this software.
// 
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are
// met:
//
// 1. Redistributions of source code must retain the above copyright
// notice, this list of conditions and the following disclaimer.
//
// 2. Redistributions in binary form must reproduce the above copyright
// notice, this list of conditions and the following disclaimer in the
// documentation and/or other materials provided with the distribution.
//
// 3. Neither the name of the Corporation nor the names of the
// contributors may be used to endorse or promote products derived from
// this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY SANDIA CORPORATION "AS IS" AND ANY
// EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
// PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL SANDIA CORPORATION OR THE
// CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
// EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
// PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
// PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
// LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
// NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
// SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
//
// ************************************************************************
#include "core_types.h"
#include "io/header/io.h"
#include "io/header/parse_args.h"
#include "io/header/vertex_weighting.h"
#include "io/header/io_views.hpp"
#include "weighted_graph.h"
#include "objective_helpers.hpp"
#include "cluster_data.hpp"
#include <limits>
#include <memory>

using namespace jet_community;

using scalar_t = ordinal_t;
using rfd_t = cluster_data;
using wg_t = weighted_graph;
using wgt_view_t = Kokkos::View<value_t*, Device>;
using r_policy = Kokkos::RangePolicy<typename Device::execution_space>;
using vtx_view_t = Kokkos::View<ordinal_t*, Device>;

template <bool uniform>
void verify_objective(const wg_t wg, vtx_view_t labels, const base_args args){
    const matrix_t g = wg.mtx;
    const wgt_view_t vtx_w = wg.vtx_w;
    ordinal_t n = g.numRows();
    ordinal_t label_count = n;
    wgt_view_t total("total degree", label_count);
    scalar_t uncut = 0;
    Kokkos::parallel_reduce("count degrees", r_policy(0, n), KOKKOS_LAMBDA(const ordinal_t i, scalar_t& update){
        ordinal_t l = labels(i);
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i+1); j++){
            ordinal_t v = g.graph.entries(j);
            if(l == labels(v)){
                if constexpr(uniform) update += 1;
                else update += g.values(j);
            }
        }
        Kokkos::atomic_add(&total(l), vtx_w(i));
	}, uncut);
    std::unique_ptr<rfd_t> rfd = get_objective(wg, args);
    Kokkos::deep_copy(rfd->total_deg, total);
    rfd->uncut = uncut;
    rfd->update_objective();
    rfd->print(std::cout);
    std::cout << std::endl;
}

void count_boundary(const wg_t wg, vtx_view_t labels){
    ordinal_t boundary = 0;
    const matrix_t g = wg.mtx;
    ordinal_t n = g.numRows();
    Kokkos::parallel_reduce("count boundary", r_policy(0, n), KOKKOS_LAMBDA(const ordinal_t i, ordinal_t& update){
        ordinal_t l = labels(i);
        ordinal_t cut = 0;
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i+1); j++){
            ordinal_t v = g.graph.entries(j);
            if(l != labels(v)) cut++;
        }
        if(cut > 0) update++;
	}, boundary);
    std::cout << "Total boundary vertices: " << boundary << "/" << n << std::endl;
}

int main(int argc, char **argv) {

    const verify_args args = parse_verify_args(argc, argv);
    if(!args.valid) return -1;

    Kokkos::initialize();
    //must scope kokkos-related data
    //so that it falls out of scope b4 finalize
    {
        matrix_t g;
        bool uniform_ew = uses_edge_weights(args);
        if(!load_graph(g, uniform_ew, args.graph_file.c_str())) return -1;
        std::cout << "Vertex Count: " << g.numRows() << "; Undirected Edge Count: " << g.nnz() / 2 << std::endl;
        std::cout << std::endl;

        wg_t wg;
        wg.mtx = g;
        wg.vtx_w = get_vtx_weights(g, args);
        wg.edge_uniform = uniform_ew;

        vtx_view_t part = load_view<vtx_view_t>(g.numRows(), args.cluster_file.c_str());

        std::cout << std::setprecision(9);
        if(wg.edge_uniform) verify_objective<true>(wg, part, args);
        else verify_objective<false>(wg, part, args);
        // count_boundary(wg, part);
    }
    Kokkos::finalize();

    return 0;
}
