/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
 */
/* 
 *  Betweenness centrality (BC)  
 *  Single precision (float data type) 
 *  TurboBC:bcgpugcooc_sc.cu
 * 
 *  This program computes the GPU-based parallel BC
 *  (scalar) for unweighted graphs represented 
 *  by sparse adjacency matrices in the COOC format.
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
extern "C"{
                 #include "bcug.h"
}


/*************************prototype kernels*************************************/
__global__ void spMVBFSCoocScKernel (int *I_d,int *J_d,int *ft_d,int *f_d,
				     float *sigma_d,int d,int r,int nz);
/******************************************************************************/
__global__ void spMVBCoocScKernel (int *I_d,int *J_d,float *delta_ut_d,
				   float *delta_u_d,int nz);
/******************************************************************************/
__global__ void  bfsFunctCoocKernel (int *f_d,int *ft_d,float *sigma_d,int *S_d,
	   	 		     int *c,int n,int d);
/******************************************************************************/

/* 
 * function to compute a gpu-based parallel BC (scalar) for unweighted graphs 
 * represented by sparse adjacency matrices in COOC format. 
 *  
 */
int  bc_gpu_ug_cooc_sc (int *I_h,int *J_h,int *S_h,float *sigma_h,float *bc_h,
			int nr,int rs,int nz,int n,int repetition){
  float t_H_to_D_I;
  float t_H_to_D_J;
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
  int i,r,d,dimGrid,dimGridspmv;
  cudaEvent_t start, stop;
  cudaEventCreate(&start);
  cudaEventCreate(&stop);
  float *delta_d;
  float *delta_u_d;
  float *delta_ut_d;
  int *ft_d;
  int *f_d;

  /*Allocate device memory for the vector J_d */
  int *J_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&J_d),sizeof(*J_d)*nz));
  cudaEventRecord(stop);

  /*Copy host memory (J_h) to device memory (J_d)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(J_d,J_h,nz*sizeof(*J_d),cudaMemcpyHostToDevice));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_H_to_D_J,start,stop);

  /*Allocate device memory for the vector I_d */
  int *I_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&I_d),sizeof(*I_d)*nz));
  /*Copy host memory (I_h) to device memory (I_d)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(I_d,I_h,nz*sizeof(*I_d),cudaMemcpyHostToDevice));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_H_to_D_I,start,stop);

  /*Allocate device memory for the vector S_d. */
  int *S_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&S_d),sizeof(*S_d)*n));

  /*Allocate device memory for the vector sigma_d */
  float *sigma_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&sigma_d),sizeof(*sigma_d)*n));
  int *c;
  checkCudaErrors(cudaMallocManaged(reinterpret_cast<void **>(&c),sizeof(*c)));

  /*Allocate device memory for the vector bc_d and set bc_d to zero*/
  float *bc_d;
  checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&bc_d),sizeof(*bc_d)*n));
  checkCudaErrors(cudaMemset(bc_d,0.0,sizeof(*bc_d)*n));

  dimGrid = (n + THREADS_PER_BLOCK)/THREADS_PER_BLOCK;
  dimGridspmv = (nz + THREADS_PER_BLOCK)/THREADS_PER_BLOCK;
  /*computing BC */
  for (r=0; r<nr; r++){

    if (nr == 1) r = rs;
    /*Allocate device memory for the vector delta_d*/
    checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_d),sizeof(*delta_d)*n));

    /*computing BFS */
    for (i = 0; i<repetition; i++){

      /*Allocate device memory for the vector ft_d*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&ft_d),sizeof(*ft_d)*n));
      /*Allocate device memory for the vector f_d and set f_d to zero*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&f_d),sizeof(*f_d)*n));
      checkCudaErrors(cudaMemset(f_d,0,sizeof(*f_d)*n));
      checkCudaErrors(cudaMemset(sigma_d,0.0,sizeof(*sigma_d)*n));
      checkCudaErrors(cudaMemset(S_d,0,sizeof(*S_d)*n));

      *c = 1;
      d = 0;
      while (*c){
	d = d + 1;
	*c = 0;
	cudaEventRecord(start);
	checkCudaErrors(cudaMemset(ft_d,0,sizeof(*ft_d)*n));
	spMVBFSCoocScKernel <<<dimGridspmv,THREADS_PER_BLOCK>>> (I_d,J_d,ft_d,f_d,sigma_d,d,r,nz);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_bfs_spmv,start,stop);
	t_bfs_spmv_t += t_bfs_spmv;

	cudaEventRecord(start);
	bfsFunctCoocKernel <<<dimGrid,THREADS_PER_BLOCK>>> (f_d,ft_d,sigma_d,S_d,c,n,d);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_bfsfunctions,start,stop);
	t_bfsfunctions_t += t_bfsfunctions;
	
	t_bfs_sum += t_bfs_spmv + t_bfsfunctions;
      }

      /*freeing and allocating memory for BC while loop  */
      cudaEventRecord(start);
      //free memory of f_d and ft_d vectors
      checkCudaErrors(cudaFree(f_d));
      checkCudaErrors(cudaFree(ft_d));
      /*set delta_d to zero*/
      checkCudaErrors(cudaMemset(delta_d,0.0,sizeof(*delta_d)*n));
      /*Allocate device memory for the vector delta_u_d*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_u_d),sizeof(*delta_u_d)*n));
      /*Allocate device memory for the vector delta_ut_d*/
      checkCudaErrors(cudaMalloc(reinterpret_cast<void **>(&delta_ut_d),sizeof(*delta_ut_d)*n));
      cudaEventRecord(stop);
      cudaEventSynchronize(stop);
      cudaEventElapsedTime(&t_allocate,start,stop);
      t_allocate_t += t_allocate;

      /*computing delta with while loop  */
      d = d-1;
      while (d > 1){

	cudaEventRecord(start);
	deltaUKernel <<<dimGrid,THREADS_PER_BLOCK>>> (S_d,delta_d,delta_u_d,sigma_d,n,d);
	cudaEventRecord(stop);
	cudaEventSynchronize(stop);
	cudaEventElapsedTime(&t_delta_u,start,stop);
	t_delta_u_t += t_delta_u;

	cudaEventRecord(start);
	checkCudaErrors(cudaMemset(delta_ut_d,0.0,sizeof(*delta_ut_d)*n));
	spMVBCoocScKernel <<<dimGridspmv,THREADS_PER_BLOCK>>> (I_d,J_d,delta_ut_d,delta_u_d,nz);
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
      }
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
  t_bfs_avg = t_bfs_sum/repetition;
  t_delta_avg = t_delta_sum/repetition;
  total_BC_t =  t_bfs_avg + t_delta_avg + t_allocate/repetition + t_bc;

  /*Copy device memory (sigma_d) to host memory (sigma_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(sigma_h,sigma_d, n*sizeof(*sigma_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_sigma,start,stop);

  /*Copy device memory (S_d) to host memory (S_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(S_h,S_d, n*sizeof(*S_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_S,start,stop);

  /*Copy device memory (bc_d) to host memory (bc_h)*/
  cudaEventRecord(start);
  checkCudaErrors(cudaMemcpy(bc_h,bc_d, n*sizeof(*bc_d),cudaMemcpyDeviceToHost));
  cudaEventRecord(stop);
  cudaEventSynchronize(stop);
  cudaEventElapsedTime(&t_D_to_H_bc,start,stop);

  int print_t = 1;
  if (print_t){
    printf("\nbcgpugcooc_sc::bc_gpu_ug_cooc_sc:time J_h to J_d = %lfms \n",t_H_to_D_J);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time I_h to I_d = %lfms \n",t_H_to_D_I);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time f <-- A'f  = %lfms \n",t_bfs_spmv_t/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time time bfs functions  = %lfms \n", t_bfsfunctions_t/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:average time BFS  = %lfms \n",t_bfs_avg);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:average time BFS/vertex  = %lfms \n",t_bfs_avg/nr);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time to allocate memory for BC stage = %lfms \n",t_allocate/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time delta_u <-- (1+delta)/sigma  = %lfms \n",t_delta_u_t/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time delta_ut <-- A'delta_u  = %lfms \n",t_bc_spmv_t/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time delta <-- delta + delta_ut*sigma  = %lfms \n",t_delta_t/repetition);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:average time delta   = %lfms \n",t_delta_avg);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:average time delta/vertex   = %lfms \n",t_delta_avg/nr);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time bc <-- bc +delta/2 = %lfms \n",t_bc);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:total BC time = %lfms \n",total_BC_t);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:total BC time/vertex = %lfms \n",total_BC_t/nr);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time sigma_d to sigma_h = %lfms \n",t_D_to_H_sigma);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time S_d to S_h = %lfms \n",t_D_to_H_S);
    printf("bcgpugcooc_sc::bc_gpu_ug_cooc_sc:time bc_d to bc_h = %lfms \n",t_D_to_H_bc);
  }

  /*cleanup memory*/
  checkCudaErrors(cudaFree(I_d));
  checkCudaErrors(cudaFree(J_d));
  checkCudaErrors(cudaFree(sigma_d));
  checkCudaErrors(cudaFree(S_d));
  checkCudaErrors(cudaFree(bc_d));
  checkCudaErrors(cudaFree(c));
  checkCudaErrors(cudaEventDestroy(start));
  checkCudaErrors(cudaEventDestroy(stop));

  return 0;
}//end bfs_gpu_ug_cooc_sc


