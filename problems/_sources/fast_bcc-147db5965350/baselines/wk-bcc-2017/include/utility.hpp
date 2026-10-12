#ifndef UTILITY_H
#define UTILITY_H

#include <vector>
#include <string>
#include <sstream>
#include <iomanip>
#include <iostream>

bool verify(const std::vector<long>& arr_1, const std::vector<long>& arr_2);
bool verify(const std::vector<int>& arr_1, const std::vector<int>& arr_2);

std::string get_file_extension(std::string filename);

void write_CSR(const std::vector<long>& vertices, const std::vector<int>& edges, std::string filename);
void print_CSR(const std::vector<long>& vertices, const std::vector<int>& edges);

template <typename T>
void print(const std::vector<T>& arr) {
    for(const auto &i : arr) 
        std::cout << i <<" ";
    std::cout << std::endl;
}

template <typename T>
void print(const std::vector<T>& arr, const std::string& str) {
    std::cout << std::endl << str <<" starts" << std::endl;
    int j = 0;
    for(const auto &i : arr) 
        std::cout << j++ <<"\t" << i << std::endl;
    std::cout <<str <<" ends" << std::endl;
}

// Function to print vectors
template <typename T>
void print_vector(const std::vector<T>& vec, const std::string& name) {
    std::cout << name << ": ";
    for (size_t i = 0; i < vec.size(); ++i) {
        std::cout << vec[i] << (i < vec.size() - 1 ? ", " : "\n");
    }
}

// std::cout << "Reading input: " << formatDuration(194826) << std::endl;
// std::cout << "Allocation of device memory: " << formatDuration(3185) << std::endl;
std::string formatDuration(double timeInMs);

#endif // UTILITY_H