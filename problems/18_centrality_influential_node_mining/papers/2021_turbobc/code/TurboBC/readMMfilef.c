/*
 * This source code is distributed under the terms defined on 
 * in the file bcugcsccooc_main.c of this source distribution.
*/
/*
 *   Read Matrix Market program based on the ANSI C library for Matrix Market I/O
 *   Single precision (float data type)
 *  
 *   This program reads a Matrix Market format file for sparse adjacency matrices 
 *   representing weighted or unweighted graphs,and to compute the in-degree and 
 *   out-degree vectors of the corresponding graph.   
 *
 *   NOTES:
 *
 *   1) Matrix Market files are always 1-based, i.e. the index of the first
 *      element of a matrix is (1,1), not (0,0) as in C.  ADJUST THESE
 *      OFFSETS ACCORDINGLY offsets accordingly when reading and writing 
 *      to files.
 *
 *   2) ANSI C requires one to use the "l" format modifier when reading
 *      double precision floating point numbers in scanf() and
 *      its variants.  For example, use "%lf", "%lg", or "%le"
 *      when reading doubles, otherwise errors will occur.
*/

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "readMMfilef.h"

/* 
 * function to read  a Matrix Market file for a weighted graph and to 
 * compute the in-degree and out-degree vectors of the graph.
 * 
*/
int readMMfile_w (FILE *f,int *I,int *J,float *valC,int *out_degree,
		  int *in_degree,int nz){
 
    int i;

    for (i=0; i<nz; i++){
	if(fscanf(f, "%d %d %g\n", &I[i], &J[i], &valC[i]) == 3){
	   I[i]--;  /* adjust from 1-based to 0-based */
           J[i]--;
	}            
      out_degree[I[i]]++;
      in_degree[J[i]]++;  
    }
   
    return 0;
}// end readMMfile_w

/******************************************************************************/
/* 
 * function to read  a Matrix Market file for a unweighted graph and to 
 * compute the in-degree and out-degree vectors of the graph.
 * 
*/
int readMMfile_uw (FILE *f,int *I,int *J,int *out_degree,int *in_degree,int nz){

    int i;

    for (i=0; i<nz; i++){
	if(fscanf(f, "%d %d\n", &I[i], &J[i]) == 2){
	   I[i]--;  /* adjust from 1-based to 0-based */
           J[i]--;
	}            
      out_degree[I[i]]++;
      in_degree[J[i]]++;  
    }
   
    return 0;
}// end readMMfile_uw



