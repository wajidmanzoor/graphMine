// Copyright 2026 Michael S. Gilbert II
// SPDX-License-Identifier: Apache-2.0
#include <unordered_set>
#include <unordered_map>
#include <string>
#include <vector>
#include <iostream>
#include "header/parse_args.h"

static std::unordered_map<std::string, Objective> obj_map = {
    {"Mod", Objective::Modularity},
    {"WMod", Objective::WModularity},
    {"CPM", Objective::CPM},
    {"NLCC", Objective::NLCC},
    {"LCC", Objective::Base}
};

void print_configuration_base(base_args args){
    std::cout << "Program configuration: " << std::endl;
    std::cout << "-- Input Graph File: " << args.graph_file << std::endl;
    if(args.vw_file.size() > 0) std::cout << "-- Input Vertex Weights File: " << args.vw_file << std::endl;
    else {
        std::cout << "-- Vertex Weighting Method: ";
        switch(args.obj_type){
            case Objective::Modularity:
                std::cout << "Degree" << std::endl;
                break;
            case Objective::WModularity:
                std::cout << "Weighted Degree" << std::endl;
                break;
            default:
                std::cout << "Unit Uniform" << std::endl;
        }
    }
    std::cout << "-- Objective Type: ";
    switch(args.obj_type){
        case Objective::Modularity:
            std::cout << "Modularity" << std::endl;
            break;
        case Objective::WModularity:
            std::cout << "Weighted Modularity" << std::endl;
            break;
        case Objective::CPM:
            std::cout << "Constant-Potts Model" << std::endl;
            break;
        case Objective::NLCC:
            std::cout << "Normalized LambdaCC" << std::endl;
            break;
        case Objective::Base:
            std::cout << "Base LambdaCC" << std::endl;
    }
    std::cout << "-- Lambda Multiplier: " << args.lambda_multiplier << std::endl;
    if(args.output_file.size() > 0) std::cout << "-- Output Clusters File: " << args.output_file << std::endl;
}

void print_configuration(cluster_args args){
    print_configuration_base(args);
    std::cout << "-- Successive Iteration Count: " << args.n_successive_iterations << std::endl;
    std::cout << "-- Total trial count: " << args.n_trials << std::endl;
    if(args.metrics_file.size() > 0){
        std::cout << "-- Metrics Output File: " << args.metrics_file << std::endl;
    }
}

void print_configuration(meme_args args){
    print_configuration_base(args);
    std::cout << "-- Population Size: " << args.pop_size << std::endl;
    std::cout << "-- Time Limit Seconds: " << args.time_limit << std::endl;
}

void print_configuration(verify_args args){
    print_configuration_base(args);
    std::cout << "-- Clusters File: " << args.cluster_file << std::endl;
}

std::unordered_map<std::string, std::string> parse_base_args(int argc, char** argv, std::vector<std::string> extra_valid_options, base_args& args){
    std::unordered_set<std::string> valid_options = {"-i", "-o", "-objective", "-lambda", "-vtx_weights"};
    valid_options.insert(extra_valid_options.begin(), extra_valid_options.end());
    std::unordered_map<std::string, std::string> required_options = {
        {"-i", "FATAL ERROR: Required graph input file not given. Please specify with argument '-i <graph file>'"}
    };
    std::unordered_map<std::string, std::string> given_options;
    
    args.valid = true;
    bool is_opt_name = true;
    std::string curr_opt_name;
    // parse options
    for(int i = 1; i < argc; i++){
        std::string opt = argv[i];
        if(is_opt_name){
            if(valid_options.count(opt) != 0){
                curr_opt_name = opt;
                is_opt_name = false;
            } else {
                std::cerr << "FATAL ERROR: Invalid option name: " << opt << std::endl;
                std::cerr << "Valid Options:" << std::endl;
                for(auto& opt_name : valid_options){
                    std::cerr << opt_name << std::endl;
                }
                args.valid = false;
                return given_options;
            }
        } else {
            given_options[curr_opt_name] = opt;
            is_opt_name = true;
        }
    }
    if(!is_opt_name){
        std::cerr << "FATAL ERROR: Value not provided for option '" << curr_opt_name << "'" << std::endl;
        args.valid = false;
        return given_options;
    }
    for(const auto& [req,msg] : required_options){
        if(given_options.count(req) == 0){
            std::cerr << msg << std::endl;
            args.valid = false;
        }
    }
    args.graph_file = given_options["-i"];
    if(given_options.count("-o") != 0){
        args.output_file = given_options["-o"];
    }
    if(given_options.count("-objective") != 0){
        std::string obj_specifier = given_options["-objective"];
        if(obj_map.count(obj_specifier) != 0){
            args.obj_type = obj_map[obj_specifier];
        } else {
            std::cerr << "FATAL ERROR: Invalid objective name '" << obj_specifier << "'!" << std::endl;
            args.valid = false;
        }
    }
    if(given_options.count("-lambda") != 0){
        args.lambda_multiplier = std::stod(given_options["-lambda"]);
    }
    if(given_options.count("-vtx_weights") != 0){
        args.vw_file = given_options["-vtx_weights"];
    }
    return given_options;
}

