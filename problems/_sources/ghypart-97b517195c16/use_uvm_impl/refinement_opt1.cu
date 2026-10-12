#include <iostream>
#include "utility/utils.cuh"
#include "kernels/refinement_kernels.cuh"
#include "include/refinement_impl.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include <sys/time.h>
#include <algorithm>
#include <bits/stdc++.h>

bool canRelax = false;
// std::ofstream track("track_moves_refinement.txt");
std::ofstream refine_move("../debug/refine_move_node_info.txt");
std::ofstream balance_move("../debug/rebalance_move_node_info.txt");
// std::vector<int> track_moves;
void refinement_opt1(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "(): " << cur_iter << "\n";
    int nonzeroPartWeight = 0;
    int nonzeroCnt = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[i + N_PARTITION(hgr)] > 0) {
            nonzeroPartWeight += hgr->nodes[i + N_WEIGHT(hgr)];
            nonzeroCnt++;
        }
    }
    std::cout << "nonzeroCnt:" << nonzeroCnt << "\n";
    int zeroCnt = hgr->nodeNum - nonzeroCnt;
    int zeroPartWeight = hgr->totalWeight - nonzeroPartWeight;
    std::cout << "totalweight:" << hgr->totalWeight << ", part0_weight:" << zeroPartWeight << ", part1_weight:" << nonzeroPartWeight << "\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    std::cout << "maxNodeWeight:" << hgr->maxWeight << ", minNodeWeight:" << hgr->minWeight << "\n";
    unsigned pass = 0;

    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int hi = (1 + tol) * hgr->totalWeight / (2 + tol);
    std::cout << ((1 + tol) * 1.f * hgr->totalWeight / (2 + tol)) / (hgr->totalWeight / K) << "\n";

    const int lo = hgr->totalWeight - hi;
    int bal      = nonzeroPartWeight;
    std::cout << bal << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    
    std::string file0 = "../debug/iter" + std::to_string(cur_iter) + "_move_gain_part0.txt";
    std::ofstream debug0(file0);
    std::string file1 = "../debug/iter" + std::to_string(cur_iter) + "_move_gain_part1.txt";
    std::ofstream debug1(file1);
    std::string file2 = "../debug/iter" + std::to_string(cur_iter) + "_move_gain_merge.txt";
    std::ofstream debug2(file2);
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        // if (pass > 0 && cur_iter == 0) {
        //     std::ofstream debug0("finest_level_part0_gain.txt");
        //     std::ofstream debug1("finest_level_part1_gain.txt");
        //     for (int i = 0; i < hgr->nodeNum; ++i) {
        //         if (hgr->nodes[N_PARTITION(hgr) + i] == 0) {
        //             debug0 << "id:" << i << ", gain:" << getGains(hgr, i) << ", weight:" << hgr->nodes[N_WEIGHT(hgr) + i] << "\n";
        //         }
        //     }
        // }
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
        thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
        initGains<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
        TIMERSTOP(0)

        zeroW[0] = 0, nonzeroW[0] = 0;
        tmpNode *zeroNodeList, *nonzeroNodeList;
        CHECK_ERROR(cudaMallocManaged(&zeroNodeList, hgr->nodeNum * sizeof(tmpNode)));
        CHECK_ERROR(cudaMallocManaged(&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode)));
        CHECK_ERROR(cudaMemset(zeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode)));
        CHECK_ERROR(cudaMemset(nonzeroNodeList, 0, hgr->nodeNum * sizeof(tmpNode)));
        gridsize = UP_DIV(hgr->nodeNum, blocksize);
        TIMERSTART(1)
        createNodeLists<<<gridsize, blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW);
        TIMERSTOP(1)
        std::cout << __LINE__ << ":" << zeroW[0] << ", " << nonzeroW[0] << "\n";
