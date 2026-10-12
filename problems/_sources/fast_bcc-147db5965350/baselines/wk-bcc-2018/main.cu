#include <iostream>  
#include <string>
#include <filesystem>
#include <cstdlib>
#include <set>
#include <cuda_runtime.h>

#include "cuda_utility.cuh"
#include "graph.cuh"

#include "sampling.cuh"
#include "cuda_bcc/connected_components.cuh"
#include "cuda_bcc/bcc.cuh"
#include "final_bcc/vertex_merging.cuh"

//---------------------------------------------------------------------
// Utility Functions
//---------------------------------------------------------------------
std::string get_file_extension(const std::string& filename) {
    size_t dot_pos = filename.find_last_of(".");
    if (dot_pos == std::string::npos) {
        return "";
    }
    return filename.substr(dot_pos + 1);
}

//---------------------------------------------------------------------
// Main
//---------------------------------------------------------------------
int main(int argc, char* argv[]) {
    std::ios_base::sync_with_stdio(false);

    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <input_file> [k] [verbose]" << std::endl;
        std::cerr << "  <input_file>  : Path to the graph file" << std::endl;
        std::cerr << "  [k]           : Max edges per vertex to sample (default: 2)" << std::endl;
        std::cerr << "  [verbose]     : Enable verbose output, 0 or 1 (default: 0)" << std::endl;
        return EXIT_FAILURE;
    }

    std::string filename = argv[1];
        int k = 2;  // Default value
        
        // Parse optional k parameter
        if (argc >= 3) {
            try {
                k = std::stoi(argv[2]);
                if (k <= 0) {
                    std::cerr << "Error: k must be a positive integer" << std::endl;
                    return EXIT_FAILURE;
                }
            } catch (const std::exception& e) {
                std::cerr << "Error: Invalid k value - " << e.what() << std::endl;
                return EXIT_FAILURE;
            }
        }
        
        // Parse optional verbose parameter
        if (argc >= 4) {
            try {
                int verbose_val = std::stoi(argv[3]);
                g_verbose = (verbose_val != 0);
            } catch (const std::exception& e) {
                std::cerr << "Error: Invalid verbose value - " << e.what() << std::endl;
                return EXIT_FAILURE;
            }
        }
        
        std::cout << "\nReading " << std::filesystem::path(filename).filename().string() << " file." << std::endl << std::endl;
        undirected_graph g(filename);

        int     num_vert    =   g.getNumVertices();
        long    num_edges   =   g.getNumEdges();

        // std::cout << "Vertices: " << num_vert << std::endl;
        // std::cout << "Edges: " << num_edges / 2 << std::endl;

        if (g_verbose) {
            std::cout << "\n\nOutputting CSR representation: \n";
            g.print_CSR();

            std::cout << "\n\nEdgeList:\n";
            g.print_edgelist();

            // print the exact csr arrays (offset and edges)
            std::cout << "\nVertices array: \n";
            const auto& vertices = g.getVertices();
            for (size_t i = 0; i < vertices.size(); ++i) {
                std::cout << vertices[i] << " ";        
            }
            std::cout << "\n\nEdges array: \n";
            const auto& edges = g.getEdges();
            for (size_t i = 0; i < edges.size(); ++i) {
                std::cout << edges[i] << " ";
            }
        }

        // copy vertices and edges to device
        long* d_row_offsets = nullptr;
        // int*  d_col_indices = nullptr;  

        CUDA_CHECK(cudaMalloc(&d_row_offsets, (num_vert + 1) * sizeof(long)), "Allocating d_row_offsets failed");
        CUDA_CHECK(cudaMemcpy(d_row_offsets, g.getVertices().data(),
                              (num_vert + 1) * sizeof(long),
                              cudaMemcpyHostToDevice), "Copying to d_row_offsets failed");  
        
        // this is not unique edges; i.e. contains both (u,v) and (v,u)
        uint64_t* d_edgelist = nullptr;
        CUDA_CHECK(cudaMalloc(&d_edgelist, num_edges * sizeof(uint64_t)), "Allocating d_edgelist failed");
        CUDA_CHECK(cudaMemcpy(d_edgelist, g.getEdgeList().data(),
                              num_edges * sizeof(uint64_t),
                              cudaMemcpyHostToDevice), "Copying to d_edgelist failed");  

        // step 1: k-out sampling
        // std::cout << "\n\n========== K-OUT SAMPLING TEST ==========" << std::endl;
        // std::cout << "Sampling up to " << k << " edges per vertex..." << std::endl;

        // input: d_row_offsets, d_col_indices, num_vert, num_edges, k
        // output: sampled edges on device
        auto sampled_edges = k_out_sampling(
            d_row_offsets, 
            d_edgelist,
            num_vert, 
            num_edges, 
            k);

        int* d_U_ptr = std::get<2>(sampled_edges);
        int* d_V_ptr = std::get<3>(sampled_edges);
        long actual_sampled_edges = std::get<4>(sampled_edges);

        // step 2: Connected Components
        // std::cout << "\n\n========== CONNECTED COMPONENTS TEST ==========" << std::endl;
        int* d_rep = nullptr;
        int* d_flag = nullptr;

        CUDA_CHECK(cudaMalloc(&d_rep, num_vert * sizeof(int)), "Allocating d_rep failed");
        CUDA_CHECK(cudaMalloc(&d_flag, sizeof(int)), "Allocating d_flag failed");
        connected_comp(actual_sampled_edges, d_U_ptr, d_V_ptr, num_vert, d_rep, d_flag);
        
        // copy d_rep to host to get number of connected components
        std::vector<int> h_rep(num_vert);
        CUDA_CHECK(cudaMemcpy(h_rep.data(), d_rep, num_vert * sizeof(int), cudaMemcpyDeviceToHost), "Copying d_rep to host failed");
        std::set<int> unique_reps;
        for (int i = 0; i < num_vert; ++i) {
            unique_reps.insert(h_rep[i]);
        }
        int num_cc = unique_reps.size();

        if(num_cc > 1) {
            std::cout << "The sampled graph is disconnected with " << num_cc << " connected components." << std::endl;
            exit(EXIT_FAILURE);
        }
        else
            std::cout << "The sampled graph is connected." << std::endl;

        /* step 3: BiConnected Components */
            // std::cout << "\n\n========== Computing BICONNECTED COMPONENTS ==========" << std::endl;
            
            gpu_bcc g_bcc_ds(num_vert, actual_sampled_edges);
            
            // copy csr graph
            g_bcc_ds.d_vertices = std::get<0>(sampled_edges);
            g_bcc_ds.d_edges = std::get<1>(sampled_edges);
            
            // Copy the edge-list
            g_bcc_ds.original_u = std::get<2>(sampled_edges);
            g_bcc_ds.original_v = std::get<3>(sampled_edges);
            // init data_structures
            g_bcc_ds.init(num_vert, actual_sampled_edges);

            // start cuda_bcc
            cuda_bcc(g_bcc_ds);
            /* BCC computation completed */

            /* Step 4: Merge the BCCs to get graph F */
            // std::cout << "\n\n========== Merging BICONNECTED COMPONENTS ==========" << std::endl;
            vertex_merging(num_vert, g_bcc_ds, d_edgelist, num_edges);
            /* Vertex Merging completed */

        print_total_function_time("Sampling WK-BCC (2018)");
    return EXIT_SUCCESS;
}

// ====[ End of Main Code ]====