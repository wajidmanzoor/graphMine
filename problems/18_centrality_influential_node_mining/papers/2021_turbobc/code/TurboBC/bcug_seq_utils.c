/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)
*  Single precision (float data type) 
*  TurboBC:bcug_seq_utils.c
* 
*  This program computes some functions needed
*  for the computation of the sequential BC
*
*/

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "spmv_seq.h"
#include "bcug.h"


/* 
 * function to compute the sum of the sigma and f vectors
 * 
*/
int sum_vs (float *sigma,int *f,int n){
  
    int k;

    for (k=0; k<n; k++){
      if (f[k] > 0.9){
        sigma[k] += f[k];
      }    
    }
    
    return 0;
}//end sum_vs
/**************************************************************************/
/* 
 * function to check that the vector f is not 0
 * 
 */
int check_f (int *c,int *f,int n){
  
  int k;
  for (k=0; k<n; k++){  
    if (f[k] > 0.9){
      *c = 1;
      return 0;
    }
  }
 
  return 0;  
}//end check_f
/**************************************************************************/
/* 
 * function to compute the S vector to store the depth at which each vertex 
 * is discovered.
 * 
 */
int S_v (int *S,int *f,int n,int d){
  
  int k;
  for (k=0; k<n; k++){  
    if (f[k] > 0.9){
      S[k] = d;
    }
  }
 
  return 0;  
}//end S_v
/**************************************************************************/
/* 
 * function to set f[k] = 0 if sigma[k] != 0
*/
int mult_vs (float *sigma,int*f,int n){

   int k;

   for (k=0; k<n; k++){
      if (sigma[k] > 0.9){
        f[k] = 0;
      }    
   }

    return 0;
}//end  mult_vs

/**************************************************************************/
/* 
 * function to assign f_t to f if f_t !=0 
 * 
*/
int assign_v(int *f,int *f_t,int n){
  
    int k;

    for (k=0; k<n; k++){
      f[k] =  0;
      if (f_t[k] > 0.9){
        f[k] = f_t[k];
      }
    }
    
    return 0;
}//end assign_v

/**************************************************************************/
/* 
 * function to assign one vector to another vector
 * 
 */
int assign_fv(float *v,float *v_t,int n){

  int k;

  for (k=0; k<n; k++){
    v[k] = v_t[k];
  }

return 0;
}//end assign_fv

/******************************************************************************/
/* 
 * function to compute the delta_u vector
*/
int delta_u_v (int *S, float *delta,float *delta_u, float *sigma,int n,int d){

   int i;

   for (i=0; i<n; i++){
     delta_u[i] = 0.0;
     if (S[i] == d && sigma[i] > 0.9){
       delta_u[i] = (1.0 + delta[i])/sigma[i];
      }    
   }

    return 0;
}//end  delta_u_v


/******************************************************************************/
/* 
 * function to compute the delta vector
*/
int delta_v (int *S, float *delta,float *delta_ut, float *sigma,int n,int d){
   
   int i;

   for (i=0; i<n; i++){
     if (S[i] == d-1 && sigma[i] > 0.9){
       delta[i] += delta_ut[i]*sigma[i];
      }    
   } 
   return 0;
}//end  delta_v

/******************************************************************************/
/* 
 * function to compute the bc vector
*/
int bc_v (float *bc,float *delta,int r,int n){

  int i;

   for (i=0; i<n; i++){
     if (i != r) bc[i] += delta[i];
      }    

   return 0;
}//end  bc_v
