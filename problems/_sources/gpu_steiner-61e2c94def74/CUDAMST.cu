/***********************************************************************************
Implementing Minimum Spanning Tree on CUDA using Atomic Functions. Part of 
implementation done for the paper:

"Large Graph Algorithms for Massively Multithreaded Architectures"
Pawan Harish, Vibhav Vineet and P.J.Narayanan.
Technical Report IIIT/TR/2009/74, 
International Institute of Information Technology-Hyderabad

Copyright (c) 2009 International Institute of Information Technology - Hyderabad. 
All rights reserved.
  
Permission to use, copy, modify and distribute this software and its documentation for 
educational purpose is hereby granted without fee, provided that the above copyright 
notice and this permission notice appear in all copies of this software and that you do 
not sell the software.
  
THE SOFTWARE IS PROVIDED "AS IS" AND WITHOUT WARRANTY OF ANY KIND,EXPRESS, IMPLIED OR 
OTHERWISE.

Created by Pawan Harish and Vibhav Vineet
************************************************************************************/



#include "CUDAMST.h"

void hostMemAllocationNodes()
{
	sameindex = (int*) malloc(sizeof(int)*no_of_nodes);
	falseval = (bool*) malloc(sizeof(bool)*no_of_nodes);
	trueval = (bool*) malloc(sizeof(bool)*no_of_nodes);
	infinity = (int*) malloc(sizeof(int)*no_of_nodes);
	zero = (int*) malloc(sizeof(int)*no_of_nodes);
	h_maxid_maxdegree = (int*) malloc(sizeof(int)*no_of_nodes);

	h_graph_nodes = (Node*) malloc(sizeof(Node)*no_of_nodes);
	
}



void hostMemAllocationEdges()
{
	h_graph_edges = (int*) malloc(sizeof(int)*edge_list_size);
	h_graph_weights = (int*) malloc(sizeof(int)*edge_list_size);
	h_graph_MST_edges = (bool*) malloc(sizeof(bool)*edge_list_size);

}

void deviceMemAllocateNodes()
{
	 cudaMalloc( (void**) &d_graph_nodes, sizeof(Node)*no_of_nodes)  ;
	 cudaMalloc( (void**) &d_global_colors, sizeof(int)*no_of_nodes)  ;
	 cudaMalloc( (void**) &d_graph_colorindex, sizeof(int)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_active_colors, sizeof(bool)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_active_vertices, sizeof(bool)*no_of_nodes );
	 cudaMalloc( (void**) &d_updating_global_colors, sizeof(int)*no_of_nodes );

	 cudaMalloc( (void**) &d_updating_degree, sizeof(unsigned int)*no_of_nodes );
	 cudaMalloc( (void**) &d_prev_colors, sizeof(int)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_prev_colorindex, sizeof(int)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_cycle_edge, sizeof(int)*no_of_nodes) ;
	
	 cudaMalloc( (void**) &d_min_edge_weight, sizeof(int)*no_of_nodes) ;
         cudaMalloc( (void**) &d_min_edge_index, sizeof(int)*no_of_nodes) ;
         cudaMalloc( (void**) &d_global_min_edge_weight, sizeof(int)*no_of_nodes) ;
         cudaMalloc( (void**) &d_global_min_edge_index, sizeof(int)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_global_min_c2, sizeof(int)*no_of_nodes) ;
	 cudaMalloc( (void**) &d_degree, sizeof(unsigned int)*no_of_nodes) ;

	 cudaMalloc( (void**) &d_over, sizeof(bool));

	 cudaMalloc( (void**) &d_done, sizeof(bool));

	 cudaMalloc( (void**) &d_removing, sizeof(bool));



}

