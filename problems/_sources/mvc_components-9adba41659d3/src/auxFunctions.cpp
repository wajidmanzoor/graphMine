#include "auxFunctions.h"
#include "helperFunctions.h"
#include "crown.hpp"
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <cstdlib>
#include <assert.h>
#include <time.h>
#include <cstring>
#include <sys/stat.h>

#define MIN(a, b) (((a) < (b)) ? (a) : (b))
#define MAX(a, b) (((a) > (b)) ? (a) : (b))

int comp(const void *elem1, const void *elem2)
{
	int f = *((int *)elem1);
	int s = *((int *)elem2);
	if (f > s)
		return 1;
	if (f < s)
		return -1;
	return 0;
}

bool auxBinarySearch(unsigned int *arr, int l, int r, unsigned int x)
{
	while (l <= r)
	{
		int m = l + (r - l) / 2;

		if (arr[m] == x)
			return true;

		if (arr[m] < x)
			l = m + 1;

		else
			r = m - 1;
	}

	return false;
}

bool leafReductionRule(CSRGraph &graph, unsigned int &minimum)
{
	bool hasChanged;
	do
	{
		hasChanged = false;
		for (unsigned int i = 0; i < graph.vertexNum; ++i)
		{
			if (graph.degree[i] == 1)
			{
				hasChanged = true;
				for (unsigned int j = graph.srcPtr[i]; j < graph.srcPtr[i + 1]; ++j)
				{
					if (graph.degree[graph.dst[j]] != -1)
					{
						unsigned int neighbor = graph.dst[j];
						graph.deleteVertex(neighbor);
						++minimum;
					}
				}
			}
		}
	} while (hasChanged);

	return hasChanged;
}

bool triangleReductionRule(CSRGraph &graph, unsigned int &minimum)
{
	bool hasChanged;
	do
	{
		hasChanged = false;
		for (unsigned int i = 0; i < graph.vertexNum; ++i)
		{
			if (graph.degree[i] == 2)
			{

				unsigned int neighbor1, neighbor2;
				bool foundNeighbor1 = false, keepNeighbors = false;
				for (unsigned int edge = graph.srcPtr[i]; edge < graph.srcPtr[i + 1]; ++edge)
				{
					unsigned int neighbor = graph.dst[edge];
					int neighborDegree = graph.degree[neighbor];
					if (neighborDegree > 0)
					{
						if (neighborDegree == 1 || neighborDegree == 2 && neighbor < i)
						{
							keepNeighbors = true;
							break;
						}
						else if (!foundNeighbor1)
						{
							foundNeighbor1 = true;
							neighbor1 = neighbor;
						}
						else
						{
							neighbor2 = neighbor;
							break;
						}
					}
				}

				if (!keepNeighbors)
				{
					bool found = auxBinarySearch(graph.dst, graph.srcPtr[neighbor2], graph.srcPtr[neighbor2 + 1] - 1, neighbor1);

					if (found)
					{
						hasChanged = true;
						// Triangle Found
						graph.deleteVertex(neighbor1);
						graph.deleteVertex(neighbor2);
						minimum += 2;
						break;
					}
				}
			}
		}
	} while (hasChanged);

	return hasChanged;
}

