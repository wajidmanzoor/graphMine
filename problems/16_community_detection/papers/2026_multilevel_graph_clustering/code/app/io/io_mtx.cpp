// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include "core_types.h"
#include <filesystem>
#include <string>
#include <iostream>
#include <fstream>
#include <vector>
#include "Kokkos_UnorderedMap.hpp"
#include "KokkosSparse_SortCrs.hpp"
#include "header/io_common.hpp"

namespace jet_community {

using graph_t = typename matrix_t::staticcrsgraph_type;
using edge_view_t = Kokkos::View<edge_offset_t*, Device>;
using edge_mirror_t = typename edge_view_t::HostMirror;
using vtx_view_t = Kokkos::View<ordinal_t*, Device>;
using vtx_mirror_t = typename vtx_view_t::HostMirror;
using wgt_view_t = Kokkos::View<value_t*, Device>;
using wgt_mirror_t = typename wgt_view_t::HostMirror;
using r_policy = Kokkos::RangePolicy<typename Device::execution_space>;
using big_r_policy = Kokkos::RangePolicy<typename Device::execution_space, Kokkos::IndexType<edge_offset_t>>;

struct mm_meta {
    bool is_coordinate;
    bool is_pattern;
    bool is_integer;
    bool is_symmetric;
};

mm_meta get_mm_metadata(const char* f, const char* fmax){
    const int max_fields = 5;
    const std::string PATTERN = "pattern";
    const std::string INTEGER = "integer";
    const std::string COORDINATE = "coordinate";
    const std::string SYMMETRIC = "symmetric";
    std::string fields[max_fields];
    int field_num = 0;
    const char* begin = f;
    // tracks if we are inside an alphanumeric sequence
    bool state_machine = false;
    while(f < fmax) {
        char c = *f;
        if(isalnum(c)){
            if(!state_machine){
                begin = f;
            }
            state_machine = true;
        } else {
            if(state_machine){
                if(field_num < max_fields){
                    fields[field_num++].assign(begin, f);
                }
            }
            state_machine = false;
        }
        f++;
        if(c == '\n') break;
    }
    mm_meta data;
    data.is_coordinate = (COORDINATE == fields[2]);
    data.is_pattern = (PATTERN == fields[3]);
    data.is_integer = (INTEGER == fields[3]);
    data.is_symmetric = (SYMMETRIC == fields[4]);
    return data;
}

static constexpr uint64_t HASH_EMPTY = std::numeric_limits<uint64_t>::max();

// basic linear-probing hash table
KOKKOS_INLINE_FUNCTION
bool is_new_entry(const Kokkos::View<uint64_t*, Device>& htable, ordinal_t u, ordinal_t v, size_t mod){
    using hasher_t = Kokkos::pod_hash<ordinal_t>;
    hasher_t hash_f;
    ordinal_t less = (u < v) ? u : v;
    uint64_t hless = hash_f(less);
    ordinal_t more = (u > v) ? u : v;
    uint64_t hmore = hash_f(more);
    uint64_t sig = (static_cast<uint64_t>(less) << 32) | more;
    size_t i = (hless*hmore + (hmore & hless)) & mod;
    while(true){
        if(htable(i) == HASH_EMPTY){
            if(Kokkos::atomic_compare_exchange(&htable(i), HASH_EMPTY, sig) == HASH_EMPTY){
                return true;
            }
        }
        if(htable(i) == sig){
            return false;
        }
        i = (i + 1) & mod;
    }
}

matrix_t construct_from_edgelist(ordinal_t n, std::vector<ordinal_t>& src_v, std::vector<ordinal_t>& dst_v, std::vector<value_t>& val_v, const bool symmetric, const bool uniform_ew){
    int self_loops = 0;
    int zero_weight = 0;
    edge_offset_t edges_read = src_v.size();
    Kokkos::View<ordinal_t*, Kokkos::HostSpace, Kokkos::MemoryTraits<Kokkos::Unmanaged>> src_host(src_v.data(), edges_read);
    Kokkos::View<ordinal_t*, Kokkos::HostSpace, Kokkos::MemoryTraits<Kokkos::Unmanaged>> dst_host(dst_v.data(), edges_read);
    vtx_view_t src(Kokkos::ViewAllocateWithoutInitializing("src"), edges_read);
    vtx_view_t dst(Kokkos::ViewAllocateWithoutInitializing("dst"), edges_read);
    wgt_view_t val(Kokkos::ViewAllocateWithoutInitializing("val"), edges_read);
    edge_view_t row_map(Kokkos::ViewAllocateWithoutInitializing("row_map"), n + 1);
    Kokkos::deep_copy(src, src_host);
    Kokkos::deep_copy(dst, dst_host);
    if(!uniform_ew){
        Kokkos::View<value_t*, Kokkos::HostSpace, Kokkos::MemoryTraits<Kokkos::Unmanaged>> val_host(val_v.data(), edges_read);
        Kokkos::deep_copy(val, val_host);
    }
    Kokkos::deep_copy(row_map, 0);
    Kokkos::View<uint64_t*, Device> unique_edges;
    size_t mod = 0;
    if(!symmetric){
        size_t cap = 2;
        while(cap < (size_t)edges_read) cap <<= 1;
        if(cap < (size_t)(1.1*edges_read)) cap <<= 1;
        mod = cap - 1;
        // hashtable expects a power of 2 capacity
        unique_edges = Kokkos::View<uint64_t*, Device>(Kokkos::ViewAllocateWithoutInitializing("unique edges table"), cap);
        Kokkos::deep_copy(unique_edges, HASH_EMPTY);
    }
    // count edges per vertex
    Kokkos::parallel_for("count edges per vertex (also find duplicates if not symmetric)", big_r_policy(0, edges_read), KOKKOS_LAMBDA(const edge_offset_t j){
        ordinal_t u = src(j);
        ordinal_t v = dst(j);
        if(u == v){
            return;
        }
        if(!uniform_ew){
            if(val(j) == 0){
                // ignore this edge in a later loop
                src(j) = dst(j);
                return;
            }
        }
        if(!symmetric){
            if(!is_new_entry(unique_edges, u, v, mod)){
                // ignore this edge in a later loop
                src(j) = dst(j);
                return;
            }
        }
        Kokkos::atomic_add(&row_map(u), 1);
        Kokkos::atomic_add(&row_map(v), 1);
    });
    // deallocate
    unique_edges = Kokkos::View<uint64_t*, Device>("dummy", 0);
    if(self_loops > 0){
        std::cout << "WARNING: Ignoring " << self_loops << " self loop edges." << std::endl;
    }
    if(zero_weight > 0){
        std::cout << "WARNING: Ignoring " << zero_weight << " zero weight edges." << std::endl;
    }
    edge_offset_t sum = 0;
    // compute row map
    Kokkos::parallel_scan("row map exclusive prefix sum", r_policy(0, n + 1), KOKKOS_LAMBDA(const ordinal_t i, edge_offset_t& update, const bool final){
        ordinal_t d = row_map(i);
        if(final){
            row_map(i) = update;
        }
        update += d;
    }, sum);

    vtx_view_t entries(Kokkos::ViewAllocateWithoutInitializing("entries"), sum);
    wgt_view_t values;
    if(!uniform_ew) values = wgt_view_t(Kokkos::ViewAllocateWithoutInitializing("values"), sum);

    vtx_view_t counters("per vertex degree counter", n);
    // write edges to entries
    Kokkos::parallel_for("write edges", big_r_policy(0, edges_read), KOKKOS_LAMBDA(const edge_offset_t j){
        ordinal_t u = src(j);
        ordinal_t v = dst(j);
        if(u == v) return;
        // could do this faster if we stored the result of the atomic add from the prior kernel
        // but that would take memory proportional to edges_read
        edge_offset_t u_offset = row_map(u) + Kokkos::atomic_fetch_add(&counters(u), 1);
        edge_offset_t v_offset = row_map(v) + Kokkos::atomic_fetch_add(&counters(v), 1);
        entries(u_offset) = v;
        entries(v_offset) = u;
        if(!uniform_ew){
            values(u_offset) = val(j);
            values(v_offset) = val(j);
        }
    });
    // deallocate
    src = vtx_view_t("dummy", 0);
    dst = vtx_view_t("dummy", 0);
    val = wgt_view_t("dummy", 0);

    // atomics will almost certainly cause reordering of the entries in each row
    // so we sort to fix it (even if it wasn't sorted to begin with, but most graphs I've seen are)
    // use parallel_thread_level sort to avoid the large memory allocations made with other method
    if(!uniform_ew) {
        KokkosSparse::sort_crs_matrix<typename Device::execution_space, edge_view_t, vtx_view_t, wgt_view_t>(typename Device::execution_space(), row_map, entries, values, n, KokkosSparse::SortAlgorithm::PARALLEL_THREAD_LEVEL);
    } else{
        KokkosSparse::sort_crs_graph<typename Device::execution_space, edge_view_t, vtx_view_t>(typename Device::execution_space(), row_map, entries, n, KokkosSparse::SortAlgorithm::PARALLEL_THREAD_LEVEL);
    }
    graph_t g_graph(entries, row_map);
    return matrix_t("input graph", n, values, g_graph);
}

enum class ParseState { SRC, DST, WGT };

bool load_mtx_graph(matrix_t& g, bool& uniform_ew, const char *fname) {
    Kokkos::Timer t;
    std::ifstream infp(fname);
    if (!infp.is_open()) {
        std::cerr << "FATAL ERROR: Could not open Matrix Market graph file " << fname << std::endl;
        return false;
    }
    size_t sz = std::filesystem::file_size(fname);
    char* s = new char[sz + 1];
    std::cout << "Reading " << sz << " bytes from " << fname << std::endl;
    infp.read(s, sz);
    infp.close();
    std::cout << "Parsing file as matrix market format" << std::endl;
    //append an endline to end of file in case one doesn't exist
    //needed to prevent parser from overshooting end of buffer
    if(s[sz - 1] != '\n'){
        s[sz] = '\n';
        sz++;
    }
    const char* f = s;
    const char* fmax = s + sz;
    mm_meta metadata = get_mm_metadata(f, fmax);
    if(!metadata.is_coordinate) {
        std::cerr << "FATAL ERROR: Importing of non-coordinate format matrix market files is not currently supported!" << std::endl;
        return false;
    }
    if(!metadata.is_pattern) {
        if(metadata.is_integer){
            if(uniform_ew){
                std::cout << "INFO: This file has edge weights. The given objective function treats edge weights as unit uniform. Please see Objectives.md for more information." << std::endl;
            }
        } else if(!uniform_ew) {
            uniform_ew = true;
            std::cout << "WARNING: Non-integer edge weights given in matrix market file. This is not currently supported. The given weights will be ignored." << std::endl;
        }
    }
    if(!metadata.is_symmetric) {
        std::cout << "INFO: Non-symmetric matrix market file detected. The graph will be automatically symmetrized." << std::endl;
        if(!uniform_ew) {
            uniform_ew = true;
            std::cout << "WARNING: Edge weights given in matrix market file. This is not supported for non-symmetric file formats. The given weights will be ignored." << std::endl;
        }
    }
    size_t sub_header[4] = {0, 0, 0, 0};
    //ignore commented lines
    while(*f == '%') next_line(f);
    while(!isdigit(*f)) f++;
    //read header data
    for(int i = 0; i < 4; i++){
        sub_header[i] = fast_atoi<size_t>(f);
        while(!isdigit(*f)){
            if(*f == '\n'){
                //end for loop
                i = 4;
                f++;
                break;
            }
            f++;
        }
    }
    ordinal_t n = sub_header[0];
    if(sub_header[0] != sub_header[1]){
        std::cerr << "FATAL ERROR: Bipartite file format detected. This format is not currently supported!" << std::endl;
        return false;
    }
    edge_offset_t m = sub_header[2];
    std::vector<ordinal_t> src(m);
    std::vector<ordinal_t> dst(m);
    std::vector<value_t> val;
    if(!uniform_ew) val.resize(m);

    edge_offset_t edges_read = 0;
    ParseState state = ParseState::SRC;
    //read edge information
    while(f < fmax){
        //increment past whitespace
        while(f < fmax && !isdigit(*f)){
            //ignore commented lines
            if(*f == '%'){
                next_line(f);
                continue;
            }
            if(*f == '\n'){
                if(state != ParseState::SRC){
                    std::cerr << "FATAL ERROR: Line with exactly one value detected" << std::endl;
                    return false;
                }
            }
            f++;
        }
        if(f >= fmax) break;
        //fast_atoi also increments past numeric chars
        ordinal_t v = 0;
        value_t w = 0;
        //subtract 1 to convert to 0-indexed
        if(state != ParseState::WGT) v = fast_atoi<ordinal_t>(f) - 1;
        else w = fast_atoi<value_t>(f);
        if(state == ParseState::SRC){
            src[edges_read] = v;
            state = ParseState::DST;
        } else if(state == ParseState::DST) {
            dst[edges_read] = v;
            if(uniform_ew) {
                state = ParseState::SRC;
                edges_read++;
                next_line(f);
            } else {
                state = ParseState::WGT;
            }
        } else {
            val[edges_read++] = w;
            state = ParseState::SRC;
            next_line(f);
        }
    }
    delete[] s;
    if(edges_read != m){
        std::cerr << "FATAL ERROR: Mismatch between expected and actual line/nonzero count in matrix market file" << std::endl;
        std::cerr << "Read " << edges_read << " nonzeros" << std::endl;
        std::cerr << "Nonzeros expected: " << m << std::endl;
        return false;
    }
    std::cout << "Finished reading data from " << fname << std::endl;
    std::cout << "Beginning conversion to CSR format" << std::endl;

    g = construct_from_edgelist(n, src, dst, val, metadata.is_symmetric, uniform_ew);
    std::cout << "Read and constructed graph from " << fname << " in " << std::setprecision(3) << t.seconds() << "s" << std::endl;
    return true;
}


bool load_graph(matrix_t& g, bool& uniform_ew, const char* fname) {
    std::filesystem::path p(fname);

    const std::string MTX_SUFFIX = ".mtx";
    if(p.extension().compare(MTX_SUFFIX) == 0){
        return load_mtx_graph(g, uniform_ew, fname);
    } else {
        return load_metis_graph(g, uniform_ew, fname);
    }
}

}
