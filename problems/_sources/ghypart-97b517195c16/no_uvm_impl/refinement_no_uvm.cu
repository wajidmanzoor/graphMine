#include <iostream>
#include <chrono>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include "use_no_uvm.cuh"
#include "refinement_no_uvm_kernels.cuh"

__global__ void projection(int* coarseNodes, int coarseHedgeN, int coarseNodeN, int* fineNodes, int fineNodeN) {
    int tid = blockIdx.x * blockDim.x + threadIdx.x;
    if (tid < fineNodeN) {
        unsigned parent = fineNodes[tid + N_PARENT1(fineNodeN)];
        fineNodes[tid + N_PARTITION1(fineNodeN)] = coarseNodes[parent - coarseHedgeN + N_PARTITION1(coarseNodeN)];
    }
}

void project_no_uvm(Hypergraph* coarsenHgr, Hypergraph* fineHgr, float& time, float& other_time, float& cur, int cur_iter) {
    std::cout << __FUNCTION__ << "...\n";
    int blocksize = 128;
    int gridsize = UP_DIV(fineHgr->nodeNum, blocksize);
    std::cout << "fineNodes:" << fineHgr->nodeNum << ", coarseNodes:" << coarsenHgr->nodeNum << "\n";
    TIMERSTART(0)
    projection<<<gridsize, blocksize>>>(coarsenHgr->nodes, coarsenHgr->hedgeNum, coarsenHgr->nodeNum, fineHgr->nodes, fineHgr->nodeNum);
    TIMERSTOP(0)
    time += time0 / 1000.f;
    cur += time0 / 1000.f;
}

void refine_no_uvm(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;
        // cur_iter >= optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;
    }
    tmpNode_nouvm *zeroNodeList, *nonzeroNodeList;
    TIMERSTART(_alloc)
    CHECK_ERROR(cudaMalloc((void**)&zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    CHECK_ERROR(cudaMalloc((void**)&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    TIMERSTOP(_alloc)
    other_time += time_alloc / 1000.f;
    // if (cur_iter == 3) {
    //     std::ofstream debug("../debug/refine_no_uvm.txt");
    //     int* nodes = (int*)malloc(hgr->nodeNum * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes + N_PARTITION1(hgr->nodeNum), hgr->nodeNum * sizeof(int), cudaMemcpyDeviceToHost));
    //     for (int i = 0; i < hgr->nodeNum; ++i) {
    //         debug << nodes[i] << "\n";
    //     }
    // }
    int* d_p0_num, *d_p1_num;
    if (optcfgs.perfOptForRefine) {
        CHECK_ERROR(cudaMalloc((void**)&d_p0_num, hgr->hedgeNum * sizeof(int)));
        CHECK_ERROR(cudaMalloc((void**)&d_p1_num, hgr->hedgeNum * sizeof(int)));
        // CHECK_ERROR(cudaMalloc((void**)&hgr->adj_part_list, hgr->totalEdgeDegree * sizeof(int)));
        // CHECK_ERROR(cudaMemset((void*)hgr->adj_part_list, 0, hgr->totalEdgeDegree * sizeof(int)));
        // TIMERSTART(_t)
        // set_adj_nodes_part<<<UP_DIV(hgr->totalEdgeDegree, 128), 128>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, hgr->adj_list, hgr->adj_part_list);
        // TIMERSTOP(_t)
    }
    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);

        if (!optcfgs.perfOptForRefine) {
            TIMERSTART(0)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(0)
            time += time0 / 1000.f;
        } else {
            CHECK_ERROR(cudaMemset((void*)d_p0_num, 0, hgr->hedgeNum * sizeof(int)));
            CHECK_ERROR(cudaMemset((void*)d_p1_num, 0, hgr->hedgeNum * sizeof(int)));
            TIMERSTART(_)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            collect_part_info1<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, hgr->adj_list, hgr->pins_hedgeid_list, d_p0_num, d_p1_num);
            init_refine_boundary_nodes<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, hgr->pins_hedgeid_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num);
            // init_move_gain1<<<hgr->hedgeNum, blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, hgr->pins_hedgeid_list, hgr->adj_part_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num, hgr->hedges);
            TIMERSTOP(_)
            // TIMERSTART(_)
            // thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            // collect_part_info2<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, hgr->adj_list, hgr->pins_hedgeid_list, d_p0_num, d_p1_num, hgr->adj_part_list);
            // init_refine_boundary_nodes1<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, hgr->pins_hedgeid_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num, hgr->adj_part_list);
            // TIMERSTOP(_)
            time += time_ / 1000.f;
        }

        // CHECK_ERROR(cudaMemset(zeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));
        // CHECK_ERROR(cudaMemset(nonzeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));
        zeroW[0] = 0, nonzeroW[0] = 0;
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        createTwoNodeLists<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << zeroW[0] << ", " << nonzeroW[0] << "\n";

        // if (cur_iter == 0 && pass == 0) {
        //     tmpNode_nouvm* zero = (tmpNode_nouvm*)malloc(hgr->nodeNum * sizeof(tmpNode_nouvm));
        //     CHECK_ERROR(cudaMemcpy((void *)zero, zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm), cudaMemcpyDeviceToHost));
        //     tmpNode_nouvm* nonzero = (tmpNode_nouvm*)malloc(hgr->nodeNum * sizeof(tmpNode_nouvm));
        //     CHECK_ERROR(cudaMemcpy((void *)nonzero, nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm), cudaMemcpyDeviceToHost));
        //     // std::ofstream debug("../scripts/ghypart.txt");
        //     // debug << "zeros:\n";
        //     for (int i = 0; i < zeroW[0]; ++i) {
        //         // debug << zero[i].nodeid - hgr->hedgeNum << "\n";
        //         printf("%d ", zero[i].nodeid - hgr->hedgeNum);
        //     }
        //     // debug << "ones:\n";
        //     // for (int i = 0; i < nonzeroW[0]; ++i) {
        //     //     debug << nonzero[i].nodeid - hgr->hedgeNum << "\n";
        //     // }
        //     printf("\n");
        // }
        thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
        thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
        TIMERSTART(2)
        if (optcfgs.testDeterminism) {
            thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
            thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
        } else {
            thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
            thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
        }
        TIMERSTOP(2)

        unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        gridsize = UP_DIV(workLen, blocksize);
        TIMERSTART(3)
        performNodeSwapInShorterLength<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen);
        TIMERSTOP(3)
        time += (time1 + time2 + time3) / 1000.f;
        cur += (time1 + time2 + time3) / 1000.f;
        std::cout << "time:" << time << " s.\n";
        pass++;
        
    }
    TIMERSTART(4)
    thrust::fill(thrust::device, hgr->nodes + N_COUNTER1(hgr->nodeNum), hgr->nodes + N_COUNTER1(hgr->nodeNum) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    CHECK_ERROR(cudaFree(nonzeroNodeList));
    CHECK_ERROR(cudaFree(zeroNodeList));
    CHECK_ERROR(cudaFree(zeroW));
    CHECK_ERROR(cudaFree(nonzeroW));
    if (optcfgs.perfOptForRefine) {
        CHECK_ERROR(cudaFree(d_p0_num));
        CHECK_ERROR(cudaFree(d_p1_num));
        // CHECK_ERROR(cudaFree(hgr->adj_part_list));
    }
    time += time4 / 1000.f;
    cur += time4 / 1000.f;
    // if (cur_iter == 1) {
    //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
    //     CHECK_ERROR(cudaMemcpy(nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    //     std::vector<int> parts(2, 0);
    //     for (int i = 0; i < hgr->nodeNum; i++) {
    //         parts[nodes[N_PARTITION1(hgr->nodeNum) + i]]++;
    //     }
    //     for (int i = 0; i < 2; i++) {
    //         std::cout << "$$ part " << i << ": " << parts[i] << "\n";
    //         // if (parts[0] == 854)    printf("cur_iter: %d\n", cur_iter);
    //     }
    //     // for (int i = 0; i < hgr->nodeNum; i++) {
    //     //     printf("%d ", nodes[N_COUNTER1(hgr->nodeNum) + i]);
    //     // }
    // }
}

