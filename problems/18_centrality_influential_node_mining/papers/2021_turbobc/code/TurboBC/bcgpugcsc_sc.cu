/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccoo_main.c of this source distribution.
*/
/* 
*  Betweenness centrality (BC)  
*  Single precision (float data type) 
*  TurboBC:bcgpugcsc_sc.cu
* 
*  This program computes the GPU-based parallel BC
*  (scalar) for unweighted graphs represented 
*  by sparse adjacency matrices in the CSC format.
*
 */

#include <cstdlib>
#include <iostream>
#include <cassert>
#include <cmath>

//includes CUDA project
#include <cuda.h>
#include <cuda_runtime.h>
#include <helper_cuda.h>
#include <helper_functions.h>
#include "bcgpug.cuh"
#include <thrust/sort.h>
extern "C"{
               #include "bcug.h"

}


/*************************prototype kernels*************************************/
__global__ void spMVBFSscKernel (int *CP_d,int *I_d,int *ft_d,int *f_d,
				   float *sigma_d,int d,int r,int n);
/******************************************************************************/
__global__ void spMVBCscKernel (int *CP_d,int *I_d,float *delta_ut_d,
				float *delta_u_d,int n);
/******************************************************************************/

/* 
 * function to compute a gpu-based parallel BC (scalar) for unweighted graphs 
 * represented by sparse adjacency matrices in CSC format. 
 *  
 */
int  bc_gpu_ug_csc_sc (int *I_h,int *CP_h,int *S_h,float *sigma_h,float *bc_h,
			int nr,int rs,int nz,int n,int repetition){
  float t_H_to_D_CP;
  float t_H_to_D_I;
  float t_D_to_H_sigma;
  float t_D_to_H_S;
  float t_D_to_H_bc;
  float t_bfs_spmv = 0.0;
  float t_bfs_spmv_t= 0.0;
  float t_bfsfunctions = 0.0;
  float t_bfsfunctions_t = 0.0;
  float t_bfs_sum = 0.0;
  float t_bfs_avg = 0.0;
  float t_allocate = 0.0;
  float t_allocate_t = 0.0;
  float t_delta_u = 0.0;
  float t_delta_u_t = 0.0;
  float t_bc_spmv = 0.0;
  float t_bc_spmv_t = 0.0;
  float t_delta = 0.0;
  float t_delta_t = 0.0;
  float t_delta_sum = 0.0;
  float t_delta_avg = 0.0;
  float t_bc = 0.0;
  float total_BC_t = 0.0;
  int i,r,d,dimGrid;
  cudaEvent_t start, stop;
  cudaEventCreate(&start);
  cudaEventCreate(&stop);
  float *delta_d;
  float *delta_u_d;
  float *delta_ut_d;
  int *ft_d;
  int *f_d;
  //printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc starting ok\n");

  /*Allocate device memory for the vector CP_d */
  int *CP_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&CP_d),sizeof(*CP_d)*(n+1)));
  cudaEventRecord(stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for CP_d ok\n");
  
  /*Copy host memory (CP_h) to device memory (CP_d)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(CP_d,CP_h,(n+1)*sizeof(*CP_d),cudaMemcpyHostToDevice));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_H_to_D_CP,start,stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::Copy CP_h to CP_d ok\n");

  /*Allocate device memory for the vector I_d */
  int *I_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&I_d),sizeof(*I_d)*nz));
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for I_d ok\n");
  /*Copy host memory (I_h) to device memory (I_d)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(I_d,I_h,nz*sizeof(*I_d),cudaMemcpyHostToDevice));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_H_to_D_I,start,stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::Copy I_h to I_d ok\n");

  /*Allocate device memory for the vector S_d. */
  int *S_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&S_d),sizeof(*S_d)*n));  
  //checkCudaErrors(cudaMemset(S_d,0,sizeof(*S_d)*n));
  //printf("bfsgpugcsc_sc::bfs_gpu_ug_csc_sc:: Allocate device memory for S_d ok\n");

  /*Allocate device memory for the vector sigma_d */
  float *sigma_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&sigma_d),sizeof(*sigma_d)*n));
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for sigma_d ok\n");

  /*allocate unified memory for integer variable c for control of the BFS while loop*/
  int *c;
  checkCudaErrors(cudaMallocManaged(reinterpret_cast<void **>(&c),sizeof(*c)));

  /*Allocate device memory for the vector bc_d and set bc_d to zero*/
  float *bc_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&bc_d),sizeof(*bc_d)*n));
  checkCudaErrors(cudaMemset(bc_d,0.0,sizeof(*bc_d)*n));
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for bc_d ok\n");
  
  dimGrid = (n + THREADS_PER_BLOCK)/THREADS_PER_BLOCK;
  /*computing BC */    
