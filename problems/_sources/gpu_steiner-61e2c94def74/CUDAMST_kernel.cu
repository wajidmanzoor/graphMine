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




#ifndef _CUDAMST_KERNEL_H_
#define _CUDAMST_KERNEL_H_

#define INF 100000000



	__global__ void
Kernel_Find_Min_Edge_Weight_Per_Vertex(Node* g_graph_nodes, int* g_graph_edges, int *g_graph_weights, bool* g_graph_MST_edges, int* g_graph_colorindex,
		int* g_global_colors, bool* g_active_colors, int *g_global_min_edge_weight, int *g_min_edge_weight,
		int *g_min_edge_index,  bool* g_over, bool *g_active_vertices, int no_of_nodes)
{
	int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
	if( tid < no_of_nodes && g_active_vertices[tid])
	{
		int color, colorindex, minedgeweight, edgeindex, addingvertex, minaddingvertexcolor, addingvertexcolorindex, addingvertexcolor, weight;
		colorindex = g_graph_colorindex[tid];
		color = g_global_colors[colorindex];
		//set the active colors
		if(!g_active_colors[color])
			g_active_colors[color]=true;
		
		//The overall termination condition
		                
		if(color!=0)
			*g_over = true;


		int start, end;
		start = g_graph_nodes[tid].starting;
		end = g_graph_nodes[tid].no_of_edges + start;

		minedgeweight = INF;
		minaddingvertexcolor = INF;
		edgeindex = INF;
		bool allsame=true;
		
		//Find the Minimum edge for this vertex, which is not in already MST and also not connecting any vertex of same color
		                
		for(int i=start; i< end; i++)
		{
			addingvertex = g_graph_edges[i];
			addingvertexcolorindex = g_graph_colorindex[addingvertex];
			addingvertexcolor = g_global_colors[addingvertexcolorindex];
			weight = g_graph_weights[i];

			if (!g_graph_MST_edges[i] && (color!=addingvertexcolor) )
			{
				if(minedgeweight > weight)
				{
					minedgeweight = weight;
					edgeindex=i;
				}
				if(minedgeweight == weight)
				{
					if(minaddingvertexcolor > addingvertexcolor)
					{
						minaddingvertexcolor = addingvertexcolor;
						edgeindex=i;
					}

				}
			}
			if(color!=addingvertexcolor)
				allsame=false;
		}

		if(allsame)
			g_active_vertices[tid]=false;


		if(edgeindex!=INF)
		{
			//Store these two values for each vertex
			g_min_edge_weight[tid] = minedgeweight;
			g_min_edge_index[tid] = edgeindex;
			//Write the edge weight atomically in a global location
			atomicMin(&g_global_min_edge_weight[color], minedgeweight);
		}


	}

}



__global__ void
Kernel_Find_Min_C2(int *g_graph_edges, int *g_global_min_c2, int* g_graph_colorindex, int* g_global_colors, bool *g_active_colors,
                int* g_global_min_edge_weight, int* g_min_edge_weight, int* g_min_edge_index, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if( tid < no_of_nodes )
        {

                int edgeindex = g_min_edge_index[tid];
                if(edgeindex!=INF)
                {
                        int colorindex,color;
                        colorindex = g_graph_colorindex[tid];
                        color = g_global_colors[colorindex];

                        if((g_global_min_edge_weight[color] ==  g_min_edge_weight[tid])) //The weight is found, write the index value
                        {
                                int v2 = g_graph_edges[edgeindex];
                                int v2_index = g_graph_colorindex[v2];
                                int c2 = g_global_colors[v2_index];
                                atomicMin(&g_global_min_c2[color],c2);
                        }
                        else
                        {
                                g_min_edge_weight[tid]= INF;
                                g_min_edge_index[tid] = INF;
                        }
                }

        }
}



