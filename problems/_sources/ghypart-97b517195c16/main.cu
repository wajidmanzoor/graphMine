/*
./mt-kahypar/application/MtKaHyPar -h ../../hypergraph-coarsening/dataset/benchmarks/wb-edu.mtx.hgr -p ../config/deterministic_preset.ini --instance-type=hypergraph -k 2 -e 0.05 -o cut -m direct -t 1
./kahypar/application/KaHyPar -h /home/wuzhenlin/workspace/hypergraph-coarsening/dataset/benchmarks/ISPD98_ibm18.hgr -k 2 -e 0.05 -o cut -m direct -p ../config/cut_kKaHyPar_sea20.ini

./gpu_coarsen ../../dataset/benchmarks/wb-edu.mtx.hgr -bp -bwt -ref_opt 6 -m 5           // 4298
./gpu_coarsen ../../dataset/benchmarks/RM07R.mtx.hgr -bp -bwt -ref_opt 6 -m 3 -r 3       // 20694
./gpu_coarsen ../../dataset/benchmarks/Stanford.mtx.hgr -bp -bwt -ref_opt 7              // 67
./gpu_coarsen ../../dataset/benchmarks/webbase-1M.mtx.hgr -bp -bwt -ref_opt 7            // 351

./gpu_coarsen ../../dataset/benchmarks/nlpkkt120.mtx.hgr -bp -bwt -ref_opt 7               // 97337
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_dual.hgr -bp -bwt -ref_opt 7      // 2808
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_dual.hgr -bp -bwt -ref_opt 6 -m 7 // 2797
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_primal.hgr -bp -bwt -ref_opt 7    // 342256

./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm17.hgr -bp -bwt -coar_opt 2               // 3034
./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm18.hgr -bp -bwt -ref_opt 7 -r 4           // 2040 with weight 68000
./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm18.hgr -bp -bwt -ref_opt 6 -m 3 -r 4      // 2036 with weight 43000
./gpu_coarsen ../../dataset/benchmarks/af_4_k101.mtx.hgr -bp -bwt -r 4                     // 1960
./gpu_coarsen ../../dataset/benchmarks/af_4_k101.mtx.hgr -bp -bwt -ref_opt 6 -m 10 -r 4    // 1935 with weight 49000
./gpu_coarsen ../../dataset/benchmarks/ecology1.mtx.hgr -bp -bwt -adjust_refineTo 5 -r 4   // 2030

./gpu_coarsen ../../dataset/benchmarks/human_gene2.mtx.hgr -bp -bwt -init_opt 3 -ref_opt 8 -m 1 // 9623
*/
#include <iostream>
#include <stdio.h>
#include <stdlib.h>
#include <vector>
#include <set>
#include <map>
#include <string.h>
#include <algorithm>
#include <string>
#include <unordered_set>
#include <tuple>
#include <experimental/filesystem>
#include "include/graph.h"
#include "utility/utils.cuh"
#include "include/coarsening_impl.h"
#include "include/partitioning_impl.h"
#include "include/refinement_impl.h"
#include "include/projection.cuh"
#include "no_uvm_impl/use_no_uvm.cuh"
#include "utility/validation.cuh"
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include <thrust/sort.h>
// #include <graphviz/gvc.h>

#if 0
#define CHECK_ERROR1(err)    checkCudaError1(err, __FILE__, __LINE__)
#define GET_LAST_ERR1()      getCudaLastErr1(__FILE__, __LINE__)

inline void getCudaLastErr1(const char *file, const int line) {
    cudaError_t err;
    if ((err = cudaGetLastError()) != cudaSuccess) {
        std::cerr << "CUDA error: " << file << "(" << line << "): " << cudaGetErrorString(err) << "\n";
        exit(EXIT_FAILURE);
    }
}

