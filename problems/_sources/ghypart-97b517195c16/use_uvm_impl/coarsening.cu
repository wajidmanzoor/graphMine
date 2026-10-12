#include <iostream>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include "include/coarsening_impl.h"
#include "kernels/coarsening_kernels.cuh"
#include "include/construction_impl.h"

float construction = 0.f;
float cudamalloc = 0.f;

void printNodeMatchInfo(Hypergraph* hgr, int iter) {
    std::cout << "matching status of maxdegree node: " << hgr->nodes[hgr->maxdeg_nodeIdx + N_MATCHED(hgr)] << "\n";
    if (hgr->nodes[hgr->maxdeg_nodeIdx + N_MATCHED(hgr)]) {
        std::cout << "current parentID of max degree node " << hgr->maxdeg_nodeIdx << ": " << hgr->nodes[hgr->maxdeg_nodeIdx + N_PARENT(hgr)] - hgr->hedgeNum << "\n";
    }
    if (iter > 0) {
        std::cout << "matching status of maxweight node: " << hgr->nodes[hgr->maxwt_nodeIdx + N_MATCHED(hgr)] << "\n";
        if (hgr->nodes[hgr->maxwt_nodeIdx + N_MATCHED(hgr)]) {
            std::cout << "current parentID of maxweight node " << hgr->maxwt_nodeIdx << ": " << hgr->nodes[hgr->maxwt_nodeIdx + N_PARENT(hgr)] - hgr->hedgeNum << "\n";
        }
    }
}

// std::ofstream out("singleton_nodes_percentage.csv");

