// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include "header/local_mover.h"
#include "header/contract.h"
#include "header/leidenR.h"
#include "header/ordering.h"
#include "memory_store.hpp"
#include "cluster_data.hpp"
#include "ExperimentLoggerUtil.hpp"
#include "weighted_graph.h"
#include "core_types.h"

namespace jet_community {

namespace contract_t = contracter;
namespace lr_t = leidenR;
namespace lm_t = local_move_heuristic;
namespace order = ordering;

namespace clustering_methods {
    // define internal types
    using exec_space = typename matrix_t::execution_space;
    using Device = typename matrix_t::device_type;
    using ordinal_t = typename matrix_t::ordinal_type;
    using scalar_t = typename matrix_t::value_type;
    using vtx_vt = typename Kokkos::View<ordinal_t*, Device>;
    using wgt_vt = typename Kokkos::View<scalar_t*, Device>;
    using policy_t = typename Kokkos::RangePolicy<exec_space>;
    using mem_t = memory_store;
    using wg_t = weighted_graph;
    using rfd_t = cluster_data;

    void coarsen_vtx_w(wgt_vt in, wgt_vt out, vtx_vt map){
        Kokkos::parallel_for("set v weights", policy_t(0, in.extent(0)), KOKKOS_LAMBDA(const ordinal_t i){
            ordinal_t c = map(i);
            Kokkos::atomic_add(&out(c), in(i));
        });
    }

    void downsample(vtx_vt in, vtx_vt out, vtx_vt map){
        Kokkos::parallel_for("set v weights", policy_t(0, in.extent(0)), KOKKOS_LAMBDA(const ordinal_t i){
            ordinal_t c = map(i);
            out(c) = in(i);
        });
    }

    template <bool plus, bool improve>
    vtx_vt leiden_part(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input){
        std::vector<wg_t> levels;
        std::vector<vtx_vt> parts;
        levels.push_back(top);
        double aggregate = 0;
        vtx_vt part("cluster assignments", top.mtx.numRows());
        if(!improve){
            Kokkos::parallel_for("set initial assignments", policy_t(0, top.mtx.numRows()), KOKKOS_LAMBDA(const ordinal_t x){
                part(x) = x;
            });
        } else Kokkos::deep_copy(part, input);
        while(true) {
            wg_t c = levels[levels.size() - 1];
            double old_obj = rfd.obj;
            // orderings must be generated for use in local_move and build_coarse_graph
            order::generate_orderings(mem, c.mtx);
            lm_t::local_move<false>(c, part, rfd, !improve && (levels.size() == 1), mem, part, true);
            if(c.mtx.nnz() > 100000 && old_obj == rfd.obj){
                // it is usually worth trying this first
                lm_t::local_move<false>(c, part, rfd, !improve && (levels.size() == 1), mem, part, false);
            }
            if(old_obj == rfd.obj){
                lm_t::local_move_strict<false>(c, part, rfd, !improve && (levels.size() == 1), mem, part);
            }
            if(rfd.label_count == c.mtx.numRows()){
                parts.push_back(part);
                break;
            }
            vtx_vt louv = part;
            int coarse_vtx_count = 0;
#ifdef EXTRA_TIMING
            Kokkos::fence();
            Kokkos::Timer lr_time;
#endif
            vtx_vt coarse_map;
            if(levels.size() == 1 && c.edge_uniform) coarse_map = lr_t::template coarsen_leidenR<true, true>(c, louv, mem, rfd, coarse_vtx_count);
            else if(levels.size() == 1 && !(c.edge_uniform)) coarse_map = lr_t::template coarsen_leidenR<true, false>(c, louv, mem, rfd, coarse_vtx_count);
            else coarse_map = lr_t::template coarsen_leidenR<false, false>(c, louv, mem, rfd, coarse_vtx_count);
            parts.push_back(coarse_map);
#ifdef EXTRA_TIMING
            Kokkos::fence();
            experiment.addMeasurement(Measurement::LeidenRefine, lr_time.seconds());
#endif
            if(coarse_vtx_count < c.mtx.numRows()){
#ifdef EXTRA_TIMING
                Kokkos::Timer t;
#endif
                wg_t next_level;
                if(c.edge_uniform) next_level = contract_t::build_coarse_graph<true, false>(c, coarse_map, coarse_vtx_count, mem);
                else next_level = contract_t::build_coarse_graph<false, false>(c, coarse_map, coarse_vtx_count, mem);
                next_level.vtx_w = wgt_vt("weighted degree 2", coarse_vtx_count);
                coarsen_vtx_w(c.vtx_w, next_level.vtx_w, coarse_map);

                part = vtx_vt("cluster assignments coarse", coarse_vtx_count);
                downsample(louv, part, coarse_map);
                levels.push_back(next_level);

#ifdef EXTRA_TIMING
                Kokkos::fence();
                aggregate += t.seconds();
#endif
            } else {
                // avoid creating new graph if leidenR didn't contract any vertices
                // which may happen with astronomically low probability for any input clustering
                // or if input clustering is very bad
                levels.push_back(c);
            }
        }

        experiment.addMeasurement(Measurement::Contract, aggregate);
        int64_t t_nnz = 0;
        for(const wg_t& level : levels){
            t_nnz += level.mtx.nnz();
        }
        experiment.setTotalNnz(t_nnz);
        experiment.setLevelCount(levels.size());
        for(int i = levels.size() - 2; i >= 0; i--){
            wg_t c = levels[i];
            vtx_vt coarse_part = parts[i + 1];
            vtx_vt fine_part = parts[i];
            Kokkos::parallel_for("update top level assignments", policy_t(0, c.mtx.numRows()), KOKKOS_LAMBDA(const ordinal_t x){
                fine_part(x) = coarse_part(fine_part(x));
            });
            if constexpr(plus){
                order::generate_orderings(mem, c.mtx);
                lm_t::local_move<false>(c, fine_part, rfd, false, mem, part, true);
            }
        }
        return parts[0];
    }

