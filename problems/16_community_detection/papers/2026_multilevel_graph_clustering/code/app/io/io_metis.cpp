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
#include <filesystem>
#include <string>
#include <iostream>
#include <fstream>
#include "header/io_common.hpp"

namespace jet_community {

using graph_t = typename matrix_t::staticcrsgraph_type;
using edge_view_t = Kokkos::View<edge_offset_t*, Device>;
using edge_mirror_t = typename edge_view_t::HostMirror;
using vtx_view_t = Kokkos::View<ordinal_t*, Device>;
using vtx_mirror_t = typename vtx_view_t::HostMirror;
using wgt_view_t = Kokkos::View<value_t*, Device>;
using wgt_mirror_t = typename wgt_view_t::HostMirror;

void next_line(const char*& str){
    while(*str != '\n') str++;
    str++;
}

bool load_metis_graph(matrix_t& g, bool& uniform_ew, const char *fname) {
    Kokkos::Timer t;
    std::ifstream infp(fname);
    if (!infp.is_open()) {
        std::cerr << "FATAL ERROR: Could not open metis graph file " << fname << std::endl;
        return false;
    }
    size_t sz = std::filesystem::file_size(fname);
    char* s = new char[sz + 1];
    std::cout << "Reading " << sz << " bytes from " << fname << std::endl;
    infp.read(s, sz);
    infp.close();
    std::cout << "Parsing file as metis format" << std::endl;
    // append a newline to end of buffer in case file is missing a trailing newline
    // needed to prevent parser from overshooting end of buffer
    s[sz] = '\n';
    sz++;
    const char* f = s;
    const char* fmax = s + sz;
    size_t header[4] = {0, 0, 0, 0};
    //ignore commented lines
    while(*f == '%') next_line(f);
    while(!isdigit(*f)) f++;
    //read header data
    for(int i = 0; i < 4; i++){
        header[i] = fast_atoi<size_t>(f);
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
    ordinal_t n = header[0];
    edge_offset_t m = header[1];
    int fmt = header[2];
    int ncon = header[3];
    bool has_ew = ((fmt % 10) == 1);
    if(fmt != 0 && fmt != 1){
        std::cerr << "FATAL ERROR: Unsupported format flags " << fmt << std::endl;
        std::cerr << "Graph parser does not currently support vertex weights" << std::endl;
        return false;
    }
    if(ncon != 0){
        std::cerr << "FATAL ERROR: Unsupported ncon " << ncon << std::endl;
        std::cerr << "Graph parser does not currently support vertex weights" << std::endl;
        return false;
    }
    vtx_view_t entries(Kokkos::ViewAllocateWithoutInitializing("entries"), m*2);
    vtx_mirror_t entries_m = Kokkos::create_mirror_view(entries);
    edge_view_t row_map(Kokkos::ViewAllocateWithoutInitializing("row map"), n + 1);
    edge_mirror_t row_map_m = Kokkos::create_mirror_view(row_map);
    wgt_view_t values;
    wgt_mirror_t values_m;
    if(has_ew && !uniform_ew) {
        values = wgt_view_t(Kokkos::ViewAllocateWithoutInitializing("values"), 2*m);
        values_m = Kokkos::create_mirror_view(values);
    } else if(has_ew){
        std::cout << "INFO: This file has edge weights. The given objective function treats edge weights as unit uniform. Please see Objectives.md for more information." << std::endl;
    } else {
        uniform_ew = true;
    }
    edge_offset_t edges_read = 0;
    ordinal_t rows_read = 0;
    row_map_m(0) = 0;
    bool is_value = false;
    //ready edge information
    while(f < fmax){
        //increment past whitespace
        while(f < fmax && !isdigit(*f)){
            //ignore commented lines
            if(*f == '%'){
                next_line(f);
                continue;
            }
            if(*f == '\n'){
                //ignore extra trailing newlines
                if(rows_read < n) row_map_m(++rows_read) = edges_read;
            }
            f++;
        }
        if(f >= fmax) break;
        //fast_atoi also increments past numeric chars
        ordinal_t edge_info = fast_atoi<ordinal_t>(f);
        if(!is_value){
            //subtract 1 to convert to 0-indexed
            entries_m(edges_read) = edge_info - 1;
        } else {
            values_m(edges_read++) = edge_info;
        }
        if(has_ew){
            is_value = !is_value;
        } else {
            edges_read++;
        }
    }
    delete[] s;
    if(rows_read != n || edges_read != 2*m){
        std::cerr << "FATAL ERROR: Mismatch between expected and actual line/nonzero count in metis file" << std::endl;
        std::cerr << "Read " << rows_read << " lines and " << edges_read << " nonzeros" << std::endl;
        std::cerr << "Lines expected: " << n << "; Nonzeros expected: " << m*2 << std::endl;
        return false;
    }
    Kokkos::deep_copy(row_map, row_map_m);
    Kokkos::deep_copy(entries, entries_m);
    if(!uniform_ew){
        Kokkos::deep_copy(values, values_m);
    }
    graph_t g_graph(entries, row_map);
    g = matrix_t("input graph", n, values, g_graph);
    std::cout << "Read graph from " << fname << " in " << std::setprecision(3) << t.seconds() << "s" << std::endl;
    return true;
}

}