#ifndef GRAPHMINE_LIBRARY
  printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: computing BC starts..\n");
#endif
  for (r=0; r<nr; r++){

    if (nr == 1) r = rs;
    /*Allocate device memory for the vector delta_d*/
     checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_d),sizeof(*delta_d)*n));
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for delta_d ok\n");
      
    /*computing BFS */    
    //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: computing BFS starts..\n");
    for (i = 0; i<repetition; i++){
          
      /*Allocate device memory for the vector ft_d*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&ft_d),sizeof(*ft_d)*n));
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for ft_d ok\n");
      /*Allocate device memory for the vector f_d and set f_d to zero*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&f_d),sizeof(*f_d)*n));
      checkCudaErrors(cudaMemset(f_d,0,sizeof(*f_d)*n));
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for f_d ok\n");     
      checkCudaErrors(cudaMemset(sigma_d,0.0,sizeof(*sigma_d)*n));
      checkCudaErrors(cudaMemset(S_d,0,sizeof(*S_d)*n));

      *c = 1;
      d = 0;
      while (*c){
	d = d + 1;
	*c = 0;
	cudaEventRecord(start);
	spMVBFSscKernel <<<dimGrid,THREADS_PER_BLOCK>>> (CP_d,I_d,ft_d,f_d,sigma_d,d,r,n);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_bfs_spmv,start,stop);
	t_bfs_spmv_t += t_bfs_spmv;

	cudaEventRecord(start);
	bfsFunctionsKernel <<<dimGrid,THREADS_PER_BLOCK>>> (f_d,ft_d,sigma_d,S_d,c,n,d);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_bfsfunctions,start,stop);
	t_bfsfunctions_t += t_bfsfunctions;

	//printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc::*c = %d,d = %d \n",*c,d);
	t_bfs_sum += t_bfs_spmv + t_bfsfunctions;
	//printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc::while:d = %d,i = %d,t_bfs_sum=%lfms \n",d,i,t_bfs_sum);
      }                 
#ifndef GRAPHMINE_LIBRARY
      if (i == 0 && nr == 1)  printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::BFS  ok d =%d\n",d);
#endif

       /*freeing and allocating memory for BC while loop  */    
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: freeing and allocating memory for BC while loop..\n");
       cudaEventRecord(start);
      //free memory of f_d and ft_d vectors
      checkCudaErrors(cudaFree(f_d));
      checkCudaErrors(cudaFree(ft_d));
      /*set delta_d to zero*/
       checkCudaErrors(cudaMemset(delta_d,0.0,sizeof(*delta_d)*n));
       /*Allocate device memory for the vector delta_u_d*/
       checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_u_d),sizeof(*delta_u_d)*n));
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for delta_u_d ok\n");
      /*Allocate device memory for the vector delta_ut_d*/
       checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_ut_d),sizeof(*delta_ut_d)*n));
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: Allocate device memory for delta_ut_d ok\n");
      cudaEventRecord(stop);
      cudaEventSynchronize(stop);
      cudaEventElapsedTime(&t_allocate,start,stop);
      t_allocate_t += t_allocate;

      /*computing delta with while loop  */    
       //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:: computing BC while loop starts..\n");
      d = d-1;
      while (d > 1){

	cudaEventRecord(start);
	deltaUKernel <<<dimGrid,THREADS_PER_BLOCK>>> (S_d,delta_d,delta_u_d,sigma_d,n,d);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_delta_u,start,stop);
	t_delta_u_t += t_delta_u;
	 
	cudaEventRecord(start);
	spMVBCscKernel <<<dimGrid,THREADS_PER_BLOCK>>> (CP_d,I_d,delta_ut_d,delta_u_d,n);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_bc_spmv,start,stop);
	t_bc_spmv_t += t_bc_spmv;

	cudaEventRecord(start);
	deltaKernel <<<dimGrid,THREADS_PER_BLOCK>>> (S_d,delta_d,delta_ut_d,sigma_d,n,d);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_delta,start,stop);
	t_delta_t += t_delta;

	d = d-1;
	t_delta_sum += t_delta_u + t_bc_spmv + t_delta;
	//printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc::while:d = %d,i = %d,t_delta_sum=%lfms \n",d,i,t_delta_sum);
      }
      //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::delta  ok\n");
      checkCudaErrors(cudaFree(delta_u_d));
      checkCudaErrors(cudaFree(delta_ut_d));
    }//end repetition
    cudaEventRecord(start);
    bcKernel <<<dimGrid,THREADS_PER_BLOCK>>> (bc_d,delta_d,r,n);
    cudaEventRecord(stop);
    cudaEventSynchronize(stop);
    cudaEventElapsedTime(&t_bc,start,stop);

    checkCudaErrors(cudaFree(delta_d));
  }//end for loop
