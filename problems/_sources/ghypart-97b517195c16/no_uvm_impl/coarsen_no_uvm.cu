#include <iostream>
#include <chrono>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include <thrust/sort.h>
#include <thrust/remove.h>
#include <cub/cub.cuh>
#include <cub/device/device_segmented_sort.cuh>
#include <cub/device/device_segmented_reduce.cuh>
#include <cub/device/device_scan.cuh>
#include <cusparse.h>
#include "use_no_uvm.cuh"
#include "coarsen_no_uvm_kernels.cuh"
#include <boost/accumulators/accumulators.hpp>
#include <boost/accumulators/statistics.hpp>
#include <omp.h>
#include <thrust/transform_reduce.h>
#include <thrust/functional.h>
#include <functional>
#include <random>
#include <sched.h>
struct is_small
{
    int threshold = 50;
    __host__ __device__  __forceinline__
    bool operator()(const tmp_hedge &x) const {
        return x.eMatch || x.size >= threshold;
    }
};

struct is_medium
{
    int threshold1 = 50;
    int threshold2 = 5000;
    __host__ __device__  __forceinline__
    bool operator()(const tmp_hedge &x) const {
        return x.eMatch || (x.size < threshold1 || x.size >= threshold2);
    }
};

struct is_large
{
    int threshold = 5000;
    __host__ __device__  __forceinline__
    bool operator()(const tmp_hedge &x) const {
        return x.eMatch || x.size < threshold;
    }
};

struct varianceshifteop
    : std::unary_function<float, float>
{
    varianceshifteop(float m)
        : mean(m)
    { /* no-op */ }

    const float mean;

    __device__ float operator()(float data) const
    {
        return ::pow(data - mean, 2.0f);
    }
};

struct variance: std::unary_function<long double, long double>
{
	variance(long double m): mean(m){ }
	const long double mean;
	__host__ __device__ long double operator()(long double data) const
	{
		return ::pow(data - mean, 2.0f);
	}
};

int findMaxPowerOfTwo(int n) {
    int maxPower = 1;

    // 将 n 与 n-1 进行按位与运算，直到结果为 0
    while ((maxPower << 1) <= n) {
        maxPower <<= 1;
    }

    return maxPower;
}

__host__ __device__ int hash2(unsigned val) {
    unsigned long int seed = val * 1103515245 + 12345;
    return ((unsigned)(seed / 65536) % 32768);
}

__global__ void setHyperedgePriority1(int* hedges, int hedgeN, unsigned matching_policy, int* eRand, int* ePrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    while (tid < hedgeN) {
        eRand[tid] = hash2(hedges[E_IDNUM1(hedgeN) + tid]);
        if (matching_policy == 0) {
            ePrior[tid] = -eRand[tid];
            eRand[tid] = -hedges[E_IDNUM1(hedgeN) + tid];
        }
        tid += gridDim.x * blockDim.x;
    }
}

__global__ void assignPriorityToNode1(int* nodes, unsigned* adj_list, unsigned* hedge_id, int hedgeN, 
                                        int totalsize, int* ePrior, int* nPrior) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    while (tid < totalsize) {
        // int* nodePrior = &nodes[adj_list[tid] - hedgeN + N_PRIORITY1(nodeN)];
        int* nodePrior = &nPrior[adj_list[tid] - hedgeN];
        // atomicMin(nodePrior, hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]);
        atomicMin(nodePrior, ePrior[hedge_id[tid]]);
        tid += gridDim.x * blockDim.x;
    }
}

__global__ void assignHashHedgeIdToNode1(int* nodes, unsigned* adj_list, unsigned* hedge_id, int hedgeN, 
                                        int totalsize, int* eRand, int* ePrior, int* nPrior, int* nRand) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    while (tid < totalsize) {
        // int nodePrior = nodes[N_PRIORITY1(nodeN) + adj_list[tid] - hedgeN];
        int nodePrior = nPrior[adj_list[tid] - hedgeN];
        // if (nodePrior == hedges[E_PRIORITY1(hedgeN) + hedge_id[tid]]) {
        if (nodePrior == ePrior[hedge_id[tid]]) {
            // int* nodeRand = &nodes[adj_list[tid] - hedgeN + N_RAND1(nodeN)];
            int* nodeRand = &nRand[adj_list[tid] - hedgeN];
            // atomicMin(nodeRand, hedges[E_RAND1(hedgeN) + hedge_id[tid]]);
            atomicMin(nodeRand, eRand[hedge_id[tid]]);
        }
        tid += gridDim.x * blockDim.x;
    }
}

__global__ void assignNodeToIncidentHedgeWithMinimalID1(int* hedges, int* nodes, unsigned* adj_list, unsigned* hedge_id, 
                                                    int hedgeN, int totalsize, int* eRand, int* nRand, int* nHedgeId) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    while (tid < totalsize) {
        // int nodeRand = nodes[N_RAND1(nodeN) + adj_list[tid] - hedgeN];
        int nodeRand = nRand[adj_list[tid] - hedgeN];
        // if (nodeRand == hedges[E_RAND1(hedgeN) + hedge_id[tid]]) {
        if (nodeRand == eRand[hedge_id[tid]]) {
            // int* hedgeid = &nodes[adj_list[tid] - hedgeN + N_HEDGEID1(nodeN)];
            int* hedgeid = &nHedgeId[adj_list[tid] - hedgeN];
            atomicMin(hedgeid, hedges[E_IDNUM1(hedgeN) + hedge_id[tid]]);
        }
        tid += gridDim.x * blockDim.x;
    }
}


class GPUTimer {
public:
    GPUTimer() {
        cudaEventCreate(&t1);   
        cudaEventCreate(&t2);
    }
    void start() { cudaEventRecord(t1, 0); }

    float elapsed() {
        cudaEventElapsedTime(&time, t1, t2);
        return time;
    }

    void end_with_sync() {
        cudaEventRecord(t2, 0);
        // cudaEventSynchronize(t1);
        cudaEventSynchronize(t2);
    }

private:
    float time;
    cudaEvent_t t1, t2;
};

Hypergraph* coarsen_no_uvm(Hypergraph* hgr, int iter, int LIMIT, float& time, float& other_time, OptionConfigs& optcfgs, 
                            unsigned long& memBytes, std::vector<std::pair<std::string, float>>& perfs, Auxillary* aux, 
                            std::vector<std::vector<std::pair<std::string, float>>>& iter_perfs, float& selectionOverhead, float& alloc_time) {
    std::cout << __FUNCTION__ << "..." << iter << "\n";
    std::vector<std::pair<std::string, float>> kernel_pairs;
    std::vector<float> iter_split_k4;
    std::vector<long double> iter_split_k4_in_kernel;
    float iter_time = 0.0;
    Hypergraph* coarsenHgr;
    coarsenHgr = (Hypergraph*)malloc(sizeof(Hypergraph));
    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr, sizeof(Hypergraph)));
    coarsenHgr->nodeNum = 0;
    coarsenHgr->hedgeNum = 0;
    coarsenHgr->graphSize = 0;
    coarsenHgr->sdHedgeSize = 0;
    coarsenHgr->sdHNdegree = 0;
    std::cout << "current allocated gpu memory:" << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
    std::string patternForMatching = "";
    std::string patternForK5 = optcfgs.useNewKernel5 ? "P3" : "P1";
    std::string patternForMerging = "";
    std::string patternForConstruction = "";

    // cpu_set_t mask;
    // CPU_ZERO(&mask);
    // // 获取当前进程的 CPU 亲和性
    // if (sched_getaffinity(0, sizeof(cpu_set_t), &mask) != -1) {
    //     for (int i = 0; i < CPU_SETSIZE; i++) {
    //         if (CPU_ISSET(i, &mask)) {
    //             std::cout << "CPU Core " << i << ": Running" << std::endl;
    //         }
    //     }
    // }

    if (optcfgs.randomSelection) {
        std::random_device rd;
        std::mt19937 gen(rd());
        std::uniform_int_distribution<int> dis(1, 3);
        int num1 = dis(gen);
        int num2 = dis(gen);
        int num3 = dis(gen);
#if 1
        if (num1 == 1) {
            // choose P1 for matching
        } else if (num1 == 2) {
            // choose P2 for matching
            optcfgs.useNewKernel1_2_3 = true;
            optcfgs.useNewKernel5 = true;
            optcfgs.useP2ForMatching = true;
        } else if (num1 == 3) {
            // choose P3 for matching
            optcfgs.useNewKernel1_2_3 = true;
            optcfgs.useNewKernel5 = true;
        }

        if (num2 == 1) {
            // choose P1 for merging
        } else if (num2 == 2) {
            // choose P2 for merging
            optcfgs.optForKernel4 = true;
            optcfgs.optForKernel6 = true;
            optcfgs.useP2ForNodeMergingK4 = true;
            optcfgs.useP2ForNodeMergingK6 = true;
        } else if (num2 == 3) {
            // choose P3 for merging
            optcfgs.optForKernel4 = true;
            optcfgs.optForKernel6 = true;
        }

        if (num3 == 1) {
            // choose P2 for construction
            optcfgs.useNewKernel12 = false;
            optcfgs.useNewParalOnBaseK12 = 1;
        } else if (num3 == 2) {
            // choose P2b for construction
            optcfgs.useNewKernel12 = true;
            optcfgs.useNewParalOnBaseK12 = 0;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 1;
        } else if (num3 == 3) {
            // choose P3 for construction
            optcfgs.useNewKernel12 = false;
            optcfgs.useNewParalOnBaseK12 = 2;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 2;
        }
#endif
#if 0
        int num = dis(gen);
        if (num == 1) {
            // choose P1 for matching
            // choose P1 for merging
            // choose P2 for construction
            optcfgs.useNewKernel12 = false;
            optcfgs.useNewParalOnBaseK12 = 1;
        } else if (num == 2) {
            // choose P2 for matching
            optcfgs.useNewKernel1_2_3 = true;
            optcfgs.useNewKernel5 = true;
            optcfgs.useP2ForMatching = true;
            // choose P2 for merging
            optcfgs.optForKernel4 = true;
            optcfgs.optForKernel6 = true;
            optcfgs.useP2ForNodeMergingK4 = true;
            optcfgs.useP2ForNodeMergingK6 = true;
            // choose P2b for construction
            optcfgs.useNewKernel12 = true;
            optcfgs.useNewParalOnBaseK12 = 0;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 1;
        } else if (num == 3) {
            // choose P3 for matching
            optcfgs.useNewKernel1_2_3 = true;
            optcfgs.useNewKernel5 = true;
            // choose P3 for merging
            optcfgs.optForKernel4 = true;
            optcfgs.optForKernel6 = true;
            // choose P3 for construction
            optcfgs.useNewKernel12 = false;
            optcfgs.useNewParalOnBaseK12 = 2;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 2;
        }
#endif
#if 0
        // only choose P2 P2 and P2b
        // choose P2 for matching
        optcfgs.useNewKernel1_2_3 = true;
        optcfgs.useNewKernel5 = true;
        optcfgs.useP2ForMatching = true;
        // choose P2 for merging
        optcfgs.optForKernel4 = true;
        optcfgs.optForKernel6 = true;
        optcfgs.useP2ForNodeMergingK4 = true;
        optcfgs.useP2ForNodeMergingK6 = true;
        // choose P2b for construction
        optcfgs.useNewKernel12 = true;
        optcfgs.useNewParalOnBaseK12 = 0;
        optcfgs.sortHedgeLists = true;
        optcfgs.useNewKernel14 = true;
        optcfgs.useNewParalOnBaseK14 = 1;
#endif
#if 0
        // only choose P3 P3 and P3
        // choose P3 for matching
        optcfgs.useNewKernel1_2_3 = true;
        optcfgs.useNewKernel5 = true;
        // choose P3 for merging
        optcfgs.optForKernel4 = true;
        optcfgs.optForKernel6 = true;
        // choose P3 for construction
        optcfgs.useNewKernel12 = false;
        optcfgs.useNewParalOnBaseK12 = 2;
        optcfgs.sortHedgeLists = true;
        optcfgs.useNewKernel14 = true;
        optcfgs.useNewParalOnBaseK14 = 2;
#endif
    }

    struct timeval beg1, end1;
    gettimeofday(&beg1, NULL);                    
    if (optcfgs.enableSelection) {
#if 1
        // choose P3 for matching
        optcfgs.useNewKernel1_2_3 = true;
        optcfgs.useNewKernel5 = true;

        if (hgr->maxDegree > 815.0 && hgr->hedgeNum <= 1316927.0) {
            // choose P3 for merging
            optcfgs.optForKernel4 = true;
            optcfgs.optForKernel6 = true;
        } else {
            // choose P1 for merging
        }

        if (hgr->sdHedgeSize > 143.519) {
            // choose P2b for construction
            optcfgs.useNewKernel12 = true;
            optcfgs.useNewParalOnBaseK12 = 0;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 1;
        } else {
            // choose P3 for construction
            optcfgs.useNewKernel12 = false;
            optcfgs.useNewParalOnBaseK12 = 2;
            optcfgs.sortHedgeLists = true;
            optcfgs.useNewKernel14 = true;
            optcfgs.useNewParalOnBaseK14 = 2;
        }
#endif
    }

    gettimeofday(&end1, NULL);
    selectionOverhead += (end1.tv_sec - beg1.tv_sec) + ((end1.tv_usec - beg1.tv_usec)/1000000.0);
    if (!optcfgs.useNewKernel1_2_3) {
        patternForMatching = "P1";
    } else if (optcfgs.useP2ForMatching) {
        patternForMatching = "P2";
    } else {
        patternForMatching = "P3";
    }
    if (!optcfgs.optForKernel4) {
        patternForMerging = "P1";
    } else if (optcfgs.useP2ForNodeMergingK4) {
        patternForMerging = "P2";
    } else {
        patternForMerging = "P3";
    }
    if (!optcfgs.useNewKernel12) {
        if (optcfgs.useNewParalOnBaseK12 == 1) {
            patternForConstruction = "P2";
        } else if (optcfgs.useNewParalOnBaseK12 == 2) {
            patternForConstruction = "P3";
        }
    } else {
        patternForConstruction = "P2b";
    }

    if (iter == 0) {
    std::cout << __LINE__ << ":"
            << "pattern for K1K2K3K5," << patternForMatching << "," << patternForK5 << "\n"
            << "pattern for K4K6," << patternForMerging << "," << patternForMerging << "\n"
            << "pattern for K12," << patternForConstruction << "," << patternForConstruction << "\n";
            // << optcfgs.sortHedgeLists << "\n"
            // << "pattern for K14," << optcfgs.useNewKernel14 << "," << optcfgs.useNewParalOnBaseK14 << "\n";
    } else {
        // std::cout << __LINE__ << ":"
        //     << optcfgs.useNewKernel1_2_3 << "," << optcfgs.useNewKernel5 << "\n"
        //     << optcfgs.optForKernel4 << "," << optcfgs.optForKernel6 << "\n"
        //     << optcfgs.useNewKernel12 << "," << optcfgs.useNewParalOnBaseK12 << "\n"
        //     << optcfgs.sortHedgeLists << "\n"
        //     << optcfgs.useNewKernel14 << "," << optcfgs.useNewParalOnBaseK14 << "\n";
    }

    int device;
    cudaDeviceProp props;
    cudaGetDevice(&device);
    cudaGetDeviceProperties(&props, device);
    std::cout << "GPU clock rate:" << props.clockRate << "\n";
    TIMERSTART(_alloc)
    allocTempData(aux, hgr);
    TIMERSTOP(_alloc)
    alloc_time += time_alloc / 1000.f;

    // thrust::fill(thrust::device, aux->ePriori, aux->ePriori + hgr->hedgeNum, INT_MAX);
    // thrust::fill(thrust::device, aux->nMatchHedgeId, aux->nMatchHedgeId + hgr->nodeNum, INT_MAX);
    // thrust::fill(thrust::device, aux->nPriori, aux->nPriori + hgr->nodeNum, INT_MAX);
    // thrust::fill(thrust::device, aux->nRand, aux->nRand + hgr->nodeNum, INT_MAX);

    int blocksize = 128;
    int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
    int num_blocks = UP_DIV(hgr->totalEdgeDegree, blocksize);
    std::cout << "hedgeNum: " << hgr->hedgeNum << ", nodeNum: " << hgr->nodeNum << "\n";
    // GPUTimer gpuTimer;
    // gpuTimer.start();
    TIMERSTART(0)
    setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
    // setHyperedgePriority1<<<UP_DIV(10000, blocksize), blocksize>>>(hgr->hedges, hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
    // setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, optcfgs.matching_policy, eRand, ePriori);
    TIMERSTOP(0)
    // // gpuTimer.end_with_sync();
    // // std::cout << "kernel execution time: #" << gpuTimer.elapsed() << " ms (setHyperedgePriority)\n";
    time += time0 / 1000.f;
    // kernel_pairs.push_back(std::make_pair("setHyperedgePriority", time0));

    // int* eRand = (int*)malloc(hgr->hedgeNum * sizeof(int));
    // int* ePriori = (int*)malloc(hgr->hedgeNum * sizeof(int));
    // CHECK_ERROR(cudaMemcpy(eRand, aux->eRand, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy(ePriori, aux->ePriori, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    // std::ofstream debug("debug.txt");
    // for (int i = 0; i < hgr->hedgeNum; i++) {
    //     debug << eRand[i] << " " << ePriori[i] << "\n";
    // }
    // debug.close();
    // std::ifstream file("debug.txt");
    // std::string line;
    // std::vector<int> eRand;
    // std::vector<int> ePriori;
    // while (std::getline(file, line)) {
    //     std::istringstream iss(line);
    //     int val1, val2;
    //     if (iss >> val1 >> val2) {
    //         eRand.push_back(val1);
    //         ePriori.push_back(val2);
    //     }
    // }
    // file.close();
    // CHECK_ERROR(cudaMemcpy(aux->eRand, eRand.data(), hgr->hedgeNum * sizeof(int), cudaMemcpyHostToDevice));
    // CHECK_ERROR(cudaMemcpy(aux->ePriori, ePriori.data(), hgr->hedgeNum * sizeof(int), cudaMemcpyHostToDevice));

    // TIMERSTART(1)
    // // multiNodeMatching1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->ePriori, aux->nPriori);
    // assignPriorityToNode1<<<100, blocksize>>>(hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
    // // assignPriorityToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
    // TIMERSTOP(1)
#if 1
    if (!optcfgs.useNewKernel1_2_3) {
        // TIMERSTART(0123)
        // setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
        // multiNodeMatching1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, aux->ePriori, aux->nPriori);
        // multiNodeMatching2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // multiNodeMatching3<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // TIMERSTOP(0123)
        // time += time0123 / 1000.f;
    #if 1
        TIMERSTART(1)
        // if (iter > 0) {
        multiNodeMatching1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->ePriori, aux->nPriori);
        // } else {
        //     multiNodeMatching_new<<<UP_DIV(aux->total_thread_num, blocksize), blocksize>>>(hgr->hedges, hgr->adj_list, hgr->hedgeNum, aux->ePriori, aux->nPriori, aux->hedge_off_per_thread, aux->total_thread_num);
        // }
        TIMERSTOP(1)
        
        TIMERSTART(2)
        multiNodeMatching2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        TIMERSTOP(2)
        
        TIMERSTART(3)
        multiNodeMatching3<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        TIMERSTOP(3)

        perfs[1].second += time1;
        perfs[2].second += time2;
        perfs[3].second += time3;
        time += (time1 + time2 + time3) / 1000.f;
        kernel_pairs.push_back(std::make_pair("multiNodeMatching1", time1));
        kernel_pairs.push_back(std::make_pair("multiNodeMatching2", time2));
        kernel_pairs.push_back(std::make_pair("multiNodeMatching3", time3));
        iter_time += time1 + time2 + time3;
    #endif
    } else {
        if (!optcfgs.useP2ForMatching) {
            std::cout << __LINE__ << "\n";
        // TIMERSTART(0123)
        // setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
        // assignPriorityToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, 
        //                                                 hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, 
        //                                                 aux->ePriori, aux->nPriori);
        // assignHashHedgeIdToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, 
        //                                                 hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, 
        //                                                 aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // assignNodeToIncidentHedgeWithMinimalID<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, 
        //                                                 aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, 
        //                                                 hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // TIMERSTOP(0123)
        // time += time0123 / 1000.f;
        #if 1
        TIMERSTART(1)
        // assignPriorityToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
        assignPriorityToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
        // assignPriorityToNode1<<<100, blocksize>>>(hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
        TIMERSTOP(1)
        
        TIMERSTART(2)
        // assignHashHedgeIdToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        assignHashHedgeIdToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // assignHashHedgeIdToNode1<<<100, blocksize>>>(hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        TIMERSTOP(2)
        
        TIMERSTART(3)
        // assignNodeToIncidentHedgeWithMinimalID<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        assignNodeToIncidentHedgeWithMinimalID<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // assignNodeToIncidentHedgeWithMinimalID1<<<100, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        TIMERSTOP(3)
        perfs[1].second += time1;
        perfs[2].second += time2;
        perfs[3].second += time3;
        time += (time1 + time2 + time3) / 1000.f;
        kernel_pairs.push_back(std::make_pair("assignPriorityToNode", time1));
        kernel_pairs.push_back(std::make_pair("assignHashHedgeIdToNode", time2));
        kernel_pairs.push_back(std::make_pair("assignNodeToIncidentHedgeWithMinimalID", time3));
        iter_time += time1 + time2 + time3;
        #endif
        } else {
        // TIMERSTART(0123)
        // setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
        // assignPriorityToNode_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                         hgr->hedgeNum, aux->ePriori, aux->nPriori);
        // assignHashHedgeIdToNode_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, 
        //                                                 hgr->hedgeNum, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // assignNodeToIncidentHedgeWithMinimalID_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, 
        //                                             hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // TIMERSTOP(0123)
        // time += time0123 / 1000.f;
        #if 1
            TIMERSTART(1)
            assignPriorityToNode_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->ePriori, aux->nPriori);
            TIMERSTOP(1)
            
            TIMERSTART(2)
            assignHashHedgeIdToNode_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
            // assignHashHedgeIdToNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
            TIMERSTOP(2)
            
            TIMERSTART(3)
            assignNodeToIncidentHedgeWithMinimalID_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->nRand, aux->nMatchHedgeId);
            // assignNodeToIncidentHedgeWithMinimalID<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
            TIMERSTOP(3)

            perfs[1].second += time1;
            perfs[2].second += time2;
            perfs[3].second += time3;
            time += (time1 + time2 + time3) / 1000.f;
            kernel_pairs.push_back(std::make_pair("assignPriorityToNode_P2", time1));
            kernel_pairs.push_back(std::make_pair("assignHashHedgeIdToNode_P2", time2));
            kernel_pairs.push_back(std::make_pair("assignNodeToIncidentHedgeWithMinimalID_P2", time3));
            iter_time += time1 + time2 + time3;
        #endif
        }
    }

    CHECK_ERROR(cudaMalloc((void**)&aux->cand_counts, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&aux->cand_counts, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->cand_counts, 0, hgr->hedgeNum * sizeof(int)));

    // TIMERSTART(_)
    // selectCandidatesTest<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
    //                                                     aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId);
    // TIMERSTOP(_)
    // CHECK_ERROR(cudaMallocManaged(&aux->dupCnts, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->isSelfMergeNodes, hgr->nodeNum * sizeof(unsigned)));
    CHECK_ERROR(cudaMemset((void*)aux->isSelfMergeNodes, 0, hgr->nodeNum * sizeof(unsigned)));
    // std::ofstream debug("after_K3_adj_mapped_nodelist.txt");
    // int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    // int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    // int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    // unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    // unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    // int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    // CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    // CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    // debug << "(adjlist_id, parent_id, isDuplica, isSelfMergeNode)\n";
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "eInBag:" << eInBag[i] << ",   ";
    //     for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
    //         int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
    //         debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
    //     }
    //     debug << "\n";
    // }

