#ifndef STACK_H
#define STACK_H

#include "compArray.cuh"

template <typename INT_OR_SHORT>
struct Stacks{
    volatile INT_OR_SHORT* stacks;
    volatile unsigned int * stacksNumDeletedVertices;
    volatile int * stackArrayIndex;
    volatile bool * stackCompNode;
    int minimum;
};

template <typename INT_OR_SHORT>
__device__ void popStack(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, unsigned int* numDeletedVertices, int* arrayIndex, bool* compNode, volatile INT_OR_SHORT* stackVertexDegrees, volatile unsigned int* stackNumDeletedVertices, volatile int * stackArrayIndex, volatile bool* stackCompNode, int * stackTop, bool isCompNode) {
    for(unsigned int vertex = threadIdx.x; vertex < vertexNum; vertex += blockDim.x) {
        vertexDegrees_s[vertex] = stackVertexDegrees[(long long)(*stackTop)*(long long)vertexNum + (long long)vertex];
    }

    *numDeletedVertices = stackNumDeletedVertices[*stackTop];
    *arrayIndex = stackArrayIndex[*stackTop];
    if (isCompNode) {
        *compNode = stackCompNode[*stackTop];
    }
    
    --(*stackTop);
}

template <typename INT_OR_SHORT>
__device__ void pushStack(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, unsigned int* numDeletedVertices, int arrayIndex, bool compNode, volatile INT_OR_SHORT* stackVertexDegrees, volatile unsigned int* stackNumDeletedVertices, volatile int * stackArrayIndex, volatile bool* stackCompNode, int * stackTop, bool isCompNode) {

    ++(*stackTop);
    for(unsigned int vertex = threadIdx.x; vertex < vertexNum ; vertex += blockDim.x) {
        stackVertexDegrees[(long long)(*stackTop)*(long long)vertexNum + (long long)vertex] = vertexDegrees_s[vertex];
    }
    if(threadIdx.x == 0) {
        stackNumDeletedVertices[*stackTop] = *numDeletedVertices;
        stackArrayIndex[*stackTop] = arrayIndex;
        if (isCompNode) {
            stackCompNode[*stackTop] = compNode;
        }
    }
}

template <typename INT_OR_SHORT>
__device__ void pushStack_connected_comp(unsigned int vertexNum, INT_OR_SHORT* vertexDegrees_s, INT_OR_SHORT* components, unsigned int comp1, int* compSize, bool done, unsigned int* numDeletedVertices, int arrayIndex, bool compNode, volatile INT_OR_SHORT* stackVertexDegrees, volatile unsigned int* stackNumDeletedVertices, volatile int * stackArrayIndex, volatile bool* stackCompNode, int * stackTop, bool isCompNode, CompArray compArray) {

    ++(*stackTop);
    for(unsigned int vertex = threadIdx.x; vertex < vertexNum ; vertex += blockDim.x) {
        if (components[vertex] == comp1 || (done && components[vertex]>-1)) {
            stackVertexDegrees[(long long)(*stackTop)*(long long)vertexNum + (long long)vertex] = vertexDegrees_s[vertex];
            components[vertex] = -1;
            atomicAdd(compSize,1);
        } else {
            stackVertexDegrees[(long long)(*stackTop)*(long long)vertexNum + (long long)vertex] = -1;
        }
    }
    __syncthreads();
    if(threadIdx.x == 0) {
        stackNumDeletedVertices[*stackTop] = *numDeletedVertices;
        stackArrayIndex[*stackTop] = arrayIndex;
        if (isCompNode) {
            stackCompNode[*stackTop] = compNode;
        }
        atomicMin((int*)&compArray.entries[arrayIndex].minimum, *compSize-1);
    }
    __syncthreads();
}

template <typename INT_OR_SHORT>
Stacks<INT_OR_SHORT> allocateStacks(int vertexNum, int numBlocks, unsigned int minimum) {
    Stacks<INT_OR_SHORT> stacks;

    volatile INT_OR_SHORT* stacks_d;
    volatile unsigned int* stacksNumDeletedVertices_d;
    volatile int* stackArrayIndex_d;
    volatile bool* stackCompNode_d;
    cudaMalloc((void**) &stacks_d, (long long)(minimum + 1) * (long long)(vertexNum) * (long long)sizeof(INT_OR_SHORT) * (long long)numBlocks);
    cudaMalloc((void**) &stacksNumDeletedVertices_d, (minimum + 1) * sizeof(unsigned int) * numBlocks);
    cudaMalloc((void**) &stackArrayIndex_d, (minimum + 1) * sizeof(int) * numBlocks);
    cudaMalloc((void**) &stackCompNode_d, (minimum + 1) * sizeof(bool) * numBlocks);

    stacks.stacks = stacks_d;
    stacks.stacksNumDeletedVertices = stacksNumDeletedVertices_d;
    stacks.stackArrayIndex = stackArrayIndex_d;
    stacks.stackCompNode = stackCompNode_d;
    stacks.minimum = minimum;

    return stacks;
}

template <typename INT_OR_SHORT>
void cudaFreeStacks(Stacks<INT_OR_SHORT> stacks) {
    cudaFree((void*)stacks.stacks);
    cudaFree((void*)stacks.stacksNumDeletedVertices);
    cudaFree((void*)stacks.stackArrayIndex);
    cudaFree((void*)stacks.stackCompNode);
}

#endif