void rebalance_no_uvm(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, 
                        float& other_time, int& rebalance, int cur_iter, OptionConfigs& optcfgs, unsigned long& memBytes) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned* nonzeroPartWeight;
    CHECK_ERROR(cudaMallocManaged(&nonzeroPartWeight, sizeof(unsigned)));
    CHECK_ERROR(cudaMemset((void*)nonzeroPartWeight, 0, sizeof(unsigned)));
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(0)
    countTotalNonzeroPartWeight<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nonzeroPartWeight);
    TIMERSTOP(0)

    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    const int hi = (1 + tol) * hgr->totalWeight / (2 + tol); // 55 / 100
    // const int hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
    const int lo = hgr->totalWeight - hi;
    int* bal;
    CHECK_ERROR(cudaMallocManaged(&bal, sizeof(int)));
    bal[0] = nonzeroPartWeight[0];
    std::cout << bal[0] << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    unsigned *bucketcnt;
    // CHECK_ERROR(cudaMalloc((void**)&bucketcnt, 101 * sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&bucketcnt, 101 * sizeof(unsigned)));
    unsigned *negCnt;
    CHECK_ERROR(cudaMallocManaged(&negCnt, sizeof(unsigned)));

#if 1
    memBytes += 101 * hgr->nodeNum * sizeof(tmpNode_nouvm);
    std::cout << __LINE__ << " prepare to consume: " << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
    tmpNode_nouvm *nodelistz;
    CHECK_ERROR(cudaMalloc((void**)&nodelistz, 101 * hgr->nodeNum * sizeof(tmpNode_nouvm)));
    // CHECK_ERROR(cudaMallocManaged(&nodelistz, 101 * hgr->nodeNum * sizeof(unsigned)));
    memBytes += 101 * hgr->nodeNum * sizeof(tmpNode_nouvm);
    std::cout << __LINE__ << " prepare to consume: " << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
    tmpNode_nouvm *nodelisto;
    CHECK_ERROR(cudaMalloc((void**)&nodelisto, 101 * hgr->nodeNum * sizeof(tmpNode_nouvm)));
    // CHECK_ERROR(cudaMallocManaged(&nodelisto, 101 * hgr->nodeNum * sizeof(unsigned)));
    memBytes += hgr->nodeNum * sizeof(tmpNode_nouvm);
    std::cout << __LINE__ << " prepare to consume: " << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
    tmpNode_nouvm *negGainlistz;
    CHECK_ERROR(cudaMalloc((void**)&negGainlistz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    // CHECK_ERROR(cudaMallocManaged(&negGainlistz, hgr->nodeNum * sizeof(unsigned)));
    memBytes += hgr->nodeNum * sizeof(tmpNode_nouvm);
    std::cout << __LINE__ << " prepare to consume: " << memBytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
    tmpNode_nouvm *negGainlisto;
    CHECK_ERROR(cudaMalloc((void**)&negGainlisto, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    // CHECK_ERROR(cudaMallocManaged(&negGainlisto, hgr->nodeNum * sizeof(unsigned)));
#endif
    unsigned* row;
    CHECK_ERROR(cudaMallocManaged(&row, sizeof(unsigned)));
    unsigned* processed;
    CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
    unsigned cnt[101];
    while (1) {
        if (bal[0] >= lo && bal[0] <= hi) {
            break;
        }
        negCnt[0] = 0;
        row[0] = 0, processed[0] = 0;
        std::cout << "bal:" << bal[0] << ", hi:" << hi << ", lo:" << lo << "\n";
        if (bal[0] < lo) {
            std::cout << "enter bal < lo branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(2)
            thrust::fill(thrust::device, bucketcnt, bucketcnt + 101, 0);
            divideNodesIntoBuckets<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, bucketcnt, negGainlistz, negCnt, partID);
            TIMERSTOP(2)

            // CHECK_ERROR(cudaMemcpy((void *)cnt, bucketcnt, 101 * sizeof(unsigned), cudaMemcpyDeviceToHost));
            // sorting each bucket in parallel
            TIMERSTART(3)
            for (int i = 0; i < 101; ++i) {
                // if (cnt[i] > 1) {
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    // thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + cnt[i], cmpGbyW_d());
                    thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], cmpGbyW_d());
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
                }
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performRebalanceMove<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelistz, bucketcnt, bal, lo, hi, row, processed, partID);
            TIMERSTOP(4)

            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            cur += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", lo:" << lo << "\n";
            if (bal[0] >= lo) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }

            // moving nodes from nodeListzNegGain
            if (negCnt[0] == 0) {
                continue;
            }
            TIMERSTART(5)
            thrust::sort(thrust::device, negGainlistz, negGainlistz + negCnt[0], cmpGbyW_d());
            TIMERSTOP(5)

            TIMERSTART(6)
            moveNegativeGainNodes<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, negGainlistz, negCnt, bal, lo, hi, processed, partID);
            TIMERSTOP(6)

            time += (time5 + time6) / 1000.f;
            cur += (time5 + time6) / 1000.f;
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            std::cout << "@bal:" << bal[0] << ", lo:" << lo << "\n";
            if (bal[0] >= lo) {
                break;
            }
        } else {
            std::cout << "enter bal > hi branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(2)
            thrust::fill(thrust::device, bucketcnt, bucketcnt + 101, 0);
            divideNodesIntoBuckets<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelisto, bucketcnt, negGainlisto, negCnt, partID);
            TIMERSTOP(2)

            // CHECK_ERROR(cudaMemcpy((void *)cnt, bucketcnt, 101 * sizeof(unsigned), cudaMemcpyDeviceToHost));
            TIMERSTART(3)
            for (int i = 0; i < 101; ++i) {
                // if (bucketcnt[i] > 1) {
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    // thrust::sort(thrust::cuda::par.on(stream), nodelisto + i * hgr->nodeNum, nodelisto + i * hgr->nodeNum + cnt[i], cmpGbyW_d());
                    thrust::sort(thrust::cuda::par.on(stream), nodelisto + i * hgr->nodeNum, nodelisto + i * hgr->nodeNum + bucketcnt[i], cmpGbyW_d());
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
                }
            }
            TIMERSTOP(3)

            TIMERSTART(4)
            performRebalanceMove<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelisto, bucketcnt, bal, lo, hi, row, processed, partID);
            TIMERSTOP(4)

            time += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            cur += (time0 + time1 + time2 + time3 + time4) / 1000.f;
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", hi:" << hi << "\n";
            if (bal[0] <= hi) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }

            // moving nodes from nodeListzNegGain
            if (negCnt[0] == 0) {
                continue;
            }
            TIMERSTART(5)
            thrust::sort(thrust::device, negGainlisto, negGainlisto + negCnt[0], cmpGbyW_d());
            TIMERSTOP(5)

            TIMERSTART(6)
            moveNegativeGainNodes<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, negGainlisto, negCnt, bal, lo, hi, processed, partID);
            TIMERSTOP(6)

            time += (time5 + time6) / 1000.f;
            cur += (time5 + time6) / 1000.f;
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            std::cout << "@bal:" << bal[0] << ", hi:" << hi << "\n";
            if (bal[0] <= hi) {
                break;
            }
        }
    }
    CHECK_ERROR(cudaFree(processed));
    CHECK_ERROR(cudaFree(row));
    CHECK_ERROR(cudaFree(negGainlisto));
    CHECK_ERROR(cudaFree(nodelisto));
    CHECK_ERROR(cudaFree(negGainlistz));
    CHECK_ERROR(cudaFree(nodelistz));
    CHECK_ERROR(cudaFree(negCnt));
    CHECK_ERROR(cudaFree(bucketcnt));
    memBytes -= 204 * hgr->nodeNum * sizeof(tmpNode_nouvm);
}

