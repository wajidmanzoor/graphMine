/*
 * This source code is distributed under the terms defined  
 * in the file bcugcsccooc_main.c of this source distribution.
 */
/* 
 *  Betweenness centrality (BC) 
 *  Single precision (float data type) 
 *  TurboBC:bcug_seq.c
 * 
 *  This program computes a sequential BC for unweighted graphs
 *  represented by sparse matrices in the CSC format.
 *
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "timer.h"
#include "spmv_seq.h"
#include "bcug.h"

/******************************************************************************/
/* 
 * function to compute a sequential BC for unweighted graphs,represented by
 * sparse adjacency matrices in the CSC format.    
 *  
 */
int bc_seq_ug_csc (int *I,int *CP,int *S,float *sigma,float *bc,int nr,int rs,
		   int nz,int n){

  /* timing variables  */
  double initial_t;
  double incr_t;
  double sum_vs_t  = 0.0;
  double spmv_bfs_t = 0.0;
  double assign_v_t = 0.0;
  double mult_vs_t = 0.0;
  double S_v_t = 0.0;
  double check_f_t = 0.0;
  double total_bfs_t = 0.0;
  double delta_u_t = 0.0;
  double delta_ut_t = 0.0;
  double delta_t = 0.0;
  double total_delta_t = 0.0;
  double bc_t = 0.0;

  int *f;
  int *f_t;
  float *delta;
  float *delta_u;
  float *delta_ut;
  int *S_t;
  float *sigma_t;
  S_t =  (int *) calloc(n,sizeof(*S_t));
  sigma_t =  (float *) calloc(n,sizeof(*sigma_t));
  
  int r;
  for (r = 0; r < nr ; r++){
    
    if (nr == 1) r = rs; 
    f =  (int *) calloc(n,sizeof(*f));
    f_t =  (int *) calloc(n,sizeof(*f_t));
    free(S_t);
    free(sigma_t);
    S_t =  (int *) calloc(n,sizeof(*S_t));
    sigma_t =  (float *) calloc(n,sizeof(*sigma_t));
    f[r] = 1;
    int d = 0;
    int c = 1;
    while (c) {
      d++;
      initial_t = get_time();
      sum_vs (sigma_t,f,n);
      incr_t = get_time()-initial_t;
      sum_vs_t += incr_t;

      initial_t = get_time();
      spmv_seq_ug_csc (f,I,CP,f_t,n);
      incr_t = get_time()-initial_t;
      spmv_bfs_t += incr_t;

      initial_t = get_time();
      assign_v(f,f_t,n);
      incr_t = get_time()-initial_t;
      assign_v_t += incr_t;

      initial_t = get_time();
      mult_vs (sigma_t,f,n);
      incr_t = get_time()-initial_t;
      mult_vs_t += incr_t;

      initial_t = get_time();
      S_v (S_t,f,n,d);
      incr_t = get_time()-initial_t;
      S_v_t += incr_t;

      initial_t = get_time();
      c = 0;
      check_f(&c,f,n);
      incr_t = get_time()-initial_t;
      check_f_t += incr_t;
    }
    if (nr==1) printf("\nbc_seq_ug_csc::BFS ok::d = %d,r = %d \n",d,r);
    free (f);
    free (f_t);
    delta =  (float *) calloc(n,sizeof(*delta));
    delta_u =  (float *) calloc(n,sizeof(*delta_u));
    delta_ut =  (float *) calloc(n,sizeof(*delta_ut));

    d = d-1;
    while (d >1) {

      initial_t = get_time();
      delta_u_v (S_t,delta,delta_u,sigma_t,n,d);
      incr_t = get_time()-initial_t;
      delta_u_t += incr_t;

      initial_t = get_time();
      spmv_delta_ut (delta_u,I,CP,delta_ut,n);
      incr_t = get_time()-initial_t;
      delta_ut_t += incr_t;

      initial_t = get_time();
      delta_v (S_t,delta,delta_ut,sigma_t,n,d);
      incr_t = get_time()-initial_t;
      delta_t += incr_t;

      d = d-1;
    }
    initial_t = get_time();
    bc_v (bc,delta,r,n);
    incr_t = get_time()-initial_t;
    bc_t += incr_t;
    free (delta);
    free (delta_u);
    free (delta_ut);
  }//end for loop
  printf("\nbc_seq_ug_csc::BC ok \n");

  assign_v (S,S_t,n);
  assign_fv (sigma,sigma_t,n);

  total_bfs_t =  sum_vs_t +  spmv_bfs_t + assign_v_t +  mult_vs_t + S_v_t + check_f_t;
  total_delta_t =  delta_u_t +  delta_ut_t + delta_t;
  int p_t = 1;
  if (p_t) {
    printf("bfs_seq_ug_csc::total times \n");
    printf("bfs_seq_ug_csc::f <-- f +sigma time = %lfs \n",sum_vs_t);
    printf("bfs_seq_ug_csc::f_t <-- A'f time = %lfs \n",spmv_bfs_t);
    printf("bfs_seq_ug_csc::f <-- f_t time = %lfs \n",assign_v_t);
    printf("bfs_seq_ug_csc::f <-- f*(-sigma) time = %lfs \n",mult_vs_t);
    printf("bfs_seq_ug_csc::S vector time = %lfs \n",S_v_t);
    printf("bfs_seq_ug_csc::c <-- check (f=0)) time = %lfs \n",check_f_t);
    printf("bfs_seq_ug_csc::total BFS time = %lfs \n",total_bfs_t);
    printf("bfs_seq_ug_csc:: delta_u vector time = %lfs \n",delta_u_t);
    printf("bfs_seq_ug_csc:: delta_ut vector time = %lfs \n",delta_ut_t);
    printf("bfs_seq_ug_csc:: delta vector time = %lfs \n",delta_t);
    printf("bfs_seq_ug_csc::total delta time = %lfs \n",total_delta_t);
    printf("bfs_seq_ug_csc::total BC time = %lfs \n",total_bfs_t+total_delta_t);
    printf("bfs_seq_ug_csc:: bc vector time = %lfs \n",bc_t);
    printf("\nbfs_seq_ug_csc::times per vertex \n");
    printf("bfs_seq_ug_csc::f <-- f +sigma time/vertex = %lfs \n",sum_vs_t/nr);
    printf("bfs_seq_ug_csc::f_t <-- A'f time/vertex = %lfs \n",spmv_bfs_t/nr);
    printf("bfs_seq_ug_csc::f <-- f_t time/vertex = %lfs \n",assign_v_t/nr);
    printf("bfs_seq_ug_csc::f <-- f*(-sigma) time/vertex = %lfs \n",mult_vs_t/nr);
    printf("bfs_seq_ug_csc::S vector time/vertex = %lfs \n",S_v_t);
    printf("bfs_seq_ug_csc::c <-- check (f=0)) time/vertex = %lfs \n",check_f_t/nr);
    printf("bfs_seq_ug_csc::total BFS time/vertex = %lfs \n",total_bfs_t/nr);
    printf("bfs_seq_ug_csc:: delta_u vector time/vertex = %lfs \n",delta_u_t/nr);
    printf("bfs_seq_ug_csc:: delta_ut vector time/vertex = %lfs \n",delta_ut_t/nr);
    printf("bfs_seq_ug_csc:: delta vector time/vertex = %lfs \n",delta_t/nr);
    printf("bfs_seq_ug_csc::total delta time/vertex = %lfs \n",total_delta_t/nr);
    printf("bfs_seq_ug_csc:: bc vector time/vertex = %lfs \n",bc_t/nr);
    printf("bfs_seq_ug_csc::total BC time/vertex = %lfs \n",(total_bfs_t+total_delta_t)/nr);
  }


  return 0;
}//end  bc_seq_ug_csc