    template <bool constrained>
    vtx_vt louvain_part(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt constraint){
        if(constrained) rfd.reset(top.mtx, top.vtx_w);
        std::vector<wg_t> levels;
        std::vector<vtx_vt> parts;
        levels.push_back(top);
        double aggregate = 0;
        bool drop_constraint = constrained;
        while(true) {
            wg_t c = levels[levels.size() - 1];
            vtx_vt part("cluster assignments", c.mtx.numRows());
            Kokkos::parallel_for("set initial assignments", policy_t(0, c.mtx.numRows()), KOKKOS_LAMBDA(const ordinal_t x){
                part(x) = x;
            });
            // orderings must be generated for use in local_move and build_coarse_graph
            order::generate_orderings(mem, c.mtx);
            lm_t::local_move<constrained>(c, part, rfd, true, mem, constraint, true);
            // the user clearly cares about quality if they are doing multiple iterations
            if(constrained && rfd.label_count == c.mtx.numRows()){
                lm_t::local_move_strict<constrained>(c, part, rfd, true, mem, constraint);
            }
            parts.push_back(part);
            if(rfd.label_count < c.mtx.numRows()){
#ifdef EXTRA_TIMING
                Kokkos::fence();
                Kokkos::Timer t;
#endif
                wg_t next_level;
                if(c.edge_uniform) next_level = contract_t::build_coarse_graph<true, true>(c, part, rfd.label_count, mem);
                else next_level = contract_t::build_coarse_graph<false, false>(c, part, rfd.label_count, mem);
                wgt_vt td_rfd = Kokkos::subview(rfd.total_deg, std::make_pair((ordinal_t)0, rfd.label_count));
                next_level.vtx_w = wgt_vt("next level vtx weights", rfd.label_count);
                Kokkos::deep_copy(next_level.vtx_w, td_rfd);
                levels.push_back(next_level);

                if(constrained) {
                    vtx_vt next_constraint("next constraint", rfd.label_count);
                    downsample(constraint, next_constraint, part);
                    constraint = next_constraint;
                }

#ifdef EXTRA_TIMING
                Kokkos::fence();
                aggregate += t.seconds();
#endif
            } else if(drop_constraint) {
                Kokkos::deep_copy(constraint, 0);
                parts.pop_back();
                drop_constraint = false;
            } else {
                break;
            }
        }
        
        int64_t t_nnz = 0;
        for(const wg_t& level : levels){
            t_nnz += level.mtx.nnz();
        }
        experiment.setTotalNnz(t_nnz);
        experiment.setLevelCount(levels.size());

        if(levels.size() > 1){
            // last level has the same partition as previous level
            // so refining this level on the uncoarsening pass
            // would not integrate any coarse information
            levels.pop_back();
            parts.pop_back();
        }
        
        // levels.size()-2 so that (i+1) is in bounds
        for(int i = levels.size() - 2; i >= 0; i--){
            wg_t c = levels[i];
            vtx_vt coarse_part = parts[i + 1];
            vtx_vt part = parts[i];
            Kokkos::parallel_for("update top level assignments", policy_t(0, c.mtx.numRows()), KOKKOS_LAMBDA(const ordinal_t x){
                part(x) = coarse_part(part(x));
            });
            order::generate_orderings(mem, c.mtx);
            lm_t::local_move<false>(c, part, rfd, false, mem, constraint, true);
        }

        experiment.addMeasurement(Measurement::Contract, aggregate);
        return parts[0];
    }

    // explicit template instantiations
    template vtx_vt leiden_part<true, true>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input);
    template vtx_vt leiden_part<true, false>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input);
    template vtx_vt leiden_part<false, true>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input);
    template vtx_vt leiden_part<false, false>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt input);

    template vtx_vt louvain_part<true>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt constraint);
    template vtx_vt louvain_part<false>(mem_t& mem, wg_t top, rfd_t& rfd, ExperimentLoggerUtil<value_t>& experiment, vtx_vt constraint);
}

}