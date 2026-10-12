#pragma once

#include <string>
#include <vector_types.h>

#define uint_	unsigned int
#define uchar_	unsigned char
#define ushort_ unsigned short
#define ull_	unsigned long long int
#define ll_     long long int

#define PRODUCT2(a, b) ((a) * (b))
#define PRODUCT3(a, b, c) ((a) * (b) * (c))

//Maps to a single instruction on G8x / G9x / G10x
#define IMAD(a, b, c) ( __mul24((a), (b)) + (c) )

//Round a / b to nearest higher integer value
inline int iDivUp(int a, int b) {
    return (a % b != 0) ? (a / b + 1) : (a / b);
}
inline uint_ iDivUp(uint_ a, uint_ b) {
    return (a % b != 0) ? (a / b + 1) : (a / b);
}
inline ull_ iDivUp(ull_ a, ull_ b) {
    return (a % b != 0) ? (a / b + 1) : (a / b);
}

struct CmdArgs {
    std::string     filename;
    std::string     out;
    std::string     datatype;               // "uchar" | "ushort" | "int" | "float"
    uint_           height      = 0;
    uint_           width       = 0;
    uint_           depth       = 0;
    uint_           bufSize     = 0;        // optional, default 0
    uint_           bx = 0, by = 0, bz = 0; // optional, all-or-none, default 0
};

// Parse commandline arguments
bool parse_commandlneArges(int argc, char** argv, CmdArgs& cfg);

// Parse the input type from string to int
int parse_input_type(const std::string& input_type);

// Output Peak RAM usage in Windows
#if defined(WIN64) || defined(WIN32)
void printPeakMemoryUsage();
#endif