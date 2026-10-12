#include <iostream>
#include <chrono>
#include "utils.cuh"
#include "include/graph.h"
#include <thrust/host_vector.h>
#include <thrust/device_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include "use_no_uvm.cuh"
#include <thrust/scan.h>
#include "kway_partition_no_uvm_kernels.cuh"
#include "partition_no_uvm_kernels.cuh"
#include <set>

void kway_partition_no_uvm(Hypergraph* hgr, unsigned int K, float& time, float& malloc_copy_time, OptionConfigs& optcfgs) {
    std::cout << __FUNCTION__ << "...\n";

    int part0Weight = optcfgs.stats.parts[0];
    int part1Weight = optcfgs.stats.parts[1];
    // swap partition
    int blocksize = 128;
    int gridsize = UP_DIV(hgr->nodeNum, blocksize);
    TIMERSTART(_)
    swapPartition<<<gridsize, blocksize>>>(hgr->nodes, hgr->nodeNum, K, part0Weight, part1Weight);
    TIMERSTOP(_)

    printf("after swapping partition...\n");
    std::vector<int> parts(K, 0);
    computeBalanceResult(hgr, K, 0.5, parts, optcfgs.useCUDAUVM);
    for (int i = 0; i < K; ++i) {
        std::cout << "|Partition " << i << "| = " << parts[i] << "\n";
    }

    int kValue[K];
    for (int i = 0; i < K; i++) {
        kValue[i] = 0;
    }
    kValue[0]           = (K + 1) / 2;
    kValue[(K + 1) / 2] = K / 2;

    // toProcess contains nodes to be executed in a given level
    std::set<int> toProcess;
    std::set<int> toProcessNew;
    toProcess.insert(0);
    toProcess.insert((K + 1) / 2);
    
    printf("start further recursive bipartitioning...\n");
    for (int level = 0; level < (int)log2(K); level++) {
        // int blocksize = 128;
        // int gridsize = UP_DIV(hgr->hedgeNum, blocksize);
        // TIMERSTART(0)
        // distributeHedgePartition<<<gridsize, blocksize>>>(hgr->nodes, hgr->hedges, hgr->adj_list, hgr->hedgeNum, hgr->nodeNum);
        // TIMERSTOP(0)


        for (unsigned i : toProcess) {
            printf("calling partition %d\n", i);
            if (kValue[i] > 1) {
                // std::ofstream debug("../scripts/ghypart.txt");
                Hypergraph* subHgr = (Hypergraph*)malloc(sizeof(Hypergraph));
                Auxillary* aux = (Auxillary*)malloc(sizeof(Auxillary));
                CHECK_ERROR(cudaMalloc((void**)&aux->d_nodeCnt, sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->d_nodeCnt, 0, sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&aux->d_edgeCnt, sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->d_edgeCnt, 0, sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&aux->d_totalPinSize, sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)aux->d_totalPinSize, 0, sizeof(int)));
                int blocksize = 128;
                int gridsize = hgr->hedgeNum;
                TIMERSTART(0)
                thrust::fill(thrust::device, hgr->hedges + E_IDNUM1(hgr->hedgeNum), 
                                                            hgr->hedges + E_IDNUM1(hgr->hedgeNum) + hgr->hedgeNum, 0);
                thrust::fill(thrust::device, hgr->nodes + N_ELEMID1(hgr->nodeNum), 
                                                            hgr->nodes + N_ELEMID1(hgr->nodeNum) + hgr->nodeNum, 0);
                subHgrNodeCounting<<<UP_DIV(hgr->nodeNum, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, i, aux->d_nodeCnt);
                distributeHedgePartition<<<gridsize, blocksize>>>(hgr->nodes, hgr->hedges, hgr->adj_list, 
                                                                  hgr->hedgeNum, hgr->nodeNum,
                                                                  i, aux->d_edgeCnt);
                TIMERSTOP(0)

                // int* hedges = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(hedges, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                // for (int i = 0; i < hgr->hedgeNum; i++) {
                //     if (hedges[E_IDNUM1(hgr->hedgeNum) + i])
                //     debug << "hedge " << i << "\n";
                // }
                // int* node = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(node, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                // for (int i = 0; i < hgr->nodeNum; i++) {
                //     if (node[N_ELEMID1(hgr->nodeNum) + i])
                //     debug << "node " << i + hgr->hedgeNum << "\n";
                // }
                TIMERSTART(others1)
                CHECK_ERROR(cudaMemcpy((void *)&subHgr->nodeNum, aux->d_nodeCnt, sizeof(int), cudaMemcpyDeviceToHost));
                CHECK_ERROR(cudaMemcpy((void *)&subHgr->hedgeNum, aux->d_edgeCnt, sizeof(int), cudaMemcpyDeviceToHost));
                CHECK_ERROR(cudaMalloc((void**)&subHgr->nodes, N_LENGTH1(subHgr->nodeNum) * sizeof(int)));
                CHECK_ERROR(cudaMalloc((void**)&subHgr->hedges, E_LENGTH1(subHgr->hedgeNum) * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)subHgr->nodes, 0, N_LENGTH1(subHgr->nodeNum) * sizeof(int)));
                CHECK_ERROR(cudaMemset((void*)subHgr->hedges, 0, E_LENGTH1(subHgr->hedgeNum) * sizeof(int)));

                thrust::exclusive_scan(thrust::device, hgr->hedges + E_IDNUM1(hgr->hedgeNum), 
                        hgr->hedges + E_IDNUM1(hgr->hedgeNum) + hgr->hedgeNum, hgr->hedges + E_IDNUM1(hgr->hedgeNum));
                thrust::exclusive_scan(thrust::device, hgr->nodes + N_ELEMID1(hgr->nodeNum),
                        hgr->nodes + N_ELEMID1(hgr->nodeNum) + hgr->nodeNum, hgr->nodes + N_ELEMID1(hgr->nodeNum), subHgr->hedgeNum);
                TIMERSTOP(others1)
                printf("subgraph hedgeNum: %d, nodeNum: %d\n", subHgr->hedgeNum, subHgr->nodeNum);
                // thrust::fill(thrust::device, subHgr->nodes + N_COUNTER1(subHgr->nodeNum), 
                //                                         subHgr->nodes + N_COUNTER1(subHgr->nodeNum) + subHgr->nodeNum, 0);
                // thrust::fill(thrust::device, subHgr->nodes + N_FS1(subHgr->nodeNum), 
                //                                             subHgr->nodes + N_FS1(subHgr->nodeNum) + 5 * subHgr->nodeNum, 0);
                
                TIMERSTART(1)
                subHgrEdgeListCounting<<<UP_DIV(hgr->hedgeNum, blocksize), blocksize>>>(subHgr->hedges, hgr->hedges, 
                                                                    hgr->adj_list, hgr->hedgeNum, subHgr->hedgeNum, 
                                                                    aux->d_totalPinSize, i);
                thrust::exclusive_scan(thrust::device, subHgr->hedges + E_DEGREE1(subHgr->hedgeNum), 
                                        subHgr->hedges + E_DEGREE1(subHgr->hedgeNum) + subHgr->hedgeNum, 
                                        subHgr->hedges + E_OFFSET1(subHgr->hedgeNum));
                TIMERSTOP(1)

                // int* hedges = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(hedges, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                // int* subhedges = (int*)malloc(E_LENGTH1(subHgr->hedgeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(subhedges, subHgr->hedges, E_LENGTH1(subHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                // for (int i = 0; i < subHgr->hedgeNum; i++) {
                //     debug << "subhedge " << i << " " << subhedges[i + E_IDNUM1(subHgr->hedgeNum)] << "\n";
                // }

                TIMERSTART(others2)
                CHECK_ERROR(cudaMemcpy((void *)&subHgr->totalEdgeDegree, aux->d_totalPinSize, sizeof(int), cudaMemcpyDeviceToHost));
                CHECK_ERROR(cudaMalloc((void**)&subHgr->adj_list, subHgr->totalEdgeDegree * sizeof(unsigned int)));
                Auxillary* subaux = (Auxillary*)malloc(sizeof(Auxillary));
                CHECK_ERROR(cudaMalloc((void**)&subaux->pins_hedgeid_list, subHgr->totalEdgeDegree * sizeof(unsigned)));
                TIMERSTOP(others2)
                subHgr->avgHedgeSize = subHgr->totalEdgeDegree / subHgr->hedgeNum;
                printf("subgraph totalEdgeDegree: %d\n", subHgr->totalEdgeDegree);

                TIMERSTART(2)
                subHgrAdjListConstruction<<<hgr->hedgeNum, blocksize>>>(subHgr->hedges, hgr->hedges, hgr->nodes, 
                                                                        subHgr->adj_list, hgr->adj_list, 
                                                                        hgr->hedgeNum, hgr->nodeNum, subHgr->hedgeNum, 
                                                                        subaux->pins_hedgeid_list, i);
                setSubHgrNodesProperties<<<UP_DIV(subHgr->nodeNum, blocksize), blocksize>>>(
                                                                        subHgr->nodes, subHgr->nodeNum, subHgr->hedgeNum);
                TIMERSTOP(2)

                // thrust::fill(thrust::device, subHgr->nodes + N_WEIGHT1(subHgr->nodeNum), 
                //                                         subHgr->nodes + N_WEIGHT1(subHgr->nodeNum) + subHgr->nodeNum, 1);
                // thrust::fill(thrust::device, subHgr->nodes + N_ELEMID1(subHgr->nodeNum), 
                //                                         subHgr->nodes + N_ELEMID1(subHgr->nodeNum) + subHgr->nodeNum, 1);
                // thrust::exclusive_scan(thrust::device, subHgr->nodes + N_ELEMID1(subHgr->nodeNum),
                //                                         subHgr->nodes + N_ELEMID1(subHgr->nodeNum) + subHgr->nodeNum, 
                //                                         subHgr->nodes + N_ELEMID1(subHgr->nodeNum));
                // thrust::exclusive_scan(thrust::device, subHgr->nodes + N_ELEMID1(subHgr->nodeNum),
                //                                         subHgr->nodes + N_ELEMID1(subHgr->nodeNum) + subHgr->nodeNum, 
                //                                         subHgr->nodes + N_ELEMID1(subHgr->nodeNum), subHgr->hedgeNum);

                // unsigned* subadjlist = (unsigned*)malloc(subHgr->totalEdgeDegree * sizeof(unsigned));
                // CHECK_ERROR(cudaMemcpy(subadjlist, subHgr->adj_list, subHgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
                // int* subhedges = (int*)malloc(E_LENGTH1(subHgr->hedgeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(subhedges, subHgr->hedges, E_LENGTH1(subHgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                // int* subnodes = (int*)malloc(N_LENGTH1(subHgr->nodeNum) * sizeof(int));
                // CHECK_ERROR(cudaMemcpy(subnodes, subHgr->nodes, N_LENGTH1(subHgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                
                // // debug << "subgraph nodeNum: " << subHgr->nodeNum << " hedgeNum: " << subHgr->hedgeNum << "\n";
                // for (int i = 0; i < subHgr->hedgeNum; i++) {
                //     int beg = subhedges[E_OFFSET1(subHgr->hedgeNum) + i];
                //     int end = subhedges[E_OFFSET1(subHgr->hedgeNum) + i] + subhedges[E_DEGREE1(subHgr->hedgeNum) + i];
                //     debug << "hedge " << i << ": ";
                //     for (int j = beg; j < end; j++) {
                //         debug << subadjlist[j] << " ";
                //     }
                //     debug << "\n";
                // }
                // for (int d = 0; d < subHgr->nodeNum; d++) {
                //     printf("%d ", subnodes[N_COUNTER1(subHgr->nodeNum) + d]);
                // }

                subHgr->totalWeight = subHgr->nodeNum;
                std::vector<Hypergraph*> d_vHgrs(1);
                d_vHgrs[0] = subHgr;
                float imbalance = optcfgs.stats.imbalance_ratio;
                float ratio  = (50.0 + imbalance) / (50.0 - imbalance);
                float tol    = std::max(ratio, 1 - ratio) - 1;
                int hi       = (1 + tol) * d_vHgrs[0]->nodeNum / (2 + tol);
                int LIMIT          = hi / 4;
                std::cout << "BiPart's LIMIT weight: " << LIMIT << "\n";
                if (optcfgs.runBipartWeightConfig || optcfgs.runBaseline) {
                    optcfgs.coarseI_weight_limit = LIMIT;
                    optcfgs.coarseMore_weight_limit = INT_MAX;
                }
                std::cout << "optionconfigs: " << optcfgs.coarseI_weight_limit << ", " << optcfgs.coarseMore_weight_limit << "\n";
                std::cout << "matching policy: " << optcfgs.matching_policy << "\n";
                int iterNum = 0;
                int coarsenTo = 25;
                unsigned size = d_vHgrs[0]->nodeNum;
                unsigned newsize = size;
                unsigned hedgesize = 0;
                Hypergraph* coarsenHgr = d_vHgrs[0];
                float coarsen_time = 0.f;
                float other_time = 0.f;
                float alloc_time = 0.f;
                unsigned long memBytes = E_LENGTH1(d_vHgrs[0]->hedgeNum) * sizeof(int) + 
                                        N_LENGTH1(d_vHgrs[0]->nodeNum) * sizeof(int) + 
                                        1 * d_vHgrs[0]->totalEdgeDegree * sizeof(unsigned);
                std::vector<float> coarsen_perf_collector(20, 0.0);
                std::vector<std::pair<std::string, float>> coarsen_perf_collectors(20);
                std::vector<std::vector<std::pair<std::string, float>>> iterate_kernel_breakdown;
                std::cout << "\n============================= start coarsen =============================\n";
                float selectionOverhead = 0.f;
                while (optcfgs.testFirstIter ? iterNum < 1 : newsize > coarsenTo) {
                // while (iterNum < 1) {
                    if (iterNum > coarsenTo) {
                        std::cout << __LINE__ << "here~~\n";
                        break;
                    }
                    if (newsize - size <= 0 && iterNum > 2) {
                        std::cout << __LINE__ << "here~~\n";
                        break;
                    }
                    size = coarsenHgr->nodeNum;

                    d_vHgrs.emplace_back(coarsen_no_uvm(coarsenHgr, iterNum, LIMIT, coarsen_time, other_time, optcfgs, memBytes, 
                                coarsen_perf_collectors, subaux, iterate_kernel_breakdown, selectionOverhead, alloc_time));
                
                    coarsenHgr = d_vHgrs.back();
                    newsize = coarsenHgr->nodeNum;
                    hedgesize = coarsenHgr->hedgeNum;

                    if (hedgesize < 1000) {
                        std::cout << __LINE__ << "here~~\n";
                        break;
                    }
                    ++iterNum;
                    std::cout << "===============================\n\n";
                }
                float total = coarsen_time;
                std::cout << __LINE__ << ":" << d_vHgrs.size() << "\n";
                std::cout << "current allocatd gpu memory size: " << memBytes << " bytes.\n";
                std::cout << "coarsen execution time: " << coarsen_time << " s.\n";
                std::cout << "other parts time: " << other_time << " s.\n";
                std::cout << "finish coarsen.\n";
            

                std::cout << "\n============================= start initial partition =============================\n";
                float partition_time = 0.f;
                unsigned int numPartitions = kValue[i];
                bool use_curr_precision = true;
                float malloc_copy_time = other_time;
                other_time = 0.f;
                if (optcfgs.filename == "ecology1.mtx.hgr") {
                    use_curr_precision = false;
                }
                if (optcfgs.useCoarseningOpts <= 2 && !optcfgs.useInitPartitionOpts && !optcfgs.useRefinementOpts) {
                    optcfgs.useFirstTwoOptsOnly = true;
                }
                if (optcfgs.runBaseline || optcfgs.useInitPartitionOpts != FIX_HEAVIEST_NODE) {
                    init_partition_no_uvm(d_vHgrs.back(), numPartitions, use_curr_precision, partition_time, other_time, optcfgs);
                }
                std::cout << "finish initial partition.\n";
                std::cout << "initial partition time: " << partition_time << " s.\n";
                total += partition_time;

                parts.clear();
                computeBalanceResult(d_vHgrs.back(), numPartitions, imbalance, parts, optcfgs.useCUDAUVM);
                for (int j = 0; j < numPartitions; j++) {
                    std::cout << "part " << j << ": " << parts[j] << "\n";
                }

                std::cout << "\n============================= start refinement =============================\n";
                float Refine_time = 0.f;
                float refine_time = 0.f;
                float balance_time = 0.f;
                float project_time = 0.f;
                int rebalance = 0;
                int curr_idx = d_vHgrs.size()-1;
                int hyperedge_cut = 0;
                other_time = 0.f;
                if (optcfgs.useRefinementOpts == MERGING_MOVE) {
                    optcfgs.switchToMergeMoveLevel = iterNum + 1;
                }
                unsigned refineTo = optcfgs.refineIterPerLevel;//2;
                ratio = 0.0f;
                tol   = 0.0f;
                bool flag = ceil(log2(numPartitions)) == floor(log2(numPartitions));
                if (flag) {
                    ratio = (50.0f + imbalance)/(50.0f - imbalance);
                    tol   = std::max(ratio, 1 - ratio) - 1;
                } else {
                    ratio = ((float)((numPartitions + 1) / 2)) / ((float)(numPartitions / 2));
                    tol   = std::max(ratio, 1 - ratio) - 1;
                    printf("ratio: %f, tol: %f\n", ratio, tol);
                }

                do {
                    float cur_ref = 0.f;
                    float cur_bal = 0.f;
                    float cur_pro = 0.f;
                    // if (curr_idx <= 1) {
                    //     int* nodes = (int*)malloc(N_LENGTH1(d_vHgrs[curr_idx]->nodeNum) * sizeof(int));
                    //     CHECK_ERROR(cudaMemcpy(nodes, d_vHgrs[curr_idx]->nodes, 
                    //                     N_LENGTH1(d_vHgrs[curr_idx]->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
                    //     for (int i = 0; i < d_vHgrs[curr_idx]->nodeNum; i++) {
                    //         printf("%d ", nodes[N_COUNTER1(d_vHgrs[curr_idx]->nodeNum) + i]);
                    //     }
                    // }
                    if (optcfgs.runBaseline || optcfgs.useFirstTwoOptsOnly == true) {
                        refine_no_uvm(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, curr_idx, optcfgs);
                        // rebalance_no_uvm(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optcfgs, memBytes);
                        rebalance_no_uvm_without_multiple_sort(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optcfgs, memBytes);
                        // break;
                    }
                    if (curr_idx > 0) {
                        project_no_uvm(d_vHgrs[curr_idx], d_vHgrs[curr_idx-1], project_time, other_time, cur_pro, curr_idx);
                    }
                    // std::cout << "curr_iter:" << curr_idx << ", edgecut:" << computeHyperedgeCut(d_vHgrs[curr_idx], optcfgs.useCUDAUVM) << "\n";
                    std::cout << "cur_ref:" << cur_ref << ", cur_bal:" << cur_bal << ", cur_pro:" << cur_pro << "\n";
                    curr_idx--;
                    std::cout << "===============================\n\n";
                } while (curr_idx >= 0);

                hyperedge_cut = computeHyperedgeCut(d_vHgrs[0], optcfgs.useCUDAUVM);
                optcfgs.stats.hyperedge_cut_num = hyperedge_cut;
                std::cout << "finish calculating edge cut..\n";
                Refine_time = refine_time + balance_time + project_time;
                std::cout << "refinement time: " << refine_time << "\n";
                std::cout << "rebalance time: " << balance_time << "\n";
                std::cout << "projection time: " << project_time << "\n";
                std::cout << "# of coarsening iterations:" << iterNum << ", # of rebalancing during refinement:" << rebalance << "\n";
                std::cout << "finish refinement.\n";
                total += Refine_time;
                malloc_copy_time += other_time;
                std::cout << "Coarsening time: " << coarsen_time << " s.\n";
                std::cout << "Initial partition time: " << partition_time<< " s.\n";
                std::cout << "Refinement time: " << Refine_time << " s.\n";
                std::cout << "Total execution time (s): " << total << "\n";
                std::cout << "Total cuda malloc && memcpy time: " << malloc_copy_time << " s.\n";
                std::cout << "Selection overhead: " << selectionOverhead << "\n";
                std::cout << "\n============================= Hypergraph Partitioning Statistics ==============================\n";
                std::cout << "# of Hyperedge cut: " << hyperedge_cut << "\n";
                std::cout << "init_partition imbalance " << optcfgs.stats.init_partition_imbalance << "\n";
                std::cout << "Balance results:[epsilon = " << imbalance / 100.0f << "]:\n";
                parts.clear();
                computeBalanceResult(d_vHgrs[0], numPartitions, imbalance, parts, optcfgs.useCUDAUVM);
                for (int j = 0; j < numPartitions; j++) {
                    std::cout << "part " << j << ": " << parts[j] << "\n";
                }
                std::cout << "===============================================================================================\n\n";

                for (int j = 1; j < d_vHgrs.size(); ++j) {
                    Hypergraph* d_hgr = d_vHgrs[j];
                    CHECK_ERROR(cudaFree(d_hgr->adj_list));
                    CHECK_ERROR(cudaFree(d_hgr->nodes));
                    CHECK_ERROR(cudaFree(d_hgr->hedges));
                }

                int tmp                   = kValue[i];
                kValue[i]                 = (tmp + 1) / 2;
                kValue[i + (tmp + 1) / 2] = (tmp) / 2;
                toProcessNew.insert(i);
                toProcessNew.insert(i + (tmp + 1) / 2);
                printf("tmp = %d, kValue[%d] = %d, kValue[%d] = %d\n", 
                        tmp, i, kValue[i], i + (tmp + 1) / 2, kValue[i + (tmp + 1) / 2]);

                // int* count;
                // CHECK_ERROR(cudaMallocManaged(&count, sizeof(int)));
                // count[0] = 0;
                TIMERSTART(3)
                updateSubHgrNodesPartition<<<UP_DIV(hgr->nodeNum, blocksize), blocksize>>>(hgr->nodes, hgr->nodeNum, 
                                                                                d_vHgrs[0]->nodes, d_vHgrs[0]->nodeNum, d_vHgrs[0]->hedgeNum,
                                                                                i, tmp/*, count*/);
                TIMERSTOP(3)
                // printf("count = %d\n", count[0]);

                Hypergraph* d_hgr = d_vHgrs[0];
                CHECK_ERROR(cudaFree(d_hgr->adj_list));
                CHECK_ERROR(cudaFree(d_hgr->nodes));
                CHECK_ERROR(cudaFree(d_hgr->hedges));

                time += total + time0 / 2000.f + time1 / 1000.f + time2 / 1000.f + time3 / 1000.f;
                malloc_copy_time += other_time + (timeothers1 + timeothers2) / 1000.f;
            }
        }
        toProcess = toProcessNew;
        toProcessNew.clear();
    }
    std::cout << "k-way partition time (s): " << time << "\n";
    std::cout << "cuda malloc && memcpy time (s): " << malloc_copy_time << "\n";
}