void rebalance_no_uvm_without_multiple_sort(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, 
                                            float& other_time, int& rebalance, int curr_idx, OptionConfigs& optCfgs, unsigned long& memBytes) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned* nonzeroPartWeight;
    CHECK_ERROR(cudaMallocManaged(&nonzeroPartWeight, sizeof(unsigned)));
    CHECK_ERROR(cudaMemset((void*)nonzeroPartWeight, 0, sizeof(unsigned)));
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(0)
    countTotalNonzeroPartWeight<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nonzeroPartWeight);
    TIMERSTOP(0)
    unsigned* zeroPartNum;
    CHECK_ERROR(cudaMallocManaged(&zeroPartNum, sizeof(unsigned)));
    unsigned* nonzeroPartNum;
    CHECK_ERROR(cudaMallocManaged(&nonzeroPartNum, sizeof(unsigned)));

    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int hi = (1 + tol) * hgr->totalWeight / (2 + tol); // 55 / 100
    if (optCfgs.useCommonDefRatio) {
        hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
    }
    const int lo = hgr->totalWeight - hi;
    int* bal;
    CHECK_ERROR(cudaMallocManaged(&bal, sizeof(int)));
    bal[0] = nonzeroPartWeight[0];
    std::cout << bal[0] << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    unsigned *bucketcnt;
    // CHECK_ERROR(cudaMalloc((void**)&bucketcnt, 101 * sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&bucketcnt, 102 * sizeof(unsigned)));
    unsigned *bucketoff;
    CHECK_ERROR(cudaMallocManaged(&bucketoff, 102 * sizeof(unsigned)));
    unsigned *bucketidx;
    CHECK_ERROR(cudaMallocManaged(&bucketidx, 102 * sizeof(unsigned)));
