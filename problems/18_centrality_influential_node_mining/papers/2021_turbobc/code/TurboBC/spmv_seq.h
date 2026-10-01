/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)
*  Single precision (float data type) 
*  TurboBC:spmv_seq.h
* 
*  This program computes:sequential vector sparse matrix 
*  multiplication (f <--A'f) for unweighted graphs represented
*  by sparse adjacency matrices in the CSC format.
*  
*  
*/

#ifndef SPMV_SEQ_H
#define SPMV_SEQ_H

/* 
 * function to compute the sequential sparse matrix-vector multiplication for 
 * unweighted graphs represented by sparse adjacency matrices in the CSC format.  
 *   
*/
int spmv_seq_ug_csc (int *f,int *I,int *CP,int *f_t,int n);

/******************************************************************************/
/* 
 * function to compute the delta_ut vector with a sequential sparse matrix-vector 
 * multiplication for unweighted graphs represented by sparse adjacency matrices 
 * in the CSC format. 
 *   
*/
int spmv_delta_ut (float *delta_u,int *I,int *CP,float *delta_ut,int n);


#endif