////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
/* 
 * if d = 1, initialize f(r) and sigma(r),
 * compute the gpu-based parallel sparse matrix-vector multiplication    
 * for sparse matrices in the CSC format, representing unweighted 
 * graphs. 
 */
__global__
void spMVBFSCoocScKernel (int *I_d,int *J_d,int *ft_d,int *f_d,
			  float *sigma_d,int d,int r,int nz){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if(i < nz){
    //if d = 1, initialize f(r) and sigma(r)
    if (d == 1){
      f_d[r] = 1;
      sigma_d[r] = 1.0;
    }
    //compute spmv
    if (f_d[I_d[i]] != 0) {
      int f = f_d[I_d[i]];
      atomicAdd(&ft_d[J_d[i]],f);
    }
  }
}//end spMVBFSCoocscKernel

/******************************************************************************/
/*
 * computes the delta_ut vector with a SpMV multiplication operation.
 */
__global__
void spMVBCoocScKernel (int *I_d,int *J_d,float *delta_ut_d,
			float *delta_u_d,int nz){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < nz){
    //compute spmv
    if (delta_u_d[I_d[i]] != 0) {
      float delta = delta_u_d[I_d[i]];
      atomicAdd(&delta_ut_d[J_d[i]],delta);
    }
  }
}//end spMVBCoocscKernel

/******************************************************************************/
/*
 * if sigma(i) == 0, assign vector ft_d to vector f_d,
 * check that the vector f_d  has at least one nonzero element
 * add the vector f to vector sigma.
 */
__global__
void bfsFunctCoocKernel (int *f_d,int *ft_d,float *sigma_d,int *S_d,
     			 int *c,int n,int d){

  int i = threadIdx.x + blockIdx.x * blockDim.x;
  if (i < n){
    f_d[i] = 0;
    if (sigma_d[i] < 0.01) f_d[i] = ft_d[i];
    if (f_d[i] > 0.9){
      *c = 1;
      sigma_d[i] += f_d[i];
      S_d[i] = d;
    }
  }

}//end  bfsFunctCoocKernel