#if 1
    tmpNode_nouvm *nodelistz;
    CHECK_ERROR(cudaMalloc((void**)&nodelistz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    tmpNode_nouvm *nodelisto;
    CHECK_ERROR(cudaMalloc((void**)&nodelisto, hgr->nodeNum * sizeof(tmpNode_nouvm)));
#endif
    unsigned* processed;
    CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
    int* d_p0_num, *d_p1_num;
    CHECK_ERROR(cudaMalloc((void**)&d_p0_num, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&d_p1_num, hgr->hedgeNum * sizeof(int)));
    while (1) {
        if (bal[0] >= lo && bal[0] <= hi) {
            break;
        }
        processed[0] = 0;
        nonzeroPartNum[0] = 0, zeroPartNum[0] = 0;
        std::cout << "bal:" << bal[0] << ", hi:" << hi << ", lo:" << lo << "\n";
        if (bal[0] < lo) {
            std::cout << "enter bal < lo branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            // CHECK_ERROR(cudaMemset((void*)d_p0_num, 0, hgr->hedgeNum * sizeof(int)));
            // CHECK_ERROR(cudaMemset((void*)d_p1_num, 0, hgr->hedgeNum * sizeof(int)));
            // // CHECK_ERROR(cudaMemset((void*)hgr->nodes + N_FS1(hgr->nodeNum), 0, hgr->nodeNum * 2 * sizeof(int)));
            // TIMERSTART(1)
            // thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            // collect_part_info1<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, hgr->totalEdgeDegree, hgr->adj_list, hgr->pins_hedgeid_list, d_p0_num, d_p1_num);
            // init_refine_boundary_nodes<<<UP_DIV(hgr->totalEdgeDegree, blocksize), blocksize>>>(hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum, hgr->pins_hedgeid_list, hgr->totalEdgeDegree, d_p0_num, d_p1_num);
            // TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            // TIMERSTART(2)
            // thrust::fill(thrust::device, bucketcnt, bucketcnt + 102, 0);
            // computeBucketCounts<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, bucketcnt, zeroPartNum, partID);
            // thrust::exclusive_scan(thrust::device, bucketcnt, bucketcnt + 102, bucketoff);
            // // createSingleNodelist<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, zeroPartNum, partID);
            // TIMERSTOP(2)

            // TIMERSTART(3)
            // thrust::fill(thrust::device, bucketidx, bucketidx + 102, 0);
            // placeNodesIntoSegments<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, bucketidx, bucketoff, partID);
            // TIMERSTOP(3)

            TIMERSTART(2)
            createSingleNodelist<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, zeroPartNum, partID);
            TIMERSTOP(2)

            TIMERSTART(3)
            TIMERSTOP(3)
            time3 = 0;

            TIMERSTART(4)
            if (optCfgs.testDeterminism) {
                thrust::sort(thrust::device, nodelistz, nodelistz + zeroPartNum[0], cmpGbyW_d_non_det());
            } else {
            thrust::sort(thrust::device, nodelistz, nodelistz + zeroPartNum[0], cmpGbyW_d());
            }
            TIMERSTOP(4)
            // std::vector<tmpNode_nouvm> nodes(zeroPartNum[0]);
            // CHECK_ERROR(cudaMemcpy((void *)&nodes[0], nodelistz, sizeof(tmpNode_nouvm) * zeroPartNum[0], cudaMemcpyDeviceToHost));
            // std::cout << zeroPartNum[0] << "\n";
            // for (int i = 0; i < zeroPartNum[0]; ++i) {
            //     std::cout << "id:" << nodes[i].nodeid << ", gain:" << nodes[i].gain << ", weight:" << nodes[i].weight << "\n";
            // }
            // std::cout << "\n";
            TIMERSTART(5)
            rebalanceMoveOnSingleNodeList<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelistz, zeroPartNum, bal, lo, hi, processed, partID);
            TIMERSTOP(5)

            time += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            cur += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", lo:" << lo << "\n";
            std::cout << "# processed moves:" << processed[0] << "\n";
            if (bal[0] >= lo) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }
        } else {
            std::cout << "enter bal > hi branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            // TIMERSTART(2)
            // thrust::fill(thrust::device, bucketcnt, bucketcnt + 102, 0);
            // computeBucketCounts<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, bucketcnt, nonzeroPartNum, partID);
            // // thrust::fill(thrust::device, bucketoff, bucketoff + 102, 0);
            // thrust::exclusive_scan(thrust::device, bucketcnt, bucketcnt + 102, bucketoff);
            // TIMERSTOP(2)

            // TIMERSTART(3)
            // thrust::fill(thrust::device, bucketidx, bucketidx + 102, 0);
            // placeNodesIntoSegments<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelisto, bucketidx, bucketoff, partID);
            // TIMERSTOP(3)

            TIMERSTART(2)
            createSingleNodelist<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelisto, nonzeroPartNum, partID);
            TIMERSTOP(2)

            TIMERSTART(3)
            TIMERSTOP(3)
            time3 = 0;
            
            TIMERSTART(4)
            if (optCfgs.testDeterminism) {
                thrust::sort(thrust::device, nodelisto, nodelisto + nonzeroPartNum[0], cmpGbyW_d_non_det());
            } else {
            thrust::sort(thrust::device, nodelisto, nodelisto + nonzeroPartNum[0], cmpGbyW_d());
            }
            TIMERSTOP(4)

            TIMERSTART(5)
            rebalanceMoveOnSingleNodeList<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelisto, nonzeroPartNum, bal, lo, hi, processed, partID);
            TIMERSTOP(5)

            time += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            cur += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            std::cout << "# processed moves:" << processed[0] << "\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", hi:" << hi << "\n";
            if (bal[0] <= hi) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }
        }
    }
    CHECK_ERROR(cudaFree(processed));
    CHECK_ERROR(cudaFree(nodelisto));
    CHECK_ERROR(cudaFree(nodelistz));
    CHECK_ERROR(cudaFree(bucketidx));
    CHECK_ERROR(cudaFree(bucketoff));
    CHECK_ERROR(cudaFree(bucketcnt));
    CHECK_ERROR(cudaFree(d_p0_num));
    CHECK_ERROR(cudaFree(d_p1_num));
}


