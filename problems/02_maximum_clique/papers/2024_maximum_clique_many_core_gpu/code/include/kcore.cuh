#pragma once
#include <cuda_runtime.h>

#include "cgarray.cuh"
#include "cub_wrapper.cuh"
#include "defs.h"
#include "graph_queue.cuh"
#include "logger.h"
#include "utils.cuh"
#include "../mcp/mcp_utils.cuh"

#define LEVEL_SKIP_SIZE (128)

template <typename T, typename CntType>
__global__ void init_asc(T *data, CntType count)
{
	T gtid = threadIdx.x + blockIdx.x * blockDim.x;
	if (gtid < count)
		data[gtid] = (T)gtid;
}

template <typename T, typename PeelT>
__global__ void filter_window(PeelT *edge_sup, T count, bool *in_bucket, T low, T high)
{
	auto gtid = threadIdx.x + blockIdx.x * blockDim.x;
	if (gtid < count)
	{
		auto v = edge_sup[gtid];
		in_bucket[gtid] = (v >= low && v < high);
	}
}

template <typename T, typename PeelT>
__global__ void filter_with_random_append(
		T *bucket_buf, T count, PeelT *EdgeSupport,
		bool *in_curr, T *curr, T *curr_cnt, T ref, T span)
{
	auto gtid = threadIdx.x + blockIdx.x * blockDim.x;
	if (gtid < count)
	{
		auto edge_off = bucket_buf[gtid];
		if (EdgeSupport[edge_off] >= ref && EdgeSupport[edge_off] < ref + span)
		{
			in_curr[edge_off] = true;
			auto insert_idx = atomicAdd(curr_cnt, 1);
			curr[insert_idx] = edge_off;
		}
	}
}

template <typename T, typename PeelT>
__global__ void update_priority(graph::GraphQueue_d<T, bool> current, T priority, T *nodePriority, T *coreNumber)
{
	auto gtid = threadIdx.x + blockIdx.x * blockDim.x;
	if (gtid < current.count[0])
	{
		auto edge_off = current.queue[gtid];
		nodePriority[edge_off] = priority;
		coreNumber[edge_off] = 0;
	}
}

template <typename T>
__device__ void add_to_queue_1(graph::GraphQueue_d<T, bool> &q, T element)
{
	auto insert_idx = atomicAdd(q.count, 1);
	q.queue[insert_idx] = element;
	q.mark[element] = true;
}

template <typename T>
__device__ void add_to_queue_1_no_dup(graph::GraphQueue_d<T, bool> &q, T element)
{
	auto old_token = atomicCASBool(q.mark + element, 0, 1);
	if (!old_token)
	{
		auto insert_idx = atomicAdd(q.count, 1);
		q.queue[insert_idx] = element;
	}
}

template <typename T, typename PeelT>
__forceinline__ __device__ void process_degree(
		T nodeId, T level, PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> &next,
		graph::GraphQueue_d<T, bool> &bucket,
		T bucket_level_end_)
{
	auto cur = atomicSub(&nodeDegree[nodeId], 1);
	if (cur == (level + 1))
		add_to_queue_1(next, nodeId);
	
	// Update the Bucket.
	auto latest = cur - 1;
	if (latest > level && latest < bucket_level_end_)
		add_to_queue_1_no_dup(bucket, nodeId);

}

template <typename T, typename PeelT>
__global__ void getNodeDegree_kernel(PeelT *nodeDegree, graph::COOCSRGraph_d<T> g)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;
	for (uint64 i = gtid; i < g.numNodes; i += blockDim.x * gridDim.x)
	{
		nodeDegree[i] = g.rowPtr[i + 1] - g.rowPtr[i];
	}
}

