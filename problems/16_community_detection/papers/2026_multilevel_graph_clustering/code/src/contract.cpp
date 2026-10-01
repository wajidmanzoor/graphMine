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
#include <limits>
#include <type_traits>
#include <Kokkos_Core.hpp>
#include "memory_store.hpp"
#include "weighted_graph.h"
#include "core_types.h"
#include <thrust/copy.h>
#include <thrust/device_ptr.h>
#include <thrust/execution_policy.h>
#include <thrust/iterator/zip_iterator.h>
#include <thrust/iterator/counting_iterator.h>



namespace jet_community {

namespace contracter {

    // define internal types
    using exec_space = typename matrix_t::execution_space;
    using mem_space = typename matrix_t::memory_space;
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using edge_offset_t = typename matrix_t::size_type;
    using scalar_t = typename matrix_t::value_type;
    using vtx_view_t = Kokkos::View<ordinal_t*, Device>;
    using wgt_view_t = Kokkos::View<scalar_t*, Device>;
    using edge_view_t = Kokkos::View<edge_offset_t*, Device>;
    using edge_subview_t = Kokkos::View<edge_offset_t, Device>;
    using graph_type = typename matrix_t::staticcrsgraph_type;
    using policy_t = Kokkos::RangePolicy<exec_space>;
    using dyn_policy_t = Kokkos::RangePolicy<Kokkos::Schedule<Kokkos::Dynamic>, exec_space>;
    using team_policy_t = Kokkos::TeamPolicy<exec_space>;
    using dyn_team_policy_t = Kokkos::TeamPolicy<Kokkos::Schedule<Kokkos::Dynamic>, exec_space>;
    using member = typename team_policy_t::member_type;
    using wg_t = weighted_graph;
    using mem_t = memory_store;
    constexpr ordinal_t HASH_NULL  = -1;
    constexpr bool is_host_space = std::is_same<typename exec_space::memory_space, typename Kokkos::DefaultHostExecutionSpace::memory_space>::value;

struct is_nonnegative {
    __host__ __device__
    bool operator()(const int x){
        return x >= 0;
    }
};

KOKKOS_INLINE_FUNCTION ordinal_t xorshiftHash(ordinal_t key) {
  ordinal_t x = key;
  x ^= x << 13;
  x ^= x >> 17;
  x ^= x << 5;
  return x;
}

template <bool pval_clone_valid>
struct countingFunctor {

    matrix_t g;
    vtx_view_t vcmap;
    edge_view_t degree_initial;
    wgt_view_t pvals;
    ordinal_t workLength;

    countingFunctor(matrix_t _g,
            vtx_view_t _vcmap,
            edge_view_t _degree_initial,
            wgt_view_t _pvals) :
        g(_g),
        vcmap(_vcmap),
        degree_initial(_degree_initial),
        pvals(_pvals),
        workLength(_g.numRows()) {}

    KOKKOS_INLINE_FUNCTION
        void operator()(const ordinal_t& i) const 
    {
        ordinal_t u = vcmap(i);
        edge_offset_t start = g.graph.row_map(i);
        edge_offset_t end = g.graph.row_map(i + 1);
        ordinal_t nonLoopEdgesTotal = end - start;
        // for uniformly edge weighted graphs
        // pvals(i) is equal to the number of self loops
        // which fine vertex i would contribute to coarse vertex u
        // this optimization allows the memory initialization and stream compaction
        // operations to do less work, and makes the cache utilization of
        // deduplication a bit better
        if constexpr(pval_clone_valid) nonLoopEdgesTotal -= pvals(i);
        Kokkos::atomic_add(&degree_initial(u), nonLoopEdgesTotal);
    }
};

template <bool uniform>
struct combineAndDedupe {
    matrix_t g;
    vtx_view_t vcmap;
    vtx_view_t htable;
    wgt_view_t hvals;
    edge_view_t hrow_map;
    edge_view_t counts;
    vtx_view_t vtx;

    combineAndDedupe(matrix_t _g,
            vtx_view_t _vcmap,
            vtx_view_t _htable,
            wgt_view_t _hvals,
            edge_view_t _hrow_map,
            edge_view_t _counts,
            vtx_view_t _vtx) :
            g(_g),
            vcmap(_vcmap),
            htable(_htable),
            hvals(_hvals),
            hrow_map(_hrow_map),
            counts(_counts),
            vtx(_vtx) {}

    // uses linear probing to resolve hash conflicts
    KOKKOS_INLINE_FUNCTION
        edge_offset_t insert(const edge_offset_t& hash_start, const edge_offset_t& size, const ordinal_t& u, const ordinal_t& i) const {
            edge_offset_t offset = xorshiftHash(u) % static_cast<uint32_t>(size);
            while(true){
                if(htable(hash_start + offset) == HASH_NULL){
                    if(Kokkos::atomic_compare_exchange(&htable(hash_start + offset), HASH_NULL, u) == HASH_NULL){
                        Kokkos::atomic_add(&counts(i), 1);
                    }
                }
                if(htable(hash_start + offset) == u){
                    return offset;
                } else {
                    offset++;
                    if(offset >= size) offset -= size;
                }
            }
        }

