#include <iostream>
#include <fstream>
#include "utils.cuh"
#include "include/graph.h"
#include "kernels/construction_kernels.cuh"
#include "include/construction_impl.h"
#include <thrust/find.h>
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/unique.h>
#include <thrust/execution_policy.h>
#include "cuda_runtime_api.h"
#include <algorithm>
#include <atomic>


__global__ void testIncidentNetLists(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned* newNetList, int hedgeN, int nodeN, int newHedgeN, int newNodeN, int* netsListCounter) {
    int tidx = blockIdx.x;
    if (tidx < nodeN) {
        if (hgr->nodes[tidx + N_INBAG(hgr)]) {
            int n_id = hgr->nodes[tidx + N_MAP_PARENT(hgr)] - newHedgeN;
            int tid = threadIdx.x;
            // if (threadIdx.x == 0) {
            //     atomicAdd(&netsListCounter[0], 1);
            // }
            // while (tid < hgr->nodes[tidx + N_DEGREE(hgr)]) {
            //     int hedgeid = hgr->incident_nets[hgr->nodes[tidx + E_OFFSET(hgr)] + tid];
            //     if (hgr->hedges[hedgeid + E_INBAG(hgr)]) {
            //         int h_id = hgr->hedges[hedgeid + E_NEXTID(hgr)];
            //         int count = atomicAdd(&netsListCounter[n_id], 1);
            //         newNetList[coarsenHgr->nodes[N_OFFSET(hgr) + n_id] + count] = h_id;
            //     }
            //     tid += blockDim.x;
            // }
        }
    }
}

__global__ void testIncidentNetLists1(Hypergraph* hgr, Hypergraph* coarsenHgr, unsigned* newNetList, int hedgeN, int nodeN, int newHedgeN, int newNodeN, int* netsListCounter) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < nodeN) {
        if (hgr->nodes[tid + N_INBAG(hgr)]) {
            int n_id = hgr->nodes[tid + N_PARENT(hgr)] - newHedgeN;
            // netsListCounter[n_id] = n_id;
            for (int i = 0; i < hgr->nodes[tid + N_DEGREE(hgr)]; ++i) {
                int hedgeid = hgr->incident_nets[hgr->nodes[tid + E_OFFSET(hgr)] + tid];
                // if (hgr->hedges[hedgeid + E_INBAG(hgr)]) 
                {
                    atomicAdd(&netsListCounter[n_id], 1);
                }
            }
        }
    }
}