#if 0
    if (optcfgs.optForKernel4) {
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        unsigned long thread_item_num = hgr->totalEdgeDegree;
        // k4_1
        unsigned long iter_k4_memops1 = 7 * hgr->totalEdgeDegree;
        unsigned long iter_k4_cptops1 = hgr->totalEdgeDegree;
        // k4_2
        unsigned long iter_k4_memops2 = 10 * hgr->totalEdgeDegree;
        unsigned long iter_k4_cptops2 = 6 * hgr->totalEdgeDegree;
        // k4_3
        unsigned long iter_k4_memops3 = 21 * hgr->totalEdgeDegree;
        unsigned long iter_k4_cptops3 = 6 * hgr->totalEdgeDegree;
        unsigned long total_ops = (iter_k4_memops1 + iter_k4_memops2 + iter_k4_memops3) + (iter_k4_cptops1 + iter_k4_cptops2 + iter_k4_cptops3);
        optcfgs.iterative_K4_num_opcost.push_back(total_ops);
        optcfgs.iter_perthread_K4_numopcost.push_back(total_ops / thread_item_num);
    } else {
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        unsigned long iter_k4_memops = 0;
        unsigned long iter_k4_cptops = 0;
        unsigned long thread_item_num = hgr->hedgeNum;
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            iter_k4_memops += (2 + 5) * hedge[i + E_DEGREE1(hgr->hedgeNum)];
            iter_k4_memops += 5 + 8 * hedge[i + E_DEGREE1(hgr->hedgeNum)];
            iter_k4_cptops += 3 * hedge[i + E_DEGREE1(hgr->hedgeNum)] + 2 + hedge[i + E_DEGREE1(hgr->hedgeNum)];
        }
        optcfgs.iterative_K4_num_opcost.push_back(iter_k4_memops + iter_k4_cptops);
        optcfgs.iter_perthread_K4_numopcost.push_back((iter_k4_memops + iter_k4_cptops) / thread_item_num);
    }
#endif

    if (optcfgs.optForKernel4) {
        if (!optcfgs.useP2ForNodeMergingK4) {
        // int maxActiveBlocks1, maxActiveBlocks2, maxActiveBlocks3;
        // cudaOccupancyMaxActiveBlocksPerMultiprocessor(&maxActiveBlocks1, collectCandidateWeights, blocksize, 0);
        // cudaOccupancyMaxActiveBlocksPerMultiprocessor(&maxActiveBlocks2, collectCandidateNodes, blocksize, 0);
        // cudaOccupancyMaxActiveBlocksPerMultiprocessor(&maxActiveBlocks3, assignMatchStatusAndSuperNodeToCandidates, blocksize, 0);
        // float occupancy1 = (maxActiveBlocks1 * blocksize / props.warpSize) / (float)(props.maxThreadsPerMultiProcessor / props.warpSize);
        // float occupancy2 = (maxActiveBlocks2 * blocksize / props.warpSize) / (float)(props.maxThreadsPerMultiProcessor / props.warpSize);
        // float occupancy3 = (maxActiveBlocks3 * blocksize / props.warpSize) / (float)(props.maxThreadsPerMultiProcessor / props.warpSize);
        // std::cout << "Theoretical occupancy info:\n";
        // std::cout << "kernel: blocks size:" << blocksize << ", maxActiveBlocks1:" << maxActiveBlocks1 << ", theoretical occupancy1:" << occupancy1 << "\n";
        // std::cout << "kernel: blocks size:" << blocksize << ", maxActiveBlocks1:" << maxActiveBlocks2 << ", theoretical occupancy1:" << occupancy2 << "\n";
        // std::cout << "kernel: blocks size:" << blocksize << ", maxActiveBlocks1:" << maxActiveBlocks3 << ", theoretical occupancy1:" << occupancy3 << "\n";
        std::cout << "total # of blocks launched:" << num_blocks << "\n";

        CHECK_ERROR(cudaMalloc((void**)&aux->cand_weight_list, hgr->totalEdgeDegree * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)aux->cand_weight_list, 0, hgr->totalEdgeDegree * sizeof(int)));
        CHECK_ERROR(cudaMalloc((void**)&aux->flags, hgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)aux->flags, 0, hgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMalloc((void**)&aux->nodeid, hgr->hedgeNum * sizeof(int)));
        thrust::fill(thrust::device, aux->nodeid, aux->nodeid + hgr->hedgeNum, INT_MAX);
        
        long long* d_timer, *d_timer1, *d_timer2;
        // CHECK_ERROR(cudaMalloc((void**)&d_timer, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMemset((void*)d_timer, 0, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMalloc((void**)&d_timer1, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMemset((void*)d_timer1, 0, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMalloc((void**)&d_timer2, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMemset((void*)d_timer2, 0, num_blocks * 2 * sizeof(clock_t)));
        // CHECK_ERROR(cudaMalloc((void**)&d_timer, hgr->totalEdgeDegree * sizeof(long long)));
        // CHECK_ERROR(cudaMemset((void*)d_timer, 0, hgr->totalEdgeDegree * sizeof(long long)));
        // CHECK_ERROR(cudaMalloc((void**)&d_timer1, hgr->totalEdgeDegree * sizeof(long long)));
        // CHECK_ERROR(cudaMemset((void*)d_timer1, 0, hgr->totalEdgeDegree * sizeof(long long)));
        // CHECK_ERROR(cudaMalloc((void**)&d_timer2, hgr->totalEdgeDegree * sizeof(long long)));
        // CHECK_ERROR(cudaMemset((void*)d_timer2, 0, hgr->totalEdgeDegree * sizeof(long long)));
        int* d_realwork;
        // CHECK_ERROR(cudaMalloc((void**)&d_realwork, hgr->totalEdgeDegree * sizeof(int)));
        // CHECK_ERROR(cudaMemset((void*)d_realwork, 0, hgr->totalEdgeDegree * sizeof(int)));

        TIMERSTART(_opt4_0)
        collectCandidateWeights<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, aux->cand_weight_list, 
                                                        aux->pins_hedgeid_list, aux->nMatchHedgeId, hgr->totalEdgeDegree, d_timer, d_realwork);
        TIMERSTOP(_opt4_0)

        TIMERSTART(_opt4_1)
        // void            *w_temp_storage = NULL;
        // size_t          tempw_storage_bytes = 0;
        // cub::DeviceScan::InclusiveSum(w_temp_storage, tempw_storage_bytes, aux->cand_weight_list, aux->cand_weight_list, hgr->totalEdgeDegree);
        // std::cout << "temp_storage_in_GB: " << tempw_storage_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
        // CHECK_ERROR(cudaMalloc((void**)&w_temp_storage, tempw_storage_bytes));
        // cub::DeviceScan::InclusiveSum(w_temp_storage, tempw_storage_bytes, aux->cand_weight_list, aux->cand_weight_list, hgr->totalEdgeDegree);
        thrust::inclusive_scan(thrust::device, aux->cand_weight_list, aux->cand_weight_list + hgr->totalEdgeDegree, aux->cand_weight_list);
        TIMERSTOP(_opt4_1)
#if 0
        TIMERSTART(_opt4_5)
        void *kernelArgs[] = { (void*)&hgr->hedges,(void*)&hgr->nodes,
                                (void*)&hgr->adj_list,(void*)&hgr->hedgeNum,(void*)&hgr->nodeNum,
                                (void*)&aux->cand_weight_list, (void*)&aux->pins_hedgeid_list,
                                (void*)&aux->nMatchHedgeId,(void*)&hgr->totalEdgeDegree,
                                (void*)&optcfgs.coarseI_weight_limit, 
                                (void*)&aux->pins_hedgeid_list, 
                                (void*)&aux->nMatchHedgeId,
                                (void*)&aux->canBeCandidates, 
                                (void*)&aux->flags, 
                                (void*)&aux->nodeid, 
                                (void*)&aux->cand_counts,
                                (void*)&aux->d_edgeCnt, (void*)&aux->d_nodeCnt,
                                (void*)&aux->eInBag, (void*)&aux->eMatch, (void*)&aux->nInBag, (void*)&aux->tmpW, (void*)&aux->nMatch,
                                (void*)&hgr->nodes + N_PARENT1(hgr->nodeNum)
                                };
        CHECK_ERROR(cudaLaunchCooperativeKernel((void *)combined_kernel12, num_blocks, blocksize, kernelArgs, 0, NULL));
        // CHECK_ERROR(cudaLaunchCooperativeKernel((void *)combined_kernel34, num_blocks, blocksize, kernelArgs, 0, NULL));
        TIMERSTOP(_opt4_5)
#endif
        TIMERSTART(_opt4_2)
        // collectCandidateNodes<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId, 
        //                                                 hgr->totalEdgeDegree, aux->cand_weight_list, test_candidates, aux->flags, aux->nodeid, aux->cand_counts);
        collectCandidateNodes<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId, 
                                                        hgr->totalEdgeDegree, aux->cand_weight_list, aux->canBeCandidates, aux->flags, aux->nodeid, aux->cand_counts, d_timer1, d_realwork);
        TIMERSTOP(_opt4_2)

        TIMERSTART(_opt4_3)
        // assignMatchStatusAndSuperNodeToCandidates<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, hgr->totalEdgeDegree, aux->pins_hedgeid_list, aux->nMatchHedgeId, 
        //                                                 newHedgeN, newNodeN, eInBag, eMatch, nInBag, tmpW, nMatch, parent, test_candidates, aux->flags, aux->nodeid, aux->cand_counts);
        assignMatchStatusAndSuperNodeToCandidates<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, hgr->totalEdgeDegree, aux->pins_hedgeid_list, aux->nMatchHedgeId, 
                                                        aux->d_edgeCnt, aux->d_nodeCnt, aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, hgr->nodes + N_PARENT1(hgr->nodeNum), 
                                                        aux->canBeCandidates, aux->flags, aux->nodeid, aux->cand_counts, d_timer2);
        TIMERSTOP(_opt4_3)
        time += (time_opt4_0 + time_opt4_1 + time_opt4_2 + time_opt4_3) / 1000.f;
        perfs[4].second += time_opt4_0 + time_opt4_1 + time_opt4_2 + time_opt4_3;
        CHECK_ERROR(cudaFree(aux->cand_weight_list));
        CHECK_ERROR(cudaFree(aux->flags));
        CHECK_ERROR(cudaFree(aux->nodeid));
        kernel_pairs.push_back(std::make_pair("collectCandidateWeights", time_opt4_0));
        kernel_pairs.push_back(std::make_pair("thrust::inclusive_scan", time_opt4_1));
        kernel_pairs.push_back(std::make_pair("collectCandidateNodes", time_opt4_2));
        kernel_pairs.push_back(std::make_pair("assignMatchStatusAndSuperNodeToCandidates", time_opt4_3));
        iter_time += time_opt4_0 + time_opt4_1 + time_opt4_2 + time_opt4_3;
        iter_split_k4.push_back(time_opt4_0);
        iter_split_k4.push_back(time_opt4_1);
        iter_split_k4.push_back(time_opt4_2);
        iter_split_k4.push_back(time_opt4_3);
        optcfgs.iterative_K4.push_back(time_opt4_0 + time_opt4_1 + time_opt4_2 + time_opt4_3);
        } else {
            CHECK_ERROR(cudaMalloc((void**)&aux->cand_weight_list, hgr->totalEdgeDegree * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)aux->cand_weight_list, 0, hgr->totalEdgeDegree * sizeof(int)));
            CHECK_ERROR(cudaMalloc((void**)&aux->flags, hgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)aux->flags, 0, hgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMalloc((void**)&aux->nodeid, hgr->hedgeNum * sizeof(int)));
            thrust::fill(thrust::device, aux->nodeid, aux->nodeid + hgr->hedgeNum, INT_MAX);

            TIMERSTART(_opt4p2_0)
            collectCandidateWeights_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, 
                                                            aux->cand_weight_list, aux->nMatchHedgeId);
            TIMERSTOP(_opt4p2_0)

            TIMERSTART(_opt4p2_1)
            thrust::inclusive_scan(thrust::device, aux->cand_weight_list, aux->cand_weight_list + hgr->totalEdgeDegree, aux->cand_weight_list);
            TIMERSTOP(_opt4p2_1)

            TIMERSTART(_opt4p2_2)
            collectCandidateNodes_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, 
                                                            aux->cand_weight_list, aux->canBeCandidates, aux->flags, aux->nodeid, aux->cand_counts);
            TIMERSTOP(_opt4p2_2)

            TIMERSTART(_opt4p2_3)
            assignSuperNodeToCandidates_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, aux->nMatchHedgeId, 
                                                            aux->d_edgeCnt, aux->d_nodeCnt, aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, hgr->nodes + N_PARENT1(hgr->nodeNum), 
                                                            aux->canBeCandidates, aux->flags, aux->nodeid, aux->cand_counts);
            TIMERSTOP(_opt4p2_3)

            time += (time_opt4p2_0 + time_opt4p2_1 + time_opt4p2_2 + time_opt4p2_3) / 1000.f;
            perfs[4].second += time_opt4p2_0 + time_opt4p2_1 + time_opt4p2_2 + time_opt4p2_3;
            CHECK_ERROR(cudaFree(aux->cand_weight_list));
            CHECK_ERROR(cudaFree(aux->flags));
            CHECK_ERROR(cudaFree(aux->nodeid));
            kernel_pairs.push_back(std::make_pair("collectCandidateWeights_P2", time_opt4p2_0));
            kernel_pairs.push_back(std::make_pair("thrust::inclusive_scan", time_opt4p2_1));
            kernel_pairs.push_back(std::make_pair("collectCandidateNodes_P2", time_opt4p2_2));
            kernel_pairs.push_back(std::make_pair("assignSuperNodeToCandidates_P2", time_opt4p2_3));
            iter_time += time_opt4p2_0 + time_opt4p2_1 + time_opt4p2_2 + time_opt4p2_3;
            iter_split_k4.push_back(time_opt4p2_0);
            iter_split_k4.push_back(time_opt4p2_1);
            iter_split_k4.push_back(time_opt4p2_2);
            iter_split_k4.push_back(time_opt4p2_3);
        }
#if 0
        // clock_t* timer = (clock_t*)malloc(num_blocks * 2 * sizeof(clock_t));
        // clock_t* timer1 = (clock_t*)malloc(num_blocks * 2 * sizeof(clock_t));
        // clock_t* timer2 = (clock_t*)malloc(num_blocks * 2 * sizeof(clock_t));
        // CHECK_ERROR(cudaMemcpy((void *)timer, d_timer, num_blocks * 2 * sizeof(clock_t), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)timer1, d_timer1, num_blocks * 2 * sizeof(clock_t), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)timer2, d_timer2, num_blocks * 2 * sizeof(clock_t), cudaMemcpyDeviceToHost));
        long long* timer = (long long*)malloc(hgr->totalEdgeDegree * sizeof(long long));
        long long* timer1 = (long long*)malloc(hgr->totalEdgeDegree * sizeof(long long));
        long long* timer2 = (long long*)malloc(hgr->totalEdgeDegree * sizeof(long long));
        CHECK_ERROR(cudaMemcpy((void *)timer, d_timer, hgr->totalEdgeDegree * sizeof(long long), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)timer1, d_timer1, hgr->totalEdgeDegree * sizeof(long long), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)timer2, d_timer2, hgr->totalEdgeDegree * sizeof(long long), cudaMemcpyDeviceToHost));
        // int* real_work_cnt = (int*)malloc(hgr->totalEdgeDegree * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)real_work_cnt, d_realwork, hgr->totalEdgeDegree * sizeof(int), cudaMemcpyDeviceToHost));
        // compute the diff between the last block end and the first block start
        // clock_t minBeg = timer[0];
        // clock_t maxEnd = timer[num_blocks];
        // clock_t minBeg1 = timer1[0];
        // clock_t maxEnd1 = timer1[num_blocks];
        // clock_t minBeg2 = timer2[0];
        // clock_t maxEnd2 = timer2[num_blocks];
        // for (int i = 1; i < num_blocks; ++i) {
        //     minBeg = timer[i] < minBeg ? timer[i] : minBeg;
        //     maxEnd = timer[i + num_blocks] > maxEnd ? timer[i + num_blocks] : maxEnd;
        // }
        // for (int i = 1; i < num_blocks; ++i) {
        //     minBeg1 = timer1[i] < minBeg1 ? timer1[i] : minBeg1;
        //     maxEnd1 = timer1[i + num_blocks] > maxEnd1 ? timer1[i + num_blocks] : maxEnd1;
        // }
        // for (int i = 1; i < num_blocks; ++i) {
        //     minBeg2 = timer2[i] < minBeg2 ? timer2[i] : minBeg2;
        //     maxEnd2 = timer2[i + num_blocks] > maxEnd2 ? timer2[i + num_blocks] : maxEnd2;
        // }
        long double avgClocksPerNode1 = 0, avgClocksPerNode3 = 0, avgClocksPerNode4 = 0;
        long long elaps1 = 0, elaps3 = 0, elaps4 = 0;
        for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
            avgClocksPerNode1 += timer[i];
            avgClocksPerNode3 += timer1[i];
            avgClocksPerNode4 += timer2[i];
            elaps1 = max(elaps1, timer[i]);
            elaps3 = max(elaps3, timer1[i]);
            elaps4 = max(elaps4, timer2[i]);
        }
        long double sum_clocks = avgClocksPerNode1 + avgClocksPerNode3 + avgClocksPerNode4;
        iter_split_k4_in_kernel.push_back(static_cast<long double>(sum_clocks));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(sum_clocks / (3 * hgr->totalEdgeDegree)));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode1));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode3));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode4));
        avgClocksPerNode1 /= hgr->totalEdgeDegree;
        avgClocksPerNode3 /= hgr->totalEdgeDegree;
        avgClocksPerNode4 /= hgr->totalEdgeDegree;
        // long sum_work_items = 0;
        // for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
        //     sum_work_items += real_work_cnt[i];
        // }
        // std::string output = optcfgs.filename + "_cycles_info_splitopt.csv";
        // std::ofstream wr(output);
        // wr << "K4-1_clock_time, K4-3_clock_time, K4-4_clock_time\n";
        // for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
        //     wr << timer[i] << ", " << timer1[i] << ", " << timer2[i] << "\n";
        // }
        // iter_split_k4_in_kernel.push_back(static_cast<long double>((maxEnd - minBeg) / CLOCKS_PER_SEC) * 1000.f);
        // iter_split_k4_in_kernel.push_back(static_cast<long double>((maxEnd1 - minBeg1) / CLOCKS_PER_SEC) * 1000.f);
        // iter_split_k4_in_kernel.push_back(static_cast<long double>((maxEnd2 - minBeg2) / CLOCKS_PER_SEC) * 1000.f);
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode1));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode3));
        iter_split_k4_in_kernel.push_back(static_cast<long double>(avgClocksPerNode4));
        // iter_split_k4_in_kernel.push_back(sum_work_items);
        // iter_split_k4_in_kernel.push_back(static_cast<long double>(elaps1 / (props.clockRate * 1000.f) * 1000.f));
        // iter_split_k4_in_kernel.push_back(static_cast<long double>(elaps3 / (props.clockRate * 1000.f) * 1000.f));
        // iter_split_k4_in_kernel.push_back(static_cast<long double>(elaps4 / (props.clockRate * 1000.f) * 1000.f));
        // iter_split_k4_in_kernel.push_back(sum_clocks);
#endif
        // CHECK_ERROR(cudaFree(d_timer));
        // CHECK_ERROR(cudaFree(d_timer1));
        // CHECK_ERROR(cudaFree(d_timer2));
        // CHECK_ERROR(cudaFree(d_realwork));
    } else {
        if (optcfgs.pureSplitK4) {
            int* counts;
            CHECK_ERROR(cudaMalloc((void**)&counts, hgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)counts, 0, hgr->hedgeNum * sizeof(int)));
            unsigned* pnodes;
            CHECK_ERROR(cudaMalloc((void**)&pnodes, hgr->hedgeNum * sizeof(unsigned)));
            int* flags;
            CHECK_ERROR(cudaMalloc((void**)&flags, hgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)flags, 0, hgr->hedgeNum * sizeof(int)));

            TIMERSTART(4_1)
            mergeNodesInsideHyperedges_split1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
                                                                aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId, 
                                                                counts, pnodes, flags);
            TIMERSTOP(4_1)

            TIMERSTART(4_2)
            mergeNodesInsideHyperedges_split2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
                                                                aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId, 
                                                                counts, pnodes, flags);
            TIMERSTOP(4_2)
        
            iter_split_k4.push_back(time4_1);
            iter_split_k4.push_back(time4_2);
            CHECK_ERROR(cudaFree(counts));
            CHECK_ERROR(cudaFree(pnodes));
            CHECK_ERROR(cudaFree(flags));
        } else {
        
            std::cout << "total # of blocks launched:" << gridsize << "\n";
            
            long long* d_timer, *d_timer1, *d_timer2;
            // CHECK_ERROR(cudaMalloc((void**)&d_timer, gridsize * 2 * sizeof(long long)));
            // CHECK_ERROR(cudaMemset((void*)d_timer, 0, gridsize * 2 * sizeof(long long)));
            // CHECK_ERROR(cudaMalloc((void**)&d_timer1, gridsize * blocksize * sizeof(long long)));
            // CHECK_ERROR(cudaMemset((void*)d_timer1, 0, gridsize * blocksize * sizeof(long long)));
            // CHECK_ERROR(cudaMalloc((void**)&d_timer2, gridsize * blocksize * sizeof(long long)));
            // CHECK_ERROR(cudaMemset((void*)d_timer2, 0, gridsize * blocksize * sizeof(long long)));
            int* d_realwork, *d_realwork1;
            // CHECK_ERROR(cudaMalloc((void**)&d_realwork, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemset((void*)d_realwork, 0, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMalloc((void**)&d_realwork1, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemset((void*)d_realwork1, 0, hgr->hedgeNum * sizeof(int)));
            TIMERSTART(4)
            // if (iter > 0) {
            mergeNodesInsideHyperedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
                                                                aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId, 
                                                                d_timer, d_timer1, d_timer2, d_realwork, d_realwork1);
            // } else {
            // mergeNodesInsideHyperedges_new<<<UP_DIV(aux->total_thread_num, blocksize), blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
            //                                                     aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId, 
            //                                                     aux->hedge_off_per_thread, aux->total_thread_num);
            // }
            TIMERSTOP(4)
            GET_LAST_ERR();
            time += time4 / 1000.f;
            perfs[4].second += time4;
            kernel_pairs.push_back(std::make_pair("mergeNodesInsideHyperedges", time4));
            iter_time += time4;
            optcfgs.iterative_K4.push_back(time4);
