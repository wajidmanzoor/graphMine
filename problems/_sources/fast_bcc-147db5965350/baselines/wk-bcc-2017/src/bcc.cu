#include <vector>
#include <string>
#include <random>
#include <chrono>
#include <cub/cub.cuh>
#include <cuda_runtime.h>

// Helper functions
#include "timer.hpp"
#include "utility.hpp"
#include "cuda_utility.cuh"

#include "bcc.cuh"
#include "bcc_memory_utils.cuh"

#include "bfs.cuh"

#include "lca.cuh"
#include "cut_vertex.cuh"

// #define DEBUG

void cuda_bcc(gpu_bcc& g_bcc_ds) {

	long numEdges 	= g_bcc_ds.numEdges; // numEdges is unique edge count (only (2,1), not (1,2)).
	int numVert 	= g_bcc_ds.numVert;

	// std::cout << "numEdges = " << numEdges << std::endl;
	// std::cout << "numVert = " << numVert << std::endl;

	// check if it is a tree or if the graph is even valid
	// handling edge-cases
	// if(numEdges == 0) {
	// 	// handle this case
	// }

	// else if(numEdges == 1) {
	// 	// handle this case
	// }

	// long num_non_tree_edges = numEdges - (numVert - 1);
	// else if(!num_non_tree_edges) {
	// 	// handle for tree
	// }

	long E = 2 * numEdges; // Two times the original edges count (0,1) and (1,0).
    
    // csr data-structures
    long* d_vertices = g_bcc_ds.d_vertices;
    int* d_edges = g_bcc_ds.d_edges;

	int *d_parent = g_bcc_ds.d_parent;
	int *d_level = g_bcc_ds.d_level;

	// Create a random device and seed it
    std::random_device rd;
    std::mt19937 gen(rd());

    // Create a distribution in the range [0, numVert]
    std::uniform_int_distribution<> distrib(0, numVert - 1);

    // Generate a random root value
    int root = distrib(gen);
    int root_level = 0;
    // Output the random root value
    // std::cout << "Random root value: " << root << std::endl;

	int child_of_root = -1;

	CUDA_CHECK(cudaMemcpy(&d_level[root], &root_level, sizeof(int), cudaMemcpyHostToDevice), "Failed to set root level.");

	Timer myTimer;
	auto start = std::chrono::high_resolution_clock::now();	
	// Step 1: Construct a rooted spanning tree
	constructSpanningTree(numVert, E, d_vertices, d_edges, d_level, d_parent, root, child_of_root);
	
	auto end = std::chrono::high_resolution_clock::now();
	auto dur = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
	
	std::cout <<"Spanning tree creation finished in: " << dur <<" ms.\n";

	// #ifdef DEBUG
	// 	std::vector<int> h_parent(numVert);
	// 	std::vector<int> h_level(numVert);

	// 	CUDA_CHECK(cudaMemcpy(h_parent.data(), d_parent, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
	//     				"Failed to copy back parent array to host.");

	// 	CUDA_CHECK(cudaMemcpy(h_level.data(), d_level, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
	//     				"Failed to copy back level array to host.");

	// 	print(h_parent, "parent array");
	// 	print(h_level,   "level array");
	// #endif

	// special case adding here, remove in release
	// std::vector<int> h_parent(numVert);
	// std::vector<int> h_level(numVert);
	// h_parent = {2, 2, 2, 22, 25, 20, 14, 1, 0, 1, 8, 0, 19, 23, 26, 11, 7, 24, 9, 1, 1, 0, 21, 0, 1, 0, 0};
	// h_level = {1,1,0,4,3,3,4,2,2,2,3,2,3,3,3,3,3,3,3,2,2,2,3,2,2,2,2};
	// CUDA_CHECK(cudaMemcpy(d_parent, h_parent.data(), numVert * sizeof(int), cudaMemcpyHostToDevice), 
	    				// "Failed to copy back parent array to host.");

	// CUDA_CHECK(cudaMemcpy(d_level, h_level.data(), numVert * sizeof(int), cudaMemcpyHostToDevice), 
	//     				"Failed to copy back parent array to host.");

	#ifdef DEBUG
		// std::vector<int> h_parent(numVert);
		// std::vector<int> h_level(numVert);
		CUDA_CHECK(cudaMemcpy(h_parent.data(), d_parent, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
	    				"Failed to copy back parent array to host.");

		CUDA_CHECK(cudaMemcpy(h_level.data(), d_level, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
	    				"Failed to copy back level array to host.");

		print(h_parent, "parent array");
		print(h_level,   "level array");
	#endif

	// Step 3 & 4 : Find LCA and Base Vertices, then apply connected Comp
    naive_lca(g_bcc_ds, root, child_of_root);

    // Step 5: Propagate safness to representative & parents
    // Step 6: Update cut vertex status and cut - edge status
    // Step 7: Update implicit bcc labels
    assign_cut_vertex_BCC(g_bcc_ds, root, child_of_root);
    dur = myTimer.stop();
 	std::cout <<"cudaBCC finished in: " << dur <<" ms." << std::endl;
}
