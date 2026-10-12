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
__global__ void FUNCTION_NAME(GlobalWorkList_global_kernel)(Stacks<INT_OR_SHORT> stacks, unsigned int * minimum, WorkList<INT_OR_SHORT> workList, CSRGraph graph, Counters* counters, int* first_to_dequeue_global, INT_OR_SHORT* global_memory, unsigned long long* NODES_PER_SM, CompArray compArray, unsigned int* compArraySize, unsigned int findBound, unsigned int* numBranches, unsigned int* numBranchesFreq) {
#else
__global__ void FUNCTION_NAME(GlobalWorkList_shared_kernel)(Stacks<INT_OR_SHORT> stacks, unsigned int * minimum, WorkList<INT_OR_SHORT> workList, CSRGraph graph, Counters* counters, int* first_to_dequeue_global, unsigned long long* NODES_PER_SM, CompArray compArray, unsigned int* compArraySize, unsigned int findBound, unsigned int* numBranches, unsigned int* numBranchesFreq) {
#endif

    // For Evaluation Purposes
    //__shared__ Counters blockCounters;
 
    Counters blockCounters;
    initializeCounters(&blockCounters);
    
    // For Evaluation Purposes
    #if RUN_KILL_TIMEOUT
    __shared__ long long startingTime;
    __shared__ bool timeOut;
    if (threadIdx.x==0) {
        startingTime = clock64();
        timeOut = false;
    }
    #endif

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
    if (threadIdx.x==0) {
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

    while(true) {
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
                if(!dequeue(vertexDegrees_s, workList, graph.vertexNum, &numDeletedVertices, &arrayIndex)) {   
                    endTime(TERMINATE,&blockCounters);
                    break;
                }
                endTime(DEQUEUE,&blockCounters);
                
                // For Debugging Purposes
                /*__shared__ bool conditionn;
                if (threadIdx.x==0) {
                    conditionn = false;
                    for (int i = 0; i<graph.vertexNum; ++i) {
                        if (vertexDegrees_s[i]>0) {
                            unsigned int counter = 0;
                            for(unsigned int edge = graph.srcPtr[i]; edge<graph.srcPtr[i+1]; ++edge) {
                                unsigned int neigh = graph.dst[edge];
                                if(vertexDegrees_s[neigh]>0) {
                                    ++counter;
                                }
                            }
                            if (counter != vertexDegrees_s[i]) {
                                conditionn = true;
                            }
                        }
                    }
                    if (conditionn) {
                        printf("Head = %u, Tail = %u, woklist Baaaaaaaaaaaaaad count = %d, numWait = %d, numEnq = %d\n",
                           (unsigned int)(*workList.head_tail & 0xFFFFFFFF),
                           (unsigned int)((*workList.head_tail >> 32) & 0xFFFFFFFF),
                           *workList.count,
                           workList.counter->numWaiting,
                           workList.counter->numEnqueued
                        );
                    } else {
                        printf("Head = %u, Tail = %u, woklist count = %d, numWait = %d, numEnq = %d\n",
                           (unsigned int)(*workList.head_tail & 0xFFFFFFFF),
                           (unsigned int)((*workList.head_tail >> 32) & 0xFFFFFFFF),
                           *workList.count,
                           workList.counter->numWaiting,
                           workList.counter->numEnqueued
                        );
                    }
                }
                __syncthreads();*/

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

        __shared__ unsigned int minimum_s;
        if(threadIdx.x == 0) {
            if (arrayIndex>-1) {
                minimum_s = atomicOr((int*)&compArray.entries[arrayIndex].minimum,0);
            } else {
                minimum_s = atomicOr(minimum,0);
            }
            
            if (right == 0) {
                left = 0;
                right = graph.vertexNum-1;
            }
            
            // For Evaluation Purposes
            #if RUN_KILL_TIMEOUT
            if (clock64() - startingTime > 25000000000000) {
                timeOut = true;
            }
            #endif
        }
        __syncthreads();

        // For Evaluation Purposes
        #if RUN_KILL_TIMEOUT
        if (timeOut) {
            stackTop = -1;
            dequeueOrPopNextItr = true;
            continue;
        }
        #endif

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
                numDeletedVerticesHighDegree = highDegreeReductionRule(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2,numDeletedVertices,minimum_s, left, right);
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
        if(numOfEdges>=square((int)minimum_s-(int)numDeletedVertices-1)+1) {
            numEdgesCondition = true;
        }
        __syncthreads();

        if(threadIdx.x == 0) {
            if (arrayIndex>-1) {
                minimum_s = atomicOr((int*)&compArray.entries[arrayIndex].minimum,0);
            } else {
                minimum_s = atomicOr(minimum,0);
            }
            // For Debugging Purposes
            //printf("I am Alive blockIdx.x = %d and stackTop = %d and minim = %u\n", blockIdx.x, stackTop, minimum_s);
        }
        __syncthreads();

        if(numDeletedVertices>=minimum_s || numEdgesCondition) { // Reached the bottom of the tree, no minimum vertex cover found
            if(threadIdx.x==0 && arrayIndex>-1) {
                int counter = atomicSub((int*)&compArray.entries[arrayIndex].counter, 1);
                if (counter==1) {
                    int parentIndex = compArray.entries[arrayIndex].index;
                    atomicAdd((int*)&compArray.entries[parentIndex].minimum, compArray.entries[arrayIndex].minimum);
                    int parentCounter = atomicSub((int*)&compArray.entries[parentIndex].counter, 1);
                    if (parentCounter==1) {
                        arrayIndex = compArray.entries[parentIndex].index;
                        numDeletedVertices = atomicOr((int*)&compArray.entries[parentIndex].minimum,0);
                        while (true) {
                            if (arrayIndex>-1) {
                                atomicMin((int*)&compArray.entries[arrayIndex].minimum, numDeletedVertices);
                                int counter = atomicSub((int*)&compArray.entries[arrayIndex].counter, 1);
                                if (counter-1>0) {
                                    break;
                                }
                                int parentIndex = compArray.entries[arrayIndex].index;
                                atomicAdd((int*)&compArray.entries[parentIndex].minimum, compArray.entries[arrayIndex].minimum);
                                int parentCounter = atomicSub((int*)&compArray.entries[parentIndex].counter, 1);
                                if (parentCounter-1>0) {
                                    break;
                                }
                                arrayIndex = compArray.entries[parentIndex].index;
                                numDeletedVertices = atomicOr((int*)&compArray.entries[parentIndex].minimum,0);

                            } else {
                                atomicMin(minimum, numDeletedVertices);
                                break;
                            }
                        }
                    }
                }
            }
            dequeueOrPopNextItr = true;
            __syncthreads();

        } else {

            int isComponents = 1;
            startTime(COMP_SEARCH,&blockCounters);
            //isComponents = bfsConnectedComp_Hybrid(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, arrayIndex, minimum_s, numDeletedVertices, compArray, workList, &blockCounters, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, &stackTop, stackSize, *compArraySize, left, right);
            //isComponents = bfs_Hybrid(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, arrayIndex, minimum_s, numDeletedVertices, compArray, workList, &blockCounters, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, &stackTop, stackSize, *compArraySize, left, right);
            isComponents = bfsCC_Hybrid(graph.vertexNum, vertexDegrees_s, graph, vertexDegrees_s2, arrayIndex, minimum_s, &numDeletedVertices, compArray, workList, &blockCounters, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, &stackTop, stackSize, *compArraySize, left, right, minimum);
            endTime(COMP_SEARCH,&blockCounters);
             __syncthreads();

            unsigned int maxVertex;
            INT_OR_SHORT maxDegree;
            if (isComponents>1) {
                #if COUNT_BRANCHING_ON_COMPONENTS
                if (threadIdx.x==0) {
                   atomicAdd(numBranches, 1);
                   atomicAdd(&numBranchesFreq[isComponents], 1);
                }
                __syncthreads();
                #endif
                dequeueOrPopNextItr = true;
                __syncthreads();

            } else if (isComponents==0) { // Reached the bottom of the tree, minimum vertex cover possibly found
                if(threadIdx.x==0) {
                    while (true) {
                        if (arrayIndex>-1) {
                            atomicMin((int*)&compArray.entries[arrayIndex].minimum, numDeletedVertices);
                            int counter = atomicSub((int*)&compArray.entries[arrayIndex].counter, 1);
                            if (counter-1>0) {
                                break;
                            }
                            int parentIndex = compArray.entries[arrayIndex].index;
                            atomicAdd((int*)&compArray.entries[parentIndex].minimum, compArray.entries[arrayIndex].minimum);
                            int parentCounter = atomicSub((int*)&compArray.entries[parentIndex].counter, 1);
                            if (parentCounter-1>0) {
                                break;
                            }
                            arrayIndex = compArray.entries[parentIndex].index;
                            numDeletedVertices = atomicOr((int*)&compArray.entries[parentIndex].minimum,0);
                        } else {
                            atomicMin(minimum, numDeletedVertices);
                            break;
                        }
                    }
                }
                dequeueOrPopNextItr = true;
                __syncthreads();

            } else {
                // Vertex cover not found, need to branch
                if(threadIdx.x == 0) {
                    if (arrayIndex>-1) {
                        atomicAdd((int*)&compArray.entries[arrayIndex].counter, 1);
                    }
                }
                __syncthreads();
                
                startTime(MAX_DEGREE,&blockCounters);
                findMaxDegree(graph.vertexNum, &maxVertex, &maxDegree, vertexDegrees_s, vertexDegrees_s2, left, right);
                endTime(MAX_DEGREE,&blockCounters);

                startTime(PREPARE_RIGHT_CHILD,&blockCounters);
                deleteNeighborsOfMaxDegreeVertex(graph,vertexDegrees_s, &numDeletedVertices, vertexDegrees_s2, &numDeletedVertices2, maxDegree, maxVertex);
                endTime(PREPARE_RIGHT_CHILD,&blockCounters);

                bool enqueueSuccess;
                if(checkThreshold(workList)) {
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
                    if (threadIdx.x==0) {
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
            for(unsigned int vertex = 0; vertex<globIndex; vertex++) {
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