void refine_no_uvm_fix_heaviest_node(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;   
    }
    tmpNode_nouvm *zeroNodeList, *nonzeroNodeList;
    CHECK_ERROR(cudaMalloc((void**)&zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    CHECK_ERROR(cudaMalloc((void**)&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));

    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
        init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
        TIMERSTOP(0)

        // CHECK_ERROR(cudaMemset(zeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));
        // CHECK_ERROR(cudaMemset(nonzeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode_nouvm)));
        zeroW[0] = 0, nonzeroW[0] = 0;
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        createTwoNodeLists<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << zeroW[0] << ", " << nonzeroW[0] << "\n";

        thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
        thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
        TIMERSTART(2)
        if (optcfgs.testDeterminism) {
            thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
            thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
        } else {
        thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
        thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
        }
        TIMERSTOP(2)

        unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        gridsize = UP_DIV(workLen, blocksize);
        TIMERSTART(3)
        performNodeSwapInShorterLengthWithoutHeaviestNode<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen, cur_iter, hgr->maxWeight);
        TIMERSTOP(3)
        time += (time0 + time1 + time2 + time3) / 1000.f;
        cur += (time0 + time1 + time2 + time3) / 1000.f;
        std::cout << "time:" << time << " s.\n";
        pass++;
        
    }
    TIMERSTART(4)
    thrust::fill(thrust::device, hgr->nodes + N_COUNTER1(hgr->nodeNum), hgr->nodes + N_COUNTER1(hgr->nodeNum) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    CHECK_ERROR(cudaFree(nonzeroNodeList));
    CHECK_ERROR(cudaFree(zeroNodeList));
    CHECK_ERROR(cudaFree(zeroW));
    CHECK_ERROR(cudaFree(nonzeroW));
    time += time4 / 1000.f;
    cur += time4 / 1000.f;
}


void rebalance_no_uvm_single_sort_fix_heaviest_node(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, 
                                            float& other_time, int& rebalance, int curr_idx, OptionConfigs& optCfgs, unsigned long& memBytes) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned* nonzeroPartWeight;
    CHECK_ERROR(cudaMallocManaged(&nonzeroPartWeight, sizeof(unsigned)));
    CHECK_ERROR(cudaMemset((void*)nonzeroPartWeight, 0, sizeof(unsigned)));
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(0)
    countTotalNonzeroPartWeightWithoutHeaviestNode<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nonzeroPartWeight, curr_idx, hgr->maxWeight);
    TIMERSTOP(0)
    unsigned* zeroPartNum;
    CHECK_ERROR(cudaMallocManaged(&zeroPartNum, sizeof(unsigned)));
    unsigned* nonzeroPartNum;
    CHECK_ERROR(cudaMallocManaged(&nonzeroPartNum, sizeof(unsigned)));

    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int total = curr_idx > 0 ? hgr->totalWeight - hgr->maxWeight : hgr->totalWeight;
    const int hi = (1 + tol) * total / (2 + tol); // 55 / 100
    // const int hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
    const int lo = total - hi;
    int* bal;
    CHECK_ERROR(cudaMallocManaged(&bal, sizeof(int)));
    bal[0] = nonzeroPartWeight[0];
    std::cout << bal[0] << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    unsigned *bucketcnt;
    // CHECK_ERROR(cudaMalloc((void**)&bucketcnt, 101 * sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&bucketcnt, 102 * sizeof(unsigned)));
    unsigned *bucketoff;
    CHECK_ERROR(cudaMallocManaged(&bucketoff, 102 * sizeof(unsigned)));
    unsigned *bucketidx;
    CHECK_ERROR(cudaMallocManaged(&bucketidx, 102 * sizeof(unsigned)));
