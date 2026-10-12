#include <iostream>
#include "utility/utils.cuh"
#include "kernels/partitioning_kernels.cuh"
#include "include/partitioning_impl.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include <sys/time.h>


void partition_opt2(Hypergraph* hgr, unsigned int K, bool use_curr_precision, float& time) {
    std::cout << __FUNCTION__ << "()===========\n";
    TIMERSTART(_)
    thrust::fill(thrust::device, hgr->nodes + N_PARTITION(hgr), hgr->nodes + N_PARTITION(hgr) + hgr->nodeNum, 1);
    TIMERSTOP(_)
    struct timeval bbeg, eend;
    int zeroPartCnt = 0;
    // std::ofstream out0("zeroPart.txt");
    // std::ofstream out1("nonzeroPart.txt");
    gettimeofday(&bbeg, NULL);
    for (int i = 0; i < hgr->hedgeNum; ++i) {
        for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
            hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j]-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
        }
    }
    int zeroPartWeight = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[i + N_PARTITION(hgr)] == 0) {
            if (hgr->nodes[i + N_WEIGHT(hgr)] == hgr->maxWeight) {
                continue;
            }
            zeroPartWeight += hgr->nodes[i + N_WEIGHT(hgr)];
            zeroPartCnt++;
            // out0 << i << ": " << hgr->nodes[i + N_DEGREE(hgr)] << ", " << hgr->nodes[i + N_WEIGHT(hgr)] << "\n";
            // out0 << i << ": " << hgr->nodes[i + N_WEIGHT(hgr)] << "\n";
        }
        // else {
        //     out1 << i << ": " << hgr->nodes[i + N_DEGREE(hgr)] << ", " << hgr->nodes[i + N_WEIGHT(hgr)] << "\n";
        // }
    }
    gettimeofday(&eend, NULL);
    float elap = (eend.tv_sec - bbeg.tv_sec) + ((eend.tv_usec - bbeg.tv_usec)/1000000.0);
    std::cout << "elapsed time: " << elap << " s.\n";
    time += time_ / 1000.f + elap;

    int onePartWeight = 0;
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[i + N_PARTITION(hgr)] == 1) {
            onePartWeight += hgr->nodes[i + N_WEIGHT(hgr)];
        }
    }
    std::cout << "part1's weight: " << onePartWeight << "\n";
    std::cout << "initially, edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
    std::ofstream debug0("../debug/initial_nodes_partition0.txt");
    std::ofstream debug1("../debug/initial_nodes_partition1.txt");
    for (int i = 0; i < hgr->nodeNum; ++i) {
        if (hgr->nodes[N_PARTITION(hgr) + i] == 0) {
            debug0 << "node " << i << ", weight: " << hgr->nodes[N_WEIGHT(hgr) + i] << ", part: " << hgr->nodes[N_PARTITION(hgr) + i] << "\n";
        } else {
            debug1 << "node " << i << ", weight: " << hgr->nodes[N_WEIGHT(hgr) + i] << ", part: " << hgr->nodes[N_PARTITION(hgr) + i] << "\n";
        }
    }
    int total = hgr->totalWeight - hgr->maxWeight;
    int nonzeroPartWeight = total - zeroPartWeight;
    unsigned kvalue        = (K + 1) / 2;
    unsigned targetWeight0 = total * kvalue / K;
    unsigned targetWeight1 = total - targetWeight0;
    std::cout << "totalweight:" << hgr->totalWeight << ", part0_weight:" << zeroPartWeight << ", part1_weight:" << nonzeroPartWeight << "\n";
    std::cout << "targetWeight0:" << targetWeight0 << ", targetWeight1:" << targetWeight1 << "\n";
    std::cout << "zeroPartCnt:" << zeroPartCnt << "\n";
    int ccount = 0;
    if (static_cast<long>(zeroPartWeight) > nonzeroPartWeight) {
        std::cout << "enter move 0 to 1 branch\n";
        int gain = nonzeroPartWeight;
        std::cout << "initial gain: " << gain << "\n";
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(0)
            thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
            thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
            initGain<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
            TIMERSTOP(0)

            count[0] = 0;
            tmpNode* nodeListz;
            CHECK_ERROR(cudaMallocManaged(&nodeListz, hgr->nodeNum * sizeof(tmpNode)));
            CHECK_ERROR(cudaMemset(nodeListz, 0, hgr->nodeNum * sizeof(tmpNode)));

            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 0;
            TIMERSTART(1)
            createNodeList<<<gridsize, blocksize>>>(hgr, nodeListz, count, partID);
            TIMERSTOP(1)
            std::cout << count[0] << "\n";

            // thrust::device_ptr<tmpNode> zero_ptr(nodeListz);
            TIMERSTART(2)
            use_curr_precision ? thrust::sort(thrust::device, nodeListz, nodeListz + count[0], mycmp()) : thrust::sort(thrust::device, nodeListz, nodeListz + count[0], mycmp1());
            TIMERSTOP(2)
#if 1
            if (ccount == 0) {
                std::ofstream debug("../debug/initial_partition_nodelist_info.txt");
                for (int i = 0; i < count[0]; ++i) {
                    debug << "nodeid: " << nodeListz[i].nodeid << ", init_gain: " << nodeListz[i].gain << ", real_gain: "
                          << nodeListz[i].real_gain << ", weight: " << nodeListz[i].weight << ", ratio: "
                          << (float)(nodeListz[i].real_gain * (1.0f / nodeListz[i].weight)) << ", degree: " << hgr->nodes[nodeListz[i].nodeid-hgr->hedgeNum + N_DEGREE(hgr)] << "\n";
                }
            }
#endif
            unsigned i = 0;
            struct timeval begin, end;
            gettimeofday(&begin, NULL);
            for (; i < count[0]; ) {
                if (nodeListz[i].weight == hgr->maxWeight) {
                    i++;
                    continue;
                }
                hgr->nodes[nodeListz[i].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 1;
                gain += hgr->nodes[nodeListz[i].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                i++;
                if (gain >= static_cast<long>(targetWeight1)) {
                    break;
                }
                if (i > sqrt(hgr->totalWeight)) {
                    break;
                }
            }
            gettimeofday(&end, NULL);
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            std::cout << "i:" << i << "\n";
            std::cout << "gain:" << gain << ", targetWeight1:" << targetWeight1 << "\n";
            std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            CHECK_ERROR(cudaFree(nodeListz));
            ccount++;
            if (gain >= static_cast<long>(targetWeight1)) {
                break;
            }
        }
        CHECK_ERROR(cudaFree(count));
    } else { // zero < nonzero
        std::cout << "enter move 1 to 0 branch\n";
        int gain = zeroPartWeight;
        unsigned* count;
        CHECK_ERROR(cudaMallocManaged(&count, sizeof(unsigned)));
        while (1) {
            int blocksize = 128;
            int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
            TIMERSTART(0)
            thrust::fill(thrust::device, hgr->nodes + N_FS(hgr), hgr->nodes + N_FS(hgr) + hgr->nodeNum, 0);
            thrust::fill(thrust::device, hgr->nodes + N_TE(hgr), hgr->nodes + N_TE(hgr) + hgr->nodeNum, 0);
            initGain<<<gridsize, blocksize>>>(hgr, hgr->hedgeNum);
            TIMERSTOP(0)

            count[0] = 0;
            tmpNode* nodeListnz;
            CHECK_ERROR(cudaMallocManaged(&nodeListnz, hgr->nodeNum * sizeof(tmpNode)));
            CHECK_ERROR(cudaMemset(nodeListnz, 0, hgr->nodeNum * sizeof(tmpNode)));
            gridsize = UP_DIV(hgr->nodeNum, blocksize);
            unsigned partID = 1;
            TIMERSTART(1)
            createNodeList<<<gridsize, blocksize>>>(hgr, nodeListnz, count, partID);
            TIMERSTOP(1)
            
            std::cout << count[0] << "\n";
            // thrust::device_ptr<tmpNode> one_ptr(nodeListnz);
            TIMERSTART(2)
            use_curr_precision ? thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], mycmp()) : thrust::sort(thrust::device, nodeListnz, nodeListnz + count[0], mycmp1());
            TIMERSTOP(2)

#if 1
            if (ccount == 0) {
                std::ofstream debug("../debug/initial_partition_nodelist_info.txt");
                for (int i = 0; i < count[0]; ++i) {
                    debug << "nodeid: " << nodeListnz[i].nodeid << ", init_gain: " << nodeListnz[i].gain << ", real_gain: "
                          << nodeListnz[i].real_gain << ", weight: " << nodeListnz[i].weight << ", ratio: "
                          << (float)(nodeListnz[i].real_gain * (1.0f / nodeListnz[i].weight)) << ", degree: " << hgr->nodes[nodeListnz[i].nodeid-hgr->hedgeNum + N_DEGREE(hgr)] << "\n";
                }
            }
#endif

            unsigned i = 0;
            struct timeval begin, end;
            gettimeofday(&begin, NULL);
            for (; i < count[0]; ) {
                if (nodeListnz[i].weight == hgr->maxWeight) {
                    i++;
                    continue;
                }
                hgr->nodes[nodeListnz[i].nodeid-hgr->hedgeNum + N_PARTITION(hgr)] = 0;
                gain += hgr->nodes[nodeListnz[i].nodeid-hgr->hedgeNum + N_WEIGHT(hgr)];
                i++;
                if (gain >= static_cast<long>(targetWeight0)) {
                    break;
                }
                if (i > sqrt(hgr->totalWeight)) {
                    break;
                }
            }
            gettimeofday(&end, NULL);
            float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
            time += (time0 + time1 + time2) / 1000.f + elapsed;
            std::cout << "i:" << i << "\n";
            std::cout << "gain:" << gain << ", targetWeight0:" << targetWeight0 << "\n";
            std::cout << "current edge cut quality:" << computeHyperedgeCut(hgr) << "\n";
            CHECK_ERROR(cudaFree(nodeListnz));
            if (gain >= static_cast<long>(targetWeight0)) {
                break;
            }
        }
        CHECK_ERROR(cudaFree(count));
    }
}