template <typename T, uint CPARTSIZE = 32>
__global__ void getNodeNumberReducedByLB_kernel(graph::COOCSRGraph_d<T> g, T* coreNumber, unsigned int lower_bound, T* count)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	uint64 local_count = 0;

	for (T j = gtid; j < g.numNodes; j += blockDim.x * gridDim.x)
	{
		// Get just vertex whose core number greater than lb
		if (coreNumber[j] >= (lower_bound))
			local_count++;
	}

	__syncthreads();

	T mask = 0xFFFFFFFF;
	mcp::reduce_part<T, CPARTSIZE>(mask, local_count);

	__syncthreads();

	// Each thread number 0 of each lane
	if (threadIdx.x % CPARTSIZE == 0)
		atomicAdd(count, local_count);

}

template <typename T, uint CPARTSIZE = 32>
__global__ void computeFlags_kernel(graph::COOCSRGraph_d<T> g, T* coreNumber, unsigned int lower_bound, char* flags)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// If over the last node return
	if (gtid >= g.numNodes)
		return;

	for (T j = gtid; j < g.numNodes; j += blockDim.x * gridDim.x)
	{
		// Get just vertex whose core number greater than lb
		flags[j] = coreNumber[j] >= (lower_bound) ? 1 : 0;
	}	
}

template <typename T, uint CPARTSIZE = 32>
__global__ void generateIndices_kernel(T* array , T maxIndex)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	T node = gtid;

	// If over the last node return
	if (gtid >= maxIndex)
		return;

	for (T j = gtid; j < maxIndex; j += blockDim.x * gridDim.x)
	{
		// Get just vertex whose core number greater than lb
		array[j] = j;
	}	
}

template <typename T>
__global__ void computeNewName_kernel(T *oldName, T *newName, T n_old, T n_new)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	T node = gtid;

	// If over the last node return
	if (node >= n_old)
		return;

	for (T j = gtid; j < n_old; j += blockDim.x * gridDim.x)
	{
		T old = oldName[j];
		newName[old] = j;
	}
}

template <typename T, uint CPARTSIZE = 32>
__global__ void getEdgeNumberAndDegreesReducedByLB_kernel(graph::COOCSRGraph_d<T> g, T* coreNumber, unsigned int lower_bound, T* count, T* degrees)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	T node = gtid;
	T global_count = 0;

  __syncthreads();

  for (T j = gtid; j < g.numNodes; j += blockDim.x * gridDim.x)
	{
		T local_count = 0;
		// Get just vertex whose core number greater than lb
		if (coreNumber[j] >= lower_bound) {
			
			T old_degree = g.rowPtr[j + 1] - g.rowPtr[j];
			T offset = g.rowPtr[j];
			for (int i = 0; i < old_degree; i++)
			{
				T vertex = g.colInd[offset + i];
				local_count += coreNumber[vertex] >= (lower_bound) ? 1 : 0;
			}
		}

		degrees[j] = local_count;
		global_count += local_count;

  }

  __syncthreads();

	// Sum in parallel
	T mask = 0xFFFFFFFF;
	mcp::reduce_part<T, CPARTSIZE>(mask, global_count);

	__syncthreads();

	// Each thread number 0 of each lane
	if (threadIdx.x % CPARTSIZE == 0)
		atomicAdd(count, global_count);

}

template <typename T, typename PeelType, uint CPARTSIZE = 32>
__global__ void buildReducedByLB_kernel(graph::COOCSRGraph_d<T> g, graph::COOCSRGraph_d<T> red_g, T* coreNumber, T* oldName, T* newName, unsigned int lower_bound)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	T node = gtid;

	// If over the last node return
	if (gtid >= red_g.numNodes)
		return;

	for (T k = gtid; k < red_g.numNodes; k += blockDim.x * gridDim.x)
	{
		// Get just vertex whose core number greater than lb
		uint64 old_degree = g.rowPtr[oldName[k] + 1] - g.rowPtr[oldName[k]];
		uint64 new_degree = red_g.rowPtr[k + 1] - red_g.rowPtr[k];

		int j = 0;
		uint64 old_offset = g.rowPtr[oldName[k]];
		uint64 offset = red_g.rowPtr[k];
		for (int i = 0; i < old_degree; i++)
		{  
			T vertex = g.colInd[old_offset + i];

			if (coreNumber[vertex] > (lower_bound - 1)) 
			{
				red_g.colInd[offset + j] = newName[vertex];
				red_g.rowInd[offset + j++] = k;
			}
		}
	}

}

