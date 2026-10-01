
#pragma once
#include <getopt.h>
#include <string>

namespace tot {

struct Config {
    std::string input_file;

    bool extract = 1;
    bool verify  = false;
};

std::string option_hints =
    "              [-i input_file]\n"
    "              [-e extract_upper_triangular (1 or 0)]\n"
    "              [-v verify (1 or 0)]\n";

auto program_options(int argc, char* argv[])
{
    Config config;
    int    opt;
    if (argc == 1) {
        printf("Usage: %s ... \n%s", argv[0], option_hints.c_str());
        std::exit(EXIT_FAILURE);
    }
    while ((opt = getopt(argc, argv, "e:v:i:")) != -1) {
        switch (opt) {
            case 'i':
                config.input_file = optarg;
                break;
            case 'e':
                config.extract = std::stoi(optarg);
                break;
            case 'v':
                config.verify = std::stoi(optarg);
                break;

            default:
                printf("Usage: %s ... \n%s", argv[0], option_hints.c_str());
                exit(EXIT_FAILURE);
        }
    }
    printf("\n-----------------config-----------------\n");
    if (!config.input_file.empty()) {
        printf("input path: %s\n", config.input_file.c_str());
    }
    else {
        printf("input file is not specified\n");
        exit(EXIT_FAILURE);
    }
    if (config.extract == 1) {
        printf("extract upper triangular\n");
    }
    if (config.verify == 1) {
        printf("verify with CPU result\n");
    }
    printf("----------------------------------------\n");
    printf("\n");
    return config;
}
}  // namespace tot