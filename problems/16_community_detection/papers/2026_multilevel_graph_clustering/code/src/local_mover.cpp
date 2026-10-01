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
#include <Kokkos_Core.hpp>
#include "KokkosSparse_CrsMatrix.hpp"
#include "memory_store.hpp"
#include "cluster_data.hpp"
#include "weighted_graph.h"
#include "header/ordering.h"

namespace jet_community {

namespace local_move_heuristic {

    // define internal types
    using exec_space = typename matrix_t::execution_space;
    using mem_space = typename matrix_t::memory_space;
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using edge_offset_t = typename matrix_t::size_type;
    using scalar_t = typename matrix_t::value_type;
    using vtx_vt = Kokkos::View<ordinal_t*, exec_space>;
    using wgt_vt = Kokkos::View<scalar_t*, Device>;
    using edge_view_t = Kokkos::View<edge_offset_t*, Device>;
    using vtx_pin_st = Kokkos::View<ordinal_t, Kokkos::SharedHostPinnedSpace>;
    using obj_vt = Kokkos::View<float*, Device>;
    using policy_t = Kokkos::RangePolicy<exec_space>;
    using team_policy_t = Kokkos::TeamPolicy<exec_space>;
    using member = typename team_policy_t::member_type;
    using refine_data = cluster_data;
    using mem_t = memory_store;
    using wg_t = weighted_graph;
    constexpr float OBJ_MIN = std::numeric_limits<float>::lowest();
    constexpr ordinal_t NULL_PART = -1;
    constexpr ordinal_t HASH_RECLAIM = -2;
    constexpr ordinal_t NO_MOVE = -3;
    constexpr ordinal_t NEW_PART = -4;
    constexpr ordinal_t LARGE_CUTOFF = ordering::LARGE_CUTOFF;
    constexpr float afterburner_eps = 0.1;

    KOKKOS_INLINE_FUNCTION uint32_t hash(uint32_t x) {
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        return x;
    }

// vertex-part connectivity datastructure
struct cdata_t {
    edge_view_t conn_offsets;
    wgt_vt conn_vals;
    vtx_vt conn_entries;
    // matrix wrapper of above views
    matrix_t c_graph;
    vtx_vt conn_table_sizes;
    bool init = false;
};

void relabel_contiguously(vtx_vt labels, refine_data& rfd, mem_t& mem){
	ordinal_t n = labels.extent(0);
    ordinal_t initial_count = rfd.label_count;
	vtx_vt used = Kokkos::subview(mem.s_mem.vtx1, std::make_pair((ordinal_t)0, initial_count));
    Kokkos::deep_copy(exec_space(), used, 0);
    // some vertices can have zero degree so some labels can have zero total degree
    // therefore we can't use rfd.total_deg to determine which labels are in use
	Kokkos::parallel_for("mark labels", policy_t(0, n), KOKKOS_LAMBDA(const ordinal_t i){
		used(labels(i)) = 1;
	});
    ordinal_t t_labels = 0;
    wgt_vt swap_total_deg = Kokkos::subview(mem.p_mem.pvals, std::make_pair((ordinal_t)0, initial_count));
    wgt_vt total_deg = Kokkos::subview(rfd.total_deg, std::make_pair((ordinal_t)0, initial_count));
    Kokkos::parallel_scan("count labels and compact total_deg", policy_t(0, initial_count), KOKKOS_LAMBDA(const ordinal_t i, ordinal_t& update, const bool final){
		if(used(i) > 0){
			if(final){
                used(i) = update;
                swap_total_deg(update) = total_deg(i);
            }
			update++;
		}
	}, t_labels);
    swap_total_deg = Kokkos::subview(mem.p_mem.pvals, std::make_pair((ordinal_t)0, t_labels));
    total_deg = Kokkos::subview(rfd.total_deg, std::make_pair((ordinal_t)0, t_labels));
    Kokkos::deep_copy(exec_space(), total_deg, swap_total_deg);
	Kokkos::parallel_for("relabel", policy_t(0, n), KOKKOS_LAMBDA(const ordinal_t i){
		labels(i) = used(labels(i));
	});
    rfd.label_count = t_labels;
}

// select the prefix of the given movelist that maximizes objective delta
template <bool uniform>
vtx_vt afterburner_filter_strict(const wg_t& wg, const vtx_vt moves, const vtx_vt& part, refine_data& rfd, mem_t& mem, double& diff) {
    const matrix_t& g = wg.mtx;
    vtx_vt dest_part = mem.p_mem.dest_part;
    obj_vt save_gains = mem.p_mem.obj_persistent;
    float penalty_mod = rfd.get_penalty_modifier();
    ordinal_t n = g.numRows();
    ordinal_t num_moves = moves.extent(0);
    vtx_vt prio = Kokkos::subview(mem.s_mem.vtx1, std::make_pair((ordinal_t)0, n));
    Kokkos::deep_copy(exec_space(), prio, n+1);
    Kokkos::parallel_for("set prios", policy_t(0, num_moves), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = moves(x);
        prio(i) = x;
    });
    Kokkos::parallel_for("afterburner heuristic", policy_t(0, num_moves), KOKKOS_LAMBDA(const ordinal_t& x){
        ordinal_t i = moves(x);
        ordinal_t best = dest_part(i);
        ordinal_t p = part(i);
        float w = wg.vtx_w(i);
        float multi = w*penalty_mod;
        float obj_change = save_gains(i);
        // compute cut change
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i + 1); j++){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            if(prio(v) < prio(i)){
                ordinal_t vpart = dest_part(v);
                obj_change -= (vpart == p) ? wgt : 0;
                obj_change += (vpart == best && best != NEW_PART) ? wgt : 0;
                vpart = part(v);
                obj_change += (vpart == p) ? wgt : 0;
                obj_change -= (vpart == best) ? wgt : 0;
            }
        }
        for(ordinal_t jx = 0; jx < x; jx++){
            ordinal_t v = moves(jx);
            ordinal_t vpart = dest_part(v);
            float wgt = -multi*wg.vtx_w(v);
            obj_change -= (vpart == p) ? wgt : 0;
            obj_change += (vpart == best && best != NEW_PART) ? wgt : 0;
            vpart = part(v);
            obj_change += (vpart == p) ? wgt : 0;
            obj_change -= (vpart == best) ? wgt : 0;
        }
        save_gains(i) = obj_change;
    });
    Kokkos::parallel_scan("check change", policy_t(0, num_moves), KOKKOS_LAMBDA(const ordinal_t x, float& update, const bool final){
        ordinal_t i = moves(x);
        update += save_gains(i);
        if(final){
            save_gains(i) = update;
        }
    });
    using argmax_reducer_t = Kokkos::MaxFirstLoc<float, ordinal_t, Kokkos::HostSpace>;
    using argmax_t = typename argmax_reducer_t::value_type;
    argmax_t result{-1.0, n};
    Kokkos::parallel_reduce("find best", policy_t(0, num_moves), KOKKOS_LAMBDA(const ordinal_t x, argmax_t& update){
        ordinal_t i = moves(x);
        float val = save_gains(i);
        if(val > update.val){
            update.val = val;
            update.loc = x;
        }
    }, argmax_reducer_t(result));
    vtx_vt output_moves;
    ordinal_t truncate = 0;
    diff = 0;
    // val may be less than zero, but appear as zero or even positive, due to catastrophic cancellation and floating-point roundoff errors
    // this problem can't be entirely avoided with fixed precision floating point numbers
    if(result.loc < num_moves && result.val > 0){
        truncate = result.loc + 1;
        diff = result.val*2;
    }
    output_moves = Kokkos::subview(moves, std::make_pair((ordinal_t)0, truncate));
    // this must be set for find_affected_smaller
    // since we select a prefix of moves, we only need to adjust it when it is larger than the prefix length
    if(mem.o_mem.last_scan_large > truncate) mem.o_mem.last_scan_large = truncate;
    if(mem.o_mem.last_scan_large2 > truncate) mem.o_mem.last_scan_large2 = truncate;
    return output_moves;
}