inline void checkCudaError1(cudaError_t err, const char *file, const int line) {
    if (err != cudaSuccess) {
        std::cerr << "CUDA error: " << file << "(" << line << "): " << cudaGetErrorString(err) << "\n";
        exit(EXIT_FAILURE);
    }
}
#define UP_DIV1(n, a)    (n + a - 1) / a
// convenient timers
#define TIMERSTART1(label)                                                    \
        cudaSetDevice(0);                                                    \
        cudaEvent_t start##label, stop##label;                               \
        float time##label;                                                   \
        cudaEventCreate(&start##label);                                      \
        cudaEventCreate(&stop##label);                                       \
        cudaEventRecord(start##label, 0);

#define TIMERSTOP1(label)                                                     \
        cudaSetDevice(0);                                                    \
        cudaEventRecord(stop##label, 0);                                     \
        cudaEventSynchronize(stop##label);                                   \
        cudaEventElapsedTime(&time##label, start##label, stop##label);       \
        std::cout << "kernel execution time: #" << time##label                                      \
                  << " ms (" << #label << ")" << std::endl;

__global__ void test_atomic1(int* arr, int length, int* list1, int* list2, int* list3, int* cnt1, int* cnt2, int* cnt3) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < length) {
        if (arr[tid] == 1) {
            list1[atomicAdd(&cnt1[0], 1)] = tid;
        } else if (arr[tid] == 2) {
            list2[atomicAdd(&cnt2[0], 1)] = tid;
        } else if (arr[tid] == 3) {
            list3[atomicAdd(&cnt3[0], 1)] = tid;
        }
    }
}

__global__ void test_compaction1(int* arr, int length, int* mark1, int* mark2, int* mark3) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < length) {
        if (arr[tid] == 1) {
            mark1[tid] = 1;
        } else if (arr[tid] == 2) {
            mark2[tid] = 1;
        } else if (arr[tid] == 3) {
            mark3[tid] = 1;
        }
    }
}
#endif
int main(int argc, char **argv) {
    if (argc < 2) {
        printf("Run the code by typing './exec <path_to_hgr_file> [options]'.\n");
        return 0;
    }

    OptionConfigs optCfgs;
    optCfgs.parse_cmd(argc, argv);
    optCfgs.printBanner();
    char *filepath = argv[1];
    std::string filename = std::experimental::filesystem::path(filepath).filename();
    int deviceCount;
    CHECK_ERROR(cudaGetDeviceCount(&deviceCount));
    int device;
    CHECK_ERROR(cudaGetDevice(&device));
    cudaDeviceProp deviceProp;
    CHECK_ERROR(cudaGetDeviceProperties(&deviceProp, device));
    std::cout << "GPU device model: " << deviceProp.name << "\n";
    std::cout << "compute capability: " << deviceProp.major << ", " << deviceProp.minor << "\n";
    std::cout << "multiProcessorCount:" << deviceProp.multiProcessorCount << "\n";
    std::cout << "maxThreadsPerMultiProcessor:" << deviceProp.maxThreadsPerMultiProcessor << "\n";
    std::cout << "maxThreadsPerBlock:" << deviceProp.maxThreadsPerBlock << "\n";
    std::cout << "regsPerMultiprocessor:" << deviceProp.regsPerMultiprocessor << "\n";
    std::cout << "regsPerBlock:" << deviceProp.regsPerBlock << "\n";

    if (!optCfgs.useCUDAUVM) 
    {
#if 0
        int length = 13378010;
        int* arr = (int*)malloc(length * sizeof(int));
        for (int i = 0; i < length; ++i) {
            arr[i] = 1;
        }
        int* d_arr;
        CHECK_ERROR1(cudaMalloc((void**)&d_arr, length * sizeof(int)));
        CHECK_ERROR1(cudaMemcpy((void *)d_arr, arr, length * sizeof(int), cudaMemcpyHostToDevice));

        int* list1, *list2, *list3;
        CHECK_ERROR1(cudaMalloc((void**)&list1, length * sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&list2, length * sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&list3, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)list1, 0, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)list2, 0, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)list3, 0, length * sizeof(int)));

        int* mark1, *mark2, *mark3;
        CHECK_ERROR1(cudaMalloc((void**)&mark1, length * sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&mark2, length * sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&mark3, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)mark1, 0, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)mark2, 0, length * sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)mark3, 0, length * sizeof(int)));

        int* cnt1, *cnt2, *cnt3;
        CHECK_ERROR1(cudaMalloc((void**)&cnt1, sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&cnt2, sizeof(int)));
        CHECK_ERROR1(cudaMalloc((void**)&cnt3, sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)cnt1, 0, sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)cnt2, 0, sizeof(int)));
        CHECK_ERROR1(cudaMemset((void*)cnt3, 0, sizeof(int)));

        int blocksize = 128;
        int gridsize = UP_DIV1(length, 128);

        TIMERSTART1(0)
        test_compaction1<<<gridsize, blocksize>>>(d_arr, length, mark1, mark2, mark3);
        TIMERSTOP1(0)
        
        TIMERSTART1(1)
        test_atomic1<<<gridsize, blocksize>>>(d_arr, length, list1, list2, list3, cnt1, cnt2, cnt3);
        TIMERSTOP1(1)
