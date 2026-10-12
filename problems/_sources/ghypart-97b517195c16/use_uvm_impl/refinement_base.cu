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


void parallel_refine(Hypergraph* hgr, unsigned refineTo, float& time, float& cur, int cur_iter, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "(): " << cur_iter << "\n";
    unsigned *zeroW, *nonzeroW;
    CHECK_ERROR(cudaMallocManaged(&zeroW, sizeof(unsigned)));
    CHECK_ERROR(cudaMallocManaged(&nonzeroW, sizeof(unsigned)));
    // std::cout << "maxNodeWeight:" << hgr->maxWeight << ", minNodeWeight:" << hgr->minWeight << "\n";
    if (optcfgs.changeRefToParamLevel) {
        cur_iter < optcfgs.changeRefToParamLevel ? refineTo = optcfgs.refineIterPerLevel : refineTo = 2;   
    }
    unsigned pass = 0;
    while (pass < refineTo) {
        int blocksize = 128;
        int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        TIMERSTART(0)
        thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
        thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
        initGains<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
        TIMERSTOP(0)

        zeroW[0] = 0, nonzeroW[0] = 0;
        tmpNode *zeroNodeList, *nonzeroNodeList;
        CHECK_ERROR(cudaMallocManaged(&zeroNodeList, hgr->nodeNum * sizeof(tmpNode)));
        CHECK_ERROR(cudaMallocManaged(&nonzeroNodeList, hgr->nodeNum * sizeof(tmpNode)));
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
        // thrust::sort(thrust::device, zeroNodeList, zeroNodeList + zeroW[0], mycmp());
        // thrust::sort(thrust::device, nonzeroNodeList, nonzeroNodeList + nonzeroW[0], mycmp());
        TIMERSTOP(2)

        unsigned workLen = zeroW[0] <= nonzeroW[0] ? 2 * zeroW[0] : 2 * nonzeroW[0];
        gridsize = UP_DIV(workLen, blocksize);
        TIMERSTART(3)
        parallelSwapNodes<<<gridsize, blocksize>>>(hgr, zeroNodeList, nonzeroNodeList, zeroW, nonzeroW, workLen);
        TIMERSTOP(3)
        time += (time0 + time1 + time2 + time3) / 1000.f;
        cur += (time0 + time1 + time2 + time3) / 1000.f;
        std::cout << "time:" << time << " s.\n";
        pass++;
        
        CHECK_ERROR(cudaFree(zeroNodeList));
        CHECK_ERROR(cudaFree(nonzeroNodeList));
    }
    TIMERSTART(4)
    thrust::fill(hgr->nodes + N_COUNTER(hgr), hgr->nodes + N_COUNTER(hgr) + hgr->nodeNum, 0);
    TIMERSTOP(4)
    time += time4 / 1000.f;
    cur += time4 / 1000.f;
    // std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
}

void parallel_balance(Hypergraph* hgr, float ratio, unsigned int K, float imbalance, float& time, float& cur, int& rebalance, int cur_iter, OptionConfigs& optcfgs) {
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
    const int hi = (1 + tol) * hgr->totalWeight / (2 + tol); // 55 / 100
    // const int hi = (1 + imbalance / 100) * (hgr->totalWeight / K);
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
            
            thrust::device_ptr<tmpNode> zero_ptr(nodelistz);
            // sorting each bucket in parallel
            TIMERSTART(2)
            for (int i = 0; i < 101; ++i) {
                if (bucketcnt[i] > 1) {
                    cudaStream_t stream;
                    cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
                    thrust::sort(thrust::cuda::par.on(stream), nodelistz + i * hgr->nodeNum, nodelistz + i * hgr->nodeNum + bucketcnt[i], cmpGbyW());
                    CHECK_ERROR(cudaStreamSynchronize(stream));
                    cudaStreamDestroy(stream);
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
                    hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                    bal += hgr->nodes[nodelistz[j * hgr->nodeNum + k].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                    if (bal >= lo) {
                        // std::cout << __LINE__ << " break balance!!!\n";
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
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            cur += (time0 + time1 + time2) / 1000.f + elapsed;
            // std::cout << "elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal << ", lo:" << lo << "\n";
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
                    // std::cout << __LINE__ << " break balance!!!\n";
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
            // std::cout << "@elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            std::cout << "@bal:" << bal << ", lo:" << lo << "\n";
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
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            cur += (time0 + time1 + time2) / 1000.f + elapsed;
            // std::cout << "elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "time:" << time << " s.\n";
            std::cout << "bal:" << bal << ", lo:" << lo << "\n";
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
            // std::cout << "@elapsed time: " << elapsed << " s.\n";
            std::cout << __LINE__ << "@time:" << time << " s.\n";
            std::cout << "@bal:" << bal << ", lo:" << lo << "\n";
            CHECK_ERROR(cudaFree(nodelisto));
            CHECK_ERROR(cudaFree(negGainlisto));
            CHECK_ERROR(cudaFree(bucketcnt));
            if (bal <= hi) {
                break;
            }
        }
        // CHECK_ERROR(cudaFree(bucketcnt));
    }
    // std::cout << "rebalance: current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
}

