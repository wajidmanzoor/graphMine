#if (!defined(HELPFUNCSHORT_H) && USE_SHORT_DEGREE) || (!defined(HELPFUNCINT_H) && !USE_SHORT_DEGREE)

#include "config.h"
#include "BWDWorkList.cuh"
#include "stack.cuh"

#if USE_SHORT_DEGREE
#define HELPFUNCSHORT_H
#define INT_OR_SHORT short
#define ATOMIC_TYPE(base) base##Short

__device__ short atomicSubShort(short* address, short val) {
    // Convert the short* address to a char* for byte-level operations
    char* addr_as_char = (char*)address;

    // Compute the base address aligned to 4 bytes (32 bits)
    char* base_addr_char = addr_as_char - ((size_t)addr_as_char % 4);
    int* base_addr = (int*)base_addr_char;

    // Calculate the offset within the 32-bit word (0 or 2)
    size_t offset = (size_t)(addr_as_char - base_addr_char);

    int old = *base_addr;
    int assumed;
    int newval;
    short old_short;

    do {
        assumed = old;

        // Extract the lower and upper 16 bits
        short low = (short)(old & 0xFFFF);
        short high = (short)((old >> 16) & 0xFFFF);

        if (offset == 0) {
            // We are working with the lower 16 bits
            old_short = low;
            low = old_short - val;
        } else {
            // We are working with the upper 16 bits
            old_short = high;
            high = old_short - val;
        }

        // Reconstruct the 32-bit integer
        newval = ((int)(unsigned short)high << 16) | (unsigned short)(low);

        // Attempt to atomically update the 32-bit word
        old = atomicCAS(base_addr, assumed, newval);
    } while (assumed != old);

    return old_short;
}

__device__ void saveIntInShortArray(volatile short* arr, int value) {
    arr[0] = value & 0xFFFF;          // Lower 16 bits
    arr[1] = (value >> 16) & 0xFFFF;  // Upper 16 bits
}

__device__ void saveIntInShortArray(short* arr, int value) {
    arr[0] = value & 0xFFFF;          // Lower 16 bits
    arr[1] = (value >> 16) & 0xFFFF;  // Upper 16 bits
}

__device__ int readIntFromShortArray(volatile short* arr) {
    int value = (static_cast<int>(arr[1]) << 16) | (static_cast<unsigned short>(arr[0]));
    return value;
}

__device__ int readIntFromShortArray(short* arr) {
    int value = (static_cast<int>(arr[1]) << 16) | (static_cast<unsigned short>(arr[0]));
    return value;
}

__device__ void AddIntInShortArray(volatile short* arr, int value) {
    int currentValue = readIntFromShortArray(arr);
    int newValue = currentValue + value;
    saveIntInShortArray(arr, newValue);
}

__device__ void AddIntInShortArray(short* arr, int value) {
    int currentValue = readIntFromShortArray(arr);
    int newValue = currentValue + value;
    saveIntInShortArray(arr, newValue);
}


#else
#define HELPFUNCINT_H
#define INT_OR_SHORT int
#define ATOMIC_TYPE(base) base

__device__ long long int square(int num) {
    return num*num;
}

__device__ bool binarySearch(unsigned int * arr,  int l, int r, unsigned int x) {

   while (l <= r) {
        int m = l + (r - l) / 2;
        if (arr[m] == x)
            return  true;
  
        if (arr[m] < x)
            l = m + 1;
  
        else
            r = m - 1;
    }
    return false;
}

#endif

__device__ void findBoundaries(INT_OR_SHORT* vertexDegrees_s, unsigned int* left, unsigned int* right, int vertexNum){
    for(unsigned int vertex = threadIdx.x; vertex < vertexNum; vertex += blockDim.x){
        if(vertexDegrees_s[vertex] > 0){
            atomicMin(left,vertex);
            break;
        }
    }
    for(int vertex = vertexNum-(int)(threadIdx.x)-1; vertex > -1; vertex -= (int)blockDim.x){
        if(vertexDegrees_s[vertex] > 0){
            atomicMax(right,vertex);
            break;
        }
    }
    __syncthreads();
}

__device__ void deleteNeighborsOfMaxDegreeVertex(CSRGraph graph, INT_OR_SHORT* vertexDegrees_s, unsigned int* numDeletedVertices, INT_OR_SHORT* vertexDegrees_s2, unsigned int* numDeletedVertices2, INT_OR_SHORT maxDegree, unsigned int maxVertex) {

    *numDeletedVertices2 = *numDeletedVertices;
    for(unsigned int vertex = threadIdx.x; vertex<graph.vertexNum; vertex+=blockDim.x){
        vertexDegrees_s2[vertex] = vertexDegrees_s[vertex];
    }
    __syncthreads();

    for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1]; edge+=blockDim.x) { // Delete Neighbors of maxVertex
        unsigned int neighbor = graph.dst[edge];
        if (vertexDegrees_s2[neighbor] > 0){
            for(unsigned int neighborEdge = graph.srcPtr[neighbor]; neighborEdge < graph.srcPtr[neighbor + 1]; ++neighborEdge) {
                unsigned int neighborOfNeighbor = graph.dst[neighborEdge];
                if(vertexDegrees_s2[neighborOfNeighbor] > 0) {
                    ATOMIC_TYPE(atomicSub)(&vertexDegrees_s2[neighborOfNeighbor], 1);
                }
            }
        }
    }
    
    *numDeletedVertices2 += maxDegree;
    __syncthreads();

    for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1] ; edge += blockDim.x) {
        unsigned int neighbor = graph.dst[edge];
        vertexDegrees_s2[neighbor] = -1;
    }
    __syncthreads();
}

__device__ void deleteMaxDegreeVertex(CSRGraph graph, INT_OR_SHORT* vertexDegrees_s, unsigned int* numDeletedVertices, unsigned int maxVertex) {

    if(threadIdx.x == 0){
        vertexDegrees_s[maxVertex] = -1;
    }
    ++(*numDeletedVertices);

    __syncthreads(); 

    for(unsigned int edge = graph.srcPtr[maxVertex] + threadIdx.x; edge < graph.srcPtr[maxVertex + 1]; edge += blockDim.x) {
        unsigned int neighbor = graph.dst[edge];
        if(vertexDegrees_s[neighbor] > 0) {
            --vertexDegrees_s[neighbor];
        }
    }
    __syncthreads();
}

__device__ unsigned int leafReductionRule(unsigned int vertexNum, INT_OR_SHORT *vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, unsigned int left, unsigned int right) {

    __shared__ unsigned int numberDeleted;
    __shared__ bool graphHasChanged;

    volatile INT_OR_SHORT * markedForDeletion = shared_mem;
    if (threadIdx.x==0){
        numberDeleted = 0;
    }
    unsigned int start = threadIdx.x + left;
    do{
        volatile INT_OR_SHORT * vertexDegrees_v = vertexDegrees_s;
        __syncthreads();
                
        for (unsigned int vertex = start ; vertex < right+1; vertex += blockDim.x){
            markedForDeletion[vertex] = 0;
        }
        if (threadIdx.x==0){
            graphHasChanged = false;
        }
        
        __syncthreads();

        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            INT_OR_SHORT degree = vertexDegrees_v[vertex];
            if (degree == 1){
                for(unsigned int edge = graph.srcPtr[vertex] ; edge < graph.srcPtr[vertex + 1]; ++edge) {
                    unsigned int neighbor = graph.dst[edge];
                    INT_OR_SHORT neighborDegree = vertexDegrees_v[neighbor];
                    if(neighborDegree>0){
                        if(neighborDegree > 1 || (neighborDegree == 1 && neighbor<vertex)) {
                            markedForDeletion[neighbor]=1;
                        }
                        break;
                    }
                }
            }
        }
        
        __syncthreads();
        
        for (unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                graphHasChanged = true;
                vertexDegrees_v[vertex] = -1;
                atomicAdd(&numberDeleted,1);
            }
        }
        
        __syncthreads();
        
        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex + 1]; edge++){
                    unsigned int neighbor = graph.dst[edge];
                    if (vertexDegrees_v[neighbor] > 0){
                        ATOMIC_TYPE(atomicSub)(&vertexDegrees_s[neighbor],1);
                    }
                }
            }
        }
    
    }while(graphHasChanged);

    __syncthreads();

    return numberDeleted;
}