// for vertices set to move a new (as in not currently existing) cluster
// find a valid unused cluster id
template <bool constrained>
void set_new_cluster_ids(const vtx_vt& moves, const vtx_vt& part, refine_data& rfd, mem_t& mem, vtx_vt constraint){

    vtx_vt vtx1 = mem.s_mem.vtx1;
    wgt_vt total_deg = rfd.total_deg;
    vtx_vt dest_part = mem.p_mem.dest_part;
    ordinal_t n_moves = moves.extent(0);
    // find viable cluster labels for new parts    
    Kokkos::parallel_scan("get new part moves", policy_t(0, n_moves), KOKKOS_LAMBDA(const ordinal_t x, ordinal_t& update, const bool final){
        ordinal_t i = moves(x);
        if(dest_part(i) == NEW_PART){
            if(final){
                vtx1(update) = i;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    exec_space().fence();
    ordinal_t new_parts = mem.s_mem.scan_host();
    if(new_parts > 0){
        ordinal_t curr_labels = rfd.label_count;
        vtx_vt has_members = Kokkos::subview(mem.s_mem.zeros1, std::make_pair((ordinal_t)0, curr_labels));
        Kokkos::parallel_for("set used labels", policy_t(0, part.extent(0)), KOKKOS_LAMBDA(const ordinal_t i){
            ordinal_t c = part(i);
            has_members(c) = 1;
        });
        ordinal_t avail = 0;
        Kokkos::parallel_scan("find available labels", policy_t(0, rfd.label_count), KOKKOS_LAMBDA(const ordinal_t i, ordinal_t& update, const bool final){
            if(has_members(i) == 0){
                if(final){
                    if(update < new_parts){
                        ordinal_t x = vtx1(update);
                        dest_part(x) = i;
                        if(constrained) constraint(i) = constraint(part(x));
                    }
                }
                update++;
            }
        }, mem.s_mem.scan_host);
        exec_space().fence();
        avail = mem.s_mem.scan_host();
        // must reset this memory to zero for later usage
        Kokkos::deep_copy(exec_space(), has_members, 0);
        if(avail < new_parts){
            ordinal_t needed = new_parts - avail;
            rfd.label_count += needed;
            Kokkos::parallel_for("set additional labels", policy_t(avail, new_parts), KOKKOS_LAMBDA(const ordinal_t x){
                ordinal_t i = vtx1(x);
                ordinal_t dest = (x - avail) + curr_labels;
                dest_part(i) = dest;
                if(constrained) constraint(dest) = constraint(part(i));
            });
            wgt_vt td_subview = Kokkos::subview(total_deg, std::make_pair(curr_labels, rfd.label_count));
            // set new labels to have zero degree
            Kokkos::deep_copy(exec_space(), td_subview, 0);
        }
    }
}

// in this kernel every candidate move
// is reevaluated by considering the effect of the other candidate moves
// a move is considered to occur before another according to their potential gains
// and the vertex ids
template <bool uniform>
struct afterburner_kernel {
    const vtx_vt vtx_list;
    const matrix_t g;
    const vtx_vt part;
    const vtx_vt dest_part;
    vtx_vt swap_bit;
    const wgt_vt vtx_w;
    const obj_vt save_gains;
    const float penalty_mod;

    afterburner_kernel(const vtx_vt _vtx_list,
        const wg_t& _wg,
        const vtx_vt& _part,
        const mem_t& _mem,
        const refine_data& _rfd) : 
        vtx_list(_vtx_list),
        g(_wg.mtx),
        part(_part),
        dest_part(_mem.p_mem.dest_part),
        swap_bit(_mem.s_mem.zeros1),
        vtx_w(_wg.vtx_w),
        save_gains(_mem.p_mem.obj_persistent),
        penalty_mod(_rfd.get_penalty_modifier()) {}

    KOKKOS_FUNCTION
    void operator()(const ordinal_t x) const {
        float change = 0;
        ordinal_t i = vtx_list(x);
        ordinal_t best = dest_part(i);
        ordinal_t p = part(i);
        scalar_t w = vtx_w(i);
        float multi = w*penalty_mod;
        float igain = save_gains(i);
        ordinal_t hi = hash(i);
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i + 1); j++){
            ordinal_t v = g.graph.entries(j);
            float vgain = save_gains(v);
            //adjust local gain if v has higher priority than i
            if((vgain - igain) >= afterburner_eps || (abs(vgain - igain) < afterburner_eps && static_cast<ordinal_t>(hash(v)) < hi)){
                ordinal_t vpart = dest_part(v);
                scalar_t wgt;
                if constexpr(uniform) wgt = 1;
                else wgt = g.values(j);
                float q = static_cast<float>(wgt) - multi*vtx_w(v);
                change -= (vpart == p) ? q : 0;
                change += (vpart == best && best != NEW_PART) ? q : 0;
                vpart = part(v);
                change += (vpart == p) ? q : 0;
                change -= (vpart == best) ? q : 0;
            }
        }
        if(igain + change >= 0){
            swap_bit(i) = 1;
        }
    }

    KOKKOS_INLINE_FUNCTION
    void operator()(const member& t) const {
        float change = 0;
        ordinal_t i = vtx_list(t.league_rank());
        ordinal_t best = dest_part(i);
        ordinal_t p = part(i);
        scalar_t w = vtx_w(i);
        float multi = w*penalty_mod;
        float igain = save_gains(i);
        ordinal_t hi = hash(i);
        Kokkos::parallel_reduce(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [&](const edge_offset_t j, float& update){
            ordinal_t v = g.graph.entries(j);
            float vgain = save_gains(v);
            //adjust local gain if v has higher priority than i
            if((vgain - igain) >= afterburner_eps || (abs(vgain - igain) < afterburner_eps && static_cast<ordinal_t>(hash(v)) < hi)){
                ordinal_t vpart = dest_part(v);
                scalar_t wgt;
                if constexpr(uniform) wgt = 1;
                else wgt = g.values(j);
                float q = static_cast<float>(wgt) - multi*vtx_w(v);
                update -= (vpart == p) ? q : 0;
                update += (vpart == best && best != NEW_PART) ? q : 0;
                vpart = part(v);
                update += (vpart == p) ? q : 0;
                update -= (vpart == best) ? q : 0;
            }
        }, change);
        if(t.team_rank() == 0){
            if(igain + change >= 0){
                swap_bit(i) = 1;
            }
        }
    }
};

// re-evaluates candidate moves in the context of each other, using an ordering condition
// negative gain candidates are filtered out
template <bool uniform>
vtx_vt afterburner_filter(vtx_vt candidates, const wg_t& wg, const vtx_vt& part, refine_data& rfd, mem_t& mem){
    const matrix_t& g = wg.mtx;
    ordinal_t n = g.numRows();
    float penalty_mod = rfd.get_penalty_modifier();
    // this must be set by candidates_and_destinations
    ordinal_t big_begin = mem.o_mem.last_scan_large;
    ordinal_t biggest_begin = mem.o_mem.last_scan_large2;
    ordinal_t n_moves = candidates.extent(0);
    ordinal_t small = big_begin;
    ordinal_t big = biggest_begin - big_begin;
    ordinal_t biggest = n_moves - biggest_begin;
    vtx_vt small_vtx = Kokkos::subview(candidates, std::make_pair(static_cast<ordinal_t>(0), small));
    vtx_vt large_vtx = Kokkos::subview(candidates, std::make_pair(big_begin, biggest_begin));
    vtx_vt largest_vtx = Kokkos::subview(candidates, std::make_pair(biggest_begin, n_moves));
    vtx_vt swap_bit = mem.s_mem.zeros1;
    vtx_vt vtx2 = mem.s_mem.vtx2;
    afterburner_kernel<uniform> afterburner_small(small_vtx, wg, part, mem, rfd);
    afterburner_kernel<uniform> afterburner_large(large_vtx, wg, part, mem, rfd);
    afterburner_kernel<uniform> afterburner_largest(largest_vtx, wg, part, mem, rfd);
    Kokkos::parallel_for("afterburner heuristic (small vtx)", policy_t(0, small), afterburner_small);
    Kokkos::parallel_for("afterburner heuristic (large vtx)", team_policy_t(big, Kokkos::AUTO), afterburner_large);
    Kokkos::parallel_for("afterburner heuristic (largest vtx)", team_policy_t(biggest, 1024), afterburner_largest);
    vtx_pin_st pin_host = mem.s_mem.pin_host;
    vtx_pin_st pin_host2 = mem.s_mem.pin_host2;
    //scan all vertices that passed the post filter
    Kokkos::parallel_scan("filter beneficial moves", policy_t(0, n_moves), KOKKOS_LAMBDA(const ordinal_t i, ordinal_t& update, const bool final){
        if(final && i == big_begin){
            pin_host() = update;
        }
        if(final && i == biggest_begin){
            pin_host2() = update;
        }
        if(swap_bit(candidates(i))){
            if(final){
                vtx2(update) = candidates(i);
                // reset to zero for later use
                swap_bit(candidates(i)) = 0;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    exec_space().fence();
    ordinal_t old_n_moves = n_moves;
    n_moves = mem.s_mem.scan_host();
    if(big_begin < old_n_moves){
        // this must be set for find_affected_smaller
        mem.o_mem.last_scan_large = pin_host();
    } else {
        mem.o_mem.last_scan_large = n_moves;
    }
    if(biggest_begin < old_n_moves){
        mem.o_mem.last_scan_large2 = pin_host2();
    } else {
        mem.o_mem.last_scan_large2 = n_moves;
    }
    vtx_vt moves = Kokkos::subview(vtx2, std::make_pair(static_cast<ordinal_t>(0), n_moves));

    return moves;
}

template <bool uniform, bool constrained>
struct select_destinations {
    const vtx_vt vtx_list;
    const matrix_t c_graph;
    const vtx_vt part;
    vtx_vt dest_part;
    const vtx_vt constraint;
    const wgt_vt vtx_w;
    const wgt_vt pvals;
    const wgt_vt total_deg;
    obj_vt save_gains;
    const float penalty_mod;
    const float filter_ratio;
    const ordinal_t n;
    const bool truncated;

    select_destinations(const vtx_vt _vtx_list,
        const wg_t& _wg,
        const matrix_t& _c_graph,
        const vtx_vt& _part,
        const vtx_vt& _constraint,
        const mem_t& _mem,
        const refine_data& _rfd,
        const float _filter_ratio,
        const bool _truncated) : 
        vtx_list(_vtx_list),
        c_graph(_c_graph),
        part(_part),
        dest_part(_mem.p_mem.dest_part),
        constraint(_constraint),
        vtx_w(_wg.vtx_w),
        pvals(_mem.p_mem.pvals),
        total_deg(_rfd.total_deg),
        save_gains(_mem.p_mem.obj_persistent),
        penalty_mod(_rfd.get_penalty_modifier()),
        filter_ratio(_filter_ratio),
        n(_wg.mtx.numRows()),
        truncated(_truncated) {}

    KOKKOS_FUNCTION
    void operator()(const ordinal_t x) const {
        ordinal_t i = truncated ? x : vtx_list(x);
        if(dest_part(i) == NO_MOVE){
            return;
        }
        ordinal_t best = NO_MOVE;
        scalar_t w = vtx_w(i);
        float multi = w*penalty_mod;
        ordinal_t p = part(i);
        float p_conn = pvals(i) - (total_deg(p) - w)*multi;
        // b_conn must be at least this value to pass filter
        float b_conn = p_conn*(1.0 - filter_ratio);
        if(p_conn < 0) b_conn = 0;
        edge_offset_t start = c_graph.graph.row_map(i);
        edge_offset_t end = c_graph.graph.row_map(i+1);
        //finds potential destination as most connected part excluding p
        for(edge_offset_t j = start; j < end; j++){
            scalar_t j_val;
            if constexpr(uniform) j_val = 1;
            else j_val = c_graph.values(j);
            if(j_val > 0 && j_val >= b_conn){
                ordinal_t px = c_graph.graph.entries(j);
                if(constrained && constraint(px) != constraint(p)) continue;
                float j_conn = j_val - static_cast<float>(total_deg(px))*multi;
                if(j_conn >= b_conn){
                    // this is not deterministic unless the case j_conn == b_conn is handled properly
                    b_conn = j_conn;
                    best = px;
                }
            }
        }
        float gain = OBJ_MIN;
        if(best != NO_MOVE){
            gain = b_conn - p_conn;
        } else if(p_conn < 0){
            gain = -p_conn;
            best = NEW_PART;
        }
        save_gains(i) = gain;
        dest_part(i) = best;
    }

    KOKKOS_INLINE_FUNCTION
    void operator()(const member& t) const {
        ordinal_t i = vtx_list(t.league_rank());
        if(dest_part(i) == NO_MOVE){
            return;
        }
        ordinal_t team_size = t.team_size();
        scalar_t w = vtx_w(i);
        float multi = w*penalty_mod;
        edge_offset_t start = c_graph.graph.row_map(i);
        edge_offset_t end = c_graph.graph.row_map(i+1);
        ordinal_t p = part(i);
        float p_conn = pvals(i) - (total_deg(p) - w)*multi;
        // j_conn must be at least this value to pass filter
        float maxl = p_conn*(1.0 - filter_ratio);
        ordinal_t argmax = NO_MOVE;
        if(p_conn < 0){
            maxl = 0;
            argmax = NEW_PART;
        }
        //finds potential destination as most connected part excluding p
        for(edge_offset_t j = start + t.team_rank(); j < end; j += team_size){
            scalar_t j_val;
            if constexpr(uniform) j_val = 1;
            else j_val = c_graph.values(j);
            if(j_val > 0 && j_val >= maxl){
                ordinal_t px = c_graph.graph.entries(j);
                if(constrained && constraint(px) != constraint(p)) continue;
                float j_conn = j_val - static_cast<float>(total_deg(px))*multi;
                if(j_conn >= maxl){
                    // this is not deterministic unless the case j_conn == maxl is handled properly
                    argmax = px;
                    maxl = j_conn;
                }
            }
        }
        maxl -= p_conn;
        // no_move has a "gain" of negative infinity for the purposes of the afterburner filter
        if(argmax == NO_MOVE) maxl = OBJ_MIN;
        float oldmaxl = maxl;
        t.team_reduce(Kokkos::Max<float, mem_space>(save_gains(i)), maxl);
        // set the threads that don't have the max gain to a large argmax
        // so that they effectively don't participate in the next reduction
        if(save_gains(i) != oldmaxl) argmax = n + 1;
        t.team_reduce(Kokkos::Min<ordinal_t, mem_space>(dest_part(i)), argmax);
    }
};

// determines which vertices (if any) should be moved to another part to improve objective
// uniform should be true if and only if c_graph is the top level input graph, and that graph is uniformly edge-weighted
template <bool uniform, bool constrained>
vtx_vt candidates_and_destinations(const wg_t& wg, const matrix_t& c_graph, const vtx_vt& part, refine_data& rfd, mem_t& mem, float filter_ratio, vtx_vt constraint){
    const matrix_t& g = wg.mtx;
    ordinal_t n = g.numRows();
    ordinal_t num_pos = 0;
    vtx_vt dest_part = mem.p_mem.dest_part;
    vtx_vt vtx1 = mem.s_mem.vtx1;
    vtx_vt order1 = mem.o_mem.order1;
    ordinal_t big_begin = mem.o_mem.offset_large;
    ordinal_t biggest_begin = mem.o_mem.offset_large2;
    vtx_vt small_vtx = Kokkos::subview(order1, std::make_pair(static_cast<ordinal_t>(0), big_begin));
    vtx_vt large_vtx = Kokkos::subview(order1, std::make_pair(big_begin, biggest_begin));
    vtx_vt largest_vtx = Kokkos::subview(order1, std::make_pair(biggest_begin, n));
    // if input label count is smaller than LARGE_CUTOFF, then all tables are also smaller than LARGE_CUTOFF
    // TODO: not true due to *2
    bool truncated = (rfd.label_count <= LARGE_CUTOFF);
    if(truncated){
        select_destinations<uniform, constrained> select_small(small_vtx, wg, c_graph, part, constraint, mem, rfd, filter_ratio, true);
        Kokkos::parallel_for("argmax destination part (small vtx)", policy_t(0, n), select_small);
    }
    else {
        select_destinations<uniform, constrained> select_small(small_vtx, wg, c_graph, part, constraint, mem, rfd, filter_ratio, false);
        select_destinations<uniform, constrained> select_large(large_vtx, wg, c_graph, part, constraint, mem, rfd, filter_ratio, false);
        select_destinations<uniform, constrained> select_largest(largest_vtx, wg, c_graph, part, constraint, mem, rfd, filter_ratio, false);
        Kokkos::parallel_for("argmax destination part (small vtx)", policy_t(0, big_begin), select_small);
        Kokkos::parallel_for("argmax destination part (large vtx)", team_policy_t(biggest_begin - big_begin, Kokkos::AUTO), select_large);
        Kokkos::parallel_for("argmax destination part (largest vtx)", team_policy_t(n - biggest_begin, 1024), select_largest);
    }
    vtx_pin_st pin_host = mem.s_mem.pin_host;
    vtx_pin_st pin_host2 = mem.s_mem.pin_host2;
    big_begin = mem.o_mem.offset_large;
    biggest_begin = mem.o_mem.offset_large2;
    // write all unlocked vertices that passed the above filter into an unordered list
    // output count of such vertices into num_pos
    // order1 is already organized into two buckets by degree > or <= 128
    Kokkos::parallel_scan("filter potentially viable moves", policy_t(0, n), KOKKOS_LAMBDA(const ordinal_t x, ordinal_t& update, const bool final){
        if(final && x == big_begin){
            pin_host() = update;
        }
        if(final && x == biggest_begin){
            pin_host2() = update;
        }
        ordinal_t i = order1(x);
        ordinal_t best = dest_part(i);
        if(best != NO_MOVE){
            if(final){
                vtx1(update) = i;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    exec_space().fence();
    num_pos = mem.s_mem.scan_host();
    if(big_begin < n){
        mem.o_mem.last_scan_large = pin_host();
    } else {
        mem.o_mem.last_scan_large = num_pos;
    }
    if(biggest_begin < n){
        mem.o_mem.last_scan_large2 = pin_host2();
    } else {
        mem.o_mem.last_scan_large2 = num_pos;
    }
    //truncate scratch views by num_pos
    vtx_vt candidates = Kokkos::subview(vtx1, std::make_pair(static_cast<ordinal_t>(0), num_pos));

    return candidates;
}

// stream-compacts order2 for the vertices adjacent to any changed vertex
// assumes a large percentage of all vertices are moved
vtx_vt find_affected(const wg_t& wg, const vtx_vt swaps, mem_t& mem){
    const matrix_t& g = wg.mtx;
    ordinal_t total_moves = swaps.extent(0);
    vtx_vt swap_bit = mem.s_mem.zeros1;
    ordinal_t total = 0;
    vtx_vt vtx1 = mem.s_mem.vtx1;
    vtx_vt order1 = mem.o_mem.order1;
    vtx_vt order2 = mem.o_mem.order2;
    vtx_vt dest_cache = mem.p_mem.dest_part;
    Kokkos::parallel_for("mark", policy_t(0, total_moves), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = swaps(x);
        swap_bit(i) = 1;
    });
    // usually, but not always, faster than directly marking adjacencies of moved vertices, since we can break out of the loop
    // also can't use a team here because we want to be able to exit the loop early
    Kokkos::parallel_for("check adjacent", policy_t(0, g.numRows()), KOKKOS_LAMBDA(const ordinal_t i){
        if(swap_bit(i) == 1) return;
        edge_offset_t limit = g.graph.row_map(i) + LARGE_CUTOFF;
        if(g.graph.row_map(i+1) < limit) limit = g.graph.row_map(i+1);
        for(edge_offset_t j = g.graph.row_map(i); j < limit; j++){
            ordinal_t v = g.graph.entries(j);
            if(swap_bit(v) == 1){
                swap_bit(i) = 2;
                break;
            }
        }
    });
    ordinal_t bigger_begin = mem.o_mem.offset_large;
    Kokkos::parallel_scan("collect vtx to be checked", policy_t(bigger_begin, g.numRows()), KOKKOS_LAMBDA(const ordinal_t x, ordinal_t& update, const bool final){
        ordinal_t i = order1(x);
        if(swap_bit(i) == 0){
            if(final){
                vtx1(update) = i;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    // above scan won't run if bigger_begin == g.numRows(), so scan_host won't be set
    if(bigger_begin == g.numRows()){
        total = 0;
    } else {
        exec_space().fence();
        total = mem.s_mem.scan_host();
    }
    Kokkos::parallel_for("check adjacent (large rows)", team_policy_t(total, Kokkos::AUTO), KOKKOS_LAMBDA(const member& t){
        //mark adjacent vertices
        ordinal_t marked = 0;
        ordinal_t i = vtx1(t.league_rank());
        // we have already checked [g.graph.row_map(i), g.graph.row_map(i) + LARGE_CUTOFF)
        Kokkos::parallel_reduce(Kokkos::TeamThreadRange(t, g.graph.row_map(i) + LARGE_CUTOFF, g.graph.row_map(i+1)), [=](const edge_offset_t j, ordinal_t& update){
            if(update == 0){
                ordinal_t v = g.graph.entries(j);
                if(swap_bit(v) == 1){
                    update++;
                }
            }
        }, marked);
        if(marked > 0){
            swap_bit(i) = 2;
        }
    });
    vtx_pin_st pin_host = mem.s_mem.pin_host;
    vtx_pin_st pin_host2 = mem.s_mem.pin_host2;
    ordinal_t big_begin = mem.o_mem.offset_mid;
    ordinal_t biggest_begin = mem.o_mem.offset_mid2;
    // order2 is already organized into two buckets by degree > or <= 32
    Kokkos::parallel_scan("collect vtx to be updated", policy_t(0, g.numRows()), KOKKOS_LAMBDA(const ordinal_t x, ordinal_t& update, const bool final){
        if(final && x == big_begin){
            pin_host() = update;
        }
        if(final && x == biggest_begin){
            pin_host2() = update;
        }
        ordinal_t i = order2(x);
        if(swap_bit(i)){
            if(final){
                vtx1(update) = i;
                // reset to zero for next iteration
                swap_bit(i) = 0;
                dest_cache(i) = NULL_PART;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    exec_space().fence();
    ordinal_t affected_total = mem.s_mem.scan_host();
    if(big_begin < g.numRows()){
        mem.o_mem.last_scan_mid = pin_host();
    } else {
        mem.o_mem.last_scan_mid = affected_total;
    }
    if(biggest_begin < g.numRows()){
        mem.o_mem.last_scan_mid2 = pin_host2();
    } else {
        mem.o_mem.last_scan_mid2 = affected_total;
    }
    vtx1 = Kokkos::subview(vtx1, std::make_pair((ordinal_t)0, affected_total));
    return vtx1;
}

// stream-compacts order2 for the vertices adjacent to any changed vertex
// assumes a smaller percentage of vertices are moved than find_affected
vtx_vt find_affected_smaller(const wg_t& wg, const vtx_vt swaps, mem_t& mem){
    const matrix_t& g = wg.mtx;
    ordinal_t total_moves = swaps.extent(0);
    vtx_vt swap_bit = mem.s_mem.zeros1;
    vtx_vt vtx1 = mem.s_mem.vtx1;
    vtx_vt order1 = mem.o_mem.order1;
    vtx_vt order2 = mem.o_mem.order2;
    vtx_vt dest_cache = mem.p_mem.dest_part;
    Kokkos::parallel_for("mark", policy_t(0, total_moves), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = swaps(x);
        swap_bit(i) = 1;
    });
    // this must be set by afterburner_filter
    ordinal_t big_begin = mem.o_mem.last_scan_large;
    ordinal_t biggest_begin = mem.o_mem.last_scan_large2;
    vtx_vt big_rows = Kokkos::subview(swaps, std::make_pair(big_begin, biggest_begin));
    vtx_vt biggest_rows = Kokkos::subview(swaps, std::make_pair(biggest_begin, total_moves));
    vtx_vt small_rows = Kokkos::subview(swaps, std::make_pair(static_cast<ordinal_t>(0), big_begin));
    Kokkos::parallel_for("mark adjacent", policy_t(0, big_begin), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = small_rows(x);
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i+1); j++){
            ordinal_t v = g.graph.entries(j);
            swap_bit(v) = 1;
        }
    });
    Kokkos::parallel_for("mark adjacent", team_policy_t(biggest_begin - big_begin, Kokkos::AUTO), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = big_rows(t.league_rank());
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i+1)), [=](const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            swap_bit(v) = 1;
        });
    });
    Kokkos::parallel_for("mark adjacent", team_policy_t(total_moves - biggest_begin, 1024), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = biggest_rows(t.league_rank());
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i+1)), [=](const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            swap_bit(v) = 1;
        });
    });

    vtx_pin_st pin_host = mem.s_mem.pin_host;
    vtx_pin_st pin_host2 = mem.s_mem.pin_host2;
    big_begin = mem.o_mem.offset_mid;
    biggest_begin = mem.o_mem.offset_mid2;
    // order2 is already organized into two buckets by degree > or <= 32
    Kokkos::parallel_scan("collect vtx to be updated", policy_t(0, g.numRows()), KOKKOS_LAMBDA(const ordinal_t x, ordinal_t& update, const bool final){
        if(final && x == big_begin){
            pin_host() = update;
        }
        if(final && x == biggest_begin){
            pin_host2() = update;
        }
        ordinal_t i = order2(x);
        if(swap_bit(i)){
            if(final){
                vtx1(update) = i;
                // reset to zero for next iteration
                swap_bit(i) = 0;
                dest_cache(i) = NULL_PART;
            }
            update++;
        }
    }, mem.s_mem.scan_host);
    exec_space().fence();
    ordinal_t affected_total = mem.s_mem.scan_host();
    if(big_begin < g.numRows()){
        mem.o_mem.last_scan_mid = pin_host();
    } else {
        mem.o_mem.last_scan_mid = affected_total;
    }
    if(biggest_begin < g.numRows()){
        mem.o_mem.last_scan_mid2 = pin_host2();
    } else {
        mem.o_mem.last_scan_mid2 = affected_total;
    }
    vtx1 = Kokkos::subview(vtx1, std::make_pair((ordinal_t)0, affected_total));
    return vtx1;
}

template <bool uniform, bool initial, bool uses_shared>
struct update_cdata {
    const vtx_vt vtx_list;
    const matrix_t g;
    const vtx_vt part;
    cdata_t cdata;
    wgt_vt pvals;
    const int max_size;

    update_cdata(const vtx_vt _vtx_list,
        const matrix_t _g,
        const vtx_vt _part,
        cdata_t _cdata,
        wgt_vt _pvals,
        const int _max_size) : 
        vtx_list(_vtx_list),
        g(_g),
        part(_part),
        cdata(_cdata),
        pvals(_pvals),
        max_size(_max_size) {}
    
    KOKKOS_INLINE_FUNCTION
    void operator()(const ordinal_t& x) const {
        const ordinal_t i = vtx_list(x);
        edge_offset_t c_start = cdata.conn_offsets(i);
        edge_offset_t c_end = cdata.conn_offsets(i + 1);
        if constexpr(!initial){
            for(edge_offset_t j = c_start; j < c_end; j++) {
                if(cdata.conn_entries(j) != NULL_PART){
                    cdata.conn_entries(j) = NULL_PART;
                    cdata.conn_vals(j) = 0;
                }
            }
        }
        ordinal_t size = c_end - c_start;
        ordinal_t* s_conn_entries = cdata.conn_entries.data() + c_start;
        scalar_t* s_conn_vals = cdata.conn_vals.data() + c_start;
        scalar_t update = 0;
        ordinal_t p_i = part(i);
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i + 1); j++) {
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            ordinal_t p = part(v);
            if(p == p_i){
                update += wgt;
                continue;
            }
            while(j + 1 < g.graph.row_map(i+1) && p == part(g.graph.entries(j+1))){
                j++;
                if constexpr(uniform) wgt += 1;
                else wgt += g.values(j);
            }
            ordinal_t p_o = hash(p) % static_cast<uint32_t>(size);
            ordinal_t px = s_conn_entries[p_o];
            while(px != p && px != NULL_PART){
                p_o++;
                p_o = (p_o == size) ? 0 : p_o;
                px = s_conn_entries[p_o];
            }
            if(px != p){
                s_conn_entries[p_o] = p;
            }
            s_conn_vals[p_o] += wgt;
        }
        pvals(i) = update;
    }

    KOKKOS_INLINE_FUNCTION
    void operator()(const member& t) const {
        const ordinal_t i = vtx_list(t.league_rank());
        edge_offset_t c_start = cdata.conn_offsets(i);
        edge_offset_t c_end = cdata.conn_offsets(i + 1);
        ordinal_t size = c_end - c_start;
        ordinal_t* s_conn_entries;
        scalar_t* s_conn_vals;
        if(uses_shared && size < max_size){
            // vals should come before entries because scalar_t is at least as large as ordinal_t
            // thus there could be alignment errors if vals is allocated second
            s_conn_vals = (scalar_t*) t.team_shmem().get_shmem(sizeof(scalar_t) * size);
            s_conn_entries = (ordinal_t*) t.team_shmem().get_shmem(sizeof(ordinal_t) * size);
            Kokkos::parallel_for(Kokkos::TeamThreadRange(t, 0, size), [&] (const edge_offset_t& j) {
                s_conn_entries[j] = NULL_PART;
                s_conn_vals[j] = 0;
            });
            t.team_barrier();
        } else {
            s_conn_entries = cdata.conn_entries.data() + c_start;
            s_conn_vals = cdata.conn_vals.data() + c_start;
            if constexpr(!initial){
                Kokkos::parallel_for(Kokkos::TeamThreadRange(t, 0, size), [&] (const edge_offset_t& j) {
                    s_conn_entries[j] = NULL_PART;
                    s_conn_vals[j] = 0;
                });
                t.team_barrier();
            }
        }
        ordinal_t p_i = part(i);
        Kokkos::parallel_reduce(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [&] (const edge_offset_t& j, scalar_t& update){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            ordinal_t p = part(v);
            if(p == p_i){
                update += wgt;
                return;
            }
            ordinal_t p_o = hash(p) % static_cast<uint32_t>(size);
            bool success = false;
            while(!success){
                ordinal_t px = s_conn_entries[p_o];
                while(px != p && px != NULL_PART){
                    p_o++;
                    p_o = (p_o == size) ? 0 : p_o;
                    px = s_conn_entries[p_o];
                }
                if(px == p){
                    success = true;
                } else {
                    Kokkos::atomic_compare_exchange(s_conn_entries + p_o, NULL_PART, p);
                    if(s_conn_entries[p_o] == p){
                        success = true;
                    } else {
                        p_o++;
                        p_o = (p_o == size) ? 0 : p_o;
                    }
                }
            }
            Kokkos::atomic_add(s_conn_vals + p_o, wgt);
        }, pvals(i));
        if(uses_shared && size < max_size){
            Kokkos::parallel_for(Kokkos::TeamThreadRange(t, c_start, c_end), [&] (const edge_offset_t& j) {
                cdata.conn_entries(j) = s_conn_entries[j - c_start];
                cdata.conn_vals(j) = s_conn_vals[j - c_start];
            });
        }
    }
};

// updates datastructures assuming a "large" number of vertices are moved
template <bool uniform>
void update_large(const wg_t& wg, const vtx_vt part, const vtx_vt swaps, cdata_t& cdata, mem_t& mem){
    const matrix_t& g = wg.mtx;
    edge_offset_t affected_edges = 0;
    Kokkos::parallel_reduce("sum degree", policy_t(0, swaps.extent(0)), KOKKOS_LAMBDA(const ordinal_t& x, edge_offset_t& update){
        ordinal_t i = swaps(x);
        update += g.graph.row_map(i+1) - g.graph.row_map(i);
    }, affected_edges);
    double affected_ratio = static_cast<double>(affected_edges) / static_cast<double>(g.nnz());
    vtx_vt affected;
    if(affected_ratio > 0.2) affected = find_affected(wg, swaps, mem);
    else affected = find_affected_smaller(wg, swaps, mem);
    ordinal_t total = affected.extent(0);
    // this must be set by find_affected/find_affected_smaller
    ordinal_t big_begin = mem.o_mem.last_scan_mid;
    ordinal_t biggest_begin = mem.o_mem.last_scan_mid2;
    ordinal_t small = big_begin;
    ordinal_t big = biggest_begin - small;
    ordinal_t biggest = total - biggest_begin;
    vtx_vt big_rows = Kokkos::subview(affected, std::make_pair(big_begin, biggest_begin));
    vtx_vt biggest_rows = Kokkos::subview(affected, std::make_pair(biggest_begin, total));
    vtx_vt small_rows = Kokkos::subview(affected, std::make_pair(static_cast<ordinal_t>(0), small));
    wgt_vt pvals = mem.p_mem.pvals;
    int max_size = 512;
    update_cdata<uniform, false, false> small_update(small_rows, g, part, cdata, pvals, max_size);
    update_cdata<uniform, false, true> big_update(big_rows, g, part, cdata, pvals, max_size);
    update_cdata<uniform, false, false> biggest_update(biggest_rows, g, part, cdata, pvals, max_size);
    Kokkos::parallel_for("update large (big rows)", team_policy_t(big, Kokkos::AUTO).set_scratch_size(0, Kokkos::PerTeam(max_size*sizeof(scalar_t) + max_size*sizeof(ordinal_t))), big_update);
    Kokkos::parallel_for("update large (biggest rows)", team_policy_t(biggest, 1024), biggest_update);
    Kokkos::parallel_for("update large (small rows)", policy_t(0, small), small_update);
}

//update datastructures assuming a "small" number of vertices are moved
template <bool uniform>
void update_small(const wg_t& wg, const vtx_vt part, const vtx_vt swaps, const vtx_vt dest_part, cdata_t& cdata, mem_t& mem){
    const matrix_t& g = wg.mtx;
    ordinal_t total_moves = swaps.extent(0);
    wgt_vt pvals = mem.p_mem.pvals;
    ordinal_t biggest_begin = mem.o_mem.last_scan_large2;
    vtx_vt big_rows = Kokkos::subview(swaps, std::make_pair((ordinal_t)0, biggest_begin));
    vtx_vt biggest_rows = Kokkos::subview(swaps, std::make_pair(biggest_begin, total_moves));
    Kokkos::parallel_for("update small (subtract)", team_policy_t(biggest_begin, Kokkos::AUTO), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = big_rows(t.league_rank());
        ordinal_t p = part(i);
        //subtract i's contribution to p connectivity for adjacent vertices
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [=] (const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            if(p == part(v)){
                Kokkos::atomic_add(&pvals(v), -wgt);
                return;
            }
            edge_offset_t v_start = cdata.conn_offsets(v);
            ordinal_t v_size = cdata.conn_table_sizes(v);
            ordinal_t p_o = hash(p) % static_cast<uint32_t>(v_size);
            //v is always adjacent to p because it is adjacent to i which is in p
            while(cdata.conn_entries(v_start + p_o) != p){
                p_o++;
                p_o = (p_o == v_size) ? 0 : p_o;
            }
            //DO NOT USE ATOMIC_ADD_FETCH HERE IT IS WAY SLOWER
            scalar_t x = Kokkos::atomic_fetch_add(&cdata.conn_vals(v_start + p_o), -wgt);
            //parts have locked locations if v_size == k (even when not originally allocated to size k)
            if(x == wgt){
                //free this gain slot
                cdata.conn_entries(v_start + p_o) = HASH_RECLAIM;
            }
        });
    });
    Kokkos::parallel_for("update small (subtract)", team_policy_t(total_moves - biggest_begin, 1024), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = biggest_rows(t.league_rank());
        ordinal_t p = part(i);
        //subtract i's contribution to p connectivity for adjacent vertices
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [=] (const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            if(p == part(v)){
                Kokkos::atomic_add(&pvals(v), -wgt);
                return;
            }
            edge_offset_t v_start = cdata.conn_offsets(v);
            ordinal_t v_size = cdata.conn_table_sizes(v);
            ordinal_t p_o = hash(p) % static_cast<uint32_t>(v_size);
            //v is always adjacent to p because it is adjacent to i which is in p
            while(cdata.conn_entries(v_start + p_o) != p){
                p_o++;
                p_o = (p_o == v_size) ? 0 : p_o;
            }
            //DO NOT USE ATOMIC_ADD_FETCH HERE IT IS WAY SLOWER
            scalar_t x = Kokkos::atomic_fetch_add(&cdata.conn_vals(v_start + p_o), -wgt);
            //parts have locked locations if v_size == k (even when not originally allocated to size k)
            if(x == wgt){
                //free this gain slot
                cdata.conn_entries(v_start + p_o) = HASH_RECLAIM;
            }
        });
    });

    // remove the new cluster id from hashmap, and insert old cluster id into hashmap
    Kokkos::parallel_for("swap pval and bval", policy_t(0, total_moves), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = swaps(x);
        // remove best (new cluster) from the hashmap
        ordinal_t best = dest_part(i);
        // insert p (old cluster) into the hashmap
        ordinal_t p = part(i);
        part(i) = best;
        dest_part(i) = NULL_PART;
        ordinal_t size = cdata.conn_table_sizes(i);
        edge_offset_t offset = cdata.conn_offsets(i);
        ordinal_t b_hash = hash(best) % static_cast<uint32_t>(size);
        scalar_t old_val = pvals(i);
        pvals(i) = 0;
        // find new cluster's connection strength, and set into pval
        for(ordinal_t q = 0; q < size; q++){
            ordinal_t p_i = (b_hash + q) % size;
            if(cdata.conn_entries(offset + p_i) == best){
                pvals(i) = cdata.conn_vals(offset + p_i);
                // delete from hashmap
                cdata.conn_vals(offset + p_i) = 0;
                cdata.conn_entries(offset + p_i) = HASH_RECLAIM;
                break;
            } else if(cdata.conn_entries(offset + p_i) == NULL_PART){
                break;
            }
        }
        // DO NOT insert old cluster into hashmap if it has no connection to vertex
        if(old_val == 0) return;
        bool success = false;
        ordinal_t p_o = hash(p) % static_cast<uint32_t>(size);
        // insert p into conn table
        // needs to find either HASH_RECLAIM or NULL_PART to make insertion
        while(!success){
            ordinal_t px = cdata.conn_entries(offset + p_o);
            while(px > NULL_PART){
                p_o = (p_o + 1) % size;
                px = cdata.conn_entries(offset + p_o);
            }
            if(px <= NULL_PART) {
                cdata.conn_entries(offset + p_o) = p;
                success = true;
            }
        }
        cdata.conn_vals(offset + p_o) = old_val;
    });

    Kokkos::parallel_for("update small (add)", team_policy_t(biggest_begin, Kokkos::AUTO), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = big_rows(t.league_rank());
        //part contains new part at this point
        ordinal_t best = part(i);
        //add i's contribution to best connectivity for adjacent vertices
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [=] (const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            dest_part(v) = NULL_PART;
            if(best == part(v)){
                Kokkos::atomic_add(&pvals(v), wgt);
                return;
            }
            edge_offset_t v_start = cdata.conn_offsets(v);
            ordinal_t v_size = cdata.conn_table_sizes(v);
            ordinal_t p_o = hash(best) % static_cast<uint32_t>(v_size);
            bool success = false;
            //check if best in conn table
            //can only determine best is absent if NULL_PART is found or v_size reached
            for(ordinal_t q = 0; q < v_size; q++){
                ordinal_t p_i = (p_o + q) % v_size;
                ordinal_t px = cdata.conn_entries(v_start + p_i);
                if(px == best){
                    success = true;
                    p_o = p_i;
                    break;
                } else if(px == NULL_PART){
                    break;
                }
            }
            //insert best into conn table
            //needs to find either HASH_RECLAIM or NULL_PART to make insertion
            while(!success){
                ordinal_t px = cdata.conn_entries(v_start + p_o);
                while(px != best && px > NULL_PART){
                    p_o++;
                    p_o = (p_o == v_size) ? 0 : p_o;
                    px = cdata.conn_entries(v_start + p_o);
                }
                if(px == best){
                    success = true;
                } else {
                    ordinal_t orig = NULL_PART;
                    if(cdata.conn_entries(v_start + p_o) == HASH_RECLAIM) orig = HASH_RECLAIM;
                    //don't care if this thread succeeds if another thread succeeds with the same value
                    Kokkos::atomic_compare_exchange(&cdata.conn_entries(v_start + p_o), orig, best);
                    if(cdata.conn_entries(v_start + p_o) == best){
                        success = true;
                    } else {
                        p_o++;
                        p_o = (p_o == v_size) ? 0 : p_o;
                    }
                }
            }
            Kokkos::atomic_add(&cdata.conn_vals(v_start + p_o), wgt);
        });
    });
    Kokkos::parallel_for("update small (add)", team_policy_t(total_moves - biggest_begin, 1024), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = biggest_rows(t.league_rank());
        //part contains new part at this point
        ordinal_t best = part(i);
        //add i's contribution to best connectivity for adjacent vertices
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i + 1)), [=] (const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            scalar_t wgt;
            if constexpr(uniform) wgt = 1;
            else wgt = g.values(j);
            dest_part(v) = NULL_PART;
            if(best == part(v)){
                Kokkos::atomic_add(&pvals(v), wgt);
                return;
            }
            edge_offset_t v_start = cdata.conn_offsets(v);
            ordinal_t v_size = cdata.conn_table_sizes(v);
            ordinal_t p_o = hash(best) % static_cast<uint32_t>(v_size);
            bool success = false;
            //check if best in conn table
            //can only determine best is absent if NULL_PART is found or v_size reached
            for(ordinal_t q = 0; q < v_size; q++){
                ordinal_t p_i = (p_o + q) % v_size;
                ordinal_t px = cdata.conn_entries(v_start + p_i);
                if(px == best){
                    success = true;
                    p_o = p_i;
                    break;
                } else if(px == NULL_PART){
                    break;
                }
            }
            //insert best into conn table
            //needs to find either HASH_RECLAIM or NULL_PART to make insertion
            while(!success){
                ordinal_t px = cdata.conn_entries(v_start + p_o);
                while(px != best && px > NULL_PART){
                    p_o++;
                    p_o = (p_o == v_size) ? 0 : p_o;
                    px = cdata.conn_entries(v_start + p_o);
                }
                if(px == best){
                    success = true;
                } else {
                    ordinal_t orig = NULL_PART;
                    if(cdata.conn_entries(v_start + p_o) == HASH_RECLAIM) orig = HASH_RECLAIM;
                    //don't care if this thread succeeds if another thread succeeds with the same value
                    Kokkos::atomic_compare_exchange(&cdata.conn_entries(v_start + p_o), orig, best);
                    if(cdata.conn_entries(v_start + p_o) == best){
                        success = true;
                    } else {
                        p_o++;
                        p_o = (p_o == v_size) ? 0 : p_o;
                    }
                }
            }
            Kokkos::atomic_add(&cdata.conn_vals(v_start + p_o), wgt);
        });
    });
}

