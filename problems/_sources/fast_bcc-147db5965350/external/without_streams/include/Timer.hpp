#ifndef TIMER_HPP
#define TIMER_HPP

#include <chrono>
#include <iostream>
#include <string>
#include <unordered_map>

extern std::unordered_map<std::string, double> function_times;  // Declaration

void add_function_time(const std::string& function_name, double time);
void print_total_function_time(const std::string& function_name);
void reset_function_times();
#endif  // TIMER_HPP