template <typename T, typename PeelType, uint CPARTSIZE = 32>
__global__ void buildReducedByLBB_kernel(graph::COOCSRGraph_d<T> g, graph::COOCSRGraph_d<T> red_g, T* coreNumber, T* oldName, T* newName, unsigned int lower_bound)
{
	uint64 gtid = threadIdx.x + blockIdx.x * blockDim.x;

	// Gets the node
	T node = gtid;

	// If over the last node return
	if (gtid >= red_g.numNodes)
		return;

	// Get just vertex whose core number greater than lb
	uint64 old_degree = g.rowPtr[oldName[node] + 1] - g.rowPtr[oldName[node]];

	int j = 0;
	uint64 old_offset = g.rowPtr[oldName[node]];
	uint64 offset = red_g.rowPtr[node];
	for (int i = 0; i < old_degree; i++)
	{  
		T vertex = g.colInd[old_offset + i];

		if (coreNumber[vertex] >= (lower_bound)) 
		{
			red_g.colInd[offset + j] = newName[vertex];
			red_g.rowInd[offset + j++] = node;
		}
	}
	
	return;
}

template <typename T, typename PeelType, uint CPARTSIZE = 32>
__global__ void buildReducedByLBBW_kernel(graph::COOCSRGraph_d<T> g, graph::COOCSRGraph_d<T> red_g, T* coreNumber, T* oldName, T* newName, unsigned int lower_bound)
{
	uint64 wgtid = (threadIdx.x + blockIdx.x * blockDim.x) / CPARTSIZE;
	const uint _laneIdx = threadIdx.x % CPARTSIZE;

	// Gets the node
	T node = wgtid;

	// If over the last node return
	if (wgtid >= red_g.numNodes)
		return;

	// Get just vertex whose core number greater than lb
	uint64 old_degree = g.rowPtr[oldName[node] + 1] - g.rowPtr[oldName[node]];

	int j = 0;
	uint64 old_offset = g.rowPtr[oldName[node]];
	uint64 offset = red_g.rowPtr[node];
	
	if (_laneIdx == 0)
	{
		for (int i = 0; i < old_degree; i++)
		{  
			T vertex = g.colInd[old_offset + i];

			if (coreNumber[vertex] > (lower_bound - 1)) 
			{
				red_g.colInd[offset + j] = newName[vertex];
				red_g.rowInd[offset + j++] = node;
			}
		}
	}
	
	return;
}


template <typename T, typename PeelT, int BD, int P>
__global__ void
kernel_partition_level_next(
		graph::COOCSRGraph_d<T> g,
		int level, bool *processed, PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> current,
		graph::GraphQueue_d<T, bool> &next,
		graph::GraphQueue_d<T, bool> &bucket,
		int bucket_level_end_,
		T priority,
		T *nodePriority,
		T *coreNumber)
{
	const size_t partitionsPerBlock = BD / P;
	const size_t lx = threadIdx.x % P;
	const int _warpIdx = threadIdx.x / P; // which warp in thread block
	const size_t gwx = (blockDim.x * blockIdx.x + threadIdx.x) / P;

	for (auto i = gwx; i < current.count[0]; i += blockDim.x * gridDim.x / P)
	{
		T nodeId = current.queue[i];
		T srcStart = g.rowPtr[nodeId];
		T srcStop = g.rowPtr[nodeId + 1];

		nodePriority[nodeId] = priority;
		coreNumber[nodeId] = level;
	
		for (auto j = srcStart + lx; j < (srcStop + P - 1) / P * P; j += P)
		{
			__syncwarp();
			if (j < srcStop)
			{
				T affectedNode = g.colInd[j];
				if (!current.mark[affectedNode])
					process_degree<T>(affectedNode, level, nodeDegree, next, bucket, bucket_level_end_);
			}
		}
	}
}