#if 0
            // long long* timer = (long long*)malloc(gridsize * 2 * sizeof(long long));
            // CHECK_ERROR(cudaMemcpy((void *)timer, d_timer, gridsize * 2 * sizeof(long long), cudaMemcpyDeviceToHost));
            long long* timer1 = (long long*)malloc(gridsize * blocksize * sizeof(long long));
            CHECK_ERROR(cudaMemcpy((void *)timer1, d_timer1, gridsize * blocksize * sizeof(long long), cudaMemcpyDeviceToHost));
            long long* timer2 = (long long*)malloc(gridsize * blocksize * sizeof(long long));
            CHECK_ERROR(cudaMemcpy((void *)timer2, d_timer2, gridsize * blocksize * sizeof(long long), cudaMemcpyDeviceToHost));
            int* real_work_cnt = (int*)malloc(hgr->hedgeNum * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)real_work_cnt, d_realwork, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
            // int* real_work_cnt1 = (int*)malloc(hgr->hedgeNum * sizeof(int));
            // CHECK_ERROR(cudaMemcpy((void *)real_work_cnt1, d_realwork1, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
            int* hedges = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)hedges, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            // compute the diff between the last block end and the first block start
            // long long minBeg = timer[0];
            // long long maxEnd = timer[gridsize];
            // long long minBeg1 = timer1[0];
            // long long maxEnd1 = timer1[gridsize];
            // for (int i = 1; i < gridsize; ++i) {
            //     minBeg = timer[i] < minBeg ? timer[i] : minBeg;
            //     maxEnd = timer[i + gridsize] > maxEnd ? timer[i + gridsize] : maxEnd;
            // }
            // for (int i = 1; i < gridsize; ++i) {
            //     minBeg1 = timer1[i] < minBeg1 ? timer1[i] : minBeg1;
            //     maxEnd1 = timer1[i + gridsize] > maxEnd1 ? timer1[i + gridsize] : maxEnd1;
            // }
            long long elap = timer2[0];
            for (int i = 1; i < gridsize * blocksize; ++i) {
                elap = max(elap, timer2[i]);
            }
            long sum_work_items = 0;
            long double avgAvgClocksPerNode = 0;
            long double sum_clocks = 0;
            for (int i = 0; i < hgr->hedgeNum; ++i) {
                sum_work_items += real_work_cnt[i];
                avgAvgClocksPerNode += (long double)(timer2[i]) / real_work_cnt[i];
                sum_clocks += timer2[i];
            }
            long double avgClocksPerUnitWork = sum_clocks / sum_work_items;
            long double realAvgClocksPerNode = 0;
            int* real_work_thread_div = (int*)malloc(hgr->hedgeNum * sizeof(int));
            for (int i = 0; i < UP_DIV(hgr->hedgeNum, 32); i++) {
                int max_work_load = 0;
                for (int j = i * 32; j < (i+1) * 32 && j < hgr->hedgeNum; j++) {
                    max_work_load = max(max_work_load, real_work_cnt[j]);
                }
                for (int j = i * 32; j < (i+1) * 32 && j < hgr->hedgeNum; j++) {
                    real_work_thread_div[j] = max_work_load;
                    realAvgClocksPerNode += (long double)(timer2[j]) / real_work_thread_div[j];
                }
            }
            // for (int i = 0; i < hgr->hedgeNum; ++i) {
            //     realAvgClocksPerNode += (long double)(timer2[i]) / real_work_thread_div[i];
            // }
            realAvgClocksPerNode /= hgr->hedgeNum;
            avgAvgClocksPerNode /= hgr->hedgeNum;
            long long elap1 = timer1[0];
            for (int i = 1; i < gridsize * blocksize; ++i) {
                elap1 = max(elap1, timer1[i]);
            }
            long double avgAvgClocksPerNode1 = 0;
            for (int i = 0; i < hgr->hedgeNum; ++i) {
                avgAvgClocksPerNode1 += (long double)(timer1[i]) / hedges[i + E_DEGREE1(hgr->hedgeNum)];
            }
            avgAvgClocksPerNode1 /= hgr->hedgeNum;
            // std::string output = optcfgs.filename + "_cycles_info_baseline.csv";
            // std::ofstream wr(output);
            // wr << "clock_time1, real_work_num, hedgesize, avgClocksPerNode1, clock_time2, real_work_num2\n";
            // for (int i = 0; i < hgr->hedgeNum; ++i) {
            //     wr << timer2[i] << ",    " << real_work_cnt[i] << ",    " << hedges[i + E_DEGREE1(hgr->hedgeNum)] << ",     " << (long double)(timer2[i]) / real_work_cnt[i] << ",     " 
            //        << timer1[i] << ",    " << real_work_cnt1[i] << "\n";
            // }
            // std::string output1 = optcfgs.filename + "_cycles_info_baseline_thrd_dive.csv";
            // std::ofstream wr1(output1);
            // wr1 << "clock_time1, real_work_num, real_work_num_thrd_dive, hedgesize, realAvgClocksPerNode1, clock_time2, real_work_num2\n";
            // for (int i = 0; i < hgr->hedgeNum; ++i) {
            //     wr1 << timer2[i] << ",    " << real_work_cnt[i] << ",    " << real_work_thread_div[i] << ",     " << hedges[i + E_DEGREE1(hgr->hedgeNum)] << ",     "
            //         << (long double)(timer2[i]) / real_work_thread_div[i] << ",     "
            //         << timer1[i] << ",    " << real_work_cnt1[i] << "\n";
            // }
            std::cout << "real_work_num:" << sum_work_items << ", theorectical_work_num:" << hgr->totalEdgeDegree << "\n";
            // iter_split_k4_in_kernel.push_back(static_cast<long long>((maxEnd - minBeg) / CLOCKS_PER_SEC) * 1000.f);
            // iter_split_k4_in_kernel.push_back(static_cast<long long>((maxEnd1 - minBeg1) / CLOCKS_PER_SEC) * 1000.f);
            // iter_split_k4_in_kernel.push_back(static_cast<long double>(elap / (props.clockRate * 1000.f) * 1000.f));
            // iter_split_k4_in_kernel.push_back(avgAvgClocksPerNode);
            // iter_split_k4_in_kernel.push_back(realAvgClocksPerNode);
            iter_split_k4_in_kernel.push_back(avgClocksPerUnitWork * sum_work_items);
            iter_split_k4_in_kernel.push_back(avgClocksPerUnitWork);
            // iter_split_k4_in_kernel.push_back(avgClocksPerUnitWork * hgr->hedgeNum * hgr->maxDegree);
            // iter_split_k4_in_kernel.push_back(static_cast<long double>(elap1 / (props.clockRate * 1000.f) * 1000.f));
            // iter_split_k4_in_kernel.push_back(avgAvgClocksPerNode1);
#endif
            // CHECK_ERROR(cudaFree(d_timer));
            // CHECK_ERROR(cudaFree(d_timer1));
            // CHECK_ERROR(cudaFree(d_timer2));
            // CHECK_ERROR(cudaFree(d_realwork));
            // CHECK_ERROR(cudaFree(d_realwork1));
        }
    }
    // std::cout << "current # non-duplicates:" << aux->dupCnts[0] << "\n";
    int a, b;
    CHECK_ERROR(cudaMemcpy((void *)&a, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&b, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    std::cout << "new hedgeNum: " << b << ", new nodeNum: " << a << std::endl;

    // if (iter == 0) {
    //     std::ofstream debug("after_K4_adj_mapped_nodelist.txt");
    //     int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    //     int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* eMatch = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eMatch, aux->eMatch, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     debug << "(adjlist_id, parent_id, isDuplica, isSelfMergeNode)\n";
    //     for (int i = 0; i < hgr->hedgeNum; ++i) {
    //         debug << "eInBag:" << eInBag[i] << ", eMatch:" << eMatch[i] << ",  ";
    //         for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
    //             int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
    //             debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
    //         }
    //         debug << "\n";
    //     }
    // }

#if 0
    if (iter == 0) {
        // unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        // CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        // int* nMatch = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)nMatch, aux->nMatch, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        int* hedgeid = (int*)malloc(hgr->totalEdgeDegree * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedgeid, aux->pins_hedgeid_list, hgr->totalEdgeDegree * sizeof(int), cudaMemcpyDeviceToHost));
        int* h_candidates = (int*)malloc(hgr->nodeNum * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)h_candidates, aux->canBeCandidates, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        std::string file = "weight_after_scan_" + std::to_string(iter) + ".txt";
        // std::ofstream debug(file);
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     for (int j = 0; j < hedge[E_DEGREE1(hgr->hedgeNum) + i]; ++j) {
        //         unsigned dst = hedge[E_OFFSET1(hgr->hedgeNum) + i] + j;
        //         debug << aux->cand_weight_list[dst] << " ";
        //     }
        //     debug << "\n";
        // }
        // file = "pins_hedgeid_list_" + std::to_string(iter) + ".txt";
        // std::ofstream debug1(file);
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     for (int j = 0; j < hedge[E_DEGREE1(hgr->hedgeNum) + i]; ++j) {
        //         unsigned dst = hedge[E_OFFSET1(hgr->hedgeNum) + i] + j;
        //         debug1 << hedgeid[dst] << " ";
        //     }
        //     debug1 << "\n";
        // }
        for (int i = 0; i < hgr->nodeNum; ++i) {
            if (test_candidates[i] != h_candidates[i]) {
                std::cout << __LINE__ << "inEqual@: " << i << "-th node, mine:" << test_candidates[i] << ", correct:" << h_candidates[i] << "\n";
                break; 
            }
        }
        file = "candidate_count_" + std::to_string(iter) + ".txt";
        std::ofstream debug2(file);
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            debug2 << counts[i] << "\n";
        }
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            if (aux->cand_counts[i] != counts[i]) {
                std::cout << __LINE__ << "inEqual@: " << i << "-th hedge, mine:" << aux->cand_counts[i] << ", correct:" << counts[i] << "\n";
                break;
            }
        }
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            if (aux->nodeid[i] != pnodes[i]) {
                std::cout << __LINE__ << "inEqual@: " << i << "-th hedge, mine:" << aux->nodeid[i] << ", correct:" << pnodes[i] << "\n";
                break;
            }
        }
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            if (aux->flags[i] != flags[i]) {
                std::cout << __LINE__ << "inEqual@: " << i << "-th hedge, mine:" << aux->flags[i] << ", correct:" << flags[i] << "\n";
                break;
            }
        }
        for (int i = 0; i < hgr->nodeNum; ++i) {
            if (parent[i] != nodes[i + N_PARENT1(hgr->nodeNum)]) {
                std::cout << __LINE__ << "inEqual@: " << i << "-th hedge, mine:" << parent[i] << ", correct:" << flags[i] << "\n";
                break;
            }
        }
    }
#endif
    
#if 0
    if (iter < 3) {
        if (!optcfgs.useNewKernel5) {
        // if (!optcfgs.run_bug) {
            std::string file1 = "../debug/test_old_kernel4_hedgelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug1(file1);
            int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < E_LENGTH1(hgr->hedgeNum); ++i) {
                if (i / hgr->hedgeNum == 0) {
                    debug1 << "E_PRIORITY: ";
                }
                if (i / hgr->hedgeNum == 1) {
                    debug1 << "E_RAND: ";
                }
                if (i / hgr->hedgeNum == 2) {
                    debug1 << "E_IDNUM: ";
                }
                if (i / hgr->hedgeNum == 3) {
                    debug1 << "E_OFFSET: ";
                }
                if (i / hgr->hedgeNum == 4) {
                    debug1 << "E_DEGREE: ";
                }
                if (i / hgr->hedgeNum == 5) {
                    debug1 << "E_ELEMID: ";
                }
                if (i / hgr->hedgeNum == 6) {
                    debug1 << "E_MATCHED: ";
                    if (i == 96779) std::cout << "@@" << hedge[i] << "\n";
                }
                if (i / hgr->hedgeNum == 7) {
                    debug1 << "E_INBAG: ";
                }
                if (i / hgr->hedgeNum == 8) {
                    debug1 << "E_NEXTID: ";
                }
                debug1 << hedge[i] << "\n";
            }
            std::cout << "incorrect hedge " << 96779 % hgr->hedgeNum << "\n";
            std::cout << hedge[96779] << "\n";
            std::string file2 = "../debug/test_old_kernel4_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
                if (i / hgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / hgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / hgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / hgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / hgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / hgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / hgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / hgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / hgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / hgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / hgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / hgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / hgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / hgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / hgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / hgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / hgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / hgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / hgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / hgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
        } else {
            std::string file1 = "../debug/test_new_kernel4_hedgelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug1(file1);
            int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < E_LENGTH1(hgr->hedgeNum); ++i) {
                if (i / hgr->hedgeNum == 0) {
                    debug1 << "E_PRIORITY: ";
                }
                if (i / hgr->hedgeNum == 1) {
                    debug1 << "E_RAND: ";
                }
                if (i / hgr->hedgeNum == 2) {
                    debug1 << "E_IDNUM: ";
                }
                if (i / hgr->hedgeNum == 3) {
                    debug1 << "E_OFFSET: ";
                }
                if (i / hgr->hedgeNum == 4) {
                    debug1 << "E_DEGREE: ";
                }
                if (i / hgr->hedgeNum == 5) {
                    debug1 << "E_ELEMID: ";
                }
                if (i / hgr->hedgeNum == 6) {
                    debug1 << "E_MATCHED: ";
                }
                if (i / hgr->hedgeNum == 7) {
                    debug1 << "E_INBAG: ";
                }
                if (i / hgr->hedgeNum == 8) {
                    debug1 << "E_NEXTID: ";
                }
                debug1 << hedge[i] << "\n";
            }
            std::string file2 = "../debug/test_new_kernel4_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
                if (i / hgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / hgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / hgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / hgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / hgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / hgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / hgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / hgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / hgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / hgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / hgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / hgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / hgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / hgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / hgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / hgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / hgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / hgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / hgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / hgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
        }
    }
#endif
    CHECK_ERROR(cudaMemset((void*)aux->cand_counts, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates, 0, hgr->nodeNum * sizeof(int)));

    // CHECK_ERROR(cudaMalloc((void**)&aux->represent, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&aux->represent, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->represent, 0, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMalloc((void**)&aux->best, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&aux->best, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->best, 0, hgr->hedgeNum * sizeof(int)));
    // thrust::fill(thrust::device, aux->best, aux->best + hgr->hedgeNum, INT_MAX);
    // thrust::fill(thrust::device, aux->represent, aux->represent + hgr->hedgeNum, INT_MAX);

    // CHECK_ERROR(cudaMalloc((void**)&aux->weight_vals, hgr->hedgeNum * sizeof(int)));
    // // CHECK_ERROR(cudaMallocManaged(&aux->weight_vals, hgr->hedgeNum * sizeof(int)));
    // thrust::fill(thrust::device, aux->weight_vals, aux->weight_vals + hgr->hedgeNum, INT_MAX);
    // CHECK_ERROR(cudaMalloc((void**)&aux->nodeid_keys, hgr->hedgeNum * sizeof(int)));
    // // CHECK_ERROR(cudaMallocManaged(&aux->nodeid_keys, hgr->hedgeNum * sizeof(int)));
    // // CHECK_ERROR(cudaMemset((void*)aux->nodeid_keys, 0, hgr->hedgeNum * sizeof(int)));
    // thrust::fill(thrust::device, aux->nodeid_keys, aux->nodeid_keys + hgr->hedgeNum, INT_MAX);
    // tmp_nodes* tNodesAttr;
    // CHECK_ERROR(cudaMallocManaged(&tNodesAttr, hgr->totalEdgeDegree * sizeof(tmp_nodes)));
    // CHECK_ERROR(cudaMemset((void*)tNodesAttr, 0, hgr->totalEdgeDegree * sizeof(tmp_nodes)));
    // CHECK_ERROR(cudaMallocManaged(&tNodesAttr, hgr->hedgeNum * sizeof(tmp_nodes)));
    // CHECK_ERROR(cudaMalloc((void**)&tNodesAttr, hgr->hedgeNum * sizeof(tmp_nodes)));
    // CHECK_ERROR(cudaMemset((void*)tNodesAttr, 0, hgr->hedgeNum * sizeof(tmp_nodes)));
    
#if 0
    int* test_candidates;
    // CHECK_ERROR(cudaMalloc((void**)&test_candidates, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&test_candidates, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)test_candidates, aux->canBeCandidates1, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));
    int* cand_counts;
    CHECK_ERROR(cudaMallocManaged(&cand_counts, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)cand_counts, 0, hgr->hedgeNum * sizeof(int)));
    
#endif
#if 0
    CHECK_ERROR(cudaMemset((void*)aux->nodeid, 0, hgr->hedgeNum * sizeof(int))); // for represent

    CHECK_ERROR(cudaMallocManaged(&aux->nodeid_keys, hgr->totalEdgeDegree * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nodeid_keys, 0, hgr->totalEdgeDegree * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&aux->weight_vals, hgr->totalEdgeDegree * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->weight_vals, 0, hgr->totalEdgeDegree * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&aux->key_counts, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->key_counts, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&aux->num_items, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->num_items, 0, sizeof(int)));

    int* test_represent;
    CHECK_ERROR(cudaMallocManaged(&test_represent, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)test_represent, 0, hgr->hedgeNum * sizeof(int)));
    int* test_best;
    CHECK_ERROR(cudaMallocManaged(&test_best, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)test_best, 0, hgr->hedgeNum * sizeof(int)));
    int* test_count;
    CHECK_ERROR(cudaMallocManaged(&test_count, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)test_count, 0, hgr->hedgeNum * sizeof(int)));

    int* test_represent1;
    CHECK_ERROR(cudaMallocManaged(&test_represent1, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)test_represent1, 0, hgr->hedgeNum * sizeof(int)));
    int* test_best1;
    CHECK_ERROR(cudaMallocManaged(&test_best1, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)test_best1, 0, hgr->hedgeNum * sizeof(int)));

    // CHECK_ERROR(cudaMalloc((void**)&tNodesAttr, hgr->hedgeNum * sizeof(tmp_nodes)));
    // CHECK_ERROR(cudaMemset((void*)tNodesAttr, 0, hgr->hedgeNum * sizeof(tmp_nodes)));

    int* nInBag1;
    CHECK_ERROR(cudaMalloc((void**)&nInBag1, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)nInBag1, aux->nInBag1, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));
    int* tmpW;
    CHECK_ERROR(cudaMalloc((void**)&tmpW, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)tmpW, aux->tmpW, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));

    int* nMatch;
    CHECK_ERROR(cudaMalloc((void**)&nMatch, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)nMatch, aux->nMatch, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));

    int* parent;
    CHECK_ERROR(cudaMalloc((void**)&parent, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged((void**)&parent, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)parent, hgr->nodes + N_PARENT1(hgr->nodeNum), hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));

    int* hedgeid;
    CHECK_ERROR(cudaMalloc((void**)&hedgeid, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)hedgeid, aux->nMatchHedgeId, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToDevice));
#endif

    if (!optcfgs.useNewKernel5) {
        TIMERSTART(5)
        PrepareForFurtherMatching<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, aux->eMatch, aux->nMatch, aux->nPriori/*, aux->best, aux->represent, aux->key_counts*/);
        // PrepareForFurtherMatching<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, eMatch, aux->nMatch, aux->nPriori);
        TIMERSTOP(5)
        time += time5 / 1000.f;
        kernel_pairs.push_back(std::make_pair("PrepareForFurtherMatching", time5));
        iter_time += time5;
        perfs[5].second += time5;
    } else {
        TIMERSTART(5)
        // resetAlreadyMatchedNodePriorityInUnmatchedHedge<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, 
        //                                                 hgr->totalEdgeDegree, aux->eMatch, aux->nMatch, aux->nPriori);
        // resetAlreadyMatchedNodePriorityInUnmatchedHedge<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, 
        //                                                 hgr->totalEdgeDegree, eMatch, aux->nMatch, aux->nPriori);
        resetAlreadyMatchedNodePriorityInUnmatchedHedge<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, 
                                                        hgr->totalEdgeDegree, aux->eMatch, aux->nMatch, aux->nPriori/*,
                                                        aux->key_counts, aux->nodeid_keys, aux->weight_vals, aux->num_items, tNodesAttr*/);
        TIMERSTOP(5)
        time += time5 * 0.9 / 1000.f;
        kernel_pairs.push_back(std::make_pair("resetAlreadyMatchedNodePriorityInUnmatchedHedge", time5));
        iter_time += time5;
        perfs[5].second += time5;
    }