void constructHgr(Hypergraph* hgr, Hypergraph* coarsenHgr, float& time, int iter, OptionConfigs& optcfgs) {
    coarsenHgr->totalEdgeDegree = 0;
    coarsenHgr->minDegree = INT_MAX;
    coarsenHgr->maxDegree = 0;
    coarsenHgr->minWeight = INT_MAX;
    coarsenHgr->maxWeight = 0;
    coarsenHgr->minVertDeg = INT_MAX;
    coarsenHgr->maxVertDeg = 0;
    // TIMERSTART(fill)
    thrust::fill(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum, 0);
    thrust::fill(thrust::device, coarsenHgr->nodes + N_MATCHED(coarsenHgr), coarsenHgr->nodes + N_MATCHED(coarsenHgr) + coarsenHgr->nodeNum, 0);
    // TIMERSTOP(fill)

    // coarsenHgr->hedgeListLen = coarsenHgr->hedgeNum * hgr->maxDegree;
    dim3 block(16, 16, 1);
    int len_y = hgr->maxDegree < 500 ? hgr->maxDegree : hgr->maxDegree / 64;
    if (hgr->maxDegree < 500) {
        block.x = 32;
        block.y = 32;
    }
    dim3 grid(UP_DIV(hgr->hedgeNum, block.x), UP_DIV(len_y, block.y), 1);
    // int block1 = 256;
    // int grid1 = UP_DIV(hgr->hedgeNum, block1);
    TIMERSTART(6)
#if 1
    setParentEdgeList<<<grid, block>>>(hgr, hgr->hedgeNum, coarsenHgr);
    // setParentEdgeList1<<<grid1, block1>>>(hgr, hgr->hedgeNum, coarsenHgr);
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     if (hgr->hedges[E_INBAG(hgr) + i]) {
    //         unsigned h_id = hgr->hedges[i + E_NEXTID(hgr)];
    //         int id = h_id;
    //         thrust::sort(hgr->par_list + hgr->hedges[i + E_OFFSET(hgr)], 
    //                         hgr->par_list + hgr->hedges[i + E_OFFSET(hgr)] + hgr->hedges[i + E_DEGREE(hgr)]);
    //         unsigned* end = thrust::unique(hgr->par_list + hgr->hedges[i + E_OFFSET(hgr)], 
    //                                         hgr->par_list + hgr->hedges[i + E_OFFSET(hgr)] + hgr->hedges[i + E_DEGREE(hgr)]);
    //         coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)] = end - (hgr->par_list + hgr->hedges[i + E_OFFSET(hgr)]);
    //         coarsenHgr->totalEdgeDegree += coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)];
    //         coarsenHgr->hedges[id + E_OFFSET(coarsenHgr)] = coarsenHgr->hedges[id -1 + E_OFFSET(coarsenHgr)] + 
    //                                                         coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)];
    //         coarsenHgr->minDegree = std::min(coarsenHgr->minDegree, coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)]);
    //         coarsenHgr->maxDegree = std::max(coarsenHgr->maxDegree, coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)]);
    //     }
    // }
#endif
    TIMERSTOP(6)

    // int num_hedges = hgr->hedgeNum;//1;//10000;//50000;
    // int bit_length = UP_DIV(coarsenHgr->nodeNum, 32);
    // hgr->bit_length = UP_DIV(coarsenHgr->nodeNum, 32);//coarsenHgr->nodeNum;
    // hgr->num_hedges = hgr->hedgeNum;
    // unsigned* bitset;
    // std::cout << "bitset memory consumption: " << (bit_length * num_hedges * sizeof(unsigned)) / (1024.f * 1024.f * 1024.f) << " GB.\n";
    // CHECK_ERROR(cudaMallocManaged(&hgr->bitset, hgr->bit_length * hgr->num_hedges * sizeof(unsigned))); // hnodeN bits
    // CHECK_ERROR(cudaMalloc((void**)&hgr->bitset, hgr->bit_length * hgr->num_hedges * sizeof(unsigned))); // hnodeN bits
    // CHECK_ERROR(cudaMemset((void*)hgr->bitset, 0, hgr->bit_length * hgr->num_hedges * sizeof(unsigned)));
    // dim3 block0(1, 128, 1);
    // dim3 grid0(UP_DIV(hgr->num_hedges, block0.x), UP_DIV(block0.y, block0.y), 1);
    // int blocksize0 = 128;
    // int gridsize0 = hgr->hedgeNum;
    TIMERSTART(1_2)
#if 0
    // markDuplicasInNextLevelAdjacentList1<<<grid0, block0>>>(hgr, hgr->hedgeNum, hgr->nodeNum, coarsenHgr, coarsenHgr->hedgeNum, bit_length, num_hedges);
    // markDuplicasInNextLevelAdjacentList1<<<grid0, block0>>>(hgr, hgr->hedgeNum, hgr->nodeNum, coarsenHgr, coarsenHgr->hedgeNum, hgr->bit_length, hgr->num_hedges);
    // markDuplicasInNextLevelAdjacentList2<<<gridsize0, blocksize0>>>(hgr, hgr->hedgeNum, hgr->nodeNum, coarsenHgr, coarsenHgr->hedgeNum, hgr->bit_length, hgr->num_hedges);
    markDuplicasInNextLevelAdjacentList3<<<gridsize0, blocksize0>>>(hgr, hgr->hedgeNum, hgr->nodeNum, coarsenHgr, coarsenHgr->hedgeNum, hgr->bit_length, hgr->num_hedges);
#endif
    TIMERSTOP(1_2)
    // GET_LAST_ERR();
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     if (hgr->hedges[E_INBAG(hgr) + i]) {
    //         unsigned h_id = hgr->hedges[i + E_NEXTID(hgr)];
    //         int id = h_id;
    //         for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //             unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARENT(hgr)];
    //             bool isfind = false;
    //             for (int k = 0; k < j; k++) {
    //                 if (hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + k] - hgr->hedgeNum + N_PARENT(hgr)] == pid) {
    //                     isfind = true;
    //                     break;
    //                 }
    //             }
    //             if (!isfind) {
    //                 hgr->par_list1[hgr->hedges[i + E_OFFSET(hgr)] + j] = 1;
    //                 coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)]++;
    //                 coarsenHgr->totalEdgeDegree++;
    //                 if (i == 24 && j == 0) {
    //                     std::cout << hgr->par_list1[hgr->hedges[24 + E_OFFSET(hgr)] + 0] << "\n";
    //                 }
    //             }
    //         }
    //     }
    // }
    // std::cout << hgr->par_list1[hgr->hedges[24 + E_OFFSET(hgr)] + 0] << "\n";
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     if (hgr->hedges[E_INBAG(hgr) + i]) {
    //         unsigned h_id = hgr->hedges[i + E_NEXTID(hgr)];
    //         int id = h_id;
    //         for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //             unsigned curr_loc = hgr->hedges[i + E_OFFSET(hgr)] + j;
    //             unsigned candidate = hgr->nodes[hgr->adj_list[curr_loc] - hgr->hedgeNum + N_PARENT(hgr)] - coarsenHgr->hedgeNum;
    //             unsigned bitset_idx = candidate / 32;
    //             unsigned bit_offset = candidate & 31;
    //             unsigned shift_bits = 31 - bit_offset;
    //             unsigned bitset_loc = (i % num_hedges) * hgr->bit_length + bitset_idx;
    //             // std::cout << "i:" << i << ", j:" << j << ", " << bitset_loc << "\n";
    //             int cur_bit = hgr->bitset[bitset_loc];
    //             hgr->bitset[bitset_loc] |= (0x80000000 >> bit_offset);
    //             int extract_bit_val = (cur_bit & (1 << shift_bits)) >> shift_bits;
    //             if (extract_bit_val == 0) {
    //                 // if (iter == 0) {
    //                 //     if (i == 24 && hgr->par_list1[curr_loc] == 1) {
    //                 //         std::cout << "here!! ";
    //                 //     }
    //                 // }
    //                 hgr->par_list1[curr_loc] = 1;
    //                 coarsenHgr->hedges[id + E_DEGREE(coarsenHgr)]++;
    //                 coarsenHgr->totalEdgeDegree++;
    //             } else {
    //                 hgr->par_list1[curr_loc] = 0;
    //             }
    //         }
    //         // memset(hgr->bitset + (i % num_hedges) * bit_length, 0, bit_length);
    //     }
    // }
    // if (iter == 0) {
    //     // std::ofstream debug("../debug/uvm_check_marklist_old_results.txt");
    //     std::ofstream debug("../debug/uvm_check_marklist_new_results.txt");
    //     // for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
    //     //     debug << hgr->par_list[i] << "\n";
    //     // }
    //     for (int i = 0; i < hgr->hedgeNum; ++i) {
    //         if (hgr->hedges[E_INBAG(hgr) + i]) {
    //             debug << "hedge " << i << ": valid!\n";
    //             for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //                 unsigned curr_loc = hgr->hedges[i + E_OFFSET(hgr)] + j;
    //                 debug << hgr->nodes[hgr->adj_list[curr_loc] - hgr->hedgeNum + N_PARENT(hgr)] - coarsenHgr->hedgeNum << " ";
    //             }
    //             debug << "\n";
    //         } else {
    //             debug << "hedge " << i << ": invalid!\n";
    //         }
    //         for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //             debug << hgr->par_list1[hgr->hedges[i + E_OFFSET(hgr)] + j] << " ";
    //         }
    //         debug << "\n";
    //     }
    // }
    // thrust::exclusive_scan(thrust::device, coarsenHgr->hedges + E_DEGREE(coarsenHgr), 
    //                 coarsenHgr->hedges + E_DEGREE(coarsenHgr) + coarsenHgr->hedgeNum, coarsenHgr->hedges + E_OFFSET(coarsenHgr));
    // if (hgr->hedgeNum == 10000) {
    //     std::ofstream debug("../debug/coarsen_parent_list1.txt");
    //     for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
    //         debug << hgr->par_list[i] << "\n";
    //     }
    //     std::ofstream debug1("../debug/coarsen_new_hedges1.txt");
    //     for (int i = 0; i < E_LENGTH(coarsenHgr); ++i) {
    //         debug1 << coarsenHgr->hedges[i] << "\n";
    //     }
    //     std::ofstream debug2("../debug/coarsen_new_nodes1.txt");
    //     for (int i = 0; i < N_LENGTH(coarsenHgr); ++i) {
    //         debug2 << coarsenHgr->nodes[i] << "\n";
    //     }
    // }
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int)));
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr->par_list, coarsenHgr->totalEdgeDegree * sizeof(bool)));
    // TIMERSTART(13)
    // thrust::exclusive_scan(thrust::device, coarsenHgr->hedges + E_DEGREE(coarsenHgr), 
    //                         coarsenHgr->hedges + E_DEGREE(coarsenHgr) + coarsenHgr->hedgeNum, 
    //                         coarsenHgr->hedges + E_OFFSET(coarsenHgr));
    // TIMERSTOP(13)
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->hedgeNum + coarsenHgr->nodeNum, blocksize);
    TIMERSTART(7)
    thrust::exclusive_scan(thrust::device, coarsenHgr->hedges + E_DEGREE(coarsenHgr), 
                    coarsenHgr->hedges + E_DEGREE(coarsenHgr) + coarsenHgr->hedgeNum, coarsenHgr->hedges + E_OFFSET(coarsenHgr));
    // TIMERSTOP(7)
    // dim3 block1(1, 128, 1);
    // dim3 grid1(UP_DIV(hgr->hedgeNum, block1.x), UP_DIV(block1.y, block1.y), 1);
    // int* d_newAdjListCounter;
    // CHECK_ERROR(cudaMallocManaged(&d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
    // TIMERSTART(8)
    constructCoarserAdjList<<<gridsize, blocksize>>>(hgr, coarsenHgr, hgr->hedgeNum + coarsenHgr->nodeNum);
    // fillNextLevelAdjacentListWithoutDuplicates2<<<grid1, block1>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->par_list1, hgr->hedgeNum, hgr->nodeNum, 
    //                                                     coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list,
    //                                                     coarsenHgr->nodeNum, coarsenHgr->hedgeNum, d_newAdjListCounter);
    TIMERSTOP(7)
    // std::cout << coarsenHgr->adj_list[coarsenHgr->hedges[12616 + E_OFFSET(coarsenHgr)] + 1] << "\n";
    // if (iter == 0) {
    //     std::string file = "../debug/testuvm_correct_level_result_" + std::to_string(iter) + ".txt";
    //     std::ofstream debug(file);
    //     for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
    //         std::sort(coarsenHgr->adj_list + coarsenHgr->hedges[E_OFFSET(coarsenHgr) + i], 
    //                   coarsenHgr->adj_list + coarsenHgr->hedges[E_OFFSET(coarsenHgr) + i] + coarsenHgr->hedges[E_DEGREE(coarsenHgr) + i]);
    //         for (int j = 0; j < coarsenHgr->hedges[i + E_DEGREE(coarsenHgr)]; ++j) {
    //             debug << coarsenHgr->adj_list[coarsenHgr->hedges[i + E_OFFSET(coarsenHgr)] + j] << " ";

    //         }
    //         debug << "\n";
    //     }
    //     debug.close();
    // }

    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr->par_list, coarsenHgr->totalEdgeDegree * sizeof(bool)));
    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr->par_list1, coarsenHgr->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMemset((void*)coarsenHgr->par_list1, 0, coarsenHgr->totalEdgeDegree * sizeof(unsigned)));
    // for (int j = 0; j < coarsenHgr->hedges[296 + E_DEGREE(coarsenHgr)]; ++j) {
    //     std::cout << coarsenHgr->adj_list[coarsenHgr->hedges[296 + E_OFFSET(coarsenHgr)] + j] << " ";
    // }
    // thrust::fill(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum, 0);
    std::cout << "\ntotalPinSize:" << coarsenHgr->totalEdgeDegree << ", totalNodeDegree: " << coarsenHgr->totalNodeDegree << "\n";
    std::cout << "minNodeWeight:" << coarsenHgr->minWeight << ", maxNodeWeight: " << coarsenHgr->maxWeight << "\n";
    std::cout << "minHedgeSize:" << coarsenHgr->minDegree << ", maxHedgeSize: " << coarsenHgr->maxDegree << "\n";
    coarsenHgr->totalWeight = hgr->totalWeight;
    time = time6 + time7;