Hypergraph* coarsen(Hypergraph* hgr, int iter, int LIMIT, float& time, OptionConfigs& optcfgs) {
    std::string file = "debug_" + optcfgs.filename;
    std::ofstream debug(file);
    Hypergraph* coarsenHgr;
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr, sizeof(Hypergraph)));
    coarsenHgr->nodeNum = 0;
    coarsenHgr->hedgeNum = 0;
    coarsenHgr->graphSize = 0;
    // unsigned int memBytes = sizeof(Hypergraph);
    // first start hashing for hedges in parallel
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
    std::cout << "hedgeNum: " << hgr->hedgeNum << ", nodeNum: " << hgr->nodeNum << "\n";
    // for (int i = 0; i < hgr->bit_length * hgr->num_hedges; ++i) {
    //     std::cout << "i:" << i << " ";
    //     int cur_bit = hgr->bitset[i];
    // }
    TIMERSTART(0)
    hedgePrioritySetting<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, optcfgs.matching_policy);
    multiNodeMatchingI<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
    multiNodeMatchingII<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
    multiNodeMatchingIII<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
    TIMERSTOP(0)
    // if (iter == 1) {
    //     std::string file1 = "../debug/test_kernel123_correct_level_hedgelist_" + std::to_string(iter) + ".txt";
    //     std::ofstream debug1(file1);
    //     for (int i = 0; i < E_LENGTH1(hgr->hedgeNum); ++i) {
    //         if (i / hgr->hedgeNum == 6) {
    //             debug1 << "E_MATCHED: ";
    //         }
    //         if (i / hgr->hedgeNum == 7) {
    //             debug1 << "E_INBAG: ";
    //         }
    //         debug1 << hgr->hedges[i] << "\n";
    //     }
    //     std::string file2 = "../debug/test_kernel123_correct_level_nodelist_" + std::to_string(iter) + ".txt";
    //     std::ofstream debug2(file2);
    //     for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
    //         if (i / hgr->nodeNum == 6) {
    //             debug2 << "N_MATCHED: ";
    //         }
    //         if (i / hgr->nodeNum == 13) {
    //             debug2 << "N_INBAG: ";
    //         }
    //         if (i / hgr->nodeNum == 11) {
    //             debug2 << "N_PARENT: ";
    //         }
    //         if (i / hgr->nodeNum == 3) {
    //             debug2 << "N_OFFSET: ";
    //         }
    //         debug2 << hgr->nodes[i] << "\n";
    //     }
    // }
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     debug << nodeid << ": " << hgr->nodes[N_WEIGHT(hgr) + nodeid] << ", " << hgr->nodes[N_TMPW(hgr) + nodeid] << "\n";
    // }
    // int unmatchedNodes = 0;
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     if (!hgr->nodes[nodeid + N_MATCHED(hgr)]) {
    //         unmatchedNodes++;
    //     }
    // }
    // std::cout << "At the beginning, current # of unmatched nodes: " << unmatchedNodes << "\n";

    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", isMatched: " << hgr->hedges[i + E_MATCHED(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //     }
    //     debug << "\n";
    // }
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", priority: " << hgr->hedges[i + E_PRIORITY(hgr)] << ", rand: " << hgr->hedges[i + E_RAND(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << 
    //     }
    // }
    // if (iter > 0)   LIMIT = hgr->maxWeight;
    TIMERSTART(1)
    // createNodePhaseI<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, LIMIT, coarsenHgr, iter);
    createNodePhaseI<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, optcfgs.coarseI_weight_limit, coarsenHgr, iter);
    TIMERSTOP(1)
    // std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", isMatched: " << hgr->hedges[i + E_MATCHED(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //     }
    //     debug << "\n";
    // }

    // if (iter == 1) {
    //     std::string file1 = "../debug/test_kernel4_correct_level_hedgelist_" + std::to_string(iter) + ".txt";
    //     std::ofstream debug1(file1);
    //     for (int i = 0; i < E_LENGTH1(hgr->hedgeNum); ++i) {
    //         if (i / hgr->hedgeNum == 6) {
    //             debug1 << "E_MATCHED: ";
    //         }
    //         if (i / hgr->hedgeNum == 7) {
    //             debug1 << "E_INBAG: ";
    //         }
    //         debug1 << hgr->hedges[i] << "\n";
    //     }
    //     std::cout << hgr->hedges[96779] << "\n";
    //     std::string file2 = "../debug/test_kernel4_correct_level_nodelist_" + std::to_string(iter) + ".txt";
    //     std::ofstream debug2(file2);
    //     for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
    //         if (i / hgr->nodeNum == 6) {
    //             debug2 << "N_MATCHED: ";
    //         }
    //         if (i / hgr->nodeNum == 13) {
    //             debug2 << "N_INBAG: ";
    //         }
    //         if (i / hgr->nodeNum == 11) {
    //             debug2 << "N_PARENT: ";
    //         }
    //         if (i / hgr->nodeNum == 3) {
    //             debug2 << "N_OFFSET: ";
    //         }
    //         debug2 << hgr->nodes[i] << "\n";
    //     }
    // }
    // printNodeMatchInfo(hgr, iter);
    // std::cout << "After coarsenI, current # of unmatched nodes: " << unmatchedNodes << "\n";
    std::cout << "Current coarsen->nodeNum: " << coarsenHgr->nodeNum << "\n";
    std::cout << "Current coarsen->hedgeNum: " << coarsenHgr->hedgeNum << "\n";

    int limit = LIMIT;//INT_MAX;//optcfgs.coarseMore_weight_limit;//
    // int *tmp_bag;
    // CHECK_ERROR(cudaMallocManaged(&tmp_bag, hgr->nodeNum * sizeof(int)));
    // TIMERSTART(bag)
    // thrust::fill(thrust::device, tmp_bag, tmp_bag + hgr->nodeNum, 0);
    // TIMERSTOP(bag)
    // unsigned* count;
    // CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
    // count[0] = 0;
    // int gridsize1 = UP_DIV(hgr->nodeNum, blocksize);
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     debug << nodeid << ": " << hgr->nodes[N_WEIGHT(hgr) + nodeid] << ", " << hgr->nodes[N_TMPW(hgr) + nodeid] << "\n";
    // }
    TIMERSTART(2)
    ResetPrioForUpdateUnmatchNodes<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
    // coarseMoreNodes<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, iter, limit);
    coarseMoreNodes<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, iter, optcfgs.coarseMore_weight_limit);
    TIMERSTOP(2)
    // std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    // std::ofstream debug("debug.txt");
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     debug << nodeid << ": " << hgr->nodes[N_WEIGHT(hgr) + nodeid] << ", " << hgr->nodes[N_TMPW(hgr) + nodeid] << "\n";
    // }
    // max_weight = *thrust::max_element(thrust::device, hgr->nodes + N_TMPW(hgr), hgr->nodes + N_TMPW(hgr) + hgr->nodeNum);
    // std::cout << "current max_weight: " << max_weight << "\n";
    // for (int i = 0; i < hgr->nodeNum; ++i) {
    //     if (hgr->nodes[N_TMPBAG(hgr) + i] == 1) {
    //         unsigned parent = hgr->nodes[N_PARENT(hgr) + i];
    //         unsigned tmpW = hgr->nodes[parent-hgr->hedgeNum + N_TMPW(hgr)];
    //         if (hgr->nodes[N_WEIGHT(hgr) + i] + tmpW <= optcfgs.coarseMore_weight_limit) {
    //             hgr->nodes[parent-hgr->hedgeNum + N_TMPW(hgr)] += hgr->nodes[N_WEIGHT(hgr) + i];
    //         } else {
    //             hgr->nodes[N_MATCHED(hgr) + i] = 0;
    //             hgr->nodes[N_TMPBAG(hgr) + i] = 0;
    //         }
    //     }
    // }

    // std::cout << "bag size: " << count[0] << "\n";
    // int real_num = 0;
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     // if (tmp_bag[nodeid]) {
    //     if (hgr->nodes[N_TMPBAG(hgr) + nodeid]) {
    //         real_num++;
    //         hgr->nodes[N_TMPW(hgr) + hgr->nodes[nodeid + N_PARENT(hgr)] - hgr->hedgeNum] += hgr->nodes[N_WEIGHT(hgr) + nodeid];
    //     }
    // }
    
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     if (tmp_bag[nodeid]) {
    //         real_num++;
    //         debug << nodeid << ": " << hgr->nodes[N_WEIGHT(hgr) + nodeid] << ", " << hgr->nodes[N_TMPW(hgr) + nodeid] << "\n";
    //     }
    //     // debug << nodeid << ": " << hgr->nodes[N_WEIGHT(hgr) + nodeid] << ", " << hgr->nodes[N_TMPW(hgr) + nodeid] << "\n";
    // }
    // std::cout << "real num: " << real_num << "\n";
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", isMatched: " << hgr->hedges[i + E_MATCHED(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //     }
    //     debug << "\n";
    // }

    // unmatchedNodes = 0;
    // maxparentweight = 0;
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     if (!hgr->nodes[nodeid + N_MATCHED(hgr)]) {
    //         unmatchedNodes++;
    //     } 
    //     else {
    //         maxparentweight = std::max(maxparentweight, 
    //             hgr->nodes[hgr->nodes[nodeid + N_PARENT(hgr)] - hgr->hedgeNum + N_TMPW(hgr)]);
    //     }
    // }
    // std::cout << "maxparentweight: " << maxparentweight << "\n";
    // printNodeMatchInfo(hgr, iter);
    // std::cout << "After coarseMore, current # of unmatched nodes: " << unmatchedNodes << "\n";
    // std::cout << "Current coarsen->nodeNum: " << coarsenHgr->nodeNum << "\n";

    TIMERSTART(3)
    coarsenPhaseII<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum, coarsenHgr);
    TIMERSTOP(3)
    // std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    // unmatchedNodes = 0;
    // maxparentweight = 0;
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     if (!hgr->nodes[nodeid + N_MATCHED(hgr)]) {
    //         unmatchedNodes++;
    //     }
    //     else {
    //         maxparentweight = std::max(maxparentweight, 
    //             hgr->nodes[hgr->nodes[nodeid + N_PARENT(hgr)] - hgr->hedgeNum + N_TMPW(hgr)]);
    //     }
    // }
    // std::cout << "maxparentweight: " << maxparentweight << "\n";
    // printNodeMatchInfo(hgr, iter);
    // std::cout << "After coarseII, current # of unmatched nodes: " << unmatchedNodes << "\n";
    
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", isMatched: " << hgr->hedges[i + E_MATCHED(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //     }
    //     debug << "\n";
    // }

    gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(4)
    noedgeNodeMatching<<<gridsize, blocksize>>>(hgr, hgr->nodeNum, coarsenHgr);
    // noedgeNodeMatching<<<gridsize, blocksize>>>(hgr, hgr->nodeNum, coarsenHgr, tmp_bag);
    TIMERSTOP(4)
    // std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    // if (iter == 1) {
    //     std::ofstream debug("../debug/coarsen_finish1.txt");
    //     for (int i = 0; i < E_LENGTH(hgr); ++i) {
    //         debug << hgr->hedges[i] << "\n";
    //     }
    //     debug << "================\n";
    //     for (int i = 0; i < N_LENGTH(hgr); ++i) {
    //         debug << hgr->nodes[i] << "\n";
    //     }
    // }
    // unmatchedNodes = 0;
    // maxparentweight = 0;
    // for (unsigned nodeid = 0; nodeid < hgr->nodeNum; ++nodeid) {
    //     if (!hgr->nodes[nodeid + N_MATCHED(hgr)]) {
    //         unmatchedNodes++;
    //     } else {
    //         maxparentweight = std::max(maxparentweight, 
    //             hgr->nodes[hgr->nodes[nodeid + N_PARENT(hgr)] - hgr->hedgeNum + N_TMPW(hgr)]);
    //     }
    // }
    // max_weight = *thrust::max_element(thrust::device, hgr->nodes + N_TMPW(hgr), hgr->nodes + N_TMPW(hgr) + hgr->nodeNum);
    // std::cout << "current max_weight: " << max_weight << "\n";
    // std::cout << "maxparentweight: " << maxparentweight << "\n";
    // printNodeMatchInfo(hgr, iter);
    // std::cout << "Current # of unmatched nodes: " << unmatchedNodes << "\n";
    
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", isMatched: " << hgr->hedges[i + E_MATCHED(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //                     << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //     }
    //     debug << "\n";
    // }
    // for (int i = 0; i < hgr->bit_length * hgr->num_hedges; ++i) {
    //     std::cout << "i:" << i << " ";
    //     int cur_bit = hgr->bitset[i];
    // }
    coarsenHgr->graphSize = coarsenHgr->hedgeNum + coarsenHgr->nodeNum;
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr->nodes, N_LENGTH(coarsenHgr) * sizeof(int)));
    CHECK_ERROR(cudaMallocManaged(&coarsenHgr->hedges, E_LENGTH(coarsenHgr) * sizeof(int)));
    coarsenHgr->num_hedges = coarsenHgr->hedgeNum;//10000;//50000;
    coarsenHgr->bit_length = UP_DIV(coarsenHgr->nodeNum, 32);
    // CHECK_ERROR(cudaMallocManaged(&coarsenHgr->bitset, coarsenHgr->bit_length * coarsenHgr->num_hedges * sizeof(unsigned))); // hnodeN bits
    // CHECK_ERROR(cudaMemset((void*)coarsenHgr->bitset, 0, coarsenHgr->bit_length * coarsenHgr->num_hedges * sizeof(unsigned)));
    // thrust::exclusive_scan(thrust::device, hgr->hedges + E_INBAG(hgr), hgr->hedges + E_INBAG(hgr) + hgr->hedgeNum, hgr->hedges + E_NEXTID(hgr));
    // thrust::exclusive_scan(thrust::device, hgr->nodes + N_INBAG(hgr), hgr->nodes + N_INBAG(hgr) + hgr->nodeNum,
    //                         hgr->nodes + N_MAP_PARENT(hgr), coarsenHgr->hedgeNum);
    // if (iter == 1) {
    //     std::ofstream debug("../debug/coarsen_node_mapping1.txt");
    //     for (int i = 0; i < N_LENGTH(hgr); ++i) {
    //         debug << hgr->nodes[i] << "\n";
    //     }
    // }
    int edgesInBag = 0;
    for (int i = 0; i < hgr->hedgeNum; ++i) {
        if (hgr->hedges[E_INBAG(hgr) + i]) {
            edgesInBag++;
        }
    }
    int nodesInBag = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[N_INBAG(hgr) + i]) {
            nodesInBag++;
        }
    }
    std::cout << "InBag: hedges:" << edgesInBag << ", nodes:" << nodesInBag << "\n";
    TIMERSTART(5)
    thrust::exclusive_scan(thrust::device, hgr->hedges + E_INBAG(hgr), hgr->hedges + E_INBAG(hgr) + hgr->hedgeNum, hgr->hedges + E_NEXTID(hgr));
    thrust::exclusive_scan(thrust::device, hgr->nodes + N_INBAG(hgr), hgr->nodes + N_INBAG(hgr) + hgr->nodeNum,
                            hgr->nodes + N_MAP_PARENT(hgr), coarsenHgr->hedgeNum);
    createNodeMapping<<<gridsize, blocksize>>>(hgr, hgr->nodeNum, coarsenHgr);
    updateSuperVertexId<<<gridsize, blocksize>>>(hgr, hgr->nodeNum);
    TIMERSTOP(5)
    // if (iter == 0) {
    //     std::ofstream debug("../debug/coarsen_node_mapping1.txt");
    //     // for (int i = 0; i < E_LENGTH(hgr); ++i) {
    //     //     debug << hgr->hedges[i] << "\n";
    //     // }
    //     // debug << "================\n";
    //     // for (int i = 0; i < N_LENGTH(hgr); ++i) {
    //     //     debug << hgr->nodes[i] << "\n";
    //     // }
    //     for (int i = 0; i < N_LENGTH(coarsenHgr); ++i) {
    //         debug << coarsenHgr->nodes[i] << "\n";
    //     }
    // }
    // std::cout << "current parentID of max degree node " << hgr->maxdeg_nodeIdx << ": " << hgr->nodes[hgr->maxdeg_nodeIdx + N_PARENT(hgr)] - coarsenHgr->hedgeNum << "\n";
    // std::cout << "current parentID of maxweight node " << hgr->maxwt_nodeIdx << ": " << hgr->nodes[hgr->maxwt_nodeIdx + N_PARENT(hgr)] - coarsenHgr->hedgeNum << "\n";
    // maxparentweight = 0;
    // for (int i = 0; i < hgr->nodeNum; ++i) {
    //     unsigned parent = hgr->nodes[i + N_PARENT(hgr)];
    //     maxparentweight = std::max(maxparentweight, coarsenHgr->nodes[parent - coarsenHgr->hedgeNum + N_TMPW(coarsenHgr)]);
    // }
    // std::cout << "maxparentweight: " << maxparentweight << "\n";
    
    // for (int i = 0; i < hgr->hedgeNum; ++i) {
    //     debug << "hedge: " << i << ", idNum: " << hgr->hedges[i + E_IDNUM(hgr)] << ", inBag: " << hgr->hedges[i + E_INBAG(hgr)] << ", E_NEXTID: " << hgr->hedges[i + E_NEXTID(hgr)] << "\n";
    //     for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
    //         // debug << "node: " << hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] << "'s parent is: " 
    //         //             << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << ", hedgeID: "
    //         //             << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_HEDGEID(hgr)] << "\n";
    //         debug << hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARENT(hgr)] << " ";
    //     }
    //     debug << "\n";
    // }

    float construct_time = 0.f;
    constructHgr(hgr, coarsenHgr, construct_time, iter, optcfgs);
    float gpu_time = (time0 + time1 + time2 + time3 + time4 + time5 + construct_time) / 1000.f;
    float cur_time = gpu_time;// + cpu_time;
    time += cur_time;
    // if (iter == 0) {
        // std::string file = "../debug/testuvm_correct_level_result_" + std::to_string(iter) + ".txt";
        // std::ofstream debug(file);
        // // for (int i = 0; i < coarsenHgr->totalEdgeDegree; ++i) {
        // //     debug << coarsenHgr->adj_list[i] << "\n";
        // // }
        // for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        //     // std::sort(coarsenHgr->adj_list + coarsenHgr->hedges[E_OFFSET(coarsenHgr) + i], 
        //     //           coarsenHgr->adj_list + coarsenHgr->hedges[E_OFFSET(coarsenHgr) + i] + coarsenHgr->hedges[E_DEGREE(coarsenHgr) + i]);
        //     for (int j = 0; j < coarsenHgr->hedges[i + E_DEGREE(hgr)]; ++j) {
        //         debug << coarsenHgr->adj_list[coarsenHgr->hedges[i + E_OFFSET(coarsenHgr)] + j] << " ";
        //     }
        //     debug << "\n";
        // }
        // debug.close();
        // // std::ofstream debug1("../debug/coarsen_parent_list1.txt");
        // // for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
        // //     debug1 << hgr->par_list[i] << "\n";
        // // }
        // std::string file1 = "../debug/test_correct_level_hedgelist_" + std::to_string(iter) + ".txt";
        // std::ofstream debug2(file1);
        // for (int i = 0; i < E_LENGTH(coarsenHgr); ++i) {
        //     debug2 << coarsenHgr->hedges[i] << "\n";
        // }
        // std::string file2 = "../debug/test_correct_level_nodelist_" + std::to_string(iter) + ".txt";
        // std::ofstream debug3(file2);
        // for (int i = 0; i < N_LENGTH(coarsenHgr); ++i) {
        //     debug3 << coarsenHgr->nodes[i] << "\n";
        // }
        // std::ofstream debug("../debug/validate_pin_list1.txt");
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (hgr->hedges[i + E_INBAG(hgr)]) {
        //         debug << hgr->hedges[i + E_NEXTID(hgr)] << ": " << i << "\n";
        //     }
        // }
        // std::ofstream debug("../test/test_pin_list.txt");
        // for (int i = 0; i < hgr->hedgeNum; ++i) {
        //     if (hgr->hedges[i + E_INBAG(hgr)]) {
        //         // debug << hgr->hedges[i + E_DEGREE(hgr)] << "\n";
        //         for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
        //             unsigned pid = hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARENT(hgr)];
        //             debug << pid - coarsenHgr->hedgeNum;
        //             if (j < hgr->hedges[i + E_DEGREE(hgr)] - 1) debug << " ";
        //         }
        //         debug << "\n";
        //     }
        // }
        // std::ofstream debug1("../test/final_deduplicate_results.txt");
        // std::ofstream debug2("../test/final_coarse_hedgesize_results.txt");
        // for (int i = 0; i < coarsenHgr->hedgeNum; ++i) {
        //     debug2 << coarsenHgr->hedges[i + E_DEGREE(coarsenHgr)] << "\n";
        //     for (int j = 0; j < coarsenHgr->hedges[i + E_DEGREE(coarsenHgr)]; ++j) {
        //         debug1 << coarsenHgr->adj_list[coarsenHgr->hedges[i + E_OFFSET(coarsenHgr)] + j] - coarsenHgr->hedgeNum << " ";
        //     }
        //     debug1 << "\n";
        // }
    // }
    // if (iter == 0) {
        // std::string file = "../debug/coarsen_level_mapping" + std::to_string(iter) + ".txt";
        // std::ofstream out(file);
        // for (int i = 0; i < hgr->nodeNum; ++i) {
        //     unsigned parent = hgr->nodes[N_PARENT(hgr) + i];
        //     out << "fineGraph nodes:" << hgr->nodes[N_ELEMID(hgr) + i] << "(" << hgr->nodes[N_WEIGHT(hgr) + i] << ") mapping to coarsenGraph supervertex: "
        //         << parent << "(" << coarsenHgr->nodes[N_WEIGHT(coarsenHgr) + parent - coarsenHgr->hedgeNum] << ")\n";
        // }
        // std::ofstream debug("../debug/coarsen_level_results1.txt");
        // for (int i = 0; i < coarsenHgr->totalEdgeDegree; ++i) {
        //     debug << coarsenHgr->adj_list[i] << "\n";
        // }
    // }
    // debug.close();
    std::cout << "new hedgeNum: " << coarsenHgr->hedgeNum << ", new nodeNum: " << coarsenHgr->nodeNum << std::endl;
    std::cout << "iteration " << iter << "'s total time:" << cur_time << " s.\n";
    // CHECK_ERROR(cudaFree(tmp_bag));
    // CHECK_ERROR(cudaFree(count));

    return coarsenHgr;
}
