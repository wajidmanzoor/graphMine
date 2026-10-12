#ifndef COMPARRAY_H
#define COMPARRAY_H

struct Comp {
    int index;
    int counter;
    int minimum;
};

struct CompArray {
    volatile Comp * entries;
    volatile int * globalArrayIndex;
};

CompArray allocateCompArray(unsigned int sizeAllocation) {
    CompArray compArray;
    volatile Comp * entries_d;
    volatile int * globalArrayIndex_d;

    cudaMalloc((void**) &entries_d, (long long)sizeAllocation * (long long)sizeof(Comp));
    cudaMalloc((void**) &globalArrayIndex_d, sizeof(int));

    compArray.entries = entries_d;
    compArray.globalArrayIndex = globalArrayIndex_d;
    cudaMemset((void*)&globalArrayIndex_d, 0, sizeof(int));

    return compArray;
}

void cudaFreeCompArray(CompArray compArray){
    cudaFree((void*)compArray.entries);
    cudaFree((void*)compArray.globalArrayIndex);
}

#endif