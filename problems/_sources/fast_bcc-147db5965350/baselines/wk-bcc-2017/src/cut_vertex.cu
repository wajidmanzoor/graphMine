#include "cut_vertex.cuh"
#include "cuda_utility.cuh"
#include "bcc_memory_utils.cuh"

#include "utility.hpp"

#include <chrono>

// int totalThreads = 1024;
// #define DEBUG

__global__ 
void Propagate_Safeness_to_rep(int totalVertices, int *d_isBaseVertex, int *d_rep, int *d_isSafe) {
	
	int tid = blockDim.x * blockIdx.x + threadIdx.x;

    if(tid < totalVertices) {
		if(d_isBaseVertex[tid] && d_isSafe[tid]) {
			d_isSafe[d_rep[tid]] = 1;
		}
	}
}

__global__ 
void Propagate_Safeness_to_comp(int totalVertices, int *d_rep, int *d_isSafe) {
	
	int tid = blockDim.x * blockIdx.x + threadIdx.x;
    if(tid < totalVertices) {
		if(d_isSafe[d_rep[tid]]) {
			d_isSafe[tid] = 1;
		}
	}
}

__global__ 
void Find_Unsafe_Component(int root, int totalVertices, int *d_rep, int *d_isSafe, int *d_cutVertex, int *d_parent, int *d_totalChild) {

	int tid = blockDim.x * blockIdx.x + threadIdx.x;
  	
  	if(tid < totalVertices) {
		if(d_rep[tid] == tid && !d_isSafe[tid] && tid != root) {
			d_cutVertex[d_parent[tid]] = 1;

			// Optimize here
			if(d_parent[tid] == root) {
				d_cutVertex[root] = 0;
				atomicAdd(d_totalChild, 1);
			}
		}
	}
}

__global__ 
void updateCutVertex(int totalVertices, int *d_parent, int *d_partOfFundamental, long *d_offset, int *d_cutVertex) {
    
    int tid = blockDim.x * blockIdx.x + threadIdx.x;

  	if(tid < totalVertices) {
  		int u = tid;
  		int v = d_parent[u];

		if (u == v) {
			return;
		}

		if (d_partOfFundamental[u]) {
			return;
		}
		
		if(d_offset[u+1] - d_offset[u] > 1) {
			d_cutVertex[u] = 1;
		}

		if(d_offset[v+1] - d_offset[v] > 1) {
			d_cutVertex[v] = 1;
		}
	}
}

__global__ 
void implicit_bcc(int totalVertices, int *isSafe, int *representative, int *parent, int *baseVertex, long *nonTreeEdgeId, int *unsafeRep) {

    int tid = blockDim.x * blockIdx.x + threadIdx.x;

    if(tid < totalVertices) {
        int u = tid;

        while(isSafe[u] == 1) {
            long i = nonTreeEdgeId[parent[u]];
            int b = baseVertex[i];
            u = representative[b];
        }

        unsafeRep[tid] = representative[u];
    }
}