CSRGraph createCSRGraphFromFile(const char *filename)
{

	CSRGraph graph;
	unsigned int vertexNum;
	unsigned int edgeNum;

	FILE *fp;
	fp = fopen(filename, "r");

	int scan = fscanf(fp, "%u%u", &vertexNum, &edgeNum);

	graph.create(vertexNum, edgeNum);

	unsigned int **edgeList = (unsigned int **)malloc(sizeof(unsigned int *) * 2);
	edgeList[0] = (unsigned int *)malloc(sizeof(unsigned int) * edgeNum);
	edgeList[1] = (unsigned int *)malloc(sizeof(unsigned int) * edgeNum);

	for (unsigned int i = 0; i < edgeNum; i++)
	{
		unsigned int v0, v1;
		scan = fscanf(fp, "%u%u", &v0, &v1);
		edgeList[0][i] = v0;
		edgeList[1][i] = v1;
	}

	fclose(fp);

	// Gets the degrees of vertices
	for (unsigned int i = 0; i < edgeNum; i++)
	{
		assert(edgeList[0][i] < vertexNum);
		graph.degree[edgeList[0][i]]++;
		if (edgeList[1][i] >= vertexNum)
		{
			printf("\n%d\n", edgeList[1][i]);
		}
		assert(edgeList[1][i] < vertexNum);
		graph.degree[edgeList[1][i]]++;
	}
	// Fill srcPtration array
	unsigned int nextIndex = 0;
	unsigned int *srcPtr2 = (unsigned int *)malloc(sizeof(unsigned int) * vertexNum);
	for (int i = 0; i < vertexNum; i++)
	{
		graph.srcPtr[i] = nextIndex;
		srcPtr2[i] = nextIndex;
		nextIndex += graph.degree[i];
	}
	graph.srcPtr[vertexNum] = edgeNum * 2;
	// fill Graph Array
	for (unsigned int i = 0; i < edgeNum; i++)
	{
		assert(edgeList[0][i] < vertexNum);
		assert(srcPtr2[edgeList[0][i]] < 2 * edgeNum);
		graph.dst[srcPtr2[edgeList[0][i]]] = edgeList[1][i];
		srcPtr2[edgeList[0][i]]++;
		assert(edgeList[1][i] < vertexNum);
		assert(srcPtr2[edgeList[1][i]] < 2 * edgeNum);
		graph.dst[srcPtr2[edgeList[1][i]]] = edgeList[0][i];
		srcPtr2[edgeList[1][i]]++;
	}

	free(srcPtr2);
	free(edgeList[0]);
	edgeList[0] = NULL;
	free(edgeList[1]);
	edgeList[1] = NULL;
	free(edgeList);
	edgeList = NULL;

	for (unsigned int vertex = 0; vertex < graph.vertexNum; ++vertex)
	{
		qsort(&graph.dst[graph.srcPtr[vertex]], graph.degree[vertex], sizeof(int), comp);
	}

	return graph;
}

CSRGraph shrinkCSRGraph(CSRGraph inputGraph, int* vertexDegrees, unsigned int* maxDegree)
{
    int *vertexMap = (int*)malloc(inputGraph.vertexNum*sizeof(int));
    unsigned int newVertexNum = 0;
    for (unsigned int i=0; i<inputGraph.vertexNum; ++i) {
        if (vertexDegrees[i] > 0) {
            vertexMap[i] = newVertexNum++;
            *maxDegree = (vertexDegrees[i]>*maxDegree)?vertexDegrees[i]:*maxDegree;
        } else {
            vertexMap[i] = -1;
        }
    }
    unsigned int newEdgeNum = 0;
    for (unsigned int vertex = 0; vertex<inputGraph.vertexNum; ++vertex) {
        if (vertexMap[vertex] != -1) {
            for (unsigned int edge=inputGraph.srcPtr[vertex]; edge<inputGraph.srcPtr[vertex+1]; ++edge) {
                unsigned int neighbor = inputGraph.dst[edge];
                if (vertexMap[neighbor] != -1) {
                    ++newEdgeNum;
                }
            }
        }
    }
    newEdgeNum /= 2;

    CSRGraph newGraph;
    newGraph.create(newVertexNum, newEdgeNum);

    for (unsigned int vertex = 0; vertex<inputGraph.vertexNum; ++vertex) {
        if (vertexMap[vertex] != -1) {
            for (unsigned int edge=inputGraph.srcPtr[vertex]; edge<inputGraph.srcPtr[vertex+1]; ++edge) {
                unsigned int neighbor = inputGraph.dst[edge];
                if (vertexMap[neighbor] != -1) {
                    ++newGraph.degree[vertexMap[vertex]];
                }
            }
        }
    }

    newGraph.srcPtr[0] = 0;
    for (unsigned int i=0; i<newVertexNum; ++i) {
        newGraph.srcPtr[i+1] = newGraph.srcPtr[i] + newGraph.degree[i];
    }
    assert(newGraph.srcPtr[newVertexNum] ==  2*newEdgeNum);

    unsigned int dstIndex = 0;
    for (unsigned int vertex=0; vertex<inputGraph.vertexNum; ++vertex) {
        if (vertexMap[vertex] != -1) {
            for (unsigned int i=inputGraph.srcPtr[vertex]; i<inputGraph.srcPtr[vertex+1]; ++i) {
                unsigned int neighbor = inputGraph.dst[i];
                if (vertexMap[neighbor] != -1) {
                    unsigned int newNeighbor = vertexMap[neighbor];
                    newGraph.dst[dstIndex++] = newNeighbor;
                }
            }
        }
    }
    assert(dstIndex == 2*newEdgeNum);
    
    // For Debugging Purposes
    /*unsigned int index = 0;
    for (int i = 0; i<inputGraph.vertexNum; ++i) {
        if (vertexDegrees[i]>0) {
            assert(vertexDegrees[i] == newGraph.degree[index++]);
        }
    }
    assert(index == newVertexNum);*/
    free(vertexMap);
    inputGraph.del();

    return newGraph;
}

