#include <string>
#include <vector>
#include <fstream>
#include <iostream>

#include "graph.hpp"

int main(int argc, char* argv[]) {
	
	if (argc < 2) {
		std::cerr << "Usage: " << argv[0] << " <graph_file> [source_vertex]\n";
		return EXIT_FAILURE;
	}
	
	std::string filename = argv[1];
	int source = (argc >= 3) ? std::stoi(argv[2]) : 0;
	
	std::cout << "Reading graph from file: " << filename << "\n";
	
	undirected_graph G(filename);
	
	int numVert = G.numVert;
	long numEdges = G.numEdges;
	
	std::cout << "Graph loaded:\n";
	std::cout << "  Vertices: " << numVert << "\n";
	std::cout << "  Edges: " << numEdges << "\n";
	if (G.avg_out_degree > 0.0) {
		std::cout << "  Average degree: " << G.avg_out_degree << "\n";
	}
	
	if (source < 0 || source >= numVert) {
		std::cerr << "Invalid source vertex: " << source << "\n";
		return EXIT_FAILURE;
	}
	
	std::cout << "\nRunning BFS from source vertex " << source << "...\n";
	G.bfs(source);
	
    return EXIT_SUCCESS;
}