__global__ void
Kernel_Add_Edge_To_Global_Min(int * g_graph_edges, int * g_global_min_c2, int* g_graph_colorindex, int* g_global_colors,
        int* g_global_min_edge_index, int* g_min_edge_weight, int* g_min_edge_index, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if( tid < no_of_nodes )
        {
                int colorindex,color;
                colorindex = g_graph_colorindex[tid];
                color = g_global_colors[colorindex];
                int edgeindex = g_min_edge_index[tid];

                if(edgeindex!=INF )//The weight is found, write the index value
                {
                        int v2 = g_graph_edges[edgeindex];
                        int v2i = g_graph_colorindex[v2];
                        int c2 = g_global_colors[v2i];
                        if(c2 == g_global_min_c2[color])
                                {
                                atomicMin(&g_global_min_edge_index[color], edgeindex);
                                }
                        else
                                {
                                g_min_edge_weight[tid]=INF;
                                g_min_edge_index[tid]=INF;
                                }
                }

        }
}



__global__ void
Kernel_Find_Degree(int * g_graph_edges, int* g_graph_colorindex, int* g_global_colors, int* g_global_min_edge_index,
                unsigned int* g_degree, unsigned int * g_updating_degree, int* g_prev_colors, int* g_prev_colorindex, int no_of_nodes)
{
        int color = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if( color < no_of_nodes )
        {
                int edgeindex = g_global_min_edge_index[color];
                if(edgeindex!=INF )
                {
                        int v2 = g_graph_edges[edgeindex];
                        int civ2 = g_graph_colorindex[v2];
                        int colv1 = color;
                        int colv2 = g_global_colors[civ2];


                        atomicInc(&g_degree[colv1],INF);
                        atomicInc(&g_degree[colv2],INF);

                        atomicInc(&g_updating_degree[colv1],INF);
                        atomicInc(&g_updating_degree[colv2],INF);
                }

                g_prev_colors[color] = g_global_colors[color];
                g_prev_colorindex[color] = g_graph_colorindex[color];
        }
}

        __global__ void
Kernel_Prop_Colors1(int *g_graph_edges, int *g_graph_colorindex, int *g_global_colors, int* g_global_min_edge_index,
        int* g_updating_global_colors,  int no_of_nodes)
{

        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                int edgeindex = g_global_min_edge_index[tid];
                if(edgeindex!=INF)
                {
                        //Update the color of each neighbour using edges present in newly added edges MST only
                        int v1color,v2,v2index,v2color;
                        v2 = g_graph_edges[edgeindex];
                        v1color = g_global_colors[tid];
                        v2index = g_graph_colorindex[v2];
                        v2color = g_global_colors[v2index];
                        atomicMin( &g_updating_global_colors[tid], v2color);
                        atomicMin( &g_updating_global_colors[v2index], v1color);
                }
        }
}
			

 __global__ void
Kernel_Prop_Colors2(int *g_global_colors, bool *g_active_colors, int *g_updating_global_colors,  bool* g_done, int no_of_nodes)
{
        //This kernel works on the global_colors[] array
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                if(g_active_colors[tid])
                {
                        int color = g_global_colors[tid];
                        int updatingcolor = g_updating_global_colors[tid];
                        if(color > updatingcolor)
                        {
                                g_global_colors[tid] = updatingcolor;
                                *g_done = true; //Termination condition for Kernel 4 and Kernel 5 while loop
                        }
                }
                g_updating_global_colors[tid] = g_global_colors[tid];
        }
}


__global__ void
Kernel_Dec_Degree1(bool *g_active_colors, unsigned int* g_degree, int* g_global_min_edge_index, int* g_graph_edges,
                int* g_prev_colorindex, int* g_prev_colors, unsigned int* g_updating_degree, bool* g_graph_MST_edges , int no_of_nodes)
{
        //This kernel works on the global_colors[] array  
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                int edgeindex = g_global_min_edge_index[tid];
                if(edgeindex != INF)
                {
                        int v2 = g_graph_edges[edgeindex];
                        int ci_v2 = g_prev_colorindex[v2];
                        int colv1 = tid;
                        int colv2 = g_prev_colors[ci_v2];

                        if(g_degree[colv1]==1)
                        {
                                atomicDec(&g_updating_degree[colv1],INF);
                                atomicDec(&g_updating_degree[colv2],INF);

                                //Here Only Mark The edge into MST
                                g_graph_MST_edges[edgeindex] = true;

                                //Remove this Edge, its work is done      
                                g_global_min_edge_index[tid] = INF;
                        }
                }
        }
}