#if 0
    if (iter < 3) {
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        if (!optcfgs.useNewKernel5) {
            std::string file2 = "../debug/test_old_kernel5_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
                if (i / hgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / hgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / hgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / hgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / hgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / hgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / hgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / hgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / hgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / hgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / hgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / hgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / hgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / hgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / hgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / hgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / hgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / hgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / hgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / hgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
        } else {
            std::string file2 = "../debug/test_new_kernel5_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
                if (i / hgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / hgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / hgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / hgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / hgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / hgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / hgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / hgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / hgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / hgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / hgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / hgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / hgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / hgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / hgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / hgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / hgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / hgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / hgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / hgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
        }
    }
#endif

    // if (optcfgs.enableSelection && optcfgs.filename.find("lang") != std::string::npos) {
    //     optcfgs.useTWCoptForKernel6 = true;
    //     optcfgs.useTWCThreshold = true;
    //     optcfgs.useWarpBased = true;
    // }
    float cur_k6 = 0.0;
    if (optcfgs.optForKernel6) {
        CHECK_ERROR(cudaMalloc((void**)&aux->weight_vals, hgr->hedgeNum * sizeof(int)));
        thrust::fill(thrust::device, aux->weight_vals, aux->weight_vals + hgr->hedgeNum, INT_MAX);
        CHECK_ERROR(cudaMalloc((void**)&aux->nodeid_keys, hgr->hedgeNum * sizeof(int)));
        thrust::fill(thrust::device, aux->nodeid_keys, aux->nodeid_keys + hgr->hedgeNum, INT_MAX);
        if (optcfgs.useTWCoptForKernel6) {
            int blocksize1 = optcfgs.blocksize[0], blocksize2 = optcfgs.blocksize[1], blocksize3 = optcfgs.blocksize[2], blocksize4 = optcfgs.blocksize[3];
            std::cout << optcfgs.twc_threshod[0] << ", " << optcfgs.twc_threshod[1] << "\n";
            std::cout << blocksize1 << ", " << blocksize2 << ", " << blocksize3 << ", " << blocksize4 << "\n";
            cudaStream_t stream1, stream2, stream3, stream4;
            tmp_hedge *hedgelist;
            tmp_hedge *shedges, *mhedges, *lhedges;
            int slen, mlen, llen;
            // cudaStreamCreateWithFlags(&stream1, cudaStreamNonBlocking);
            // cudaStreamCreateWithFlags(&stream2, cudaStreamNonBlocking);
            CHECK_ERROR(cudaStreamCreate(&stream1));
            CHECK_ERROR(cudaStreamCreate(&stream2));
            CHECK_ERROR(cudaStreamCreate(&stream3));
            CHECK_ERROR(cudaStreamCreate(&stream4));
            
            if (optcfgs.useThrustRemove) {
                CHECK_ERROR(cudaMalloc((void**)&hedgelist, hgr->hedgeNum * sizeof(tmp_hedge)));
                CHECK_ERROR(cudaMalloc((void**)&shedges, hgr->hedgeNum * sizeof(tmp_hedge)));
                CHECK_ERROR(cudaMalloc((void**)&mhedges, hgr->hedgeNum * sizeof(tmp_hedge)));
                CHECK_ERROR(cudaMalloc((void**)&lhedges, hgr->hedgeNum * sizeof(tmp_hedge)));
            } else {
                CHECK_ERROR(cudaMalloc((void**)&aux->s_hedgeidList, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->s_hedgeidList, 0, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&aux->m_hedgeidList, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->m_hedgeidList, 0, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&aux->l_hedgeidList, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->l_hedgeidList, 0, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&aux->u_hedgeidList, hgr->hedgeNum * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->u_hedgeidList, 0, hgr->hedgeNum * sizeof(int)));
                if (optcfgs.useMarkListForK6) {
                    CHECK_ERROR(cudaMalloc((void**)&aux->mark_sHedge, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->mark_sHedge, 0, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMalloc((void**)&aux->mark_mHedge, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->mark_mHedge, 0, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMalloc((void**)&aux->mark_lHedge, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->mark_lHedge, 0, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMalloc((void**)&aux->mark_uHedge, hgr->hedgeNum * sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->mark_uHedge, 0, hgr->hedgeNum * sizeof(int)));
                } else {
                    CHECK_ERROR(cudaMallocManaged(&aux->s_counter, sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->s_counter, 0, sizeof(int)));
                    CHECK_ERROR(cudaMallocManaged(&aux->m_counter, sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->m_counter, 0, sizeof(int)));
                    CHECK_ERROR(cudaMallocManaged(&aux->l_counter, sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->l_counter, 0, sizeof(int)));
                    CHECK_ERROR(cudaMallocManaged(&aux->u_counter, sizeof(int)));
                    CHECK_ERROR(cudaMemset((void*)aux->u_counter, 0, sizeof(int)));
                }
            }

            // int* hedgesize;
            // CHECK_ERROR(cudaMalloc((void**)&hedgesize, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemcpy((void *)hedgesize, hgr->hedges + E_DEGREE1(hgr->hedgeNum), hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));

            if (!optcfgs.useTWCThreshold) {
                if (!optcfgs.useMarkListForK6) {
                    TIMERSTART(_atomic)
                    // assignEachHedgeToCorrespondingKernel<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->s_counter, aux->m_counter, aux->l_counter, aux->u_counter,
                    //                                                                     aux->s_hedgeidList, aux->m_hedgeidList, aux->l_hedgeidList, aux->u_hedgeidList);
                    assignEachHedgeToCorrespondingKernel<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->s_counter, aux->m_counter, aux->l_counter, aux->u_counter,
                                                                                        aux->s_hedgeidList, aux->m_hedgeidList, aux->l_hedgeidList, aux->u_hedgeidList);
                    TIMERSTOP(_atomic)
                    kernel_pairs.push_back(std::make_pair("assignEachHedgeToCorrespondingKernel", time_atomic));
                    cur_k6 += time_atomic;
                } else {
                    TIMERSTART(_mark)
                    // markHedgeInCorrespondingWorkLists<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->mark_sHedge, aux->mark_mHedge, aux->mark_lHedge, aux->mark_uHedge);
                    markHedgeInCorrespondingWorkLists<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->mark_sHedge, aux->mark_mHedge, aux->mark_lHedge, aux->mark_uHedge);
                    TIMERSTOP(_mark)
                    TIMERSTART(_scan)
                    thrust::inclusive_scan(thrust::cuda::par.on(stream1), aux->mark_sHedge, aux->mark_sHedge + hgr->hedgeNum, aux->mark_sHedge);
                    thrust::inclusive_scan(thrust::cuda::par.on(stream2), aux->mark_mHedge, aux->mark_mHedge + hgr->hedgeNum, aux->mark_mHedge);
                    thrust::inclusive_scan(thrust::cuda::par.on(stream3), aux->mark_lHedge, aux->mark_lHedge + hgr->hedgeNum, aux->mark_lHedge);
                    thrust::inclusive_scan(thrust::cuda::par.on(stream4), aux->mark_uHedge, aux->mark_uHedge + hgr->hedgeNum, aux->mark_uHedge);
                    TIMERSTOP(_scan)
                    TIMERSTART(_scatter)
                    // putValidHedgeIntoCorrespondingList<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->mark_sHedge, aux->s_hedgeidList, aux->mark_mHedge, aux->m_hedgeidList,
                    //                                                                 aux->mark_lHedge, aux->l_hedgeidList, aux->mark_uHedge, aux->u_hedgeidList);
                    putValidHedgeIntoCorrespondingList<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->mark_sHedge, aux->s_hedgeidList, aux->mark_mHedge, aux->m_hedgeidList,
                                                                                    aux->mark_lHedge, aux->l_hedgeidList, aux->mark_uHedge, aux->u_hedgeidList);
                    TIMERSTOP(_scatter)
                    kernel_pairs.push_back(std::make_pair("markHedgeInCorrespondingWorkLists", time_mark));
                    kernel_pairs.push_back(std::make_pair("thrust::inclusive_scan", time_scan));
                    kernel_pairs.push_back(std::make_pair("putValidHedgeIntoCorrespondingList", time_scatter));
                    cur_k6 += (time_mark + time_scan + time_scatter);
                }
            }
            // if (optcfgs.tuneTWCThreshold) {
            else {
                std::cout << gridsize << ", " << blocksize << "\n";
                if (optcfgs.useThrustRemove) {
                    TIMERSTART(_ass)
                    assignHedgeInfo<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, hedgelist);
                    TIMERSTOP(_ass)

                    TIMERSTART(_rmv)
                    tmp_hedge* send = thrust::remove_copy_if(thrust::cuda::par.on(stream1), hedgelist, hedgelist+hgr->hedgeNum, shedges, is_small());
                    tmp_hedge* mend = thrust::remove_copy_if(thrust::cuda::par.on(stream2), hedgelist, hedgelist+hgr->hedgeNum, mhedges, is_medium());
                    tmp_hedge* lend = thrust::remove_copy_if(thrust::cuda::par.on(stream3), hedgelist, hedgelist+hgr->hedgeNum, lhedges, is_large());
                    TIMERSTOP(_rmv)
                    slen = send - shedges, mlen = mend - mhedges, llen = lend - lhedges;
                    std::cout << slen << ", " << mlen << ", " << llen << "\n";
                    cur_k6 += time_ass + time_rmv;
                } else {
                    if (!optcfgs.useMarkListForK6) {
                        TIMERSTART(_atomic)
                        // assignTWCHedgeWorkListsWithTunableThresholds<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->s_counter, aux->m_counter, aux->l_counter, aux->u_counter,
                        //                                             aux->s_hedgeidList, aux->m_hedgeidList, aux->l_hedgeidList, aux->u_hedgeidList, optcfgs.twc_threshod[0], optcfgs.twc_threshod[1]);
                        assignTWCHedgeWorkListsWithTunableThresholds<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->s_counter, aux->m_counter, aux->l_counter,
                                                                    aux->s_hedgeidList, aux->m_hedgeidList, aux->l_hedgeidList, optcfgs.twc_threshod[0], optcfgs.twc_threshod[1]/*, hedgesize*/);
                        TIMERSTOP(_atomic)
                        kernel_pairs.push_back(std::make_pair("assignTWCHedgeWorkListsWithTunableThresholds", time_atomic));
                        cur_k6 += time_atomic;
                    } else {
                        // markHedgeInCorrespondingWorkLists1<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->mark_sHedge, aux->mark_mHedge, aux->mark_lHedge, 
                        //                                             optcfgs.twc_threshod[0], optcfgs.twc_threshod[1]);
                        TIMERSTART(_mark)
                        markHedgeInCorrespondingWorkLists1<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->eMatch, aux->mark_sHedge, aux->mark_mHedge, aux->mark_lHedge, 
                                                                    optcfgs.twc_threshod[0], optcfgs.twc_threshod[1]/*, hedgesize*/);
                        TIMERSTOP(_mark)
                        TIMERSTART(_scan)
                        thrust::inclusive_scan(thrust::cuda::par.on(stream1), aux->mark_sHedge, aux->mark_sHedge + hgr->hedgeNum, aux->mark_sHedge);
                        thrust::inclusive_scan(thrust::cuda::par.on(stream2), aux->mark_mHedge, aux->mark_mHedge + hgr->hedgeNum, aux->mark_mHedge);
                        thrust::inclusive_scan(thrust::cuda::par.on(stream3), aux->mark_lHedge, aux->mark_lHedge + hgr->hedgeNum, aux->mark_lHedge);
                        // thrust::inclusive_scan(thrust::cuda::par.on(stream4), aux->mark_uHedge, aux->mark_uHedge + hgr->hedgeNum, aux->mark_uHedge);
                        TIMERSTOP(_scan)
                        TIMERSTART(_scatter)
                        // putValidHedgeIntoCorrespondingList<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->mark_sHedge, aux->s_hedgeidList, aux->mark_mHedge, aux->m_hedgeidList,
                        //                                                                 aux->mark_lHedge, aux->l_hedgeidList, aux->mark_uHedge, aux->u_hedgeidList);
                        putValidHedgeIntoCorrespondingList<<<gridsize, blocksize>>>(hgr->hedges, hgr->hedgeNum, aux->mark_sHedge, aux->s_hedgeidList, aux->mark_mHedge, aux->m_hedgeidList,
                                                                                        aux->mark_lHedge, aux->l_hedgeidList, aux->mark_uHedge, aux->u_hedgeidList);
                        TIMERSTOP(_scatter)
                        kernel_pairs.push_back(std::make_pair("markHedgeInCorrespondingWorkLists1", time_mark));
                        kernel_pairs.push_back(std::make_pair("thrust::inclusive_scan", time_scan));
                        kernel_pairs.push_back(std::make_pair("putValidHedgeIntoCorrespondingList", time_scatter));
                        cur_k6 += (time_mark + time_scan + time_scatter);
                    }
                }
            }

            int s, m, l, u;
            if (!optcfgs.useThrustRemove) {
                if (!optcfgs.useMarkListForK6) {
                    CHECK_ERROR(cudaMemcpy((void *)&s, aux->s_counter, sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&m, aux->m_counter, sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&l, aux->l_counter, sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&u, aux->u_counter, sizeof(int), cudaMemcpyDeviceToHost));
                } else {
                    CHECK_ERROR(cudaMemcpy((void *)&s, &aux->mark_sHedge[hgr->hedgeNum-1], sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&m, &aux->mark_mHedge[hgr->hedgeNum-1], sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&l, &aux->mark_lHedge[hgr->hedgeNum-1], sizeof(int), cudaMemcpyDeviceToHost));
                    CHECK_ERROR(cudaMemcpy((void *)&u, &aux->mark_uHedge[hgr->hedgeNum-1], sizeof(int), cudaMemcpyDeviceToHost));
                }
            }
            std::cout << "s:" << s << ", m:" << m << ", l:" << l << ", u:" << u << "\n";
#if 1 // for testing overall time
            if (optcfgs.useThrustRemove) {
                TIMERSTART(_twc)
                processHedgesInThreadLevel_<<<UP_DIV(slen, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                            shedges, slen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                if (mlen) {
                processHedgesInWarpLevel_<<<(mlen + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    mhedges, mlen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                }
                if (llen) {
                processHedgesInBlockLevel_<<<llen, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                lhedges, llen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                }
                TIMERSTOP(_twc)
                cur_k6 += time_twc;
            } else if (!optcfgs.useReduceOptForKernel6) {
                std::cout << __LINE__ << "here@@@\n";
                if (optcfgs.useMarkListForK6) {
                    TIMERSTART(_twc)
                    if (s) {
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->s_hedgeidList, aux->mark_sHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    }
                    if (m) {
                    processHedgesInWarpLevel<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                            hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                            aux->m_hedgeidList, aux->mark_mHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                            aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    if (l) {
                    processHedgesInBlockLevel<<<l, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->l_hedgeidList, aux->mark_lHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                        aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    TIMERSTOP(_twc)
                    cur_k6 += time_twc;
                } else if (optcfgs.useWarpBased) {
                    TIMERSTART(_twc)
                    if (s) {
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->s_hedgeidList, aux->s_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    }
                    if (m) {
                    processHedgesInWarpLevel<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                            hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                            aux->m_hedgeidList, aux->m_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                            aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    if (l) {
                    std::cout << __LINE__ << "here$$$\n";
                    processHedgesInBlockLevel<<<l, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->l_hedgeidList, aux->l_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                        aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    TIMERSTOP(_twc)
                    cur_k6 += time_twc;
                }
            } else { // using shared mem reduce for warp level and block level
                if (optcfgs.useMarkListForK6) {
                    TIMERSTART(_twc)
                    if (s) {
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->s_hedgeidList, aux->mark_sHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    }
                    if (m) {       
                    processHedgesInWarpLevelWithSharedMemReduce<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, blocksize2 * 2 * sizeof(int), stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->m_hedgeidList, aux->mark_mHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    if (l) {
                    processHedgesInBlockLevelWithSharedMemReduce<<<l, blocksize3, blocksize3 * 2 * sizeof(int), stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->mark_lHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    TIMERSTOP(_twc)
                    cur_k6 += time_twc;
                } else if (optcfgs.useWarpBased) {
                    TIMERSTART(_twc)
                    if (s) {
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->s_hedgeidList, aux->s_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    }
                    if (m) {
                    processHedgesInWarpLevelWithSharedMemReduce<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, blocksize2 * 2 * sizeof(int), stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->m_hedgeidList, aux->m_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    if (l) {
                    processHedgesInBlockLevelWithSharedMemReduce<<<l, blocksize3, blocksize3 * 2 * sizeof(int), stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->l_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    }
                    TIMERSTOP(_twc)
                    cur_k6 += time_twc;
                }
            }
#endif
#if 0
            if (optcfgs.useThrustRemove) {
                TIMERSTART(_twc1)
                processHedgesInThreadLevel_<<<UP_DIV(slen, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                            shedges, slen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                TIMERSTOP(_twc1)
                kernel_pairs.push_back(std::make_pair("processSmallSizeHedges", time_twc1));
                cur_k6 += time_twc1;
                if (mlen) {
                    TIMERSTART(_twc2)
                    processHedgesInWarpLevel_<<<(mlen + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    mhedges, mlen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    TIMERSTOP(_twc2)
                    kernel_pairs.push_back(std::make_pair("processHedgesInWarpLevel", time_twc2));
                    cur_k6 += time_twc1;
                }
                if (llen) {
                    TIMERSTART(_twc3)
                    processHedgesInBlockLevel_<<<llen, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                lhedges, llen, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                    TIMERSTOP(_twc3)
                    kernel_pairs.push_back(std::make_pair("processHedgesInBlockLevel", time_twc3));
                }
            } else {
                if (optcfgs.useMarkListForK6) {
                    TIMERSTART(_twc1)
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                aux->s_hedgeidList, aux->mark_sHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    TIMERSTOP(_twc1)
                    kernel_pairs.push_back(std::make_pair("processSmallSizeHedges", time_twc1));
                } else {
                    TIMERSTART(_twc1)
                    processHedgesInThreadLevel<<<UP_DIV(s, blocksize1), blocksize1, 0, stream1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                aux->s_hedgeidList, aux->s_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId);
                    TIMERSTOP(_twc1)
                    kernel_pairs.push_back(std::make_pair("processSmallSizeHedges", time_twc1));
                }
                if (!optcfgs.useReduceOptForKernel6) {
                    if (m) {
                        if (!optcfgs.useWarpBased) {
                            TIMERSTART(_twc2)
                            if (!optcfgs.useMarkListForK6) {
                                processHedgesInBlockLevel<<<m, blocksize2, 0, stream2>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                            aux->m_hedgeidList, aux->m_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                            aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                            } else {
                                processHedgesInBlockLevel<<<m, blocksize2, 0, stream2>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->m_hedgeidList, aux->mark_mHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                        aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                            }
                            TIMERSTOP(_twc2)
                            kernel_pairs.push_back(std::make_pair("processHedgesInBlockLevel", time_twc2));
                        } else {
                            TIMERSTART(_twc2)
                            if (!optcfgs.useMarkListForK6) {
                                std::cout << "here!!\n";
                                processHedgesInWarpLevel<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                            hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                            aux->m_hedgeidList, aux->m_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                            aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                            } else {
                                processHedgesInWarpLevel<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, 0, stream2>>>(
                                                                        hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->m_hedgeidList, aux->mark_mHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                        aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                            }
                            TIMERSTOP(_twc2)
                            kernel_pairs.push_back(std::make_pair("processHedgesInWarpLevel", time_twc2));
                        }
                    }
                    if (l) {
                        TIMERSTART(_twc3)
                        if (!optcfgs.useMarkListForK6) {
                            std::cout << "here!!\n";
                        processHedgesInBlockLevel<<<l, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->l_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        } else {
                        processHedgesInBlockLevel<<<l, blocksize3, 0, stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->mark_lHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        }
                        TIMERSTOP(_twc3)
                        kernel_pairs.push_back(std::make_pair("processHedgesInBlockLevel", time_twc3));
                    }
                    if (u) {
                        if (!optcfgs.useMarkListForK6) {
                        processHedgesInBlockLevel<<<u, blocksize4, 0, stream4>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->u_hedgeidList, aux->u_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        } else {
                        processHedgesInBlockLevel<<<u, blocksize4, 0, stream4>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->u_hedgeidList, aux->mark_uHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        }
                    }
                } else {
                    if (m) {
                        if (!optcfgs.useMarkListForK6) {
                        processHedgesInWarpLevelWithSharedMemReduce<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, blocksize2 * 2 * sizeof(int), stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->m_hedgeidList, aux->m_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        } else {
                        processHedgesInWarpLevelWithSharedMemReduce<<<(m + blocksize2/32 - 1) / (blocksize2/32), blocksize2, blocksize2 * 2 * sizeof(int), stream2>>>(
                                                                    hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->m_hedgeidList, aux->mark_mHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        }
                    }
                    if (l) {
                        if (!optcfgs.useMarkListForK6) {
                        processHedgesInBlockLevelWithSharedMemReduce<<<l, blocksize3, blocksize3 * 2 * sizeof(int), stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->l_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        } else {
                        processHedgesInBlockLevelWithSharedMemReduce<<<l, blocksize3, blocksize3 * 2 * sizeof(int), stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->l_hedgeidList, aux->mark_lHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        }
                    }
                    if (u) {
                        if (!optcfgs.useMarkListForK6) {
                        processHedgesInBlockLevelWithSharedMemReduce<<<u, blocksize4, blocksize4 * 2 * sizeof(int), stream4>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->u_hedgeidList, aux->u_counter, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        } else {
                        processHedgesInBlockLevelWithSharedMemReduce<<<l, blocksize3, blocksize4 * 2 * sizeof(int), stream3>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                    aux->u_hedgeidList, aux->mark_uHedge + hgr->hedgeNum-1, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nPriori, aux->nMatchHedgeId,
                                                                    aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                        }
                    }
                }
            }
#endif
            GET_LAST_ERR();
            if (optcfgs.useThrustRemove) {
                CHECK_ERROR(cudaFree(hedgelist));
                CHECK_ERROR(cudaFree(shedges));
                CHECK_ERROR(cudaFree(mhedges));
                CHECK_ERROR(cudaFree(lhedges));
            } else {
                CHECK_ERROR(cudaFree(aux->s_hedgeidList));
                CHECK_ERROR(cudaFree(aux->m_hedgeidList));
                CHECK_ERROR(cudaFree(aux->l_hedgeidList));
                CHECK_ERROR(cudaFree(aux->u_hedgeidList));
                if (optcfgs.useMarkListForK6) {
                    CHECK_ERROR(cudaFree(aux->mark_sHedge));
                    CHECK_ERROR(cudaFree(aux->mark_mHedge));
                    CHECK_ERROR(cudaFree(aux->mark_lHedge));
                    CHECK_ERROR(cudaFree(aux->mark_uHedge));
                }
            }
            CHECK_ERROR(cudaStreamDestroy(stream1));
            CHECK_ERROR(cudaStreamDestroy(stream2));
            CHECK_ERROR(cudaStreamDestroy(stream3));
            CHECK_ERROR(cudaStreamDestroy(stream4));

            time += cur_k6 / 1000.f;
            perfs[6].second += cur_k6;
            iter_time += cur_k6;
            optcfgs.iterative_K6.push_back(cur_k6);
            std::cout << "TWC kernel 6 in iter" << iter << ": " << cur_k6 << " ms. (useStreamCompaction:" << optcfgs.useMarkListForK6 << ").\n";

        } else if (!optcfgs.useP2ForNodeMergingK6) {
            if (optcfgs.filename.find("Stanford") != std::string::npos || optcfgs.filename.find("dual") != std::string::npos || optcfgs.filename.find("Chebyshev4") != std::string::npos
                 || optcfgs.filename.find("trans4") != std::string::npos || optcfgs.filename.find("lang") != std::string::npos) {
                optcfgs.splitK6ForFindCands = 1, optcfgs.splitK6ForMerging = 1;
                optcfgs.splitK6ForFindRep = 1;
            }
            else if (optcfgs.filename.find("human_gene2") != std::string::npos || optcfgs.filename.find("gupta3") != std::string::npos || optcfgs.filename.find("kron") != std::string::npos) {
                optcfgs.splitK6ForFindCands = 0, optcfgs.splitK6ForMerging = 0;
                optcfgs.splitK6ForFindRep = 1;
            }
            else if (optcfgs.filename.find("wb-edu") != std::string::npos || optcfgs.filename.find("nlpkkt120") != std::string::npos || optcfgs.filename.find("primal") != std::string::npos) {
                optcfgs.splitK6ForFindCands = 1, optcfgs.splitK6ForMerging = 1;
                optcfgs.splitK6ForFindRep = 0;
            }
            else {
                std::cout << __LINE__ << "here!!\n";
                optcfgs.splitK6ForFindCands = 1, optcfgs.splitK6ForMerging = 1;
                optcfgs.splitK6ForFindRep = 0;//1;//
            }
            optcfgs.splitK6ForFindRep = 1;
            if (optcfgs.splitK6ForFindCands == 1) {
                TIMERSTART(6_1)
                parallelFindingCandsWithAtomicMin<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId,
                                                                aux->eMatch, aux->nMatch, aux->cand_counts, aux->canBeCandidates1, hgr->totalEdgeDegree/*, aux->nPriori, 
                                                                aux->key_counts, aux->nodeid_keys, aux->weight_vals, aux->num_items*/);
                // collectRepresentNodes<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId,
                //                                                     aux->eMatch, aux->nMatch, aux->nPriori, aux->cand_counts, aux->canBeCandidates, hgr->totalEdgeDegree,
                //                                                     aux->key_counts, aux->nodeid_keys, aux->weight_vals, aux->num_items, tNodesAttr);
                // selectRepresentNodes<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, 
                //                                             aux->eMatch, aux->nMatch, aux->nPriori, test_best1, test_represent1, test_count, aux->nodeid_keys, aux->weight_vals, tNodesAttr);
                // parallelMergingNodesForEachHedges0<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                         aux->eMatch, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId, aux->cand_counts);
                TIMERSTOP(6_1)
                kernel_pairs.push_back(std::make_pair("parallelFindingCandsWithAtomicMin", time6_1));
                cur_k6 += time6_1;
            } else if (optcfgs.splitK6ForFindCands == 0) {
                TIMERSTART(6_1)
                parallelFindingCandidatesForEachHedge<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,// aux->nPriori, parent,
                                                                        aux->cand_counts/*, test_represent1, test_best1, aux->nodeid_keys, aux->weight_vals, tNodesAttr*/);
                TIMERSTOP(6_1)
                kernel_pairs.push_back(std::make_pair("parallelFindingCandidatesForEachHedge", time6_1));
                cur_k6 += time6_1;
            }

            // int tune_bsize = 128;
            // int sharedMemBytes = tune_bsize * 2 * sizeof(int);

            // int* d_off;
            // CHECK_ERROR(cudaMallocManaged((void**)&d_off, (hgr->hedgeNum + 1) * sizeof(int)));
            // // CHECK_ERROR(cudaMemcpy((void *)d_off, aux->key_counts, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));
            // thrust::exclusive_scan(thrust::device, aux->key_counts, aux->key_counts + hgr->hedgeNum, d_off);
            // CHECK_ERROR(cudaMemcpy((void *)&d_off[hgr->hedgeNum], aux->num_items, sizeof(int), cudaMemcpyHostToDevice));
            // cub::DeviceSegmentedSort::SortPairs(d_temp_storage, temp_storage_bytes, aux->weight_vals, aux->weight_vals, aux->nodeid_keys, aux->nodeid_keys, aux->num_items[0], hgr->hedgeNum, d_off, d_off+1);
            // std::cout << "temp_storage_in_GB: " << temp_storage_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
            // CHECK_ERROR(cudaMallocManaged((void**)&d_temp_storage, temp_storage_bytes));
            // cub::DeviceSegmentedSort::SortPairs(d_temp_storage, temp_storage_bytes, aux->weight_vals, aux->weight_vals, aux->nodeid_keys, aux->nodeid_keys, aux->num_items[0], hgr->hedgeNum, d_off, d_off+1);
            // CHECK_ERROR(cudaFree(d_temp_storage));
            // CHECK_ERROR(cudaFree(d_off));

            if (optcfgs.splitK6ForFindRep == 0) {
                TIMERSTART(6_2)
                // parallelMergingNodesForEachHedges<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                         aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,// aux->nPriori, parent,
                //                                                         aux->cand_counts/*, test_represent1, test_best1, aux->nodeid_keys, aux->weight_vals, tNodesAttr*/);
                // parallelMergingNodesForEachHedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                         aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,// aux->nPriori, parent,
                //                                                         aux->cand_counts/*, test_represent1, test_best1, aux->nodeid_keys, aux->weight_vals, tNodesAttr*/);
                // parallelMergingNodesForEachHedges1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                         aux->eMatch, nInBag1, tmpW, nMatch, test_candidates, aux->nPriori, hedgeid, parent,
                //                                                         cand_counts, test_represent1, test_best1, aux->nodeid_keys, aux->weight_vals, tNodesAttr);
                // parallelMergingNodesForEachHedges1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                         aux->eMatch, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId,// aux->nInBag1, parent,
                //                                                         aux->cand_counts, aux->represent, aux->best/*, aux->nodeid_keys, aux->weight_vals, tNodesAttr*/);
                parallelFindingRepresentForEachHedge<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                        aux->eMatch, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId, aux->nInBag1,// parent,
                                                                        aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                TIMERSTOP(6_2)
                kernel_pairs.push_back(std::make_pair("parallelFindingRepresentForEachHedge", time6_2));
                std::cout << __LINE__ << " parallelFindingRepresentForEachHedge\n";
                cur_k6 += time6_2;
            } else {
                if (optcfgs.useReduceOptForKernel6) {
                    TIMERSTART(6_2)
                    parallelFindingRepresentWithReduceMin<<<hgr->hedgeNum, blocksize, blocksize * 2 * sizeof(int)>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId,
                                                                        aux->eMatch, aux->nMatch, aux->nPriori, aux->weight_vals, aux->nodeid_keys, hgr->totalEdgeDegree);
                    TIMERSTOP(6_2)
                    kernel_pairs.push_back(std::make_pair("parallelFindingRepresentWithReduceMin", time6_2));
                    std::cout << __LINE__ << " parallelFindingRepresentWithReduceMin\n";
                    cur_k6 += time6_2;
                } else {
                    TIMERSTART(6_2)
                    parallelFindingRepresentWithAtomicMin<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, aux->pins_hedgeid_list, aux->nMatchHedgeId,
                                                                                aux->eMatch, aux->nMatch, aux->nPriori, aux->weight_vals, hgr->totalEdgeDegree, aux->nodeid_keys);
                    TIMERSTOP(6_2)
                    kernel_pairs.push_back(std::make_pair("parallelFindingRepresentWithAtomicMin", time6_2));
                    std::cout << __LINE__ << " parallelFindingRepresentWithAtomicMin\n";
                    cur_k6 += time6_2;
                }
            }


            if (optcfgs.splitK6ForMerging == 1) {
                TIMERSTART(6_3)
                // parallelMatchNewCandsToSuperNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                             aux->eMatch, nInBag1, tmpW, nMatch, test_candidates, aux->nPriori, hedgeid, parent,
                //                                                             cand_counts, test_represent1, test_best1, aux->pins_hedgeid_list, hgr->totalEdgeDegree);
                // parallelMatchNewCandsToSuperNode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                //                                                             aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,// aux->nPriori, parent,
                //                                                             aux->cand_counts, aux->represent, aux->best, aux->pins_hedgeid_list, hgr->totalEdgeDegree);
                parallelMergingNodesForEachAdjElement<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                            aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,// aux->nPriori, parent,
                                                                            aux->cand_counts, aux->nodeid_keys, aux->weight_vals, aux->pins_hedgeid_list, hgr->totalEdgeDegree);
                TIMERSTOP(6_3)
                kernel_pairs.push_back(std::make_pair("parallelMergingNodesForEachAdjElement", time6_3));
                cur_k6 += time6_3;
            } else if (optcfgs.splitK6ForMerging == 0) {
                TIMERSTART(6_3)
                parallelMergingNodesForEachHedge<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                                aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nMatchHedgeId,
                                                                                aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
                TIMERSTOP(6_3)
                kernel_pairs.push_back(std::make_pair("parallelMergingNodesForEachHedge", time6_3));
                cur_k6 += time6_3;
            }

            time += cur_k6 / 1000.f;
            perfs[6].second += cur_k6;
            iter_time += cur_k6;
            optcfgs.iterative_K6.push_back(cur_k6);
            std::cout << "kernel 6 split in iter" << iter << ": " << cur_k6<< "\n";
            
            // if (iter == 0) {
            // if (optcfgs.useNewTest4 && optcfgs.useNewTest5 && optcfgs.useNewTest6) {
            //     debug << "newTest4:" << time_test4 << ", newTest5:" << time_test5 << ", newTest6:" << time_test6 << "\n";
            // }
            // if (!optcfgs.useNewTest4 && !optcfgs.useNewTest5 && !optcfgs.useNewTest6) {
            //     debug << "oldTest4:" << time_test4 << ", oldTest5:" << time_test5 << ", oldTest6:" << time_test6 << "\n";
            // }
            // debug << time_test4 << ", " << time_test5 << ", " << time_test6 << "\n";
            // debug << "newTest4:" << optcfgs.useNewTest4 << ", time:" << time_test4 << "  ";
            // debug << "newTest5:" << optcfgs.useNewTest5 << ", time:" << time_test5 << "  ";
            // debug << "newTest6:" << optcfgs.useNewTest6 << ", time:" << time_test6 << "\n";
                // debug << time_test5 << ",";
                // std::ofstream debug("curr_candidates.txt");
                // int* cands = (int*)malloc(hgr->nodeNum * sizeof(int));
                // CHECK_ERROR(cudaMemcpy((void *)cands, aux->canBeCandidates, sizeof(int) * hgr->nodeNum, cudaMemcpyDeviceToHost));
                // for (int i = 0; i < hgr->nodeNum; ++i) {
                //     debug << cands[i] << "\n";
                // }
                // std::ofstream debug1("curr_hedgelist.txt");
                // for (int i = 0; i < aux->s_counter[0]; ++i) {
                //     debug1 << aux->s_hedgeidList[i] << "\n";
                // }
            // }
        } else {
            std::cout << "running P2 for node merging kernel 6!\n";
            TIMERSTART(_opt6p2)
            mergeMoreNodesAcrossHyperedges_P2<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, 
                                                                aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId,
                                                                aux->cand_counts, aux->nodeid_keys, aux->weight_vals);
            TIMERSTOP(_opt6p2)
            time += time_opt6p2 / 1000.f;
            perfs[6].second += time_opt6p2;
            kernel_pairs.push_back(std::make_pair("mergeMoreNodesAcrossHyperedges_P2", time_opt6p2));
            optcfgs.iterative_K6.push_back(time_opt6p2);
            iter_time += time_opt6p2;
        }
        CHECK_ERROR(cudaFree(aux->weight_vals));
        CHECK_ERROR(cudaFree(aux->nodeid_keys));
    } else {
        // unsigned* real_access_size;
        // CHECK_ERROR(cudaMallocManaged(&real_access_size, hgr->hedgeNum * sizeof(unsigned)));
        // int bsize = 1;
        // int gsize = 1;//UP_DIV(hgr->hedgeNum, bsize);//
        TIMERSTART(6)
        mergeMoreNodesAcrossHyperedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId/*, 
                                                                aux->weight_vals, aux->nodeid_keys, aux->cand_counts, 0, hgr->maxDegree, hedgelist*/);
        // mergeMoreNodesAcrossHyperedges_mod<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
        //                                                         aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId, aux->isDuplica, aux->dupCnts);
        // mergeMoreNodesAcrossHyperedges<<<gsize, bsize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
        //                                                         aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId, 
        //                                                         aux->weight_vals, aux->nodeid_keys, aux->cand_counts, 6000, hgr->maxDegree+1, tNodesAttr);
        // mergeMoreNodesAcrossHyperedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
        //                                                         eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId);
        // parallelSelectMinWeightMinNodeId<<<UP_DIV(hgr->hedgeNum / 2, blocksize), blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
        //                                                                                     aux->eMatch, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId, aux->nInBag1, 
        //                                                                                     aux->represent, aux->best);
        TIMERSTOP(6)
        time += time6 / 1000.f;
        perfs[6].second += time6;
        kernel_pairs.push_back(std::make_pair("mergeMoreNodesAcrossHyperedges", time6));
        optcfgs.iterative_K6.push_back(time6);
        iter_time += time6;
    }
    // std::cout << "current # non-duplicates:" << aux->dupCnts[0] << "\n";
#if 1
    if (iter <= 1) {
        // int* h_candidates1 = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)h_candidates1, aux->canBeCandidates1, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // int* h_candidates = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)h_candidates, aux->canBeCandidates, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < hgr->nodeNum; ++i) {
        //     if (h_candidates[i] != h_candidates1[i]) {
        //         std::cout << __LINE__ << "inEqual@: " << i << "-th node, mine:" << h_candidates[i] << ", correct:" << h_candidates1[i] << "\n";
        //         break; 
        //     }
        // }
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (aux->weight_vals[i] != aux->best[i]) {
        //         std::cout << __LINE__ << "best:inEqual@: " << i << "-th node, mine:" << aux->weight_vals[i] << ", correct:" << aux->best[i] << "\n";
        //         break;
        //     }
        // }
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (aux->nodeid_keys[i] != aux->represent[i]) {
        //         std::cout << __LINE__ << "represent:inEqual@: " << i << "-th node, mine:" << aux->nodeid_keys[i] << ", correct:" << aux->represent[i] << "\n";
        //         break;
        //     }
        // }
        // int* h_counts = (int*)malloc(hgr->hedgeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)h_counts, aux->cand_counts, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     // if (aux->key_counts[i] != test_count[i]) {
        //     if (cand_counts[i] != h_counts[i]) {
        //         std::cout << __LINE__ << "count:inEqual@: " << i << "-th node, mine:" << cand_counts[i] << ", correct:" << h_counts[i] << "\n";
        //         break;
        //     }
        // }
        // int* h_parent = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)h_parent, parent, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        // int* h_cand = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)h_cand, aux->canBeCandidates1, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < hgr->nodeNum; ++i) {
        //     if (h_parent[i] != nodes[i + N_PARENT1(hgr->nodeNum)]) {
        //         std::cout << __LINE__ << "parent:inEqual@: " << i << "-th node, mine:" << h_parent[i] << ", correct:" << nodes[i + N_PARENT1(hgr->nodeNum)] << "\n";
        //         break;
        //     }
        // }
        // for (int i = 0; i < hgr->nodeNum; ++i) {
        //     if (test_candidates[i] != h_cand[i]) {
        //         std::cout << __LINE__ << "candidate:inEqual@: " << i << "-th node, mine:" << test_candidates[i] << ", correct:" << h_cand[i] << "\n";
        //         break;
        //     }
        // }
        // std::string file = "hedge_info_" + std::to_string(iter) + ".txt";
        // std::ofstream debug(file);
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     debug << i << ": " << tNodesAttr[i].eMatch << ", " << tNodesAttr[i].hedgesize << "\n";
        // }
    }
#endif

    CHECK_ERROR(cudaMemcpy((void *)&a, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&b, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    std::cout << "new hedgeNum: " << b << ", new nodeNum: " << a << std::endl;
    CHECK_ERROR(cudaFree(aux->cand_counts));

    // if (iter == 0) {
    //     std::ofstream debug("after_K6_adj_mapped_nodelist.txt");
    //     int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    //     int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* eMatch = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eMatch, aux->eMatch, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     debug << "(adjlist_id, parent_id, isDuplica, isSelfMergeNode)\n";
    //     for (int i = 0; i < hgr->hedgeNum; ++i) {
    //         debug << "eInBag:" << eInBag[i] << ", eMatch:" << eMatch[i] << ",  ";
    //         for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
    //             int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
    //             debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
    //         }
    //         debug << "\n";
    //     }
    // }

    TIMERSTART(7)
    countingHyperedgesRetainInCoarserLevel<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, aux->d_edgeCnt, aux->eInBag, aux->eMatch, aux->nMatch);
    TIMERSTOP(7)
    
    CHECK_ERROR(cudaMemcpy((void *)&a, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&b, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    std::cout << "new hedgeNum: " << b << ", new nodeNum: " << a << std::endl;

    // if (iter == 0) {
    //     std::ofstream debug("after_K7_adj_mapped_nodelist.txt");
    //     int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    //     int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* eMatch = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eMatch, aux->eMatch, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     debug << "(adjlist_id, parent_id, isDuplica, isSelfMergeNode)\n";
    //     for (int i = 0; i < hgr->hedgeNum; ++i) {
    //         debug << "eInBag:" << eInBag[i] << ", eMatch:" << eMatch[i] << ",  ";
    //         for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
    //             int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
    //             debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
    //         }
    //         debug << "\n";
    //     }
    // }
    
    gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(8)
    selfMergeSingletonNodes<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, aux->d_nodeCnt, aux->nInBag1, aux->nInBag, aux->tmpW, aux->nMatch, aux->nMatchHedgeId, aux->isSelfMergeNodes);
    TIMERSTOP(8)
    CHECK_ERROR(cudaMemcpy((void *)&a, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&b, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    std::cout << "new hedgeNum: " << b << ", new nodeNum: " << a << std::endl;

    // if (iter == 0) {
    //     std::ofstream debug("after_K8_adj_mapped_nodelist.txt");
    //     int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    //     int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
    //     int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     debug << "(adjlist_id, parent_id, isDuplica, isSelfMergeNode)\n";
    //     for (int i = 0; i < hgr->hedgeNum; ++i) {
    //         debug << "eInBag:" << eInBag[i] << ",   ";
    //         for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
    //             int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
    //             debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
    //         }
    //         debug << "\n";
    //     }
    // }

    // auto start_time1 = std::chrono::high_resolution_clock::now();
    // std::chrono::high_resolution_clock::time_point start_time1 = std::chrono::high_resolution_clock::now();
    TIMERSTART(others1)
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->nodeNum, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->hedgeNum, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)coarsenHgr->nodes, 0, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)coarsenHgr->hedges, 0, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int)));
    // thrust::fill(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum, 0);
    // thrust::fill(thrust::device, coarsenHgr->nodes + N_MATCHED(coarsenHgr), coarsenHgr->nodes + N_MATCHED(coarsenHgr) + coarsenHgr->nodeNum, 0);
    // CHECK_ERROR(cudaMalloc((void**)&aux->tmpW1, coarsenHgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->tmpW1, 0, coarsenHgr->nodeNum * sizeof(int)));
    TIMERSTOP(others1)
    // auto end_time1 = std::chrono::high_resolution_clock::now();
    // std::chrono::high_resolution_clock::time_point end_time1 = std::chrono::high_resolution_clock::now();
    // auto duration1 = std::chrono::duration_cast<std::chrono::milliseconds>(end_time1 - start_time1);
    // std::chrono::duration<double> time_span1 = std::chrono::duration_cast<std::chrono::duration<double>>(end_time1 - start_time1);

    TIMERSTART(9)
    // thrust::exclusive_scan(thrust::device, hgr->hedges + E_INBAG1(hgr->hedgeNum), hgr->hedges + E_INBAG1(hgr->hedgeNum) + hgr->hedgeNum, 
    //                                         hgr->hedges + E_NEXTID1(hgr->hedgeNum));
    // thrust::exclusive_scan(thrust::device, hgr->hedges + E_INBAG1(hgr->hedgeNum), hgr->hedges + E_INBAG1(hgr->hedgeNum) + hgr->hedgeNum, 
    //                                         eNextId);
    thrust::exclusive_scan(thrust::device, aux->eInBag, aux->eInBag + hgr->hedgeNum, aux->eNextId);
    // thrust::exclusive_scan(thrust::device, eInBag, eInBag + hgr->hedgeNum, eNextId);
    // thrust::exclusive_scan(thrust::device, hgr->nodes + N_INBAG1(hgr->nodeNum), hgr->nodes + N_INBAG1(hgr->nodeNum) + hgr->nodeNum,
    //                                         hgr->nodes + N_MAP_PARENT1(hgr->nodeNum), coarsenHgr->hedgeNum);
    // thrust::exclusive_scan(thrust::device, aux->nInBag, aux->nInBag + hgr->nodeNum,
    //                                         hgr->nodes + N_MAP_PARENT1(hgr->nodeNum), coarsenHgr->hedgeNum);
    thrust::exclusive_scan(thrust::device, aux->nInBag, aux->nInBag + hgr->nodeNum, aux->nNextId, coarsenHgr->hedgeNum);
    TIMERSTOP(9)
    TIMERSTART(10)
    setupNodeMapping<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, 
                            coarsenHgr->nodes, coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->nInBag, aux->nNextId, aux->tmpW, aux->tmpW1);
    // createNodeMapping<<<gridsize, blocksize>>>(hgr, hgr->nodeNum, coarsenHgr);
    TIMERSTOP(10)
    TIMERSTART(11)
    updateCoarsenNodeId<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, aux->nNextId);
    // updateSuperVertexId<<<gridsize, blocksize>>>(hgr, hgr->nodeNum);
    TIMERSTOP(11)

    CHECK_ERROR(cudaMalloc((void**)&aux->adj_node_parList, hgr->totalEdgeDegree * sizeof(int)));
    // CHECK_ERROR(cudaMalloc((void**)&aux->nodes_dup_degree, coarsenHgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nodes_dup_degree, 0, coarsenHgr->nodeNum * sizeof(int)));
    TIMERSTART(1_1)
    updateAdjParentList<<<num_blocks, blocksize>>>(hgr->nodes, hgr->adj_list, aux->adj_node_parList, aux->nNextId, 
                                                    hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eInBag, aux->pins_hedgeid_list/*, 
                                                    aux->nodes_dup_degree, coarsenHgr->hedgeNum, aux->isSelfMergeNodes, aux->isDuplica*/);
    TIMERSTOP(1_1)
    
    // if (optcfgs.perfOptForRefine) {
    //     CHECK_ERROR(cudaMalloc((void**)&hgr->adj_node_parList, hgr->totalEdgeDegree * sizeof(int)));
    //     CHECK_ERROR(cudaMemcpy((void *)hgr->adj_node_parList, aux->adj_node_parList, hgr->totalEdgeDegree * sizeof(int), cudaMemcpyHostToDevice));
    // }

    // time += (time0 + time1 + time2 + time3 + time4 + time5 + time6 + time7 + time8 + time9 + time10 + time11) / 1000.f;
    // time += (time7 + time8 + time9 + time10 + time11) / 1000.f;
    time += (time7 + time8 + time9 + time10 + time11 + time1_1) / 1000.f;
    kernel_pairs.push_back(std::make_pair("countingHyperedgesRetainInCoarserLevel", time7));
    kernel_pairs.push_back(std::make_pair("selfMergeSingletonNodes", time8));
    kernel_pairs.push_back(std::make_pair("thrust::exclusive_scan", time9));
    kernel_pairs.push_back(std::make_pair("setupNodeMapping", time10));
    kernel_pairs.push_back(std::make_pair("updateCoarsenNodeId", time11));
    iter_time += time7 + time8 + time9 + time10 + time11;
    std::cout << "avg_hedge_size:" << hgr->avgHedgeSize << "\n";
    // int* checkCount;
    // CHECK_ERROR(cudaMallocManaged(&checkCount, sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)checkCount, 0, sizeof(int)));
    if (!optcfgs.useNewKernel12) {
        unsigned long iter_k12_memops = 0;
        unsigned long iter_k12_cptops = 0;
        unsigned long thread_item_num = 1;
#if 0
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        if (!optcfgs.useNewParalOnBaseK12 == 2) {
            for (int i = 0; i < hgr->hedgeNum; ++i) {
                // debug << "eInBag:" << eInBag[i] << ",   ";
                iter_k12_memops += blocksize;
                if (eInBag[i]) {
                    iter_k12_memops += blocksize * 3;
                    for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
                        // int elemtid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j];
                        // debug << elemtid << "(" << nodes[elemtid - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)] << ", " << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ", " << isSelfMergeNodes[elemtid - hgr->hedgeNum] << ") ";
                        iter_k12_memops += 2 + j;
                        iter_k12_cptops += j;
                    }
                    // if (hedge[i + E_DEGREE1(hgr->hedgeNum)] > 6) {
                    //     real_work_items++;
                    // }
                }
            }
            thread_item_num = coarsenHgr->hedgeNum * blocksize;
        }
        if (optcfgs.useNewParalOnBaseK12 == 2) {
            for (int i = 0; i < hgr->hedgeNum; ++i) {
                iter_k12_memops += hedge[i + E_DEGREE1(hgr->hedgeNum)] * 2;
                if (eInBag[i]) {
                    iter_k12_memops += hedge[i + E_DEGREE1(hgr->hedgeNum)] * 3;
                    for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
                        iter_k12_memops += 1 + j;
                        iter_k12_cptops += j;
                    }
                }
            }
            thread_item_num = hgr->totalEdgeDegree;
        }
        // h_size* h_tuple = (h_size*)malloc(hgr->hedgeNum * sizeof(h_size));
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     h_tuple[i].eInBag = eInBag[i];
        //     h_tuple[i].size = hedge[i + E_DEGREE1(hgr->hedgeNum)];
        //     h_tuple[i].id = i;
        // }
        // std::sort(h_tuple, h_tuple + hgr->hedgeNum, sort_by_size());
        // std::ofstream out("sorted_hedge_size.txt");
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     out << h_tuple[i].eInBag << ": id " << h_tuple[i].id << ":   " << h_tuple[i].size << "\n";
        // }
        // std::cout << real_work_items << ", " << real_work_items * 1.0 / hgr->hedgeNum << "\n";
        // std::cout << "total_num_threads:" << hgr->hedgeNum * blocksize << "\n";
        // std::cout << "total_num_insts:" << iter_k12_memops + iter_k12_cptops << "\n";
#endif
        optcfgs.iterative_K12_num_opcost.push_back(iter_k12_memops + iter_k12_cptops);
        optcfgs.iter_perthread_K12_numopcost.push_back((iter_k12_memops + iter_k12_cptops) / thread_item_num);
    }

    if (!optcfgs.useNewKernel12) { // use old kernel!!!!
        // std::cout << "use old kernel markParentsForPinsLists<<<>>>()\n";
        dim3 block(16, 16, 1);
        int len_y = hgr->maxDegree < 500 ? hgr->maxDegree : hgr->maxDegree / 64;
        if (hgr->maxDegree < 500) {
            block.x = 32;
            block.y = 32;
        }
        dim3 grid(UP_DIV(hgr->hedgeNum, block.x), UP_DIV(len_y, block.y), 1);
        std::cout << "grid:" << grid.x << ", " << grid.y << "\n";
        std::cout << "block:" << block.x << ", " << block.y << "\n";
        std::cout << "For func1, gridsize:" << hgr->hedgeNum << ", " << blocksize << "\n";
        TIMERSTART(12)
        if (!optcfgs.useNewParalOnBaseK12) {
            // if (!optcfgs.useMemOpt) {
            //     markParentsForPinsLists<<<grid, block>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica,//hgr->par_list1, 
            //                                             hgr->hedgeNum, hgr->nodeNum, coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
            //                                             hgr->maxDegree, /*checkCount, cnt_per_edge_inbag*/aux->isSelfMergeNodes, aux->dupCnts);
            //     // markParentsForPinsLists_early_duplica<<<grid, block>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, coarsenHgr->hedges, coarsenHgr->hedgeNum, 
            //     //                                                 aux->d_totalPinSize, aux->eNextId, aux->eInBag, aux->isSelfMergeNodes, aux->dupCnts);
            // } else if (optcfgs.useMemOpt == 1) {
            //     markDuplicateParentInPins<<<grid, block>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
            //                                         coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
            //                                         aux->adj_node_parList);
            // }
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            markDuplicateWithBasePattern<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                                        coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag);
        } else if (optcfgs.useNewParalOnBaseK12 == 1) {
            // blocksize = 16;
            if (!optcfgs.useMemOpt) {
                if (!optcfgs.testK12NoLongestHedge) {
                    // std::cout << "ssssss\n";
                markParentsForPinsLists1<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                                                        coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, hgr->maxDegree);
                } else {
                markDuplicateCoarsePins_nocheck_longest_hedge_test<<<hgr->hedgeNum, blocksize>>>(
                                            hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, hgr->maxDegree,
                                            coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
                                            aux->adj_node_parList, hgr->maxDegree);
                }
            } else if (optcfgs.useMemOpt == 1) {
                if (!optcfgs.testK12IdealWork) {
                markDuplicateParentInPins1<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                                                coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
                                                aux->adj_node_parList, hgr->maxDegree);
                } else {
                    
                // markDuplicateParentInPins_idealcase_test<<<hgr->hedgeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                //                             coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
                //                             aux->adj_node_parList, hgr->maxDegree);
                }
                
            }
        } else if (optcfgs.useNewParalOnBaseK12 == 2) {
            if (optcfgs.useMemOpt == 1) {
            markDuplicateParentInPins1_parallelism<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                                                coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
                                                aux->adj_node_parList, aux->pins_hedgeid_list, hgr->totalEdgeDegree, hgr->maxDegree);
                // std::cout << "#############################\n";
            } else {
                parallel_markDuplicateParentInPins_base<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, 
                                                coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->d_totalPinSize, aux->eNextId, aux->eInBag, 
                                                aux->adj_node_parList, aux->pins_hedgeid_list, hgr->totalEdgeDegree, hgr->maxDegree);
                // std::cout << "++++++++++++++++++++++++++++\n";
            }
        }
        TIMERSTOP(12)
        time += time12 / 1000.f;
        perfs[12].second += time12;
        kernel_pairs.push_back(std::make_pair("markParentsForPinsLists", time12));
        optcfgs.iterative_K12.push_back(time12);
        iter_time += time12;
        GET_LAST_ERR();
    }
    // std::cout << "current # non-duplicates:" << aux->dupCnts[0] << "\n";
