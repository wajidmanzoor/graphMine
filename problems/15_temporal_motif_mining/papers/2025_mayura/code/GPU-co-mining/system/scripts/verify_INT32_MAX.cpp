#include <iostream>
#include <fstream>
#include <limits>

int main(int args, char* argv[]) {
    if (args != 2) {
        std::cerr << "Usage: " << argv[0] << " /path/to/your/inputfile.txt" << std::endl;
        return 1;
    }
    std::ifstream inputFile(argv[1]);
    if (!inputFile) {
        std::cerr << "Error opening file!" << std::endl;
        return 1;
    }

    int64_t num1, num2, num3;
    const int32_t int32_max = std::numeric_limits<int32_t>::max();
    bool allWithinRange = true;

    while (inputFile >> num1 >> num2 >> num3) {
        if (num1 < 0 || num1 > int32_max
         || num2 < 0 || num2 > int32_max
         || num3 < 0 || num3 > int32_max) {
            allWithinRange = false;
            break;
        }
    }

    inputFile.close();

    if (allWithinRange) {
        std::cout << "All numbers are within the range of 0 to INT32_MAX." << std::endl;
    } else {
        std::cout << "Some numbers are out of the range of 0 to INT32_MAX." << std::endl;
    }

    return 0;
}