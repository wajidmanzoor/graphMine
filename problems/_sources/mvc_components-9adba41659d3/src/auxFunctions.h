#ifndef AUX_H
#define AUX_H

#include "CSRGraphRep.h"
#include "config.h"

CSRGraph createCSRGraphFromFile(const char *filename);
CSRGraph shrinkCSRGraph(CSRGraph inputGraph, int* vertexDegrees, unsigned int* maxDegree);
unsigned int RemoveMaxApproximateMVC(CSRGraph graph);
unsigned int RemoveEdgeApproximateMVC(CSRGraph graph);
bool check_graph(CSRGraph graph);
void performChecks(CSRGraph graph, Config config);
void seqRootReduction(CSRGraph graph, unsigned int minimum, int* vertexDegrees, unsigned int* numDeletedVertices, unsigned int* maxDegree);
void setBlockDimAndUseGlobalMemory(Config &config, CSRGraph graph, int maxSharedMemPerSM, long long maxGlobalMemory, int maxNumThreadsPerSM, int maxThreadsPerBlock, int maxThreadsPerMultiProcessor, int numOfMultiProcessors, int minimum, bool useShort, size_t alreadyUsedSharedMemPerBlock);
void printResults(Config config, unsigned int maxApprox, unsigned int edgeApprox, double timeMax, double timeEdge, unsigned int minimum, double timeMin, unsigned int numblocks, unsigned int numBlocksPerSM, int numThreadsPerSM, unsigned int numVertices, unsigned int numEdges, unsigned int k_found);
void printResults(Config config, unsigned int maxApprox, unsigned int edgeApprox, double timeMax, double timeEdge, unsigned int minimum, double timeMin, unsigned int numVertices, unsigned int numEdges, unsigned int k_found);
void printNumBranchesInFile(Config config, unsigned int numBranches_h, unsigned int *numBranchesFreq_h, unsigned int numVertices);
#endif