#if 1
    tmpNode_nouvm *nodelistz;
    CHECK_ERROR(cudaMalloc((void**)&nodelistz, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    tmpNode_nouvm *nodelisto;
    CHECK_ERROR(cudaMalloc((void**)&nodelisto, hgr->nodeNum * sizeof(tmpNode_nouvm)));
#endif
    unsigned* processed;
    CHECK_ERROR(cudaMallocManaged(&processed, sizeof(unsigned)));
    int count = 0;
    while (1) {
        if (bal[0] >= lo && bal[0] <= hi) {
            break;
        }
        processed[0] = 0;
        nonzeroPartNum[0] = 0, zeroPartNum[0] = 0;
        std::cout << "bal:" << bal[0] << ", hi:" << hi << ", lo:" << lo << "\n";
        if (bal[0] < lo) {
            std::cout << "enter bal < lo branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(2)
            // thrust::fill(thrust::device, bucketcnt, bucketcnt + 102, 0);
            // computeBucketCounts<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, bucketcnt, zeroPartNum, partID);
            // // thrust::fill(thrust::device, bucketoff, bucketoff + 102, 0);
            // thrust::exclusive_scan(thrust::device, bucketcnt, bucketcnt + 102, bucketoff);
            createSingleNodelist<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, zeroPartNum, partID);
            TIMERSTOP(2)
            std::cout << "zeroPartNum:" << zeroPartNum[0] << "\n";
            // TIMERSTART(3)
            // thrust::fill(thrust::device, bucketidx, bucketidx + 102, 0);
            // placeNodesIntoSegments<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelistz, bucketidx, bucketoff, partID);
            // TIMERSTOP(3)

            TIMERSTART(4)
            if (optCfgs.testDeterminism) {
                thrust::sort(thrust::device, nodelistz, nodelistz + zeroPartNum[0], cmpGbyW_d_non_det());
            } else {
            thrust::sort(thrust::device, nodelistz, nodelistz + zeroPartNum[0], cmpGbyW_d());
            }
            TIMERSTOP(4)

            // if (curr_idx == 1 && count == 1) {
            //     std::ofstream debug("move_node_list_no_uvm.txt");
            //     tmpNode_nouvm* nodelist = (tmpNode_nouvm*)malloc(hgr->nodeNum * sizeof(tmpNode_nouvm));
            //     CHECK_ERROR(cudaMemcpy((void *)nodelist, nodelistz, hgr->nodeNum * sizeof(tmpNode_nouvm), cudaMemcpyDeviceToHost));
            //     for (int i = 0; i < zeroPartNum[0]; ++i) {
            //         debug << nodelist[i].nodeid << ", weight:" << nodelist[i].weight << "\n";
            //     }
            // }
            // std::cout << "maxWeight:" << hgr->maxWeight << "\n";
            TIMERSTART(5)
            rebalanceMoveOnSingleNodeListWithoutHeaviestNode<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelistz, zeroPartNum, 
                                                            bal, lo, hi, processed, partID, curr_idx, hgr->maxWeight);
            TIMERSTOP(5)

            // time += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            // cur += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            time += (time0 + time1 + time2 + time4 + time5) / 1000.f;
            cur += (time0 + time1 + time2 + time4 + time5) / 1000.f;
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", lo:" << lo << "\n";
            std::cout << "# processed moves:" << processed[0] << "\n";
            // std::cout << "curr_iter:" << curr_idx << ", edgecut:" << computeHyperedgeCut(hgr, optCfgs.useCUDAUVM) << "\n";
            // if (curr_idx == 0) {
            //     std::ofstream debug("iterative_edgecut_no_uvm.txt", std::ios::app);
            //     debug << computeHyperedgeCut(hgr, optCfgs.useCUDAUVM) << "\n";
            // }
            count++;
            if (bal[0] >= lo) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }
        } else {
            std::cout << "enter bal > hi branch+++++++++\n";
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(1)
            thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
            init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
            TIMERSTOP(1)

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(2)
            thrust::fill(thrust::device, bucketcnt, bucketcnt + 102, 0);
            computeBucketCounts<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, bucketcnt, nonzeroPartNum, partID);
            // thrust::fill(thrust::device, bucketoff, bucketoff + 102, 0);
            thrust::exclusive_scan(thrust::device, bucketcnt, bucketcnt + 102, bucketoff);
            TIMERSTOP(2)

            TIMERSTART(3)
            thrust::fill(thrust::device, bucketidx, bucketidx + 102, 0);
            placeNodesIntoSegments<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, nodelisto, bucketidx, bucketoff, partID);
            TIMERSTOP(3)

            TIMERSTART(4)
            if (optCfgs.testDeterminism) {
                thrust::sort(thrust::device, nodelisto, nodelisto + nonzeroPartNum[0], cmpGbyW_d_non_det());
            } else {
            thrust::sort(thrust::device, nodelisto, nodelisto + nonzeroPartNum[0], cmpGbyW_d());
            }
            TIMERSTOP(4)

            TIMERSTART(5)
            rebalanceMoveOnSingleNodeListWithoutHeaviestNode<<<1, 1>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, nodelisto, nonzeroPartNum, 
                                                            bal, lo, hi, processed, partID, curr_idx, hgr->maxWeight);
            TIMERSTOP(5)

            time += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            cur += (time0 + time1 + time2 + time3 + time4 + time5) / 1000.f;
            std::cout << "# processed moves:" << processed[0] << "\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal[0] << ", hi:" << hi << "\n";
            if (bal[0] <= hi) {
                break;
            }
            if (processed[0] > sqrt(hgr->nodeNum)) {
                continue;
            }
        }
    }
    CHECK_ERROR(cudaFree(processed));
    CHECK_ERROR(cudaFree(nodelisto));
    CHECK_ERROR(cudaFree(nodelistz));
    CHECK_ERROR(cudaFree(bucketidx));
    CHECK_ERROR(cudaFree(bucketoff));
    CHECK_ERROR(cudaFree(bucketcnt));
}