unsigned int RemoveMaxApproximateMVC(CSRGraph graph)
{
    
	CSRGraph approxGraph;
	approxGraph.copy(graph);
    
	unsigned int minimum = 0;
	bool hasEdges = true;
	while (hasEdges)
	{
		bool leafHasChanged = false, triangleHasChanged = false;
		unsigned int iterationCounter = 0;

		do
		{
			leafHasChanged = leafReductionRule(approxGraph, minimum);
			if (iterationCounter == 0 || leafHasChanged)
			{
				triangleHasChanged = triangleReductionRule(approxGraph, minimum);
			}
			++iterationCounter;
		} while (triangleHasChanged);

		unsigned int maxV;
		int maxD = 0;
		for (unsigned int i = 0; i < approxGraph.vertexNum; i++)
		{
			if (approxGraph.degree[i] > maxD)
			{
				maxV = i;
				maxD = approxGraph.degree[i];
			}
		}
		if (maxD == 0)
			hasEdges = false;
		else
		{
			approxGraph.deleteVertex(maxV);
			++minimum;
		}
	}
	approxGraph.del();
    
	return minimum;
}

void seqRootReduction(CSRGraph graph, unsigned int minimum, int* vertexDegrees, unsigned int* numDeletedVertices, unsigned int* maxDegree) {

    for (unsigned int i = 0; i < graph.vertexNum; i++) {
        vertexDegrees[i] = graph.degree[i];
        *maxDegree = (graph.degree[i]>*maxDegree)?graph.degree[i]:*maxDegree;
    }
   
    bool leafHasChanged = false, crownHasChanged = false, highDegreeHasChanged = false, triangleHasChanged = false, cliqueHasChanged = false, cycleHasChanged = false;
    unsigned int iterationCounter = 0;
    do {
        do
        {
            leafHasChanged = leafReductionRule(graph, vertexDegrees, numDeletedVertices, 0, graph.vertexNum - 1);
            if (iterationCounter==0 || leafHasChanged || triangleHasChanged || highDegreeHasChanged) {
                crownHasChanged = crown_rule(graph, vertexDegrees, numDeletedVertices);
            } else {
                crownHasChanged = false;
            }
            if (iterationCounter==0 || leafHasChanged || crownHasChanged || highDegreeHasChanged) {
                triangleHasChanged = triangleReductionRule(graph, vertexDegrees, numDeletedVertices, 0, graph.vertexNum - 1);
            } else {
                triangleHasChanged = false;
            }
            if (iterationCounter==0 || leafHasChanged || crownHasChanged || triangleHasChanged) {
                highDegreeHasChanged = highDegreeReductionRule(graph, vertexDegrees, numDeletedVertices, minimum, 0, graph.vertexNum - 1);
            } else {
                highDegreeHasChanged = false;
            }
            ++iterationCounter;
        } while (crownHasChanged || triangleHasChanged || highDegreeHasChanged);

        cliqueHasChanged = cliqueReductionRule(graph, vertexDegrees, numDeletedVertices, 0, graph.vertexNum - 1);
        cycleHasChanged = cycleReductionRule(graph, vertexDegrees, numDeletedVertices, 0, graph.vertexNum - 1);
        if (cliqueHasChanged || cycleHasChanged) {
            highDegreeHasChanged = highDegreeReductionRule(graph, vertexDegrees, numDeletedVertices, minimum, 0, graph.vertexNum - 1);
            crownHasChanged = crown_rule(graph, vertexDegrees, numDeletedVertices);
        }

    } while(highDegreeHasChanged || crownHasChanged);
}

unsigned int getRandom(int lower, int upper)
{
	srand(time(0));
	unsigned int num = (rand() % (upper - lower + 1)) + lower;
	return num;
}