__device__ unsigned int cycleReductionRule(unsigned int vertexNum, INT_OR_SHORT *vertexDegrees_s, CSRGraph graph, INT_OR_SHORT * shared_mem, unsigned int left, unsigned int right) {
    __shared__ unsigned int numberDeleted;
    if(threadIdx.x == 0) {
        numberDeleted = 0;
    }
    volatile INT_OR_SHORT * markedForDeletion = shared_mem;
    INT_OR_SHORT * vertexDegrees_v = vertexDegrees_s;
    unsigned int start = threadIdx.x + left;
    for (unsigned int vertex = start; vertex < right+1; vertex += blockDim.x){
        markedForDeletion[vertex] = 0;
    }
    __syncthreads();

    for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
        INT_OR_SHORT degree = vertexDegrees_v[vertex];
        if(degree != 2) {
            continue;
        }
        bool secondFound = false;
        bool big_brother = false;
        unsigned int last;
        unsigned int second;
        for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
            unsigned int neigh = graph.dst[edge];
            if(vertexDegrees_v[neigh]>0) {
                if(neigh<vertex) {
                    big_brother = true;
                    break;
                }
                if(secondFound) {
                    last = neigh;
                    break;
                } else {
                    secondFound = true;
                    second = neigh;
                }
            }
        }

        if(big_brother) {
            continue;
        }
        
        if(vertexDegrees_v[last] != 2) {
                continue;
        }

        unsigned int first = vertex;
        bool isCycle = true;
        bool done = false;

        while(isCycle) {
            if (vertexDegrees_v[second] != 2) {
                break;
            }
            for(unsigned int edge=graph.srcPtr[second]; edge<graph.srcPtr[second+1]; ++edge) {
                unsigned int neigh = graph.dst[edge];
                if(neigh!=first && vertexDegrees_v[neigh]>0) {
                    if(neigh<vertex || vertexDegrees_v[neigh] != 2) {
                        isCycle = false;
                        break;
                    } else if (neigh!=last) {
                        first = second;
                        second = neigh;
                        break;
                    } else {
                        done = true;
                        break;
                    }
                }
            }
            if(done) {
                markedForDeletion[vertex] = 1;
                unsigned int pointer = vertex;
                unsigned int prev = last;
                unsigned int cycleSize = 1;
                while(pointer!=last) {
                    ++cycleSize;
                    for(unsigned int e = graph.srcPtr[pointer]; e<graph.srcPtr[pointer+1]; ++e) {
                        unsigned int n = graph.dst[e];
                        if(n!=prev && vertexDegrees_v[n]>0) {
                            markedForDeletion[n] = 1;
                            prev = pointer;
                            pointer = n;
                            break;
                        }
                    }
                }
                atomicAdd(&numberDeleted,(cycleSize+1)/2);
                // For Debugging Purposes
                //printf("Cycle Size: %d\n",cycleSize);
                break;
            }
        }
    }
    __syncthreads();
   
    for (unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
        if(markedForDeletion[vertex]) { 
            vertexDegrees_v[vertex] = -1;
        }
    }

   __syncthreads();
   return numberDeleted;
}

__device__ unsigned int cliqueReductionRule(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT * shared_mem, unsigned int left, unsigned int right) {
    __shared__ unsigned int numberDeleted;
    if(threadIdx.x == 0) {
        numberDeleted = 0;
    }
    volatile INT_OR_SHORT * markedForDeletion = shared_mem;
    volatile INT_OR_SHORT * vertexDegrees_v = vertexDegrees_s;
    unsigned int start = threadIdx.x + left;
    for (unsigned int vertex = start; vertex < right+1; vertex += blockDim.x){
        markedForDeletion[vertex] = 0;
    }
    __syncthreads();
    
    for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
        INT_OR_SHORT degree = vertexDegrees_v[vertex];
        unsigned int k = degree+1;
        if(degree>2) {
            bool inClique = true;
            for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
                unsigned int neigh = graph.dst[edge];
                if(vertexDegrees_v[neigh]>0) {
                    if(neigh<vertex || vertexDegrees_v[neigh]!=k-1) {
                        inClique = false;
                        break;
                    }
                }
            }
            if(inClique) {
                for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
                    unsigned int neigh = graph.dst[edge];

                    if(vertexDegrees_v[neigh]>0) {
                        for(unsigned int edgeN = graph.srcPtr[neigh]; edgeN<graph.srcPtr[neigh+1]; ++edgeN) {
                            unsigned int neighN = graph.dst[edgeN];

                            if(vertexDegrees_v[neighN]>0 && neighN!=vertex) {
                                bool found = false;
                                for(unsigned int edgeNN = graph.srcPtr[vertex]; edgeNN<graph.srcPtr[vertex+1]; ++edgeNN) {
                                    unsigned int neighNN = graph.dst[edgeNN];
                                    if(vertexDegrees_v[neighNN]>0 && neighN==neighNN) {
                                        found  = true;
                                        break;
                                    }
                                }
                                if(!found) {
                                    inClique = false;
                                    break;
                                }
                            }
                        }
                        if(!inClique) {
                            break;
                        }
                    }
                }   
            }
            if(inClique) {
                atomicAdd(&numberDeleted,k-1);
                markedForDeletion[vertex] = 1;
                for(unsigned int edge = graph.srcPtr[vertex]; edge<graph.srcPtr[vertex+1]; ++edge) {
                    unsigned int neigh = graph.dst[edge];
                    if (vertexDegrees_v[neigh]>0) {
                        markedForDeletion[neigh] = 1;
                    }
                }
                // For Debugging Purposes
                //printf("Clique Size: %d\n",k);
            }
        }
    }
    __syncthreads();

    for (unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
        if(markedForDeletion[vertex]) { 
            vertexDegrees_v[vertex] = -1;
        }
    }

   __syncthreads();
   return numberDeleted;
}

