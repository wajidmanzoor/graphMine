#ifndef COMMAND_LINE_PARSER_H
#define COMMAND_LINE_PARSER_H

#include <iostream>
#include <string>
#include <cstdlib>
#include <cuda_runtime.h>

class CommandLineParser {
public:
    enum Algorithm {
        CUT_VERTEX,
        CUT_EDGES,
        IMPLICIT_BCC,
        EXPLICIT_BCC,
        SERIAL_BCC,
    };

    struct CommandLineArgs {
        std::string inputFile;
        std::string output_directory = "output/";
        Algorithm algorithm = EXPLICIT_BCC;
        int cudaDevice = 0;
        bool write_output = false;
        bool error = false;
    };

    CommandLineParser(int argc, char* argv[]) {
        parseArguments(argc, argv);
    }

    const CommandLineArgs& getArgs() const {
        return args;
    }

    static bool isValidCudaDevice(int device) {
        int deviceCount;
        cudaGetDeviceCount(&deviceCount);
        return device >= 0 && device < deviceCount;
    }

    static const std::string help_msg;

private:
    CommandLineArgs args;

    void parseArguments(int argc, char* argv[]) {
        for (int i = 1; i < argc; ++i) {
            std::string arg = argv[i];
            if (arg == "-i" && i + 1 < argc) {
                args.inputFile = argv[++i];
            } else if (arg == "-o" && i + 1 < argc) {
                args.write_output = true;
                args.output_directory = argv[++i];
            } else if (arg == "-a" && i + 1 < argc) {
                std::string algoArg = argv[++i];
                if (algoArg == "cv") {
                    args.algorithm = CUT_VERTEX;
                } else if (algoArg == "ce") {
                    args.algorithm = CUT_EDGES;
                } else if (algoArg == "ibcc") {
                    args.algorithm = IMPLICIT_BCC;
                } else if (algoArg == "ebcc") {
                    args.algorithm = EXPLICIT_BCC;
                } else if (algoArg == "sbcc") {
                    args.algorithm = SERIAL_BCC;
                } else {
                    std::cerr << "Unknown algorithm abbreviation: " << algoArg << std::endl;
                    args.error = true;
                }
            } else if (arg == "-d" && i + 1 < argc) {
                int device = std::atoi(argv[++i]);
                if (!isValidCudaDevice(device)) {
                    args.error = true;
                    std::cerr << "Error: Invalid CUDA device number." << std::endl;
                }
                args.cudaDevice = device;
            } else {
                std::cerr << "Unknown argument: " << arg << std::endl;
                args.error = true;
            }
        }
        if (args.inputFile.empty()) {
        std::cerr << "Error: Please provide Input file." << std::endl;
        args.error = true;
    }
}

};
const std::string CommandLineParser::help_msg =
"Command line arguments:\n"
" -h Print this help and exit\n"
" -i $input Sets input file to $input (mandatory)\n"
" -o $output Sets output file to $output (default: output/)\n"
" -a $algo Chooses algorithm to run (default: explicit_bcc)\n"
" Options: cv (cut_vertex), ce (cut_edges), ibcc (implicit_bcc),\n"
" ebcc (explicit_bcc), sbcc (serial-bcc)\n"
" -d $device Sets CUDA device to $device (default: 0)\n";

#endif // COMMAND_LINE_PARSER_H