void deviceMemCopy()
{


	 cudaMemcpy( d_graph_nodes, h_graph_nodes, sizeof(Node)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_global_colors, sameindex, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_graph_colorindex, sameindex, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_active_colors, falseval, sizeof(bool)*no_of_nodes, cudaMemcpyHostToDevice) ;

	 cudaMemcpy( d_active_vertices, trueval, sizeof(bool)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_updating_global_colors, sameindex, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_min_edge_weight, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_min_edge_index, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_global_min_edge_weight, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_global_min_edge_index, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_global_min_c2, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_degree, zero, sizeof(unsigned int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_updating_degree, zero, sizeof(unsigned int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_prev_colors, sameindex, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_prev_colorindex, sameindex, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_cycle_edge, infinity, sizeof(int)*no_of_nodes, cudaMemcpyHostToDevice) ;
	
	 cudaMemcpy( d_graph_edges, h_graph_edges, sizeof(int)*edge_list_size, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_graph_weights, h_graph_weights, sizeof(int)*edge_list_size, cudaMemcpyHostToDevice) ;
	 cudaMemcpy( d_graph_MST_edges, h_graph_MST_edges, sizeof(bool)*edge_list_size, cudaMemcpyHostToDevice) ;
}

void deviceMemAllocateEdges()
{
	 cudaMalloc( (void**) &d_graph_edges, sizeof(int)*edge_list_size) ;
	 cudaMalloc( (void**) &d_graph_weights, sizeof(int)*edge_list_size) ;
	 cudaMalloc( (void**) &d_graph_MST_edges, sizeof(bool)*edge_list_size) ;

}


void GPUMST()
{

	int num_of_blocks = 1;
	int num_of_threads_per_block = no_of_nodes;

	//Make execution Parameters according to the number of nodes
	//        //Distribute threads across multiple Blocks if necessary
	if(no_of_nodes>MAX_THREADS_PER_BLOCK)
	{
		num_of_blocks = (int)ceil(no_of_nodes/(double)MAX_THREADS_PER_BLOCK);
		num_of_threads_per_block = MAX_THREADS_PER_BLOCK;
	}

	// setup execution parameters
	dim3  grid( num_of_blocks, 1, 1);
	dim3  threads( num_of_threads_per_block, 1, 1);

	test  = (int*) malloc(sizeof(int)*no_of_nodes);
	testui  = (unsigned int*) malloc(sizeof(unsigned int)*no_of_nodes);
	testb = (bool*) malloc(sizeof(bool)*no_of_nodes);
	testbe = (bool*) malloc(sizeof(bool)*edge_list_size);

	

	//start the timer
	//~ unsigned int timer = 0;
	//~ unsigned int timer1 = 0;
	cudaDeviceSynchronize();
	//~ CUT_SAFE_CALL( cutCreateTimer( &timer);
	//~ CUT_SAFE_CALL( cutStartTimer( timer);
	int k=0,k3=0;

	bool over;
	bool done;
	/// TIMER CODE
	cudaEvent_t start, stop;
	cudaEventCreate(&start);
	cudaEventCreate(&stop);
	cudaEventRecord(start);
	do
	{

		//if no thread in Kernel1 changes this value then the loop stops
		over=false;
		 cudaMemcpy( d_over, &over, sizeof(bool), cudaMemcpyHostToDevice) ;

		Kernel_Find_Min_Edge_Weight_Per_Vertex<<< grid, threads, 0 >>>(d_graph_nodes, d_graph_edges, d_graph_weights,
				d_graph_MST_edges, d_graph_colorindex,
				d_global_colors, d_active_colors,
				d_global_min_edge_weight,d_min_edge_weight,
				d_min_edge_index, d_over, d_active_vertices, no_of_nodes);
		//CUT_CHECK_ERROR("Kernel_Find_Min_Edge_Weight_Per_Vertex execution failed");

		cudaDeviceSynchronize();

		 cudaMemcpy( &over, d_over, sizeof(bool), cudaMemcpyDeviceToHost) ;
		if(!over)break;

		Kernel_Find_Min_C2<<< grid, threads, 0 >>>(d_graph_edges, d_global_min_c2, d_graph_colorindex, d_global_colors, d_active_colors,
				d_global_min_edge_weight, d_min_edge_weight, d_min_edge_index, no_of_nodes );
		//CUT_CHECK_ERROR("Kernel_Find_Min_C1 execution failed");
		cudaDeviceSynchronize();

		Kernel_Add_Edge_To_Global_Min<<< grid, threads, 0 >>>(d_graph_edges, d_global_min_c2, d_graph_colorindex, d_global_colors,
				d_global_min_edge_index, d_min_edge_weight, d_min_edge_index,no_of_nodes );

		//CUT_CHECK_ERROR("Kernel_Add_Edge_To_Global_Min execution failed");
		cudaDeviceSynchronize();

		Kernel_Find_Degree<<< grid, threads, 0 >>>(d_graph_edges, d_graph_colorindex, d_global_colors, d_global_min_edge_index,
				d_degree, d_updating_degree, d_prev_colors, d_prev_colorindex, no_of_nodes );
		//CUT_CHECK_ERROR("Kernel_Find_Degree execution failed");
		cudaDeviceSynchronize();

		do
		{
			done=false;
			 cudaMemcpy( d_done, &done, sizeof(bool), cudaMemcpyHostToDevice) ;

			Kernel_Prop_Colors1<<< grid, threads, 0 >>>(d_graph_edges, d_graph_colorindex, d_global_colors,
					d_global_min_edge_index,d_updating_global_colors,  no_of_nodes );
			//CUT_CHECK_ERROR("Kernel_Prop_Colors1 execution failed");
			cudaDeviceSynchronize();

			Kernel_Prop_Colors2<<< grid, threads, 0 >>>(d_global_colors, d_active_colors, d_updating_global_colors,  d_done, no_of_nodes );
			//CUT_CHECK_ERROR("Kernel_Prop_Colors2 execution failed");
			cudaDeviceSynchronize();

			 cudaMemcpy( &done, d_done, sizeof(bool), cudaMemcpyDeviceToHost) ;
			k3++;
		}
		while(done);
		Kernel_Update_Colorindex<<< grid, threads, 0 >>>(d_graph_colorindex, d_global_colors, no_of_nodes);
		//CUT_CHECK_ERROR("Kernel_Updating_Colorindex execution failed");
		cudaDeviceSynchronize();

		bool removing = false;
		do
		{
			removing=false;
			 cudaMemcpy( d_removing, &removing, sizeof(bool), cudaMemcpyHostToDevice) ;

			Kernel_Dec_Degree1<<< grid, threads, 0 >>>(d_active_colors, d_degree, d_global_min_edge_index, d_graph_edges,
					d_prev_colorindex, d_prev_colors, d_updating_degree,
					d_graph_MST_edges,no_of_nodes);
			//CUT_CHECK_ERROR("Kernel_Dec_Degree1 execution failed");
			cudaDeviceSynchronize();


			Kernel_Dec_Degree2<<< grid, threads, 0 >>>(d_degree, d_active_colors, d_updating_degree, d_removing, no_of_nodes);
			//CUT_CHECK_ERROR("Kernel_Dec_Degree2 execution failed");
			cudaDeviceSynchronize();

			 cudaMemcpy( &removing, d_removing, sizeof(bool), cudaMemcpyDeviceToHost) ;
		}
		while(removing);


		Kernel_Add_Remaining_Edges<<< grid, threads, 0 >>>(d_global_min_edge_index,  d_graph_MST_edges,  no_of_nodes);
		//CUT_CHECK_ERROR("Kernel_Add_Remaining_Edges execution failed");
		cudaDeviceSynchronize();

		Kernel_Edge_Per_Cycle_New_Color<<< grid, threads, 0 >>>(d_global_min_edge_index, d_graph_edges, d_graph_colorindex,
				d_global_colors, d_cycle_edge, no_of_nodes );
		//CUT_CHECK_ERROR("Kernel_Edge_Per_Cycle_New_Color execution failed");
		cudaDeviceSynchronize();

		Kernel_Remove_Cycle_Edge_From_MST<<< grid, threads, 0 >>>(d_cycle_edge, d_graph_MST_edges, no_of_nodes);
		//CUT_CHECK_ERROR("Kernel_Add_Cycle_Edge_To_MST execution failed");
		cudaDeviceSynchronize();

		Kernel_Reinitialize<<< grid, threads, 0 >>>(d_active_colors, d_global_min_edge_index, d_global_min_c2,
				d_global_min_edge_weight, d_min_edge_index,d_min_edge_weight, d_degree,
				d_updating_degree, d_prev_colors, d_cycle_edge,
				d_prev_colorindex, no_of_nodes );

		//CUT_CHECK_ERROR("Kernel_Update_Colorindex execution failed");
		cudaDeviceSynchronize();

		k++;
	}
	while(1);

	//~ cudaDeviceSynchronize();
	cudaDeviceSynchronize();
	
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	float milliseconds = 0;
	cudaEventElapsedTime(&milliseconds, start, stop);
	
	//~ CUT_SAFE_CALL( cutStopTimer( timer));

	//~ CUT_SAFE_CALL( cutDeleteTimer( timer));
	//~ printf( "Processing time: %f (ms)\n", milliseconds);
		
}


void freeMem()
{
	free(test);
	free(testui);
	free(testb);
	free(testbe);

	free(h_graph_nodes);
	free(sameindex);
	free(falseval);
	free(trueval);
	free(infinity);
	free(zero);
	free(h_maxid_maxdegree);

	free(h_graph_edges);
	free(h_graph_weights);
	free(h_graph_MST_edges);


	cudaFree(d_graph_nodes);
	cudaFree(d_graph_colorindex);
	cudaFree(d_global_colors);
	cudaFree(d_active_colors);
	cudaFree(d_updating_global_colors);
	cudaFree(d_global_min_edge_weight);
	cudaFree(d_global_min_edge_index);
	cudaFree(d_global_min_c2);
	cudaFree(d_min_edge_weight);
	cudaFree(d_min_edge_index);

	cudaFree(d_degree);
	cudaFree(d_updating_degree);
	cudaFree(d_prev_colors);
	cudaFree(d_prev_colorindex);
	cudaFree(d_cycle_edge);

	cudaFree(d_graph_edges);
	cudaFree(d_graph_weights);
	cudaFree(d_graph_MST_edges);

}

