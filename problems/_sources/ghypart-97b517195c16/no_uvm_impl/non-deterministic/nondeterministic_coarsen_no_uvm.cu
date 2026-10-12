#include <iostream>
#include <chrono>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include <thrust/sort.h>
#include <cub/cub.cuh>
#include <cub/device/device_segmented_sort.cuh>
#include <cub/device/device_segmented_reduce.cuh>
#include <cub/device/device_scan.cuh>
#include "../use_no_uvm.cuh"
#include "../coarsen_no_uvm_kernels.cuh"
#include "nondeterministic_coarsen_no_uvm_kernels.cuh"

Hypergraph* non_det_coarsen_no_uvm(Hypergraph* hgr, int iter, int LIMIT, float& time, float& other_time, OptionConfigs& optcfgs, 
                            unsigned long& memBytes, std::vector<std::pair<std::string, float>>& perfs, Auxillary* aux) {
    std::cout << __FUNCTION__ << "..." << iter << "\n";
    Hypergraph* coarsenHgr;
    coarsenHgr = (Hypergraph*)malloc(sizeof(Hypergraph));
    coarsenHgr->nodeNum = 0;
    coarsenHgr->hedgeNum = 0;
    coarsenHgr->graphSize = 0;
    std::cout << "current allocated gpu memory:" << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";

    allocTempData(aux, hgr);
    
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
    std::cout << "hedgeNum: " << hgr->hedgeNum << ", nodeNum: " << hgr->nodeNum << "\n";

    TIMERSTART(0)
    setHyperedgePriority<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, optcfgs.matching_policy, aux->eRand, aux->ePriori);
    TIMERSTOP(0)
    time += time0 / 1000.f;

    int num_blocks = UP_DIV(hgr->totalEdgeDegree, blocksize);
    if (!optcfgs.useNewKernel1_2_3) {
        TIMERSTART(1)
        assignPriorityToNodeND1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->ePriori, aux->nPriori);
        TIMERSTOP(1)

        // TIMERSTART(2)
        // assignHashHedgeIdToNodeND1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // TIMERSTOP(2)

        // TIMERSTART(3)
        // assignNodeToIncidentHedgeND1<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->nodeNum, hgr->hedgeNum, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // TIMERSTOP(3)
        // perfs[1].second += time1;
        // perfs[2].second += time2;
        // perfs[3].second += time3;
        // time += (time1 + time2 + time3) / 1000.f;
        // std::cout << "non_det parallel matching policy time:" << time1 + time2 + time3 << "\n";
    } else {
        TIMERSTART(1)
        assignPriorityToNodeND<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->ePriori, aux->nPriori);
        TIMERSTOP(1)

        // TIMERSTART(2)
        // assignHashHedgeIdToNodeND<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->ePriori, aux->nPriori, aux->nRand);
        // TIMERSTOP(2)

        // TIMERSTART(3)
        // assignNodeToIncidentHedgeND<<<num_blocks, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->pins_hedgeid_list, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, aux->eRand, aux->nRand, aux->nMatchHedgeId);
        // TIMERSTOP(3)
        // perfs[1].second += time1;
        // perfs[2].second += time2;
        // perfs[3].second += time3;
        // time += (time1 + time2 + time3) / 1000.f;
        // std::cout << "non_det parallel matching policy time:" << time1 + time2 + time3 << "\n";
    }