edge_offset_t pval_sum(wgt_vt pvals, ordinal_t n){
    // this works well for large vertex swap counts
    // perhaps the old approach could be useful for small vertex swap counts (specifically during the uncoarsening pass)
    edge_offset_t sum = 0;
    Kokkos::parallel_reduce("count cutsize change part1", policy_t(0, n), KOKKOS_LAMBDA(const ordinal_t& i, edge_offset_t& gain_update){
        gain_update += pvals(i);
    }, sum);
    return sum;
}

//perform swaps, update gains, and compute change to cut and imbalance
template <bool uniform>
void perform_moves(const wg_t& wg, vtx_vt part, const vtx_vt swaps, cdata_t& cdata, mem_t& mem, refine_data& curr_state){
    const wgt_vt& vtx_w = wg.vtx_w;
    vtx_vt dest_part = Kokkos::subview(mem.p_mem.dest_part, std::make_pair(static_cast<ordinal_t>(0), wg.mtx.numRows()));
    ordinal_t total_moves = swaps.extent(0);
    wgt_vt pvals = mem.p_mem.pvals;
    wgt_vt total_deg = curr_state.total_deg;
    Kokkos::parallel_for("update total deg", policy_t(0, total_moves), KOKKOS_LAMBDA(const ordinal_t& x){
        ordinal_t i = swaps(x);
        ordinal_t best = dest_part(i);
        ordinal_t p = part(i);
        Kokkos::atomic_add(&total_deg(p), -vtx_w(i));
        Kokkos::atomic_add(&total_deg(best), vtx_w(i));
    });
    //change part assignments and update part sizes
    if(!cdata.init || total_moves >= wg.mtx.numRows() * 0.03){
        // update cluster ids before updating datastructures
        Kokkos::parallel_for("update parts", policy_t(0, total_moves), KOKKOS_LAMBDA(const ordinal_t x){
            ordinal_t i = swaps(x);
            ordinal_t best = dest_part(i);
            part(i) = best;
        });
        if(!cdata.init){
            init_conn_graph<uniform>(wg, part, cdata, mem);
            Kokkos::deep_copy(exec_space(), dest_part, NULL_PART);
        } else {
            update_large<uniform>(wg, part, swaps, cdata, mem);
        }
    } else {
        // cluster ids updated inside this function
        update_small<uniform>(wg, part, swaps, dest_part, cdata, mem);
    }
    edge_offset_t curr_pval = pval_sum(pvals, wg.mtx.numRows());
    edge_offset_t cut_change = curr_pval - curr_state.last_pval;
    curr_state.last_pval = curr_pval;
    curr_state.uncut += cut_change;
    curr_state.update_objective();
}

