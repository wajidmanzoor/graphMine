// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include "core_types.h"
#include "io/header/io.h"
#include "io/header/parse_args.h"
#include "io/header/io_views.hpp"
#include "io/header/vertex_weighting.h"
#include "weighted_graph.h"
#include "memory_store.hpp"
#include "cluster_data.hpp"
#include "ExperimentLoggerUtil.hpp"
#include "clustering_methods.h"
#include "objective_helpers.hpp"
#include <memory>
#include <random>

using namespace jet_community;
using rfd_t = cluster_data;
using wg_t = weighted_graph;
using mem_t = memory_store;
namespace cm_t = clustering_methods;
using team_policy_t = Kokkos::TeamPolicy<typename Device::execution_space>;
using member = typename team_policy_t::member_type;
using r_policy = Kokkos::RangePolicy<typename Device::execution_space>;
using vtx_view_t = Kokkos::View<ordinal_t*, Device>;

vtx_view_t intersection_cluster(vtx_view_t c1, vtx_view_t c2, int l2){

    ordinal_t n = c1.extent(0);
    vtx_view_t htable("hash table", n);
    Kokkos::deep_copy(htable, -1);

    vtx_view_t out("output constraint", n);
    Kokkos::parallel_for("insert products", r_policy(0, n), KOKKOS_LAMBDA(const ordinal_t i) {
        ordinal_t a = c1(i);
        ordinal_t b = c2(i);
        ordinal_t h = a*l2 + b;
        ordinal_t x = h % n;
        while(true){
            Kokkos::atomic_compare_exchange(&htable(x), -1, h);
            if(htable(x) == h){
                break;
            } else {
                x = (x + 1) % n;
            }
        }
        out(i) = x;
    });
    vtx_view_t hval("hash vals", n);
    Kokkos::parallel_scan("get new ids", r_policy(0, n), KOKKOS_LAMBDA(const ordinal_t i, ordinal_t& update, const bool final){
        if(htable(i) != -1){
            if(final){
                hval(i) = update;
            }
            update++;
        }
    });
    Kokkos::parallel_for("set ids", r_policy(0, n), KOKKOS_LAMBDA(const ordinal_t i){
        out(i) = hval(out(i));
    });
    return out;
}

struct clustering {
    vtx_view_t clusters;
    Kokkos::View<uint32_t*, Device> signature;
    double obj;
    int labels;
};

// each set-bit indicates a cut-edge
Kokkos::View<uint32_t*, Device> gen_signature(matrix_t g, vtx_view_t c, mem_t& mem){
    edge_offset_t sign_size = (g.nnz() + 31) / 32;
    Kokkos::View<uint32_t*, Device> sign("signature", sign_size);
    ordinal_t n = g.numRows();
    ordinal_t low = mem.o_mem.offset_large;
    ordinal_t high = n - low;
    // orderings should be valid because leiden+ will set them for the top level
    vtx_view_t vtx_high = Kokkos::subview(mem.o_mem.order1, std::make_pair(low, n));
    vtx_view_t vtx_low = Kokkos::subview(mem.o_mem.order1, std::make_pair(static_cast<ordinal_t>(0), low));
    Kokkos::parallel_for("create signature", r_policy(0, low), KOKKOS_LAMBDA(const ordinal_t x){
        ordinal_t i = vtx_low(x);
        for(edge_offset_t j = g.graph.row_map(i); j < g.graph.row_map(i+1); j++){
            ordinal_t v = g.graph.entries(j);
            if(c[i] != c[v]){
                edge_offset_t sign_offset = j / 32;
                int bit_offset = j & 31;
                uint32_t setbit = 1u << bit_offset;
                Kokkos::atomic_or(&sign(sign_offset), setbit);
            }
        }
    });
    Kokkos::parallel_for("create signature", team_policy_t(high, Kokkos::AUTO), KOKKOS_LAMBDA(const member& t){
        ordinal_t i = vtx_high(t.league_rank());
        Kokkos::parallel_for(Kokkos::TeamThreadRange(t, g.graph.row_map(i), g.graph.row_map(i+1)), [&](const edge_offset_t j){
            ordinal_t v = g.graph.entries(j);
            if(c[i] != c[v]){
                edge_offset_t sign_offset = j / 32;
                int bit_offset = j & 31;
                uint32_t setbit = 1u << bit_offset;
                Kokkos::atomic_or(&sign(sign_offset), setbit);
            }
        });
    });
    return sign;
}

value_t get_cut_diff(Kokkos::View<uint32_t*, Device> sign1, Kokkos::View<uint32_t*, Device> sign2){
    edge_offset_t chunks = sign1.extent(0);
    value_t diff = 0;
    Kokkos::parallel_reduce("compare signatures", r_policy(0, chunks), KOKKOS_LAMBDA(const edge_offset_t x, value_t& update){
        uint32_t chunk_xor = sign1(x) ^ sign2(x);
        update += Kokkos::popcount(chunk_xor);
    }, diff);
    return diff;
}