#if 0
        if (canRelax) {
            unsigned *zeroW1, *nonzeroW1;
            CHECK_ERROR(cudaMallocManaged(&zeroW1, sizeof(unsigned)));
            CHECK_ERROR(cudaMallocManaged(&nonzeroW1, sizeof(unsigned)));
            zeroW1[0] = 0, nonzeroW1[0] = 0;
            tmpNode *zeroNodeList1, *nonzeroNodeList1;
            CHECK_ERROR(cudaMallocManaged(&zeroNodeList1, zeroCnt * sizeof(tmpNode)));
            CHECK_ERROR(cudaMallocManaged(&nonzeroNodeList1, nonzeroCnt * sizeof(tmpNode)));
            TIMERSTART(_ss)
            createNodeLists1<<<gridsize, blocksize>>>(hgr, zeroNodeList1, nonzeroNodeList1, zeroW1, nonzeroW1);
            TIMERSTOP(_ss)
            std::cout << __LINE__ << ":" << zeroW1[0] << ", " << nonzeroW1[0] << "\n";

            // int *move_flag1;
            // CHECK_ERROR(cudaMallocManaged(&move_flag1, hgr->nodeNum * sizeof(int)));
            // for (int i = 0; i < hgr->nodeNum; ++i) {
            //     if (i < zeroW[0]) {
            //         move_flag1[zeroNodeList1[i].nodeid - hgr->hedgeNum] = 1;
            //     } else {
            //         move_flag1[nonzeroNodeList1[i-zeroW[0]].nodeid - hgr->hedgeNum] = -1;
            //     }
            // }
            thrust::device_ptr<tmpNode> zero_ptr1(zeroNodeList1);
            thrust::device_ptr<tmpNode> one_ptr1(nonzeroNodeList1);
            TIMERSTART(_test)
            thrust::sort(thrust::device, zero_ptr1, zero_ptr1 + zeroW1[0], mycmp());
            thrust::sort(thrust::device, one_ptr1, one_ptr1 + nonzeroW1[0], mycmp());
            // reComputeGains<<<UP_DIV(hgr->nodeNum, blocksize), blocksize>>>(hgr, hgr->hedgeNum, zeroNodeList1, nonzeroNodeList1, zeroW1, nonzeroW1, move_flag1, hgr->nodeNum);
            TIMERSTOP(_test)

            std::ofstream debug0("../debug/finest_level_part0_gain.txt");
            std::ofstream debug1("../debug/finest_level_part1_gain.txt");
            for (int i = 0; i < zeroCnt; ++i) {
                debug0 << "part0: " << zeroNodeList1[i].nodeid - hgr->hedgeNum << ": gain:" << zeroNodeList1[i].gain << ", real_gain:" << zeroNodeList1[i].real_gain 
                       << ", weight:" << zeroNodeList1[i].weight << ", ratio:" << (double)(zeroNodeList1[i].real_gain * (1.0f / zeroNodeList1[i].weight))
                       << ", degree:" << hgr->nodes[N_DEGREE(hgr) + zeroNodeList1[i].nodeid - hgr->hedgeNum] << ", parent:" << hgr->nodes[N_PARENT(hgr) + zeroNodeList1[i].nodeid - hgr->hedgeNum] << "\n";
            }
            for (int i = 0; i < nonzeroCnt; ++i) {
                debug1 << "part1: " << nonzeroNodeList1[i].nodeid - hgr->hedgeNum << ": gain:" << nonzeroNodeList1[i].gain << ", real_gain:" << nonzeroNodeList1[i].real_gain 
                       << ", weight:" << nonzeroNodeList1[i].weight << ", ratio:" << (double)(nonzeroNodeList1[i].real_gain * (1.0f / nonzeroNodeList1[i].weight))
                       << ", degree:" << hgr->nodes[N_DEGREE(hgr) + nonzeroNodeList1[i].nodeid - hgr->hedgeNum] << ", parent:" << hgr->nodes[N_PARENT(hgr) + nonzeroNodeList1[i].nodeid - hgr->hedgeNum] << "\n";
            }
            // CHECK_ERROR(cudaFree(move_flag1));
            CHECK_ERROR(cudaFree(zeroNodeList1));
            CHECK_ERROR(cudaFree(nonzeroNodeList1));
        }
#endif
        thrust::device_ptr<tmpNode> zero_ptr(zeroNodeList);
        thrust::device_ptr<tmpNode> one_ptr(nonzeroNodeList);
        TIMERSTART(2)
        thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmp());
        thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmp());
        // thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], cmpGbyW());
        // thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], cmpGbyW());
        // thrust::sort(thrust::device, zeroNodeList, zeroNodeList + zeroW[0], mycmp());
        // thrust::sort(thrust::device, nonzeroNodeList, nonzeroNodeList + nonzeroW[0], mycmp());
        TIMERSTOP(2)

        unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        unsigned nodeListLen = zeroW[0] + nonzeroW[0];
