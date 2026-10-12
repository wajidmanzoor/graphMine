#ifndef BWDWORKLIST_H
#define BWDWORKLIST_H

#include "config.h"
#include "crown.hpp"
#include "Counters.cuh"
#include "compArray.cuh"

typedef unsigned int Ticket;
typedef unsigned long long int HT;

typedef union {
	struct {int numWaiting; int numEnqueued;};
	unsigned long long int combined;
} Counter;

template <typename INT_OR_SHORT>
struct WorkList{
	unsigned int size;
	unsigned int threshold;
    volatile INT_OR_SHORT* list;
    volatile unsigned int* listNumDeletedVertices;
    volatile int* arrayIndex;
    volatile Ticket *tickets;
    HT *head_tail;
	int* count;
	Counter * counter;
};

template <typename INT_OR_SHORT>
__device__ bool checkThreshold(WorkList<INT_OR_SHORT> workList){

    __shared__ int numEnqueued;
    if (threadIdx.x == 0){
        numEnqueued = atomicOr(&workList.counter->numEnqueued,0);
    }
    __syncthreads();

    if (numEnqueued >= (int)workList.threshold){
        return false;
    } else {
        return true;
    }

}


#if __CUDA_ARCH__ < 700
	__device__ __forceinline__ void backoff()
	{
		__threadfence();
	}

	__device__ __forceinline__ void sleepBWD(unsigned int exp)
	{
		__threadfence();
	}
#else
	__device__ __forceinline__ void backoff()
	{
		__threadfence();
	}

	__device__ __forceinline__ void sleepBWD(unsigned int exp)
	{
		__nanosleep(1<<exp);
	}
#endif

__device__ unsigned int* head(HT* head_tail){
	return reinterpret_cast<unsigned int*>(head_tail) + 1;
}

__device__ unsigned int* tail(HT* head_tail) {
	return reinterpret_cast<unsigned int*>(head_tail);
}

template <typename INT_OR_SHORT>
__device__ void waitForTicket(const unsigned int P, const Ticket number, WorkList<INT_OR_SHORT> workList) {
	while (workList.tickets[P] != number)
	{
		backoff();
	}
}

template <typename INT_OR_SHORT>
__device__ bool ensureDequeue(WorkList<INT_OR_SHORT> workList){
	int Num = atomicOr(workList.count,0);
	bool ensurance = false;
	while (!ensurance && Num > 0) {
		if (atomicSub(workList.count, 1) > 0) {
			ensurance = true;
		}
		else {
			Num = atomicAdd(workList.count, 1) + 1;
		}
	}

	return ensurance;
}

template <typename INT_OR_SHORT>
__device__ bool ensureEnqueue(WorkList<INT_OR_SHORT> workList){
	int Num = atomicOr(workList.count,0);
	bool ensurance = false;
	while (!ensurance && Num < (int)workList.size)
	{
		if (atomicAdd(workList.count, 1) < (int)workList.size)
		{
			ensurance = true;
		}
		else 
		{
			Num = atomicSub(workList.count, 1) - 1;
		}
	}
	
	return ensurance;
}

template <typename INT_OR_SHORT>
__device__ void readData(INT_OR_SHORT* vertexDegree_s, unsigned int * vcSize, int* vcArIdx, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum){	
	__shared__ unsigned int P;
	unsigned int Pos;
	if (threadIdx.x==0){
	Pos = atomicAdd(head(const_cast<HT*>(workList.head_tail)), 1);
	P = Pos % workList.size;
	waitForTicket(P, 2 * (Pos / workList.size) + 1,workList);
	}
	__syncthreads();

	for(unsigned int vertex = threadIdx.x; vertex < vertexNum; vertex += blockDim.x) {
		vertexDegree_s[vertex] = workList.list[(long long)P*(long long)vertexNum + (long long)vertex];
	}

	*vcSize = workList.listNumDeletedVertices[P];
    *vcArIdx = workList.arrayIndex[P];

    __threadfence();
	__syncthreads();

	if (threadIdx.x==0) {
        workList.tickets[P] = 2 * ((Pos + workList.size) / workList.size);
	}
}

