#include <iostream>
#include <fstream>
#include <set>
#include <random>

int main(int argc, char* argv[]) {
    int numvert, numedges;
    std::set<std::pair<int, int>> edge_list;
    if(argc < 3) {
        std::cerr <<"usage: <numVert> <numEdges>\n";
        return 1; 
    }
    numvert = std::stoi(argv[1]);
    numedges = std::stoi(argv[2]);

    // Reading number of vertices and edges from the terminal
    std::cout << "Entered number of vertices: " << numvert << std::endl;
    std::cout << "Enter number of edges: " << numedges << std::endl;

    // Create a random device and seed it
    std::random_device rd;
    std::mt19937 gen(rd());

    // Create a distribution in the range [0, numvert - 1]
    std::uniform_int_distribution<> distrib(0, numvert - 1);

    // Generate random edges
    while(edge_list.size() < numedges) {
        int u = distrib(gen);
        int v = distrib(gen);

        // Ensure no self-loops and the edge is unique
        if(u != v) {
            auto inserted = edge_list.insert(std::make_pair(u, v));
            // If the edge was not inserted because it's a duplicate, try again
            if (!inserted.second) continue;
        }
    }

    // Writing edges to a file
    std::ofstream outfile("edges.txt");
    if (!outfile.is_open()) {
        std::cerr << "Error opening file for writing." << std::endl;
        return -1;
    }
    outfile << numvert <<" " << 2 * numedges << std::endl;
    for (const auto& edge : edge_list) {
        outfile << edge.first << " " << edge.second << std::endl;
        outfile << edge.second << " " << edge.first << std::endl;
    }

    outfile.close();

    return 0;
}
