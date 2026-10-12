#include <iostream>
#include <chrono>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include "use_no_uvm.cuh"
#include "partition_no_uvm_kernels.cuh"

void init_partition_no_uvm(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time, float& other_time, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    // int* d_p0_num, *d_p1_num;
    // CHECK_ERROR(cudaMalloc((void**)&d_p0_num, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMalloc((void**)&d_p1_num, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&d_p0_num, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&d_p1_num, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)d_p0_num, 0, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)d_p1_num, 0, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMalloc((void**)&hgr->adj_part_list, hgr->totalEdgeDegree * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)hgr->adj_part_list, 0, hgr->totalEdgeDegree * sizeof(int)));
    unsigned* zeroPartWeight;
    CHECK_ERROR(cudaMallocManaged(&zeroPartWeight, sizeof(unsigned)));
    // CHECK_ERROR(cudaMemset((void*)zeroPartWeight, 0, sizeof(unsigned)));
    zeroPartWeight[0] = 0;
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(0)
    setupInitPartition<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroPartWeight);
    // setupInitPartition1<<<UP_DIV(hgr->nodeNum + hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, zeroPartWeight, hgr->hedges, hgr->hedgeNum,
    //                             hgr->totalEdgeDegree, hgr->adj_list, hgr->pins_hedgeid_list, hgr->adj_part_list, d_p0_num, d_p1_num);
    TIMERSTOP(0)
    // GET_LAST_ERR();
    // int* hedge_id = (int*)malloc(hgr->totalEdgeDegree * sizeof(int));
    // CHECK_ERROR(cudaMemcpy((void *)hedge_id, hgr->pins_hedgeid_list, hgr->totalEdgeDegree * sizeof(int), cudaMemcpyDeviceToHost));
    // std::ofstream debug("hedge_id.txt");
    // for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
    //     debug << hedge_id[i] << "\n";
    // }

    int total = hgr->totalWeight;
    int nonzeroPartWeight = total - zeroPartWeight[0];
    unsigned kvalue        = (K + 1) / 2;
    unsigned targetWeight0 = total * kvalue / K;
    unsigned targetWeight1 = total - targetWeight0;
    std::cout << "totalweight:" << hgr->totalWeight << ", part0_weight:" << zeroPartWeight[0] << ", part1_weight:" << nonzeroPartWeight << "\n";
    std::cout << "targetWeight0:" << targetWeight0 << ", targetWeight1:" << targetWeight1 << "\n";
    tmpNode_nouvm* nodeListz;
    CHECK_ERROR(cudaMalloc((void**)&nodeListz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    tmpNode_nouvm* nodeListnz;
    CHECK_ERROR(cudaMalloc((void**)&nodeListnz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    if (static_cast<long>(zeroPartWeight[0]) > nonzeroPartWeight) {
        std::cout << "enter move 0 to 1 branch\n";
        int* gain;
        CHECK_ERROR(cudaMallocManaged(&gain, sizeof(int)));
        gain[0] = nonzeroPartWeight;
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        unsigned* processed;
        CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
        // tmpNode* nodeListz;
        // CHECK_ERROR(cudaMalloc((void**)&nodeListz, hgr->nodeNum * sizeof(tmpNode)));
        // int iter = 0;
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0); // memset FS and TE as 0
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            // init_move_gain1<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, 
            //                         hgr->pins_hedgeid_list, hgr->adj_part_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num, hgr->hedges);
            // init_move_gain1<<<gridsize, blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, 
            //                         hgr->pins_hedgeid_list, hgr->adj_part_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num, hgr->hedges);
            TIMERSTOP(1)
            // if (iter == 0) {
            //     std::ofstream debug("part_num1.txt");
            //     for (int i = 0; i < hgr->hedgeNum;++i) {
            //         debug << d_p0_num[i] << " " << d_p1_num[i] << "\n";
            //     }
            // }

            count[0] = 0;
            processed[0] = 0;
            CHECK_ERROR(cudaMemset(nodeListz, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(2)
            createPotentialNodeList<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodeListz, count, partID);
            TIMERSTOP(2)
            std::cout << count[0] << "\n";

            TIMERSTART(3)
            if (optcfgs.testDeterminism) {
                use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW_non_det()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW1_non_det());
            } else {
            use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW_f()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW1_f());
            // use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], mycmp()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], mycmp1());
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performInitMove<<<1, 1>>>(hgr->nodes, hgr->hedgeNum, hgr->nodeNum, nodeListz, partID,
                                      count, gain, processed, targetWeight1, hgr->totalWeight);
            TIMERSTOP(4)

            // CHECK_ERROR(cudaMemset((void*)d_p0_num, 0, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemset((void*)d_p1_num, 0, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemset((void*)hgr->adj_part_list, 0, hgr->totalEdgeDegree * sizeof(int)));
            // TIMERSTART(5)
            // collect_part_info_next_round<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, hgr->adj_list,
            //                                                                                     hgr->pins_hedgeid_list, hgr->adj_part_list, d_p0_num, d_p1_num);
            // TIMERSTOP(5)

            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << "processed:" << processed[0] << "\n";
            std::cout << "gain:" << gain[0] << ", targetWeight1:" << targetWeight1 << "\n";
            optcfgs.stats.init_partition_imbalance = (float)gain[0] / targetWeight1;
            // iter++;
            if (gain[0] >= static_cast<long>(targetWeight1)) {
                break;
            }
        }
        // CHECK_ERROR(cudaFree(nodeListz));
        CHECK_ERROR(cudaFree(processed));
        CHECK_ERROR(cudaFree(count));
        CHECK_ERROR(cudaFree(gain));
    } else {
        std::cout << "enter move 1 to 0 branch\n";
        int* gain;
        CHECK_ERROR(cudaMallocManaged(&gain, sizeof(int)));
        gain[0] = zeroPartWeight[0];
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        unsigned* processed;
        CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
        // tmpNode* nodeListnz;
        // CHECK_ERROR(cudaMalloc((void**)&nodeListnz, hgr->nodeNum * sizeof(tmpNode)));
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0); // memset FS and TE as 0
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            count[0] = 0;
            processed[0] = 0;
            CHECK_ERROR(cudaMemset(nodeListnz, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(2)
            createPotentialNodeList<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodeListnz, count, partID);
            // createPotentialNodeList<<<100, blocksize>>>(hgr->nodes, hgr->nodeNum, nodeListnz, count, partID);
            TIMERSTOP(2)
            std::cout << count[0] << "\n";

            TIMERSTART(3)
            if (optcfgs.testDeterminism) {
                use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW_non_det()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW1_non_det());
            } else {
            use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW_f()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW1_f());
            // use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], mycmp()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], mycmp1());
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performInitMove<<<1, 1>>>(hgr->nodes, hgr->hedgeNum, hgr->nodeNum, nodeListnz, partID,
                                      count, gain, processed, targetWeight0, hgr->totalWeight);
            TIMERSTOP(4)
            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << "processed:" << processed[0] << "\n";
            std::cout << "gain:" << gain[0] << ", targetWeight0:" << targetWeight0 << "\n";
            optcfgs.stats.init_partition_imbalance = (float)gain[0] / targetWeight0;
            if (gain[0] >= static_cast<long>(targetWeight0)) {
                break;
            }
        }
        // CHECK_ERROR(cudaFree(nodeListnz));
        CHECK_ERROR(cudaFree(processed));
        CHECK_ERROR(cudaFree(count));
        CHECK_ERROR(cudaFree(gain));
    }
    CHECK_ERROR(cudaFree(nodeListz));
    CHECK_ERROR(cudaFree(nodeListnz));
    CHECK_ERROR(cudaFree(zeroPartWeight));
    // CHECK_ERROR(cudaFree(d_p0_num));
    // CHECK_ERROR(cudaFree(d_p1_num));
    // TIMERSTART(5)
    // TIMERSTOP(5)
}