#endif
        // warm up
        int warmp_ups = 5;//0;//
        for (int i = 0; i < warmp_ups; ++i) {
            SetupWithoutUVM(optCfgs, argv, deviceProp);
        }
        optCfgs.start = true;
        SetupWithoutUVM(optCfgs, argv, deviceProp);
    } 
    else {
#if 1
    std::vector<Hypergraph*> vHgrs(1);
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0], sizeof(Hypergraph)));
    unsigned int memBytes = sizeof(Hypergraph);

    std::ifstream f(filepath);
    std::string line;
    std::getline(f, line);
    std::stringstream ss(line);
    ss >> vHgrs[0]->hedgeNum >> vHgrs[0]->nodeNum;
    vHgrs[0]->graphSize = vHgrs[0]->hedgeNum + vHgrs[0]->nodeNum;
    
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->hedges, E_LENGTH(vHgrs[0]) * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->nodes, N_LENGTH(vHgrs[0]) * sizeof(int)));
    
    for (int i = 0; i < vHgrs[0]->nodeNum; ++i) {
        int num = vHgrs[0]->nodeNum;
        // vHgrs[0]->nodes[N_ID(vHgrs[0]) + i] = i + 1; // id
        vHgrs[0]->nodes[N_ELEMID(vHgrs[0]) + i] = i + vHgrs[0]->hedgeNum; // elementID i + 1 + vHgrs[0]->hedgeNum
        vHgrs[0]->nodes[N_PRIORITY(vHgrs[0]) + i] = INT_MAX; // priority
        vHgrs[0]->nodes[N_RAND(vHgrs[0]) + i] = INT_MAX; // rand
        vHgrs[0]->nodes[N_HEDGEID(vHgrs[0]) + i] = INT_MAX; // hedgeID
        vHgrs[0]->nodes[N_WEIGHT(vHgrs[0]) + i] = 1; // weight
        vHgrs[0]->maxDegree = 0;
        vHgrs[0]->minDegree = INT_MAX;
        vHgrs[0]->nodes[N_DEGREE(vHgrs[0]) + i] = 0;
        vHgrs[0]->nodes[N_MATCHED(vHgrs[0]) + i] = 0;
    }
    std::vector<unsigned int> edges_id;
    std::vector<std::vector<unsigned>> in_nets(vHgrs[0]->nodeNum);
    uint32_t cnt   = 0;
    uint32_t edges = 0;
    struct timeval begin, end;
    gettimeofday(&begin, NULL);
    while (std::getline(f, line)) {
        std::stringstream ss(line);
        int val;
        while (ss >> val) {
            unsigned newval = vHgrs[0]->hedgeNum + (val - 1);
            edges_id.push_back(newval);
            edges++;
            vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + cnt]++; // degree
            vHgrs[0]->nodes[N_DEGREE(vHgrs[0]) + (val - 1)]++;
            in_nets[val-1].push_back(cnt);
        }
        vHgrs[0]->maxDegree = vHgrs[0]->maxDegree < vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + cnt] ? 
                                vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + cnt] : vHgrs[0]->maxDegree;
        vHgrs[0]->minDegree = vHgrs[0]->minDegree > vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + cnt] ? 
                                vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + cnt] : vHgrs[0]->minDegree;
        vHgrs[0]->hedges[E_IDNUM(vHgrs[0]) + cnt] = cnt + 1; // idNum
        vHgrs[0]->hedges[E_ELEMID(vHgrs[0]) + cnt] = cnt + 1; // elementID
        vHgrs[0]->hedges[E_ELEMID(vHgrs[0]) + cnt] = INT_MAX;
        cnt++;
    }
    vHgrs[0]->totalEdgeDegree = edges;
    vHgrs[0]->totalWeight = vHgrs[0]->nodeNum;
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->adj_list, vHgrs[0]->totalEdgeDegree * sizeof(unsigned int)));
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->par_list, vHgrs[0]->totalEdgeDegree * sizeof(bool)));
    // CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->par_list1, vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMemset((void*)vHgrs[0]->par_list1, 0, vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // vHgrs[0]->num_hedges = vHgrs[0]->hedgeNum;//10000;//50000;
    // vHgrs[0]->bit_length = UP_DIV(vHgrs[0]->nodeNum, 32);
    // CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->bitset, vHgrs[0]->bit_length * vHgrs[0]->num_hedges * sizeof(unsigned))); // hnodeN bits
    // CHECK_ERROR(cudaMemset((void*)vHgrs[0]->bitset, 0, vHgrs[0]->bit_length * vHgrs[0]->num_hedges * sizeof(unsigned)));
    // std::cout << "bitset memory consumption: " << (vHgrs[0]->bit_length * vHgrs[0]->num_hedges * sizeof(unsigned)) / (1024.f * 1024.f * 1024.f) << " GB.\n";
    // std::cout << "bitset size: " << vHgrs[0]->bit_length * vHgrs[0]->num_hedges * sizeof(unsigned) << " bytes.\n";
    CHECK_ERROR(cudaMemcpy(vHgrs[0]->adj_list, &edges_id[0], vHgrs[0]->totalEdgeDegree * sizeof(unsigned int), cudaMemcpyHostToDevice));
    for (int i = 0; i < vHgrs[0]->hedgeNum; ++i) {
        if (i > 0) {
            vHgrs[0]->hedges[E_OFFSET(vHgrs[0]) + i] = // offset
                        vHgrs[0]->hedges[E_OFFSET(vHgrs[0]) + i-1] + vHgrs[0]->hedges[E_DEGREE(vHgrs[0]) + i-1];
        }
    }
    for (int i = 0; i < vHgrs[0]->nodeNum; ++i) {
        vHgrs[0]->totalNodeDegree += in_nets[i].size();
        if (i > 0) {
            vHgrs[0]->nodes[N_OFFSET(vHgrs[0]) + i] = vHgrs[0]->nodes[N_OFFSET(vHgrs[0]) + i-1] + vHgrs[0]->nodes[N_DEGREE(vHgrs[0]) + i-1];
        }
    }
    CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->incident_nets, vHgrs[0]->totalNodeDegree * sizeof(unsigned int)));
    for (int i = 0; i < vHgrs[0]->nodeNum; ++i) {
        std::copy(in_nets[i].begin(), in_nets[i].end(), vHgrs[0]->incident_nets + vHgrs[0]->nodes[N_OFFSET(vHgrs[0]) + i]);
    }
    
    gettimeofday(&end, NULL);
    float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
    std::cout << "read input elapsed: " << elapsed << " s.\n";
    f.close();
    // CHECK_ERROR(cudaMallocManaged(&vHgrs[0]->tmp_bag, vHgrs[0]->nodeNum * sizeof(bool)));
    vHgrs[0]->maxVertDeg = *thrust::max_element(thrust::device, vHgrs[0]->nodes + N_DEGREE(vHgrs[0]), 
                                vHgrs[0]->nodes + N_DEGREE(vHgrs[0]) + vHgrs[0]->nodeNum);
    vHgrs[0]->minVertDeg = *thrust::min_element(thrust::device, vHgrs[0]->nodes + N_DEGREE(vHgrs[0]), 
                                vHgrs[0]->nodes + N_DEGREE(vHgrs[0]) + vHgrs[0]->nodeNum);
    vHgrs[0]->maxdeg_nodeIdx = thrust::max_element(thrust::device, vHgrs[0]->nodes + N_DEGREE(vHgrs[0]), 
                                vHgrs[0]->nodes + N_DEGREE(vHgrs[0]) + vHgrs[0]->nodeNum) - (vHgrs[0]->nodes + N_DEGREE(vHgrs[0]));
    // std::ofstream out0("original_nodes.txt");
    // for (int i = 0; i < vHgrs[0]->nodeNum; ++i) {
    //     out0 << i << ": " << vHgrs[0]->nodes[i + N_DEGREE(vHgrs[0])] << ", " << vHgrs[0]->nodes[i + N_WEIGHT(vHgrs[0])] << "\n";
    // }
    std::cout << "hedgeNum: " << vHgrs[0]->hedgeNum << ", nodeNum: " << vHgrs[0]->nodeNum << "\n";
    std::cout << "totalEdgeDegree: " << vHgrs[0]->totalEdgeDegree << ", totalNodeDegree: " << vHgrs[0]->totalNodeDegree << "\n";
    std::cout << "minHedgeSize: " << vHgrs[0]->minDegree << ", maxHedgeSize: " << vHgrs[0]->maxDegree << "\n";
    std::cout << "maxDegree node index: " << vHgrs[0]->maxdeg_nodeIdx << "\n"; // 7420108, 25762
    std::cout << "maxNodeDegree:" << vHgrs[0]->maxVertDeg << ", minNodeDegree:" << vHgrs[0]->minVertDeg << "\n";
    std::cout << E_LENGTH(vHgrs[0]) << ", " << N_LENGTH(vHgrs[0]) << "\n";
    std::cout << "inital memory allocation: " << memBytes * 1.0 / (1024 * 1024 * 1024) << " GB.\n";

    // for (int i = 0; i < vHgrs[0]->bit_length * vHgrs[0]->num_hedges; ++i) {
    //     std::cout << "i:" << i << "\n";
    //     int cur_bit = vHgrs[0]->bitset[i];
    // }

    float imbalance = optCfgs.stats.imbalance_ratio;//3.0;//8.0;//5.0;//
    float ratio  = (50.0 + imbalance) / (50.0 - imbalance);//55.0 / 45.0;
    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int hi       = (1 + tol) * vHgrs[0]->nodeNum / (2 + tol); // 55 / 100
    int LIMIT          = hi / 4;
    std::cout << "BiPart's LIMIT weight: " << LIMIT << "\n";
    if (optCfgs.runBipartWeightConfig || optCfgs.runBaseline) {
        optCfgs.coarseI_weight_limit = LIMIT;//INT_MAX;//
        optCfgs.coarseMore_weight_limit = INT_MAX;
    }
    // if (optCfgs.run_without_params) {
    //     optCfgs.coarseI_weight_limit = LIMIT;//
    //     optCfgs.coarseMore_weight_limit = INT_MAX;//
    // }
    // if (optCfgs.runBipartBestPolicy) {
    //     optCfgs.coarseI_weight_limit = LIMIT;//70000;//
    //     optCfgs.coarseMore_weight_limit = INT_MAX;//70000;//
    // }
    // if (optCfgs.runDebugMode) {
    //     optCfgs.coarseI_weight_limit = 3100;//62000;//17500;//57000;//8000;//500000;//LIMIT;//70000;//32000;//
    //     optCfgs.coarseMore_weight_limit = 3100;//62000;//17500;//57000;//8000;//500000;//INT_MAX;//70000;//32000;//
    // }
    if (optCfgs.useCoarseningOpts <= 2 && !optCfgs.useInitPartitionOpts && !optCfgs.useRefinementOpts) {
        optCfgs.useFirstTwoOptsOnly = true;
    }
    std::cout << "optionconfigs: " << optCfgs.coarseI_weight_limit << ", " << optCfgs.coarseMore_weight_limit << "\n";
    std::cout << "matching policy: " << optCfgs.matching_policy << "\n";
    // getchar();
    // LIMIT = vHgrs[0]->maxVertDeg;//2017;//
    int iterNum = 0;
    int coarsenTo = 25;
    unsigned size = vHgrs[0]->nodeNum;
    unsigned newsize = size;
    unsigned hedgesize = 0;
    Hypergraph* coarsenHgr = vHgrs[0];
    float coarsen_time = 0.f;
    // std::ofstream debug("coarsen_nodes_weight_info.txt");
    std::cout << "\n============================= start coarsen =============================\n";
    while (newsize > coarsenTo) {
    // while (iterNum < 1) {
        // if (iterNum == atoi(argv[2]))  break;
        if (iterNum > coarsenTo) {
            std::cout << __LINE__ << "here~~\n";
            break;
        }
        if (newsize - size <= 0 && iterNum > 2) {
            std::cout << __LINE__ << "here~~\n";
            break;
        }
        char *prefetch = getenv("__PREFETCH");
        if (prefetch == nullptr || strcmp(prefetch, "off") != 0) {
            std::cout << "using memory prefetching\n";
            cudaMemPrefetchAsync(coarsenHgr, sizeof(Hypergraph), device, NULL);
            cudaMemPrefetchAsync(coarsenHgr->hedges, E_LENGTH(coarsenHgr) * sizeof(int), device, NULL);
            cudaMemPrefetchAsync(coarsenHgr->nodes, N_LENGTH(coarsenHgr) * sizeof(int), device, NULL);
            cudaMemPrefetchAsync(coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int), device, NULL);
            cudaMemPrefetchAsync(coarsenHgr->par_list, coarsenHgr->totalEdgeDegree * sizeof(bool), device, NULL);
            // cudaMemPrefetchAsync(coarsenHgr->par_list1, coarsenHgr->totalEdgeDegree * sizeof(unsigned), device, NULL);
            // cudaMemPrefetchAsync(coarsenHgr->bitset, coarsenHgr->bit_length * coarsenHgr->num_hedges * sizeof(unsigned), device, NULL);
        }
        std::cout << "minNodeDegree: " << coarsenHgr->minVertDeg << ", maxNodeDegree: " << coarsenHgr->maxVertDeg << "\n";
        size = coarsenHgr->nodeNum;
        // int flag = atoi(argv[2]);
        std::cout << "LIMIT weight: " << LIMIT << "\n";
        vHgrs.emplace_back(coarsen(coarsenHgr, iterNum, LIMIT, coarsen_time, optCfgs));
        coarsenHgr = vHgrs.back();
        newsize = coarsenHgr->nodeNum;
        hedgesize = coarsenHgr->hedgeNum;
        // debug << "iteration " << iterNum << "=====:\n";
        // for (int i = 0; i < coarsenHgr->nodeNum; ++i) {
        //     debug << "node: " << i << ", degree: " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + i] << ", weight: " << coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + i] << "\n";
        // }
        if (hedgesize < 1000) {
            std::cout << __LINE__ << "here~~\n";
            break;
        }
        ++iterNum;
        std::cout << "===============================\n\n";
    }
    if (optCfgs.exp_id == VALIDATE_COARSENING_RESULT) {
        coarsening_validation(vHgrs.back(), optCfgs.useCUDAUVM);
    }