__device__ unsigned int bfsCC_StackOnly(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, bool compNode, unsigned int minimum_s, unsigned int* numDeletedVertices, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, volatile bool * stackCompNode, int* stackTop, unsigned int stackSize, unsigned int left, unsigned int right) {

    __shared__ int num_components;
    __shared__ int found_new_level;
    __shared__ bool done;
    __shared__ int select_comp;
    __shared__ bool exceedFlag;
    __shared__ int compSize;
    __shared__ int not_Clique_Cycle;
    __shared__ int compStartingVertexDegree;
    unsigned int parentIndex;
    volatile INT_OR_SHORT* components = shared_mem;
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
        num_components = 0;
        exceedFlag = false;
    }
    __syncthreads();

    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = 0;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();
    
    if (done) {return 0;}

    startTime(PUSH_TO_STACK, blockCounters);
    pushStack(vertexNum, (INT_OR_SHORT*)components, numDeletedVertices, arrayIndex, compNode, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, stackTop, true);
    endTime(PUSH_TO_STACK, blockCounters);
    maxDepth(*stackTop, blockCounters);
    parentIndex = *stackTop;
     __syncthreads();

    do {
        __syncthreads();
        if(threadIdx.x == 0) {
            select_comp = 0;
            compSize = 1;
            not_Clique_Cycle = 0;
            ++num_components;
            done = true;
        }
        __syncthreads();

        for (unsigned int i = start; i<right+1 && !select_comp; i+=blockDim.x) {
            if(components[i] == 0) {
                if(atomicCAS(&select_comp,0,1) == 0) {
                    components[i] = 1;
                    compStartingVertexDegree = vertexDegrees_s[i];
                }
            }
        }
        __syncthreads();

        do {
            __syncthreads();
            if (threadIdx.x == 0) {
                found_new_level = 0;
            }
             __syncthreads();
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] == 0) {
                    for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                        unsigned int neigh = graph.dst[edge];
                        if (vertexDegrees_s[neigh]>0) {
                            if(components[neigh] == 1) {
                                components[vertex] = 1;
                                atomicAdd(&compSize,1);
                                found_new_level = 1;
                                if (vertexDegrees_s[vertex]!=compStartingVertexDegree) {
                                    not_Clique_Cycle = 1;
                                }
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
        } while (found_new_level);
        
        if (!not_Clique_Cycle) {
            if (compStartingVertexDegree == 2) {
                *numDeletedVertices += (compSize+1)/2;
                if (threadIdx.x == 0) {
                    stackNumDeletedVertices[parentIndex] += (compSize+1)/2;
                    --num_components;
                }
            } else if (compStartingVertexDegree == compSize-1) {
                *numDeletedVertices += compSize-1;
                if (threadIdx.x == 0) {
                    stackNumDeletedVertices[parentIndex] += compSize-1;
                    --num_components;
                }
            } else {
                 __syncthreads();
                if (threadIdx.x == 0) {
                    not_Clique_Cycle = 1;
                }
            }
        }
        __syncthreads();

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 0) {
                done = false;
                break;
            }
        }
        __syncthreads();
        
        if (!not_Clique_Cycle) {
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] > 0){
                    components[vertex] = -1;
                    vertexDegrees_s[vertex] = -1;
                }
            }
            __syncthreads();
                
            if (!done) {
                continue;
            }
            __syncthreads();

            if (num_components==0) {
                --(*stackTop);
                return 0;
            } else if (num_components==1) {
                (*stackTop) -= 2;
                return num_components;
            }
            __syncthreads();

            break;
        }
        __syncthreads();
        
        if(done && num_components == 1) {
            --(*stackTop);
            return num_components;
        }
        
        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 1) {
                components[vertex] = vertexDegrees_s[vertex];
            }
        }
        __syncthreads();
         
        unsigned int numDeletedVertices2 = 0;
        startTime(PUSH_TO_STACK, blockCounters);
        pushStack(vertexNum, (INT_OR_SHORT*)components, &numDeletedVertices2, parentIndex, 1, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, stackTop, true);
        endTime(PUSH_TO_STACK,blockCounters);
        maxDepth(*stackTop, blockCounters);
        __syncthreads();
        
        if (threadIdx.x==0 && *stackTop==stackSize-1) {
            exceedFlag = true;
        }
        __syncthreads();
        
        if (exceedFlag) {
            *stackTop = parentIndex-1;
            *numDeletedVertices = minimum_s;
            return 0; //no need for this node
        }

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x){
            if(components[vertex] > 0){
                components[vertex] = -1;
            }
        }
        __syncthreads();

    } while(!done);
    __syncthreads();
    
    if (threadIdx.x==0) {
        done = false;
        #if USE_SHORT_DEGREE
        saveIntInShortArray(&stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum+(long long)3], num_components-1);
        #else
        stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum+(long long)3] = num_components-1;
        #endif
        if (minimum_s>*numDeletedVertices+num_components) {
            #if USE_SHORT_DEGREE
            saveIntInShortArray(&stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum], minimum_s-*numDeletedVertices-num_components+1);
            #else
            stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum] = minimum_s-*numDeletedVertices-num_components+1;
            #endif
        } else {
            done = true;
        }
    }
    __syncthreads();
    
    if (done) {
        *stackTop = parentIndex-1;
        *numDeletedVertices = minimum_s;
        return 0; //no need for this node
    }
    __syncthreads();

    return num_components;
}

__device__ unsigned int bfsCC_param_StackOnly(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, bool compNode, unsigned int minimum_s, unsigned int* numDeletedVertices, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, volatile bool * stackCompNode, int* stackTop, unsigned int stackSize, unsigned int * k, unsigned int left, unsigned int right) {

    __shared__ int num_components;
    __shared__ int found_new_level;
    __shared__ bool done;
    __shared__ int select_comp;
    __shared__ bool exceedFlag;
    __shared__ int compSize;
    __shared__ int not_Clique_Cycle;
    __shared__ int compStartingVertexDegree;
    unsigned int parentIndex;
    volatile INT_OR_SHORT* components = shared_mem;
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
        num_components = 0;
        exceedFlag = false;
    }
    __syncthreads();

    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = 0;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();
    
    if (done) {return 0;}

    startTime(PUSH_TO_STACK, blockCounters);
    pushStack(vertexNum, (INT_OR_SHORT*)components, numDeletedVertices, arrayIndex, compNode, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, stackTop, true);
    endTime(PUSH_TO_STACK, blockCounters);
    maxDepth(*stackTop, blockCounters);
    parentIndex = *stackTop;
     __syncthreads();

    do {
        __syncthreads();
        if(threadIdx.x == 0) {
            select_comp = 0;
            compSize = 1;
            not_Clique_Cycle = 0;
            ++num_components;
            done = true;
        }
        __syncthreads();

        for (unsigned int i = start; i<right+1 && !select_comp; i+=blockDim.x) {
            if(components[i] == 0) {
                if(atomicCAS(&select_comp,0,1) == 0) {
                    components[i] = 1;
                    compStartingVertexDegree = vertexDegrees_s[i];
                }
            }
        }
        __syncthreads();

        do {
            __syncthreads();
            if (threadIdx.x == 0) {
                found_new_level = 0;
            }
             __syncthreads();
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] == 0) {
                    for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                        unsigned int neigh = graph.dst[edge];
                        if (vertexDegrees_s[neigh]>0) {
                            if(components[neigh] == 1) {
                                components[vertex] = 1;
                                atomicAdd(&compSize,1);
                                found_new_level = 1;
                                if (vertexDegrees_s[vertex]!=compStartingVertexDegree) {
                                    not_Clique_Cycle = 1;
                                }
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
        } while (found_new_level);
        
        if (!not_Clique_Cycle) {
            if (compStartingVertexDegree == 2) {
                *numDeletedVertices += (compSize+1)/2;
                if (threadIdx.x == 0) {
                    stackNumDeletedVertices[parentIndex] += (compSize+1)/2;
                    --num_components;
                }
            } else if (compStartingVertexDegree == compSize-1) {
                *numDeletedVertices += compSize-1;
                if (threadIdx.x == 0) {
                    stackNumDeletedVertices[parentIndex] += compSize-1;
                    --num_components;
                }
            } else {
                 __syncthreads();
                if (threadIdx.x == 0) {
                    not_Clique_Cycle = 1;
                }
            }
        }
        __syncthreads();

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 0) {
                done = false;
                break;
            }
        }
        __syncthreads();
        
        if (!not_Clique_Cycle) {
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] > 0){
                    components[vertex] = -1;
                    vertexDegrees_s[vertex] = -1;
                }
            }
            __syncthreads();
                
            if (!done) {
                continue;
            }
            __syncthreads();

            if (num_components==0) {
                --(*stackTop);
                return 0;
            } else if (num_components==1) {
                (*stackTop) -= 2;
                return num_components;
            }
            __syncthreads();

            break;
        }
        __syncthreads();
        
        if(done && num_components == 1) {
            --(*stackTop);
            return num_components;
        }
        
        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 1) {
                components[vertex] = vertexDegrees_s[vertex];
            }
        }
        __syncthreads();
         
        unsigned int numDeletedVertices2 = 0;
        startTime(PUSH_TO_STACK, blockCounters);
        pushStack(vertexNum, (INT_OR_SHORT*)components, &numDeletedVertices2, parentIndex, 1, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, stackCompNode, stackTop, true);
        endTime(PUSH_TO_STACK,blockCounters);
        maxDepth(*stackTop, blockCounters);
        __syncthreads();
        
        if (threadIdx.x==0) {
            if (*stackTop==stackSize-1) {
                exceedFlag = true;
            }
            
        }
        __syncthreads();
        
        if (exceedFlag) {
            *stackTop = parentIndex-1;
            *numDeletedVertices = minimum_s;
            return 0; //no need for this node
        }

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x){
            if(components[vertex] > 0){
                components[vertex] = -1;
            }
        }
        __syncthreads();

    } while(!done);
    __syncthreads();
  
    if (threadIdx.x==0) {  
        for (unsigned int i=1; i<=num_components; ++i) {
            stackNumDeletedVertices[parentIndex] += (int)minimum_s-(int)*numDeletedVertices-i+1;
        }
        done = false;
        #if USE_SHORT_DEGREE
        saveIntInShortArray(&stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum+(long long)3], (int)minimum_s-(int)*numDeletedVertices-num_components+1);
        #else
        stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum+(long long)3] = (int)minimum_s-(int)*numDeletedVertices-num_components+1;
        #endif
        if (minimum_s>*numDeletedVertices+num_components) {
            #if USE_SHORT_DEGREE
            saveIntInShortArray(&stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum], minimum_s-*numDeletedVertices-num_components+1);
            #else
            stackVertexDegrees[(long long)parentIndex*(long long)graph.vertexNum] = minimum_s-*numDeletedVertices-num_components+1;
            #endif
        } else {
            done = true;
        }
    }
    __syncthreads();
    
    if (done) {
        *stackTop = parentIndex-1;
        *numDeletedVertices = minimum_s;
        return 0; //no need for this node
    }
    __syncthreads();

    return num_components;
}