void fast_fill(vtx_vt a, ordinal_t V){
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

//initialize conn hash tables for each vertex
template <bool uniform>
void init_conn_graph(const wg_t& wg, const vtx_vt& part, cdata_t& cdata, mem_t& mem){
    const matrix_t& g = wg.mtx;
    cdata.init = true;
    Kokkos::deep_copy(exec_space(), cdata.conn_vals, 0);
    fast_fill(cdata.conn_entries, NULL_PART);
    // Kokkos::deep_copy(exec_space(), cdata.conn_entries, NULL_PART);
    ordinal_t n = g.numRows();
    vtx_vt order2 = mem.o_mem.order2;
    wgt_vt pvals = mem.p_mem.pvals;
    vtx_vt small_rows = Kokkos::subview(order2, std::make_pair(static_cast<ordinal_t>(0), mem.o_mem.offset_mid));
    vtx_vt big_rows = Kokkos::subview(order2, std::make_pair(mem.o_mem.offset_mid, mem.o_mem.offset_mid2));
    vtx_vt biggest_rows = Kokkos::subview(order2, std::make_pair(mem.o_mem.offset_mid2, n));
    int max_size = 512;
    update_cdata<uniform, true, false> small_update(small_rows, g, part, cdata, pvals, max_size);
    update_cdata<uniform, true, true> big_update(big_rows, g, part, cdata, pvals, max_size);
    update_cdata<uniform, true, false> biggest_update(biggest_rows, g, part, cdata, pvals, max_size);
    Kokkos::parallel_for("init conn (big rows)", team_policy_t(mem.o_mem.offset_mid2 - mem.o_mem.offset_mid, Kokkos::AUTO).set_scratch_size(0, Kokkos::PerTeam(max_size*sizeof(scalar_t) + max_size*sizeof(ordinal_t))), big_update);
    Kokkos::parallel_for("init conn (biggest rows)", team_policy_t(n - mem.o_mem.offset_mid2, 1024), biggest_update);
    Kokkos::parallel_for("init conn (small rows)", policy_t(0, mem.o_mem.offset_mid), small_update);
}

//initializes datastructures
cdata_t truncate_and_init_mem(mem_t& mem, const wg_t& wg, int label_count, bool top){
    const matrix_t g = wg.mtx;
    ordinal_t n = g.numRows();
    cdata_t cdata;
    cdata.init = false;
    cdata.conn_offsets = Kokkos::subview(mem.p_mem.row_map, std::make_pair(static_cast<ordinal_t>(0), n + 1));
    cdata.conn_table_sizes = Kokkos::subview(mem.p_mem.cluster_sizes, std::make_pair(static_cast<ordinal_t>(0), n));
    Kokkos::parallel_scan("comp conn offsets", policy_t(0, n), KOKKOS_LAMBDA(const ordinal_t& i, edge_offset_t& update, const bool final){
        ordinal_t degree = g.graph.row_map(i + 1) - g.graph.row_map(i);
        if(!top) degree *= 1.2;
        if(degree > 2*label_count) degree = 2*label_count;
        if(final){
            cdata.conn_offsets(i) = update;
            cdata.conn_table_sizes(i) = degree;
        }
        update += degree;
        if(final && i + 1 == n){
            cdata.conn_offsets(n) = update;
        }
    }, mem.s_mem.edge_scan_host);
    exec_space().fence();
    edge_offset_t gain_size = mem.s_mem.edge_scan_host();
    cdata.conn_vals = Kokkos::subview(mem.p_mem.vals, std::make_pair(static_cast<edge_offset_t>(0), gain_size));
    cdata.conn_entries = Kokkos::subview(mem.p_mem.entries, std::make_pair(static_cast<edge_offset_t>(0), gain_size));
    cdata.c_graph = matrix_t("conn graph", g.numRows(), g.numRows(), gain_size, cdata.conn_vals, cdata.conn_offsets, cdata.conn_entries);
    wgt_vt pval_init_subview = Kokkos::subview(mem.p_mem.pvals, std::make_pair(static_cast<ordinal_t>(0), n));
    vtx_vt dest_part_init_subview = Kokkos::subview(mem.p_mem.dest_part, std::make_pair(static_cast<ordinal_t>(0), n));
    Kokkos::deep_copy(exec_space(), pval_init_subview, 0);
    Kokkos::deep_copy(exec_space(), dest_part_init_subview, NULL_PART);
    return cdata;
}

void clone_pval(mem_t& mem, ordinal_t n){
    wgt_vt pval_subview = Kokkos::subview(mem.p_mem.pvals, std::make_pair(static_cast<ordinal_t>(0), n));
    wgt_vt pval_clone_subview = Kokkos::subview(mem.p_mem.pvals_clone, std::make_pair(static_cast<ordinal_t>(0), n));
    Kokkos::deep_copy(exec_space(), pval_clone_subview, pval_subview);
}

// moves vertices between clusters such that the objective increases
template <bool constrained>
void local_move(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint, bool enable_simulated_annealing){
    const matrix_t g = wg.mtx;
    // this is a reference to avoid allocating new memory
    refine_data& curr_state = mem.spare_cluster_data;
    curr_state.copy(best_state);
    vtx_vt part = Kokkos::subview(mem.p_mem.part, std::make_pair(static_cast<ordinal_t>(0), g.numRows()));
    Kokkos::deep_copy(exec_space(), part, best_part);
    cdata_t cdata = truncate_and_init_mem(mem, wg, best_state.label_count, best_state.top_nnz == g.nnz());
    if(!is_initial){
        if(wg.edge_uniform) init_conn_graph<true>(wg, part, cdata, mem);
        else init_conn_graph<false>(wg, part, cdata, mem);
        curr_state.last_pval = pval_sum(mem.p_mem.pvals, g.numRows());
    } else {
        curr_state.last_pval = 0;
    }
    // need to store this data
    // because this is only otherwise stored if the partition improves
    // and it might still be needed if that never happens
    clone_pval(mem, g.numRows());
    int iter_count = 0;
    std::vector<float> filter_ratios = {0.75, 0.25};
    std::vector<int> limits = {4, 2};
    for(size_t x = 0; x < filter_ratios.size(); x++){
        float filter_ratio = enable_simulated_annealing ? filter_ratios[x] : 0;
        int limit = limits[x];
        int count = 0;
        while(count++ < limit){
            iter_count++;
            vtx_vt moves;
            matrix_t c_graph = cdata.c_graph;
            if(!cdata.init){
                // use the input graph in place of the conn graph
                c_graph = g;
            }
            if(wg.edge_uniform && !cdata.init) moves = candidates_and_destinations<true, constrained>(wg, c_graph, part, curr_state, mem, filter_ratio, constraint);
            else moves = candidates_and_destinations<false, constrained>(wg, c_graph, part, curr_state, mem, filter_ratio, constraint);
            // anytime there are zero candidate moves, the local move procedure can not progress
            if(moves.extent(0) == 0) break;
            if(wg.edge_uniform) moves = afterburner_filter<true>(moves, wg, part, curr_state, mem);
            else moves = afterburner_filter<false>(moves, wg, part, curr_state, mem);
            // if all candidates have negative gain, it is possible that none are selected by the afterburner
            // in this case, progress may be possible with a different filter ratio, but significant progress from this state is unlikely
            if(moves.extent(0) == 0) break;
            if(iter_count > 1 || !is_initial) set_new_cluster_ids<constrained>(moves, part, curr_state, mem, constraint);
            if(wg.edge_uniform) perform_moves<true>(wg, part, moves, cdata, mem, curr_state);
            else perform_moves<false>(wg, part, moves, cdata, mem, curr_state);
            //copy current partition and relevant data to output partition if following conditions pass
            if(curr_state.obj > best_state.obj){
                best_state.copy(curr_state);
                Kokkos::deep_copy(exec_space(), best_part, part);
                clone_pval(mem, g.numRows());
            }
        }
    }
    relabel_contiguously(best_part, best_state, mem);
}

// if a non-node optimal vertex exists, this function (almost) guarantees an improvement to the objective function
// with some exceptions due to floating-point roundoff
// this occurs specifically if a vertex is close to node-optimal, having a near-zero objective delta to a neighboring cluster 
template <bool constrained>
void local_move_strict(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint){
    const matrix_t g = wg.mtx;
    // this is a reference to avoid allocating new memory
    refine_data& curr_state = mem.spare_cluster_data;
    curr_state.copy(best_state);
    vtx_vt part = Kokkos::subview(mem.p_mem.part, std::make_pair(static_cast<ordinal_t>(0), g.numRows()));
    Kokkos::deep_copy(exec_space(), part, best_part);
    cdata_t cdata = truncate_and_init_mem(mem, wg, best_state.label_count, best_state.top_nnz == g.nnz());
    if(!is_initial){
        if(wg.edge_uniform) init_conn_graph<true>(wg, part, cdata, mem);
        else init_conn_graph<false>(wg, part, cdata, mem);
        clone_pval(mem, g.numRows());
        curr_state.last_pval = pval_sum(mem.p_mem.pvals, g.numRows());
    } else {
        curr_state.last_pval = 0;
    }
    // need to store this data
    // because this is only otherwise stored if the partition improves
    // and it might still be needed if that never happens
    clone_pval(mem, g.numRows());
    for(int i = 0; i < 6; i++) {
        vtx_vt moves;
        matrix_t c_graph = cdata.c_graph;
        if(!cdata.init){
            // use the input graph in place of the conn graph
            c_graph = g;
        }
        if(wg.edge_uniform && !cdata.init) moves = candidates_and_destinations<true, constrained>(wg, c_graph, part, curr_state, mem, 0, constraint);
        else moves = candidates_and_destinations<false, constrained>(wg, c_graph, part, curr_state, mem, 0, constraint);

        // move list needs to be in vtx2 or else bad things happen
        // that normally happens in the afterburner, which isn't called here
        vtx_vt moves2 = Kokkos::subview(mem.s_mem.vtx2, std::make_pair((ordinal_t)0, (ordinal_t)moves.extent(0)));
        Kokkos::deep_copy(exec_space(), moves2, moves);
        moves = moves2;

        if(moves.extent(0) == 0) break;
        if(i > 0 || !is_initial) set_new_cluster_ids<constrained>(moves, part, curr_state, mem, constraint);
        double expected_diff = 0;
        if(wg.edge_uniform) moves = afterburner_filter_strict<true>(wg, moves, part, curr_state, mem, expected_diff);
        else moves = afterburner_filter_strict<false>(wg, moves, part, curr_state, mem, expected_diff);
        if(moves.extent(0) == 0) break;
        if(wg.edge_uniform) perform_moves<true>(wg, part, moves, cdata, mem, curr_state);
        else perform_moves<false>(wg, part, moves, cdata, mem, curr_state);
        //copy current partition and relevant data to output partition if following conditions pass
        if(curr_state.obj > best_state.obj){
            best_state.copy(curr_state);
            Kokkos::deep_copy(exec_space(), best_part, part);
            clone_pval(mem, g.numRows());
        } else if(curr_state.obj < best_state.obj) {
            // this may occur when the current clustering is node optimal
            std::cout << "INFO: Clustering did not improve after moving " << moves.extent(0) << " vertices on iteration " << i << std::endl;
            std::cout << "INFO: This has occurred due to floating-point roundoff" << std::endl;
            std::cout << "Expected pre-normalization diff: " << expected_diff << "; Actual pre-normalization diff: " << curr_state.obj - best_state.obj << std::endl;
        }
        vtx_vt dest_part_init_subview = Kokkos::subview(mem.p_mem.dest_part, std::make_pair(static_cast<ordinal_t>(0), g.numRows()));
        // reset this cache because it causes accuracy problems in afterburner_filter_strict
        Kokkos::deep_copy(exec_space(), dest_part_init_subview, NULL_PART);
    }
    relabel_contiguously(best_part, best_state, mem);
}

    // explicit template instantiations
    template void local_move<true>(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint, bool enable_simulated_annealing);
    template void local_move<false>(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint, bool enable_simulated_annealing);

    template void local_move_strict<true>(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint);
    template void local_move_strict<false>(const wg_t wg, vtx_vt best_part, refine_data& best_state, bool is_initial, mem_t& mem, vtx_vt constraint);

}

}