#if 0
    if (iter == 0) {
        int total = 0;
        std::string output = "";
        // std::ofstream debug("duplicate_list_mod.txt");
        std::ofstream debug("duplicate_list.txt");
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        int* eBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)eBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        int* adj_parlist = (int*)malloc(hgr->totalEdgeDegree * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)adj_parlist, aux->adj_node_parList, hgr->totalEdgeDegree * sizeof(int), cudaMemcpyDeviceToHost));
        int* coarse_hedges = (int*)malloc(E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)coarse_hedges, coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        int* eNext = (int*)malloc(hgr->hedgeNum * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)eNext, aux->eNextId, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            if (eBag[i]/* && hedge[i + E_DEGREE1(hgr->hedgeNum)] < 1000*/) {
                // for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
                //     debug << adj_parlist[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << "(" << isDuplica[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << ") ";
                // }
                // debug << "\n";
                debug << hedge[i + E_DEGREE1(hgr->hedgeNum)] << ", " << coarse_hedges[eNext[i] + E_DEGREE1(coarsenHgr->hedgeNum)] << "\n";
                total += coarse_hedges[eNext[i] + E_DEGREE1(coarsenHgr->hedgeNum)];
            }
        }
        std::cout << "total_adjacency_len:" << total << "\n";
    }