    KOKKOS_INLINE_FUNCTION
        void operator()(const member& thread) const
    {
        const ordinal_t x = vtx(thread.league_rank());
        const ordinal_t i = vcmap(x);
        const edge_offset_t start = g.graph.row_map(x);
        const edge_offset_t end = g.graph.row_map(x + 1);
        const edge_offset_t hash_start = hrow_map(i);
        const edge_offset_t size = hrow_map(i + 1) - hash_start;
        Kokkos::parallel_for(Kokkos::TeamThreadRange(thread, start, end), [&](const edge_offset_t j){
            ordinal_t u = vcmap(g.graph.entries(j));
            if(i == u) return;
            edge_offset_t offset = insert(hash_start, size, u, i);
            if constexpr(uniform) Kokkos::atomic_add(&hvals(hash_start + offset), 1);
            else Kokkos::atomic_add(&hvals(hash_start + offset), g.values(j));
        });
    }

    KOKKOS_INLINE_FUNCTION
        void operator()(const ordinal_t& xx) const
    {
        const ordinal_t x = vtx(xx);
        const ordinal_t i = vcmap(x);
        const edge_offset_t start = g.graph.row_map(x);
        const edge_offset_t end = g.graph.row_map(x + 1);
        const edge_offset_t hash_start = hrow_map(i);
        const edge_offset_t size = hrow_map(i + 1) - hash_start;
        for(edge_offset_t j = start; j < end; j++){
            ordinal_t u = vcmap(g.graph.entries(j));
            if(i == u) continue;
            edge_offset_t offset = insert(hash_start, size, u, i);
            if constexpr(uniform) Kokkos::atomic_add(&hvals(hash_start + offset), 1);
            else Kokkos::atomic_add(&hvals(hash_start + offset), g.values(j));
        }
    }
};

void fast_fill(vtx_view_t a, ordinal_t V){
    edge_offset_t width = a.extent(0);
    edge_offset_t w8 = (width + 7)/8;
    Kokkos::parallel_for("fast fill", policy_t(0, w8), KOKKOS_LAMBDA(const edge_offset_t i){
        a(i) = V;
        a(i + w8) = V;
        a(i + 2*w8) = V;
        a(i + 3*w8) = V;
        a(i + 4*w8) = V;
        a(i + 5*w8) = V;
        a(i + 6*w8) = V;
        // this one may be out of bounds for even arbitrarily large width
        // technically some of the other ones can also be out of bounds for width < 42
        if(i + 7*w8 < width) a(i + 7*w8) = V;
    });
}

template <bool uniform, bool pval_clone_valid>
wg_t build_coarse_graph(const wg_t curr_level,
    const vtx_view_t vcmap,
    const ordinal_t nc,
    mem_t& mem) {

    matrix_t g = curr_level.mtx;
    ordinal_t n = g.numRows();
    double multiplier = 1.0;
    if(nc > n * 0.5) multiplier = 1.5;
    if(g.nnz() * multiplier > mem.p_mem.entries.extent(0)){
        // rare edge-case
        multiplier = 1.0;
    }

    Kokkos::Timer timer;

    // determine upper bound on coarse vertex sizes
    edge_view_t hrow_map = Kokkos::subview(mem.p_mem.row_map, std::make_pair((ordinal_t)0, nc + 1));
    wgt_view_t pvals_clone = mem.p_mem.pvals_clone;
    Kokkos::deep_copy(exec_space(), hrow_map, 0);
    countingFunctor<pval_clone_valid> countF(g, vcmap, hrow_map, pvals_clone);
    Kokkos::parallel_for("count edges per coarse vertex (also compute coarse vertex weights)", policy_t(0, n), countF);

    // allocate hash tables for each coarse vertex
    edge_offset_t hash_size = 0;
    Kokkos::parallel_scan("scan offsets", policy_t(0, nc + 1), KOKKOS_LAMBDA(const ordinal_t i, edge_offset_t& update, const bool final){
        edge_offset_t val = hrow_map(i) * multiplier;
        if(final){
            hrow_map(i) = update;
        }
        update += val;
    }, mem.s_mem.edge_scan_host);
    exec_space().fence();
    hash_size = mem.s_mem.edge_scan_host();
    vtx_view_t htable = Kokkos::subview(mem.p_mem.entries, std::make_pair((edge_offset_t)0, hash_size));
    fast_fill(htable, HASH_NULL);
    // Kokkos::deep_copy(exec_space(), htable, HASH_NULL);
    wgt_view_t hvals = Kokkos::subview(mem.p_mem.vals, std::make_pair((edge_offset_t)0, hash_size));
    Kokkos::deep_copy(exec_space(), hvals, 0);

    // accumulates edge totals per coarse vertex
    edge_view_t coarse_row_map_f("edges_per_source", nc + 1);
    ordinal_t small = mem.o_mem.offset_mid;
    ordinal_t large = mem.o_mem.offset_mid2 - small;
    ordinal_t largest = n - mem.o_mem.offset_mid2;
    vtx_view_t vtx_small = Kokkos::subview(mem.o_mem.order2, std::make_pair(static_cast<ordinal_t>(0), small));
    vtx_view_t vtx_large = Kokkos::subview(mem.o_mem.order2, std::make_pair(small, mem.o_mem.offset_mid2));
    vtx_view_t vtx_largest = Kokkos::subview(mem.o_mem.order2, std::make_pair(mem.o_mem.offset_mid2, n));
    // identifies unique coarse edges
    combineAndDedupe<uniform> cnd_small(g, vcmap, htable, hvals, hrow_map, coarse_row_map_f, vtx_small);
    combineAndDedupe<uniform> cnd_large(g, vcmap, htable, hvals, hrow_map, coarse_row_map_f, vtx_large);
    combineAndDedupe<uniform> cnd_largest(g, vcmap, htable, hvals, hrow_map, coarse_row_map_f, vtx_largest);
    Kokkos::parallel_for("deduplicate", team_policy_t(large, Kokkos::AUTO), cnd_large);
    Kokkos::parallel_for("deduplicate", team_policy_t(largest, 1024), cnd_largest);
    Kokkos::parallel_for("deduplicate", policy_t(0, small), cnd_small);
    edge_offset_t old_size = hash_size;
    // build row map of coarse graph
    Kokkos::parallel_scan("scan offsets", policy_t(0, nc + 1), KOKKOS_LAMBDA(const ordinal_t i, edge_offset_t& update, const bool final){
        edge_offset_t val = coarse_row_map_f(i);
        if(final){
            coarse_row_map_f(i) = update;
        }
        update += val;
    }, mem.s_mem.edge_scan_host);
    exec_space().fence();
    hash_size = mem.s_mem.edge_scan_host();

    // segmented stream compaction
    // segments have size equal to max representable number of ordinal_t
    // this allows storing offsets directly into entries_coarse, even if edge_offset_t is a larger type
    vtx_view_t entries_coarse(Kokkos::ViewAllocateWithoutInitializing("coarse entries"), hash_size);
    wgt_view_t wgts_coarse(Kokkos::ViewAllocateWithoutInitializing("coarse weights"), hash_size);
    Kokkos::fence();
    edge_offset_t stream_compact_start = 0;
    edge_offset_t coarse_start = 0;
    while(stream_compact_start < old_size) {
        ordinal_t* htb = htable.data() + stream_compact_start;
        ordinal_t width = std::numeric_limits<ordinal_t>::max();
        if(stream_compact_start + width >= old_size) width = old_size - stream_compact_start;
        thrust::counting_iterator<ordinal_t> iter(0);
        ordinal_t* ec = entries_coarse.data() + coarse_start;
        ordinal_t* ec_end;
        if(!is_host_space) ec_end = thrust::copy_if(thrust::device, iter, iter + width, htb, ec, is_nonnegative());
        else ec_end = thrust::copy_if(thrust::host, iter, iter + width, htb, ec, is_nonnegative());
        ordinal_t compacted_width = ec_end - ec;
        Kokkos::parallel_for("read", policy_t(0, compacted_width), KOKKOS_LAMBDA(const ordinal_t dst_base){
            edge_offset_t dst_offset = coarse_start + dst_base;
            edge_offset_t src_offset = entries_coarse(dst_offset) + stream_compact_start;
            entries_coarse(dst_offset) = htable(src_offset);
            wgts_coarse(dst_offset) = hvals(src_offset);
        });
        coarse_start += compacted_width;
        stream_compact_start += width;
    }

    graph_type gc_graph(entries_coarse, coarse_row_map_f);
    matrix_t gc("gc", nc, wgts_coarse, gc_graph);
    wg_t next_level;
    next_level.mtx = gc;
    next_level.edge_uniform = false;
    return next_level;
}

    // explicit template instantiations
    template wg_t build_coarse_graph<true, true>(const wg_t curr_level,
        const vtx_view_t vcmap,
        const ordinal_t nc,
        mem_t& mem);

    template wg_t build_coarse_graph<true, false>(const wg_t curr_level,
        const vtx_view_t vcmap,
        const ordinal_t nc,
        mem_t& mem);

    template wg_t build_coarse_graph<false, true>(const wg_t curr_level,
        const vtx_view_t vcmap,
        const ordinal_t nc,
        mem_t& mem);

    template wg_t build_coarse_graph<false, false>(const wg_t curr_level,
        const vtx_view_t vcmap,
        const ordinal_t nc,
        mem_t& mem);

}

}