unsigned int RemoveEdgeApproximateMVC(CSRGraph graph)
{

	CSRGraph approxGraph;
	approxGraph.copy(graph);

	unsigned int minimum = 0;
	unsigned int numRemainingEdges = approxGraph.edgeNum;

	for (unsigned int vertex = 0; vertex < approxGraph.vertexNum && numRemainingEdges > 0; vertex++)
	{
		bool leafHasChanged = false, triangleHasChanged = false;
		unsigned int iterationCounter = 0;

		do
		{
			leafHasChanged = leafReductionRule(approxGraph, minimum);
			if (iterationCounter == 0 || leafHasChanged)
			{
				triangleHasChanged = triangleReductionRule(approxGraph, minimum);
			}
			++iterationCounter;
		} while (triangleHasChanged);

		if (approxGraph.degree[vertex] > 0)
		{

			unsigned int randomEdge = getRandom(approxGraph.srcPtr[vertex], approxGraph.srcPtr[vertex] + approxGraph.degree[vertex] - 1);

			numRemainingEdges -= approxGraph.degree[vertex];
			numRemainingEdges -= approxGraph.degree[approxGraph.dst[randomEdge]];
			++numRemainingEdges;
			approxGraph.deleteVertex(vertex);
			approxGraph.deleteVertex(approxGraph.dst[randomEdge]);
			minimum += 2;
		}
	}

	approxGraph.del();
    
	return minimum;
}

bool check_graph(CSRGraph graph) {
    
    // Loop through vertices
    for (unsigned int vertex=0; vertex<graph.vertexNum; ++vertex) {

        // Allocate memory for a single row
        unsigned int* row = (unsigned int*)malloc(sizeof(unsigned int) * graph.vertexNum);

        // Initialize the row
        for (unsigned int i=0; i<graph.vertexNum; ++i) {
            row[i] = 0;
        }

        // Check duplicate edges for the current vertex
        for (unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
            unsigned int neighbor = graph.dst[edge];
            if (row[neighbor] == 0) {
                row[neighbor] = 1;
            } else {
                free(row);
                return false;
            }
        }

        // Check for self-loop
        if (row[vertex] != 0) {
            free(row);
            return false;
        }

        free(row);
    }

    return true;
}

void performChecks(CSRGraph graph, Config config)
{
	assert(check_graph(graph) == true);
	assert(ceil(log2((float)config.blockDim)) == floor(log2((float)config.blockDim)));
    if (config.globalListSize>-1) {
        assert(ceil(log2((float)config.globalListSize)) == floor(log2((float)config.globalListSize)));
    }
}