#endif

    // if (iter == 0 && optcfgs.testCPUImp) {
    //     std::vector<int> hedge(E_LENGTH1(hgr->hedgeNum), 0);
    //     std::vector<int> nodes(N_LENGTH1(hgr->nodeNum), 0);
    //     std::vector<unsigned> adj_list(hgr->totalEdgeDegree, 0);
    //     std::vector<int> eInBag(hgr->hedgeNum, 0);
    //     std::vector<int> eNext(hgr->hedgeNum, 0);
    //     CHECK_ERROR(cudaMemcpy((void *)&adj_list[0], hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)&hedge[0], hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)&nodes[0], hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)&eInBag[0], aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     CHECK_ERROR(cudaMemcpy((void *)&eNext[0], aux->eNextId, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     // int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
    //     // int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     // int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     // int* eNext = (int*)malloc(hgr->hedgeNum * sizeof(int));
    //     // unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));

    //     int cpu_thread_num = 24;
    //     int chunk_size = 32;//hgr->hedgeNum / cpu_thread_num;
    //     auto start = std::chrono::high_resolution_clock::now();
    //     int count = 0;
    //     std::vector<std::vector<unsigned>> edges_id(coarsenHgr->hedgeNum);
    //     // omp_set_num_threads(24);
    //     // #pragma omp parallel for schedule(dynamic, chunk_size)
    //     #pragma omp parallel for schedule(static, chunk_size)
    //     // #pragma omp parallel
    //     // {
    //         // int threads = omp_get_thread_num(); 
    //         // std::cout << "omp_get_num_threads:" << omp_get_num_threads() << "\n";
    //         for (int i = 0; i < hgr->hedgeNum; ++i) {
    //             if (eInBag[i]) {
    //                 unsigned h_id = eNext[i];
    //                 int id = h_id;
    //                 // count += hedge[i + E_DEGREE1(hgr->hedgeNum)];
    //                 int beg_off = hedge[i + E_OFFSET1(hgr->hedgeNum)];
    //                 int cur_deg = hedge[i + E_DEGREE1(hgr->hedgeNum)];
    //                 // for (int j = hedge[i + E_OFFSET1(hgr->hedgeNum)]; j < hedge[i+1 + E_OFFSET1(hgr->hedgeNum)]; j++) {
    //                 for (int j = beg_off; j < beg_off + cur_deg; j++) {
    //                     unsigned pid = nodes[adj_list[j] - hgr->hedgeNum + N_PARENT1(hgr->nodeNum)];
    //                     auto f = std::find(edges_id[id].begin(), edges_id[id].end(), pid);
    //                     if (f == edges_id[id].end()) {
    //                         edges_id[id].push_back(pid);
    //                     }
    //                 }
    //             }
    //         }
    //     // }
    //     std::chrono::duration<double> elapsed_seconds = std::chrono::high_resolution_clock::now() - start;
    //     std::cout << "Elapsed time: " << elapsed_seconds.count() << " seconds.\n";
    //     std::cout << "GPU kernel execution time: " << optcfgs.iterative_K12.back() / 1000.f << " s.\n";
    //     int total_elements = 0;
    //     // std::cout << edges_id.size() << "\n";
    //     // std::cout << "count:" << count << "\n";
    //     for (int i = 0; i < edges_id.size(); ++i) {
    //         total_elements += edges_id[i].size();
    //     }
    //     std::cout << "cpu result for new adjacent list length:" << total_elements << "\n";
    // }

    if (optcfgs.useNewKernel12) {
        unsigned long iter_k12_memops = 0;
        unsigned long iter_k12_cptops = 0;
        unsigned long real_work_items = 0;
#if 0
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
        // int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        // unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        // unsigned* isDuplica = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        // int* isSelfMergeNodes = (int*)malloc(hgr->nodeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)isSelfMergeNodes, aux->isSelfMergeNodes, hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)isDuplica, aux->isDuplica, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            // debug << "eInBag:" << eInBag[i] << ",   ";
            iter_k12_memops += blocksize;
            if (eInBag[i]) {
                iter_k12_memops += blocksize * 3;
                iter_k12_memops += 3 * hedge[i + E_DEGREE1(hgr->hedgeNum)] + 2 * hedge[i + E_DEGREE1(hgr->hedgeNum)];
                iter_k12_cptops += 9 * hedge[i + E_DEGREE1(hgr->hedgeNum)] + 3 * hedge[i + E_DEGREE1(hgr->hedgeNum)];
                // if (hedge[i + E_DEGREE1(hgr->hedgeNum)] > 6) {
                //     real_work_items++;
                // }
            }
        }
        // std::cout << real_work_items << ", " << real_work_items * 1.0 / hgr->hedgeNum << "\n";
#endif
        optcfgs.iterative_K12_num_opcost.push_back(iter_k12_memops + iter_k12_cptops);
        optcfgs.iter_perthread_K12_numopcost.push_back((iter_k12_memops + iter_k12_cptops) / (10000 * blocksize));
    }
    
    if (optcfgs.useNewKernel12) { // use new kernel!!!!
        // std::cout << "use new kernel markDuplicasInNextLevelAdjacentList_2<<<>>>()\n";
        int num_hedges = 10000;//500;//hgr->hedgeNum;//50000;//5000;//1;//
        int bit_length = UP_DIV(coarsenHgr->nodeNum, 32);//coarsenHgr->nodeNum;//
        int blocksize0 = 128;
        int gridsize0 = num_hedges;//hgr->hedgeNum;//
        std::cout << "bitset memory consumption: " << (bit_length * 1UL * num_hedges * sizeof(unsigned)) / (1024.f * 1024.f * 1024.f) << " GB.\n";
        TIMERSTART(_bs_alloc)
        // CHECK_ERROR(cudaMalloc((void**)&aux->bitset, bit_length * num_hedges * sizeof(unsigned))); // hnodeN bits
        // CHECK_ERROR(cudaMemset((void*)aux->bitset, 0, bit_length * num_hedges * sizeof(unsigned)));
        TIMERSTOP(_bs_alloc)
        // thrust::fill(thrust::device, aux->bitset, aux->bitset + bit_length * num_hedges, INT_MAX);

        // int gridsize0 = hgr->hedgeNum;
        // std::cout << "bitset memory consumption: " << (bit_length * 1UL * hgr->hedgeNum * sizeof(unsigned)) / (1024.f * 1024.f * 1024.f) << " GB.\n";
        // CHECK_ERROR(cudaMalloc((void**)&aux->bitset, bit_length * hgr->hedgeNum * sizeof(unsigned))); // hnodeN bits
        // CHECK_ERROR(cudaMemset((void*)aux->bitset, 0, bit_length * hgr->hedgeNum * sizeof(unsigned)));

        // TIMERSTART(1_2)
        if (!optcfgs.useMemOpt) {
            TIMERSTART(1_2)
            CHECK_ERROR(cudaMalloc((void**)&aux->bitset, bit_length * num_hedges * sizeof(unsigned))); // hnodeN bits
            CHECK_ERROR(cudaMemset((void*)aux->bitset, 0, bit_length * num_hedges * sizeof(unsigned)));
            markDuplicasInNextLevelAdjacentList_3<<<gridsize0, blocksize0>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, aux->eNextId, aux->eInBag,
                                                                coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->bitset, bit_length, num_hedges, aux->d_totalPinSize, hgr->maxDegree/*, checkCount*/);
            TIMERSTOP(1_2)
            optcfgs.iterative_K12.push_back(time1_2);
        } else if (optcfgs.useMemOpt == 1) {
            TIMERSTART(1_2)
            CHECK_ERROR(cudaMalloc((void**)&aux->bitset, bit_length * num_hedges * sizeof(unsigned))); // hnodeN bits
            CHECK_ERROR(cudaMemset((void*)aux->bitset, 0, bit_length * num_hedges * sizeof(unsigned)));
            markDuplicateParentInPins2<<<gridsize0, blocksize0>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, aux->eNextId, aux->eInBag,
                                                                coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->bitset, bit_length, num_hedges, aux->d_totalPinSize, aux->adj_node_parList, hgr->maxDegree);
            // markDuplicateParentInPins3<<<gridsize0, blocksize0>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, aux->eNextId, aux->eInBag, hgr->totalEdgeDegree,
            //                                                     coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->bitset, bit_length, num_hedges, aux->d_totalPinSize, aux->adj_node_parList, hgr->maxDegree);
            // markDuplicateParentInPins2_mod<<<gridsize0, blocksize0>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, aux->eNextId, aux->eInBag,
            //                                                     coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->bitset, bit_length, num_hedges, aux->d_totalPinSize, aux->adj_node_parList, aux->isSelfMergeNodes);
            TIMERSTOP(1_2)
            time += time1_2 / 1000.f;
            perfs[12].second += time1_2;
            kernel_pairs.push_back(std::make_pair("markDuplicasInNextLevelAdjacentList_3", time1_2));
            optcfgs.iterative_K12.push_back(time1_2);
            iter_time += time1_2;
        }
        // TIMERSTOP(1_2)
        CHECK_ERROR(cudaFree(aux->bitset));
        // time += time1_2 / 1000.f;
        // perfs[12].second += time1_2;
        // kernel_pairs.push_back(std::make_pair("markDuplicasInNextLevelAdjacentList_3", time1_2));
        // // memBytes += bit_length * 1UL * num_hedges * sizeof(unsigned);
        // optcfgs.iterative_K12.push_back(time1_2);
        // iter_time += time1_2;
        // other_time += time_bs_alloc / 1000.f;
    }


    // auto start_time2 = std::chrono::high_resolution_clock::now();
    TIMERSTART(others2)
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->totalEdgeDegree, aux->d_totalPinSize, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int)));
    // CHECK_ERROR(cudaMemset((void*)aux->pins_hedgeid_list, 0, hgr->totalEdgeDegree * sizeof(unsigned)));
    CHECK_ERROR(cudaMalloc((void**)&aux->next_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int)));
    CHECK_ERROR(cudaMemset((void*)aux->next_hedgeid_list, 0, coarsenHgr->totalEdgeDegree * sizeof(unsigned)));
    TIMERSTOP(others2)
    coarsenHgr->avgHedgeSize = (long double)coarsenHgr->totalEdgeDegree * 1.0 / coarsenHgr->hedgeNum;
    // auto end_time2 = std::chrono::high_resolution_clock::now();
    // auto duration2 = std::chrono::duration_cast<std::chrono::milliseconds>(end_time2 - start_time2);
    // std::chrono::duration<double> time_span2 = std::chrono::duration_cast<std::chrono::duration<double>>(end_time2 - start_time2);
    std::cout << "totalEdgeDegree:" << coarsenHgr->totalEdgeDegree << "\n";

    size_t totalMemory = 0;  
    size_t availableMemory = 0;  
    CHECK_ERROR(cudaMemGetInfo(&totalMemory, &availableMemory));
    std::cout << "Total memory: " << totalMemory / (1024 * 1024 * 1024) << " G" << std::endl;  
    std::cout << "Available memory: " << availableMemory / (1024 * 1024 * 1024) << " G" << std::endl; 

    TIMERSTART(13)
    thrust::exclusive_scan(thrust::device, coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum), 
                            coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum) + coarsenHgr->hedgeNum, 
                            coarsenHgr->hedges + E_OFFSET1(coarsenHgr->hedgeNum));
    TIMERSTOP(13)
    time += time13 / 1000.f;
    kernel_pairs.push_back(std::make_pair("thrust::exclusive_scan", time13));
    iter_time += time13;
    
    int* sdv;
    CHECK_ERROR(cudaMalloc((void**)&sdv, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)sdv, 0, sizeof(int)));
    if (!optcfgs.useNewKernel14) {
        blocksize = 128;
        // gridsize = UP_DIV(hgr->hedgeNum + coarsenHgr->nodeNum, blocksize);
        gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(14)
        // setupNextLevelAdjacentList<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
        //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list,
        //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum,
        //                                                     d_totalNodeDeg, d_maxPinSize, d_minPinSize, d_maxWeight, d_minWeight);
        // fillNextLevelAdjacentListWithoutDuplicates0<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
        //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->pins_hedgeid_list, aux->eNextId, aux->eInBag,
        //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum,
        //                                                     aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, aux->d_maxWeight, aux->d_minWeight);
        // fillNextLevelAdjacentListWithoutDuplicates0<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
        //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->pins_hedgeid_list, eNextId, eInBag,
        //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum,
        //                                                     aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, aux->d_maxWeight, aux->d_minWeight);
        // fillNextLevelAdjacentListWithoutDuplicates0<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
        //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->pins_hedgeid_list, aux->eNextId, aux->eInBag,
        //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum,
        //                                                     aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, aux->d_maxWeight, aux->d_minWeight);
        // if (iter > 0) { 
        fillNextLevelAdjacentListWithoutDuplicates0<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
                                                            coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->next_hedgeid_list, aux->eNextId, aux->eInBag,
                                                            coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum,
                                                            aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, aux->d_maxWeight, aux->d_minWeight,
                                                            sdv, coarsenHgr->avgHedgeSize);
        // } else {
        // fillNextLevelAdjacentList_new<<<UP_DIV(aux->total_thread_num, blocksize), blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
        //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->next_hedgeid_list, aux->eNextId, aux->eInBag,
        //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, hgr->hedgeNum + coarsenHgr->nodeNum, aux->d_totalNodeDeg, 
        //                                                     aux->d_maxPinSize, aux->d_minPinSize, aux->d_maxWeight, aux->d_minWeight, aux->hedge_off_per_thread, aux->total_thread_num);
        // }
        TIMERSTOP(14)
        time += time14 / 1000.f;
        perfs[14].second += time14;
        optcfgs.iterative_K14.push_back(time14);
        gridsize = UP_DIV(coarsenHgr->nodeNum, blocksize);
        TIMERSTART(15)
        setCoarsenNodesProperties<<<gridsize, blocksize>>>(coarsenHgr->nodes, coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_maxWeight, aux->d_minWeight, aux->tmpW1);
        TIMERSTOP(15)
        time += time15 / 1000.f;
        perfs[15].second += time15;
        kernel_pairs.push_back(std::make_pair("fillNextLevelAdjacentListWithoutDuplicates0", time14));
        kernel_pairs.push_back(std::make_pair("setCoarsenNodesProperties", time15));
        iter_time += time14 + time15;
    } else {
        int* d_newAdjListCounter;
        TIMERSTART(_k14cnter)
        // CHECK_ERROR(cudaMalloc((void**)&aux->d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
        // CHECK_ERROR(cudaMemset((void*)aux->d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMalloc((void**)&d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
        TIMERSTOP(_k14cnter)
        blocksize = 128;
        gridsize = hgr->hedgeNum;//num_hedges;//
        
        if (!optcfgs.useNewParalOnBaseK14 == 2) {
            TIMERSTART(14)
            CHECK_ERROR(cudaMalloc((void**)&d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
            // fillNextLevelAdjacentListWithoutDuplicates2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
            //                                                 coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->pins_hedgeid_list, aux->eNextId, aux->eInBag,
            //                                                 coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter);
            // fillNextLevelAdjacentListWithoutDuplicates2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
            //                                                 coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->pins_hedgeid_list, eNextId, eInBag,
            //                                                 coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter);
            // fillNextLevelAdjacentListWithoutDuplicates2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum,
            //                                                 coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->pins_hedgeid_list, eNextId, eInBag,
            //                                                 coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter);
            fillNextLevelAdjacentListWithoutDuplicates2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
                                                            coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->next_hedgeid_list, aux->eNextId, aux->eInBag,
                                                            coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter,
                                                            sdv, coarsenHgr->avgHedgeSize);
            TIMERSTOP(14)
            time += time14 / 1000.f;
            perfs[14].second += time14;
            kernel_pairs.push_back(std::make_pair("fillNextLevelAdjacentListWithoutDuplicates2", time14));
            iter_time += time14;
            optcfgs.iterative_K14.push_back(time14);
        } else {
            TIMERSTART(14)
            CHECK_ERROR(cudaMalloc((void**)&d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
            fillNextLevelAdjList_parallelbynode<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
                                                            coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->next_hedgeid_list, aux->eNextId, aux->eInBag,
                                                            coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter,
                                                            aux->adj_node_parList, aux->pins_hedgeid_list, hgr->totalEdgeDegree,
                                                            sdv, coarsenHgr->avgHedgeSize);
            TIMERSTOP(14)
            time += time14 / 1000.f;
            perfs[14].second += time14;
            kernel_pairs.push_back(std::make_pair("fillNextLevelAdjacentListWithoutDuplicates2", time14));
            iter_time += time14;
            optcfgs.iterative_K14.push_back(time14);
        }
        
        gridsize = UP_DIV(coarsenHgr->nodeNum, blocksize);
        TIMERSTART(15)
        setCoarsenNodesProperties<<<gridsize, blocksize>>>(coarsenHgr->nodes, coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_maxWeight, aux->d_minWeight, aux->tmpW1);
        TIMERSTOP(15)
        // CHECK_ERROR(cudaFree(aux->d_newAdjListCounter));
        CHECK_ERROR(cudaFree(d_newAdjListCounter));
        // time += (time1_4 + time15) / 1000.f;
        // perfs[14].second += time1_4;
        perfs[15].second += time15;
        // kernel_pairs.push_back(std::make_pair("fillNextLevelAdjacentListWithoutDuplicates2", time1_4));
        kernel_pairs.push_back(std::make_pair("setCoarsenNodesProperties", time15));
        // iter_time += time1_4 + time15;
        iter_time += time15;
        // other_time += time_k14cnter / 1000.f;
    }

#if 0
    if (iter < 3) {
        if (!optcfgs.useNewKernel5) {
        // if (!optcfgs.run_bug) {
            std::string file1 = "../debug/test_old_final_hedgelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug1(file1);
            int* hedge = (int*)malloc(E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)hedge, coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < E_LENGTH1(coarsenHgr->hedgeNum); ++i) {
                if (i / coarsenHgr->hedgeNum == 0) {
                    debug1 << "E_PRIORITY: ";
                }
                if (i / coarsenHgr->hedgeNum == 1) {
                    debug1 << "E_RAND: ";
                }
                if (i / coarsenHgr->hedgeNum == 2) {
                    debug1 << "E_IDNUM: ";
                }
                if (i / coarsenHgr->hedgeNum == 3) {
                    debug1 << "E_OFFSET: ";
                }
                if (i / coarsenHgr->hedgeNum == 4) {
                    debug1 << "E_DEGREE: ";
                }
                if (i / coarsenHgr->hedgeNum == 5) {
                    debug1 << "E_ELEMID: ";
                }
                if (i / coarsenHgr->hedgeNum == 6) {
                    debug1 << "E_MATCHED: ";
                }
                if (i / coarsenHgr->hedgeNum == 7) {
                    debug1 << "E_INBAG: ";
                }
                if (i / coarsenHgr->hedgeNum == 8) {
                    debug1 << "E_NEXTID: ";
                }
                debug1 << hedge[i] << "\n";
            }
            std::string file2 = "../debug/test_old_final_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            int* nodes = (int*)malloc(N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)nodes, coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < N_LENGTH1(coarsenHgr->nodeNum); ++i) {
                if (i / coarsenHgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / coarsenHgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / coarsenHgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / coarsenHgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / coarsenHgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / coarsenHgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / coarsenHgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / coarsenHgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / coarsenHgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / coarsenHgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / coarsenHgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / coarsenHgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / coarsenHgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / coarsenHgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / coarsenHgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / coarsenHgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / coarsenHgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / coarsenHgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / coarsenHgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / coarsenHgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
            std::string file = "../debug/test_old_final_adjlist_" + std::to_string(iter) + ".txt";
            std::ofstream debug(file);
            unsigned* adj_list = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
            CHECK_ERROR(cudaMemcpy((void *)adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
            unsigned* adj_list1 = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
            CHECK_ERROR(cudaMemcpy((void *)adj_list1, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
            for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
                std::sort(adj_list + hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i], adj_list + hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i] + hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i]);
                for (int j = 0; j < hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i]; ++j) {
                    debug << adj_list[hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i] + j] << " ";
                }
                debug << "\n";
            }
        } else {
            std::string file1 = "../debug/test_new_final_hedgelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug1(file1);
            int* hedge = (int*)malloc(E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)hedge, coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < E_LENGTH1(coarsenHgr->hedgeNum); ++i) {
                if (i / coarsenHgr->hedgeNum == 0) {
                    debug1 << "E_PRIORITY: ";
                }
                if (i / coarsenHgr->hedgeNum == 1) {
                    debug1 << "E_RAND: ";
                }
                if (i / coarsenHgr->hedgeNum == 2) {
                    debug1 << "E_IDNUM: ";
                }
                if (i / coarsenHgr->hedgeNum == 3) {
                    debug1 << "E_OFFSET: ";
                }
                if (i / coarsenHgr->hedgeNum == 4) {
                    debug1 << "E_DEGREE: ";
                }
                if (i / coarsenHgr->hedgeNum == 5) {
                    debug1 << "E_ELEMID: ";
                }
                if (i / coarsenHgr->hedgeNum == 6) {
                    debug1 << "E_MATCHED: ";
                }
                if (i / coarsenHgr->hedgeNum == 7) {
                    debug1 << "E_INBAG: ";
                }
                if (i / coarsenHgr->hedgeNum == 8) {
                    debug1 << "E_NEXTID: ";
                }
                debug1 << hedge[i] << "\n";
            }
            std::string file2 = "../debug/test_new_final_nodelist_" + std::to_string(iter) + ".txt";
            std::ofstream debug2(file2);
            int* nodes = (int*)malloc(N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int));
            CHECK_ERROR(cudaMemcpy((void *)nodes, coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            for (int i = 0; i < N_LENGTH1(coarsenHgr->nodeNum); ++i) {
                if (i / coarsenHgr->nodeNum == 0) {
                    debug2 << "N_PRIORITY: ";
                }
                if (i / coarsenHgr->nodeNum == 1) {
                    debug2 << "N_RAND: ";
                }
                if (i / coarsenHgr->nodeNum == 2) {
                    debug2 << "N_DEGREE: ";
                }
                if (i / coarsenHgr->nodeNum == 3) {
                    debug2 << "N_OFFSET: ";
                }
                if (i / coarsenHgr->nodeNum == 4) {
                    debug2 << "N_HEDGEID: ";
                }
                if (i / coarsenHgr->nodeNum == 5) {
                    debug2 << "N_ELEMID: ";
                }
                if (i / coarsenHgr->nodeNum == 6) {
                    debug2 << "N_MATCHED: ";
                }
                if (i / coarsenHgr->nodeNum == 7) {
                    debug2 << "N_FOR_UPDATE: ";
                }
                if (i / coarsenHgr->nodeNum == 8) {
                    debug2 << "N_MORE_UPDATE: ";
                }
                if (i / coarsenHgr->nodeNum == 9) {
                    debug2 << "N_WEIGHT: ";
                }
                if (i / coarsenHgr->nodeNum == 10) {
                    debug2 << "N_TMPW: ";
                }
                if (i / coarsenHgr->nodeNum == 11) {
                    debug2 << "N_PARENT: ";
                }
                if (i / coarsenHgr->nodeNum == 12) {
                    debug2 << "N_MAP_PARENT: ";
                }
                if (i / coarsenHgr->nodeNum == 13) {
                    debug2 << "N_INBAG: ";
                }
                if (i / coarsenHgr->nodeNum == 14) {
                    debug2 << "N_FS: ";
                }
                if (i / coarsenHgr->nodeNum == 15) {
                    debug2 << "N_TE: ";
                }
                if (i / coarsenHgr->nodeNum == 16) {
                    debug2 << "N_COUNTER: ";
                }
                if (i / coarsenHgr->nodeNum == 17) {
                    debug2 << "N_TMPBAG: ";
                }
                if (i / coarsenHgr->nodeNum == 18) {
                    debug2 << "N_PARTITION: ";
                }
                if (i / coarsenHgr->nodeNum == 19) {
                    debug2 << "N_NETCOUNT: ";
                }
                debug2 << nodes[i] << "\n";
            }
            std::string file = "../debug/test_new_final_adjlist_" + std::to_string(iter) + ".txt";
            std::ofstream debug(file);
            unsigned* adj_list = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
            CHECK_ERROR(cudaMemcpy((void *)adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
            for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
                std::sort(adj_list + hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i], adj_list + hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i] + hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i]);
                for (int j = 0; j < hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i]; ++j) {
                    debug << adj_list[hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i] + j] << " ";
                }
                debug << "\n";
            }
            file = "../debug/test_new_pins_hedgeid_list_" + std::to_string(iter) + ".txt";
            std::ofstream debug0(file);
            unsigned* pins_hedgeid_list = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
            CHECK_ERROR(cudaMemcpy((void *)pins_hedgeid_list, coarsenHgr->pins_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
            for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
                for (int j = 0; j < hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i]; ++j) {
                    debug0 << pins_hedgeid_list[hedge[E_OFFSET1(coarsenHgr->hedgeNum) + i] + j] << " ";
                }
                debug0 << "\n";
            }
        }
    }