#ifndef GRAPHMINE_LIBRARY
   printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc::t_bfs_sum=%lfms \n",t_bfs_sum);
#endif
   t_bfs_avg = t_bfs_sum/repetition;
#ifndef GRAPHMINE_LIBRARY
   printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc::t_delta_sum=%lfms \n",t_delta_sum);
#endif
   t_delta_avg = t_delta_sum/repetition;
   total_BC_t =  t_bfs_avg + t_delta_avg + t_allocate/repetition + t_bc;
 
  /*Copy device memory (sigma_d) to host memory (sigma_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(sigma_h,sigma_d, n*sizeof(*sigma_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_sigma,start,stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::Copy sigma_d to sigma_h ok\n");

  /*Copy device memory (S_d) to host memory (S_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(S_h,S_d, n*sizeof(*S_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_S,start,stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::Copy S_d to S_h ok\n");

  /*Copy device memory (bc_d) to host memory (bc_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(bc_h,bc_d, n*sizeof(*bc_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_bc,start,stop);
  //printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc::Copy bc_d to bc_h ok\n");

#ifdef GRAPHMINE_LIBRARY
  int print_t = 0;
#else
  int print_t = 1;
#endif
  if (print_t){
    printf("\nbcgpugcsc_sc::bc_gpu_ug_csc_sc:time CP_h to CP_d = %lfms \n",t_H_to_D_CP);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time I_h to I_d = %lfms \n",t_H_to_D_I);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time f <-- A'f  = %lfms \n",t_bfs_spmv_t/repetition);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time time bfs functions  = %lfms \n", t_bfsfunctions_t/repetition);    
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:average time BFS  = %lfms \n",t_bfs_avg);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:average time BFS/vertex  = %lfms \n",t_bfs_avg/nr);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time to allocate memory for BC stage = %lfms \n",t_allocate/repetition);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time delta_u <-- (1+delta)/sigma  = %lfms \n",t_delta_u_t/repetition);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time delta_ut <-- A'delta_u  = %lfms \n",t_bc_spmv_t/repetition);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time delta <-- delta + delta_ut*sigma  = %lfms \n",t_delta_t/repetition);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:average time delta   = %lfms \n",t_delta_avg);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:average time delta/vertex   = %lfms \n",t_delta_avg/nr);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time bc <-- bc +delta/2 = %lfms \n",t_bc);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:total BC time = %lfms \n",total_BC_t);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:total BC time/vertex = %lfms \n",total_BC_t/nr);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time sigma_d to sigma_h = %lfms \n",t_D_to_H_sigma);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time S_d to S_h = %lfms \n",t_D_to_H_S);
    printf("bcgpugcsc_sc::bc_gpu_ug_csc_sc:time bc_d to bc_h = %lfms \n",t_D_to_H_bc);
  }

  /*cleanup memory*/
  checkCudaErrors(cudaFree(CP_d));
  checkCudaErrors(cudaFree(I_d));
  checkCudaErrors(cudaFree(sigma_d)); 
  checkCudaErrors(cudaFree(S_d));
  checkCudaErrors(cudaFree(bc_d)); 
  checkCudaErrors(cudaFree(c));  
  checkCudaErrors(cudaEventDestroy(start));
  checkCudaErrors(cudaEventDestroy(stop));

  return 0;
}//end bfs_gpu_ug_csc_sc


////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
/* 
 * if d = 1, initialize f(r) and sigma(r),
 * compute the gpu-based parallel sparse matrix-vector multiplication    
 * for sparse matrices in the CSC format, representing unweighted 
 * graphs. 
 */
__global__
void spMVBFSscKernel (int *CP_d,int *I_d,int *ft_d,int *f_d,
			float *sigma_d,int d,int r,int n){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if(i < n){
    //if d =1, then initialize f(r) and sigma(r) 
    if (d == 1){
      f_d[r] = 1;
      sigma_d[r] = 1.0;
    }
    //compute SpMV for ft_d = A'f_d 
    ft_d[i] = 0;
    if (sigma_d[i] < 0.01){
      int k;
      int start = CP_d[i];
      int end = CP_d[i+1];
      int sum = 0;
      for (k = start;k < end; k++){
	sum += f_d[I_d[k]];
      }
      if ((float) sum > 0.9) {
	ft_d[i] = sum;
      }

      /*
      int m = 100;
      int ii = 100;
      if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,sum = %lf,ft_d[%d]=%d\n",
      threadIdx.x,blockIdx.x,i,sum,i,ft_d[i]);}*/
    }
  }
}//end spMVBFSscKernel

