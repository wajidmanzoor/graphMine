// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <Kokkos_Core.hpp>
#include <sstream>
#include <iostream>
#include <fstream>

namespace jet_community {

template <class view_t>
void write_part(view_t part_d, const char *fname){
    std::ofstream ofp(fname);
    if(!ofp.is_open()) return;
    typename view_t::HostMirror part = Kokkos::create_mirror_view(part_d);
    Kokkos::deep_copy(part, part_d);
    size_t n = part.extent(0);
    std::stringstream ss;
    for(size_t x = 0; x < n; x++){
        ss << part(x) << std::endl;
    }
    ofp << ss.str();
    ofp.close();
}

template <class view_t>
view_t load_view(size_t n, const char *fname){
    std::ifstream ifp(fname);
    view_t v_d("device view", n);
    if(!ifp.is_open()){
        std::cerr << "FATAL ERROR: Could not open " << fname << std::endl;
        return v_d;
    }
    typename view_t::HostMirror v = Kokkos::create_mirror_view(v_d);
    for(size_t x = 0; x < n; x++){
        ifp >> v(x);
    }
    ifp.close();
    Kokkos::deep_copy(v_d, v);
    return v_d;
}

}