#if 1
        tmpNode* mergeNodeList;
        CHECK_ERROR(cudaMallocManaged(&mergeNodeList, nodeListLen * sizeof(tmpNode)));
        CHECK_ERROR(cudaMemset(mergeNodeList, 0, nodeListLen * sizeof(tmpNode)));

        for (int i = 0; i < nodeListLen; ++i) {
            if (i < zeroW[0]) {
                zeroNodeList[i].move_direction = 1;
            } else {
                nonzeroNodeList[i-zeroW[0]].move_direction = -1;
            }
        }

        TIMERSTART(_tmp)
        thrust::copy(thrust::device, zeroNodeList, zeroNodeList+zeroW[0], mergeNodeList);
        thrust::copy(thrust::device, nonzeroNodeList, nonzeroNodeList+nonzeroW[0], mergeNodeList+zeroW[0]);
        thrust::sort(thrust::device, mergeNodeList, mergeNodeList + nodeListLen, cmpGbyW());
        TIMERSTOP(_tmp)
        // for (int i = 0; i < nodeListLen; ++i) {
        //     std::cout << mergeNodeList[i].nodeid << " " << mergeNodeList[i].real_gain << " " << mergeNodeList[i].weight << "\n";
        // }
        
        debug0 << "pass: " << pass << "\n";
        for (int i = 0; i < zeroW[0]; ++i) {
            debug0 << "part0: " << zeroNodeList[i].nodeid << ": " << zeroNodeList[i].gain << ", " << zeroNodeList[i].real_gain 
                    << ", " << zeroNodeList[i].weight << ", " << (double)(zeroNodeList[i].real_gain * (1.0f / zeroNodeList[i].weight)) << "\n";
        }
        
        debug1 << "pass: " << pass << "\n";
        for (int i = 0; i < nonzeroW[0]; ++i) {
            debug1 << "part1: " << nonzeroNodeList[i].nodeid << ": " << nonzeroNodeList[i].gain << ", " << nonzeroNodeList[i].real_gain 
                    << ", " << nonzeroNodeList[i].weight << ", " << (double)(nonzeroNodeList[i].real_gain * (1.0f / nonzeroNodeList[i].weight)) << "\n";
        }

        debug2 << "pass: " << pass << "\n";
        for (int i = 0; i < nodeListLen; ++i) {
            debug2 << "node: " << mergeNodeList[i].nodeid << ": " << mergeNodeList[i].gain << ", " << mergeNodeList[i].real_gain 
                    << ", " << mergeNodeList[i].weight << ", " << (double)(mergeNodeList[i].gain * (1.0f / mergeNodeList[i].weight)) << ", direction: " << mergeNodeList[i].move_direction << "\n";
        }
