#pragma once
#include "../include/defs.h"
#include "../include/queue.cuh"
#include "../include/utils.cuh"
#include "mcp_utils.cuh"
#include "parameter.cuh"
		

// /////////////////////////////////////////////////////////////////////////////////
// First level independent subtree with San Segundo's coloring Algorithm Hybrid Warp
// /////////////////////////////////////////////////////////////////////////////////

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__launch_bounds__(BLOCK_DIM_X, 2048 / BLOCK_DIM_X)
__global__ void mcp_kernel_l1_wl_donor_w_psanse(
	mcp::GLOBAL_HANDLE<T> gh,
	queue_callee(queue, tickets, head, tail))
{
	mcp::LOCAL_HANDLE<T> lh;
  __shared__ mcp::WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> __warp__(wsh);
	__shared__ mcp::SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> sh;
	__shared__ T cut_by_kcore_l1;
	__shared__ T cut_by_color;
	__shared__ T cut_by_color_l1;
	__shared__ uint32_t subgraph_edges;
	__shared__ float avg_subgraph_density;
	__shared__ float max_subgraph_density;
	__shared__ uint32_t avg_subgraph_width;
	__shared__ uint32_t max_subgraph_width;
	__shared__ uint32_t number_of_subgraph;
	__shared__ volatile T second_level_work_stealing;
	__shared__ volatile unsigned long long branches;
	__shared__ T __warp__(work_stealing);
	__shared__ T max_clique_size, core_i;

	lh.numPartitions = BLOCK_DIM_X / CPARTSIZE; // Number of warp scheduler in block
	lh.gwx = (blockDim.x * blockIdx.x + threadIdx.x) / CPARTSIZE;
	lh.wx = threadIdx.x / CPARTSIZE; // Warp index
	lh.lx = threadIdx.x % CPARTSIZE; // Lane index (index inside the warp)
	lh.partMask = (CPARTSIZE == 32 ? 0xFFFFFFFF : (1 << CPARTSIZE) - 1) 
					<< ((lh.wx % (32 / CPARTSIZE)) * CPARTSIZE);

	if (threadIdx.x == 0)
	{
		sh.root_sm_block_id = sh.sm_block_id = blockIdx.x;
		sh.state = 0;
		cut_by_color_l1 = 0;
		cut_by_kcore_l1 = 0;
		cut_by_color = 0;
		avg_subgraph_density = 0;
		max_subgraph_density = 0;
		avg_subgraph_width = 0;
		max_subgraph_width = 0;
		number_of_subgraph = 0;
		branches = 0;

	}

	if (laneIdx == 0) {
		wsh[warpIdx].root_sm_warp_id = wsh[warpIdx].sm_warp_id = lh.gwx;
		wsh[warpIdx].root_sm_block_id = blockIdx.x;
		sh.queue[warpIdx] = 0;
		sh.tickets[warpIdx].store(0, cuda::memory_order_relaxed);
	}
	__syncthreads();

	while (sh.state != 100)
	{
		// If First Level or begin
		if (sh.state == 0)
		{
			__syncthreads();
			if (threadIdx.x == 0) {
				// Each block gets the vertex
				//printf("block %u extracts a candidate level 1\n", blockIdx.x);
				sh.i = atomicAdd((T *)gh.work_stealing, gh.stride);
			}
			__syncthreads();

			// If work finished go in the waiting queue
			if (sh.i >= gh.iteration_limit) // L1 ? #Nodes : #Edges
			{
				__syncthreads();
				if (laneIdx == 0)
				{
					//printf("First level terminated\n");
					sh.state = 1; // finish
					wsh[warpIdx].state = 1;
					queue_enqueue(queue, tickets, head, tail, WARPS, wsh[warpIdx].sm_warp_id);
				}
				__syncthreads();
				continue;
			}
			__syncthreads();
			fetch_both(core_i, gh.core[sh.i], max_clique_size, (*gh.Cmax_size));
			__syncthreads();
			if (core_i < max_clique_size)
			{
				__syncthreads();
				continue;
			}
			mcp::setup_stack_first_level_psanse_(gh, sh);

			if (sh.usrcLen <= max_clique_size - 1)
			{
				__syncthreads();
				continue;
			}
			__syncthreads();

			mcp::encode_clear(lh, sh, sh.usrcLen);
		
			// Compute the induced subgraph for kcore first level
			for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
			{
				auto &g = gh.gsplit;
				mcp::graph::warp_sorted_count_and_encode_full<T, CPARTSIZE>(
					&g.colInd[sh.usrcStart], sh.usrcLen,
					&g.colInd[g.rowPtr[g.colInd[sh.usrcStart + j]]], 
					g.splitPtr[g.colInd[sh.usrcStart + j]] 
					- g.rowPtr[g.colInd[sh.usrcStart + j]],
					j, sh.num_divs_local, sh.encode);
			}

			__syncthreads();

			// Run greedy coloring
			if (mcp::compute_upperbound_chromatic_number_psanse(lh, sh, max_clique_size - 1, sh.num_divs_local) <= max_clique_size - 1)
			{
				if (gh.verbose && threadIdx.x == 0) cut_by_color_l1++;
				__syncthreads();
				continue;
			}
			__syncthreads();

			// Compute k-core reduction of the first level and the ordering
			mcp::compute_kcore_first_level(lh, sh, gh, sh.num_divs_local, sh.encode, max_clique_size);

			if (sh.usrcLen <= max_clique_size - 1 || sh.max_core_l1 + 1 < max_clique_size) {
				if (gh.verbose && threadIdx.x == 0)	cut_by_kcore_l1++;
				__syncthreads();
				continue;
			}

			mcp::reduce_stack_first_level(gh, sh);
			mcp::encode_clear(lh, sh, sh.usrcLen);
			mcp::reverse_degeneracy_ordering_first_level(lh, sh, gh);

			// Compute the induced subgraph based on degeneracy ordered first level
			// Warp-parallel
			fetch(subgraph_edges, 0);

			__syncthreads();

			if (gh.verbose)
			{
				for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
				{
					auto &g = gh.gsplit;
					mcp::graph::warp_sorted_count_and_encode_full_stats<T, CPARTSIZE>(
						sh.ordering, sh.usrcLen,
						&g.colInd[g.rowPtr[sh.ordering[j]]], 
						g.splitPtr[sh.ordering[j]] 
						- g.rowPtr[sh.ordering[j]],
						j, sh.num_divs_local, sh.encode, subgraph_edges);
				}
			}
			else
			{
				for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
				{
					auto &g = gh.gsplit;
					mcp::graph::warp_sorted_count_and_encode_full<T, CPARTSIZE>(
						sh.ordering, sh.usrcLen,
						&g.colInd[g.rowPtr[sh.ordering[j]]], 
						g.splitPtr[sh.ordering[j]] 
						- g.rowPtr[sh.ordering[j]],
						j, sh.num_divs_local, sh.encode);
				}
			}
			
			__syncthreads();

			if (gh.verbose && threadIdx.x == 0)
			{
				float current_density = static_cast<float>(subgraph_edges) / static_cast<float>(sh.usrcLen * (sh.usrcLen - 1));
				max_subgraph_density = max(max_subgraph_density, current_density);
				max_subgraph_width = max(max_subgraph_width, sh.usrcLen);
				avg_subgraph_width += sh.usrcLen;
				avg_subgraph_density += current_density;
				number_of_subgraph++;
				//atomicAdd((unsigned long long*)&branches, 1);
			}

			__syncthreads();

			// Determine intersection and put them into sh.pl
			mcp::compute_P_intersection_to_first_level(sh, sh.usrcLen, sh.num_divs_local, sh.to_bl);
			__syncthreads(); fetch(max_clique_size, (*gh.Cmax_size)); __syncthreads();
			mcp::compute_branches_fast_second_level(lh, sh, int(max_clique_size) - 1, sh.num_divs_local);

			// If B = 0
			if (mcp::b_maximality(gh, sh, lh)) { if (gh.verbose && threadIdx.x == 0) cut_by_color++; __syncthreads(); continue; }

			mcp::compute_branching_aux_set_second_level(sh, sh.to_col);

			// setup stack for warps
			mcp::setup_warp_stack_second_level(gh, lh, sh, wsh[warpIdx]);

			fetch(second_level_work_stealing, 0);
			if (laneIdx == 0) reset_warp_shared_queue(sh.queue, sh.tickets, sh.head, sh.tail);
			__syncthreads();

		}
		else if (sh.state == 1 && wsh[warpIdx].state == 1) // Wait in the queue
		{
			__syncwarp();
			if (laneIdx == 0)
			{
				//printf("warp %u waiting\n", wsh[warpIdx].sm_warp_id);
				//printf("Waiting warps: %u / %u\n", tail->load(cuda::memory_order_relaxed) - head->load(cuda::memory_order_relaxed), WARPS);
				mcp::wait_for_donor_warp_(gh.work_ready[wsh[warpIdx].sm_warp_id], sh.state, wsh[warpIdx].state, 
							queue_caller(queue, tickets, head, tail));
			}
			__syncwarp();
			continue;
		}
		else if (sh.state == 1 && wsh[warpIdx].state == 2) // Get work from queue at first level
		{
			__syncwarp();
			mcp::setup_warp_stack_donor_psanse_(gh, lh, wsh[warpIdx]);
		}

		while (wsh[warpIdx].state != 100)
		{
			__syncwarp();
			if (sh.state == 0 && wsh[warpIdx].state == 0)
			{
				// Dequeue a vertex from P
				__syncwarp();
				if (laneIdx == 0)	wsh[warpIdx].i = atomicAdd((T*)&second_level_work_stealing, 1);
				__syncwarp();

				if (wsh[warpIdx].i >= sh.usrcLen)
				{
					__syncwarp();
					if (laneIdx == 0)
					{	
						wsh[warpIdx].state = 1;
						shared_queue_enqueue(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh[warpIdx].sm_warp_id);
						//printf("warp: %u end\n", warpIdx);
					}
					__syncwarp();
					continue;
				}
				__syncwarp();

				const T li = wsh[warpIdx].i >> 5;
				const T ri = 1 << (wsh[warpIdx].i & 0x1F);

				// If is not branching index
				__syncwarp();
				if ((sh.to_bl[li] & ri) == 0)
				{
					__syncwarp();
					continue;
				}
				__syncwarp();

				mcp::compute_warp_P_intersection_second_level(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local, sh.to_bl, sh.to_col, wsh[warpIdx].pl);

				if (laneIdx == 0)
				{
					wsh[warpIdx].colored[0] = false;
					wsh[warpIdx].l = wsh[warpIdx].base_l = 3;
					wsh[warpIdx].level_pointer_index[warp_current_level] = 0;
				}

				__syncwarp();
			}else
			if (sh.state == 0 && wsh[warpIdx].state == 1)
			{
				// wait for donor in the local queue
				__syncwarp();
				if (laneIdx == 0)
				{
					//if(local_tail[blockIdx.x].load(cuda::memory_order_relaxed) - local_head[blockIdx.x].load(cuda::memory_order_relaxed) == NUMPART) printf("block %u\n", blockIdx.x);
					mcp::shared_wait_for_donor_warp_local(gh.work_ready[wsh[warpIdx].sm_warp_id], wsh[warpIdx].state, sh);
				}
				__syncwarp();
				continue;
			}
			else if (sh.state == 0 && wsh[warpIdx].state == 2)
			{
				// setup donor stack
				__syncwarp();
				mcp::setup_warp_stack_donor_psanse_(gh, lh, wsh[warpIdx]);
			}

			__syncwarp();

			while (wsh[warpIdx].l >= wsh[warpIdx].base_l)
			{

				if (!wsh[warpIdx].colored[warp_current_level]) 
				{				
					// If P = 0
					if (mcp::p_warp_maximality_(gh, lh, wsh[warpIdx])) continue;
					if (gh.verbose && laneIdx == 0) atomicAdd((unsigned long long *)&branches, 1); __syncwarp();
					mcp::compute_warp_branches_fast_(lh, wsh[warpIdx], int((*gh.Cmax_size)) - int(wsh[warpIdx].l - 1), wsh[warpIdx].num_divs_local,
						warp_current_level, wsh[warpIdx].pl + warp_current_level * wsh[warpIdx].num_divs_local, 
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);

					// If B = 0
					if (mcp::b_warp_maximality_(gh, wsh[warpIdx], lh)) { if (gh.verbose && laneIdx == 0) atomicAdd(&cut_by_color, 1); __syncwarp(); continue; }
					mcp::compute_warp_branching_aux_set_(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local, wsh[warpIdx].pl + warp_current_level * wsh[warpIdx].num_divs_local, 
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local, wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					fetch_warp(work_stealing, (*gh.work_stealing), warpIdx); __syncwarp();
				}

				// Donates in the local queue
				if (sh.state == 0 && second_level_work_stealing >= sh.usrcLen) 
				{
					mcp::prepare_warp_fork_(lh, wsh[warpIdx]);
					mcp::get_warp_candidates_for_next_level_local<true>(lh, wsh[warpIdx], warp_current_level,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					mcp::try_dequeue_warp_shared(lh, gh, wsh[warpIdx], sh);
					
					if (wsh[warpIdx].fork) mcp::do_warp_fork_shared(lh, gh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local,
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local, sh);
				}

				// Donates in the global queue
				if (work_stealing[warpIdx] >= gh.iteration_limit)
				{
					mcp::prepare_warp_fork_(lh, wsh[warpIdx]);
					mcp::get_warp_candidates_for_next_level_<true>(lh, wsh[warpIdx], warp_current_level,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					mcp::try_dequeue_warp_global(lh, gh, wsh[warpIdx], queue_caller(queue, tickets, head, tail));

					if (wsh[warpIdx].fork) mcp::do_warp_fork_global(lh, gh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local,
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local,
							queue_caller(queue, tickets, head, tail));

				}

				// If B visited
				if (!mcp::get_next_warp_branching_index_(gh, lh, wsh[warpIdx],
					wsh[warpIdx].level_pointer_index[warp_current_level], 
					wsh[warpIdx].usrcLen, wsh[warpIdx].bl + wsh[warpIdx].num_divs_local * warp_current_level)) continue;	

				mcp::next_warp_pointer(lh, wsh[warpIdx].level_pointer_index[warp_current_level]);
				mcp::compute_warp_P_intersection_for_next_level_(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
					wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local, wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local,
					wsh[warpIdx].pl + warp_next_level * wsh[warpIdx].num_divs_local);
				
				mcp::go_to_next_level_warp(lh, wsh[warpIdx].l, wsh[warpIdx].level_pointer_index[warp_next_level], wsh[warpIdx].colored[warp_next_level]);

			}
		
			__syncwarp();
			if (laneIdx == 0 && sh.state == 0 && wsh[warpIdx].state == 2)
			{
				// queue enqueue local
				wsh[warpIdx].state = 1;
				shared_queue_enqueue(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh[warpIdx].sm_warp_id);

			}else
			if (laneIdx == 0 && sh.state == 1 && wsh[warpIdx].state == 2)
			{
				// go out
				wsh[warpIdx].state = 100;
			}
			__syncwarp();
		}

		__syncwarp();
		if (laneIdx == 0 && sh.state == 1 && wsh[warpIdx].state == 100)
		{
			// queue enqueue global
			wsh[warpIdx].state = 1;
			queue_enqueue(queue, tickets, head, tail, WARPS, wsh[warpIdx].sm_warp_id);
		}
		__syncwarp();

	}

		
	// Collect statistics	
	if (gh.verbose && threadIdx.x == 0)
	{
		atomicAdd((T*)gh.cut_by_kcore_l1, cut_by_kcore_l1);
		atomicAdd((T*)gh.cut_by_color_l1, cut_by_color_l1);
		atomicAdd((T*)gh.cut_by_color, cut_by_color);
		atomicAdd((uint32_t*)gh.total_subgraph, number_of_subgraph);
		atomicAdd((float*)gh.avg_subgraph_density, avg_subgraph_density);
		atomicMax((float*)gh.max_subgraph_density, max_subgraph_density);
		atomicAdd((uint32_t*)gh.avg_subgraph_width, avg_subgraph_width);
		atomicMax((uint32_t*)gh.max_subgraph_width, max_subgraph_width);
		atomicAdd((unsigned long long*)gh.branches, branches);
	}

}


// /////////////////////////////////////////////////////////////////////////////////
// First level independent subtree with San Segundo's coloring Algorithm Hybrid Warp
// /////////////////////////////////////////////////////////////////////////////////

template <typename T, uint BLOCK_DIM_X, uint CPARTSIZE>
__launch_bounds__(BLOCK_DIM_X, 2048 / BLOCK_DIM_X)
__global__ void mcp_kernel_l1_wl_donor_w_reduce(
	mcp::GLOBAL_HANDLE<T> gh,
	queue_callee(queue, tickets, head, tail))
{
	mcp::LOCAL_HANDLE<T> lh;
  __shared__ mcp::WARP_SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> __warp__(wsh);
	__shared__ mcp::SHARED_HANDLE<T, BLOCK_DIM_X, CPARTSIZE> sh;
	__shared__ T cut_by_kcore_l1;
	__shared__ T cut_by_color;
	__shared__ T cut_by_color_l1;
	__shared__ uint32_t subgraph_edges;
	__shared__ float avg_subgraph_density;
	__shared__ float max_subgraph_density;
	__shared__ uint32_t avg_subgraph_width;
	__shared__ uint32_t max_subgraph_width;
	__shared__ uint32_t number_of_subgraph;
	__shared__ volatile T second_level_work_stealing;
	__shared__ volatile unsigned long long branches;
	__shared__ T __warp__(work_stealing), max_clique_size, core_i;

	lh.numPartitions = BLOCK_DIM_X / CPARTSIZE; // Number of warp scheduler in block
	lh.gwx = (blockDim.x * blockIdx.x + threadIdx.x) / CPARTSIZE;
	lh.wx = threadIdx.x / CPARTSIZE; // Warp index
	lh.lx = threadIdx.x % CPARTSIZE; // Lane index (index inside the warp)
	lh.partMask = (CPARTSIZE == 32 ? 0xFFFFFFFF : (1 << CPARTSIZE) - 1) 
					<< ((lh.wx % (32 / CPARTSIZE)) * CPARTSIZE);

	if (threadIdx.x == 0)
	{
		sh.root_sm_block_id = sh.sm_block_id = blockIdx.x;
		sh.state = 0;
		cut_by_color_l1 = 0;
		cut_by_kcore_l1 = 0;
		cut_by_color = 0;
		avg_subgraph_density = 0;
		max_subgraph_density = 0;
		avg_subgraph_width = 0;
		max_subgraph_width = 0;
		number_of_subgraph = 0;
		branches = 0;
	}

	if (laneIdx == 0) {
		wsh[warpIdx].root_sm_warp_id = wsh[warpIdx].sm_warp_id = lh.gwx;
		wsh[warpIdx].root_sm_block_id = blockIdx.x;
		sh.queue[warpIdx] = 0;
		sh.tickets[warpIdx].store(0, cuda::memory_order_relaxed);
	}
	__syncthreads();

	while (sh.state != 100)
	{
		// If First Level or begin
		if (sh.state == 0)
		{
			__syncthreads();
			if (threadIdx.x == 0) {
				// Each block gets the vertex
				//printf("block %u extracts a candidate level 1\n", blockIdx.x);
				sh.i = atomicAdd((T *)gh.work_stealing, gh.stride);
			}
			__syncthreads();

			// If work finished go in the waiting queue
			if (sh.i >= gh.iteration_limit) // L1 ? #Nodes : #Edges
			{
				__syncthreads();
				if (laneIdx == 0)
				{
					//printf("First level terminated\n");
					sh.state = 1; // finish
					wsh[warpIdx].state = 1;
					queue_enqueue(queue, tickets, head, tail, WARPS, wsh[warpIdx].sm_warp_id);
				}
				__syncthreads();
				continue;
			}

			fetch_both(core_i, gh.core[sh.i], max_clique_size, (*gh.Cmax_size));
			__syncthreads();
			if (core_i < max_clique_size)
			{
				__syncthreads();
				continue;
			}
			__syncthreads();

			mcp::setup_stack_first_level_psanse_(gh, sh);

			if (sh.usrcLen <= max_clique_size - 1)
			{
				__syncthreads();
				continue;
			}
			__syncthreads();

			mcp::encode_clear(lh, sh, sh.usrcLen);
		
			// Compute the induced subgraph for kcore first level
			for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
			{
				auto &g = gh.gsplit;
				mcp::graph::warp_sorted_count_and_encode_full<T, CPARTSIZE>(
					&g.colInd[sh.usrcStart], sh.usrcLen,
					&g.colInd[g.rowPtr[g.colInd[sh.usrcStart + j]]], 
					g.splitPtr[g.colInd[sh.usrcStart + j]] 
					- g.rowPtr[g.colInd[sh.usrcStart + j]],
					j, sh.num_divs_local, sh.encode);
			}

			__syncthreads();

			// Run greedy coloring
			if (mcp::compute_upperbound_chromatic_number_psanse(lh, sh, max_clique_size - 1, sh.num_divs_local) <= max_clique_size - 1)
			{
				if (gh.verbose && threadIdx.x == 0) cut_by_color_l1++;
				__syncthreads();
				continue;
			}

			// Compute k-core reduction of the first level and the ordering
			mcp::compute_kcore_first_level(lh, sh, gh, sh.num_divs_local, sh.encode, max_clique_size);

			if (sh.usrcLen <= max_clique_size - 1 || sh.max_core_l1 + 1 < max_clique_size) {
				if (gh.verbose && threadIdx.x == 0)	cut_by_kcore_l1++;
				__syncthreads();
				continue;
			}

			mcp::reduce_stack_first_level(gh, sh);
			mcp::encode_clear(lh, sh, sh.usrcLen);
			mcp::reverse_degeneracy_ordering_first_level(lh, sh, gh);

			// Compute the induced subgraph based on degeneracy ordered first level
			// Warp-parallel
			fetch(subgraph_edges, 0);

			__syncthreads();

			if (gh.verbose)
			{
				for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
				{
					auto &g = gh.gsplit;
					mcp::graph::warp_sorted_count_and_encode_full_stats<T, CPARTSIZE>(
						sh.ordering, sh.usrcLen,
						&g.colInd[g.rowPtr[sh.ordering[j]]], 
						g.splitPtr[sh.ordering[j]] 
						- g.rowPtr[sh.ordering[j]],
						j, sh.num_divs_local, sh.encode, subgraph_edges);
				}
			}
			else
			{
				for (T j = lh.wx; j < sh.usrcLen; j += lh.numPartitions)
				{
					auto &g = gh.gsplit;
					mcp::graph::warp_sorted_count_and_encode_full<T, CPARTSIZE>(
						sh.ordering, sh.usrcLen,
						&g.colInd[g.rowPtr[sh.ordering[j]]], 
						g.splitPtr[sh.ordering[j]] 
						- g.rowPtr[sh.ordering[j]],
						j, sh.num_divs_local, sh.encode);
				}
			}
			
			__syncthreads();

			if (gh.verbose && threadIdx.x == 0)
			{
				float current_density = static_cast<float>(subgraph_edges) / static_cast<float>(sh.usrcLen * (sh.usrcLen - 1));
				max_subgraph_density = max(max_subgraph_density, current_density);
				max_subgraph_width = max(max_subgraph_width, sh.usrcLen);
				avg_subgraph_width += sh.usrcLen;
				avg_subgraph_density += current_density;
				number_of_subgraph++;
				//atomicAdd((unsigned long long*)&branches, 1);
			}

			__syncthreads();

			// Determine intersection and put them into sh.pl
			mcp::compute_P_intersection_to_first_level(sh, sh.usrcLen, sh.num_divs_local, sh.to_bl);

			if (mcp::reduce_second_level(gh, lh, sh, sh.num_divs_local, 0)) continue;

			mcp::compute_branches_fast_second_level(lh, sh, int((*gh.Cmax_size)) - 1, sh.num_divs_local);

			// If B = 0
			if (mcp::b_maximality(gh, sh, lh)) { if (gh.verbose && threadIdx.x == 0) cut_by_color++; __syncthreads(); continue; }

			mcp::compute_branching_aux_set_second_level(sh, sh.to_col);

			// setup stack for warps
			mcp::setup_warp_stack_second_level(gh, lh, sh, wsh[warpIdx]);

			if (laneIdx == 0) 
			{
				second_level_work_stealing = 0;
				reset_warp_shared_queue(sh.queue, sh.tickets, sh.head, sh.tail);
			}
			__syncthreads();

		}
		else if (sh.state == 1 && wsh[warpIdx].state == 1) // Wait in the queue
		{
			__syncwarp();
			if (laneIdx == 0)
			{
				//printf("warp %u waiting\n", wsh[warpIdx].sm_warp_id);
				//printf("Waiting warps: %u / %u\n", tail->load(cuda::memory_order_relaxed) - head->load(cuda::memory_order_relaxed), WARPS);
				mcp::wait_for_donor_warp_(gh.work_ready[wsh[warpIdx].sm_warp_id], sh.state, wsh[warpIdx].state, 
							queue_caller(queue, tickets, head, tail));
			}
			__syncwarp();
			continue;
		}
		else if (sh.state == 1 && wsh[warpIdx].state == 2) // Get work from queue at first level
		{
			__syncwarp();
			mcp::setup_warp_stack_donor_psanse_(gh, lh, wsh[warpIdx]);
		}

		while (wsh[warpIdx].state != 100)
		{
			__syncwarp();
			if (sh.state == 0 && wsh[warpIdx].state == 0)
			{
				// Dequeue a vertex from P
				if (laneIdx == 0)	wsh[warpIdx].i = atomicAdd((T*)&second_level_work_stealing, 1);
				__syncwarp();

				if (wsh[warpIdx].i >= sh.usrcLen)
				{
					__syncwarp();
					if (laneIdx == 0)
					{	
						wsh[warpIdx].state = 1;
						shared_queue_enqueue(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh[warpIdx].sm_warp_id);
						//printf("warp: %u end\n", warpIdx);
					}
					__syncwarp();
					continue;
				}

				const T li = wsh[warpIdx].i >> 5;
				const T ri = 1 << (wsh[warpIdx].i & 0x1F);

				// If is not branching index
				if ((sh.to_bl[li] & ri) == 0)
				{
					__syncwarp();
					continue;
				}

				mcp::compute_warp_P_intersection_second_level(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local, sh.to_bl, sh.to_col, wsh[warpIdx].pl);

				if (laneIdx == 0)
				{
					wsh[warpIdx].colored[0] = false;
					wsh[warpIdx].l = wsh[warpIdx].base_l = 3;
					wsh[warpIdx].level_pointer_index[warp_current_level] = 0;
				}

				__syncwarp();
			}else
			if (sh.state == 0 && wsh[warpIdx].state == 1)
			{
				// wait for donor in the local queue
				__syncwarp();
				if (laneIdx == 0)
				{
					//if(local_tail[blockIdx.x].load(cuda::memory_order_relaxed) - local_head[blockIdx.x].load(cuda::memory_order_relaxed) == NUMPART) printf("block %u\n", blockIdx.x);
					mcp::shared_wait_for_donor_warp_local(gh.work_ready[wsh[warpIdx].sm_warp_id], wsh[warpIdx].state, sh);
				}
				__syncwarp();
				continue;
			}
			else if (sh.state == 0 && wsh[warpIdx].state == 2)
			{
				// setup donor stack
				__syncwarp();
				mcp::setup_warp_stack_donor_psanse_(gh, lh, wsh[warpIdx]);
			}

			__syncwarp();

			while (wsh[warpIdx].l >= wsh[warpIdx].base_l)
			{
				
				
				if (!wsh[warpIdx].colored[warp_current_level]) 
				{				
					// If P = 0
					if (mcp::p_warp_maximality_(gh, lh, wsh[warpIdx])) continue;
					if (mcp::warp_reduce(gh, lh, wsh[warpIdx], wsh[warpIdx].num_divs_local, wsh[warpIdx].l - 2, wsh[warpIdx].pl + warp_current_level * wsh[warpIdx].num_divs_local)) {continue;}
					if (gh.verbose && laneIdx == 0) atomicAdd((unsigned long long *)&branches, 1);
					mcp::compute_warp_branches_fast_(lh, wsh[warpIdx], int((*gh.Cmax_size)) - int(wsh[warpIdx].l - 1), wsh[warpIdx].num_divs_local,
						warp_current_level, wsh[warpIdx].pl + warp_current_level * wsh[warpIdx].num_divs_local, 
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);

					// If B = 0
					if (mcp::b_warp_maximality_(gh, wsh[warpIdx], lh)) { if (laneIdx == 0 && gh.verbose) atomicAdd(&cut_by_color, 1); __syncwarp(); continue; }
					mcp::compute_warp_branching_aux_set_(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local, wsh[warpIdx].pl + warp_current_level * wsh[warpIdx].num_divs_local, 
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local, wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					fetch_warp(work_stealing, (*gh.work_stealing), warpIdx); __syncwarp();
				}
				
				// Donates in the local queue
				if (sh.state == 0 && second_level_work_stealing >= sh.usrcLen) 
				{
					mcp::prepare_warp_fork_(lh, wsh[warpIdx]);
					mcp::get_warp_candidates_for_next_level_local<true>(lh, wsh[warpIdx], warp_current_level,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					mcp::try_dequeue_warp_shared(lh, gh, wsh[warpIdx], sh);
					
					if (wsh[warpIdx].fork) mcp::do_warp_fork_shared(lh, gh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local,
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local, sh);
				}

				// Donates in the global queue
				if (work_stealing[warpIdx] >= gh.iteration_limit)
				{
					mcp::prepare_warp_fork_(lh, wsh[warpIdx]);
					mcp::get_warp_candidates_for_next_level_<true>(lh, wsh[warpIdx], warp_current_level,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local);
					mcp::try_dequeue_warp_global(lh, gh, wsh[warpIdx], queue_caller(queue, tickets, head, tail));

					if (wsh[warpIdx].fork) mcp::do_warp_fork_global(lh, gh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
						wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local,
						wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local,
							queue_caller(queue, tickets, head, tail));

				}
				
				// If B visited
				if (!mcp::get_next_warp_branching_index_(gh, lh, wsh[warpIdx],
					wsh[warpIdx].level_pointer_index[warp_current_level], 
					wsh[warpIdx].usrcLen, wsh[warpIdx].bl + wsh[warpIdx].num_divs_local * warp_current_level)) continue;	

				//if (laneIdx == 0) printf("l1: %u, i:%u, l: %u, c: %u, w: %u\n", sh.i, wsh[warpIdx].i, wsh[warpIdx].l, lh.newIndex, lh.gwx);

				mcp::next_warp_pointer(lh, wsh[warpIdx].level_pointer_index[warp_current_level]);
				mcp::compute_warp_P_intersection_for_next_level_(lh, wsh[warpIdx], wsh[warpIdx].num_divs_local,
					wsh[warpIdx].bl + warp_current_level * wsh[warpIdx].num_divs_local, wsh[warpIdx].al + warp_current_level * wsh[warpIdx].num_divs_local,
					wsh[warpIdx].pl + warp_next_level * wsh[warpIdx].num_divs_local);
				
				mcp::go_to_next_level_warp(lh, wsh[warpIdx].l, wsh[warpIdx].level_pointer_index[warp_next_level], wsh[warpIdx].colored[warp_next_level]);
			}
		
			__syncwarp();
			if (laneIdx == 0 && sh.state == 0 && wsh[warpIdx].state == 2)
			{
				// queue enqueue local
				wsh[warpIdx].state = 1;
				shared_queue_enqueue(sh.queue, sh.tickets, sh.head, sh.tail, NUMPART, wsh[warpIdx].sm_warp_id);

			}else
			if (laneIdx == 0 && sh.state == 1 && wsh[warpIdx].state == 2)
			{
				// go out
				wsh[warpIdx].state = 100;
			}
			__syncwarp();
		}

		__syncwarp();
		if (laneIdx == 0 && sh.state == 1 && wsh[warpIdx].state == 100)
		{
			// queue enqueue global
			wsh[warpIdx].state = 1;
			queue_enqueue(queue, tickets, head, tail, WARPS, wsh[warpIdx].sm_warp_id);
		}
		__syncwarp();

	}
		
	// Collect statistics	
	if (gh.verbose && threadIdx.x == 0)
	{
		atomicAdd((T*)gh.cut_by_kcore_l1, cut_by_kcore_l1);
		atomicAdd((T*)gh.cut_by_color_l1, cut_by_color_l1);
		atomicAdd((T*)gh.cut_by_color, cut_by_color);
		atomicAdd((uint32_t*)gh.total_subgraph, number_of_subgraph);
		atomicAdd((float*)gh.avg_subgraph_density, avg_subgraph_density);
		atomicMax((float*)gh.max_subgraph_density, max_subgraph_density);
		atomicAdd((uint32_t*)gh.avg_subgraph_width, avg_subgraph_width);
		atomicMax((uint32_t*)gh.max_subgraph_width, max_subgraph_width);
		atomicAdd((unsigned long long*)gh.branches, branches);
	}

}
