// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <string>

enum class Objective { Modularity, CPM, WModularity, NLCC, Base};

struct base_args {
    std::string graph_file;
    std::string output_file;
    std::string vw_file;
    double lambda_multiplier = 1.0;
    Objective obj_type = Objective::Modularity;
    bool valid;
};

struct verify_args : base_args {
    std::string cluster_file;
};

struct cluster_args : base_args {
    int n_trials = 1;
    int n_successive_iterations = 0;
    std::string metrics_file;
};

struct meme_args : base_args {
    int pop_size = 10;
    int time_limit = 10;
};

cluster_args parse_cluster_args(int argc, char** argv);

meme_args parse_meme_args(int argc, char** argv);

verify_args parse_verify_args(int argc, char** argv);