#endif

    if ((optcfgs.useNewKernel12 && optcfgs.sortHedgeLists) || (optcfgs.useNewKernel14 && optcfgs.sortHedgeLists)) {
        TIMERSTART(_sort)
        // int* offset = (int*)malloc(coarsenHgr->hedgeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)offset, coarsenHgr->hedges + E_OFFSET1(coarsenHgr->hedgeNum), coarsenHgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // int* degree = (int*)malloc(coarsenHgr->hedgeNum * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)degree, coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum), coarsenHgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // unsigned* adj_list = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
        // CHECK_ERROR(cudaMemcpy((void *)adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        //     std::sort(adj_list + offset[i], adj_list + offset[i] + degree[i]);
        // }
        // // for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        // //     // std::cout << i << ": degree:" << hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i] << "\n";
        // //     // thrust::sort(thrust::device, coarsenHgr->adj_list + offset[i], coarsenHgr->adj_list + offset[i] + degree[i]);
        // //     // cudaStream_t stream;
        // //     // cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
        // //     // thrust::sort(thrust::cuda::par.on(stream), coarsenHgr->adj_list + offset[i], coarsenHgr->adj_list + offset[i] + degree[i]);
        // //     // CHECK_ERROR(cudaStreamSynchronize(stream));
        // //     // cudaStreamDestroy(stream);
        // //     // thrust::sort(thrust::host, adj_list + offset[i], adj_list + offset[i] + degree[i]);
        // // }
        // CHECK_ERROR(cudaMemcpy((void *)coarsenHgr->adj_list, adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));

        void* d_temp_storage = NULL;
        size_t temp_storage_bytes = 0;
        int* d_off;
        CHECK_ERROR(cudaMalloc((void**)&d_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMemcpy((void *)d_off, coarsenHgr->hedges + E_OFFSET1(coarsenHgr->hedgeNum), coarsenHgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));
        CHECK_ERROR(cudaMemcpy((void *)&d_off[coarsenHgr->hedgeNum], &coarsenHgr->totalEdgeDegree, sizeof(int), cudaMemcpyHostToDevice));
        cub::DeviceSegmentedSort::SortKeys(d_temp_storage, temp_storage_bytes, coarsenHgr->adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree, coarsenHgr->hedgeNum, d_off, d_off+1);
        std::cout << "temp_storage_in_GB: " << temp_storage_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
        CHECK_ERROR(cudaMalloc((void**)&d_temp_storage, temp_storage_bytes));
        cudaStream_t stream;
        cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
        cub::DeviceSegmentedSort::SortKeys(d_temp_storage, temp_storage_bytes, coarsenHgr->adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree, coarsenHgr->hedgeNum, d_off, d_off+1, stream);
        CHECK_ERROR(cudaStreamSynchronize(stream));
        CHECK_ERROR(cudaStreamDestroy(stream));
        CHECK_ERROR(cudaFree(d_temp_storage));
        CHECK_ERROR(cudaFree(d_off));
        // CHECK_ERROR(cudaMalloc((void**)&aux->d_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        // CHECK_ERROR(cudaMemcpy((void *)aux->d_off, coarsenHgr->hedges + E_OFFSET1(coarsenHgr->hedgeNum), coarsenHgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));
        // CHECK_ERROR(cudaMemcpy((void *)&aux->d_off[coarsenHgr->hedgeNum], &coarsenHgr->totalEdgeDegree, sizeof(int), cudaMemcpyHostToDevice));
        // cub::DeviceSegmentedSort::SortKeys(aux->d_temp_storage, temp_storage_bytes, coarsenHgr->adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree, coarsenHgr->hedgeNum, aux->d_off, aux->d_off+1);
        // std::cout << "temp_storage_in_GB: " << temp_storage_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
        // CHECK_ERROR(cudaMalloc((void**)&aux->d_temp_storage, temp_storage_bytes));
        // cudaStream_t stream;
        // cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
        // cub::DeviceSegmentedSort::SortKeys(aux->d_temp_storage, temp_storage_bytes, coarsenHgr->adj_list, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree, coarsenHgr->hedgeNum, aux->d_off, aux->d_off+1, stream);
        // CHECK_ERROR(cudaStreamSynchronize(stream));
        // CHECK_ERROR(cudaStreamDestroy(stream));
        // CHECK_ERROR(cudaFree(aux->d_temp_storage));
        // CHECK_ERROR(cudaFree(aux->d_off));
        TIMERSTOP(_sort)
        time += time_sort / 1000.f;
        perfs[16].second += time_sort;
        kernel_pairs.push_back(std::make_pair("cub::DeviceSegmentedSort", time_sort));
        iter_time += time_sort;
    }

#if 0
    if (optcfgs.testSpGEMM) {
        int* node_map_csr_off;
        int* node_map_csr_col;
        float* node_map_csr_val;
        int* edge_map_csr_off;
        int* edge_map_csr_col;
        float* edge_map_csr_val;
        int* curr_adj_csr_off;
        int* curr_adj_csr_col;
        float* curr_adj_csr_val;
        int* next_adj_csr_off;
        int* next_adj_csr_col;
        float* next_adj_csr_val;
        float               alpha       = 1.0f;
        float               beta        = 0.0f;
        cusparseOperation_t opA         = CUSPARSE_OPERATION_NON_TRANSPOSE;
        cusparseOperation_t opB         = CUSPARSE_OPERATION_NON_TRANSPOSE;
        cudaDataType        computeType = CUDA_R_32F;

        int nnzA = coarsenHgr->hedgeNum;
        int nnzC = hgr->nodeNum;
        int nnzB = hgr->totalEdgeDegree;
        int nnzD = coarsenHgr->totalEdgeDegree;
        // CHECK_ERROR(cudaMalloc((void**)&edge_map_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&edge_map_csr_col, nnzA * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&edge_map_csr_val, nnzA * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&edge_map_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&edge_map_csr_col, nnzA * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&edge_map_csr_val, nnzA * sizeof(float)));
        CHECK_ERROR(cudaMemset((void*)edge_map_csr_off, 0, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)edge_map_csr_col, 0, nnzA * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)edge_map_csr_val, 0, nnzA * sizeof(float)));
        
        // CHECK_ERROR(cudaMalloc((void**)&node_map_csr_off, (hgr->nodeNum + 1) * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&node_map_csr_col, nnzC * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&node_map_csr_val, nnzC * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&node_map_csr_off, (hgr->nodeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&node_map_csr_col, nnzC * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&node_map_csr_val, nnzC * sizeof(float)));
        CHECK_ERROR(cudaMemset((void*)node_map_csr_off, 0, (hgr->nodeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)node_map_csr_col, 0, nnzC * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)node_map_csr_val, 0, nnzC * sizeof(float)));

        // CHECK_ERROR(cudaMalloc((void**)&curr_adj_csr_off, (hgr->hedgeNum + 1) * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&curr_adj_csr_col, nnzB * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&curr_adj_csr_val, nnzB * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&curr_adj_csr_off, (hgr->hedgeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&curr_adj_csr_col, nnzB * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&curr_adj_csr_val, nnzB * sizeof(float)));
        CHECK_ERROR(cudaMemcpy((void *)curr_adj_csr_off, hgr->hedges + E_OFFSET1(hgr->hedgeNum), hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));
        CHECK_ERROR(cudaMemcpy((void *)&curr_adj_csr_off[hgr->hedgeNum], &hgr->totalEdgeDegree, sizeof(int), cudaMemcpyHostToDevice));

        // CHECK_ERROR(cudaMalloc((void**)&next_adj_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&next_adj_csr_col, nnzD * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&next_adj_csr_val, nnzD * sizeof(int)));
        
        TIMERSTART(_spgemm1)
        transform_edge_mapping_list_to_csr_format<<<UP_DIV(hgr->hedgeNum, blocksize), blocksize>>>(hgr->hedgeNum, coarsenHgr->hedgeNum, aux->eInBag, aux->eNextId, edge_map_csr_off, edge_map_csr_col, edge_map_csr_val);
        transform_node_mapping_list_to_csr_format<<<UP_DIV(hgr->nodeNum, blocksize), blocksize>>>(coarsenHgr->hedgeNum, hgr->nodes, hgr->nodeNum, node_map_csr_off, node_map_csr_col, node_map_csr_val);
        transform_adjlist_to_csr_format<<<num_blocks, blocksize>>>(hgr->adj_list, hgr->hedgeNum, hgr->totalEdgeDegree, curr_adj_csr_col, curr_adj_csr_val);
        TIMERSTOP(_spgemm1)
        
        // std::ofstream spmm("test_spgemm_col.txt");
        std::ofstream spmm1("test_spgemm_ref.txt");
        // std::ofstream spmm2("test_spgemm_mid.txt");
        // std::ofstream spmm3("test_spgemm_off.txt");
        // std::ofstream spmm4("test_spgemm_val.txt");
        std::ofstream spmm5("final_spgemm_col.txt");
        // std::ofstream bag("hedge_bag.txt");
        // std::ofstream next("hedge_col.txt");
        // for (int i = 0; i < coarsenHgr->hedgeNum + 1; ++i) {
        //     spmm << edge_map_csr_off[i] << "\n";
        // }
        // for (int i = 0; i < hgr->nodeNum + 1; ++i) {
        //     spmm << node_map_csr_off[i] << "\n";
        // }
        // for (int i = 0; i < hgr->hedgeNum + 1; ++i) {
        //     spmm << curr_adj_csr_off[i] << "\n";
        // }
        // for (int i = 0; i < nnzA; ++i) {
        //     spmm2 << edge_map_csr_col[i] << "\n";
        // }
        // for (int i = 0; i < nnzA; ++i) {
        //     spmm2 << edge_map_csr_val[i] << "\n";
        // }
        // for (int i = 0; i < nnzC; ++i) {
        //     spmm2 << node_map_csr_col[i] << "\n";
        // }
        // for (int i = 0; i < nnzC; ++i) {
        //     spmm2 << node_map_csr_val[i] << "\n";
        // }
        // int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        // int* eInBag = (int*)malloc(hgr->hedgeNum * sizeof(int));
        // int* eNext = (int*)malloc(hgr->hedgeNum * sizeof(int));
        // int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        // unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        // CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)eInBag, aux->eInBag, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // CHECK_ERROR(cudaMemcpy((void *)eNext, aux->eNextId, hgr->hedgeNum * sizeof(int), cudaMemcpyDeviceToHost));
        // int total = 0;
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (eInBag[i]) {
        //         total += hedge[i + E_DEGREE1(hgr->hedgeNum)];
        //         // for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
        //         //     spmm1 << adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] - hgr->hedgeNum << "\n";
        //         // }
        //         // spmm1 << "\n";
        //         // next << i << "\n";
        //     }
        //     // bag << eInBag[i] << "\n";
        // }
        // std::cout << "total:" << total << "\n";
        // for (int i = 0; i < hgr->nodeNum; ++i) {
        //     spmm1 << nodes[i + N_PARENT1(hgr->nodeNum)] - coarsenHgr->hedgeNum << "\n";
        // }
        // int* hedge1 = (int*)malloc(E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int));
        // CHECK_ERROR(cudaMemcpy((void *)hedge1, coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        //     spmm1 << hedge1[i + E_OFFSET1(coarsenHgr->hedgeNum)] << "\n";
        // }
        // spmm1 << coarsenHgr->totalEdgeDegree << "\n";
        // unsigned* adj_list1 = (unsigned*)malloc(coarsenHgr->totalEdgeDegree * sizeof(unsigned));
        // CHECK_ERROR(cudaMemcpy((void *)adj_list1, coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < coarsenHgr->totalEdgeDegree; ++i) {
        //     spmm1 << adj_list1[i] - coarsenHgr->hedgeNum << "\n";
        // }
#if 0
        // cpu impl
        // int* matEdge = (int*)malloc(coarsenHgr->hedgeNum * hgr->hedgeNum * sizeof(int));
        // memset(matEdge, 0, coarsenHgr->hedgeNum * hgr->hedgeNum * sizeof(int));
        int* matEdge;
        CHECK_ERROR(cudaMallocManaged(&matEdge, coarsenHgr->hedgeNum * hgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)matEdge, 0, coarsenHgr->hedgeNum * hgr->hedgeNum * sizeof(int)));
        for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
            for (int j = 0; j < hgr->hedgeNum; ++j) {
                if (eInBag[j] && eNext[j] == i) {
                    matEdge[i * hgr->hedgeNum + j] = 1;
                }
            }
        }
        std::cout << "finish init matEdge\n";
        // int* matNode = (int*)malloc(hgr->nodeNum * coarsenHgr->nodeNum * sizeof(int));
        // memset(matNode, 0, hgr->nodeNum * coarsenHgr->nodeNum * sizeof(int));
        int* matNode;
        CHECK_ERROR(cudaMallocManaged(&matNode, hgr->nodeNum * coarsenHgr->nodeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)matNode, 0, hgr->nodeNum * coarsenHgr->nodeNum * sizeof(int)));
        for (int i = 0; i < hgr->nodeNum; ++i) {
            for (int j = 0; j < coarsenHgr->nodeNum; ++j) {
                if (nodes[i + N_PARENT1(hgr->nodeNum)] - coarsenHgr->hedgeNum == j) {
                    matNode[i * coarsenHgr->nodeNum + j] = 1;
                }
            }
        }
        std::cout << "finish init matNode\n";
        // int* matAdj = (int*)malloc(hgr->hedgeNum * hgr->nodeNum * sizeof(int));
        // memset(matAdj, 0, hgr->hedgeNum * hgr->nodeNum * sizeof(int));
        int* matAdj;
        CHECK_ERROR(cudaMallocManaged(&matAdj, hgr->hedgeNum * hgr->nodeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)matAdj, 0, hgr->hedgeNum * hgr->nodeNum * sizeof(int)));
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
                int nodeid = adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] - hgr->hedgeNum;
                matAdj[i * hgr->nodeNum + nodeid] = 1;
            }
        }
        std::cout << "finish init matAdj\n";
        // int* matDup = (int*)malloc(coarsenHgr->hedgeNum * hgr->nodeNum * sizeof(int));
        // memset(matDup, 0, coarsenHgr->hedgeNum * hgr->nodeNum * sizeof(int));
        int* matDup;
        CHECK_ERROR(cudaMallocManaged(&matDup, coarsenHgr->hedgeNum * hgr->nodeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)matDup, 0, coarsenHgr->hedgeNum * hgr->nodeNum * sizeof(int)));
        // int* matNew = (int*)malloc(coarsenHgr->hedgeNum * coarsenHgr->nodeNum * sizeof(int));
        // memset(matNew, 0, coarsenHgr->hedgeNum * coarsenHgr->nodeNum * sizeof(int));
        int* matNew;
        CHECK_ERROR(cudaMallocManaged(&matNew, coarsenHgr->hedgeNum * coarsenHgr->nodeNum * sizeof(int)));
        CHECK_ERROR(cudaMemset((void*)matNew, 0, coarsenHgr->hedgeNum * coarsenHgr->nodeNum * sizeof(int)));

        dim3 block(16, 16, 1);
        dim3 grid(UP_DIV(hgr->nodeNum, block.x), UP_DIV(coarsenHgr->hedgeNum, block.y), 1);
        dim3 grid1(UP_DIV(coarsenHgr->nodeNum, block.x), UP_DIV(coarsenHgr->hedgeNum, block.y), 1);
        TIMERSTART(_self)
        computeAxB<<<grid, block>>>(matEdge, matAdj, matDup, hgr->hedgeNum, coarsenHgr->hedgeNum, hgr->nodeNum);
        computeAxB<<<grid1, block>>>(matDup, matNode, matNew, hgr->nodeNum, coarsenHgr->hedgeNum, coarsenHgr->nodeNum);
        TIMERSTOP(_self)
        std::cout << "finish compute matNew\n";
        for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
            for (int j = 0; j < coarsenHgr->nodeNum; ++j) {
                if (matNew[i * coarsenHgr->nodeNum + j]) {
                    spmm5 << j << "\n";
                }
            }
        }