__device__ unsigned int bfs_Hybrid(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, unsigned int minimum, unsigned int numDeletedVertices, CompArray compArray, WorkList<INT_OR_SHORT> workList, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, int* stackTop, unsigned int stackSize, unsigned int compArraySize, unsigned int left, unsigned int right) {
    __shared__ int globIndex;
    __shared__ int num_components;
    __shared__ bool exceedFlag;
    __shared__ bool done;
    __shared__ int found_new_level;
    __shared__ int select_comp;
    __shared__ int parentArrayIndex;
    __shared__ int childArrayIndex;
    __shared__ int nextChildIndex;
    __shared__ int compSize;

    volatile INT_OR_SHORT* components = shared_mem;    
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
    }
    __syncthreads();

    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = 0;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();

    if (done) {return 0;}
    
    if (threadIdx.x == 0) {
        globIndex = atomicOr((int*)compArray.globalArrayIndex,0);
        num_components = 0;
        exceedFlag = false;
    }
    __syncthreads();

    if (globIndex+3>compArraySize) {return 1;}

    do {
        __syncthreads();
        if(threadIdx.x == 0) {
            select_comp = 0;
            ++num_components;
            compSize = 1;
            done = true;
        }
        __syncthreads();

        for (unsigned int i = start; i<right+1 && !select_comp; i+=blockDim.x) {
            if(components[i] == 0) {
                if(atomicCAS(&select_comp,0,1) == 0) {
                    components[i] = 1;                   
                }
            }
        }
        __syncthreads();

        do {
            __syncthreads();
            if (threadIdx.x == 0) {
                found_new_level = 0;
            }
             __syncthreads();
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] == 0) {
                    for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                        unsigned int neigh = graph.dst[edge];
                        if (vertexDegrees_s[neigh]>0) {
                            if(components[neigh] == 1) {
                                components[vertex] = 1;
                                atomicAdd(&compSize,1);
                                found_new_level = 1;
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
        } while (found_new_level);

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 0) {
                done = false;
                break;
            }
        }
        __syncthreads();
        
        if (num_components == 1) {
            if (done) {break;}
            __syncthreads();
            if(threadIdx.x == 0) {
                parentArrayIndex = atomicAdd((int*)compArray.globalArrayIndex,3);
                if (parentArrayIndex<compArraySize-2) {
                    compArray.entries[parentArrayIndex].index = arrayIndex;
                    compArray.entries[parentArrayIndex].minimum = numDeletedVertices;
                    compArray.entries[parentArrayIndex].counter = 1;
                    childArrayIndex = parentArrayIndex+1;
                    nextChildIndex = parentArrayIndex+2;
                } else {
                    done = true;
                }
            }
            __syncthreads();
            if (done) {break;}
        } else {
            if (threadIdx.x == 0) {
                childArrayIndex = nextChildIndex;
                nextChildIndex = atomicAdd((int*)compArray.globalArrayIndex,1);
                if (nextChildIndex>=compArraySize) {
                    done = true;
                }
            }
        }
        __syncthreads();
        
        if (threadIdx.x==0) {
            if (!done) {
                atomicAdd((int*)&compArray.entries[parentArrayIndex].counter, 1);
            } else {
                compSize = 0;
            }
        }
        __syncthreads();

        if (done) {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1 || components[vertex] == 0) {
                    components[vertex] = vertexDegrees_s[vertex];
                    atomicAdd(&compSize,1);
                }
            }
        } else {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1) {
                    components[vertex] = vertexDegrees_s[vertex];
                }
            }
        }
        __syncthreads();

        if(threadIdx.x == 0) {
            compArray.entries[childArrayIndex].index = parentArrayIndex;
            compArray.entries[childArrayIndex].counter = 1;
            if (minimum-numDeletedVertices>num_components) {
                compArray.entries[childArrayIndex].minimum = (compSize-1<minimum-numDeletedVertices-num_components+1)?compSize-1:minimum-numDeletedVertices-num_components+1;
            } else {
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
        }
        __syncthreads();
 
        bool enqueueSuccess;
        unsigned int numDeletedVertices2 = 0;
        if(checkThreshold(workList)) {
            startTime(ENQUEUE,blockCounters);
            enqueueSuccess = enqueue((INT_OR_SHORT*)components, workList, vertexNum, &numDeletedVertices2, childArrayIndex);
        } else  {
            enqueueSuccess = false;
        }
        __syncthreads();

        if(!enqueueSuccess) {
            startTime(PUSH_TO_STACK,blockCounters);
            pushStack(vertexNum, (INT_OR_SHORT*)components, &numDeletedVertices2, childArrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, stackTop, false);        
            endTime(PUSH_TO_STACK,blockCounters);
            maxDepth(*stackTop, blockCounters);
            if (threadIdx.x==0 && *stackTop==stackSize-1) {
                exceedFlag = true;
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
            __syncthreads();
            if (exceedFlag) {--(*stackTop);}
        } else {
            endTime(ENQUEUE,blockCounters);
        }
        __syncthreads();

        if (!done) {
            for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
                if(components[vertex] > 0){
                    components[vertex] = -1;
                }
            }
        }
        __syncthreads();

    } while(!done);

    return num_components;
}

