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

std::ofstream refine_move1("../debug/refine_move_node_info.txt");
void refinement_opt2(Hypergraph* hgr, unsigned refineTo, unsigned int K, float imbalance, float& time, float& cur, int cur_iter, float ratio, int iterNum, OptionConfigs& optcfgs) {
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
    // if (cur_iter > 0) {
    // imbalance *= 1.25;
    // }
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
        unsigned weight0 = 0;
        unsigned weight1 = 0;
        for (int i = 0; i < workLen / 2; ++i) {
            weight0 += zeroNodeList[i].weight;
            weight1 += nonzeroNodeList[i].weight;
        }
        std::cout << "after sorting, in common length[" << workLen / 2 << "], candidates weight in part0: " << weight0 << ", candidates weight in part1: " << weight1 << "\n";
        unsigned nodeListLen = zeroW[0] + nonzeroW[0];
#if 1
        int *move_flag;
        CHECK_ERROR(cudaMallocManaged(&move_flag, hgr->nodeNum * sizeof(int)));
        for (int i = 0; i < nodeListLen; ++i) {
            if (i < zeroW[0]) {
                move_flag[zeroNodeList[i].nodeid - hgr->hedgeNum] = 1;
                zeroNodeList[i].move_direction = 1;
            } else {
                move_flag[nonzeroNodeList[i-zeroW[0]].nodeid - hgr->hedgeNum] = -1;
                nonzeroNodeList[i-zeroW[0]].move_direction = -1;
            }
        }
        TIMERSTART(_tmp)
        reComputeGains<<<UP_DIV(nodeListLen, blocksize), blocksize>>>(hgr, hgr->hedgeNum, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, move_flag, nodeListLen/*, mergeNodeList*/);
        TIMERSTOP(_tmp)

        unsigned zeroPartPositiveNum = 0;
        unsigned nonzeronPartPositiveNum = 0;
        for (int i = 0; i < nodeListLen; ++i) {
            if (i < zeroW[0]) {
                if (zeroNodeList[i].real_gain > 0) {
                    zeroPartPositiveNum++;
                }
            } else {
                if (nonzeroNodeList[i-zeroW[0]].real_gain > 0) {
                    nonzeronPartPositiveNum++;
                }
            }
        }
        unsigned realPositiveNum = zeroPartPositiveNum + nonzeronPartPositiveNum;
        std::cout << "currently, zeroPart positive num: " << zeroPartPositiveNum << ", nonzeroPart positive num: " << nonzeronPartPositiveNum << "\n";
            
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
            
#endif
        // gridsize = UP_DIV(workLen, blocksize);
        TIMERSTART(3)
        // parallelSwapNodes<<<UP_DIV(workLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen);
        // performRealMoves<<<UP_DIV(nodeListLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, nodeListLen);
        // parallelMoveNodes<<<UP_DIV(workLen, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, workLen/*, reduction*/);
        // parallelMoveNodes1<<<UP_DIV(realPositiveNum, blocksize), blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroPartPositiveNum, nonzeronPartPositiveNum, realPositiveNum);
        TIMERSTOP(3)
        int processed = 0;
        refine_move1 << "iteration " << cur_iter << ":\n";
        refine_move1 << "pass: " << pass << "\n";
        unsigned init_edgecut = computeHyperedgeCut(hgr);
        std::cout << "enter moving-based heuristics...\n";
        // if (cur_iter < 5) {
        thrust::sort(thrust::device, zero_ptr, zero_ptr + zeroW[0], mycmp1());
        thrust::sort(thrust::device, one_ptr, one_ptr + nonzeroW[0], mycmp1());
        while (processed < realPositiveNum/* && (bal >= lo && bal <= hi)*/) {
            if (processed < zeroPartPositiveNum) {
                unsigned accu = bal + zeroNodeList[processed].weight;
                if (accu >= lo && accu <= hi) {
                    hgr->nodes[zeroNodeList[processed].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                    bal += zeroNodeList[processed].weight;
                    processed++;
                    refine_move1 << "0 to 1: " << zeroNodeList[processed].nodeid << ", gain:" << zeroNodeList[processed].gain
                                << ", real_gain:" << zeroNodeList[processed].real_gain << ", weight:" << zeroNodeList[processed].weight << "\n";
                } else {
                    break;
                }
            } else if (processed >= zeroPartPositiveNum) {
                unsigned accu = bal - nonzeroNodeList[processed - zeroPartPositiveNum].weight;
                if (accu >= lo && accu <= hi) {
                    hgr->nodes[nonzeroNodeList[processed - zeroPartPositiveNum].nodeid - hgr->hedgeNum + N_PARTITION(hgr)] = 0;
                    bal -= nonzeroNodeList[processed - zeroPartPositiveNum].weight;
                    processed++;
                    refine_move1 << "1 to 0: " << nonzeroNodeList[processed - zeroPartPositiveNum].nodeid << ", gain:" << nonzeroNodeList[processed - zeroPartPositiveNum].gain
                                << ", real_gain:" << nonzeroNodeList[processed - zeroPartPositiveNum].real_gain << ", weight:" << nonzeroNodeList[processed - zeroPartPositiveNum].weight << "\n";
                } else {
                    break;
                }
            }
        }

        std::cout << "# of processed moves: " << processed << "\n";
#if 0
        if (cur_iter == iterNum && pass == 0) {
            std::ofstream debug("../debug/gain_after_tentative_move.txt");
            for (int i = 0; i < workLen / 2; ++i) {
                unsigned nodeid = zeroNodeList[i].nodeid;
                int tmp_gain = 0;
                int tmp_FS = 0;
                int tmp_TE = 0;
                for (int j = 0; j < hgr->nodes[N_DEGREE(hgr) + nodeid - hgr->hedgeNum]; ++j) {
                    unsigned hedgeid = hgr->incident_nets[hgr->nodes[N_OFFSET(hgr) + nodeid - hgr->hedgeNum] + j];
                    unsigned degree = hgr->hedges[E_DEGREE(hgr) + hedgeid];
                    int p1 = 0;
                    int p2 = 0;
                    for (int k = 0; k < degree; ++k) {
                        unsigned neigh = hgr->adj_list[hgr->hedges[hedgeid + E_OFFSET(hgr)] + k];
                        if (neigh != nodeid) {
                            int part = hgr->nodes[neigh - hgr->hedgeNum + N_PARTITION(hgr)];
                            part == 0 ? p1++ : p2++;
                        }
                    }
                    if (nodeid == 928175) {
                        debug << "hedgeid:" << hedgeid << ", p1:" << p1 << ", p2:" << p2 << "\n";
                    }
                    if (p1 == degree - 1) {
                        tmp_gain++;
                        tmp_FS++;
                    } else if (p2 == degree - 1) {
                        tmp_gain--;
                        tmp_TE++;
                    }
                }
                // debug << "nodeid: " << nodeid << ", current_gain: " << tmp_gain << "\n";
                if (nodeid == 928175) {
                    std::cout << "nodeid: " << nodeid << ", current_part: " << hgr->nodes[nodeid - hgr->hedgeNum + N_PARTITION(hgr)]
                      << ", tmp_FS: " << tmp_FS << ", tmp_TE: " << tmp_TE << "\n";
                }
            }
        }
#endif
        time += (time0 + time1 + time2 + time3) / 1000.f;
        cur += (time0 + time1 + time2 + time3) / 1000.f;
        std::cout << "time:" << time << " s.\n";
        pass++;

        CHECK_ERROR(cudaFree(move_flag));
        CHECK_ERROR(cudaFree(zeroNodeList));
        CHECK_ERROR(cudaFree(nonzeroNodeList));
        std::cout << "current_bal: " << bal << "\n";
        std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
    }
    // if (cur_iter == iterNum) {
    //     std::ofstream debug("../debug/track_moves_refinement.txt");
    //     for (int i = 0; i < track_moves.size(); ++i) {
    //         debug << track_moves[i] << "\n";
    //     }
    // }
    TIMERSTART(4)
    thrust::fill(hgr->nodes + N_COUNTER(hgr), hgr->nodes + N_COUNTER(hgr) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    // time += time4 / 1000.f;
    // cur += time4 / 1000.f;
    // std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
}

void rebalancing_opt2(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, int& rebalance, int cur_iter, int iterNum, OptionConfigs& optcfgs) {
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
    int hi = (1 + tol) * hgr->totalWeight / (2 + tol); // 55 / 100
    if (!optcfgs.useBipartRatioComputation) {
        hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
    }
    const int lo = hgr->totalWeight - hi;
    int bal      = nonzeroPartWeight;
    std::cout << "nonzeroCnt:" << nonzeroCnt << "\n";
    std::cout << bal << ", " << hi << ", " << lo << ", " << tol << ", " << ratio << "\n";
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
            thrust::device_ptr<tmpNode> zero_ptr(nodelistz);
            // sorting each bucket in parallel
            TIMERSTART(2)
            for (int i = 0; i < 101; ++i) {
                total_count += bucketcnt[i];
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], cmpGbyW());
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
                    if (min_element > bucketcnt[i]) min_element = bucketcnt[i];
                    if (max_element < bucketcnt[i]) max_element = bucketcnt[i];
                }
            }
            TIMERSTOP(2)
            std::cout << "totally, there are " << total_count << " waiting move candidates!!!\n";
            
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
                    hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                    bal += hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                    if (bal >= lo) {
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
            // std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
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
                    thrust::sort(thrust::cuda::par.on(stream), nodelisto + i * hgr->nodeNum, nodelisto + i * hgr->nodeNum + bucketcnt[i], cmpGbyW());
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
                    if (bal <= hi) {
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
            std::cout << "bal:" << bal << ", lo:" << lo << "\n";
            // std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
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
    std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
}