template <typename T, typename PeelT, int BD, int P>
__global__ void
kernel_partition_remove_vertices(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> kcore,
		graph::GraphQueue_d<T, bool> clique,
		PeelT min_degree)
{
	const size_t partitionsPerBlock = BD / P;
	const size_t lx = threadIdx.x % P;
	const int _warpIdx = threadIdx.x / P; // which warp in thread block
	const size_t gwx = (blockDim.x * blockIdx.x + threadIdx.x) / P;

	for (auto i = gwx; i < clique.count[0]; i += blockDim.x * gridDim.x / P)
	{
		T nodeId = clique.queue[i];
		T srcStart = g.rowPtr[nodeId];
		T srcStop = g.rowPtr[nodeId + 1];

		for (auto j = srcStart + lx; j < (srcStop + P - 1) / P * P; j += P)
		{
			__syncwarp();
			if (j < srcStop)
			{
				T affectedNode = g.colInd[j];
				if (kcore.mark[affectedNode])
				{
					atomicSub(&nodeDegree[affectedNode], 1);
				}
			}
		}
	}
}

template <typename T, typename PeelT>
__global__ void
kernel_partition_remove_vertex(
		graph::COOCSRGraph_d<T> g,
		graph::GraphQueue_d<T, bool> kcore,
		PeelT *nodeDegree,
		T node
	)
{
	const auto gx = (blockDim.x * blockIdx.x + threadIdx.x);
	const T offset = g.rowPtr[node];
	const T offset_1 = g.rowPtr[node + 1];
	if (gx >= offset_1 - offset) return;
	const T neighbour = g.colInd[offset + gx];
	if (kcore.mark[neighbour]) nodeDegree[neighbour]--;
}

template <typename T, typename PeelT, int BD, int P>
__global__ void
kernel_update_marks(
		graph::COOCSRGraph_d<T> g,
		graph::GraphQueue_d<T, bool> &kcore,
		graph::GraphQueue_d<T, bool> clique)
{
	const auto gx = (blockDim.x * blockIdx.x + threadIdx.x);

	if (gx >= clique.count[0])
		return;

	T node = clique.queue[gx];
	kcore.mark[node] = false;
}


template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_fill_candidates_vertex(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> kcore,
		graph::GraphQueue_d<PeelT, bool> &degree
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= kcore.count[0])
		return;

	T node = kcore.queue[gtid];
	PeelT _degree = nodeDegree[node];

	if (kcore.mark[node]) {
		degree.queue[atomicAdd(degree.count, 1)] = _degree;
	}

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_fill_candidates_vertex(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> kcore,
		graph::GraphQueue_d<PeelT, bool> &degree,
		graph::GraphQueue_d<T, bool> &currents
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= kcore.count[0])
		return;

	T node = kcore.queue[gtid];
	PeelT _degree = nodeDegree[node];

	if (kcore.mark[node]) {
		T pos;
		degree.queue[pos = atomicAdd(degree.count, 1)] = _degree;
		currents.queue[pos] = node;
	}

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_fill_candidates_vertex_from_clique(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> kcore,
		graph::GraphQueue_d<T, bool> clique,
		graph::GraphQueue_d<PeelT, bool> &degree
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= clique.count[0])
		return;

	T node = clique.queue[gtid];
	PeelT _degree = nodeDegree[node];
	T pos;

	if (kcore.mark[node]) {
		degree.queue[atomicAdd(degree.count, 1)] = _degree;
	}

}