void init_partition_fix_heaviest_node(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time, float& other_time, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned* zeroPartWeight;
    CHECK_ERROR(cudaMallocManaged(&zeroPartWeight, sizeof(unsigned)));
    zeroPartWeight[0] = 0;
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(0)
    setupInitPartitionWithoutHeaviestNode<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroPartWeight, hgr->maxWeight);
    TIMERSTOP(0)

    int total = hgr->totalWeight - hgr->maxWeight;
    int nonzeroPartWeight = total - zeroPartWeight[0];
    unsigned kvalue        = (K + 1) / 2;
    unsigned targetWeight0 = total * kvalue / K;
    unsigned targetWeight1 = total - targetWeight0;
    std::cout << "totalweight:" << hgr->totalWeight << ", part0_weight:" << zeroPartWeight[0] << ", part1_weight:" << nonzeroPartWeight << "\n";
    std::cout << "targetWeight0:" << targetWeight0 << ", targetWeight1:" << targetWeight1 << "\n";
    tmpNode_nouvm* nodeListz;
    CHECK_ERROR(cudaMalloc((void**)&nodeListz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    tmpNode_nouvm* nodeListnz;
    CHECK_ERROR(cudaMalloc((void**)&nodeListnz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    if (static_cast<long>(zeroPartWeight[0]) > nonzeroPartWeight) {
        std::cout << "enter move 0 to 1 branch\n";
        int* gain;
        CHECK_ERROR(cudaMallocManaged(&gain, sizeof(int)));
        gain[0] = nonzeroPartWeight;
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        unsigned* processed;
        CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
        // tmpNode* nodeListz;
        // CHECK_ERROR(cudaMalloc((void**)&nodeListz, hgr->nodeNum * sizeof(tmpNode)));
// #if 0
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0); // memset FS and TE as 0
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            count[0] = 0;
            processed[0] = 0;
            CHECK_ERROR(cudaMemset(nodeListz, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(2)
            createPotentialNodeList<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodeListz, count, partID);
            TIMERSTOP(2)
            std::cout << count[0] << "\n";

            TIMERSTART(3)
            if (optcfgs.testDeterminism) {
                use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW_non_det()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW1_non_det());
            } else {
            use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW_f()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], cmpGbyW1_f());
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performInitMoveWithoutHeaviestNode<<<1, 1>>>(hgr->nodes, hgr->hedgeNum, hgr->nodeNum, nodeListz, partID,
                                            count, gain, processed, targetWeight1, hgr->totalWeight, hgr->maxWeight);
            TIMERSTOP(4)
            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << "processed:" << processed[0] << "\n";
            std::cout << "gain:" << gain[0] << ", targetWeight1:" << targetWeight1 << "\n";
            optcfgs.stats.init_partition_imbalance = (float)gain[0] / targetWeight1;
            if (gain[0] >= static_cast<long>(targetWeight1)) {
                break;
            }
        }
// #endif
        // CHECK_ERROR(cudaFree(nodeListz));
        CHECK_ERROR(cudaFree(processed));
        CHECK_ERROR(cudaFree(count));
        CHECK_ERROR(cudaFree(gain));
    } else {
        std::cout << "enter move 1 to 0 branch\n";
        int* gain;
        CHECK_ERROR(cudaMallocManaged(&gain, sizeof(int)));
        gain[0] = zeroPartWeight[0];
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        unsigned* processed;
        CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
        // tmpNode* nodeListnz;
        // CHECK_ERROR(cudaMalloc((void**)&nodeListnz, hgr->nodeNum * sizeof(tmpNode)));
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0); // memset FS and TE as 0
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            count[0] = 0;
            processed[0] = 0;
            CHECK_ERROR(cudaMemset(nodeListnz, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(2)
            createPotentialNodeList<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodeListnz, count, partID);
            TIMERSTOP(2)
            std::cout << count[0] << "\n";

            TIMERSTART(3)
            if (optcfgs.testDeterminism) {
                use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW_non_det()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW1_non_det());
            } else {
            use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW_f()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], cmpGbyW1_f());
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performInitMoveWithoutHeaviestNode<<<1, 1>>>(hgr->nodes, hgr->hedgeNum, hgr->nodeNum, nodeListnz, partID,
                                            count, gain, processed, targetWeight0, hgr->totalWeight, hgr->maxWeight);
            TIMERSTOP(4)
            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << "processed:" << processed[0] << "\n";
            std::cout << "gain:" << gain[0] << ", targetWeight0:" << targetWeight0 << "\n";
            optcfgs.stats.init_partition_imbalance = (float)gain[0] / targetWeight0;
            if (gain[0] >= static_cast<long>(targetWeight0)) {
                break;
            }
        }
        // CHECK_ERROR(cudaFree(nodeListnz));
        CHECK_ERROR(cudaFree(processed));
        CHECK_ERROR(cudaFree(count));
        CHECK_ERROR(cudaFree(gain));
    }
    CHECK_ERROR(cudaFree(nodeListz));
    CHECK_ERROR(cudaFree(nodeListnz));
    CHECK_ERROR(cudaFree(zeroPartWeight));
}
