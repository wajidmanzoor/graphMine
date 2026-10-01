/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)
*  Single precision (float data type) 
*  TurboBC:spmv_seq.c
* 
*  This program computes:sequential vector sparse matrix 
*  multiplication (f <--A'f) for unweighted graphs represented
*  by sparse adjacency matrices in the CSC format.
*  
*  
*/

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "spmv_seq.h"

/* 
 * function to compute the sequential sparse matrix-vector multiplication for 
 * unweighted graphs represented by sparse adjacency matrices in the CSC format.  
 *   
*/
int spmv_seq_ug_csc (int *f,int *IC,int *CP,int *f_t,int n){
  
  int i, k, start, end;
  int sum;

   for (i=0; i<n; i++){
     sum = 0;
     start = CP[i];
     end = CP[i+1];
     for (k=start; k<end; k++){
       sum += f[IC[k]];
     }
     if (sum > 0.1){
       f_t[i] = sum;
     }
   }  
  
   return 0;
}//end spmv_seq_ug_csc

/******************************************************************************/
/* 
 * function to compute the delta_ut vector with a sequential sparse matrix-vector 
 * multiplication for unweighted graphs represented by sparse adjacency matrices 
 * in the CSC format. 
 *   
*/
int spmv_delta_ut (float *delta_u,int *IC,int *CP,float *delta_ut,int n){
  
  int i, k, start, end;
  float sum;

   for (i=0; i<n; i++){
     delta_ut[i] = 0.0;
     sum = 0.0;
     start = CP[i];
     end = CP[i+1];
     for (k=start; k<end; k++){
       sum += delta_u[IC[k]];
     }
     if (sum > 0.0){
       delta_ut[i] = sum;
     }
   }  

  return 0;
}//end spmv_delta_ut