template <typename INT_OR_SHORT>
__device__ void putData(INT_OR_SHORT* vertexDegree_s, unsigned int * vcSize, int arrayIndex, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum){
	__shared__ unsigned int P;
	unsigned int Pos;
	unsigned int B;
	if (threadIdx.x==0){
	Pos = atomicAdd(tail(const_cast<HT*>(workList.head_tail)), 1);
	P = Pos % workList.size;
	B = 2 * (Pos /workList.size);
	waitForTicket(P, B, workList);
	}
	__syncthreads();

	for(unsigned int i = threadIdx.x; i < vertexNum; i += blockDim.x) {
		workList.list[(long long)(P)*(long long)(vertexNum) + (long long)i] = vertexDegree_s[i];
	}

	if(threadIdx.x == 0) {
		workList.listNumDeletedVertices[P] = *vcSize;
        workList.arrayIndex[P] = arrayIndex;
	}
	__threadfence();
	__syncthreads();

	if (threadIdx.x==0) {
		workList.tickets[P] = B + 1;
		atomicAdd(&workList.counter->numEnqueued,1);
	}
}

template <typename INT_OR_SHORT>
__device__ void putData_connected_comp(INT_OR_SHORT* vertexDegree_s, INT_OR_SHORT* components, int comp1, int* compSize,  bool done, unsigned int * vcSize, int arrayIndex, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum, CompArray compArray){
	__shared__ unsigned int P;
	unsigned int Pos;
	unsigned int B;
	if (threadIdx.x==0){
	Pos = atomicAdd(tail(const_cast<HT*>(workList.head_tail)), 1);
	P = Pos % workList.size;
	B = 2 * (Pos /workList.size);
	waitForTicket(P, B, workList);
	}
	__syncthreads();

	for(unsigned int i = threadIdx.x; i < vertexNum; i += blockDim.x) {
        if (components[i] == comp1 || (done && components[i]>-1)) {
            workList.list[(long long)(P)*(long long)(vertexNum) + (long long)i] = vertexDegree_s[i];
            components[i] = -1;
            atomicAdd(compSize,1);
        } else {
            workList.list[(long long)(P)*(long long)(vertexNum) + (long long)i] = -1;
        }
	}
    __syncthreads();

	if(threadIdx.x == 0) {
		workList.listNumDeletedVertices[P] = *vcSize;
        workList.arrayIndex[P] = arrayIndex;
        atomicMin((int*)&compArray.entries[arrayIndex].minimum, *compSize-1);
	}
	__threadfence();
	__syncthreads();

	if (threadIdx.x==0) {
		workList.tickets[P] = B + 1;
		atomicAdd(&workList.counter->numEnqueued,1);
	}
}

template <typename INT_OR_SHORT>
__device__ inline bool enqueue(INT_OR_SHORT* vertexDegree_s, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum, unsigned int * vcSize, int arrayIndex) {
	__shared__  bool writeData;
	if (threadIdx.x==0){
		writeData = ensureEnqueue(workList);
	}
	__syncthreads();
	
	if (writeData)
	{
		putData(vertexDegree_s, vcSize, arrayIndex, workList, vertexNum);
	}
	
	return writeData;
}

template <typename INT_OR_SHORT>
__device__ inline bool enqueue_connected_comp(INT_OR_SHORT* vertexDegree_s, INT_OR_SHORT* components, int comp1, int* compSize,  bool done, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum, unsigned int * vcSize, int arrayIndex, CompArray compArray) {
	__shared__  bool writeData;
	if (threadIdx.x==0){
		writeData = ensureEnqueue(workList);
	}
	__syncthreads();
	
	if (writeData)
	{
		putData_connected_comp(vertexDegree_s, components, comp1, compSize, done, vcSize, arrayIndex, workList, vertexNum, compArray);
	}
	
	return writeData;
}

template <typename INT_OR_SHORT>
__device__ inline bool dequeue(INT_OR_SHORT* vertexDegree_s, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum, unsigned int * vcSize, int* vcArIdx) {	
	unsigned int expoBackOff = 0;

	__shared__  bool isWorkDone;
	if (threadIdx.x==0){
		isWorkDone = false;
		atomicAdd(&workList.counter->numWaiting,1);
	}
	__syncthreads();

	__shared__  bool hasData;
	while (!isWorkDone) {

		if (threadIdx.x==0){
			hasData = ensureDequeue(workList);
		}
		__syncthreads();

		if (hasData){
			readData(vertexDegree_s, vcSize, vcArIdx, workList, vertexNum);
			if (threadIdx.x==0){
                Counter tempCounter;
				tempCounter.numWaiting = -1;
				tempCounter.numEnqueued = -2;
				atomicAdd(&workList.counter->combined,tempCounter.combined);
			}
			return true;
		}

		if (threadIdx.x==0){
			Counter tempCounter;
			tempCounter.combined = atomicOr(&workList.counter->combined,0);
			if (tempCounter.numWaiting==gridDim.x && tempCounter.numEnqueued==0){
				isWorkDone=true;
			}
		}
		__syncthreads();
		sleepBWD(expoBackOff++);
	}
	return false;
}