template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_get_minimum_degree_vertices(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		graph::GraphQueue_d<T, bool> kcore,
		graph::GraphQueue_d<T, bool> &clique,
		PeelT min_degree
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= kcore.count[0])
		return;

	T node = kcore.queue[gtid];
	PeelT degree = nodeDegree[node];

	if (kcore.mark[node] && degree == min_degree)
		clique.queue[atomicAdd(clique.count, 1)] = node;

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_fill_max_core_vertices (
		graph::COOCSRGraph_d<T> g,
		T *coreNumber,
		graph::GraphQueue_d<T, bool> &kcore,
		int max_core
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= g.numNodes)
		return;

	T node = gtid;
	int core = coreNumber[node];
	if (core == max_core)
	{
		kcore.queue[atomicAdd(kcore.count, 1)] = node;
		kcore.mark[node] = true;
	}

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_compute_degree_kcore(
		graph::COOCSRGraph_d<T> g,
		graph::GraphQueue_d<T, bool> kcore,
		PeelT* nodeDegree
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= kcore.count[0])
		return;

	T node = kcore.queue[gtid];
	T offset = g.rowPtr[node];
	T offset_1 = g.rowPtr[node + 1];
	PeelT deg = offset_1 - offset;

	for (int i = 0; i < deg; i++)
	{
		T neighbour = g.colInd[offset + i];
		if (kcore.mark[neighbour])
			nodeDegree[node]++;
	}

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_get_min_degree_vert(
		graph::COOCSRGraph_d<T> g,
		graph::GraphQueue_d<T, bool> current,
		PeelT* nodeDegree
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	if (gtid >= current.count[0])
		return;

	T node = current.queue[gtid];
	T offset = g.rowPtr[node];
	T offset_1 = g.rowPtr[node + 1];

	for (int i = 0; i < offset_1 - offset; i++)
	{
		T neighbour = g.colInd[offset + i];
		if (current.mark[neighbour])
			nodeDegree[node]++;
	}

}

template <typename T, typename PeelT, uint BLOCK_DIM_X, uint CPARTSIZE>
__global__ void
kernel_remove_vertex(
		graph::COOCSRGraph_d<T> g,
		PeelT *nodeDegree,
		T *node
)
{
	auto gtid = (blockDim.x * blockIdx.x) + threadIdx.x;

	T degree = g.rowPtr[*node + 1] - g.rowPtr[*node];
	T offset = g.rowPtr[*node];
	
	if (gtid >= degree)
		return;

	T neighbour = g.colInd[offset + gtid];

	nodeDegree[neighbour]--;

}

namespace graph
{
	template <typename T, typename PeelT>
	class SingleGPU_Kcore
	{
	private:
		int dev_;
		cudaStream_t stream_;

		// Outputs:
		// Max k of a complete ktruss kernel
		int k = 0;

		// Percentage of deleted edges for a specific k
		float percentage_deleted_k;

		// Same Function for any comutation
		void bucket_scan(
				GPUArray<PeelT> nodeDegree, T node_num, int level,
				GraphQueue<T, bool> &current,
				GPUArray<T> asc,
				GraphQueue<T, bool> &bucket,
				int &bucket_level_end_)
		{
			static bool is_first = true;
			if (is_first)
			{
				current.mark.setAll(false, true);
				bucket.mark.setAll(false, true);
				is_first = false;
			}

			const size_t block_size = 128;

			if (level == bucket_level_end_)
			{
				// Clear the bucket_removed_indicator
				// Filter nodes with grade between level and bucket_level_end_ + LEVEL_SKIP_SIZE
				T grid_size = (node_num + block_size - 1) / block_size;
				execKernel((filter_window<T, PeelT>), grid_size, block_size, dev_, false,
									 nodeDegree.gdata(), node_num, bucket.mark.gdata(), level, bucket_level_end_ + LEVEL_SKIP_SIZE);

				T val = CUBSelect(asc.gdata(), bucket.queue.gdata(), bucket.mark.gdata(), node_num, dev_);
				bucket.count.setSingle(0, val, true);
				bucket_level_end_ += LEVEL_SKIP_SIZE;
			}
			// SCAN the window.
			// If nodes count not 0 in bucket queue
			if (bucket.count.getSingle(0) != 0)
			{
				// Add in current queue nodes with degree greather eq than 0 an less than 1
				current.count.setSingle(0, 0, true);
				long grid_size = (bucket.count.getSingle(0) + block_size - 1) / block_size;
				execKernel((filter_with_random_append<T, PeelT>), grid_size, block_size, dev_, false,
									 bucket.queue.gdata(), bucket.count.getSingle(0), nodeDegree.gdata(), current.mark.gdata(), current.queue.gdata(), &(current.count.gdata()[0]), level, 1);
			}
			else
			{
				current.count.setSingle(0, 0, true);
			}
		}


