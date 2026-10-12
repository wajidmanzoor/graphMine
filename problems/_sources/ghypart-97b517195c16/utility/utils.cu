#include "utils.cuh"

int computeHyperedgeCut(Hypergraph* hgr, bool useUVM) {
    int count = 0;
    if (useUVM) {
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            std::set<unsigned> partitions;
            for (int j = 0; j < hgr->hedges[i + E_DEGREE(hgr)]; ++j) {
                unsigned part = hgr->nodes[hgr->adj_list[hgr->hedges[i + E_OFFSET(hgr)] + j] - hgr->hedgeNum + N_PARTITION(hgr)];
                partitions.insert(part);
            }
            count += partitions.size() - 1;
        }
    } else {
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        for (int i = 0; i < hgr->hedgeNum; ++i) {
            std::set<unsigned> partitions;
            for (int j = 0; j < hedge[i + E_DEGREE1(hgr->hedgeNum)]; ++j) {
                unsigned part = nodes[adj_list[hedge[i + E_OFFSET1(hgr->hedgeNum)] + j] - hgr->hedgeNum + N_PARTITION1(hgr->nodeNum)];
                partitions.insert(part);
            }
            count += partitions.size() - 1;
        }
        free(adj_list);
        free(hedge);
        free(nodes);
    }
    return count;
}

void printBalanceResult(Hypergraph* hgr, int numPartitions, float imbalance, bool useUVM) {
    std::vector<int> parts(numPartitions, 0);
    if (useUVM) {
        for (size_t i = 0; i < hgr->nodeNum; i++) {
            unsigned pp = hgr->nodes[i + N_PARTITION(hgr)];
            parts[pp]++;
        }
        for (int i = 0; i < numPartitions; ++i) {
            std::cout << "|Partition " << i << "| = " << parts[i] << ", |V|/" << numPartitions << " = " << hgr->nodeNum / numPartitions
                    << ", final ratio: " << fabs(parts[i] - hgr->nodeNum / numPartitions) / (float)(hgr->nodeNum / numPartitions) << "\n";
        }
    } else {
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        for (size_t i = 0; i < hgr->nodeNum; i++) {
            unsigned pp = nodes[i + N_PARTITION1(hgr->nodeNum)];
            parts[pp]++;
        }
        for (int i = 0; i < numPartitions; ++i) {
            std::cout << "|Partition " << i << "| = " << parts[i] << ", |V|/" << numPartitions << " = " << hgr->nodeNum / numPartitions
                    << ", final ratio: " << fabs(parts[i] - hgr->nodeNum / numPartitions) / (float)(hgr->nodeNum / numPartitions) << "\n";
        }
        free(nodes);
    }
}

void computeBalanceResult(Hypergraph* hgr, int numPartitions, float imbalance, std::vector<int>& parts, bool useUVM) {
    parts.resize(numPartitions, 0);
    if (useUVM) {
        for (size_t i = 0; i < hgr->nodeNum; i++) {
            unsigned pp = hgr->nodes[i + N_PARTITION(hgr)];
            parts[pp]++;
        }
    } else {
        printf("hgr->nodeNum: %d\n", hgr->nodeNum);
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        for (size_t i = 0; i < hgr->nodeNum; i++) {
            unsigned pp = nodes[i + N_PARTITION1(hgr->nodeNum)];
            parts[pp]++;
        }
        free(nodes);
        // for (int i = 0; i < numPartitions; ++i) {
        //     std::cout << "|Partition " << i << "| = " << parts[i] << ", |V|/" << numPartitions << " = " << hgr->nodeNum / numPartitions
        //             << ", final ratio: " << fabs(parts[i] - hgr->nodeNum / numPartitions) / (float)(hgr->nodeNum / numPartitions) << "\n";
        // }
    }
}


bool isPowerOfTwo(int x) {
    return (x & (x - 1)) == 0;
}