#if 1
    // if (!optcfgs.runBaseline) { 
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr->incident_nets, coarsenHgr->totalNodeDegree * sizeof(unsigned int)));
    unsigned* newNetList;
    CHECK_ERROR(cudaMallocManaged(&newNetList, coarsenHgr->totalNodeDegree * sizeof(unsigned int)));
    int* netsListCounter;
    CHECK_ERROR(cudaMallocManaged(&netsListCounter, coarsenHgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)netsListCounter, 0, coarsenHgr->nodeNum * sizeof(int)));
    // TIMERSTART(fill)
    // thrust::fill(thrust::device, net_counts, net_counts + coarsenHgr->nodeNum, 0);
    // TIMERSTOP(fill)
    len_y = coarsenHgr->maxDegree < 500 ? coarsenHgr->maxDegree : coarsenHgr->maxDegree / 64;
    if (coarsenHgr->maxDegree < 500) {
        block.x = 32;
        block.y = 32;
    }
    grid = dim3(UP_DIV(coarsenHgr->hedgeNum, block.x), UP_DIV(len_y, block.y), 1);
    TIMERSTART(8)
    thrust::exclusive_scan(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), 
                    coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum, coarsenHgr->nodes+ N_OFFSET(coarsenHgr));
    constructIncidentNetLists<<<grid, block>>>(coarsenHgr, coarsenHgr->hedgeNum/*, net_counts*/);
    TIMERSTOP(8)
    time += time8;
    // }
    // gridsize = UP_DIV(hgr->nodeNum, blocksize);
    // TIMERSTART(9)
    // // testIncidentNetLists<<<hgr->nodeNum, blocksize>>>(hgr, coarsenHgr, newNetList, hgr->hedgeNum, hgr->nodeNum, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, netsListCounter);
    // testIncidentNetLists1<<<gridsize, blocksize>>>(hgr, coarsenHgr, newNetList, hgr->hedgeNum, hgr->nodeNum, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, netsListCounter);
    // TIMERSTOP(9)
    // std::ofstream debug("net_uvm_count_result.txt");
    // // for (int i = 0; i < coarsenHgr->nodeNum; ++i) {
    // //     debug << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + i] << ", " << netsListCounter[i] << "\n";
    // // }
    // for (int i = 0; i < hgr->nodeNum; ++i) {
    //     if (hgr->nodes[N_INBAG(hgr) + i]) {
    //         unsigned parent = hgr->nodes[N_PARENT(hgr) + i] - coarsenHgr->hedgeNum;
    //         debug << "hgr node:" << i << ": " << hgr->nodes[N_DEGREE(hgr) + i] << "; coarsen node:" 
    //               << parent << ": " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + parent] << "\n";
    //     }
    // }
    // std::cout << netsListCounter[0] << "\n";