vtx_view_t meme_cluster(wg_t wg, const meme_args args) {

    std::unique_ptr<rfd_t> objective = get_objective(wg, args);
    rfd_t& rfd = *objective;
    mem_t mem(wg.mtx, rfd);
    std::vector<clustering> pop;
    ExperimentLoggerUtil<value_t> dummy;
    std::cout << std::setprecision(9);
    std::cout << std::fixed;
    int pop_size = args.pop_size;
    int time_limit = args.time_limit;
    for(int i = 0; i < pop_size; i++){
        vtx_view_t dummy_constraint;
        vtx_view_t c = cm_t::leiden_part<true, false>(mem, wg, rfd, dummy, dummy_constraint);
        clustering y;
        y.clusters = c;
        y.obj = rfd.get_objective();
        y.labels = rfd.label_count;
        y.signature = gen_signature(wg.mtx, c, mem);
        std::cout << "Adding clustering with obj: " << rfd.get_objective() << std::endl;
        pop.push_back(y);
        rfd.reset(wg.mtx, wg.vtx_w);
    }

    std::random_device r;
    std::default_random_engine e1(r());
    std::uniform_int_distribution<int> uniform_dist1(0, pop_size - 1);
    std::uniform_int_distribution<int> uniform_dist2(0, pop_size - 2);
    std::uniform_int_distribution<int> uniform_dist3(0, wg.mtx.nnz());
    double best = 0;
    int e = 0;
    int curr_iter = 0;
    Kokkos::Timer t;
    while(t.seconds() < time_limit) {
        int choice1 = uniform_dist1(e1);
        int choice2 = uniform_dist2(e1);
        choice2 = (choice1 + choice2) % pop_size;
        int p1 = pop[choice1].obj > pop[choice2].obj ? choice1 : choice2;
        int p2 = p1;
        while(p2 == p1){
            choice1 = uniform_dist1(e1);
            choice2 = uniform_dist2(e1);
            choice2 = (choice1 + choice2) % pop_size;
            p2 = pop[choice1].obj > pop[choice2].obj ? choice1 : choice2;
        }
        clustering c1 = pop[p1]; // choose parent 1
        clustering c2 = pop[p2]; // choose parent 2
        vtx_view_t constraint = intersection_cluster(c1.clusters, c2.clusters, c2.labels);
        // create offspring
        vtx_view_t c3 = cm_t::louvain_part<true>(mem, wg, rfd, dummy, constraint);
        std::cout << "Parent 1 obj: " << c1.obj << "; Parent 2 obj: " << c2.obj << "; Offspring obj: " << rfd.get_objective();
        for(int x = 0; x < 5; x++){
            c3 = cm_t::leiden_part<true, true>(mem, wg, rfd, dummy, c3);
        }
        std::cout << "; Post leiden obj: " << rfd.get_objective();
        if(rfd.get_objective() > best){
            best = rfd.get_objective();
        }

        // replace worst with c3
        int am = -1;
        double obj_max = rfd.get_objective();
        value_t min_diff = std::numeric_limits<value_t>::max();
        Kokkos::View<uint32_t*, Device> signature = gen_signature(wg.mtx, c3, mem);
        for(int p = 0; p < pop_size; p++){
            double obj = pop[p].obj;
            if(obj < obj_max){
                value_t diff = get_cut_diff(signature, pop[p].signature);
                if(diff < min_diff){
                    min_diff = diff;
                    am = p;
                }
            }
        }
        if(am != -1){
            pop[am].clusters = c3;
            pop[am].obj = rfd.get_objective();
            pop[am].labels = rfd.label_count;
            pop[am].signature = signature;
        } else {
            min_diff = 0;
        }
        std::cout << "; Min diff: " << min_diff << std::endl;
        rfd.reset(wg.mtx, wg.vtx_w);
        if(++curr_iter >= pop_size) {
            std::cout << "Epoch " << e << " best objective: " << best << std::endl;
            e++;
            curr_iter = 0;
        }
    }
    int am = -1;
    double obj_max = 0;
    for(int p = 0; p < pop_size; p++){
        double obj = pop[p].obj;
        if(obj > obj_max){
            obj_max = obj;
            am = p;
        }
    }
    std::cout << "Final objective: " << obj_max << std::endl;
    return pop[am].clusters;
}

int main(int argc, char **argv) {

    const meme_args args = parse_meme_args(argc, argv);
    if(!args.valid) return -1;

    Kokkos::initialize(argc, argv);
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

        vtx_view_t best_clusters = meme_cluster(wg, args);
        if(args.output_file.size() > 0){
            std::cout << "Writing best clustering to " << args.output_file << std::endl;
            write_part<vtx_view_t>(best_clusters, args.output_file.c_str());
        }
    }
    Kokkos::finalize();

    return 0;
}