__device__ unsigned int bfsCC_Hybrid(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, unsigned int minimum, unsigned int * numDeletedVertices, CompArray compArray, WorkList<INT_OR_SHORT> workList, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, int* stackTop, unsigned int stackSize, unsigned int compArraySize, unsigned int left, unsigned int right, unsigned int* minimum_original) {
    __shared__ int globIndex;
    __shared__ int num_components;
    __shared__ bool exceedFlag;
    __shared__ bool done;
    __shared__ int found_new_level;
    __shared__ int select_comp;
    __shared__ int parentArrayIndex;
    __shared__ int childArrayIndex;
    __shared__ int nextChildIndex;
    __shared__ int compSize;
    __shared__ int not_Clique_Cycle;
    __shared__ int compStartingVertexDegree;

    volatile INT_OR_SHORT* components = shared_mem;    
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
    }
    __syncthreads();

    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = 0;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();

    if (done) {return 0;}
    
    if (threadIdx.x == 0) {
        globIndex = atomicOr((int*)compArray.globalArrayIndex,0);
        num_components = 0;
        exceedFlag = false;
    }
    __syncthreads();

    if (globIndex+3>compArraySize) {return 1;}

    do {
        __syncthreads();
        if(threadIdx.x == 0) {
            select_comp = 0;
            not_Clique_Cycle = 0;
            ++num_components;
            compSize = 1;
            done = true;
        }
        __syncthreads();

        for (unsigned int i = start; i<right+1 && !select_comp; i+=blockDim.x) {
            if(components[i] == 0) {
                if(atomicCAS(&select_comp,0,1) == 0) {
                    components[i] = 1;
                    compStartingVertexDegree = vertexDegrees_s[i];
                }
            }
        }
        __syncthreads();

        do {
            __syncthreads();
            if (threadIdx.x == 0) {
                found_new_level = 0;
            }
             __syncthreads();
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] == 0) {
                    for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                        unsigned int neigh = graph.dst[edge];
                        if (vertexDegrees_s[neigh]>0) {
                            if(components[neigh] == 1) {
                                components[vertex] = 1;
                                atomicAdd(&compSize,1);
                                found_new_level = 1;
                                if (vertexDegrees_s[vertex]!=compStartingVertexDegree) {
                                    not_Clique_Cycle = 1;
                                }
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
        } while (found_new_level);

        if (!not_Clique_Cycle) {
            if (compStartingVertexDegree == 2) {
                *numDeletedVertices += (compSize+1)/2;
                if (threadIdx.x == 0) {
                    if (num_components>1) {
                        atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum,(compSize+1)/2);  
                    }
                    --num_components;
                }
            } else if (compStartingVertexDegree == compSize-1) {
                *numDeletedVertices += compSize-1;
                if (threadIdx.x == 0) {
                    if (num_components>1) {
                        atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum,compSize-1); 
                    }
                    --num_components;
                }
            } else {
                 __syncthreads();
                if (threadIdx.x == 0) {
                    not_Clique_Cycle = 1;
                }
            }
        }
        __syncthreads();

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 0) {
                done = false;
                break;
            }
        }
        __syncthreads();
        
        if (!not_Clique_Cycle) {
            if (!done) {
                for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                    if(components[vertex] > 0){
                        components[vertex] = -1;
                        vertexDegrees_s[vertex] = -1;
                    }
                }
                __syncthreads();
                continue;
            }

            if (num_components==0) {return 0;} 

            if (threadIdx.x == 0) {
                arrayIndex = parentArrayIndex;
                int numDelVer;
                int counter = atomicSub((int*)&compArray.entries[arrayIndex].counter, 1);
                if (counter==1) {
                    int parentIndex = compArray.entries[arrayIndex].index;
                    atomicAdd((int*)&compArray.entries[parentIndex].minimum, compArray.entries[arrayIndex].minimum);
                    int parentCounter = atomicSub((int*)&compArray.entries[parentIndex].counter, 1);
                    if (parentCounter==1) {
                        arrayIndex = compArray.entries[parentIndex].index;
                        numDelVer = atomicOr((int*)&compArray.entries[parentIndex].minimum,0);
                        while (true) {
                            if (arrayIndex>-1) {
                                atomicMin((int*)&compArray.entries[arrayIndex].minimum, numDelVer);
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
                                numDelVer = atomicOr((int*)&compArray.entries[parentIndex].minimum,0);

                            } else {
                                atomicMin(minimum_original, numDelVer);
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
            return num_components+1; //although num_components maybe 1, it will run on the compArray
        }
        __syncthreads();

        if (num_components == 1) {
            if (done) {break;}
            __syncthreads();
            if(threadIdx.x == 0) {
                parentArrayIndex = atomicAdd((int*)compArray.globalArrayIndex,3);
                if (parentArrayIndex<compArraySize-2) {
                    compArray.entries[parentArrayIndex].index = arrayIndex;
                    compArray.entries[parentArrayIndex].minimum = *numDeletedVertices;
                    compArray.entries[parentArrayIndex].counter = 1;
                    childArrayIndex = parentArrayIndex+1;
                    nextChildIndex = parentArrayIndex+2;
                } else {
                    done = true;
                }
            }
            __syncthreads();
            if (done) {break;}
        } else {
            if (threadIdx.x == 0) {
                childArrayIndex = nextChildIndex;
                nextChildIndex = atomicAdd((int*)compArray.globalArrayIndex,1);
                if (nextChildIndex>=compArraySize) {
                    done = true;
                }
            }
        }
        __syncthreads();
        
        if (threadIdx.x==0) {
            if (!done) {
                atomicAdd((int*)&compArray.entries[parentArrayIndex].counter, 1);
            } else {
                compSize = 0;
            }
        }
        __syncthreads();

        if (done) {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1 || components[vertex] == 0) {
                    components[vertex] = vertexDegrees_s[vertex];
                    atomicAdd(&compSize,1);
                }
            }
        } else {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1) {
                    components[vertex] = vertexDegrees_s[vertex];
                }
            }
        }
        __syncthreads();

        if(threadIdx.x == 0) {
            compArray.entries[childArrayIndex].index = parentArrayIndex;
            compArray.entries[childArrayIndex].counter = 1;
            if (minimum>*numDeletedVertices+num_components) {
                compArray.entries[childArrayIndex].minimum = (compSize-1<minimum-*numDeletedVertices-num_components+1)?compSize-1:minimum-*numDeletedVertices-num_components+1;
            } else {
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
        }
        __syncthreads();

        bool enqueueSuccess;
        unsigned int numDeletedVertices2 = 0;
        if(checkThreshold(workList)) {
            startTime(ENQUEUE,blockCounters);
            enqueueSuccess = enqueue((INT_OR_SHORT*)components, workList, vertexNum, &numDeletedVertices2, childArrayIndex);
        } else  {
            enqueueSuccess = false;
        }
        __syncthreads();

        if(!enqueueSuccess) {
            startTime(PUSH_TO_STACK,blockCounters);
            pushStack(vertexNum, (INT_OR_SHORT*)components, &numDeletedVertices2, childArrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, stackTop, false);        
            endTime(PUSH_TO_STACK,blockCounters);
            maxDepth(*stackTop, blockCounters);
            if (threadIdx.x==0 && *stackTop==stackSize-1) {
                exceedFlag = true;
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
            __syncthreads();
            if (exceedFlag) {--(*stackTop);}
        } else {
            endTime(ENQUEUE,blockCounters);
        }
        __syncthreads();

        if (!done) {
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] > 0){
                    components[vertex] = -1;
                }
            }
        }
        __syncthreads();

    } while(!done);
    
    __syncthreads();
    
    return num_components;
}

