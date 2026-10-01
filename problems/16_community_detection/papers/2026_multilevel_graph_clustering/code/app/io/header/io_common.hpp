// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "core_types.h"

namespace jet_community{

    bool load_mtx_graph(matrix_t& g, bool& uniform_ew, const char *fname);
    bool load_metis_graph(matrix_t& g, bool& uniform_ew, const char *fname);
    
    template<typename t>
    t fast_atoi( const char*& str ) {
        t val = 0;
        while(isdigit(*str)) {
            val = val*10 + static_cast<t>(*str - '0');
            str++;
        }
        return val;
    }

    void next_line(const char*& str);
}