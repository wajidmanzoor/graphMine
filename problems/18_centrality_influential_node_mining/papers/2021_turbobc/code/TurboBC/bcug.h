/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC) 
*  Single precision (float data type)
*  TurboBC:bcug.h
* 
*   This program computes: 
*   1) a sequential BC for unweighted,
*      graphs with sparse matrices in the CSC format.
*   2) a single precision GPU-based parallel BC for unweighted,
*      graphs with sparse matrices in the CSC and in the COOC 
*      formats.
*      
* 
*/

#ifndef BCUG_H
#define BCUG_H

#define MAX_THREADS_PER_GRID (2**31)
#define THREADS_PER_WARP 32
#define THREADS_PER_BLOCK 1024
#define WARPS_PER_BLOCK (THREADS_PER_BLOCK/THREADS_PER_WARP)
#define I_SIZE ((3/2)*THREADS_PER_BLOCK)


/*define Structure of Arrays (SoA) for the sparse matrix A representing
 unweighted graphs in the CSC format*/
struct Csc{
  int   *IC;
  int   *CP;
  
};

/*define Structure of Arrays (SoA) for the sparse matrix A in the COOC format*/
struct Cooc{
      int   *ICOOC;
      int   *JCOOC;
};

/******************************************************************************/
/* 
 * function to compute a sequential BC for unweighted graphs,represented by
 * sparse adjacency matrices in CSC format.    
 *  
*/
int bc_seq_ug_csc (int *I,int *CP,int *S,float *sigma,float *bc,int nr,int rs,
		   int nz,int n);

/******************************************************************************/
/* 
 * function to compute a gpu-based parallel BC (scalar) for unweighted graphs 
 * represented by sparse adjacency matrices in CSC format. 
 *  
 */
int  bc_gpu_ug_csc_sc (int *I_h,int *CP_h,int *S_h,float *sigma_h,float *bc_h,
		       int nr,int rs,int nz,int n,int repetition);

/******************************************************************************/
/* 
 * function to compute a gpu-based parallel BC (warp shuffle) for unweighted
 * graphs represented by sparse adjacency matrices in CSC format.
 *  
 */
int  bc_gpu_ug_csc_wa (int *I_h,int *CP_h,int *S_h,float *sigma_h,float *bc_h,
		       int nr,int rs,int nz,int n,int repetition);

/******************************************************************************/
/* 
 * function to compute a gpu-based parallel BC (scalar) for unweighted graphs 
 * represented by sparse adjacency matrices in COOC format. 
 *  
 */
int  bc_gpu_ug_cooc_sc (int *I_h,int *J_h,int *S_h,float *sigma_h,float *bc_h,
		       int nr,int rs,int nz,int n,int repetition);


/******************************************************************************/
/* 
 * function to compute the sum of the sigma and f vectors
 * 
*/
int sum_vs (float *sigma,int *f,int n);

/*****************************************************************************/
/* 
 * function to check that the vector f is not 0
 * 
 */
int check_f (int *c,int *f,int n);

/*****************************************************************************/
/* 
 * function to compute the S vector to store the depth at which each vertex 
 * is discovered.
 * 
 */
int S_v (int *S,int *f,int n,int d);

/******************************************************************************/
/* 
 * function to set f[k] = 0 if sigma[k] != 0
*/
int mult_vs (float *sigma,int *f,int n);

/*****************************************************************************/
/* 
 * function to assign f_t to f if f_t !=0  
 * 
*/
int assign_v(int *f,int *f_t,int n);

/**************************************************************************/
/* 
 * function to assign one vector to another vector
 * 
 */
int assign_fv(float *v,float *v_t,int n);

/******************************************************************************/
/* 
 * function to compute the delta_u vector
*/
int delta_u_v (int *S, float *delta,float *delta_u, float *sigma,int n,int d);

/******************************************************************************/
/* 
 * function to compute the delta vector
*/
int delta_v (int *S, float *delta,float *delta_ut, float *sigma,int n,int d);

/******************************************************************************/
/* 
 * function to compute the bc vector
*/
int bc_v (float *bc,float *delta,int r,int n);

#endif
