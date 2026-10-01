/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)  
*  Single precision (float data type) 
*  TurboBC:bcgpug.cuh
* 
*  This program defines the prototypes of some functions 
*  used to compute  the GPU-based parallel BC
*  for unweighted graphs represented by sparse 
*  adjacency matrices in the CSC and COOC formats.
*
*/

/*************************prototype GPU kernels********************************/
__global__ void bfsFunctionsKernel (int *f_d,int *ft_d,float *sigma_d,int *S,
				    int *c,int n,int d);
/******************************************************************************/
__global__ void deltaUKernel (int *S_d,float *delta_d,float *delta_u_d,
			     float *sigma_d,int n,int d);				
/******************************************************************************/
__global__ void deltaKernel (int *S_d,float *delta_d,float *delta_ut_d,
			     float *sigma_d,int n,int d);				
/******************************************************************************/
__global__ void bcKernel (float *bc_d,float *delta_d,int r,int n);				
/******************************************************************************/