		void find_heur_clique(COOCSRGraph_d<T> &g)
		{
			graph::GraphQueue<T, bool> kcore_q;
			kcore_q.Create(gpu, g.numNodes, dev_);
			kcore_q.mark.setAll(false, true);
			kcore_q.count.setSingle(0, 0, true);

			graph::GraphQueue<PeelT, bool> degree_q;
			degree_q.Create(gpu, g.numNodes, dev_);
			graph::GraphQueue<T, bool> currents_q;
			currents_q.Create(gpu, g.numNodes, dev_);
			
			GPUArray<PeelT> _nodeDegree;
			_nodeDegree.initialize("Aux degrees", AllocationTypeEnum::unified, g.numNodes, dev_);
			_nodeDegree.setAll(0, true);

			GPUArray<int> remaining;
			remaining.initialize("Ramaining nodes", AllocationTypeEnum::unified, 1, dev_);

			heurCliqueSize.initialize("Heur Clique", AllocationTypeEnum::unified, 1, dev_);
			heurCliqueSize.setSingle(0, 0, true);

			auto block_size = 256;
			auto node_grid_size = (g.numNodes + block_size - 1) / block_size;
			execKernel((kernel_fill_max_core_vertices<T, PeelT, 256, 32>), node_grid_size, block_size, dev_, false, g, coreNumber.gdata(),
										kcore_q.device_queue->gdata()[0], k - 1);
			auto grid_size = (kcore_q.count.getSingle(0) + block_size - 1) / block_size;
			execKernel((kernel_compute_degree_kcore<T, PeelT, 256, 32>), grid_size, block_size, dev_, false, g,
										kcore_q.device_queue->gdata()[0], _nodeDegree.gdata());

			remaining.setSingle(0, kcore_q.count.getSingle(0), true);
			GPUArray<PeelT> min_degree;
			min_degree.initialize("minimum degree", AllocationTypeEnum::unified, 1, dev_);
			min_degree.setSingle(0, k, true);
			GPUArray<T> node;
			node.initialize("node", AllocationTypeEnum::unified, 1, dev_);

			while (remaining.getSingle(0) > 0)
			{

				cudaDeviceSynchronize();

				const auto block_size = 256;
				degree_q.count.setSingle(0, 0, true);
				currents_q.count.setSingle(0, 0, true);
				execKernel((kernel_fill_candidates_vertex<T, PeelT, 256, 32>), grid_size, block_size, dev_, false, g, _nodeDegree.gdata(),
										kcore_q.device_queue->gdata()[0], degree_q.device_queue->gdata()[0], currents_q.device_queue->gdata()[0]);
				
				// min degree
				{
					void *d_temp_storage = nullptr;
					size_t temp_storage_bytes = 0;
					cub::KeyValuePair<int, PeelT> *d_out;
					cub::KeyValuePair<int, PeelT> *h_out = new cub::KeyValuePair<int, PeelT>();
					CUDA_RUNTIME(cudaMalloc((void**)&d_out, sizeof(cub::KeyValuePair<int, PeelT>)));
					cub::DeviceReduce::ArgMin(d_temp_storage, temp_storage_bytes, degree_q.queue.gdata(), d_out, degree_q.count.getSingle(0));
					CUDA_RUNTIME(cudaMalloc(&d_temp_storage, temp_storage_bytes));
					cub::DeviceReduce::ArgMin(d_temp_storage, temp_storage_bytes, degree_q.queue.gdata(), d_out, degree_q.count.getSingle(0));
					CUDA_RUNTIME(cudaFree(d_temp_storage));
					cudaMemcpy(h_out, d_out, sizeof(cub::KeyValuePair<int, PeelT>), ::cudaMemcpyDeviceToHost);
					auto argmin = h_out->key;
					cudaFree(d_out);
					free(h_out);	
					min_degree.setSingle(0, degree_q.queue.getSingle(argmin), true);
					node.setSingle(0, currents_q.queue.getSingle(argmin), true);
				}

				if (min_degree.getSingle(0) + 1 == remaining.getSingle(0))
				{
					heurCliqueSize.setSingle(0, min_degree.getSingle(0) + 1, true);
					heurCliqueVertices.initialize("Heuristic clique vertices",
						AllocationTypeEnum::gpu, remaining.getSingle(0), dev_);
					CUDA_RUNTIME(cudaMemcpy(heurCliqueVertices.gdata(),
						currents_q.queue.gdata(),
						remaining.getSingle(0) * sizeof(T),
						cudaMemcpyDeviceToDevice));
					remaining.setSingle(0, 0, true);
					break;
				}

				T offset, offset_1;
				cudaMemcpy(&offset, &g.rowPtr[node.getSingle(0)], sizeof(PeelT), ::cudaMemcpyDeviceToHost);
				cudaMemcpy(&offset_1, &g.rowPtr[node.getSingle(0) + 1], sizeof(PeelT), ::cudaMemcpyDeviceToHost);
				auto neigh_grid_size = (offset_1 - offset + block_size - 1) / block_size;
				execKernel((kernel_partition_remove_vertex<T, PeelT>), neigh_grid_size, block_size, dev_, false,
										g,
										kcore_q.device_queue->gdata()[0],
										_nodeDegree.gdata(),
										node.getSingle(0));

				remaining.setSingle(0, remaining.getSingle(0) - 1, true);
				kcore_q.mark.setSingle(node.getSingle(0), false, true);

			}

			min_degree.freeGPU();
			node.freeGPU();
			_nodeDegree.freeGPU();
			currents_q.free();
			kcore_q.free();
			degree_q.free();
			remaining.freeGPU();
		}
		