/******************************************************************************/
/*
 * assign vector ft_d to vector f_d,
 * check that the vector f_d  has at least one nonzero element
 * add the vector f to vector sigma.
 * computes the S vector. 
 */
__global__
void bfsFunctionsKernel (int *f_d,int *ft_d,float *sigma_d,int *S_d,int *c,
			 int n,int d){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < n){
    f_d[i] = 0;
    if (ft_d[i] > 0.9){
      *c = 1;
      f_d[i] = ft_d[i];
      sigma_d[i] += ft_d[i];
      S_d[i] = d;
    }

     /*int m = 1;
     int ii = 10;
     if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,d=%d,*c=%d,sigma_d[%d]=%lf,ft_d[%d]=%d,f_d[%d]=%d,S_d[d]=%d\n",
     threadIdx.x,blockIdx.x,i,d,*c,i,sigma_d[i],i,ft_d[i],i,f_d[i],i,S_d[i]);}*/
  }

}//end  bfsFunctionsKernel

/******************************************************************************/
/*
 * computes the delta_u vector  
*/
__global__
void deltaUKernel (int *S_d,float *delta_d,float *delta_u_d,
		    float *sigma_d,int n,int d){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < n){
    delta_u_d[i] = 0.0;
    if (S_d[i] == d && sigma_d[i] > 0.1){      
      delta_u_d[i] = (1.0 + delta_d[i])/sigma_d[i];
    
      /*int m = 0;
     int ii = 40;
     if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,d=%d,S_d[%d]=%d,sigma_d[%d]=%lf,delta_d[%d]=%lf,delta_u_d[%d]=%lf\n",
     threadIdx.x,blockIdx.x,i,d,i,S_d[i],i,sigma_d[i],i,delta_d[i],i,delta_u_d[i]);}*/
     }
    /*int m = 0;
     int ii = 40;
     if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,d=%d,S_d[%d]=%d,sigma_d[%d]=%lf,delta_d[%d]=%lf,delta_u_d[%d]=%lf\n",
     threadIdx.x,blockIdx.x,i,d,i,S_d[i],i,sigma_d[i],i,delta_d[i],i,delta_u_d[i]);}*/
  }
}//end  deltaUKernel

/******************************************************************************/
/*
 * computes the delta_ut vector with a SpMV multiplication operation.
*/
__global__
void spMVBCscKernel (int *CP_d,int *I_d,float *delta_ut_d,float *delta_u_d,
		     int n){
		    
  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < n){
    delta_ut_d[i] = 0.0;
    int k;
    int start = CP_d[i];
    int end = CP_d[i+1];
    float sum = 0.0;
    for (k = start;k < end; k++){
	sum += delta_u_d[I_d[k]];
    }
    if (sum > 0.0) delta_ut_d[i] = sum;
    
    
      int m = 0;
      int ii = 40;
      if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,sum = %lf,delta_ut_d[%d]=%lf\n",
      threadIdx.x,blockIdx.x,i,sum,i,delta_ut_d[i]);}
  }  
}//end spMVBCscKernel

/******************************************************************************/
/*
 * computes the delta vector  
*/
__global__
void deltaKernel (int *S_d,float *delta_d,float *delta_ut_d,
		  float *sigma_d,int n,int d){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < n  && delta_ut_d[i] > 0.0){
    if (S_d[i] == d-1 && sigma_d[i] > 0.9){      
      delta_d[i] += delta_ut_d[i]*sigma_d[i];
    }

     int m = 0;
     int ii = 40;
     if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,d=%d,sigma_d[%d]=%lf,delta_d[%d]=%lf,delta_ut_d[%d]=%lf\n",
     threadIdx.x,blockIdx.x,i,d,i,sigma_d[i],i,delta_d[i],i,delta_ut_d[i]);}
  }

}//end  deltaUKernel

/******************************************************************************/
/*
 * computes the bc vector  
*/
__global__
void bcKernel (float *bc_d,float *delta_d,int r,int n){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
   if (i < n && i != r && delta_d[i] > 0.0){
     bc_d[i] += delta_d[i];
     
     int m = 0;
     int ii = 10;
     if(blockIdx.x<m && i<ii){printf("threadIdx.x=%d,blockIdx.x=%d,i=%d,bc_d[%d]=%lf,delta_d[%d]=%lf\n",
     threadIdx.x,blockIdx.x,i,i,bc_d[i],i,delta_d[i]);}
  }

}//end  bcKernel