void setBlockDimAndUseGlobalMemory(Config &config, CSRGraph graph, int maxSharedMemPerSM, long long maxGlobalMemory, int maxNumThreadsPerSM, int maxThreadsPerBlock, int maxThreadsPerMultiProcessor, int numOfMultiProcessors, int minimum, bool useShort, size_t alreadyUsedSharedMemPerBlock)
{
    int thresholdBlocksNum = maxNumThreadsPerSM*numOfMultiProcessors/maxThreadsPerBlock;
    if (config.numBlocks) {
        if ((maxNumThreadsPerSM*numOfMultiProcessors/64) < config.numBlocks) {
            fprintf(stderr, "\nPlease choose numBlocks less than or equal to : %d\n", maxNumThreadsPerSM*numOfMultiProcessors/64);
            exit(0);
        }
    }
    if (config.blockDim) {
        if (config.blockDim<64 || config.blockDim>maxThreadsPerBlock) {
             fprintf(stderr, "\nPlease choose an appropriate blockDim between : 64 and %d\n", maxThreadsPerBlock);
            exit(0);
        }
    }
    
	long long numBlocks = (maxNumThreadsPerSM / maxThreadsPerBlock) * numOfMultiProcessors;

	if (config.numBlocks)
	{
        if (config.blockDim) {
            unsigned int maxNumBlocksForThisDim = (maxNumThreadsPerSM/config.blockDim)*numOfMultiProcessors;
            if (maxNumBlocksForThisDim<config.numBlocks || (maxNumBlocksForThisDim/config.numBlocks)>=2) {
                fprintf(stderr, "\nPlease choose an appropriate combination for numBlocks and blockDim.\n");
                exit(0);
            }
        }
		numBlocks = (long long)config.numBlocks;
	}
    
    unsigned int sizeofINT_OR_SHORT = sizeof(int);
    if(useShort) {
        sizeofINT_OR_SHORT = sizeof(short);
    }

	long long minStackSize;
	if (config.blockDim && !config.numBlocks)
	{
		numBlocks = (maxNumThreadsPerSM / config.blockDim) * numOfMultiProcessors;
		minStackSize = (
            (long long)(minimum+1)*(
                (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                + (long long)(2)*(long long)sizeof(int)
                + (long long)sizeof(bool)
            )
        )*(long long)numBlocks;
	}
	else
	{
		minStackSize = (
            (long long)(minimum+1)*(
                (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                + (long long)(2)*(long long)sizeof(int)
                + (long long)sizeof(bool)
            )
        )*(long long)numBlocks;
	}

	long long globalListSize;
    long long totalCompArraySize;
	if (config.version == HYBRID)
	{
        if (config.globalListSize>-1) {
            globalListSize = (long long)config.globalListSize * (long long)(graph.vertexNum + 2) * (long long)sizeofINT_OR_SHORT;
        } else {
            globalListSize = (long long)524288 * (long long)(graph.vertexNum + 2) * (long long)sizeofINT_OR_SHORT;
        }
        if (config.compArraySize!=0 && config.compArraySize<3) {
            fprintf(stderr, "\nPlease choose a compArraySize larger than : 2\n");
            exit(0);
        } else if (config.compArraySize>1000000000) {
            fprintf(stderr, "\nPlease choose a compArraySize smaller than : 1,000,000,000\n");
            exit(0);
        }
        totalCompArraySize = (long long)config.compArraySize*(long long)(3*sizeof(int));
	}
	else
	{
		globalListSize = 0;
        totalCompArraySize = 0;
	}

    // Using compArraySize of 200,000,000 for the default reported case (when config.reduceInduce==0)
    if (config.reduceInduce==0) {
        if(config.compArraySize==700000000) {
            config.compArraySize = 200000000;
            totalCompArraySize = (long long)config.compArraySize*(long long)(3*sizeof(int));
        }
    }

	long long consumedGlobalMem = (long long)(1024 * 1024 * 1024 * 2.5) + globalListSize + totalCompArraySize;
	long long availableGlobalMem = maxGlobalMemory - consumedGlobalMem;

	long long maxNumBlocksGlobalMem =
        MIN((long long)availableGlobalMem / (
            (long long)(minimum+1)*(
                (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                + (long long)(2)*(long long)sizeof(int)
                + (long long)sizeof(bool)
            )
        ), maxNumThreadsPerSM * numOfMultiProcessors / 64);

	if ((long long)(consumedGlobalMem + minStackSize) > maxGlobalMemory && maxNumBlocksGlobalMem<1)
	{
        if (config.version == STACK_ONLY) {
            fprintf(stderr, "\nCan't fit in current GPU memory!\n");
            exit(0);
        } else if (config.globalListSize>-1) {
            if (config.globalListSize>0) {
                fprintf(stderr, "\nPlease choose a WorkList Size smaller than : %d \n", config.globalListSize);
            } else if (config.compArraySize>0) {
                fprintf(stderr, "\nPlease choose a compArray Size smaller than : %lld \n", config.compArraySize);
            } else {
                fprintf(stderr, "\nCan't fit in current GPU memory!\n");
            }
            exit(0);
        }
        if(config.reduceInduce==0) {
            config.globalListSize= 524288;
            while (config.globalListSize>0) {
                config.globalListSize = config.globalListSize/2;
                globalListSize = (long long)config.globalListSize * (long long)(graph.vertexNum + 2) * (long long)sizeofINT_OR_SHORT;
                consumedGlobalMem = (long long)(1024 * 1024 * 1024 * 2.5) + globalListSize + totalCompArraySize;
                availableGlobalMem = maxGlobalMemory - consumedGlobalMem;
                maxNumBlocksGlobalMem =
                    MIN((long long)availableGlobalMem / (
                        (long long)(minimum+1)*(
                            (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                            + (long long)(2)*(long long)sizeof(int)
                            + (long long)sizeof(bool)
                        )
                    ), maxNumThreadsPerSM * numOfMultiProcessors / 64);
                if (maxNumBlocksGlobalMem>=1) {
                    break;
                }
                if (config.globalListSize==0) {
                    if (config.compArraySize>0) {
                        fprintf(stderr, "\nPlease choose a compArray Size smaller than : %lld \n", config.compArraySize);
                    } else {
                        fprintf(stderr, "\nCan't fit in current GPU memory!\n");
                    }
                    exit(0);
                }
            }
        }
	}
    
    if ((long long)(consumedGlobalMem + minStackSize) > maxGlobalMemory)
	{
        if (config.version == STACK_ONLY || config.globalListSize>-1 || config.reduceInduce==0) {
            config.numBlocks = maxNumBlocksGlobalMem;
        } else {
            
            bool customizedVersion = false;

            if (config.numBlocks) {
                // reduces worklist till numBlocks fits
                long long tempAvailableGlobalMem;
                long long tempMaxNumBlocksGlobalMem;
                long long tempGlobalListSize;
                config.globalListSize = 524288;
                while (maxNumBlocksGlobalMem<config.numBlocks && config.globalListSize>1) {
                    tempGlobalListSize = globalListSize/2;
                    tempAvailableGlobalMem = availableGlobalMem + tempGlobalListSize;
                    tempMaxNumBlocksGlobalMem = (long long)tempAvailableGlobalMem /(
                                                    (long long)(minimum+1)*(
                                                        (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                                                        + (long long)(2)*(long long)sizeof(int)
                                                        + (long long)sizeof(bool)
                                                    )
                                                );
                    availableGlobalMem = tempAvailableGlobalMem;
                    maxNumBlocksGlobalMem = tempMaxNumBlocksGlobalMem;
                    globalListSize = tempGlobalListSize;
                    config.globalListSize = config.globalListSize/2;
                }

                if (maxNumBlocksGlobalMem<1) {
                    if (config.compArraySize>0) {
                        fprintf(stderr, "\nPlease choose a compArray Size smaller than : %lld \n", config.compArraySize);
                    } else {
                        fprintf(stderr, "\nCan't fit in current GPU memory!\n");
                    }
                    exit(0);
                } else if (maxNumBlocksGlobalMem<config.numBlocks) {
                    config.numBlocks = maxNumBlocksGlobalMem;
                }
                customizedVersion = true;

            } else if (config.blockDim) {
                long long tempAvailableGlobalMem;
                long long tempMaxNumBlocksGlobalMem;
                long long tempGlobalListSize;
                config.globalListSize = 524288;
                while (maxNumBlocksGlobalMem<numBlocks && config.globalListSize>1) {
                    tempGlobalListSize = globalListSize/2;
                    tempAvailableGlobalMem = availableGlobalMem + tempGlobalListSize;
                    tempMaxNumBlocksGlobalMem = (long long)tempAvailableGlobalMem /(
                                                    (long long)(minimum+1)*(
                                                        (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                                                        + (long long)(2)*(long long)sizeof(int)
                                                        + (long long)sizeof(bool)
                                                    )
                                                );
                    availableGlobalMem = tempAvailableGlobalMem;
                    maxNumBlocksGlobalMem = tempMaxNumBlocksGlobalMem;
                    globalListSize = tempGlobalListSize;
                    config.globalListSize = config.globalListSize/2;
                }

                if (maxNumBlocksGlobalMem<1) {
                    if (config.compArraySize>0) {
                        fprintf(stderr, "\nPlease choose a compArray Size smaller than : %lld \n", config.compArraySize);
                    } else {
                        fprintf(stderr, "\nCan't fit in current GPU memory!\n");
                    }
                    exit(0);
                } else if (maxNumBlocksGlobalMem<numBlocks) {
                    config.numBlocks = maxNumBlocksGlobalMem;
                }
                customizedVersion = true;
            }

            if (!customizedVersion) {
                long long tempAvailableGlobalMem;
                long long tempMaxNumBlocksGlobalMem;
                long long tempGlobalListSize;
                config.globalListSize = 524288;
                while (maxNumBlocksGlobalMem<thresholdBlocksNum && config.globalListSize>0) {
                    tempGlobalListSize = globalListSize/2;
                    tempAvailableGlobalMem = availableGlobalMem + tempGlobalListSize;
                    tempMaxNumBlocksGlobalMem = (long long)tempAvailableGlobalMem /(
                                                    (long long)(minimum+1)*(
                                                        (long long)(graph.vertexNum)*(long long)sizeofINT_OR_SHORT
                                                        + (long long)(2)*(long long)sizeof(int)
                                                        + (long long)sizeof(bool)
                                                    )
                                                );
                    if ((tempMaxNumBlocksGlobalMem<2)
                        || (tempMaxNumBlocksGlobalMem>maxNumBlocksGlobalMem+0.1*maxNumBlocksGlobalMem))
                    {
                        availableGlobalMem = tempAvailableGlobalMem;
                        maxNumBlocksGlobalMem = tempMaxNumBlocksGlobalMem;
                        globalListSize = tempGlobalListSize;
                        config.globalListSize = config.globalListSize/2;
                    } else {
                        break;
                    }
                }

                if (maxNumBlocksGlobalMem<1) {
                    if (config.compArraySize>0) {
                        fprintf(stderr, "\nPlease choose a compArray Size smaller than : %lld \n", config.compArraySize);
                    } else {
                        fprintf(stderr, "\nCan't fit in current GPU memory!\n");
                    }
                    exit(0);
                } else if (maxNumBlocksGlobalMem<thresholdBlocksNum) {
                    config.numBlocks = maxNumBlocksGlobalMem;
                }
            }
        }
	}
    
    if (config.globalListSize == -1) {
        config.globalListSize = 524288;
    }

    long long minBlockDimGlobalMem;
    minBlockDimGlobalMem = maxNumThreadsPerSM * numOfMultiProcessors / maxNumBlocksGlobalMem;
    minBlockDimGlobalMem = pow(2, floor(log2((double)minBlockDimGlobalMem)));
    long long minBlockDim = MIN(1024, minBlockDimGlobalMem);
    
    for (long long i = 64; i < 1024; i *= 2)
	{
		if (maxNumThreadsPerSM * numOfMultiProcessors / i <= maxNumBlocksGlobalMem)
		{
			minBlockDim = i;
			break;
		}
	}
    unsigned int maxNumBlocks = maxNumThreadsPerSM*numOfMultiProcessors / minBlockDim;
    if (maxNumBlocks>thresholdBlocksNum && maxNumBlocksGlobalMem<maxNumBlocks) {
        minBlockDim*=2;
        maxNumBlocks = maxNumThreadsPerSM*numOfMultiProcessors / minBlockDim;
    }
    maxNumBlocks = MIN(maxNumBlocks, maxNumBlocksGlobalMem);

    if (config.version == HYBRID) {
        printf("globalListSize = %d\n", config.globalListSize);
        printf("compArraySize = %lld\n", config.compArraySize);
    }
    //printf("maxNumBlocksGlobalMem = %lld\n",maxNumBlocksGlobalMem);
    //printf("minBlockDim = %lld\n",minBlockDim);
    //printf("maxNumBlocks = %d\n",maxNumBlocks);

	long long maxBlockDim = 1024;
	long long optimalBlockDim = maxBlockDim;
	bool useSharedMem = false;
    
    long long sharedMemPerSM;
	for (long long blockDim = minBlockDim; blockDim <= maxBlockDim; blockDim *= 2)
	{
		long long maxBlocksPerSMBlockDim = maxNumThreadsPerSM / blockDim;
		long long sharedMemNeeded = (graph.vertexNum + MAX(graph.vertexNum, 2 * blockDim))*sizeofINT_OR_SHORT
                                     + alreadyUsedSharedMemPerBlock;
		sharedMemPerSM = maxBlocksPerSMBlockDim * sharedMemNeeded;

		if (maxSharedMemPerSM >= sharedMemPerSM)
		{
			optimalBlockDim = blockDim;
			useSharedMem = true;
			break;
		}
	}

	//printf("\nOptimal BlockDim : %lld\n", optimalBlockDim);
	//fflush(stdout);

	if (config.blockDim==0)
	{
        if (config.numBlocks) {
            config.blockDim = maxNumThreadsPerSM*numOfMultiProcessors / config.numBlocks;
            config.blockDim = pow(2, floor(log2((double)config.blockDim)));
            config.blockDim = MIN(1024, config.blockDim);
            if (config.blockDim < minBlockDim || config.numBlocks>maxNumBlocks)
            {
                fprintf(stderr, "\nPlease choose numBlocks less than or equal to : %d\n", maxNumBlocks);
                exit(0);
            }
        } else {
            config.blockDim = optimalBlockDim;
        }
	} 
    else if (config.blockDim < minBlockDim)
    {
        fprintf(stderr, "\nPlease choose a BlockDim greater than or equal to : %lld\n", minBlockDim);
        exit(0);
    }

    if (config.blockDim < optimalBlockDim && useSharedMem == 1)
    {
        useSharedMem = 0;
        if (config.userDefMemory && (config.useGlobalMemory == 0))
        {
            fprintf(stderr, "\nCannot use shared memory with this configuration, please choose a greater blockDim/less numBlocks.\n");
            exit(0);
        }
        printf("To use shared memory choose a greater blockDim.\n");
    }
    
	if (!config.userDefMemory)
	{
		config.useGlobalMemory = !useSharedMem;
        printf("Use Shared Mem : %d\n", useSharedMem);
	} else {
        printf("Use Shared Mem : %d\n", !config.useGlobalMemory);
    }

    if (useSharedMem) {
        printf("sharedMemUsed = %lld\n", sharedMemPerSM);
    }
}

void printResults(Config config, unsigned int maxApprox, unsigned int edgeApprox, double timeMax, double timeEdge, unsigned int minimum, double timeMin, unsigned int numblocks, unsigned int numBlocksPerSM, int numThreadsPerSM, unsigned int numVertices, unsigned int numEdges, unsigned int k_found)
{

	char outputFilename[500];
	strcpy(outputFilename, "Results/Results.csv");

    mkdir("Results", 0777);
	FILE *output_file = fopen(outputFilename, "a");

	fprintf(
		output_file,
		"%s,%s,%u,%u,%s,%s,%d,%f,%d,%d,%d,%u,%d,%d,%u,%f,%u,%f,%u,%u,%u,%f\n",
		config.outputFilePrefix, config.graphFileName, numVertices, numEdges, asString(config.instance), asString(config.version), config.globalListSize, config.globalListThreshold,
		config.startingDepth, config.useGlobalMemory, config.blockDim, numBlocksPerSM, numThreadsPerSM, config.numBlocks, maxApprox, timeMax, edgeApprox, timeEdge, minimum, config.k, k_found, timeMin);

	fclose(output_file);
}

void printResults(Config config, unsigned int maxApprox, unsigned int edgeApprox, double timeMax, double timeEdge, unsigned int minimum, double timeMin, unsigned int numVertices, unsigned int numEdges, unsigned int k_found)
{

	char outputFilename[500];
	strcpy(outputFilename, "Results/Results.csv");

    mkdir("Results", 0777);
	FILE *output_file = fopen(outputFilename, "a");

	fprintf(
		output_file,
		"%s,%s,%u,%u,%s,%s,  ,  ,  ,  ,  ,  ,  ,  ,%u,%f,%u,%f,%u,%u,%u,%f\n",
		config.outputFilePrefix, config.graphFileName, numVertices, numEdges, asString(config.instance), asString(config.version), maxApprox, timeMax,
		edgeApprox, timeEdge, minimum, config.k, k_found, timeMin * 1000);

	fclose(output_file);
}

void printNumBranchesInFile(Config config, unsigned int numBranches_h, unsigned int *numBranchesFreq_h, unsigned int numVertices)
{
    char filename[100];
    strcpy(filename,config.graphFileName);

    char * token = strtok(filename, "/");
    // loop through the string to extract all other tokens
    char * outputfile;
    while( token != NULL ) {
        outputfile = token;
        token = strtok(NULL, "/");
    }

    char outputFilename[500];
    strcpy(outputFilename,"Num_Branches/Num_Branches_");
    strcat(outputFilename,outputfile);

    mkdir("Num_Branches", 0777);
    FILE *output_file = fopen(outputFilename, "w");

    fprintf(output_file, "Branches on components: %u\n\n", numBranches_h);
    fprintf(output_file, "Components per branch { number of components: frequency }\n\n");

    fprintf(output_file, "{");
    bool first = true;

    for (unsigned int i = 0; i < numVertices; ++i)
    {
        if (numBranchesFreq_h[i] != 0)
        {
            if (!first)
            {
                fprintf(output_file, ";");
            }

            fprintf(output_file, "%u: %u", i, numBranchesFreq_h[i]);
            first = false;
        }
    }

    fprintf(output_file, "}\n");

    fclose(output_file);
}