template <typename INT_OR_SHORT>
__device__ inline bool dequeueParameterized(INT_OR_SHORT* vertexDegree_s, WorkList<INT_OR_SHORT> workList, unsigned int vertexNum, unsigned int * vcSize, int* vcArIdx, unsigned int * kFound){	
	unsigned int expoBackOff = 0;
	__shared__  bool isWorkDone;
	if (threadIdx.x==0){
		isWorkDone = false;
		atomicAdd(&workList.counter->numWaiting,1);
	}
	__syncthreads();

	__shared__  bool hasData;

	while (!isWorkDone) {

		if (threadIdx.x==0){
			hasData = ensureDequeue(workList);
		}
		__syncthreads();

		if (hasData){
			readData(vertexDegree_s, vcSize, vcArIdx, workList, vertexNum);
			if (threadIdx.x==0){
				Counter tempCounter;
				tempCounter.numWaiting = -1;
				tempCounter.numEnqueued = -2;
				atomicAdd(&workList.counter->combined,tempCounter.combined);
			}
			return true;
		}

		if (threadIdx.x==0){
			Counter tempCounter;
			tempCounter.combined = atomicOr(&workList.counter->combined,0);
			if ((tempCounter.numWaiting==gridDim.x && tempCounter.numEnqueued==0) || atomicOr(kFound,0)){
				isWorkDone=true;
			}
		}
		__syncthreads();
		sleepBWD(expoBackOff++);
	}
	return false;
}

template <typename INT_OR_SHORT>
WorkList<INT_OR_SHORT> allocateWorkList(CSRGraph graph, Config config, unsigned int numBlocks) {
	WorkList<INT_OR_SHORT> workList;
	workList.size = config.globalListSize;
	workList.threshold = config.globalListThreshold * workList.size;

	volatile INT_OR_SHORT* list_d;
	volatile unsigned int * listNumDeletedVertices_d;
    volatile int * arrayIndex_d;
	volatile Ticket *tickets_d;
	HT *head_tail_d;
	int* count_d;
	Counter * counter_d;
	cudaMalloc((void**) &list_d, (long long)(graph.vertexNum) * (long long)sizeof(INT_OR_SHORT) * (long long)workList.size);
	cudaMalloc((void**) &listNumDeletedVertices_d, sizeof(unsigned int) * workList.size);
    cudaMalloc((void**) &arrayIndex_d, sizeof(int) * workList.size);
	cudaMalloc((void**) &tickets_d, sizeof(Ticket) * workList.size);
	cudaMalloc((void**) &head_tail_d, sizeof(HT));
	cudaMalloc((void**) &count_d, sizeof(int));
	cudaMalloc((void**) &counter_d, sizeof(Counter));
	
    workList.list = list_d;
	workList.listNumDeletedVertices = listNumDeletedVertices_d;
    workList.arrayIndex = arrayIndex_d;
	workList.tickets = tickets_d;
	workList.head_tail = head_tail_d;
	workList.count = count_d;
	workList.counter = counter_d;

	HT head_tail = 0x0ULL;
	Counter counter;
	counter.combined = 0;
	cudaMemcpy(head_tail_d,&head_tail,sizeof(HT),cudaMemcpyHostToDevice);
	cudaMemset((void*)&tickets_d[0], 0, workList.size * sizeof(Ticket));
	cudaMemset(count_d, 0, sizeof(int));
	cudaMemcpy(counter_d, &counter ,sizeof(Counter),cudaMemcpyHostToDevice);

	return workList;
}

template <typename INT_OR_SHORT>
void cudaFreeWorkList(WorkList<INT_OR_SHORT> workList){
	cudaFree((void*)workList.list);
	cudaFree(workList.head_tail);
	cudaFree((void*)workList.listNumDeletedVertices);
    cudaFree((void*)workList.arrayIndex);
	cudaFree(workList.counter);
	cudaFree(workList.count);
}

#endif
