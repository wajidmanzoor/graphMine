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


#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
//#include <cutil.h>


#define MAX_THREADS_PER_BLOCK 512


int no_of_nodes;
int edge_list_size;
int  source, start, edgeno;

FILE *fp;

struct Node
{
        int starting;
        int no_of_edges;
};

#include "CUDAMST_kernel.cu"


void MSTGraph(int argc, char** argv);
void hostMemAllocationNodes();
void hostMemAllocationEdges();

void deviceMemAllocationNodes();
void deviceMemAllocationEdges();

void deviceMemCopy(); 


void GPUMST() ; 
void freeMem(); 
Node* h_graph_nodes;
int *sameindex, *infinity, *zero, *h_maxid_maxdegree, *h_graph_edges, *h_graph_weights ;
bool *falseval, *trueval, *h_graph_MST_edges;

// Rajz
int *h_graph_edges_dup, *h_graph_weights_dup;

int *d_global_colors, *d_graph_colorindex, *d_updating_global_colors, *d_min_edge_weight, *d_min_edge_index;
bool *d_active_colors, *d_active_vertices; 
int *d_global_min_edge_weight, *d_global_min_edge_index, *d_global_min_c2, *d_prev_colors, *d_prev_colorindex, *d_cycle_edge;
unsigned int *d_degree, *d_updating_degree;
Node* d_graph_nodes;
int *d_graph_edges, *d_graph_weights;
bool *d_graph_MST_edges, *d_over, *d_done, *d_removing;
int *test; 
unsigned int *testui; 
bool *testb, *testbe ; 





