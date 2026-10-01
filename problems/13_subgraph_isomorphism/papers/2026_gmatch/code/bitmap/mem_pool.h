#ifndef MEM_POOL_H
#define MEM_POOL_H


#include <cstdint>
#include <assert.h>
#include <cstdlib>
#include "helper.h"
#include "params.h"


#define memPoolBlockIntNum (memPoolBlockSize / sizeof(int))         // # of integers within a block


class MemPool {
    int *head;              // starting address of memory pool
    int *nextAddrBound;     // upper bound of nextAddr
    int *nextAddr;          // address of next available block

public:
    MemPool() {
        cudaCheck(cudaMalloc(&head, memPoolBlockNum * memPoolBlockSize));
        cudaCheck(cudaMemset(head, -1, memPoolBlockNum * memPoolBlockSize));
        nextAddr = head;
        nextAddrBound = head + memPoolBlockNum * memPoolBlockIntNum;
    }

    __device__ __forceinline__ int *
    alloc() {
        int *current;
        int *next;
        do {
            current = (int *)atomicAdd((ull *)&nextAddr, 0);
            next = current + memPoolBlockIntNum;
            if (next >= nextAddrBound) {
                // printf("No more available block in the memory pool. The maximum address allowed for a block is %p, yet the requested address is %p\n",
                //        nextAddrBound, nextAddr);
                return nullptr;
            }
        }
        while (atomicCAS((ull *)&nextAddr, (ull)current, (ull)next) != (ull)current);

        return current;
    }

    __host__ void
    freeAll() {
        nextAddr = head;
    }

    __host__ void
    deallocate() {
        if (head != nullptr) {
            cudaCheck(cudaFree(head));
        }
        head = nullptr;
    }

    __host__ float allocated_block_memory() {
        return (nextAddr - head) * sizeof(int) / 1024.;
    }

    void
    print_meta() {
        printf("+-----------------------------------------+\n");
        printf("| Memory Pool Information                 |\n");
        printf("+-----------------------+-----------------+\n");
        printf("| Head Address          | %-16p|\n", head);
        printf("| Maximum Block Address | %-16p|\n", nextAddrBound);
        printf("| Block Number          | %-16lld|\n", memPoolBlockNum);
        printf("| Block Size (bytes)    | %-16lld|\n", memPoolBlockSize);
        printf("| Used Blocks           | %-16lld|\n", (nextAddr - head) / memPoolBlockIntNum);
        printf("| Used Memory (MB)      | %-16lld|\n", (nextAddr - head) * sizeof(int) / 1024 / 1024ull);
        printf("+-----------------------+-----------------+\n");
    }
};

#endif