__device__ unsigned int bfsConnectedComp_Hybrid(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, unsigned int minimum, unsigned int numDeletedVertices, CompArray compArray, WorkList<INT_OR_SHORT> workList, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, int* stackTop, unsigned int stackSize, unsigned int compArraySize, unsigned int left, unsigned int right) {

    __shared__ int globIndex;
    __shared__ int num_components;
    __shared__ bool exceedFlag;
    __shared__ int select_comp1;
    __shared__ int select_comp2;
    __shared__ int comp1;
    __shared__ int comp2;
    __shared__ bool done;
    __shared__ int found_new_level;
    __shared__ int parentArrayIndex;
    __shared__ int childArrayIndex;
    __shared__ int nextChildIndex;
    __shared__ int compSize;

    volatile INT_OR_SHORT* components = shared_mem;
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
    }
    __syncthreads();
    
    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = vertex;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();

    if (done) {return 0;}
    
    if (threadIdx.x == 0) {
        globIndex = atomicOr((int*)compArray.globalArrayIndex,0);
        num_components = 0;
        select_comp1 = 0;
        select_comp2 = 0;
        exceedFlag = false;
    }
    __syncthreads();

    if (globIndex+3>compArraySize) {
        return 1;
    }
    __syncthreads();

    do {
        __syncthreads();
        if (threadIdx.x == 0) {
            found_new_level = 0;
        }
         __syncthreads();
        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex]>-1) {
                for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                    unsigned int neigh = graph.dst[edge];
                    if (vertexDegrees_s[neigh]>0) {
                        if(components[neigh] < components[vertex]) {
                            components[vertex] = components[neigh];
                            found_new_level = 1;
                        }
                    }
                }
            }
        }
        __syncthreads();
    } while (found_new_level);
        
    for (unsigned int i = start; i < right+1 && !select_comp1; i+=blockDim.x) {
        if(components[i]>-1) {
            if(atomicCAS(&select_comp1,0,1) == 0) {
                comp1 = components[i];                   
            }
        }
    }
    __syncthreads();

    for (unsigned int i = start; i < right+1 && !select_comp2; i+=blockDim.x) {
        if(components[i]>-1 && components[i] != comp1) {
            if(atomicCAS(&select_comp2,0,1) == 0) {
                comp2 = components[i];                   
            }
        }
    }
    __syncthreads();

    if (threadIdx.x==0 && !select_comp2) {
        done = true;
    }
    __syncthreads();

    if (done) {return 1;}
    __syncthreads();

    if(threadIdx.x == 0) {
        parentArrayIndex = atomicAdd((int*)compArray.globalArrayIndex,3);
        if (parentArrayIndex<compArraySize-2) {
            compArray.entries[parentArrayIndex].index = arrayIndex;
            compArray.entries[parentArrayIndex].minimum = numDeletedVertices;
            compArray.entries[parentArrayIndex].counter = 1;
            childArrayIndex = parentArrayIndex+1;
            nextChildIndex = parentArrayIndex+2;
        } else {
            done = true;
        }
    }
    __syncthreads();

    if (done) {return 1;}
    __syncthreads();

    while (true) {
        __syncthreads();
        if (threadIdx.x==0) {
            select_comp2 = 0;
            ++num_components;
            compSize = 0;
            if (!done) {
                atomicAdd((int*)&compArray.entries[parentArrayIndex].counter, 1);
            }

            compArray.entries[childArrayIndex].index = parentArrayIndex;
            compArray.entries[childArrayIndex].counter = 1;
            if (minimum-numDeletedVertices>num_components) {
                compArray.entries[childArrayIndex].minimum = minimum-numDeletedVertices-num_components+1;
            } else {
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
        }
        __syncthreads();
        
        bool enqueueSuccess;
        unsigned int numDeletedVertices2 = 0;
        if(checkThreshold(workList)) {
            startTime(ENQUEUE,blockCounters);
            enqueueSuccess = enqueue_connected_comp((INT_OR_SHORT*)vertexDegrees_s, (INT_OR_SHORT*)components, comp1, &compSize, done, workList, vertexNum, &numDeletedVertices2, childArrayIndex, compArray);
        } else  {
            enqueueSuccess = false;
        }
        __syncthreads();

        if(!enqueueSuccess) {
            startTime(PUSH_TO_STACK,blockCounters);
            pushStack_connected_comp(vertexNum, (INT_OR_SHORT*)vertexDegrees_s, (INT_OR_SHORT*)components, comp1, &compSize, done, &numDeletedVertices2, childArrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, stackTop, false, compArray); 
            endTime(PUSH_TO_STACK,blockCounters);
            maxDepth(*stackTop, blockCounters);
            if (threadIdx.x==0 && *stackTop==stackSize-1) {
                exceedFlag = true;
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
            __syncthreads();
            if (exceedFlag) {--(*stackTop);}
        } else {
            endTime(ENQUEUE,blockCounters);
        }
        __syncthreads();
        
        if(done) {break;}
        __syncthreads();
        
        if (threadIdx.x==0) {
            comp1 = comp2;
        }
        __syncthreads();

        for (unsigned int i = start; i < right+1 && !select_comp2; i+=blockDim.x) {
            if(components[i]>-1 && components[i] != comp1) {
                if(atomicCAS(&select_comp2,0,1) == 0) {
                    comp2 = components[i];                   
                }
            }
        }
        __syncthreads();
        
        if (threadIdx.x == 0) {
            if (!select_comp2) {
                done = true;
            }
            childArrayIndex = nextChildIndex;
            nextChildIndex = atomicAdd((int*)compArray.globalArrayIndex,1);
            if (nextChildIndex>=compArraySize) {
                done = true;
            }
        }
        __syncthreads();
    }
    return num_components;
}

__device__ unsigned int bfsCC_Param_Hybrid(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, int arrayIndex, unsigned int minimum, unsigned int* numDeletedVertices, CompArray compArray, WorkList<INT_OR_SHORT> workList, Counters* blockCounters, volatile INT_OR_SHORT * stackVertexDegrees, volatile unsigned int * stackNumDeletedVertices, volatile int * stackArrayIndex, int* stackTop, unsigned int stackSize, unsigned int compArraySize, unsigned int * k, unsigned int * kFound, unsigned int left, unsigned int right) {

    __shared__ int globIndex;
    __shared__ int num_components;
    __shared__ bool exceedFlag;
    __shared__ bool done;
    __shared__ int found_new_level;
    __shared__ int select_comp;
    __shared__ int parentArrayIndex;
    __shared__ int childArrayIndex;
    __shared__ int nextChildIndex;
    __shared__ int compSize;
    __shared__ int not_Clique_Cycle;
    __shared__ int compStartingVertexDegree;

    volatile INT_OR_SHORT* components = shared_mem;    
    unsigned int start = threadIdx.x + left;
    
    if (threadIdx.x == 0) {
        done = true;
    }
    __syncthreads();

    for(unsigned int vertex = threadIdx.x; vertex < graph.vertexNum; vertex+=blockDim.x) {
        if(vertexDegrees_s[vertex] > 0) {
            components[vertex] = 0;
            done = false;
        } else {
            components[vertex] = -1;
        }
    }
    __syncthreads();

    if (done) {return 0;}
    
    if (threadIdx.x == 0) {
        globIndex = atomicOr((int*)compArray.globalArrayIndex,0);
        num_components = 0;
        exceedFlag = false;
    }
    __syncthreads();

    if (globIndex+3>compArraySize) {return 1;}

    do {
        __syncthreads();
        if(threadIdx.x == 0) {
            select_comp = 0;
            not_Clique_Cycle = 0;
            ++num_components;
            compSize = 1;
            done = true;
        }
        __syncthreads();

        for (unsigned int i = start; i<right+1 && !select_comp; i+=blockDim.x) {
            if(components[i] == 0) {
                if(atomicCAS(&select_comp,0,1) == 0) {
                    components[i] = 1;
                    compStartingVertexDegree = vertexDegrees_s[i];
                }
            }
        }
        __syncthreads();

        do {
            __syncthreads();
            if (threadIdx.x == 0) {
                found_new_level = 0;
            }
             __syncthreads();
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] == 0) {
                    for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex+1]; ++edge) {
                        unsigned int neigh = graph.dst[edge];
                        if (vertexDegrees_s[neigh]>0) {
                            if(components[neigh] == 1) {
                                components[vertex] = 1;
                                atomicAdd(&compSize,1);
                                found_new_level = 1;
                                if (vertexDegrees_s[vertex]!=compStartingVertexDegree) {
                                    not_Clique_Cycle = 1;
                                }
                                break;
                            }
                        }
                    }
                }
            }
            __syncthreads();
        } while (found_new_level);

        if (!not_Clique_Cycle) {
            if (compStartingVertexDegree == 2) {
                *numDeletedVertices += (compSize+1)/2;
                if (threadIdx.x == 0) {
                    if (num_components>1) {
                        atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum,(compSize+1)/2); 
                    }
                    --num_components;
                }
            } else if (compStartingVertexDegree == compSize-1) {
                *numDeletedVertices += compSize-1;
                if (threadIdx.x == 0) {
                    if (num_components>1) {
                        atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum,compSize-1); 
                    }
                    --num_components;
                }
            } else {
                 __syncthreads();
                if (threadIdx.x == 0) {
                    not_Clique_Cycle = 1;
                }
            }
        }
        __syncthreads();

        for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
            if(components[vertex] == 0) {
                done = false;
                break;
            }
        }
        __syncthreads();
        
        if (!not_Clique_Cycle) {
            if (!done) {
                for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                    if(components[vertex] > 0){
                        components[vertex] = -1;
                        vertexDegrees_s[vertex] = -1;
                    }
                }
                __syncthreads();
                continue;
            }

            if (num_components==0) {return 0;}
            
            if (threadIdx.x == 0) {
                int theArrayIndex = 0;
                int numDelVer = 0;
                unsigned int compMin = *k+1;
                unsigned int iterationCounter = 0;
                int parentIndex = parentArrayIndex;
                while (true) {
                    if (theArrayIndex>-1) {
                        if (iterationCounter>0) {
                            compMin = atomicMin((int*)&compArray.entries[theArrayIndex].minimum, numDelVer);
                            if (compMin<=numDelVer) {
                                break;
                            }
                            parentIndex = compArray.entries[theArrayIndex].index;
                        }
                        atomicSub((int*)&compArray.entries[parentIndex].minimum, compMin-numDelVer);
                        theArrayIndex = compArray.entries[parentIndex].index;
                        numDelVer = compArray.entries[parentIndex].minimum;
                    } else {
                        if(numDelVer<=*k) {
                            atomicOr(kFound,1);
                        }
                        // For Debugging Purposes
                        //printf("numDel = %d\n",numDelVer);
                        break;
                    }
                    ++iterationCounter;
                }
            }
            __syncthreads();
            return num_components+1; //although num_components maybe 1, it will run on the compArray
        }
        __syncthreads();
        
        if (num_components == 1) {
            if (done) {break;}
            __syncthreads();
            if(threadIdx.x == 0) {
                parentArrayIndex = atomicAdd((int*)compArray.globalArrayIndex,3);
                if (parentArrayIndex<compArraySize-2) {
                    compArray.entries[parentArrayIndex].index = arrayIndex;
                    compArray.entries[parentArrayIndex].minimum = *numDeletedVertices+*k+1;
                    childArrayIndex = parentArrayIndex+1;
                    nextChildIndex = parentArrayIndex+2;
                } else {
                    done = true;
                }
            }
            __syncthreads();
            if (done) {break;}
        } else {
            if (threadIdx.x == 0) {
                childArrayIndex = nextChildIndex;
                nextChildIndex = atomicAdd((int*)compArray.globalArrayIndex,1);
                if (nextChildIndex>=compArraySize) {
                    done = true;
                }
            }
        }
        __syncthreads();
        
        if (done) {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1 || components[vertex] == 0) {
                    components[vertex] = vertexDegrees_s[vertex];
                    atomicAdd(&compSize,1);
                }
            }
        } else {
            for(unsigned int vertex = start; vertex<right+1; vertex+=blockDim.x) {
                if(components[vertex] == 1) {
                    components[vertex] = vertexDegrees_s[vertex];
                }
            }
        }
        __syncthreads();

        if(threadIdx.x == 0) {
            compArray.entries[childArrayIndex].index = parentArrayIndex;
            if (minimum>*numDeletedVertices+num_components) {
                compArray.entries[childArrayIndex].minimum = (compSize-1<minimum-*numDeletedVertices-num_components+1)?compSize-1:minimum-*numDeletedVertices-num_components+1;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum,compArray.entries[childArrayIndex].minimum);
            } else {
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, *k+1);
                done = true;
                ++num_components;
            }
        }
        __syncthreads();
        
        if (threadIdx.x==0) {
            if (done) {
                atomicSub((int*)&compArray.entries[parentArrayIndex].minimum, *k+1);
            }
        }
        __syncthreads();
 
        bool enqueueSuccess;
        unsigned int numDeletedVertices2 = 0;
        if(checkThreshold(workList)) {
            startTime(ENQUEUE,blockCounters);
            enqueueSuccess = enqueue((INT_OR_SHORT*)components, workList, vertexNum, &numDeletedVertices2, childArrayIndex);
        } else  {
            enqueueSuccess = false;
        }
        __syncthreads();

        if(!enqueueSuccess) {
            startTime(PUSH_TO_STACK,blockCounters);
            pushStack(vertexNum, (INT_OR_SHORT*)components, &numDeletedVertices2, childArrayIndex, NULL, stackVertexDegrees, stackNumDeletedVertices, stackArrayIndex, NULL, stackTop, false);        
            endTime(PUSH_TO_STACK,blockCounters);
            maxDepth(*stackTop, blockCounters);
            if (threadIdx.x==0 && *stackTop==stackSize-1) {
                exceedFlag = true;
                compArray.entries[childArrayIndex].minimum = 0;
                atomicAdd((int*)&compArray.entries[parentArrayIndex].minimum, minimum);
                if (!done) {
                    atomicSub((int*)&compArray.entries[parentArrayIndex].counter, 1);
                }
                done = true;
                ++num_components;
            }
            __syncthreads();
            if (exceedFlag) {--(*stackTop);}
        } else {
            endTime(ENQUEUE,blockCounters);
        }
        __syncthreads();

        if (!done) {
            for(unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x) {
                if(components[vertex] > 0){
                    components[vertex] = -1;
                }
            }
        }
        __syncthreads();

    } while(!done);
 
    return num_components;
}