#if PRINT_RESULT    
    std::string out_name = "../debug/myimpl_final.txt";
    std::ofstream out(out_name);
    std::ofstream out1("../debug/mycoarsen.txt");
    for (int i = 0; i < vHgrs.back()->hedgeNum; ++i) {
        out1 << "new element_id[" << i << "]: ";
        int degree = vHgrs.back()->hedges[E_DEGREE(vHgrs.back()) + i];
        for (int j = 0; j < degree; ++j) {
            out1 << vHgrs.back()->adj_list[vHgrs.back()->hedges[E_OFFSET(vHgrs.back()) + i] + j] << " ";
        }
        out1 << "\n";
    }
    std::ofstream outnw("../debug/mynodeweight.txt");
    for (int i = 0; i < vHgrs.back()->nodeNum; ++i) {
        outnw << i << ": " << vHgrs.back()->nodes[i + N_WEIGHT(vHgrs.back())] << "\n";
    }
#endif
#if 1
    unsigned *cpu_nets = new unsigned[vHgrs.back()->totalNodeDegree];
    unsigned *cpu_cnts = new unsigned[vHgrs.back()->nodeNum];
    memset(cpu_cnts, 0, vHgrs.back()->nodeNum * sizeof(unsigned));
    for (int i = 0; i < vHgrs.back()->hedgeNum; ++i) {
        for (int j = 0; j < vHgrs.back()->hedges[E_DEGREE(vHgrs.back()) + i]; ++j) {
            unsigned nodeid = vHgrs.back()->adj_list[vHgrs.back()->hedges[E_OFFSET(vHgrs.back()) + i] + j];
            cpu_nets[vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + nodeid - vHgrs.back()->hedgeNum] + cpu_cnts[nodeid - vHgrs.back()->hedgeNum]] = i;
            cpu_cnts[nodeid - vHgrs.back()->hedgeNum]++;
        }
    }
    std::ofstream outnets("gpu_uvm_incident_netlists.txt");
    std::ofstream outcpu("cpu_incident_netlists.txt");
    for (int i = 0; i < vHgrs.back()->nodeNum; ++i) {
        std::sort(vHgrs.back()->incident_nets + vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i], 
                  vHgrs.back()->incident_nets + vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i] + vHgrs.back()->nodes[N_DEGREE(vHgrs.back()) + i]);
        std::sort(cpu_nets + vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i], 
                  cpu_nets + vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i] + vHgrs.back()->nodes[N_DEGREE(vHgrs.back()) + i]);
        outnets << "node " << i << "'s incident netid: ";
        outcpu << "node " << i << "'s incident netid: ";
        for (int j = 0; j < vHgrs.back()->nodes[N_DEGREE(vHgrs.back()) + i]; ++j) {
            outnets << vHgrs.back()->incident_nets[vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i] + j] << " ";
            outcpu << cpu_nets[vHgrs.back()->nodes[N_OFFSET(vHgrs.back()) + i] + j] << " ";
        }
        outnets << "\n";
        outcpu << "\n";
    }
    
    delete cpu_cnts;
    delete cpu_nets;