#endif
#if 0
    coarsenHgr->maxVertDeg = *thrust::max_element(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), 
                                coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum);
    coarsenHgr->minVertDeg = *thrust::min_element(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), 
                                coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum);
    coarsenHgr->maxdeg_nodeIdx = thrust::max_element(thrust::device, coarsenHgr->nodes + N_DEGREE(coarsenHgr), 
                            coarsenHgr->nodes + N_DEGREE(coarsenHgr) + coarsenHgr->nodeNum) - (coarsenHgr->nodes + N_DEGREE(coarsenHgr));
    coarsenHgr->maxwt_nodeIdx = thrust::max_element(thrust::device, coarsenHgr->nodes + N_WEIGHT(coarsenHgr), 
                            coarsenHgr->nodes + N_WEIGHT(coarsenHgr) + coarsenHgr->nodeNum) - (coarsenHgr->nodes + N_WEIGHT(coarsenHgr));
    
    std::cout << "maxdeg node in fine hgr: " << hgr->maxdeg_nodeIdx << ", max degree: " << hgr->nodes[N_DEGREE(hgr) + hgr->maxdeg_nodeIdx] << "\n";
    std::cout << "maxweight node in fine hgr: " << hgr->maxwt_nodeIdx << ", max weight: " << hgr->nodes[N_WEIGHT(hgr) + hgr->maxwt_nodeIdx] << "\n";
    unsigned parent1 = hgr->nodes[N_PARENT(hgr) + hgr->maxdeg_nodeIdx] - coarsenHgr->hedgeNum;
    unsigned parent2 = hgr->nodes[N_PARENT(hgr) + hgr->maxwt_nodeIdx] - coarsenHgr->hedgeNum;
    std::cout << "parent1 of maxdeg node in fine hgr: " << parent1 << "\n";
    std::cout << "parent2 of maxweight node in fine hgr: " << parent2 << "\n";
    std::cout << "weight of parent1: " << coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + parent1] << "\n";
    std::cout << "weight of parent2: " << coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + parent2] << "\n";
    std::cout << "degree of parent1: " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + parent1] << "\n";
    std::cout << "degree of parent2: " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + parent2] << "\n";

    std::cout << "\nmaxWeight node index in coarse hgr: " << coarsenHgr->maxwt_nodeIdx << 
                 " with weight " << coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + coarsenHgr->maxwt_nodeIdx] << "\n";
    std::cout << "maxNodeWeight in coarse hgr:" << coarsenHgr->maxWeight << ", minNodeWeight:" << coarsenHgr->minWeight << "\n";
    unsigned maxfinenode = 0;
    int prev_maxwt = 0;
    int prev_nodenum = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[N_WEIGHT(hgr) + i] > prev_maxwt && hgr->nodes[N_PARENT(hgr) + i] - coarsenHgr->hedgeNum == coarsenHgr->maxwt_nodeIdx) {
            maxfinenode = i;
            prev_nodenum++;
        }
    }
    std::cout << "there are " << prev_nodenum << " vertices who are grouping into supervertex " << coarsenHgr->maxwt_nodeIdx << "\n";
    // std::cout << "hgr->nodes[N_PARENT(hgr) + maxfinenode] - coarsenHgr->hedgeNum = " << hgr->nodes[N_PARENT(hgr) + maxfinenode] - coarsenHgr->hedgeNum << "\n";
    std::cout << "corresponding maxweight node in fine hgr:" << maxfinenode << " with weight " << hgr->nodes[N_WEIGHT(hgr) + maxfinenode] << "\n";
    
    std::cout << "maxdegree node index in coarse hgr: " << coarsenHgr->maxdeg_nodeIdx << 
                 " with degree " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + coarsenHgr->maxdeg_nodeIdx] << "\n";
    std::cout << "maxNodeDegree in coarse hgr:" << coarsenHgr->maxVertDeg << ", minNodeDegree:" << coarsenHgr->minVertDeg << "\n";
    maxfinenode = 0;
    int prev_maxdeg = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[N_DEGREE(hgr) + i] > prev_maxdeg && hgr->nodes[N_PARENT(hgr) + i] - coarsenHgr->hedgeNum == coarsenHgr->maxdeg_nodeIdx) {
            maxfinenode = i;
        }
    }
    std::cout << "corresponding maxdeg node in fine hgr:" << maxfinenode << "\n";
    bool isfind = false;
    for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        for (int j = 0; j < coarsenHgr->hedges[i + E_DEGREE(coarsenHgr)]; ++j) {
            if (coarsenHgr->maxwt_nodeIdx == coarsenHgr->adj_list[coarsenHgr->hedges[i + E_OFFSET(coarsenHgr)] + j] - coarsenHgr->hedgeNum) {
                std::cout << "find " << coarsenHgr->maxwt_nodeIdx << "!!!\n";
                isfind = true;
                break;
            }
        }
        if (isfind == true) {
            break;
        }
    }
    
    std::cout << "\ndegree of maxweight node in coarse hgr: " << coarsenHgr->nodes[N_DEGREE(coarsenHgr) + coarsenHgr->maxwt_nodeIdx] << "\n";
#endif
    // time = time6 + time7 + time8;
}
