/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)
*  Single precision (float data type) 
*  TurboBC:utils_bc.c
* 
*  This program:
*  1) prints results
*  2) check the GPU computed values of BFS shortest paths by comparing
*    with the results of the sequential BFS.
*  3) check the GPU computed values of the S vector by comparing
*     with the results of the sequential computed values of S.
*  4) check the GPU computed values of the bc vector by comparing
*     with the results of the sequential computed values of bc.
* 
*/

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "utils_bc.h"

/* 
 * function to print sparse formats and results
*/
int printBC(int *I,int *J,int *ICOOC,int *JCOOC,int *S,int *S_hgpu,float *sigma,
	     float *sigma_hgpu,float *bc,float *bc_hgpu,int nz, int n){

    /* Print every score so validation can compare the complete result vector. */
    int i,m1 = n;

    /*printf("CscA.IC  CoocA.ICOOC CoocA.JCOOC\n");    
    if (n > m1){
       for (i=0; i<m1; i++){
	  printf("%d %d %d %d\n",i,IC[i], ICOOC[i], JCOOC[i]);
	}
	for (i=nz-m1; i<nz; i++){
	  printf("%d %d %d %d\n",i,IC[i], ICOOC[i], JCOOC[i]);
	}
    }else{
	for (i=0; i<nz; i++){
	  printf("%d %d %d %d\n",i,IC[i], ICOOC[i], JCOOC[i]);
	}
    }
    printf("CscA.CP \n");
    if (n > m1){
	for (i=0; i<m1; i++){
	  printf("%d %d\n",i, CP[i]);
	}
	for (i=n-m1; i<n+1; i++){
	  printf("%d %d\n",i, CP[i]);
	}
    }else{
	for (i=0; i<n+1; i++){
	  printf("%d %d\n",i, CP[i]);
	}
	}*/

    printf("\nS   S_hgpu \n");
    if (n > m1){
	for (i=0; i<m1; i++){
	  printf("%d,%d,%d\n",i,S[i],S_hgpu[i]);
	}
	for (i=n-m1; i<n; i++){
	  printf("%d,%d,%d\n",i,S[i],S_hgpu[i]);
	}
    }else{
	for (i=0; i<n; i++){
	  printf("%d,%d,%d\n", i,S[i],S_hgpu[i]);
	}
    }
    
    printf("\nsigma   sigma_hgpu \n");
    if (n > m1){
	for (i=0; i<m1; i++){
	  printf("%d,%lf,%lf\n",i,sigma[i],sigma_hgpu[i]);
	}
	for (i=n-m1; i<n; i++){
	  printf("%d,%lf,%lf\n",i,sigma[i],sigma_hgpu[i]);
	}
    }else{
	for (i=0; i<n; i++){
	  printf("%d,%lf,%lf\n",i,sigma[i],sigma_hgpu[i]);
	}
    }

    printf("\nbc   bc_hgpu \n");
    if (n > m1){
	for (i=0; i<m1; i++){
	  printf("%d,%lf,%lf\n",i,bc[i],bc_hgpu[i]);
	}
	for (i=n-m1; i<n; i++){
	  printf("%d,%lf,%lf\n",i,bc[i],bc_hgpu[i]);
	}
    }else{
	for (i=0; i<n; i++){
	  printf("%d,%lf,%lf\n",i,bc[i],bc_hgpu[i]);
	}
    }
    
    return 0;
}// end printBC

/******************************************************************************/
/* 
 * function to check the GPU computed values of BFS shortest paths by comparing
 * with the results of the sequential BFS. 
*/
int bfs_check(float *sigma,float *sigma_hgpu,int n){

    int i;
    int check = 1;
    float epsilon = 1.0e-5;
    int count = 0;
    
    for (i=0; i<n; i++){
      if (fabs (sigma[i]-sigma_hgpu[i]) > epsilon){
	check = 0;
        count++;      
      }
    }
    if(check){
      printf("values of the GPU computed sigma vector are correct \n");
    }else{
      printf("error in %d values of the GPU computed sigma_hgpu vector\n",count);
    }	
  
    return 0;
}//end bfs_check

/******************************************************************************/
/* 
 * function to check the GPU computed values of the S vector by comparing
 * with the results of the sequential computed values of S. 
*/
int S_check(int *S,int *S_hgpu,int n){

    int i;
    int check = 1;
    int epsilon = 1.0e-5;
    int count = 0;
    
    for (i=0; i<n; i++){
      if (fabs (S[i]-S_hgpu[i]) > epsilon){
	check = 0;
        count++;      
      }
    }
    if(check){
      printf("values of the GPU computed S vector are correct \n");
    }else{
      printf("error in %d values of the GPU computed S_hgpu vector\n",count);
    }	
  
    return 0;
}//end S_check

/******************************************************************************/
/* 
 * function to check the GPU computed values of the bc vector by comparing
 * with the results of the sequential computed values of bc. 
*/
int bc_check(float *bc,float *bc_hgpu,int n){

    int i;
    int check = 1;
    float epsilon = 0.05;
    int count = 0;
    
    for (i=0; i<n; i++){
      if (fabs (bc[i]-bc_hgpu[i]) > epsilon){
	check = 0;
        count++;      
      }
    }
    if(check){
      printf("values of the GPU computed bc vector are correct \n");
    }else{
      printf("error in %d values of the GPU computed bc_hgpu vector\n",count);
    }	
  
    return 0;
}//end bc_check