#endif
    float total = coarsen_time;
    std::cout << __LINE__ << ":" << vHgrs.size() << "\n";
    std::cout << "coarsen execution time: " << coarsen_time << " s.\n";
    std::cout << "finish coarsen.\n";

    bool use_curr_precision = true;
    if (optCfgs.filename == "ecology1.mtx.hgr") {
        use_curr_precision = false;
    }
    std::cout << "\n============================= start initial partition =============================\n";
    float partition_time = 0.f;
    unsigned int numPartitions = 2;
#if 1
    if (optCfgs.runBaseline || optCfgs.useInitPartitionOpts != FIX_HEAVIEST_NODE) {
        partition_baseline(vHgrs.back(), numPartitions, use_curr_precision, partition_time, optCfgs);
    } else if (optCfgs.useInitPartitionOpts == FIX_HEAVIEST_NODE) {
        partition_opt2(vHgrs.back(), numPartitions, use_curr_precision, partition_time);
    }
    if (optCfgs.exp_id == VALIDATE_INITIAL_PARTITION_RESULT) {
        initial_partitioning_validation(vHgrs.back(), optCfgs.useCUDAUVM);
    }
#endif
    std::cout << "finish initial partition.\n";
    std::cout << "initial partition time: " << partition_time << " s.\n";
    total += partition_time;