__device__ unsigned int highDegreeReductionRule(unsigned int vertexNum, INT_OR_SHORT *vertexDegrees_s, CSRGraph graph, INT_OR_SHORT * shared_mem, unsigned int numDeletedVertices, unsigned int minimum, unsigned int left, unsigned int right) {

    __shared__ unsigned int numberDeleted_s;
    __shared__ bool graphHasChanged;

    volatile INT_OR_SHORT * markedForDeletion = shared_mem;
    if (threadIdx.x==0){
        numberDeleted_s = 0;
    }
    unsigned int start = threadIdx.x + left;
    do{
        volatile INT_OR_SHORT * vertexDegrees_v = vertexDegrees_s;
        __syncthreads();
        
        for (unsigned int vertex = start ; vertex < right+1; vertex += blockDim.x){
            markedForDeletion[vertex] = 0;
        }
        if (threadIdx.x==0){
            graphHasChanged = false;
        }
        
        __syncthreads();

        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            INT_OR_SHORT degree = vertexDegrees_v[vertex];
            if (degree > 0 && degree + numDeletedVertices + numberDeleted_s >= minimum){
                markedForDeletion[vertex]=1;
            }
        }
        __syncthreads();
        
        for (unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                graphHasChanged = true;
                vertexDegrees_v[vertex] = -1;
                atomicAdd(&numberDeleted_s,1);
            }
        }
        
        __syncthreads();
                    
        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex + 1]; edge++){
                    unsigned int neighbor = graph.dst[edge];
                    if (vertexDegrees_v[neighbor] > 0) {
                        ATOMIC_TYPE(atomicSub)(&vertexDegrees_s[neighbor],1);
                    }
                }
            }
        }
    
    }while(graphHasChanged);

    __syncthreads();

    return numberDeleted_s;
}