void verify_config(base_args& args){
    if(args.vw_file.size() > 0) {
        if(args.obj_type != Objective::NLCC && args.obj_type != Objective::Base){
            args.valid = false;
            std::cerr << "FATAL ERROR: Vertex weights file is only supported with objectives Normalized LambdaCC and Base LambdaCC!" << std::endl;
        }
    }
}

cluster_args parse_cluster_args(int argc, char** argv){
    std::vector<std::string> extra_valid_options = {"-trials", "-ex_iters", "-metrics"};
    
    cluster_args args;
    std::unordered_map<std::string, std::string> given_options = parse_base_args(argc, argv, extra_valid_options, args);
    if(!args.valid) return args;

    if(given_options.count("-trials") != 0){
        args.n_trials = std::stoi(given_options["-trials"]);
    }
    if(args.n_trials < 1) args.n_trials = 1;
    if(given_options.count("-ex_iters") != 0){
        args.n_successive_iterations = std::stoi(given_options["-ex_iters"]);
    }
    if(args.n_successive_iterations < -1) args.n_successive_iterations = -1;
    if(given_options.count("-metrics") != 0){
        args.metrics_file = given_options["-metrics"];
    }
    print_configuration(args);
    verify_config(args);
    return args;
}

meme_args parse_meme_args(int argc, char** argv){
    std::vector<std::string> extra_valid_options = {"-pop_size", "-time_limit"};
    
    meme_args args;
    std::unordered_map<std::string, std::string> given_options = parse_base_args(argc, argv, extra_valid_options, args);
    if(!args.valid) return args;

    if(given_options.count("-pop_size") != 0){
        args.pop_size = std::stoi(given_options["-pop_size"]);
    }
    if(args.pop_size < 10){
        std::cout << "WARNING: Population size given as " << args.pop_size << " < 10. Setting population size to 10." << std::endl;
        args.pop_size = 10;
    }
    if(given_options.count("-time_limit") != 0){
        args.time_limit = std::stoi(given_options["-time_limit"]);
    }
    if(args.time_limit < 10){
        std::cout << "WARNING: Time limit given as " << args.time_limit << "s < 10s. Setting time limit to 10s." << std::endl;
        args.time_limit = 10;
    }
    print_configuration(args);
    verify_config(args);
    return args;
}

verify_args parse_verify_args(int argc, char** argv){
    std::vector<std::string> extra_valid_options = {"-clusters"};
    
    verify_args args;
    std::unordered_map<std::string, std::string> given_options = parse_base_args(argc, argv, extra_valid_options, args);
    if(!args.valid) return args;

    if(given_options.count("-clusters") == 0){
        std::cerr << "FATAL ERROR: Required clusters file not given! Please specify with argument '-clusters <cluster file>'" << std::endl;
        args.valid = false;
        return args;
    }

    args.cluster_file = given_options["-clusters"];
    print_configuration(args);
    verify_config(args);
    return args;
}