#if PRINT_RESULT
    std::ofstream out2("../debug/initial_partition.txt");
    out2 << "initial partition result:\n";
    for (int i = 0; i < vHgrs.back()->nodeNum; ++i) {
        out2 << vHgrs.back()->nodes[i + N_FS(vHgrs.back())] << ", "
            << vHgrs.back()->nodes[i + N_TE(vHgrs.back())] << ", "
            << vHgrs.back()->nodes[i + N_PARTITION(vHgrs.back())] << "\n";
    }
#endif

    if (optCfgs.useRefinementOpts == MERGING_MOVE) {
        optCfgs.switchToMergeMoveLevel = iterNum + 1;
    }
    unsigned refineTo = optCfgs.refineIterPerLevel;//2;
    ratio = 0.0f;
    tol   = 0.0f;
    bool flag = ceil(log2(numPartitions)) == floor(log2(numPartitions));
    if (flag) {
        ratio = (50.0f + imbalance)/(50.0f - imbalance);
        tol   = std::max(ratio, 1 - ratio) - 1;
    } else {
        ratio = (numPartitions + 1) / 2 / numPartitions / 2;
        tol   = std::max(ratio, 1 - ratio) - 1;
    }
    std::cout << "\n============================= start refinement =============================\n";
    float Refine_time = 0.f;
    float refine_time = 0.f;
    float balance_time = 0.f;
    float project_time = 0.f;
    int rebalance = 0;
    int curr_idx = vHgrs.size()-1;
