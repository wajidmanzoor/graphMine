#include <stdio.h>
#include <stdint.h>
#include <assert.h>

#include "config.h"
#include "stack.cuh"
#include "Counters.cuh"
#include "BWDWorkList.cuh"
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
__global__ void FUNCTION_NAME(GlobalWorkListParameterized_global_kernel)(Stacks<INT_OR_SHORT> stacks, WorkList<INT_OR_SHORT> workList, CSRGraph graph, Counters* counters, int* first_to_dequeue_global, INT_OR_SHORT* global_memory, unsigned int * k, unsigned int * kFound, unsigned long long* NODES_PER_SM, CompArray compArray, unsigned int* compArraySize, unsigned int findBound) {
#else
__global__ void FUNCTION_NAME(GlobalWorkListParameterized_shared_kernel)(Stacks<INT_OR_SHORT> stacks, WorkList<INT_OR_SHORT> workList, CSRGraph graph, Counters* counters, int* first_to_dequeue_global, unsigned int * k, unsigned int * kFound, unsigned long long* NODES_PER_SM, CompArray compArray, unsigned int* compArraySize, unsigned int findBound) {
#endif

    bool condition = true;
    Counters blockCounters;
    initializeCounters(&blockCounters);

    #if USE_COUNTERS
        __shared__ unsigned int sm_id;
        if (threadIdx.x==0){
            sm_id=get_smid();
        }
    #endif

    int stackTop = -1;
    unsigned int stackSize = (stacks.minimum + 1);
    volatile INT_OR_SHORT * stackVertexDegrees = &stacks.stacks[(long long)blockIdx.x * (long long)stackSize * (long long)graph.vertexNum];
    volatile unsigned int * stackNumDeletedVertices = &stacks.stacksNumDeletedVertices[blockIdx.x * stackSize];
    volatile int * stackArrayIndex = &stacks.stackArrayIndex[blockIdx.x * stackSize];

    // Define the vertexDegree_s
    unsigned int numDeletedVertices;
    unsigned int numDeletedVertices2;
    
    int arrayIndex = -1;
    
    #if USE_GLOBAL_MEMORY
    INT_OR_SHORT * vertexDegrees_s = &global_memory[graph.vertexNum*(2*blockIdx.x)];
    INT_OR_SHORT * vertexDegrees_s2 = &global_memory[graph.vertexNum*(2*blockIdx.x + 1)];
    #else
    extern __shared__ INT_OR_SHORT SHARED_MEM_TYPE(shared_mem)[];
    INT_OR_SHORT * vertexDegrees_s = SHARED_MEM_TYPE(shared_mem);
    INT_OR_SHORT * vertexDegrees_s2 = &SHARED_MEM_TYPE(shared_mem)[graph.vertexNum];
    #endif
    
    bool dequeueOrPopNextItr = true; 
    __syncthreads();

    __shared__ bool first_to_dequeue;
    if (threadIdx.x==0){
        if(atomicCAS(first_to_dequeue_global,0,1) == 0) { 
            first_to_dequeue = true;
        } else {
            first_to_dequeue = false;
        }
    }
    __syncthreads();
    if (first_to_dequeue) {
        for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex += blockDim.x) {
            vertexDegrees_s[vertex] = graph.degree[vertex];
        }
        numDeletedVertices = 0;
        dequeueOrPopNextItr = false;
        #if USE_COUNTERS
            if (threadIdx.x==0){
                atomicAdd(&NODES_PER_SM[sm_id],1);
            }
        #endif
    }
    __syncthreads();

     __shared__ unsigned int kIsFound;

    while(true) {
        
        if(threadIdx.x==0) {
            kIsFound = atomicOr(kFound,0);
        }
        __syncthreads();
        
        if(kIsFound) {
            break;
        }

        if(dequeueOrPopNextItr) {
            if(stackTop != -1) { // Local stack is not empty, pop from the local stack
                startTime(POP_FROM_STACK,&blockCounters);
                popStack(graph.vertexNum, vertexDegrees_s, &numDeletedVertices, &arrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, &stackTop, false);
                endTime(POP_FROM_STACK,&blockCounters);

                #if USE_COUNTERS
                    if (threadIdx.x==0){
                        atomicAdd(&NODES_PER_SM[sm_id],1);
                    }
                #endif
            } else { // Local stack is empty, read from the global workList
                startTime(TERMINATE,&blockCounters);
                startTime(DEQUEUE,&blockCounters);
                if(!dequeueParameterized(vertexDegrees_s, workList, graph.vertexNum, &numDeletedVertices, &arrayIndex, kFound)) {  
                    endTime(TERMINATE,&blockCounters);
                    break;
                }
                endTime(DEQUEUE,&blockCounters);

                #if USE_COUNTERS
                    if (threadIdx.x==0){
                        atomicAdd(&NODES_PER_SM[sm_id],1);
                    }
                #endif
            } 
        }
        __syncthreads();
        
        __shared__ unsigned int left;
        __shared__ unsigned int right;
        if(threadIdx.x == 0){
            left = graph.vertexNum-1;
            right = 0;
        }
        __syncthreads();
        
        if (findBound) {
            startTime(FIND_BOUND,&blockCounters);
            findBoundaries(vertexDegrees_s, &left, &right, graph.vertexNum);
            endTime(FIND_BOUND,&blockCounters);
        }
        
        __shared__ unsigned int currentMin_s;
        if(threadIdx.x == 0) {
            if (arrayIndex>-1) {
                currentMin_s = atomicOr((int*)&compArray.entries[arrayIndex].minimum,0);
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
                currentMin_s = atomicOr((int*)&compArray.entries[arrayIndex].minimum,0);
            } else {
                currentMin_s = *k+1;
            }
        }
        __syncthreads();

        if(numDeletedVertices>=currentMin_s || numEdgesCondition) {
            dequeueOrPopNextItr = true;

        } else {
            unsigned int isComponents = 1;
            startTime(COMP_SEARCH,&blockCounters);
            isComponents = bfsCC_Param_Hybrid(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, arrayIndex, currentMin_s, &numDeletedVertices, compArray, workList, &blockCounters, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, &stackTop, stackSize, *compArraySize, k, kFound, left, right);
            endTime(COMP_SEARCH,&blockCounters);
            __syncthreads();

            unsigned int maxVertex;
            INT_OR_SHORT maxDegree;
            if (isComponents>1) {
                dequeueOrPopNextItr = true;
                __syncthreads();

            } else if (isComponents==0) { // Reached the bottom of the tree, minimum vertex cover possibly found
                if(threadIdx.x==0) {
                    while (true) {
                        if (arrayIndex>-1) {
                            unsigned int compMin = atomicMin((int*)&compArray.entries[arrayIndex].minimum, numDeletedVertices);
                            if (compMin<=numDeletedVertices) {
                                break;
                            }
                            int parentIndex = compArray.entries[arrayIndex].index;
                            atomicSub((int*)&compArray.entries[parentIndex].minimum, compMin-numDeletedVertices);
                            arrayIndex = compArray.entries[parentIndex].index;
                            numDeletedVertices = compArray.entries[parentIndex].minimum;
                        } else {
                            if(numDeletedVertices<=*k) {
                                atomicOr(kFound,1);
                            }
                            // For Debugging Purposes
                            //printf("numDel = %d\n",numDeletedVertices);
                            break;
                        }
                    }
                }
                dequeueOrPopNextItr = true;
                __syncthreads();

            } else {
                // Vertex cover not found, need to branch
                startTime(MAX_DEGREE,&blockCounters);
                findMaxDegree(graph.vertexNum, &maxVertex, &maxDegree, vertexDegrees_s, vertexDegrees_s2, left, right);
                endTime(MAX_DEGREE,&blockCounters);

                startTime(PREPARE_RIGHT_CHILD,&blockCounters);
                deleteNeighborsOfMaxDegreeVertex(graph,vertexDegrees_s, &numDeletedVertices, vertexDegrees_s2, &numDeletedVertices2, maxDegree, maxVertex);
                endTime(PREPARE_RIGHT_CHILD,&blockCounters);

                bool enqueueSuccess;
                if(checkThreshold(workList)){
                    startTime(ENQUEUE,&blockCounters);
                    enqueueSuccess = enqueue(vertexDegrees_s2, workList, graph.vertexNum, &numDeletedVertices2, arrayIndex);
                } else  {
                    enqueueSuccess = false;
                }
                __syncthreads();

                if(!enqueueSuccess) {
                    startTime(PUSH_TO_STACK,&blockCounters);
                    pushStack(graph.vertexNum, vertexDegrees_s2, &numDeletedVertices2, arrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, &stackTop, false);
                    endTime(PUSH_TO_STACK,&blockCounters);
                    maxDepth(stackTop, &blockCounters); 
                } else {
                    endTime(ENQUEUE,&blockCounters);
                }
                __syncthreads();

                startTime(PREPARE_LEFT_CHILD,&blockCounters);
                // Prepare the child that removes the neighbors of the max vertex to be processed on the next iteration
                deleteMaxDegreeVertex(graph, vertexDegrees_s, &numDeletedVertices, maxVertex);
                endTime(PREPARE_LEFT_CHILD,&blockCounters);

                #if USE_COUNTERS
                    if (threadIdx.x==0){
                        atomicAdd(&NODES_PER_SM[sm_id],1);
                    }
                #endif

                dequeueOrPopNextItr = false;
                __syncthreads();
            }
        }
        __syncthreads();
    }
    
    // For Debugging Purposes
    /*if (blockIdx.x==0) {
        if (threadIdx.x==0) {
            int globIndex = (*compArray.globalArrayIndex<*compArraySize)?*compArray.globalArrayIndex:*compArraySize;
            for(unsigned int vertex = 0; vertex < globIndex; vertex++) {
                printf("index = %d\n",vertex);
                printf("counter = %d\n",compArray.entries[vertex].counter);
                printf("minimum = %d\n",compArray.entries[vertex].minimum);
                printf("index = %d\n\n",compArray.entries[vertex].index);
            }
        }
    }*/

    #if USE_COUNTERS
    if(threadIdx.x == 0) {
        counters[blockIdx.x] = blockCounters;
    }
    #endif
}

#undef INT_OR_SHORT
#undef FUNCTION_NAME(base)
#undef SHARED_MEM_TYPE(base)