		void AscendingGpu(int n, GPUArray<T> &identity_arr_asc)
		{
			const size_t block_size = 128;
			T grid_size = (n + block_size - 1) / block_size;
			identity_arr_asc.initialize("Identity Array Asc", gpu, n, dev_);
			execKernel(init_asc, grid_size, block_size, dev_, false, identity_arr_asc.gdata(), n);
		}

	public:
		GPUArray<PeelT> nodeDegree;
		GPUArray<T> nodePriority;
		GPUArray<T> coreNumber;
		GPUArray<int> heurCliqueSize;
		GPUArray<T> heurCliqueVertices;

		SingleGPU_Kcore(int dev) : dev_(dev)
		{
			CUDA_RUNTIME(cudaSetDevice(dev_));
			CUDA_RUNTIME(cudaStreamCreate(&stream_));
			CUDA_RUNTIME(cudaStreamSynchronize(stream_));
		}

		SingleGPU_Kcore() : SingleGPU_Kcore(0) {}

		~SingleGPU_Kcore() 
		{
			coreNumber.freeGPU();
			heurCliqueSize.freeGPU();
			heurCliqueVertices.freeGPU();
			nodePriority.freeGPU();
			nodeDegree.freeGPU();
			if (stream_ != nullptr)
			{
				CUDA_RUNTIME(cudaStreamDestroy(stream_));
				stream_ = nullptr;
			}
		}