#if 0
    TIMERSTART(4)
    mergeNodesInsideHyperedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, optcfgs.coarseI_weight_limit, aux->d_edgeCnt, aux->d_nodeCnt, iter, 
                        aux->eInBag, aux->eMatch, aux->nInBag, aux->tmpW, aux->nMatch, aux->canBeCandidates, aux->nMatchHedgeId);
    TIMERSTOP(4)
    time += time4 / 1000.f;
    perfs[4].second += time4;

    TIMERSTART(5)
    PrepareForFurtherMatching<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, aux->eMatch, aux->nMatch, aux->nPriori);
    TIMERSTOP(5)
    time += time5 / 1000.f;

    TIMERSTART(6)
        mergeMoreNodesAcrossHyperedges<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, iter, optcfgs.coarseMore_weight_limit, 
                                                                aux->eMatch, aux->nInBag1, aux->tmpW, aux->nMatch, aux->canBeCandidates1, aux->nPriori, aux->nMatchHedgeId);
    TIMERSTOP(6)
    time += time6 / 1000.f;
    perfs[6].second += time6;


    TIMERSTART(7)
    countingHyperedgesRetainInCoarserLevel<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, aux->d_edgeCnt, aux->eInBag, aux->eMatch, aux->nMatch);
    TIMERSTOP(7)

    gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(8)
    selfMergeSingletonNodes<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, aux->d_nodeCnt, aux->nInBag1, aux->nInBag, aux->tmpW, aux->nMatch, aux->nMatchHedgeId);
    TIMERSTOP(8)

    TIMERSTART(others1)
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->nodeNum, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->hedgeNum, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->nodes, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->hedges, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)coarsenHgr->nodes, 0, N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)coarsenHgr->hedges, 0, E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int)));
    TIMERSTOP(others1)

    TIMERSTART(9)
    thrust::exclusive_scan(thrust::device, aux->eInBag, aux->eInBag + hgr->hedgeNum, aux->eNextId);
    thrust::exclusive_scan(thrust::device, aux->nInBag, aux->nInBag + hgr->nodeNum, aux->nNextId, coarsenHgr->hedgeNum);
    TIMERSTOP(9)

    TIMERSTART(10)
    setupNodeMapping<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, 
                            coarsenHgr->nodes, coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->nInBag, aux->nNextId, aux->tmpW, aux->tmpW1);
    TIMERSTOP(10)

    TIMERSTART(11)
    updateCoarsenNodeId<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, aux->nNextId);
    TIMERSTOP(11)

    time += (time7 + time8 + time9 + time10 + time11) / 1000.f;


    int num_hedges = 10000;
    int bit_length = UP_DIV(coarsenHgr->nodeNum, 32);
    int blocksize0 = 128;
    int gridsize0 = num_hedges;//hgr->hedgeNum;
    TIMERSTART(1_2)
    std::cout << "bitset memory consumption: " << (bit_length * 1UL * num_hedges * sizeof(unsigned)) / (1024.f * 1024.f * 1024.f) << " GB.\n";
    CHECK_ERROR(cudaMalloc((void**)&aux->bitset, bit_length * num_hedges * sizeof(unsigned))); // hnodeN bits
    CHECK_ERROR(cudaMemset((void*)aux->bitset, 0, bit_length * num_hedges * sizeof(unsigned)));

    markDuplicasInNextLevelAdjacentList_3<<<gridsize0, blocksize0>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum, aux->eNextId, aux->eInBag,
                                                            coarsenHgr->hedges, coarsenHgr->hedgeNum, aux->bitset, bit_length, num_hedges, aux->d_totalPinSize);
    CHECK_ERROR(cudaFree(aux->bitset));
    TIMERSTOP(1_2)
    time += time1_2 / 1000.f;
    perfs[12].second += time1_2;

    TIMERSTART(others2)
    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->totalEdgeDegree, aux->d_totalPinSize, sizeof(int), cudaMemcpyDeviceToHost));
    CHECK_ERROR(cudaMalloc((void**)&coarsenHgr->adj_list, coarsenHgr->totalEdgeDegree * sizeof(unsigned int)));
    CHECK_ERROR(cudaMemset((void*)aux->pins_hedgeid_list, 0, hgr->totalEdgeDegree * sizeof(unsigned)));
    TIMERSTOP(others2)

    TIMERSTART(13)
    thrust::exclusive_scan(thrust::device, coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum), 
                            coarsenHgr->hedges + E_DEGREE1(coarsenHgr->hedgeNum) + coarsenHgr->hedgeNum, 
                            coarsenHgr->hedges + E_OFFSET1(coarsenHgr->hedgeNum));
    TIMERSTOP(13)
    time += time13 / 1000.f;

    int* d_newAdjListCounter;
    CHECK_ERROR(cudaMalloc((void**)&d_newAdjListCounter, coarsenHgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)d_newAdjListCounter, 0, coarsenHgr->hedgeNum * sizeof(int)));
    blocksize = 128;
    gridsize = hgr->hedgeNum;//num_hedges;//
    TIMERSTART(1_4)
    fillNextLevelAdjacentListWithoutDuplicates2<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, aux->isDuplica, hgr->hedgeNum, hgr->nodeNum,
                                                    coarsenHgr->hedges, coarsenHgr->nodes, coarsenHgr->adj_list, aux->pins_hedgeid_list, aux->eNextId, aux->eInBag,
                                                    coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_totalNodeDeg, aux->d_maxPinSize, aux->d_minPinSize, d_newAdjListCounter);
    TIMERSTOP(1_4)

    gridsize = UP_DIV(coarsenHgr->nodeNum, blocksize);
    TIMERSTART(15)
    setCoarsenNodesProperties<<<gridsize, blocksize>>>(coarsenHgr->nodes, coarsenHgr->nodeNum, coarsenHgr->hedgeNum, aux->d_maxWeight, aux->d_minWeight, aux->tmpW1);
    TIMERSTOP(15)
    CHECK_ERROR(cudaFree(d_newAdjListCounter));
    time += (time1_4 + time15) / 1000.f;
    perfs[14].second += time1_4;
    perfs[15].second += time15;

    CHECK_ERROR(cudaMemcpy((void *)&coarsenHgr->totalNodeDegree, aux->d_totalNodeDeg, sizeof(int), cudaMemcpyDeviceToHost));
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
    std::cout << "current level cuda malloc && memcpy time: " << (timeothers1 + timeothers2) / 1000.f << " s.\n";

    std::cout << "current level cuda kernel time: " << time << " s.\n";
    other_time += (timeothers1 + timeothers2) / 1000.f;
    unsigned long curr_bytes = E_LENGTH1(coarsenHgr->hedgeNum) * sizeof(int) + N_LENGTH1(coarsenHgr->nodeNum) * sizeof(int) + 1 * coarsenHgr->totalEdgeDegree * sizeof(unsigned);
    memBytes += curr_bytes;
    std::cout << "current iteration accumulate memory space: " << curr_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";

    perfs[0].second += time0;
    perfs[5].second += time5;
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
#endif
    deallocTempData(aux);
    return coarsenHgr;
}