void allocTempData(Auxillary* aux, Hypergraph* hgr) {
    CHECK_ERROR(cudaMalloc((void**)&aux->d_nodeCnt, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_nodeCnt, 0, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_edgeCnt, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_edgeCnt, 0, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_totalPinSize, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_totalPinSize, 0, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_totalNodeDeg, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_totalNodeDeg, 0, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_minPinSize, sizeof(int)));
    int minPinSize = INT_MAX;
    CHECK_ERROR(cudaMemcpy((void *)aux->d_minPinSize, &minPinSize, sizeof(int), cudaMemcpyHostToDevice));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_maxPinSize, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_maxPinSize, 0, sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_minWeight, sizeof(int)));
    int minWeight = INT_MAX;
    CHECK_ERROR(cudaMemcpy((void *)aux->d_minWeight, &minWeight, sizeof(int), cudaMemcpyHostToDevice));
    CHECK_ERROR(cudaMalloc((void**)&aux->d_maxWeight, sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->d_maxWeight, 0, sizeof(int)));
    // TIMERSTART(_t)
    CHECK_ERROR(cudaMalloc((void**)&aux->eInBag, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->eInBag, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->eMatch, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->eMatch, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->eNextId, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->eNextId, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->eRand, hgr->hedgeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->eRand, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->ePriori, hgr->hedgeNum * sizeof(int)));
    
    CHECK_ERROR(cudaMalloc((void**)&aux->nInBag1, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nInBag1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->nInBag, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nInBag, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->nNextId, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nNextId, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->tmpW, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->tmpW, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->tmpW1, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->tmpW1, 0, hgr->nodeNum * sizeof(int)));

    CHECK_ERROR(cudaMalloc((void**)&aux->nMatch, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nMatch, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->canBeCandidates, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->canBeCandidates1, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->nMatchHedgeId, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nMatchHedgeId, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->nPriori, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nPriori, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMalloc((void**)&aux->nRand, hgr->nodeNum * sizeof(int)));
    // CHECK_ERROR(cudaMemset((void*)aux->nRand, 0, hgr->nodeNum * sizeof(int)));
    // TIMERSTOP(_t)
    // TIMERSTART(_tt)
    CHECK_ERROR(cudaMemset((void*)aux->eInBag, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->eMatch, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->eNextId, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->eRand, 0, hgr->hedgeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nInBag1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nInBag, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nNextId, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->tmpW, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->tmpW1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nMatch, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->canBeCandidates1, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nMatchHedgeId, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nPriori, 0, hgr->nodeNum * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->nRand, 0, hgr->nodeNum * sizeof(int)));

    thrust::fill(thrust::device, aux->ePriori, aux->ePriori + hgr->hedgeNum, INT_MAX);
    thrust::fill(thrust::device, aux->nMatchHedgeId, aux->nMatchHedgeId + hgr->nodeNum, INT_MAX);
    thrust::fill(thrust::device, aux->nPriori, aux->nPriori + hgr->nodeNum, INT_MAX);
    thrust::fill(thrust::device, aux->nRand, aux->nRand + hgr->nodeNum, INT_MAX);
    // TIMERSTART(_t)
    CHECK_ERROR(cudaMalloc((void**)&aux->isDuplica, hgr->totalEdgeDegree * sizeof(int)));
    CHECK_ERROR(cudaMemset((void*)aux->isDuplica, 0, hgr->totalEdgeDegree * sizeof(int)));
    // TIMERSTOP(_tt)
}

void deallocTempData(Auxillary* aux) {
    CHECK_ERROR(cudaFree(aux->isDuplica));
    CHECK_ERROR(cudaFree(aux->nRand));
    CHECK_ERROR(cudaFree(aux->nPriori));
    CHECK_ERROR(cudaFree(aux->nMatchHedgeId));
    CHECK_ERROR(cudaFree(aux->canBeCandidates1));
    CHECK_ERROR(cudaFree(aux->canBeCandidates));
    CHECK_ERROR(cudaFree(aux->nMatch));
    CHECK_ERROR(cudaFree(aux->tmpW1));
    CHECK_ERROR(cudaFree(aux->tmpW));
    CHECK_ERROR(cudaFree(aux->nNextId));
    CHECK_ERROR(cudaFree(aux->nInBag));
    CHECK_ERROR(cudaFree(aux->nInBag1));
    
    CHECK_ERROR(cudaFree(aux->ePriori));
    CHECK_ERROR(cudaFree(aux->eRand));
    CHECK_ERROR(cudaFree(aux->eNextId));
    CHECK_ERROR(cudaFree(aux->eMatch));
    CHECK_ERROR(cudaFree(aux->eInBag));

    CHECK_ERROR(cudaFree(aux->d_maxWeight));
    CHECK_ERROR(cudaFree(aux->d_minWeight));
    CHECK_ERROR(cudaFree(aux->d_maxPinSize));
    CHECK_ERROR(cudaFree(aux->d_minPinSize));
    CHECK_ERROR(cudaFree(aux->d_totalNodeDeg));
    CHECK_ERROR(cudaFree(aux->d_totalPinSize));
    CHECK_ERROR(cudaFree(aux->d_edgeCnt));
    CHECK_ERROR(cudaFree(aux->d_nodeCnt));
}