		void getNodeDegree(COOCSRGraph_d<T> &g, const size_t nodeOffset = 0, const size_t edgeOffset = 0)
		{
			const int dimBlock = 256;
			nodeDegree.initialize("Node Degree", gpu, g.numNodes, dev_);
			uint dimGridNodes = (g.numNodes + dimBlock - 1) / dimBlock;
			execKernel(getNodeDegree_kernel<T>, dimGridNodes, dimBlock, dev_, false, nodeDegree.gdata(), g);
		}

		void findKcoreIncremental_async(COOCSRGraph_d<T> &g, const size_t nodeOffset = 0, const size_t edgeOffset = 0)
		{
			CUDA_RUNTIME(cudaSetDevice(dev_));
			constexpr int dimBlock = 64; // For edges and nodes

			GPUArray<BCTYPE> processed; // isDeleted

			int level = 0;
			int bucket_level_end_ = level;
			// Lets apply queues and buckets
			graph::GraphQueue<T, bool> bucket_q;
			bucket_q.Create(gpu, g.numNodes, dev_);

			graph::GraphQueue<T, bool> current_q;
			current_q.Create(gpu, g.numNodes, dev_);

			graph::GraphQueue<T, bool> next_q;
			next_q.Create(gpu, g.numNodes, dev_);
			next_q.mark.setAll(false, true);

			GPUArray<T> identity_arr_asc;
			AscendingGpu(g.numNodes, identity_arr_asc);

			nodePriority.initialize("Edge Support", gpu, g.numNodes, dev_);
			nodePriority.setAll(g.numEdges, false);

			coreNumber.initialize("Edge Support", gpu, g.numNodes, dev_);
			coreNumber.setAll(0, true);

			getNodeDegree(g);

			int todo = g.numNodes;
			const auto todo_original = g.numNodes;
			
			T priority = 0;
		
			while (todo > 0)
			{
				CUDA_RUNTIME(cudaGetLastError());
				cudaDeviceSynchronize();

				// 1 bucket fill
				bucket_scan(nodeDegree, todo_original, level, current_q, identity_arr_asc, bucket_q, bucket_level_end_);

				int iterations = 0;
				while (current_q.count.getSingle(0) > 0)
				{
					
					next_q.count.setSingle(0, 0, true);
					todo -= current_q.count.getSingle(0);

					if (level == 0)
					{
						auto block_size = 256;
						auto grid_size = (current_q.count.getSingle(0) + block_size - 1) / block_size;
						execKernel((update_priority<T, PeelT>), grid_size, block_size, dev_, false, current_q.device_queue->gdata()[0], priority, nodePriority.gdata(), coreNumber.gdata());
					}
					else
					{
						auto block_size = 256;
						auto grid_warp_size = (32 * current_q.count.getSingle(0) + block_size - 1) / block_size;
						auto grid_block_size = current_q.count.getSingle(0);
						
						execKernel((kernel_partition_level_next<T, PeelT, 256, 32>), grid_warp_size, block_size, dev_, false,
											 g,
											 level, processed.gdata(), nodeDegree.gdata(),
											 current_q.device_queue->gdata()[0],
											 next_q.device_queue->gdata()[0],
											 bucket_q.device_queue->gdata()[0],
											 bucket_level_end_, priority, nodePriority.gdata(), coreNumber.gdata());
					}

					swap(current_q, next_q);
					iterations++;
					priority++;

        }
        
				level++;
			}



			processed.freeGPU();
			current_q.free();
			next_q.free();
			bucket_q.free();
			identity_arr_asc.freeGPU();
			nodeDegree.freeGPU();

			k = level;

			printf("Max Core = %d\n", k - 1);

			find_heur_clique(g);

		}

		void sync() { CUDA_RUNTIME(cudaStreamSynchronize(stream_)); }
		uint count() const { return k - 1; }
		int device() const { return dev_; }
		cudaStream_t stream() const { return stream_; }
	};
} // namespace graph
