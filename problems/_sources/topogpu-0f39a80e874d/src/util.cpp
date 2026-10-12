#include "util.h"
#include <cstring>

#if defined(WIN64) || defined(WIN32)
#include <windows.h>
#include <psapi.h>
#include <iostream>
#endif

int parse_input_type(const std::string& input_type) {
    /*
    	Parse the input type from string to int
    */
    if (input_type == "uchar") return 0;
    if (input_type == "ushort") return 1;
    if (input_type == "int") return 2;
    if (input_type == "float") return 3;
    printf("Error: unrecognized input data type: %s\n", input_type.c_str());
    exit(1);
    return -1;
}

#if defined(WIN64) || defined(WIN32)
void printPeakMemoryUsage() {
    PROCESS_MEMORY_COUNTERS_EX pmc;
    if (GetProcessMemoryInfo(GetCurrentProcess(),
        (PROCESS_MEMORY_COUNTERS*)&pmc,
        sizeof(pmc))) {
        SIZE_T peakMem = pmc.PeakWorkingSetSize; // bytes
        double peakGB = peakMem / (1024.0 * 1024.0 * 1024.0);
        std::cout << "Peak RAM usage: " << peakGB << " GB" << std::endl;
    }
}
#endif

void print_help(const char* prog) {
    std::printf(
        R"(Usage:
          %s -help
          %s -filename <path> -datatype <uchar|ushort|int|float> -height <u> -width <u> [-depth <u>]
             [-bufSize <u>]
             [-blockSize_x <u> -blockSize_y <u> [-blockSize_z <u>]]
             [-out <path>]

        Parameters:
          -filename       Full path to input file.
          -datatype       One of: uchar, ushort, int, float.
          -height         Image height (uint).
          -width          Image width  (uint).
          -depth          Optional image depth (uint).
                          If omitted, the input is treated as 2D (height x width).
                          If provided, the input is treated as 3D (height x width x depth).
          -bufSize        Optional buffer size in numbers. Default 2000 if omitted.
          -blockSize_x    Optional block size X (uint). Must be a power of 2 and >= 2.
          -blockSize_y    Optional block size Y (uint). Must be a power of 2 and >= 2.
          -blockSize_z    Optional block size Z (uint). Must be a power of 2 and >= 2.
                          For 2D (no -depth), if any -blockSize_* is provided, both must be provided.
                          For 3D (with -depth), if any -blockSize_* is provided, all three must be provided.
          -out            Optional output path (string) to write results.

        Output:
          If -depth is not provided (2D input), each line is:
            dim birth death birth_coordinate (y, x) death_coordinate (y, x)

          If -depth is provided (3D input), each line is:
            dim birth death birth_coordinate (z, y, x) death_coordinate (z, y, x)

        Notes:
          - Optional groups are independent. You may pass only -bufSize, only -blockSize_*, -out, any combination, or none.
          - blockSize_* will be automatically decided if omitted.)"
        "\n",
        prog, prog);
}

bool eqflag(const char* a, const char* b) {
    return std::strcmp(a, b) == 0;
}

bool parse_uint(const char* s, uint_& out) {
    if (!s || !*s) return false;
    char* end = nullptr;
    unsigned long long v = std::strtoull(s, &end, 10);
    if (end == s || *end != '\0') return false;
    if (v > 0xFFFFFFFFull) return false;
    out = static_cast<uint_>(v);
    return true;
}

bool is_valid_datatype(const std::string& t) {
    return t == "uchar" || t == "ushort" || t == "int" || t == "float";
}

bool parse_commandlneArges(int argc, char** argv, CmdArgs& cfg) {
    if (argc == 2 && (eqflag(argv[1], "-help") || eqflag(argv[1], "--help"))) {
        print_help(argv[0]);
        return false; // signal "help shown"
    }

    for (int i = 1; i < argc; ++i) {
        const char* a = argv[i];

        if (eqflag(a, "-help") || eqflag(a, "--help")) {
            print_help(argv[0]);
            return false;
        }
        else if (eqflag(a, "-filename")) {
            if (++i >= argc) { std::fprintf(stderr, "Error: -filename requires a value.\n"); return false; }
            cfg.filename = argv[i];
        }
        else if (eqflag(a, "-datatype")) {
            if (++i >= argc) { std::fprintf(stderr, "Error: -datatype requires a value.\n"); return false; }
            cfg.datatype = argv[i];
        }
        else if (eqflag(a, "-height")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.height)) { std::fprintf(stderr, "Error: -height requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-width")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.width)) { std::fprintf(stderr, "Error: -width requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-depth")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.depth)) { std::fprintf(stderr, "Error: -depth requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-bufSize")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.bufSize)) { std::fprintf(stderr, "Error: -bufSize requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-blockSize_x")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.bx)) { std::fprintf(stderr, "Error: -blockSize_x requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-blockSize_y")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.by)) { std::fprintf(stderr, "Error: -blockSize_y requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-blockSize_z")) {
            if (++i >= argc || !parse_uint(argv[i], cfg.bz)) { std::fprintf(stderr, "Error: -blockSize_z requires uint.\n"); return false; }
        }
        else if (eqflag(a, "-out")) {
            if (++i >= argc) { std::fprintf(stderr, "Error: -out requires a path.\n"); return false; }
            cfg.out = argv[i];
        }
        else {
            std::fprintf(stderr, "Error: unknown flag '%s'. Use -help.\n", a);
            return false;
        }
    }

    // Required checks
    if (cfg.filename.empty()) {
        std::fprintf(stderr, "Error: -filename is required.\n");
        return false;
    }
    if (!is_valid_datatype(cfg.datatype)) {
        std::fprintf(stderr, "Error: -datatype must be one of {uchar, ushort, int, float}.\n");
        return false;
    }
    if (cfg.height == 0 || cfg.width == 0) {
        std::fprintf(stderr, "Error: -height, -width must be > 0.\n");
        return false;
    }

    // 2D vs 3D mode
    const bool is3D = (cfg.depth != 0);

    // All-or-none for block sizes, depending on 2D/3D
    bool bx_set = cfg.bx != 0;
    bool by_set = cfg.by != 0;
    bool bz_set = cfg.bz != 0;

    if (is3D) {
        // 3D: if any blockSize_* is set, all three must be set
        if (bx_set || by_set || bz_set) {
            if (!(bx_set && by_set && bz_set)) {
                std::fprintf(stderr, "Error: in 3D mode, -blockSize_x, -blockSize_y, -blockSize_z must be provided together.\n");
                return false;
            }
        }
    }
    else {
        // 2D: depth == 0
        // -blockSize_z is not allowed (or at least not meaningful)
        if (bz_set) {
            std::fprintf(stderr, "Error: -blockSize_z is only valid when -depth is provided (3D input).\n");
            return false;
        }
        // If any of x/y is set, both must be set
        if (bx_set || by_set) {
            if (!(bx_set && by_set)) {
                std::fprintf(stderr, "Error: in 2D mode, -blockSize_x and -blockSize_y must be provided together.\n");
                return false;
            }
        }
    }

    // If not set, ensure zero (explicit)
    if (!bx_set) cfg.bx = 0;
    if (!by_set) cfg.by = 0;
    if (!bz_set) cfg.bz = 0;

    return true;
}