void assign_cut_vertex_BCC(const gpu_bcc& g_bcc_ds, int root, int child_of_root) {
	
	int no_of_vertices 		 = 	g_bcc_ds.numVert;
	int *d_isBase 			 = 	g_bcc_ds.d_is_baseVertex;
	int *d_rep 				 = 	g_bcc_ds.d_rep;
	int *d_isSafe 			 = 	g_bcc_ds.d_isSafe;
	int *d_baseVertex 		 = 	g_bcc_ds.d_baseVertex;
	int *d_cutVertex 		 = 	g_bcc_ds.d_cut_vertex;
	int *d_parent 			 = 	g_bcc_ds.d_parent;
	int *d_partOfFundamental = 	g_bcc_ds.d_isPartofFund;
	int *d_imp_bcc_num 		 = 	g_bcc_ds.d_imp_bcc_num;

	long *d_offset 			 = 	g_bcc_ds.d_vertices;
	long *d_nonTreeEdgeId 	 = 	g_bcc_ds.d_nonTreeEdgeId;
	
	int totalThreads = 1024;
	int no_of_blocks = (no_of_vertices + totalThreads - 1) / totalThreads;

	auto start = std::chrono::high_resolution_clock::now();
	Propagate_Safeness_to_rep<<<no_of_blocks, totalThreads>>>(no_of_vertices, d_isBase, d_rep, d_isSafe);
	
	CUDA_CHECK(cudaGetLastError(), "Propagate_Safeness_to_rep Kernel launch failed");
	Propagate_Safeness_to_comp<<<no_of_blocks, totalThreads>>>(no_of_vertices, d_rep, d_isSafe);
	CUDA_CHECK(cudaGetLastError(), "Propagate_Safeness_to_comp Kernel launch failed");

    // Find un_safe components
    int totalRootChild = 0;
    int *d_totalRootChild;
    CUDA_CHECK(cudaMalloc((void **)&d_totalRootChild, sizeof(int)), "Failed to allocate memory for root_child_count");
    CUDA_CHECK(cudaMemcpy(d_totalRootChild, &totalRootChild, sizeof(int), cudaMemcpyHostToDevice), "totalRootChild cannot be copied into gpu");
    
    
	Find_Unsafe_Component<<<no_of_blocks, totalThreads>>>(root, no_of_vertices, d_rep, d_isSafe, d_cutVertex, d_parent, d_totalRootChild);
	CUDA_CHECK(cudaGetLastError(), "Find_Unsafe_Component Kernel launch failed");

	CUDA_CHECK(cudaMemcpy(&totalRootChild, d_totalRootChild, sizeof(int), cudaMemcpyDeviceToHost), "d_totalRootChild cannot be copied into cpu");

	updateCutVertex<<<no_of_blocks, totalThreads>>>(no_of_vertices, d_parent, d_partOfFundamental, d_offset, d_cutVertex);
	CUDA_CHECK(cudaGetLastError(), "updateCutVertex Kernel launch failed");
    CUDA_CHECK(cudaDeviceSynchronize(), "Error during cudaDeviceSynchronize()");

	// std::cout <<"Total root child : " << totalRootChild << std::endl;
	if(totalRootChild > 1) {
		int root_vertex_status = 1;
		CUDA_CHECK(cudaMemcpy(&d_cutVertex[root], &root_vertex_status, sizeof(int), cudaMemcpyHostToDevice) , "root cut vertex status cannot be copied into gpu");
	}

	#ifdef DEBUG
		std::vector<int> h_isSafe(no_of_vertices);
		CUDA_CHECK(cudaMemcpy(h_isSafe.data(), d_isSafe, no_of_vertices*sizeof(int), cudaMemcpyDeviceToHost), "Failed to copy d_isSafe to host");
		std::cout << "h_isSafe array:\n";
		for(const auto &i : h_isSafe)
			std::cout << i <<" ";
		std::cout << std::endl;
	#endif
		
	
	implicit_bcc<<<no_of_blocks, totalThreads>>>(no_of_vertices, d_isSafe, d_rep, d_parent, d_baseVertex, d_nonTreeEdgeId, d_imp_bcc_num);

	CUDA_CHECK(cudaGetLastError(), "updateCutVertex Kernel launch failed");
    // CUDA_CHECK(cudaDeviceSynchronize(), "Error during implicit_bcc/cudaDeviceSynchronize()");

    if(totalRootChild == 1) {
	    // Copy the BCC number from the child node to the root node
		CUDA_CHECK(cudaMemcpy(&d_imp_bcc_num[root], &d_imp_bcc_num[child_of_root], sizeof(int), cudaMemcpyDeviceToDevice), "failed to update root bcc number");
	}

	auto end = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count();
    std::cout <<"implicit_bcc took: " << duration <<" ms\n";
}