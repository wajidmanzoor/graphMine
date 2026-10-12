#ifndef HELPERFUNC_H
#define HELPERFUNC_H

#include "CSRGraphRep.h"
void generate_graph(CSRGraph &graph);
void generate_data(CSRGraph &graph, int *vertexDegrees, unsigned int numDeletedVertices, unsigned int minimum, unsigned int left, unsigned int right, unsigned int label);
void close_json_file();
unsigned int strong_branch(CSRGraph &graph,  int *vertexDegrees, unsigned int numDeletedVertices, unsigned int minimum, unsigned int left, unsigned int right);
void reduce_and_divide(CSRGraph &graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int minimum, unsigned int left, unsigned int right);
long long int squareSequential(int num);
int *deleteVertex(CSRGraph &graph, unsigned int vertex, int *vertexDegrees, unsigned int *numDeletedVertices);
bool leafReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right);
bool highDegreeReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, int minimum,unsigned int left, unsigned int right);
bool triangleReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right);
bool cliqueReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right);
bool cycleReductionRule(CSRGraph graph, int *vertexDegrees, unsigned int *numDeletedVertices, unsigned int left, unsigned int right);
#endif