__device__ unsigned int triangleReductionRule(unsigned int vertexNum, INT_OR_SHORT *vertexDegrees_s, CSRGraph graph, INT_OR_SHORT* shared_mem, unsigned int left, unsigned int right) {
    
    __shared__ unsigned int numberDeleted;
    __shared__ bool graphHasChanged;
    
    volatile INT_OR_SHORT * markedForDeletion = shared_mem;
    if (threadIdx.x==0){
        numberDeleted = 0;
        //printf("triangle\n");
    }
    unsigned int start = threadIdx.x + left;
    do{
        volatile INT_OR_SHORT * vertexDegrees_v = vertexDegrees_s;
        __syncthreads();

        for (unsigned int vertex = start ; vertex < right+1; vertex += blockDim.x){
            markedForDeletion[vertex] = 0;
        }

        if (threadIdx.x==0){
            graphHasChanged = false;
        }
        
        __syncthreads();
        
        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            
            INT_OR_SHORT degree = vertexDegrees_v[vertex];
            if (degree == 2){
                unsigned int neighbor1, neighbor2;
                bool foundNeighbor1 = false, keepNeighbors = false;
                for(unsigned int edge = graph.srcPtr[vertex] ; edge < graph.srcPtr[vertex + 1]; ++edge) {
                    unsigned int neighbor = graph.dst[edge];
                    INT_OR_SHORT neighborDegree = vertexDegrees_v[neighbor];
                    if(neighborDegree>0){
                        if(neighborDegree == 1 || neighborDegree == 2 && neighbor < vertex){
                            keepNeighbors = true;
                            break;
                        } else if(!foundNeighbor1){
                            foundNeighbor1 = true;
                            neighbor1 = neighbor;
                        } else {
                            neighbor2 = neighbor;    
                            break;
                        }
                    }
                }

                if(!keepNeighbors) {
                    bool found = binarySearch(graph.dst, graph.srcPtr[neighbor2], graph.srcPtr[neighbor2 + 1] - 1, neighbor1);
                    if(found){
                        // Triangle Found
                        markedForDeletion[neighbor1] = true;
                        markedForDeletion[neighbor2] = true;
                        break;
                    }
                }
            }
        }
        
        __syncthreads();
        
        for (unsigned int vertex = start; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                graphHasChanged = true;
                vertexDegrees_v[vertex] = -1;
                atomicAdd(&numberDeleted,1);
            }
        }
        
        __syncthreads();
        
        for (unsigned int vertex = start ; vertex < right+1; vertex+=blockDim.x){
            if(markedForDeletion[vertex]){ 
                for(unsigned int edge = graph.srcPtr[vertex]; edge < graph.srcPtr[vertex + 1]; edge++){
                    unsigned int neighbor = graph.dst[edge];
                    if (vertexDegrees_v[neighbor] > 0){
                        ATOMIC_TYPE(atomicSub)(&vertexDegrees_s[neighbor],1);
                    }
                }
            }
        }
    
    }while(graphHasChanged);

    __syncthreads();

    return numberDeleted;
}

__device__ void findMaxDegree(unsigned int vertexNum, unsigned int *maxVertex, INT_OR_SHORT *maxDegree, INT_OR_SHORT *vertexDegrees_s, INT_OR_SHORT * shared_mem, unsigned int left, unsigned int right) {
    *maxVertex = 0;
    *maxDegree = 0;
    unsigned int start = threadIdx.x + left;
    for(unsigned int vertex = start; vertex < right+1; vertex += blockDim.x) {
        INT_OR_SHORT degree = vertexDegrees_s[vertex];
        if(degree > *maxDegree){ 
            *maxVertex = vertex;
            *maxDegree = degree;
        }
    }

    // Reduce max degree
    INT_OR_SHORT * vertex_s = shared_mem;
    INT_OR_SHORT * degree_s = &shared_mem[blockDim.x];
    __syncthreads(); 

    #if USE_SHORT_DEGREE
    vertex_s[threadIdx.x] = threadIdx.x;
    #else
    vertex_s[threadIdx.x] = *maxVertex;
    #endif

    degree_s[threadIdx.x] = *maxDegree;
    __syncthreads();

    for(unsigned int stride = blockDim.x/2; stride > 0; stride /= 2) {
        if(threadIdx.x < stride) {
            if(degree_s[threadIdx.x] < degree_s[threadIdx.x + stride]){
                degree_s[threadIdx.x] = degree_s[threadIdx.x + stride];
                vertex_s[threadIdx.x] = vertex_s[threadIdx.x + stride];
            }
        }
        __syncthreads();
    }
    
    *maxDegree = degree_s[0];
    
    #if USE_SHORT_DEGREE
    __shared__ unsigned int tempMaxVertex;
    if (threadIdx.x == vertex_s[0]) {
        tempMaxVertex = *maxVertex;
    }
    __syncthreads();
    *maxVertex = tempMaxVertex;
    
    #else
    *maxVertex = vertex_s[0];
    
    #endif
    __syncthreads();
}

__device__ unsigned int findNumOfEdges(unsigned int vertexNum, INT_OR_SHORT *vertexDegrees_s, INT_OR_SHORT * shared_mem, unsigned int left, unsigned int right) {

    int sumDegree = 0;
    unsigned int start = threadIdx.x + left;
    for(unsigned int vertex = start; vertex < right+1; vertex += blockDim.x) {
        int degree = vertexDegrees_s[vertex];
        if(degree > 0){
            sumDegree += degree;
        }
    }
    __syncthreads();
    INT_OR_SHORT* degree_s = shared_mem;
    
    #if USE_SHORT_DEGREE

    saveIntInShortArray(&degree_s[2*threadIdx.x], sumDegree);
    
    __syncthreads();

    for(unsigned int stride = blockDim.x; stride > 1; stride /= 2) {
        if(2*threadIdx.x < stride) {
            AddIntInShortArray(&degree_s[2*threadIdx.x],readIntFromShortArray(&degree_s[2*threadIdx.x+stride]));
        }
        __syncthreads();
    }
    return readIntFromShortArray(&degree_s[0])/2;

    #else
    
    degree_s[threadIdx.x] = sumDegree;
    
    __syncthreads();
    
    for(unsigned int stride = blockDim.x/2; stride > 0; stride /= 2) {
        if(threadIdx.x < stride) {
            degree_s[threadIdx.x] += degree_s[threadIdx.x + stride];
        }
        __syncthreads();
    }
    return degree_s[0]/2;
    
    #endif
}

#undef INT_OR_SHORT
#undef ATOMIC_TYPE(base)
#endif