#if PRINT_RESULT
    out_name = "../debug/edge_cut_" + filename + ".csv";
    std::ofstream out_cut(out_name);
    out_cut << filename << "\n";
    out_cut << "iterNum,#edge cut after refinement,#edge cut after rebalance\n";
#endif
#if 1
    do {
        // if (vHgrs.size() == 0)  break;
        float cur_ref = 0.f;
        float cur_bal = 0.f;
        float cur_pro = 0.f;
        if (optCfgs.runBaseline || optCfgs.useFirstTwoOptsOnly == true) {
            parallel_refine(vHgrs[curr_idx], refineTo, refine_time, cur_ref, curr_idx, optCfgs);
            parallel_balance(vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, rebalance, curr_idx, optCfgs);
        } else {
            if (optCfgs.useRefinementOpts == ADAPTIVE_MOVING || optCfgs.useRefinementOpts == MERGING_MOVE) {
                refinement_opt1(vHgrs[curr_idx], refineTo, numPartitions, imbalance, refine_time, cur_ref, curr_idx, ratio, iterNum, optCfgs);
                rebalancing_opt1(vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, rebalance, curr_idx, iterNum, optCfgs);
            }
            if (optCfgs.useRefinementOpts == GAIN_RECALCULATION) {
                refinement_opt2(vHgrs[curr_idx], refineTo, numPartitions, imbalance, refine_time, cur_ref, curr_idx, ratio, iterNum, optCfgs);
                rebalancing_opt2(vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, rebalance, curr_idx, iterNum, optCfgs);
            }
            if (optCfgs.useRefinementOpts == FIX_HEAVIEST_NODE) {
                refinement_opt3(vHgrs[curr_idx], refineTo, numPartitions, imbalance, refine_time, cur_ref, curr_idx, ratio, iterNum, optCfgs);
                rebalancing_opt3(vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, rebalance, curr_idx, iterNum, optCfgs);
            }
            if (optCfgs.useRefinementOpts == FIX_NODE_ADAP_MOVE) {
                refinement_opt4(vHgrs[curr_idx], refineTo, numPartitions, imbalance, refine_time, cur_ref, curr_idx, ratio, iterNum, optCfgs);
                rebalancing_opt4(vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, rebalance, curr_idx, iterNum, optCfgs);
            }
        }
        if (curr_idx > 0) {
            projectPartition(vHgrs[curr_idx], vHgrs[curr_idx-1], project_time, cur_pro, curr_idx);
        }
        std::cout << "curr_iter:" << curr_idx << ", edgecut:" << computeHyperedgeCut(vHgrs[curr_idx]) << "\n";
        std::cout << "cur_ref:" << cur_ref << ", cur_bal:" << cur_bal << ", cur_pro:" << cur_pro << "\n";
        curr_idx--;
        std::cout << "===============================\n\n";
    } while (curr_idx >= 0);
#endif
    int hyperedge_cut = computeHyperedgeCut(vHgrs[0]);
    if (optCfgs.exp_id == VALIDATE_FINAL_PARTITION_RESULT) {
        optCfgs.stats.hyperedge_cut_num = hyperedge_cut;
        final_partitioning_validation(vHgrs[0], optCfgs.stats, optCfgs.useCUDAUVM);
    }
    computeBalanceResult(vHgrs[0], numPartitions, imbalance, optCfgs.stats.parts);