#endif
        cusparseHandle_t     handle = NULL, handle1 = NULL;
        cusparseSpMatDescr_t matA, matB, matTmp, matC, matD;
        void*  dBuffer1    = NULL, *dBuffer2   = NULL;
        size_t bufferSize1 = 0,    bufferSize2 = 0;
        void*  dBuffer3    = NULL, *dBuffer4   = NULL;
        size_t bufferSize3 = 0,    bufferSize4 = 0;

        // int64_t tmp_nnz, tmp_row_num = coarsenHgr->hedgeNum, tmp_col_num = hgr->nodeNum;
        // int64_t tmp_nnz1, tmp_row_num1 = coarsenHgr->hedgeNum, tmp_col_num1 = coarsenHgr->nodeNum;
        int64_t tmp_nnz, tmp_row_num, tmp_col_num;
        int64_t tmp_nnz1, tmp_row_num1, tmp_col_num1;
        cusparseSpGEMMDescr_t spgemmDesc, spgemmDesc1;
        CHECK_CUSPARSE(cusparseCreate(&handle));
        CHECK_CUSPARSE(cusparseCreate(&handle1));
        CHECK_CUSPARSE(cusparseCreateCsr(&matA, coarsenHgr->hedgeNum, hgr->hedgeNum, nnzA, edge_map_csr_off, edge_map_csr_col, edge_map_csr_val, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_BASE_ZERO, CUDA_R_32F));
        CHECK_CUSPARSE(cusparseCreateCsr(&matC, hgr->nodeNum, coarsenHgr->nodeNum, nnzC, node_map_csr_off, node_map_csr_col, node_map_csr_val, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_BASE_ZERO, CUDA_R_32F));
        CHECK_CUSPARSE(cusparseCreateCsr(&matB, hgr->hedgeNum, hgr->nodeNum, hgr->totalEdgeDegree, curr_adj_csr_off, curr_adj_csr_col, curr_adj_csr_val, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_BASE_ZERO, CUDA_R_32F));
        CHECK_CUSPARSE(cusparseCreateCsr(&matTmp, coarsenHgr->hedgeNum, hgr->nodeNum, 0, NULL, NULL, NULL, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_BASE_ZERO, CUDA_R_32F));
        CHECK_CUSPARSE(cusparseCreateCsr(&matD, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, 0, NULL, NULL, NULL, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_32I, CUSPARSE_INDEX_BASE_ZERO, CUDA_R_32F));
        CHECK_CUSPARSE(cusparseSpGEMM_createDescr(&spgemmDesc));
        CHECK_CUSPARSE(cusparseSpGEMM_createDescr(&spgemmDesc1));

        TIMERSTART(_spgemm2)
        CHECK_CUSPARSE(cusparseSpGEMM_workEstimation(handle, opA, opB, &alpha, matA, matB, &beta, matTmp, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize1, NULL));
        CHECK_ERROR(cudaMalloc((void**) &dBuffer1, bufferSize1));
        CHECK_CUSPARSE(cusparseSpGEMM_workEstimation(handle, opA, opB, &alpha, matA, matB, &beta, matTmp, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize1, dBuffer1));

        CHECK_CUSPARSE(cusparseSpGEMM_compute(handle, opA, opB, &alpha, matA, matB, &beta, matTmp, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize2, NULL));
        CHECK_ERROR(cudaMalloc((void**) &dBuffer2, bufferSize2));
        // compute the intermediate product of A * B
        CHECK_CUSPARSE(cusparseSpGEMM_compute(handle, opA, opB, &alpha, matA, matB, &beta, matTmp, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize2, dBuffer2));
        
        int* tmp_csr_off, *tmp_csr_col;
        CHECK_ERROR(cudaMallocManaged(&tmp_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        CHECK_CUSPARSE(cusparseSpMatGetSize(matTmp, &tmp_row_num, &tmp_col_num, &tmp_nnz));
        float *tmp_csr_val;
        CHECK_ERROR(cudaMallocManaged(&tmp_csr_col, tmp_nnz * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&tmp_csr_val, tmp_nnz * sizeof(float)));
        std::cout << "tmp_nnz:" << tmp_nnz << "\n";
        std::cout << "tmp_row_num:" << tmp_row_num << ", tmp_col_num:" << tmp_col_num << "\n";

        CHECK_CUSPARSE(cusparseCsrSetPointers(matTmp, tmp_csr_off, tmp_csr_col, tmp_csr_val));
        CHECK_CUSPARSE(cusparseSpGEMM_copy(handle, opA, opB, &alpha, matA, matB, &beta, matTmp, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc));
        TIMERSTOP(_spgemm2)

        TIMERSTART(_spgemm3)
        CHECK_CUSPARSE(cusparseSpGEMM_workEstimation(handle, opA, opB, &alpha, matTmp, matC, &beta, matD, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize3, NULL));
        CHECK_ERROR(cudaMalloc((void**) &dBuffer3, bufferSize3));
        CHECK_CUSPARSE(cusparseSpGEMM_workEstimation(handle, opA, opB, &alpha, matTmp, matC, &beta, matD, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize3, dBuffer3));

        CHECK_CUSPARSE(cusparseSpGEMM_compute(handle, opA, opB, &alpha, matTmp, matC, &beta, matD, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize4, NULL));
        CHECK_ERROR(cudaMalloc((void**) &dBuffer4, bufferSize4));
        // compute the intermediate product of A * B
        CHECK_CUSPARSE(cusparseSpGEMM_compute(handle, opA, opB, &alpha, matTmp, matC, &beta, matD, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc, &bufferSize4, dBuffer4));

        CHECK_ERROR(cudaMallocManaged(&next_adj_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int)));
        CHECK_CUSPARSE(cusparseSpMatGetSize(matD, &tmp_row_num1, &tmp_col_num1, &tmp_nnz1));
        CHECK_ERROR(cudaMallocManaged(&next_adj_csr_col, tmp_nnz1 * sizeof(int)));
        CHECK_ERROR(cudaMallocManaged(&next_adj_csr_val, tmp_nnz1 * sizeof(float)));
        std::cout << "tmp_nnz1:" << tmp_nnz1 << "\n";
        std::cout << "tmp_row_num1:" << tmp_row_num1 << ", tmp_col_num1:" << tmp_col_num1 << "\n";

        CHECK_CUSPARSE(cusparseCsrSetPointers(matD, next_adj_csr_off, next_adj_csr_col, next_adj_csr_val));
        CHECK_CUSPARSE(cusparseSpGEMM_copy(handle, opA, opB, &alpha, matTmp, matC, &beta, matD, computeType, CUSPARSE_SPGEMM_DEFAULT, spgemmDesc));
        TIMERSTOP(_spgemm3)
        // for (int i = 0; i < tmp_nnz1; ++i) {
        //     spmm5 << next_adj_csr_col[i] << "\n";
        //     // spmm4 << next_adj_csr_val[i] << "\n";
        // }
        // for (int i = 0; i < coarsenHgr->hedgeNum + 1; ++i) {
        //     spmm3 << next_adj_csr_off[i] << "\n";
        // }
        // int* matTmpCol = (int*)malloc(tmp_nnz * sizeof(int));
        // CHECK_ERROR(cudaMemcpy(matTmpCol, tmp_csr_col, tmp_nnz * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < tmp_nnz; ++i) {
        //     spmm << matTmpCol[i] << "\n";
        // }
        // int* matTmpOff = (int*)malloc((coarsenHgr->hedgeNum + 1) * sizeof(int));
        // CHECK_ERROR(cudaMemcpy(matTmpOff, tmp_csr_off, (coarsenHgr->hedgeNum + 1) * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < (coarsenHgr->hedgeNum + 1); ++i) {
        //     spmm3 << matTmpOff[i] << "\n";
        // }
        // for (int i = 0; i < tmp_nnz; ++i) {
        //     // spmm4 << tmp_csr_val[i] << "\n";
        //     spmm << tmp_csr_col[i] << "\n";
        // }
        // int* matBCol = (int*)malloc(nnzB * sizeof(int));
        // CHECK_ERROR(cudaMemcpy(matBCol, curr_adj_csr_col, nnzB * sizeof(int), cudaMemcpyDeviceToHost));
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (eInBag[i]) {
        //         for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
        //             spmm2 << matBCol[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] << "\n";
        //         }
        //     }
        // }

        CHECK_CUSPARSE( cusparseSpGEMM_destroyDescr(spgemmDesc) );
        CHECK_CUSPARSE( cusparseSpGEMM_destroyDescr(spgemmDesc1) );
        CHECK_CUSPARSE( cusparseDestroySpMat(matA) );
        CHECK_CUSPARSE( cusparseDestroySpMat(matB) );
        CHECK_CUSPARSE( cusparseDestroySpMat(matC) );
        CHECK_CUSPARSE( cusparseDestroySpMat(matTmp) );
        CHECK_CUSPARSE( cusparseDestroySpMat(matD) );
        CHECK_CUSPARSE( cusparseDestroy(handle) );
        CHECK_CUSPARSE( cusparseDestroy(handle1) );

        CHECK_ERROR( cudaFree(dBuffer1) );
        CHECK_ERROR( cudaFree(dBuffer2) );
        CHECK_ERROR( cudaFree(dBuffer3) );
        CHECK_ERROR( cudaFree(dBuffer4) );

        CHECK_ERROR( cudaFree(node_map_csr_off) );
        CHECK_ERROR( cudaFree(node_map_csr_col) );
        CHECK_ERROR( cudaFree(node_map_csr_val) );

        CHECK_ERROR( cudaFree(edge_map_csr_off) );
        CHECK_ERROR( cudaFree(edge_map_csr_col) );
        CHECK_ERROR( cudaFree(edge_map_csr_val) );
        
        CHECK_ERROR( cudaFree(curr_adj_csr_off) );
        CHECK_ERROR( cudaFree(curr_adj_csr_col) );
        CHECK_ERROR( cudaFree(curr_adj_csr_val) );
        
        CHECK_ERROR( cudaFree(next_adj_csr_off) );
        CHECK_ERROR( cudaFree(next_adj_csr_col) );
        CHECK_ERROR( cudaFree(next_adj_csr_val) );
    }
#endif

    CHECK_ERROR(cudaFree(aux->pins_hedgeid_list));
    // CHECK_ERROR(cudaMemset((void*)aux->pins_hedgeid_list, 0, hgr->totalEdgeDegree * sizeof(unsigned)));
    CHECK_ERROR(cudaMalloc((void**)&aux->pins_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int)));
    CHECK_ERROR(cudaMemcpy((void *)aux->pins_hedgeid_list, aux->next_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int), cudaMemcpyDeviceToDevice));
    if (optcfgs.perfOptForRefine) {
        CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->pins_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned)));
        CHECK_ERROR(cudaMemcpy((void *)coarsenHgr->pins_hedgeid_list, aux->next_hedgeid_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));
    }
    CHECK_ERROR(cudaFree(aux->next_hedgeid_list));
    // CHECK_ERROR(cudaFree(aux->adj_node_parList));
    // // CHECK_ERROR(cudaFree(aux->nodes_dup_degree));
    // CHECK_ERROR(cudaFree(aux->isSelfMergeNodes));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->totalNodeDegree, aux->d_totalNodeDeg, sizeof(int), cudaMemcpyDeviceToHost));
#if 0
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->incident_nets, coarsenHgr->totalNodeDegree * sizeof(unsigned int)));
    TIMERSTART(17)
    thrust::exclusive_scan(thrust::device, coarsenHgr->nodes + N_DEGREE1(coarsenHgr->nodeNum), 
                            coarsenHgr->nodes + N_DEGREE1(coarsenHgr->nodeNum) + coarsenHgr->nodeNum, 
                            coarsenHgr->nodes + N_OFFSET1(coarsenHgr->nodeNum));
    TIMERSTOP(17)
    time += time17 / 1000.f;
    kernel_pairs.push_back(std::make_pair("thrust::exclusive_scan", time17));

    int* netsListCounter;
    CHECK_ERROR(cudaMalloc((void**)&netsListCounter, coarsenHgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&netsListCounter, coarsenHgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)netsListCounter, 0, coarsenHgr->nodeNum * sizeof(int)));
    
    // int len_y = coarsenHgr->maxDegree < 500 ? coarsenHgr->maxDegree : coarsenHgr->maxDegree / 64;
    // dim3 block;
    // if (coarsenHgr->maxDegree < 500) {
    //     block.x = 32;
    //     block.y = 32;
    // }
    // dim3 grid = dim3(UP_DIV(coarsenHgr->hedgeNum, block.x), UP_DIV(len_y, block.y), 1);
    TIMERSTART(18)
    // fillIncidentNetLists<<<grid, block>>>(coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->incident_nets, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, netsListCounter);
    fillIncidentNetLists<<<coarsenHgr->hedgeNum, blocksize>>>(coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, coarsenHgr->incident_nets, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, netsListCounter);
    // fillIncidentNetLists1<<<hgr->nodeNum, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->incident_nets, 
    //                                 coarsenHgr->nodes, coarsenHgr->incident_nets, hgr->hedgeNum, hgr->nodeNum, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, 
    //                                 netsListCounter, aux->eInBag, aux->nInBag, aux->eNextId, aux->nNextId);
    TIMERSTOP(18)
    time += time18 / 1000.f;
    kernel_pairs.push_back(std::make_pair("fillIncidentNetLists", time18));
    // std::ofstream debug("net_count_result.txt");
    // int* degree = (int*)malloc(coarsenHgr->nodeNum * sizeof(int));
    // CHECK_ERROR(cudaMemcpy((void *)degree, coarsenHgr->nodes + N_DEGREE1(coarsenHgr->nodeNum), coarsenHgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    // for (int i = 0; i < coarsenHgr->nodeNum; ++i) {
    //     debug << degree[i] << ", " << netsListCounter[i] << "\n";
    // }
    // std::cout << netsListCounter[0] << "\n";
    CHECK_ERROR(cudaFree(netsListCounter));
#endif
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->minDegree, aux->d_minPinSize, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->maxDegree, aux->d_maxPinSize, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->minWeight, aux->d_minWeight, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->maxWeight, aux->d_maxWeight, sizeof(int), cudaMemcpyDeviceToHost));
    // GET_LAST_ERR();
    std::cout << "\ntotalPinSize:" << coarsenHgr->totalEdgeDegree << ", totalNodeDegree: " << coarsenHgr->totalNodeDegree << "\n";
    std::cout << "minNodeWeight:" << coarsenHgr->minWeight << ", maxNodeWeight: " << coarsenHgr->maxWeight << "\n";
    std::cout << "minHedgeSize:" << coarsenHgr->minDegree << ", maxHedgeSize: " << coarsenHgr->maxDegree << "\n";
    std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    coarsenHgr->totalWeight = hgr->totalWeight;
    // coarsenHgr->avgHedgeSize = coarsenHgr->totalEdgeDegree / coarsenHgr->hedgeNum;
    std::cout << "current level cuda malloc && memcpy time: " << (timeothers1 + timeothers2) / 1000.f << " s.\n";
    // std::cout << "current level cuda malloc && memcpy duration: " << (duration1.count() + duration2.count()) / 1000.f << " s.\n";
    // std::cout << "current level cuda malloc && memcpy duration: " << time_span1.count() + time_span2.count() << " s.\n";
    std::cout << "current level cuda kernel time: " << time << " s.\n";
    other_time += (timeothers1 + timeothers2) / 1000.f;
    unsigned long curr_bytes = E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int) + N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int) + 1 * coarsenHgr->totalEdgeDegree * sizeof(unsigned);
    memBytes += curr_bytes;
    std::cout << "current iteration accumulate memory space: " << curr_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";

    // perfs[0].second += time0;
    // perfs[1].second += time1;
    // perfs[2].second += time2;
    // perfs[3].second += time3;
    // perfs[4].second += time4;
    // perfs[5].second += time5;
    // perfs[6].second += time6;
    perfs[7].second += time7;
    perfs[8].second += time8;
    perfs[9].second += time9;
    perfs[10].second += time10;
    perfs[11].second += time11;
    perfs[13].second += time13;

    perfs[0].first = "setHyperedgePriority";
    perfs[1].first = "multiNodeMatching1";
    perfs[2].first = "multiNodeMatching2";
    perfs[3].first = "multiNodeMatching3";
    perfs[4].first = "mergeNodesInsideHyperedges";
    perfs[5].first = "PrepareForFurtherMatching";
    perfs[6].first = "mergeMoreNodesAcrossHyperedges";
    perfs[7].first = "countingHyperedgesRetainInCoarserLevel";
    perfs[8].first = "selfMergeSingletonNodes";
    perfs[9].first = "thrust::exclusive_scan";
    perfs[10].first = "setupNodeMapping";
    perfs[11].first = "updateCoarsenNodeId";
    perfs[12].first = "markDuplicasInNextLevelAdjacentList";
    perfs[13].first = "thrust::exclusive_scan";
    perfs[14].first = "constructNextLevelAdjacentList";
    perfs[15].first = "setCoarsenNodesProperties";
    perfs[16].first = "sortNextLevelAdjacentList";

    // TIMERSTART(_var)
    int* next_hedge = (int*)malloc(E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int));
    CHECK_ERROR(cudaMemcpy((void *)next_hedge, coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    // TIMERSTOP(_var)
    int* next_hnode = (int*)malloc(N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int));
    CHECK_ERROR(cudaMemcpy((void *)next_hnode, coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    // int maxPower = findMaxPowerOfTwo(coarsenHgr->hedgeNum);
    // std::cout << "不超过 " << coarsenHgr->hedgeNum << " 的最大的 2 的幂次是: " << maxPower << std::endl;

    // struct timeval tbeg, tend;
    // gettimeofday(&tbeg, NULL);
    // gettimeofday(&beg1, NULL);
    for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        long double diff = next_hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i] - coarsenHgr->avgHedgeSize;
        coarsenHgr->sdHedgeSize += diff * diff;
    }
    coarsenHgr->avgHNdegree = coarsenHgr->totalNodeDegree / coarsenHgr->nodeNum;
    // int test = 0;
    for (int i = 0; i < coarsenHgr->nodeNum; ++i) {
        long double diff = next_hnode[N_DEGREE1(coarsenHgr->nodeNum) + i] - coarsenHgr->avgHNdegree;
        coarsenHgr->sdHNdegree += diff * diff;
        // std::cout << diff << " ";
        // test += next_hnode[N_DEGREE1(coarsenHgr->nodeNum) + i];
    }
    // std::cout << test << "\n";
    // gettimeofday(&tend, NULL);
    // std::cout << "sequential time:" << (tend.tv_sec - tbeg.tv_sec) + ((tend.tv_usec - tbeg.tv_usec)/1000000.0) << "\n";
    
    // long double squaredDifferences = 0.0;
    // omp_set_num_threads(24);
    // gettimeofday(&tbeg, NULL);
    // #pragma omp parallel for reduction(+:squaredDifferences)
    // for (int i = 0; i < coarsenHgr->hedgeNum; i++) {
    //     long double diff = next_hedge[E_DEGREE1(coarsenHgr->hedgeNum) + i] - coarsenHgr->avgHedgeSize;
    //     squaredDifferences += diff * diff;
    // }
    // TIMERSTART(_var)
    // long double result = thrust::transform_reduce(
    //         next_hedge + E_DEGREE1(coarsenHgr->hedgeNum),
    //         next_hedge + E_DEGREE1(coarsenHgr->hedgeNum) + coarsenHgr->hedgeNum,
    //         variance(coarsenHgr->avgHedgeSize),
    //         0.0f,
    //         thrust::plus<long double>());
    // long double result = thrust::transform_reduce(
    //         coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum),
    //         coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum) + coarsenHgr->hedgeNum,
    //         variance(coarsenHgr->avgHedgeSize),
    //         0.0f,
    //         thrust::plus<long double>());
    // gettimeofday(&tend, NULL);
    // std::cout << "parallel time:" << (tend.tv_sec - tbeg.tv_sec) + ((tend.tv_usec - tbeg.tv_usec)/1000000.0) << "\n";
    // TIMERSTOP(_var)
    // std::cout << "parallel time:" << time_var/1000.f << "\n";
    // int h_sdv = 0;
    // CHECK_ERROR(cudaMemcpy((void *)&h_sdv, sdv, sizeof(int), cudaMemcpyDeviceToHost));
    // std::cout << "compare:" << coarsenHgr->sdHedgeSize << ", " << result << "\n";
    
    gettimeofday(&beg1, NULL);
    coarsenHgr->sdHedgeSize = (long double)sqrtf64(coarsenHgr->sdHedgeSize / coarsenHgr->hedgeNum);
    coarsenHgr->sdHNdegree = (long double)sqrtf64(coarsenHgr->sdHNdegree / coarsenHgr->nodeNum);
    gettimeofday(&end1, NULL);
    selectionOverhead += (end1.tv_sec - beg1.tv_sec) + ((end1.tv_usec - beg1.tv_usec)/1000000.0);
    std::cout << "compute sdv:" << (end1.tv_sec - beg1.tv_sec) + ((end1.tv_usec - beg1.tv_usec)/1000000.0) << "\n";
    std::cout << "new avgHedgeSize: " << coarsenHgr->avgHedgeSize << ", new sdHedgeSize: " << coarsenHgr->sdHedgeSize << std::endl;
    std::cout << "new avgHNdegree: " << coarsenHgr->avgHNdegree << ", new sdHNdegree: " << coarsenHgr->sdHNdegree << std::endl;
    free(next_hedge);
    free(next_hnode);
    
    optcfgs.iterative_hedgenum.push_back(hgr->hedgeNum);
    optcfgs.iterative_nodenum.push_back(hgr->nodeNum);
    optcfgs.iterative_adjlist_size.push_back(hgr->totalEdgeDegree);
    optcfgs.iterative_maxhedgesize.push_back(hgr->maxDegree);
    optcfgs.iterative_avghedgesize.push_back(hgr->avgHedgeSize);
    optcfgs.iterative_sdhedgesize.push_back(hgr->sdHedgeSize);
    optcfgs.iterative_time.push_back(iter_time);
    optcfgs.iterative_split_K4.push_back(iter_split_k4);
    optcfgs.iterative_split_K4_in_kernel.push_back(iter_split_k4_in_kernel);
    iter_perfs.push_back(kernel_pairs);

    // CHECK_ERROR(cudaFree(aux->next_hedgeid_list));
    CHECK_ERROR(cudaFree(aux->adj_node_parList));
    CHECK_ERROR(cudaFree(aux->isSelfMergeNodes));
    deallocTempData(aux);
#endif
    return coarsenHgr;
}
