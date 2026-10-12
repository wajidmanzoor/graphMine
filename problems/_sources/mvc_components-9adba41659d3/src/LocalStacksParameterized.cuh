#include <stdio.h>
#include <stdint.h>
#include <assert.h>

#include "config.h"
#include "stack.cuh"
#include "Counters.cuh"
#include "helperFunctions.cuh"

#if USE_SHORT_DEGREE
#define INT_OR_SHORT short
#define FUNCTION_NAME(base) base##_short
#define SHARED_MEM_TYPE(base) base##_short
#else
#define INT_OR_SHORT int
#define FUNCTION_NAME(base) base##_int
#define SHARED_MEM_TYPE(base) base##_int
#endif

#if USE_GLOBAL_MEMORY
__global__ void FUNCTION_NAME(LocalStacksParameterized_global_kernel)(Stacks<INT_OR_SHORT> stacks, CSRGraph graph, INT_OR_SHORT* global_memory, unsigned int * k, unsigned int * kFound, Counters* counters, unsigned int * pathCounter, unsigned long long* NODES_PER_SM, int startingDepth, unsigned int findBound) {
#else
__global__ void FUNCTION_NAME(LocalStacksParameterized_shared_kernel)(Stacks<INT_OR_SHORT> stacks, CSRGraph graph, unsigned int * k, unsigned int * kFound, Counters* counters, unsigned int * pathCounter, unsigned long long* NODES_PER_SM, int startingDepth, unsigned int findBound) {
#endif

    Counters blockCounters;
    initializeCounters(&blockCounters);

    __shared__ unsigned int left;
    __shared__ unsigned int right;

    #if USE_COUNTERS
        __shared__ unsigned int sm_id;
        if (threadIdx.x==0){
            sm_id=get_smid();
        }
    #endif

    do{
        __shared__ unsigned int path;
        if(threadIdx.x==0){
            path = atomicAdd(pathCounter,1);
        }
        __syncthreads();

        if(path>=(1<<startingDepth)){
            break;
        }

        // Initialize the vertexDegrees_s
        
        unsigned int numDeletedVertices = 0;
        unsigned int numDeletedVertices2;

        #if USE_GLOBAL_MEMORY
        INT_OR_SHORT * vertexDegrees_s = &global_memory[graph.vertexNum*(2*blockIdx.x)];
        INT_OR_SHORT * vertexDegrees_s2 = &global_memory[graph.vertexNum*(2*blockIdx.x + 1)];
        #else
        extern __shared__ INT_OR_SHORT SHARED_MEM_TYPE(shared_mem)[];
        INT_OR_SHORT * vertexDegrees_s = SHARED_MEM_TYPE(shared_mem);
        INT_OR_SHORT * vertexDegrees_s2 = &SHARED_MEM_TYPE(shared_mem)[graph.vertexNum];
        #endif

        for(unsigned int i = threadIdx.x; i < graph.vertexNum; i += blockDim.x) {
            vertexDegrees_s[i] = graph.degree[i];
        }
        __syncthreads();

        // Find the block's sub-tree
        bool vcFound = false;
        bool minExceeded = false;
        __shared__ unsigned int kIsFound;
        if(threadIdx.x==0){
            kIsFound = atomicOr(kFound,0);
        }
        __syncthreads();
        
        for(unsigned int depth = 0; depth < startingDepth && !vcFound && !minExceeded && !(kIsFound); ++depth) {
            #if USE_COUNTERS
                if (threadIdx.x==0){
                    atomicAdd(&NODES_PER_SM[sm_id],1);
                }
            #endif
            
            if(threadIdx.x == 0){
                left = graph.vertexNum-1;
                right = 0;
            }
            __syncthreads();
            if (k > 0) {
                if (findBound) {
                    startTime(FIND_BOUND,&blockCounters);
                    findBoundaries(vertexDegrees_s, &left, &right, graph.vertexNum);
                    endTime(FIND_BOUND,&blockCounters);
                }
            } else {
                if(threadIdx.x == 0) {
                    left = 0;
                    right = graph.vertexNum -1;
                }
            }
            __syncthreads();
            
            if(threadIdx.x == 0) {
                if (right == 0) {
                    left = 0;
                    right = graph.vertexNum-1;
                }
            }
            __syncthreads();

            // reduction rule

            unsigned int iterationCounter = 0, numDeletedVerticesLeaf, numDeletedVerticesTriangle, numDeletedVerticesHighDegree;
            do {
                startTime(LEAF_REDUCTION,&blockCounters);
                numDeletedVerticesLeaf = leafReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, left, right);
                endTime(LEAF_REDUCTION,&blockCounters);
                numDeletedVertices += numDeletedVerticesLeaf;
                if(iterationCounter==0 || numDeletedVerticesLeaf>0 || numDeletedVerticesHighDegree>0) {
                    startTime(TRIANGLE_REDUCTION,&blockCounters);
                    numDeletedVerticesTriangle = triangleReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, left, right);
                    endTime(TRIANGLE_REDUCTION,&blockCounters);
                    numDeletedVertices += numDeletedVerticesTriangle;
                } else {
                    numDeletedVerticesTriangle = 0;
                }
                if(iterationCounter==0 || numDeletedVerticesLeaf>0 || numDeletedVerticesTriangle>0) {
                    startTime(HIGH_DEGREE_REDUCTION,&blockCounters);
                    numDeletedVerticesHighDegree = highDegreeReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2,numDeletedVertices,*k+1, left, right);
                    endTime(HIGH_DEGREE_REDUCTION,&blockCounters);
                    numDeletedVertices += numDeletedVerticesHighDegree;
                } else {
                    numDeletedVerticesHighDegree = 0;
                }
                ++iterationCounter;
            } while(numDeletedVerticesTriangle>0 || numDeletedVerticesHighDegree>0);

            startTime(NUM_EDGES,&blockCounters);
            unsigned int numOfEdges = findNumOfEdges(graph.vertexNum, vertexDegrees_s, vertexDegrees_s2, left, right);
            endTime(NUM_EDGES,&blockCounters);

            bool numEdgesCondition = false;
            if(numOfEdges>=square((int)(*k)-(int)numDeletedVertices)+1) {
                numEdgesCondition = true;
            }
            __syncthreads();

            if(numDeletedVertices>*k || numEdgesCondition) {
                minExceeded = true;
            } else {

                unsigned int maxVertex = 0;
                INT_OR_SHORT maxDegree = 0;

                startTime(MAX_DEGREE,&blockCounters);
                findMaxDegree(graph.vertexNum, &maxVertex, &maxDegree, vertexDegrees_s, vertexDegrees_s2, left, right);
                endTime(MAX_DEGREE,&blockCounters);

                if(maxDegree<1){
                    vcFound = true;
                    if(numDeletedVertices<=*k){
                        atomicOr(kFound,1);
                    }
                    __syncthreads();
                } else {
                    unsigned int goLeft = !((path >> depth) & 1u);
                    if(goLeft){
                        
                        if (threadIdx.x == 0){
                            vertexDegrees_s[maxVertex] = -1;
                        }
                        ++numDeletedVertices;
                        __syncthreads();

                        for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1]; edge+=blockDim.x) {
                            unsigned int neighbor = graph.dst[edge];
                            if(vertexDegrees_s[neighbor] != -1){
                                #if USE_SHORT_DEGREE
                                atomicSubShort(&vertexDegrees_s[neighbor], 1);
                                #else
                                atomicSub(&vertexDegrees_s[neighbor], 1);
                                #endif
                            }
                        }

                    } else {// Delete Neighbors of maxVertex
                        numDeletedVertices += maxDegree;

                        for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1]; edge += blockDim.x) {
                            unsigned int neighbor = graph.dst[edge];
                            if(vertexDegrees_s[neighbor] != -1) {
                                for(unsigned int neighborEdge = graph.srcPtr[neighbor]; neighborEdge < graph.srcPtr[neighbor + 1]; ++neighborEdge) {
                                    unsigned int neighborOfNeighbor = graph.dst[neighborEdge];
                                    if(vertexDegrees_s[neighborOfNeighbor] != -1) {
                                        #if USE_SHORT_DEGREE
                                        atomicSubShort(&vertexDegrees_s[neighborOfNeighbor], 1);
                                        #else
                                        atomicSub(&vertexDegrees_s[neighborOfNeighbor], 1);
                                        #endif
                                    }
                                }
                            }
                        }
                        __syncthreads();

                        for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1] ; edge += blockDim.x) {
                            unsigned int neighbor = graph.dst[edge];
                            vertexDegrees_s[neighbor] = -1;
                        }
                    }
                }

            }

            if(threadIdx.x==0){
                kIsFound = atomicOr(kFound,0);
            }
            __syncthreads();
        }

        // Each block its at it's required level which is at most Root depth
        if(!vcFound && !minExceeded) {
            unsigned int stackSize = (stacks.minimum + 1);
            volatile INT_OR_SHORT * stackVertexDegrees = &stacks.stacks[(long long)blockIdx.x * (long long)stackSize * (long long)graph.vertexNum];
            volatile unsigned int * stackNumDeletedVertices = &stacks.stacksNumDeletedVertices[blockIdx.x * stackSize];
            volatile int * stackArrayIndex = &stacks.stackArrayIndex[blockIdx.x * stackSize];
            volatile bool * stackCompNode = &stacks.stackCompNode[blockIdx.x * stackSize];

            int arrayIndex = -1;
            bool compNode = 0;
            int stackTop = -1;

            // go into while loop 
            bool popNextItr = false;
            __syncthreads();
            
            do{
                if(threadIdx.x==0) {
                    kIsFound = atomicOr(kFound,0);
                }
                __syncthreads();

                if(kIsFound){
                    break;
                }

                if(popNextItr) {
                    startTime(POP_FROM_STACK,&blockCounters);
                    popStack(graph.vertexNum, vertexDegrees_s, &numDeletedVertices, &arrayIndex, &compNode, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, &stackTop, true);
                    endTime(POP_FROM_STACK,&blockCounters);

                    #if USE_COUNTERS
                        if (threadIdx.x==0){
                            atomicAdd(&NODES_PER_SM[sm_id],1);
                        }
                    #endif
                }
                __syncthreads();
                
                if(threadIdx.x == 0) {
                    left = graph.vertexNum-1;
                    right = 0;
                }
                __syncthreads();
                
                if (findBound) {
                    startTime(FIND_BOUND,&blockCounters);
                    findBoundaries(vertexDegrees_s, &left, &right, graph.vertexNum);
                    endTime(FIND_BOUND,&blockCounters);
                }

                //reduction rule
                __shared__ unsigned int currentMin_s;
                if(threadIdx.x == 0) {
                    if (arrayIndex>-1) {
                        #if USE_SHORT_DEGREE
                        currentMin_s = readIntFromShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum]);
                        #else
                        currentMin_s = stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum];
                        #endif
                    } else {
                        currentMin_s = *k+1;
                    }
                    
                    if (right == 0) {
                        left = 0;
                        right = graph.vertexNum-1;
                    }
                }
                __syncthreads();
        
                unsigned int iterationCounter = 0, numDeletedVerticesLeaf, numDeletedVerticesTriangle, numDeletedVerticesHighDegree;
                do {
                    startTime(LEAF_REDUCTION,&blockCounters);
                    numDeletedVerticesLeaf = leafReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, left, right);
                    endTime(LEAF_REDUCTION,&blockCounters);
                    numDeletedVertices += numDeletedVerticesLeaf;
                    if(iterationCounter==0 || numDeletedVerticesLeaf>0 || numDeletedVerticesHighDegree>0) {
                        startTime(TRIANGLE_REDUCTION,&blockCounters);
                        numDeletedVerticesTriangle = triangleReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, left, right);
                        endTime(TRIANGLE_REDUCTION,&blockCounters);
                        numDeletedVertices += numDeletedVerticesTriangle;
                    } else {
                        numDeletedVerticesTriangle = 0;
                    }
                    if(iterationCounter==0 || numDeletedVerticesLeaf>0 || numDeletedVerticesTriangle>0) {
                        startTime(HIGH_DEGREE_REDUCTION,&blockCounters);
                        numDeletedVerticesHighDegree = highDegreeReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2,numDeletedVertices,currentMin_s, left, right);
                        endTime(HIGH_DEGREE_REDUCTION,&blockCounters);
                        numDeletedVertices += numDeletedVerticesHighDegree;
                    } else {
                        numDeletedVerticesHighDegree = 0;
                    }
                    ++iterationCounter;
                } while(numDeletedVerticesTriangle>0 || numDeletedVerticesHighDegree>0);

                startTime(NUM_EDGES,&blockCounters);
                unsigned int numOfEdges = findNumOfEdges(graph.vertexNum, vertexDegrees_s, vertexDegrees_s2, left, right);
                endTime(NUM_EDGES,&blockCounters);
                
                bool numEdgesCondition = false;
                if(numOfEdges>=square((int)currentMin_s-(int)numDeletedVertices-1)+1) {
                    numEdgesCondition = true;
                }
                __syncthreads();
        
                if(threadIdx.x == 0) {
                    if (arrayIndex>-1) {
                        #if USE_SHORT_DEGREE
                        currentMin_s = readIntFromShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum]);
                        #else
                        currentMin_s = stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum];
                        #endif
                    } else {
                        currentMin_s = *k+1;
                    }
                }
                __syncthreads();

                if(numDeletedVertices>=currentMin_s || numEdgesCondition) {
                    if (threadIdx.x == 0 && arrayIndex>-1 && compNode) {
                        #if USE_SHORT_DEGREE
                        if (arrayIndex != stackTop) {
                            unsigned int oldMinim = readIntFromShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3]);
                            saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3], oldMinim+1);
                            saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum], oldMinim+1);
                        } else {
                            saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum], 0);
                            saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3], 0);
                        }
                        #else
                        if (arrayIndex != stackTop) {
                            unsigned int oldMinim = stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3];
                            stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3] = oldMinim+1;
                            stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum] = oldMinim+1;
                        } else {
                            stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum] = 0;
                            stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3] = 0;
                        }
                        #endif
                    }
                    popNextItr = true;
                    __syncthreads();
                } else {
                
                    unsigned int isComponents = 1;
                    startTime(COMP_SEARCH,&blockCounters);
                    isComponents = bfsCC_param_StackOnly(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, arrayIndex, compNode, currentMin_s, &numDeletedVertices, &blockCounters, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, &stackTop, stackSize, k, left, right);
                    endTime(COMP_SEARCH,&blockCounters);
                    __syncthreads();

                    unsigned int maxVertex;
                    INT_OR_SHORT maxDegree;
                    if (isComponents>1) {
                        popNextItr = true;
                        __syncthreads();

                    } else if (isComponents==0) {
                        if(threadIdx.x == 0) {
                            bool kIsFounded = false;
                            unsigned int originalNumDeletedVertices = numDeletedVertices;
                            int originalArrayIndex = arrayIndex;
                            while (true) {
                                if (arrayIndex>-1) {
                                    #if USE_SHORT_DEGREE
                                    unsigned int oldMin=readIntFromShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum]);
                                    if (oldMin<=numDeletedVertices) {
                                        break;
                                    }
                                    saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum], numDeletedVertices);
                                    #else
                                    unsigned int oldMin = stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum];
                                    if (oldMin<=numDeletedVertices) {
                                        break;
                                    }
                                    stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum] = numDeletedVertices;
                                    #endif

                                    stackNumDeletedVertices[arrayIndex] -= (oldMin-numDeletedVertices);
                                    numDeletedVertices = stackNumDeletedVertices[arrayIndex];
                                    arrayIndex = stackArrayIndex[arrayIndex];
                                } else {
                                    if(numDeletedVertices<=*k) {
                                        atomicOr(kFound,1);
                                        kIsFounded = true;
                                    }
                                    // For Debugging Purposes
                                    //printf("numDel = %d\n", numDeletedVertices);
                                    break;
                                }
                            }
                            
                            numDeletedVertices = originalNumDeletedVertices;
                            arrayIndex = originalArrayIndex;
                        
                            if (arrayIndex>-1 && compNode) {
                                #if USE_SHORT_DEGREE
                                if (arrayIndex != stackTop) {
                                    unsigned int oldMinim = readIntFromShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3]);
                                    saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3], oldMinim+1);
                                    saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum], oldMinim+1);
                                } else {
                                    saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum], 0);
                                    saveIntInShortArray(&stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3], 0);
                                }
                                #else
                                if (arrayIndex != stackTop) {
                                    unsigned int oldMinim = stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3];
                                    stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3] = oldMinim+1;
                                    stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum] = oldMinim+1;
                                } else {
                                    stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum] = 0;
                                    stackVertexDegrees[(long long)arrayIndex*(long long)graph.vertexNum+(long long)3] = 0;
                                }
                                #endif
                            }
                        }
                        popNextItr = true;
                        __syncthreads();
                    } else {

                        // Find max degree
                        startTime(MAX_DEGREE,&blockCounters);
                        findMaxDegree(graph.vertexNum, &maxVertex, &maxDegree, vertexDegrees_s, vertexDegrees_s2, left, right);
                        endTime(MAX_DEGREE,&blockCounters);

                        startTime(PREPARE_RIGHT_CHILD,&blockCounters);
                        deleteNeighborsOfMaxDegreeVertex(graph,vertexDegrees_s, &numDeletedVertices, vertexDegrees_s2, &numDeletedVertices2, maxDegree, maxVertex);
                        endTime(PREPARE_RIGHT_CHILD,&blockCounters);

                        startTime(PUSH_TO_STACK,&blockCounters);
                        pushStack(graph.vertexNum, vertexDegrees_s2, &numDeletedVertices2, arrayIndex, compNode, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, &stackTop, true);
                        endTime(PUSH_TO_STACK,&blockCounters);
                        maxDepth(stackTop, &blockCounters);
                        __syncthreads();

                        startTime(PREPARE_LEFT_CHILD,&blockCounters);
                        deleteMaxDegreeVertex(graph, vertexDegrees_s, &numDeletedVertices, maxVertex);
                        endTime(PREPARE_LEFT_CHILD,&blockCounters);

                        #if USE_COUNTERS
                            if (threadIdx.x==0){
                                atomicAdd(&NODES_PER_SM[sm_id],1);
                            }
                        #endif

                        compNode = 0;
                        popNextItr = false;
                        __syncthreads();
                    }
                }
                __syncthreads();

            } while(stackTop != -1);
        }
    }while(true);

    #if USE_COUNTERS
    if(threadIdx.x == 0) {
        counters[blockIdx.x] = blockCounters;
    }
    #endif
}

#undef INT_OR_SHORT
#undef FUNCTION_NAME(base)
#undef SHARED_MEM_TYPE(base)