void refine_no_uvm_fix_node_hybrid_move(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;   
    }
    tmpNode_nouvm *zeroNodeList, *nonzeroNodeList;
    CHECK_ERROR(cudaMalloc((void**)&zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    CHECK_ERROR(cudaMalloc((void**)&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    
    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
        init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
        TIMERSTOP(0)

        zeroW[0] = 0, nonzeroW[0] = 0;
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        createTwoNodeListsWithMarkingDirection<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << zeroW[0] << ", " << nonzeroW[0] << "\n";

        // thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
        // thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
        // TIMERSTART(2)
        // if (optcfgs.testDeterminism) {
        //     thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
        //     thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
        // } else {
        // thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
        // thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
        // }
        // TIMERSTOP(2)

        // unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        // unsigned nodeListLen = zeroW[0] + nonzeroW[0];
        // tmpNode_nouvm* mergeNodeList;
        // CHECK_ERROR(cudaMalloc((void**)&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
        // CHECK_ERROR(cudaMemset(mergeNodeList, 0, nodeListLen * sizeof(tmpNode_nouvm)));
        // for (int i = 0; i < nodeListLen; ++i) {
        //     if (i < zeroW[0]) {
        //         zeroNodeList[i].move_direction = 1;
        //     } else {
        //         nonzeroNodeList[i-zeroW[0]].move_direction = -1;
        //     }
        // }
        // TIMERSTART(2)
        // thrust::copy(thrust::device, zeroNodeList, zeroNodeList+zeroW[0], mergeNodeList);
        // thrust::copy(thrust::device, nonzeroNodeList, nonzeroNodeList+nonzeroW[0], mergeNodeList+zeroW[0]);
        // thrust::sort(thrust::device, mergeNodeList, mergeNodeList + nodeListLen, cmpGbyW_d());
        // TIMERSTOP(2)

        // time += (time0 + time1 + time2) / 1000.f;
        // cur += (time0 + time1 + time2) / 1000.f;
        std::cout << "enter moving-based heuristics...\n";
        // gridsize = UP_DIV(workLen, blocksize);
        if (cur_iter >= optcfgs.switchToMergeMoveLevel) { // 1 for human_gene2
            thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
            thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
            TIMERSTART(2)
            if (optcfgs.testDeterminism) {
                thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
                thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
            } else {
                thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
                thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
            }
            TIMERSTOP(2)
            unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
            gridsize = UP_DIV(workLen, blocksize);
            TIMERSTART(3)
            performNodeSwapInShorterLengthWithoutHeaviestNode<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen, cur_iter, hgr->maxWeight);
            TIMERSTOP(3)
            time += (time0 + time1 + time2 + time3) / 1000.f;
            cur += (time0 + time1 + time2 + time3) / 1000.f;
        } else {
            unsigned nodeListLen = zeroW[0] + nonzeroW[0];
            tmpNode_nouvm* mergeNodeList;
            CHECK_ERROR(cudaMalloc((void**)&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
            // CHECK_ERROR(cudaMallocManaged(&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
            CHECK_ERROR(cudaMemset(mergeNodeList, 0, nodeListLen * sizeof(tmpNode_nouvm)));
            TIMERSTART(2)
            thrust::copy(thrust::device, zeroNodeList, zeroNodeList+zeroW[0], mergeNodeList);
            thrust::copy(thrust::device, nonzeroNodeList, nonzeroNodeList+nonzeroW[0], mergeNodeList+zeroW[0]);
            thrust::sort(thrust::device, mergeNodeList, mergeNodeList + nodeListLen, cmpGbyW_d());
            TIMERSTOP(2)
            // if (pass == 0) {
            //     std::cout << "print here!\n";
            //     std::ofstream debug("merge_node_list_no_uvm.txt");
            //     tmpNode_nouvm* merge = (tmpNode_nouvm*)malloc(nodeListLen * sizeof(tmpNode_nouvm));
            //     CHECK_ERROR(cudaMemcpy((void *)merge, mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm), cudaMemcpyDeviceToHost));
            //     for (int i = 0; i < nodeListLen; ++i) {
            //         debug << merge[i].nodeid << ", weight:" << merge[i].weight << ", dir:" << merge[i].move_direction << "\n";
            //     }
            //     std::ofstream debug1("curr_partition_no_uvm.txt");
            //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
            //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            //     for (int i = 0; i < hgr->nodeNum; ++i) {
            //         debug1 << nodes[N_PARTITION1(hgr->nodeNum) + i] << "\n";
            //     }
            // }
            gridsize = UP_DIV(nodeListLen, blocksize);
            // std::cout << "maxWeight:" << hgr->maxWeight << "\n";
            TIMERSTART(3)
            performMergingMovesWithoutHeaviestNode<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, mergeNodeList, nodeListLen, cur_iter, hgr->maxWeight);
            TIMERSTOP(3)
            // if (pass == 0) {
            //     std::ofstream debug1("after_merging_no_uvm.txt");
            //     int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
            //     CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
            //     for (int i = 0; i < hgr->nodeNum; ++i) {
            //         debug1 << nodes[N_PARTITION1(hgr->nodeNum) + i] << "\n";
            //     }
            // }
            CHECK_ERROR(cudaFree(mergeNodeList));
            time += (time0 + time1 + time2 + time3) / 1000.f;
            cur += (time0 + time1 + time2 + time3) / 1000.f;
        }
        std::cout << "time:" << time << " s.\n";
        pass++;
        // std::cout << "curr_iter:" << cur_iter << ", edgecut:" << computeHyperedgeCut(hgr, optcfgs.useCUDAUVM) << "\n";
    }
    TIMERSTART(4)
    thrust::fill(thrust::device, hgr->nodes + N_COUNTER1(hgr->nodeNum), hgr->nodes + N_COUNTER1(hgr->nodeNum) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    CHECK_ERROR(cudaFree(nonzeroNodeList));
    CHECK_ERROR(cudaFree(zeroNodeList));
    CHECK_ERROR(cudaFree(zeroW));
    CHECK_ERROR(cudaFree(nonzeroW));
    time += time4 / 1000.f;
    cur += time4 / 1000.f;
}


void refine_no_uvm_with_hybrid_move(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;   
    }
    tmpNode_nouvm *zeroNodeList, *nonzeroNodeList;
    CHECK_ERROR(cudaMalloc((void**)&zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    CHECK_ERROR(cudaMalloc((void**)&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    
    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
        init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
        TIMERSTOP(0)

        zeroW[0] = 0, nonzeroW[0] = 0;
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        createTwoNodeListsWithMarkingDirection<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << zeroW[0] << ", " << nonzeroW[0] << "\n";

        // thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
        // thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
        // TIMERSTART(2)
        // if (optcfgs.testDeterminism) {
        //     thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
        //     thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
        // } else {
        // thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
        // thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
        // }
        // TIMERSTOP(2)

        // unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        // unsigned nodeListLen = zeroW[0] + nonzeroW[0];
        // tmpNode_nouvm* mergeNodeList;
        // CHECK_ERROR(cudaMalloc((void**)&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
        // CHECK_ERROR(cudaMemset(mergeNodeList, 0, nodeListLen * sizeof(tmpNode_nouvm)));
        // for (int i = 0; i < nodeListLen; ++i) {
        //     if (i < zeroW[0]) {
        //         zeroNodeList[i].move_direction = 1;
        //     } else {
        //         nonzeroNodeList[i-zeroW[0]].move_direction = -1;
        //     }
        // }
        // TIMERSTART(2)
        // thrust::copy(thrust::device, zeroNodeList, zeroNodeList+zeroW[0], mergeNodeList);
        // thrust::copy(thrust::device, nonzeroNodeList, nonzeroNodeList+nonzeroW[0], mergeNodeList+zeroW[0]);
        // thrust::sort(thrust::device, mergeNodeList, mergeNodeList + nodeListLen, cmpGbyW_d());
        // TIMERSTOP(2)

        // time += (time0 + time1 + time2) / 1000.f;
        // cur += (time0 + time1 + time2) / 1000.f;
        std::cout << "enter moving-based heuristics...\n";
        // gridsize = UP_DIV(workLen, blocksize);
        if (cur_iter >= optcfgs.switchToMergeMoveLevel) { // 1 for human_gene2
            thrust::device_ptr<tmpNode_nouvm> zero_ptr(zeroNodeList);
            thrust::device_ptr<tmpNode_nouvm> one_ptr(nonzeroNodeList);
            TIMERSTART(2)
            if (optcfgs.testDeterminism) {
                thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG_non_det());
                thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG_non_det());
            } else {
                thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmpG());
                thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmpG());
            }
            TIMERSTOP(2)
            unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
            gridsize = UP_DIV(workLen, blocksize);
            TIMERSTART(3)
            performNodeSwapInShorterLength<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen);
            TIMERSTOP(3)
            time += (time0 + time1 + time2 + time3) / 1000.f;
            cur += (time0 + time1 + time2 + time3) / 1000.f;
        } else {
            unsigned nodeListLen = zeroW[0] + nonzeroW[0];
            tmpNode_nouvm* mergeNodeList;
            CHECK_ERROR(cudaMalloc((void**)&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
            // CHECK_ERROR(cudaMallocManaged(&mergeNodeList, nodeListLen * sizeof(tmpNode_nouvm)));
            CHECK_ERROR(cudaMemset(mergeNodeList, 0, nodeListLen * sizeof(tmpNode_nouvm)));
            TIMERSTART(2)
            thrust::copy(thrust::device, zeroNodeList, zeroNodeList+zeroW[0], mergeNodeList);
            thrust::copy(thrust::device, nonzeroNodeList, nonzeroNodeList+nonzeroW[0], mergeNodeList+zeroW[0]);
            thrust::sort(thrust::device, mergeNodeList, mergeNodeList + nodeListLen, cmpGbyW_d());
            TIMERSTOP(2)
            gridsize = UP_DIV(nodeListLen, blocksize);
            TIMERSTART(3)
            performMergingMoves<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, hgr->hedgeNum, mergeNodeList, nodeListLen);
            TIMERSTOP(3)
            CHECK_ERROR(cudaFree(mergeNodeList));
            time += (time0 + time1 + time2 + time3) / 1000.f;
            cur += (time0 + time1 + time2 + time3) / 1000.f;
        }
        std::cout << "time:" << time << " s.\n";
        pass++;
    }
    TIMERSTART(4)
    thrust::fill(thrust::device, hgr->nodes + N_COUNTER1(hgr->nodeNum), hgr->nodes + N_COUNTER1(hgr->nodeNum) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    CHECK_ERROR(cudaFree(nonzeroNodeList));
    CHECK_ERROR(cudaFree(zeroNodeList));
    CHECK_ERROR(cudaFree(zeroW));
    CHECK_ERROR(cudaFree(nonzeroW));
    time += time4 / 1000.f;
    cur += time4 / 1000.f;
}

// TODO.
void refine_no_uvm_with_movegain_verify(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, float& other_time, unsigned int K, int comb_len, float ratio, float imbalance, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;   
    }
    int nonzeroPartWeight = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[i + N_PARTITION(hgr)] > 0) {
            nonzeroPartWeight += hgr->nodes[i + N_WEIGHT(hgr)];
        }
    }
    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int hi;
    if (optcfgs.useBalanceRelax) {
        hi = (1 + tol) * hgr->totalWeight / (2 + tol);
        std::cout << ((1 + tol) * 1.f * hgr->totalWeight / (2 + tol)) / (hgr->totalWeight / K) << "\n";
    }
    if (optcfgs.makeBalanceExceptFinestLevel) {
        cur_iter > 0 ? hi = (1 + imbalance / 100) * (hgr->totalWeight / K) : hi = (1 + tol) * hgr->totalWeight / (2 + tol);
    }
    const int lo = hgr->totalWeight - hi;
    int bal      = nonzeroPartWeight;
    std::cout << bal << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    // tmpNode_nouvm *zeroNodeList, *nonzeroNodeList;
    // CHECK_ERROR(cudaMalloc((void**)&zeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    // CHECK_ERROR(cudaMalloc((void**)&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    tmpNode_nouvm *candNodeList;
    CHECK_ERROR(cudaMalloc((void**)&candNodeList, hgr->nodeNum * sizeof(tmpNode_nouvm)));
    unsigned *candCount;
    CHECK_ERROR(cudaMallocManaged(&candCount, sizeof(unsigned)));

    int* delta_gains;
    CHECK_ERROR(cudaMalloc((void**)&delta_gains, pow(2, comb_len) * sizeof(int)));
    int *best_gain;
    CHECK_ERROR(cudaMallocManaged(&best_gain, sizeof(int)));
    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS1(hgr->nodeNum), hgr->nodes + N_FS1(hgr->nodeNum) + 2 * hgr->nodeNum, 0);
        init_move_gain<<<gridsize, blocksize>>>(hgr->hedges, hgr->nodes, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
        TIMERSTOP(0)

        // zeroW[0] = 0, nonzeroW[0] = 0;
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        // createTwoNodeLists<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        createCandNodeListsWithSrcPartition<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, candNodeList, candCount);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << candCount[0] << "\n";

        TIMERSTART(2)
        thrust::sort(thrust::device, candNodeList, candNodeList + candCount[0], cmpGbyW_d());
        TIMERSTOP(2)
        

        std::cout << "time:" << time << " s.\n";
        pass++;
        
    }
    // TIMERSTART(4)
    // thrust::fill(thrust::device, hgr->nodes + N_COUNTER1(hgr->nodeNum), hgr->nodes + N_COUNTER1(hgr->nodeNum) + hgr->nodeNum, 0);
    // TIMERSTOP(4)
    // CHECK_ERROR(cudaFree(nonzeroNodeList));
    // CHECK_ERROR(cudaFree(zeroNodeList));
    CHECK_ERROR(cudaFree(delta_gains));
    CHECK_ERROR(cudaFree(candNodeList));
    CHECK_ERROR(cudaFree(candCount));
    CHECK_ERROR(cudaFree(zeroW));
    CHECK_ERROR(cudaFree(nonzeroW));
    // time += time4 / 1000.f;
    // cur += time4 / 1000.f;
}

