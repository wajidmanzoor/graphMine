/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)
*  Single precision (float data type) 
*  TurboBC:utils_bc.h
* 
*  This program:
*  1) prints results
*  2) check the GPU computed values of BFS shortest paths by comparing
*     with the results of the sequential BFS.
*  3) check the GPU computed values of the S vector by comparing
*     with the results of the sequential computed values of S.
*  4) check the GPU computed values of the bc vector by comparing
*     with the results of the sequential computed values of bc.
* 
*/

#ifndef  UTILS_BC_H
#define  UTILS_BC_H

/* 
 * function to print sparse formats and results
*/
int  printBC(int *I,int *J,int *ICOOC,int *JCOOC,int *S,int *S_hgpu,float *sigma,
	     float *sigma_hgpu,float *bc,float *bc_hgpu,int nz, int n);
	      
/******************************************************************************/		
/* 
 * function to check the GPU computed values of BFS shortest paths by comparing
 * with the results of the sequential BFS. 
*/
int bfs_check(float *sigma,float *sigma_hgpu,int n);

/******************************************************************************/
/* 
 * function to check the GPU computed values of the S vector by comparing
 * with the results of the sequential computed values of S. 
*/
int S_check(int *S,int *S_hgpu,int n);

/******************************************************************************/
/* 
 * function to check the GPU computed values of the bc vector by comparing
 * with the results of the sequential computed values of bc. 
*/
int bc_check(float *bc,float *bc_hgpu,int n);
#endif
