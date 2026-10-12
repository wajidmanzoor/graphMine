// This version assigns correct edge labels to all bcc's

#include <string>
#include <vector>
#include <fstream>
#include <iostream>
#include<unordered_set>

#include <unistd.h>
#include <cuda_runtime.h>

#include "graph.hpp"
#include "timer.hpp"
#include "utility.hpp"

#include "bcc.cuh"
#include "cuda_utility.cuh"
#include "bcc_memory_utils.cuh"
#include "CommandLineParser.cuh"

void assign_edge_bcc(const std::vector<int>& U, const std::vector<int>& V, std::vector<int>& edge_bcc_num, const std::vector<int>& imp_bcc_num, const std::vector<int>& cut_vertex, const std::vector<int>& parent) {
	long numEdges = U.size();
	for(long i = 0; i < numEdges; ++i) {
		
		// case_1: both are non-cut_vertices
		int u = U[i];
		int v = V[i];
		if(!cut_vertex[u] and !cut_vertex[v]) {
			edge_bcc_num[i] = imp_bcc_num[u];
		}

		// case_2: both are cut_vertices
		else if(cut_vertex[u] and cut_vertex[v]) {
			if(parent[u] == v) {
				std::cout << "parent of u is v";
				// assign the bcc_num of child
				edge_bcc_num[i] = imp_bcc_num[u];
			} else if(parent[v] == u) {
				std::cout << "parent of v is u";
				edge_bcc_num[i] = imp_bcc_num[v];
			}
			else {
				std::cout << "Not a tree edge.";
				edge_bcc_num[i] = imp_bcc_num[u];
			}
		}

		// case_3: one vertex is cut_vertex and the other non_cut_vertex
		else {
			edge_bcc_num[i] = imp_bcc_num[!cut_vertex[u]? u : v];
		}
	}
}

int main(int argc, char* argv[]) {
	std::ios_base::sync_with_stdio(false);
	CommandLineParser cmdParser(argc, argv);
	const auto& args = cmdParser.getArgs();
		
	if (args.error) {
        std::cerr << CommandLineParser::help_msg << std::endl;
        exit(EXIT_FAILURE);
    }

	// Set the CUDA device
    CUDA_CHECK(cudaSetDevice(args.cudaDevice), "Unable to set device ");

	std::string filename = args.inputFile;
	std::cout <<"\n\nReading " << get_file_extension(filename) << " file.\n";
	Timer t1;
	undirected_graph G(filename);
	auto dur = t1.stop();
	// std::cout <<"Reading input and csr creation finished in: " << formatDuration(dur) << std::endl;
	t1.reset();

	bool write_output = args.write_output;
	// write_output = false;
	std::string output_path = args.output_directory;

	cudaFree(0);
	int numVert = G.numVert;
	long numEdges = G.u_arr.size();

	gpu_bcc g_bcc_ds(numVert, numEdges);
	// Copy the edge-list
	CUDA_CHECK(cudaMemcpy(g_bcc_ds.original_u, G.u_arr.data(), numEdges * sizeof(int), cudaMemcpyHostToDevice), 
    			"Unable to copy original_u array to device");
    CUDA_CHECK(cudaMemcpy(g_bcc_ds.original_v, G.v_arr.data(), numEdges * sizeof(int), cudaMemcpyHostToDevice),
    			"Unable to copy original_v array to device");

    // Copy the csr graph
    CUDA_CHECK(cudaMemcpy(g_bcc_ds.d_vertices, G.vertices.data(), G.vertices.size() * sizeof(long), cudaMemcpyHostToDevice), 
    			"Unable to copy csr_edge_offset array to device");
    CUDA_CHECK(cudaMemcpy(g_bcc_ds.d_edges, G.edges.data(), G.edges.size() * sizeof(int), cudaMemcpyHostToDevice),
    			"Unable to copy csr_neighbour array to device");

    // init data_structures
	g_bcc_ds.init(numVert, numEdges);

	// start cuda_bcc
    cuda_bcc(g_bcc_ds);

	if(write_output) {
		std::vector<int> host_cut_vertex(numVert);
		CUDA_CHECK(cudaMemcpy(host_cut_vertex.data(), g_bcc_ds.d_cut_vertex, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
					"Failed to copy d_cut_vertex to host");

		std::vector<int> host_implicit_bcc_number(numVert);
		CUDA_CHECK(cudaMemcpy(host_implicit_bcc_number.data(), g_bcc_ds.d_imp_bcc_num, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
					"Failed to copy d_imp_bcc_num to host");

		filename = get_file_extension(filename);
		filename += "_result.txt";
		filename = output_path + filename;

		std::cout << "Writing output to: " << filename << std::endl;
		
		std::ofstream outfile(filename);
   		if(!outfile) {
   			std::cerr <<"Unable to create file.\n";
   			return EXIT_FAILURE;
   		}
   		outfile << numVert << std::endl; //<<"\t" << numEdges << std::endl;
   		int ncv, j; //ncv -> num_Cut_vertex
   		j = ncv = 0;
   		outfile << "cut vertex status\n";
   		for(const auto&i : host_cut_vertex) {
   			if(i)
   	        	ncv++;
   			outfile << j++ << "\t" << i << std::endl;
   		}
   		std::cout <<"Total CV count: " << ncv << std::endl;
   
   		j = 0;
   		outfile << "vertex BCC number\n";
   		for(const auto&i : host_implicit_bcc_number)
   			outfile << j++ << "\t" << i << std::endl;

   		// assign edge bcc numbers
   		std::vector<int> edge_bcc_num(numEdges);
   		int *d_parent = g_bcc_ds.d_parent;
   		std::vector<int> h_parent(numVert);

		CUDA_CHECK(cudaMemcpy(h_parent.data(), d_parent, numVert * sizeof(int), cudaMemcpyDeviceToHost), 
	    				"Failed to copy back parent array to host.");
   		assign_edge_bcc(G.u_arr, G.v_arr, edge_bcc_num, host_implicit_bcc_number, host_cut_vertex, h_parent);

   		// write edge_bcc numbers
		j = 0;
   		outfile << "edge BCC numbers\n";
   		outfile << numEdges << "\n";
   		for(long i = 0; i < numEdges; ++i) {
   			outfile << G.u_arr[i] <<" - " << G.v_arr[i] << " -> " << edge_bcc_num[i] << std::endl;
   		}

   		int nbcc = 0;
		std::unordered_set<int> seen_bcc;

		for(int i = 0; i < numEdges; ++i){
			if( seen_bcc.find(edge_bcc_num[i]) == seen_bcc.end() ){
				nbcc++;
				seen_bcc.insert(edge_bcc_num[i]);
			}
		}

		outfile << ncv << " " << nbcc << "\n";
   	}
    return EXIT_SUCCESS;
}