#endif
        // gridsize = UP_DIV(workLen, blocksize);
        TIMERSTART(3)
        // parallelSwapNodes<<<UP_DIV(workLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen);
        // performRealMoves<<<UP_DIV(nodeListLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, nodeListLen);
        // parallelMoveNodes<<<UP_DIV(workLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, workLen/*, reduction*/);
        // parallelMoveNodes1<<<UP_DIV(realPositiveNum, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroPartPositiveNum, nonzeronPartPositiveNum, realPositiveNum);
        TIMERSTOP(3)
        int processed = 0;
        refine_move << "iteration " << cur_iter << ":\n";
        refine_move << "pass: " << pass << "\n";
        unsigned init_edgecut = computeHyperedgeCut(hgr);
        std::cout << "enter moving-based heuristics...\n";
        if (cur_iter >= optcfgs.switchToMergeMoveLevel) {
        // if (cur_iter >= 3) {
            for (int i = 0; i < workLen / 2; ++i) {
                // if (cur_iter >= 3 && zeroNodeList[i].weight == hgr->maxWeight) {
                //     continue;
                // }
                // refine_move << "swap " << zeroNodeList[i].nodeid << "[0](" << zeroNodeList[i].weight << ") <---> " << nonzeroNodeList[i].nodeid << "[1](" << nonzeroNodeList[i].weight << ")\n";
                hgr->nodes[N_PARTITION(hgr) + zeroNodeList[i].nodeid - hgr->hedgeNum] = 1;
                bal += zeroNodeList[i].weight;
                // unsigned curr_edgecut = computeHyperedgeCut(hgr);
                // refine_move << "after move from 0 to 1, current edge cut quality:" << curr_edgecut << ", current_bal: " << bal << "\n";
                hgr->nodes[N_COUNTER(hgr) + zeroNodeList[i].nodeid - hgr->hedgeNum]++;
            }
            for (int i = 0; i < workLen / 2; ++i) {
                hgr->nodes[N_PARTITION(hgr) + nonzeroNodeList[i].nodeid - hgr->hedgeNum] = 0;
                bal -= nonzeroNodeList[i].weight;
                // unsigned curr_edgecut = computeHyperedgeCut(hgr);
                // refine_move << "after move from 1 to 0, current edge cut quality:" << curr_edgecut << ", current_bal: " << bal << "\n";
                hgr->nodes[N_COUNTER(hgr) + nonzeroNodeList[i].nodeid - hgr->hedgeNum]++;
            }
        } else {
            std::cout << "enter merging move..\n";
            for (int i = 0; i < nodeListLen; ++i) {
                // if (cur_iter > 0 && zeroNodeList[i].weight == hgr->maxWeight) {
                //     continue;
                // }
                if (mergeNodeList[i].move_direction == 1) {
                    hgr->nodes[N_PARTITION(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum] = 1;
                    bal += mergeNodeList[i].weight;
                    hgr->nodes[N_COUNTER(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum]++;
                    // unsigned curr_edgecut = computeHyperedgeCut(hgr);
                    // // std::cout << "after move from 0 to 1, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // if (init_edgecut > curr_edgecut) {
                    //     init_edgecut = curr_edgecut;
                    //     // std::cout << "after move from 0 to 1, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // } else { // revert
                    //     hgr->nodes[N_PARTITION(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum] = 0;
                    //     hgr->nodes[N_COUNTER(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum]--;
                    //     bal -= mergeNodeList[i].weight;
                    //     continue;
                    // }
                } else if (mergeNodeList[i].move_direction == -1) {
                    hgr->nodes[N_PARTITION(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum] = 0;
                    bal -= mergeNodeList[i].weight;
                    hgr->nodes[N_COUNTER(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum]++;
                    // unsigned curr_edgecut = computeHyperedgeCut(hgr);
                    // // std::cout << "after move from 1 to 0, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // if (init_edgecut > curr_edgecut) {
                    //     init_edgecut = curr_edgecut;
                    //     // std::cout << "after move from 1 to 0, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // } else { // revert
                    //     hgr->nodes[N_PARTITION(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum] = 1;
                    //     hgr->nodes[N_COUNTER(hgr) + mergeNodeList[i].nodeid - hgr->hedgeNum]--;
                    //     bal += mergeNodeList[i].weight;
                    //     continue;
                    // }
                }
            }
        }
        std::cout << "# of processed moves: " << processed << "\n";

        // if (cur_iter == 0 && (zeroW[0] == 0 || nonzeroW[0] == 0)) {
        //     canRelax = true;
        // }
        time += (time0 + time1 + time2 + time3) / 1000.f;
        cur += (time0 + time1 + time2 + time3) / 1000.f;
        std::cout << "time:" << time << " s.\n";
        pass++;

        CHECK_ERROR(cudaFree(mergeNodeList));
        CHECK_ERROR(cudaFree(zeroNodeList));
        CHECK_ERROR(cudaFree(nonzeroNodeList));
        std::cout << "current_bal: " << bal << "\n";
        std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
    }
    TIMERSTART(4)
    thrust::fill(hgr->nodes + N_COUNTER(hgr), hgr->nodes + N_COUNTER(hgr) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    // time += time4 / 1000.f;
    // cur += time4 / 1000.f;
    // std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
}

std::ofstream rebal_neg("../debug/negative_move_gain_nodes.txt");
void rebalancing_opt1(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "()===========\n";
    int nonzeroPartWeight = 0;
    int nonzeroCnt = 0;
    struct timeval bbeg, eend;
    gettimeofday(&bbeg, NULL);
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[i + N_PARTITION(hgr)] > 0) {
            nonzeroPartWeight += hgr->nodes[i + N_WEIGHT(hgr)];
            nonzeroCnt++;
        }
    }
    gettimeofday(&eend, NULL);
    float elap = (eend.tv_sec - bbeg.tv_sec) + ((eend.tv_usec - bbeg.tv_usec)/1000000.0);
    std::cout << "elapsed time: " << elap << " s.\n";
    time += elap;
    cur += elap;

    float tol    = std::max(ratio, 1 - ratio) - 1; // 10 / 45
    int hi = (1 + tol) * hgr->totalWeight / (2 + tol);
    // if (!optcfgs.useBipartRatioComputation) {
    //     hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
    // }
    const int lo = hgr->totalWeight - hi;
    int bal      = nonzeroPartWeight;
    std::cout << "nonzeroCnt:" << nonzeroCnt << "\n";
    std::cout << bal << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
    int count = 0;
    balance_move << "iteration " << cur_iter << ": ";
    while (1) {
        if (bal >= lo && bal <= hi) {
            break;
        }

        // int blocksize = 128;
        // int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        // TIMERSTART(0)
        // thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
        // thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
        // initGains<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
        // TIMERSTOP(0)

        // unsigned *bucketcnt;
        // CHECK_ERROR(cudaMallocManaged(&bucketcnt, 101 * sizeof(unsigned)));
        // unsigned *negCnt;
        // CHECK_ERROR(cudaMallocManaged(&negCnt, sizeof(unsigned)));
        std::cout << "bal:" << bal << ", hi:" << hi << ", lo:" << lo << "\n";
        if (bal < lo) {
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(0)
            thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
            thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
            initGains<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
            TIMERSTOP(0)

            unsigned *bucketcnt;
            CHECK_ERROR(cudaMallocManaged(&bucketcnt, 101 * sizeof(unsigned)));
            unsigned *negCnt;
            CHECK_ERROR(cudaMallocManaged(&negCnt, sizeof(unsigned)));
            std::cout << "enter bal < lo branch+++++++++\n";
            // placing each node in an appropriate bucket using the gain by weight ratio
            negCnt[0] = 0;
            tmpNode *nodelistz;
            CHECK_ERROR(cudaMallocManaged(&nodelistz, 101 * hgr->nodeNum * sizeof(tmpNode)));
            // CHECK_ERROR(cudaMemset(nodelistz, 0, 101 * hgr->nodeNum * sizeof(tmpNode)));
            tmpNode *negGainlistz;
            CHECK_ERROR(cudaMallocManaged(&negGainlistz, hgr->nodeNum * sizeof(tmpNode)));

            // int blocksize = 128;
            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(1)
            thrust::fill(bucketcnt, bucketcnt + 101, 0);
            placeNodesInBuckets<<<gridsize, blocksize>>>(hgr, nodelistz, bucketcnt, negGainlistz, negCnt, partID);
            TIMERSTOP(1)
            
            int total_count = 0;
            unsigned min_element = INT_MAX;
            unsigned max_element = 0;
            for (int i = 0; i < 101; ++i) {
                total_count += bucketcnt[i];
            }
            int *move_flag;
            CHECK_ERROR(cudaMallocManaged(&move_flag, hgr->nodeNum * sizeof(int)));
            for (int i = 0; i <= 100; i++) {
                for (int j = 0; j < bucketcnt[i]; ++j) {
                    move_flag[nodelistz[i * hgr->nodeNum + j].nodeid - hgr->hedgeNum] = 1;
                }
            }
            dim3 block(1, 128, 1);
            dim3 grid(101, UP_DIV(max_element, block.y), 1);
            TIMERSTART(_tmp)
            reComputeGainInBuckets<<<grid, block>>>(hgr, nodelistz, bucketcnt, total_count, move_flag);
            TIMERSTOP(_tmp)

            thrust::device_ptr<tmpNode> zero_ptr(nodelistz);
            // sorting each bucket in parallel
            TIMERSTART(2)
            for (int i = 0; i < 101; ++i) {
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    // if (i < 11) {
                    thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], cmpGbyW());
                    // } else {
                    //     thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], mycmp3());
                    // }
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
                    if (min_element > bucketcnt[i]) min_element = bucketcnt[i];
                    if (max_element < bucketcnt[i]) max_element = bucketcnt[i];
                }
            }
            TIMERSTOP(2)
            std::cout << "totally, there are " << total_count << " waiting move candidates!!!\n";
            
            // for (int i = 0; i < 101; ++i) {
            //     if (bucketcnt[i] > 1) {
            //         cudaStream_t stream;
            //         cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
            //         thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], mycmp1());
            //         CHECK_ERROR(cudaStreamSynchronize(stream));
            //         cudaStreamDestroy(stream);
            //     }
            // }
            balance_move << "pass: " << count << ": \n";
            std::cout << "pass: " << count << ": \n";
            // int tentative_num = 0;
            // if (cur_iter == 18 && count == 0) {
            //     std::ofstream debug("rebalance_nodelist_movegain.txt");
            //     debug << "bucket 11 contains: " << bucketcnt[11] << " candidates:\n";
                rebal_neg << "iteration " << iterNum << ", pass: " << count << "\n";
                for (int j = 0; j < bucketcnt[11]; ++j) {
                    rebal_neg << "nodeid: " << nodelistz[11 * hgr->nodeNum + j].nodeid << ": gain[" << nodelistz[11 * hgr->nodeNum + j].gain
                                << "], real_gain[" << nodelistz[11 * hgr->nodeNum + j].real_gain << "], weight[" << nodelistz[11 * hgr->nodeNum + j].weight 
                                << "], ratio[" << (double)(nodelistz[11 * hgr->nodeNum + j].real_gain * (1.0f / nodelistz[11 * hgr->nodeNum + j].weight)) << "]\n";
                    // double gainByWeight = (double)(nodelistz[11 * hgr->nodeNum + j].real_gain * (1.0f / nodelistz[11 * hgr->nodeNum + j].weight));
                    // if (gainByWeight > -0.02) {
                    //     tentative_num++;
                    // }
                }
            // }
            // std::cout << "tentative_num: " << tentative_num << "\n";
            
            unsigned i = 0;
            unsigned j = 0;
            
            // now moving nodes from partition 0 to 1
            struct timeval begin, end;
            // unsigned init_edgecut = computeHyperedgeCut(hgr);
            gettimeofday(&begin, NULL);
            while (j < 101) {
                if (bucketcnt[j] == 0) {
                    j++;
                    continue;
                }
                balance_move << "select from bucket[" << j << "], bucket_size is : " << bucketcnt[j] << "\n";
                for (int k = 0; k < bucketcnt[j]; ++k) {
                    // double gainByWeight = (double)(nodelistz[j * hgr->nodeNum + k].real_gain * (1.0f / nodelistz[j * hgr->nodeNum + k].weight));
                    // if (cur_iter > 0 && nodelistz[j * hgr->nodeNum + k].weight == hgr->maxWeight) {
                    //     continue;
                    // }
                    hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                    bal += hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                    // std::cout << "move 0 --> 1, node " << nodelistz[j * hgr->nodeNum + k].nodeid << "(weight:" << nodelistz[j * hgr->nodeNum + k].weight << "), (degree:" << hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_DEGREE(hgr)] << ")\n";
                    // std::cout << "after move from 0 to 1, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // unsigned curr_edgecut = computeHyperedgeCut(hgr);
                    // if (init_edgecut > curr_edgecut) {
                    //     init_edgecut = curr_edgecut;
                    //     std::cout << "move 0 --> 1, node " << nodelistz[j * hgr->nodeNum + k].nodeid << "(" << nodelistz[j * hgr->nodeNum + k].weight << ")\n";
                    //     std::cout << "after move from 0 to 1, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    // } else { // revert
                    //     hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
                    //     bal -= hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                    //     continue;
                    // }
                    // if (track_moves[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum] == -1) {
                    //     std::cout << "node: " << nodelistz[j * hgr->nodeNum + k].nodeid << " is already moved from 1 to 0 in this iteration!!!\n";
                    // }
                    // track_moves[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum] = 1;
                    balance_move << "0 to 1: move " << i << "-th node: " << nodelistz[j * hgr->nodeNum + k].nodeid << ", gain:" << nodelistz[j * hgr->nodeNum + k].gain
                                 << ", real_gain:" << nodelistz[j * hgr->nodeNum + k].real_gain << ", weight:" << nodelistz[j * hgr->nodeNum + k].weight << "\n";
                    if (bal >= lo) {
                        std::cout << "move node " << nodelistz[j * hgr->nodeNum + k].nodeid << " with weight " << nodelistz[j * hgr->nodeNum + k].weight << "\n";
                        // out_move << cur_iter << "," << hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)] << "\n";
                        std::cout << __LINE__ << " break balance!!!\n";
                        break;
                    }
                    i++;
                    if (i > sqrt(hgr->nodeNum)) {
                        break;
                    }
                }
                if (bal >= lo) {
                    break;
                }
                if (i > sqrt(hgr->nodeNum)) {
                    break;
                }
                j++;
            }
            gettimeofday(&end, NULL);
            std::cout << "max bucket:" << max_element << "\n";
            std::cout << "min bucket:" << min_element << "\n";
            // std::sort(bucketcnt, bucketcnt + 101);
            // std::cout << "q1 bucket:" << bucketcnt[101 / 4] << ", med bucket:" << bucketcnt[101 / 2] << ", q3 bucket:" << bucketcnt[101*3/4] << "\n";
            std::cout << "Until " << j << "-th bucket, # processed moves:" << i << "\n";
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            cur += (time0 + time1 + time2) / 1000.f + elapsed;
            std::cout << "elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal << ", lo:" << lo << "\n";
            std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            CHECK_ERROR(cudaFree(move_flag));
            count++;
            if (bal >= lo) {
                break;
            }
            if (i > sqrt(hgr->nodeNum)) {
                continue;
            }

            // moving nodes from nodeListzNegGain
            if (negCnt[0] == 0) {
                continue;
            }
            thrust::device_ptr<tmpNode> negzero_ptr(negGainlistz);
            TIMERSTART(3)
            thrust::sort(/*thrust::device, */negGainlistz, negGainlistz + negCnt[0], cmpGbyW());
            // thrust::sort(thrust::device, negzero_ptr, negzero_ptr + negCnt[0], cmpGbyW());
            TIMERSTOP(3)
            gettimeofday(&begin, NULL);
            for (int k = 0; k < negCnt[0]; ++k) {
                hgr->nodes[negGainlistz[k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                bal += hgr->nodes[negGainlistz[k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                if (bal >= lo) {
                    std::cout << __LINE__ << " break balance!!!\n";
                    break;
                }
                i++;
                if (i > sqrt(hgr->nodeNum)) {
                    break;
                }
            }
            gettimeofday(&end, NULL);
            elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += time3 / 1000.f + elapsed;
            cur += time3 / 1000.f + elapsed;
            std::cout << "@elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            // std::cout << "maximal move node weight " << maxmoveweight << "\n";
            std::cout << "@bal:" << bal << ", lo:" << lo << "\n";
            // std::cout << "@rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            CHECK_ERROR(cudaFree(nodelistz));
            CHECK_ERROR(cudaFree(negGainlistz));
            CHECK_ERROR(cudaFree(bucketcnt));
            if (bal >= lo) {
                break;
            }
        } else { // bal > hi
            rebalance++;
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(0)
            thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
            thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
            initGains<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
            TIMERSTOP(0)

            unsigned *bucketcnt;
            CHECK_ERROR(cudaMallocManaged(&bucketcnt, 101 * sizeof(unsigned)));
            unsigned *negCnt;
            CHECK_ERROR(cudaMallocManaged(&negCnt, sizeof(unsigned)));
            std::cout << "enter bal > hi branch+++++++++\n";
            // placing each node in an appropriate bucket using the gain by weight ratio
            negCnt[0] = 0;
            tmpNode *nodelisto;
            CHECK_ERROR(cudaMallocManaged(&nodelisto, 101 * hgr->nodeNum * sizeof(tmpNode)));
            tmpNode *negGainlisto;
            CHECK_ERROR(cudaMallocManaged(&negGainlisto, hgr->nodeNum * sizeof(tmpNode)));
            
            // int blocksize = 128;
            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(1)
            thrust::fill(bucketcnt, bucketcnt + 101, 0);
            placeNodesInBuckets<<<gridsize, blocksize>>>(hgr, nodelisto, bucketcnt, negGainlisto, negCnt, partID);
            TIMERSTOP(1)
            
            // unsigned min_element = INT_MAX;
            // unsigned max_element = 0;
            thrust::device_ptr<tmpNode> one_ptr(nodelisto);
            // sorting each bucket in parallel
            TIMERSTART(2)
            for (int i = 0; i < 101; ++i) {
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    // if (i < 11) {
                    thrust::sort(thrust::cuda::par.on(stream), nodelisto + i * hgr->nodeNum, nodelisto + i * hgr->nodeNum + bucketcnt[i], cmpGbyW());
                    // } else {
                    //     thrust::sort(thrust::cuda::par.on(stream), nodelisto + i * hgr->nodeNum, nodelisto + i * hgr->nodeNum + bucketcnt[i], mycmp3());
                    // }
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
                    // if (min_element > bucketcnt[i]) min_element = bucketcnt[i];
                    // if (max_element < bucketcnt[i]) max_element = bucketcnt[i];
                }
            }
            TIMERSTOP(2)

            unsigned i = 0;
            unsigned j = 0;
            // now moving nodes from partition 0 to 1
            struct timeval begin, end;
            gettimeofday(&begin, NULL);
            while (j < 101) {
                if (bucketcnt[j] == 0) {
                    j++;
                    continue;
                }
                for (int k = 0; k < bucketcnt[j]; ++k) {
                    hgr->nodes[nodelisto[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
                    bal -= hgr->nodes[nodelisto[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                    // std::cout << "move 1 --> 0, node " << nodelisto[j * hgr->nodeNum + k].nodeid << "(" << nodelisto[j * hgr->nodeNum + k].weight << ")\n";
                    // std::cout << "after move from 1 to 0, current edge cut quality:" << computeHyperedgeCut(hgr) << ", current_bal: " << bal << "\n";
                    if (bal <= hi) {
                        // std::cout << "move node " << nodelisto[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum << " with weight "
                        //           << hgr->nodes[nodelisto[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)] << "\n";
                        // out_move << cur_iter << "," << hgr->nodes[nodelisto[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)] << "\n";
                        std::cout << __LINE__ << " break balance!!!\n";
                        break;
                    }
                    i++;
                    if (i > sqrt(hgr->nodeNum)) {
                        break;
                    }
                }
                if (bal <= hi) {
                    break;
                }
                if (i > sqrt(hgr->nodeNum)) {
                    break;
                }
                j++;
            }
            gettimeofday(&end, NULL);
            // std::cout << "max bucket:" << max_element << "\n";
            // std::cout << "min bucket:" << min_element << "\n";
            // std::sort(bucketcnt, bucketcnt + 101);
            // std::cout << "q1 bucket:" << bucketcnt[101 / 4] << ", med bucket:" << bucketcnt[101 / 2] << ", q3 bucket:" << bucketcnt[101*3/4] << "\n";
            std::cout << "Until " << j << "-th bucket, # processed moves:" << i << "\n";
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            cur += (time0 + time1 + time2) / 1000.f + elapsed;
            std::cout << "elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            // std::cout << "maximal move node weight " << maxmoveweight << "\n";
            std::cout << "bal:" << bal << ", lo:" << lo << "\n";
            std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            if (bal <= hi) {
                break;
            }
            if (i > sqrt(hgr->nodeNum)) {
                continue;
            }

            // moving nodes from nodeListzNegGain
            if (negCnt[0] == 0) {
                continue;
            }
            thrust::device_ptr<tmpNode> negone_ptr(negGainlisto);
            TIMERSTART(3)
            thrust::sort(/*thrust::device, */negGainlisto, negGainlisto + negCnt[0], cmpGbyW());
            // thrust::sort(thrust::device, negone_ptr, negone_ptr + negCnt[0], cmpGbyW());
            TIMERSTOP(3)
            gettimeofday(&begin, NULL);
            for (int k = 0; k < negCnt[0]; ++k) {
                hgr->nodes[negGainlisto[k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
                bal -= hgr->nodes[negGainlisto[k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                if (bal <= hi) {
                    break;
                }
                i++;
                if (i > sqrt(hgr->nodeNum)) {
                    break;
                }
            }
            gettimeofday(&end, NULL);
            elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += time3 / 1000.f + elapsed;
            cur += time3 / 1000.f + elapsed;
            std::cout << "@elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            std::cout << "@bal:" << bal << ", lo:" << lo << "\n";
            // std::cout << "@rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            CHECK_ERROR(cudaFree(nodelisto));
            CHECK_ERROR(cudaFree(negGainlisto));
            CHECK_ERROR(cudaFree(bucketcnt));
            if (bal <= hi) {
                break;
            }
        }
        // CHECK_ERROR(cudaFree(bucketcnt));
    }
}