__global__ void
Kernel_Dec_Degree2(unsigned int *g_degree, bool *g_active_colors, unsigned int *g_updating_degree, bool *g_removing, int no_of_nodes)
{
        //This kernel works on the global_colors[] array  
        int color = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(color < no_of_nodes)
        {
                if(g_active_colors[color])
                {
                        int updating_degree = g_updating_degree[color];
                        if(g_degree[color] > updating_degree)
                        {
                                g_degree[color] = updating_degree;
                                *g_removing = true;
                        }
                }
        }
}


        __global__ void
Kernel_Add_Remaining_Edges(int *g_global_min_edge_index,  bool* g_graph_MST_edges, int no_of_nodes)
{
        //This kernel works on the global_colors[] array  
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                int edgeindex = g_global_min_edge_index[tid];
                if(edgeindex!=INF)
                {
                        g_graph_MST_edges[edgeindex]=true;
                }
        }

}


__global__ void
Kernel_Edge_Per_Cycle_New_Color(int *g_global_min_edge_index,int* g_graph_edges, int* g_graph_colorindex,
                                int *g_global_colors, int *g_cycle_edge, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                int edgeindex = g_global_min_edge_index[tid];
                if(edgeindex!=INF)
                        {
                        int v2 = g_graph_edges[edgeindex];
                        int ci_v2 = g_graph_colorindex[v2];
                        int colv2 = g_global_colors[ci_v2];
                        atomicMin(&g_cycle_edge[colv2], edgeindex);
                        }

        }
}

__global__ void
Kernel_Remove_Cycle_Edge_From_MST(int *g_cycle_edge, bool *g_graph_MST_edges, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes)
        {
                int edgeindex = g_cycle_edge[tid];
                if(edgeindex!=INF)
                        {
                        g_graph_MST_edges[edgeindex] = false;
                        }

        }
}

__global__ void
Kernel_Update_Colorindex(int *g_graph_colorindex, int *g_global_colors, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes )
        {
                int colorindex = g_graph_colorindex[tid];
                int color = g_global_colors[colorindex];
                while(color!=colorindex)
                {
                        colorindex = g_global_colors[color];
                        color = g_global_colors[colorindex];
                }

                //This is the color I should point to
                g_graph_colorindex[tid]=colorindex;

        }
}

__global__ void
Kernel_Reinitialize(bool *g_active_colors, int *g_global_min_edge_index, int *g_global_min_c2,
                        int* g_global_min_edge_weight, int* g_min_edge_index, int* g_min_edge_weight,
                        unsigned int* g_degree, unsigned int* g_updating_degree,
                        int* g_prev_colors, int *g_cycle_edge, int* g_prev_colorindex, int no_of_nodes)
{
        int tid = blockIdx.x*MAX_THREADS_PER_BLOCK + threadIdx.x;
        if(tid < no_of_nodes )
        {
                //Re-Initialization of arrays
                g_active_colors[tid] = false;
                g_global_min_edge_index[tid] = INF;
                g_global_min_edge_weight[tid] = INF;
                g_global_min_c2[tid] = INF;
                g_min_edge_index[tid]=INF;
                g_min_edge_weight[tid]=INF;
                g_degree[tid]=0;
                g_updating_degree[tid]=0;
                g_prev_colors[tid]=INF;
                g_prev_colorindex[tid]=INF;
                g_cycle_edge[tid]=INF;
        }
}




#endif

