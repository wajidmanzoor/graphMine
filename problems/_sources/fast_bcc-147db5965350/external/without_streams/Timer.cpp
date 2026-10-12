// function_timings.cpp
#include "include/Timer.hpp"

#include <vector>
#include <iomanip>  // For std::fixed and std::setprecision
#include <algorithm>  // For std::sort

std::unordered_map<std::string, double> function_times;  // Definition

void add_function_time(const std::string& function_name, double time) {
    if (function_times.find(function_name) == function_times.end()) {
        function_times[function_name] = time;  // Initialize if not already present
    } else {
        function_times[function_name] += time;  // Accumulate time if already present
    }
}

// Function to print the times sorted by increasing order
void print_times() {
    // Create a vector of pairs from the unordered_map
    std::vector<std::pair<std::string, double>> sorted_times(function_times.begin(), function_times.end());
    
    // Sort the vector by the second element of the pair (the times)
    std::sort(sorted_times.begin(), sorted_times.end(), [](const std::pair<std::string, double>& a, const std::pair<std::string, double>& b) {
        return a.second > b.second;  // Sort in increasing order of times
    });

    std::cout << "\nFunction execution times:\n";
    for (const auto& pair : sorted_times) {
        std::cout << std::fixed << std::setprecision(2)  // Set precision for decimal places
                  << "Time of " << pair.first << " : " << pair.second << " ms\n";
    }

    std::cout << std::endl;
}

// Function to reset the function times
void reset_function_times() {
    function_times.clear();
}

void print_total_function_time(const std::string& function_name) {
    double total_time = 0;
    for (const auto& pair : function_times) {
        total_time += pair.second;
    }
    // std::cout << "Total execution time of all functions: " << total_time << " ms.\n";
    std::cout << "\nTotal execution time for " << function_name << ": " << total_time << " ms.\n";

    #ifdef DETAIL
        print_times();
    #endif
}
