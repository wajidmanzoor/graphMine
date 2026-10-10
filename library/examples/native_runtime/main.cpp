#include <graphmine/runtime.hpp>
#include <iostream>
int main() { std::cout << graphmine::runtime::request(R"({"command":"catalog"})"); }