#if PRINT_RESULT
    std::string myresults = "../debug/" + optCfgs.filename + "_gpu_results.txt";
    std::ofstream cmp(myresults);
    out << "final partition result:\n";
    for (int i = 0; i < vHgrs[0]->nodeNum; ++i) {
        out << i << ": " << vHgrs[0]->nodes[i + N_PARTITION(vHgrs[0])] << "\n";
        cmp << vHgrs[0]->nodes[i + N_PARTITION(vHgrs[0])] << "\n";
    }
#endif
    Refine_time = refine_time + balance_time + project_time;
    std::cout << "refinement time: " << refine_time << "\n";
    std::cout << "rebalance time: " << balance_time << "\n";
    std::cout << "projection time: " << project_time << "\n";
    std::cout << "# of coarsening iterations:" << iterNum << ", # of rebalancing during refinement:" << rebalance << "\n";
    std::cout << "finish refinement.\n";
    total += Refine_time;
    std::cout << "Coarsening time: " << coarsen_time << " s.\n";
    std::cout << "Initial partition time: " << partition_time<< " s.\n";
    std::cout << "Refinement time: " << Refine_time << " s.\n";
    std::cout << "Total execution time: " << total << " s.\n";
    std::cout << "\n============================= Hypergraph Partitioning Statistics ==============================\n";
    std::cout << "# of Hyperedge cut: " << hyperedge_cut << "\n";
    std::cout << "init_partition imbalance " << optCfgs.stats.init_partition_imbalance << "\n";
    std::cout << "Balance results:[epsilon = " << imbalance / 100.0f << "]:\n";
    // printBalanceResult(vHgrs[0], numPartitions, imbalance);
    for (int i = 0; i < numPartitions; ++i) {
        std::cout << "|Partition " << i << "| = " << optCfgs.stats.parts[i] << ", |V|/" << numPartitions << " = " << vHgrs[0]->nodeNum / numPartitions
                << ", final ratio: " << fabs(optCfgs.stats.parts[i] - vHgrs[0]->nodeNum / numPartitions) / (float)(vHgrs[0]->nodeNum / numPartitions) << "\n";
    }
    std::cout << "===============================================================================================\n";

    optCfgs.stats.total_time = total;
    optCfgs.stats.coarsen_time = coarsen_time;
    optCfgs.stats.partition_time = partition_time;
    optCfgs.stats.Refine_time = Refine_time;
    optCfgs.stats.refine_time = refine_time;
    optCfgs.stats.balance_time = balance_time;
    optCfgs.stats.project_time = project_time;
    optCfgs.stats.rebalance = rebalance;
    optCfgs.stats.coarsen_iterations = iterNum;
    optCfgs.stats.hyperedge_cut = hyperedge_cut;
    optCfgs.stats.maxNodeWeight = vHgrs.back()->maxWeight;
    optCfgs.statistics2csv();

#if COMPARE_RESULT
    std::string mt_kahypar = "../debug/" + filename + ".mtkahypar.txt";
    std::ifstream res(mt_kahypar);
    std::string line1;
    int id = 0;
    std::string rev_mt_kahypar = "../debug/" + filename + ".mtkahypar.rev.txt";
    std::ofstream revert(rev_mt_kahypar);
    std::ofstream diff("../debug/diff.txt");
    while (std::getline(res, line1)) {
        std::stringstream ss(line1);
        int val;
        ss >> val;
        // val == 1 ? vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] = 0 : vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] = 1;
        // vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] = val;
        // revert << vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] << "\n";
        val == 1 ? val = 0 : val = 1;
        revert << val << "\n";
        if (vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] != val) {
            diff << "diff: id:" << id << ": " << vHgrs[0]->nodes[id + N_PARTITION(vHgrs[0])] << "[gpu], " << val << "[mtkahypar], degree:" << vHgrs[0]->nodes[id + N_DEGREE(vHgrs[0])] << "\n";
        }
        id++;
    }
#endif
    while (!vHgrs.empty()) {
        Hypergraph* hgr = vHgrs.back();
        vHgrs.pop_back();
        CHECK_ERROR(cudaFree(hgr->incident_nets));
        CHECK_ERROR(cudaFree(hgr->adj_list));
        CHECK_ERROR(cudaFree(hgr->nodes));
        CHECK_ERROR(cudaFree(hgr->hedges));
        CHECK_ERROR(cudaFree(hgr));
    }

    // std::for_each(vHgrs.begin(), vHgrs.end(), deletePtr());
    // vHgrs.clear();
#endif
    }
    std::cout << "finish all.\n";
    return 0;
}
