/*
./mt-kahypar/application/MtKaHyPar -h ../../hypergraph-coarsening/dataset/benchmarks/wb-edu.mtx.hgr -p ../config/deterministic_preset.ini --instance-type=hypergraph -k 2 -e 0.05 -o cut -m direct -t 1
./kahypar/application/KaHyPar -h /home/wuzhenlin/workspace/hypergraph-coarsening/dataset/benchmarks/ISPD98_ibm18.hgr -k 2 -e 0.05 -o cut -m direct -p ../config/cut_kKaHyPar_sea20.ini

./gpu_coarsen ../../dataset/benchmarks/wb-edu.mtx.hgr -bp -bwt -ref_opt 6 -m 5           // 4298
./gpu_coarsen ../../dataset/benchmarks/RM07R.mtx.hgr -bp -bwt -ref_opt 6 -m 3 -r 3       // 20694
./gpu_coarsen ../../dataset/benchmarks/Stanford.mtx.hgr -bp -bwt -ref_opt 7              // 67
./gpu_coarsen ../../dataset/benchmarks/webbase-1M.mtx.hgr -bp -bwt -ref_opt 7            // 351

./gpu_coarsen ../../dataset/benchmarks/nlpkkt120.mtx.hgr -bp -bwt -ref_opt 7               // 97337
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_dual.hgr -bp -bwt -ref_opt 7      // 2808
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_dual.hgr -bp -bwt -ref_opt 6 -m 7 // 2797
./gpu_coarsen ../../dataset/benchmarks/sat14_series_bug7_primal.hgr -bp -bwt -ref_opt 7    // 342256

./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm17.hgr -bp -bwt -coar_opt 2               // 3034
./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm18.hgr -bp -bwt -ref_opt 7 -r 4           // 2040 with weight 68000
./gpu_coarsen ../../dataset/benchmarks/ISPD98_ibm18.hgr -bp -bwt -ref_opt 6 -m 3 -r 4      // 2036 with weight 43000
./gpu_coarsen ../../dataset/benchmarks/af_4_k101.mtx.hgr -bp -bwt -r 4                     // 1960
./gpu_coarsen ../../dataset/benchmarks/af_4_k101.mtx.hgr -bp -bwt -ref_opt 6 -m 10 -r 4    // 1935 with weight 49000
./gpu_coarsen ../../dataset/benchmarks/ecology1.mtx.hgr -bp -bwt -adjust_refineTo 5 -r 4   // 2030

./gpu_coarsen ../../dataset/benchmarks/human_gene2.mtx.hgr -bp -bwt -init_opt 3 -ref_opt 8 -m 1 // 9623
*/

#include "use_no_uvm.cuh"
#include "../utility/validation.cuh"
#include <thrust/device_vector.h>
#include <thrust/host_vector.h>
#include <thrust/sort.h>
#include <thrust/execution_policy.h>
#include <cub/cub.cuh>
#include <cub/device/device_segmented_sort.cuh>
#include <cub/device/device_segmented_reduce.cuh>
#include <cub/device/device_scan.cuh>
#include "coarsen_no_uvm_kernels.cuh"
// #include <numeric>
#include <algorithm>

void SetupWithoutUVM(OptionConfigs optCfgs, char **argv, cudaDeviceProp deviceProp) {
    std::cout << __FUNCTION__ << "...\n";
    char *filepath = argv[1];
    std::ifstream f(filepath);
    std::string line;
    std::getline(f, line);
    std::stringstream ss(line);

    std::vector<Hypergraph*> h_vHgrs(1);
    h_vHgrs[0] = (Hypergraph*)malloc(sizeof(Hypergraph));
    ss >> h_vHgrs[0]->hedgeNum >> h_vHgrs[0]->nodeNum;
    h_vHgrs[0]->graphSize = h_vHgrs[0]->hedgeNum + h_vHgrs[0]->nodeNum;
    std::cout << "hedgeNum: " << h_vHgrs[0]->hedgeNum << ", nodeNum: " << h_vHgrs[0]->nodeNum << "\n";
    std::cout << E_LENGTH1(h_vHgrs[0]->hedgeNum) << ", " << N_LENGTH1(h_vHgrs[0]->nodeNum) << "\n";

    h_vHgrs[0]->hedges = (int*)malloc(E_LENGTH1(h_vHgrs[0]->hedgeNum) * sizeof(int));
    h_vHgrs[0]->nodes = (int*)malloc(N_LENGTH1(h_vHgrs[0]->nodeNum) * sizeof(int));
    memset(h_vHgrs[0]->hedges, 0, E_LENGTH1(h_vHgrs[0]->hedgeNum) * sizeof(int));
    memset(h_vHgrs[0]->nodes, 0, N_LENGTH1(h_vHgrs[0]->nodeNum) * sizeof(int));
    for (int i = 0; i < h_vHgrs[0]->nodeNum; ++i) {
        h_vHgrs[0]->nodes[N_ELEMID1(h_vHgrs[0]->nodeNum) + i] = i + h_vHgrs[0]->hedgeNum; // elementID i + 1 + vHgrs[0]->hedgeNum
        // h_vHgrs[0]->nodes[N_PRIORITY1(h_vHgrs[0]->nodeNum) + i] = INT_MAX; // priority
        // h_vHgrs[0]->nodes[N_RAND1(h_vHgrs[0]->nodeNum) + i] = INT_MAX; // rand
        // h_vHgrs[0]->nodes[N_HEDGEID1(h_vHgrs[0]->nodeNum) + i] = INT_MAX; // hedgeID
        h_vHgrs[0]->nodes[N_WEIGHT1(h_vHgrs[0]->nodeNum) + i] = 1; // weight
        h_vHgrs[0]->maxDegree = 0;
        h_vHgrs[0]->minDegree = INT_MAX;
        h_vHgrs[0]->nodes[N_DEGREE1(h_vHgrs[0]->nodeNum) + i] = 0;
        // h_vHgrs[0]->nodes[N_MATCHED1(h_vHgrs[0]->nodeNum) + i] = 0;
    }
    std::vector<unsigned int> edges_id;
    std::vector<unsigned int> pins_edge_id;
    std::vector<std::vector<unsigned>> in_nets(h_vHgrs[0]->nodeNum);
    std::vector<h_size> hedge_tuple;
    uint32_t cnt   = 0;
    uint32_t edges = 0;
    std::string last_line = "";
    std::vector<unsigned> isDuplica;
    struct timeval begin, end;
    gettimeofday(&begin, NULL);
    while (std::getline(f, line)) {
        std::stringstream ss(line);
        int val;
        while (ss >> val) {
            unsigned newval = h_vHgrs[0]->hedgeNum + (val - 1);
            edges_id.push_back(newval);
            pins_edge_id.push_back(cnt);
            edges++;
            h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + cnt]++; // degree
            h_vHgrs[0]->nodes[N_DEGREE1(h_vHgrs[0]->nodeNum) + (val - 1)]++;
            in_nets[val-1].push_back(cnt);
        }
        // h_vHgrs[0]->maxDegree = h_vHgrs[0]->maxDegree < h_vHgrs[0]->hedges[E_DEGREE(h_vHgrs[0]) + cnt] ? 
        //                         h_vHgrs[0]->hedges[E_DEGREE(h_vHgrs[0]) + cnt] : h_vHgrs[0]->maxDegree;
        // h_vHgrs[0]->minDegree = h_vHgrs[0]->minDegree > h_vHgrs[0]->hedges[E_DEGREE(h_vHgrs[0]) + cnt] ? 
        //                         h_vHgrs[0]->hedges[E_DEGREE(h_vHgrs[0]) + cnt] : h_vHgrs[0]->minDegree;
        h_vHgrs[0]->maxDegree = std::max(h_vHgrs[0]->maxDegree, h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + cnt]); 
        h_vHgrs[0]->minDegree = std::min(h_vHgrs[0]->minDegree, h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + cnt]);
        h_vHgrs[0]->hedges[E_IDNUM1(h_vHgrs[0]->hedgeNum) + cnt] = cnt + 1; // idNum
        // h_vHgrs[0]->hedges[E_ELEMID1(h_vHgrs[0]->hedgeNum) + cnt] = cnt + 1; // elementID
        // h_vHgrs[0]->hedges[E_ELEMID1(h_vHgrs[0]->hedgeNum) + cnt] = INT_MAX;
        h_size h_tuple;
        h_tuple.id = cnt;
        h_tuple.size = h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + cnt];
        hedge_tuple.push_back(h_tuple);
        last_line == line ? isDuplica.push_back(1) : isDuplica.push_back(0);
        last_line = line;
        cnt++;
    }
    h_vHgrs[0]->totalEdgeDegree = edges;
    h_vHgrs[0]->totalWeight = h_vHgrs[0]->nodeNum;
    h_vHgrs[0]->adj_list = (unsigned*)malloc(h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned));
    // std::vector<unsigned> transform_edges(h_vHgrs[0]->totalEdgeDegree);
    std::memcpy(h_vHgrs[0]->adj_list, &edges_id[0], h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned));
    for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        if (i > 0) {
            h_vHgrs[0]->hedges[E_OFFSET1(h_vHgrs[0]->hedgeNum) + i] = // offset
                        h_vHgrs[0]->hedges[E_OFFSET1(h_vHgrs[0]->hedgeNum) + i-1] + h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + i-1];
        }
        hedge_tuple[i].firstnode = h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[E_OFFSET1(h_vHgrs[0]->hedgeNum) + i]];
    }
    for (int i = 0; i < h_vHgrs[0]->nodeNum; ++i) {
        h_vHgrs[0]->totalNodeDegree += in_nets[i].size();
        if (i > 0) {
            h_vHgrs[0]->nodes[N_OFFSET1(h_vHgrs[0]->nodeNum) + i] = 
                        h_vHgrs[0]->nodes[N_OFFSET1(h_vHgrs[0]->nodeNum) + i-1] + h_vHgrs[0]->nodes[N_DEGREE1(h_vHgrs[0]->nodeNum) + i-1];
        }
    }
    h_vHgrs[0]->incident_nets = (unsigned*)malloc(h_vHgrs[0]->totalNodeDegree * sizeof(unsigned));
    for (int i = 0; i < h_vHgrs[0]->nodeNum; ++i) {
        std::copy(in_nets[i].begin(), in_nets[i].end(), h_vHgrs[0]->incident_nets + h_vHgrs[0]->nodes[N_OFFSET1(h_vHgrs[0]->nodeNum) + i]);
    }
    gettimeofday(&end, NULL);
    float elapsed = (end.tv_sec - begin.tv_sec) + ((end.tv_usec - begin.tv_usec)/1000000.0);
    std::cout << "read input data elapsed: " << elapsed << " s.\n";
    f.close();

    h_vHgrs[0]->maxVertDeg = *thrust::max_element(h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum), h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum) + h_vHgrs[0]->nodeNum);
    h_vHgrs[0]->minVertDeg = *thrust::min_element(h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum), h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum) + h_vHgrs[0]->nodeNum);
    std::cout << "maxNodeDegree:" << h_vHgrs[0]->maxVertDeg << ", minNodeDegree:" << h_vHgrs[0]->minVertDeg << "\n";
    sum_min_max mytuple = thrust::reduce(h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum), h_vHgrs[0]->nodes + N_DEGREE1(h_vHgrs[0]->nodeNum) + h_vHgrs[0]->nodeNum,
                                        sum_min_max(), mycombiner());
    std::cout << "maxNodeDegree:" << mytuple.max << ", minNodeDegree:" << mytuple.min << ", totalNodeDegree:" << mytuple.sum << "\n";
    std::cout << "hedgeNum: " << h_vHgrs[0]->hedgeNum << ", nodeNum: " << h_vHgrs[0]->nodeNum << "\n";
    std::cout << "hedge_length: " << E_LENGTH1(h_vHgrs[0]->hedgeNum) << ", node_length: " << N_LENGTH1(h_vHgrs[0]->nodeNum) << "\n";
    std::cout << "totalEdgeDegree: " << h_vHgrs[0]->totalEdgeDegree << ", totalNodeDegree: " << h_vHgrs[0]->totalNodeDegree << "\n";
    std::cout << "minHedgeSize: " << h_vHgrs[0]->minDegree << ", maxHedgeSize: " << h_vHgrs[0]->maxDegree << "\n";
    std::cout << "graphAdjListSize," << h_vHgrs[0]->totalEdgeDegree << "\n";
#if 1

    struct timeval beg1, end1;
    gettimeofday(&beg1, NULL);
    std::vector<Hypergraph*> d_vHgrs(1);
    d_vHgrs[0] = (Hypergraph*)malloc(sizeof(Hypergraph));
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0], sizeof(Hypergraph)));
    d_vHgrs[0]->hedgeNum = h_vHgrs[0]->hedgeNum;
    d_vHgrs[0]->nodeNum = h_vHgrs[0]->nodeNum;
    d_vHgrs[0]->graphSize = h_vHgrs[0]->graphSize;
    d_vHgrs[0]->totalEdgeDegree = h_vHgrs[0]->totalEdgeDegree;
    d_vHgrs[0]->totalNodeDegree = h_vHgrs[0]->totalNodeDegree;
    d_vHgrs[0]->minDegree = h_vHgrs[0]->minDegree;
    d_vHgrs[0]->maxDegree = h_vHgrs[0]->maxDegree;
    d_vHgrs[0]->totalWeight = h_vHgrs[0]->nodeNum;
    d_vHgrs[0]->avgHedgeSize = (long double)d_vHgrs[0]->totalEdgeDegree / d_vHgrs[0]->hedgeNum;
    long double standDev = 0.0;
    for (int i = 0; i < d_vHgrs[0]->hedgeNum; ++i) {
        standDev += (long double)powf64(h_vHgrs[0]->hedges[E_DEGREE1(h_vHgrs[0]->hedgeNum) + i] - d_vHgrs[0]->avgHedgeSize, 2);
    }
    d_vHgrs[0]->sdHedgeSize = (long double)sqrtf64(standDev / d_vHgrs[0]->hedgeNum);
    d_vHgrs[0]->avgHNdegree = (long double)d_vHgrs[0]->totalNodeDegree / d_vHgrs[0]->nodeNum;
    standDev = 0.0;
    for (int i = 0; i < d_vHgrs[0]->nodeNum; ++i) {
        standDev += (long double)powf64(h_vHgrs[0]->nodes[N_DEGREE1(h_vHgrs[0]->nodeNum) + i] - d_vHgrs[0]->avgHNdegree, 2);
    }
    d_vHgrs[0]->sdHNdegree = (long double)sqrtf64(standDev / d_vHgrs[0]->nodeNum);
    std::cout << "initial hypergraph avghsize," << d_vHgrs[0]->avgHedgeSize << ",sdv/avg," << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << "\n";
    std::cout << "initial avgnodedeg," << d_vHgrs[0]->avgHNdegree << ",sdvnodedeg," << d_vHgrs[0]->sdHNdegree << "\n";
#endif
#if 0
    std::vector<Hypergraph1*> d_vHgrs(1);
    d_vHgrs[0] = (Hypergraph1*)malloc(sizeof(Hypergraph1));
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->hedgeNum, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->hedgeNum, &h_vHgrs[0]->hedgeNum, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->nodeNum, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->nodeNum, &h_vHgrs[0]->nodeNum, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->graphSize, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->graphSize, &h_vHgrs[0]->graphSize, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->totalEdgeDegree, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->totalEdgeDegree, &h_vHgrs[0]->totalEdgeDegree, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->totalNodeDegree, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->totalNodeDegree, &h_vHgrs[0]->totalNodeDegree, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->minDegree, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->minDegree, &h_vHgrs[0]->minDegree, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->maxDegree, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->maxDegree, &h_vHgrs[0]->maxDegree, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->maxVertDeg, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->maxVertDeg, &h_vHgrs[0]->maxVertDeg, sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->minVertDeg, sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->minVertDeg, &h_vHgrs[0]->minVertDeg, sizeof(int), cudaMemcpyHostToDevice));
#endif
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->hedges, E_LENGTH1(h_vHgrs[0]->hedgeNum) * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0]->hedges, E_LENGTH(h_vHgrs[0]) * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->hedges, h_vHgrs[0]->hedges, E_LENGTH1(h_vHgrs[0]->hedgeNum) * sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->nodes, N_LENGTH1(h_vHgrs[0]->nodeNum) * sizeof(int)));
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0]->nodes, N_LENGTH(h_vHgrs[0]) * sizeof(int)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->nodes, h_vHgrs[0]->nodes, N_LENGTH1(h_vHgrs[0]->nodeNum) * sizeof(int), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->adj_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0]->adj_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->adj_list, h_vHgrs[0]->adj_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));
    
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0]->par_list, h_vHgrs[0]->totalEdgeDegree * sizeof(bool)));
    // CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->par_list1, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMallocManaged(&d_vHgrs[0]->par_list1, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMemset((void*)d_vHgrs[0]->par_list1, 0, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));

    // CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->pins_hedgeid_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    // CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->pins_hedgeid_list, &pins_edge_id[0], h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));

    Auxillary* aux = (Auxillary*)malloc(sizeof(Auxillary));
    CHECK_ERROR(cudaMalloc((void**)&aux->pins_hedgeid_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
    CHECK_ERROR(cudaMemcpy((void *)aux->pins_hedgeid_list, &pins_edge_id[0], h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));
    
    CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->incident_nets, h_vHgrs[0]->totalNodeDegree * sizeof(unsigned)));
    CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->incident_nets, h_vHgrs[0]->incident_nets, h_vHgrs[0]->totalNodeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));

    gettimeofday(&end1, NULL);
    float elapsed1 = (end1.tv_sec - beg1.tv_sec) + ((end1.tv_usec - beg1.tv_usec)/1000000.0);
    std::cout << "initialize input elapsed: " << elapsed1 << " s.\n";

    if (optCfgs.perfOptForRefine) {
        CHECK_ERROR(cudaMalloc((void**)&d_vHgrs[0]->pins_hedgeid_list, h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned)));
        CHECK_ERROR(cudaMemcpy((void *)d_vHgrs[0]->pins_hedgeid_list, &pins_edge_id[0], h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned), cudaMemcpyHostToDevice));
    }
    optCfgs.stats.total_hedge_num = d_vHgrs[0]->hedgeNum;
    optCfgs.stats.total_node_num = d_vHgrs[0]->nodeNum;
    // adjNode_nouvm* adj_nodes;
    // CHECK_ERROR(cudaMalloc((void**)&adj_nodes, h_vHgrs[0]->totalEdgeDegree * sizeof(adjNode_nouvm)));
    // std::ofstream tmp("../../dataset/test.hgr");
    // tmp << h_vHgrs[0]->hedgeNum << " " << h_vHgrs[0]->nodeNum << "\n";
    // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
    //     // for (int j = 0; j < h_vHgrs[0]->maxDegree; ++j) {
    //     for (int j = 0; j < d_vHgrs[0]->avgHedgeSize; ++j) {
    //         int nodeid = (i+1) + j;
    //         if (nodeid <= h_vHgrs[0]->nodeNum) {
    //             tmp << nodeid;
    //         }
    //         // if (nodeid <= h_vHgrs[0]->nodeNum && j < h_vHgrs[0]->maxDegree - 1)  tmp << " ";
    //         if (nodeid <= h_vHgrs[0]->nodeNum && j < d_vHgrs[0]->avgHedgeSize - 1)  tmp << " ";
    //     }
    //     tmp << "\n";
    // }
    // std::string newfile = "../../dataset/benchmarks/new_" + optCfgs.filename;
    // std::ofstream tmp(newfile);
    // tmp << h_vHgrs[0]->hedgeNum << " " << h_vHgrs[0]->nodeNum << "\n";
    // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
    //     // std::cout << "here!!" << i << "\n";
    //     for (int j = 0; j < h_vHgrs[0]->hedgeNum; ++j) {
    //         // if (i == 1) {
    //         //     std::cout << "here!!" << j << "\n";
    //         // }
    //         if (h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[j + E_OFFSET1(h_vHgrs[0]->hedgeNum)]] - h_vHgrs[0]->hedgeNum + 1 == i+1) {
    //             for (int k = 0; k < h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++k) {
    //                 tmp << h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[j + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + k] - h_vHgrs[0]->hedgeNum + 1;
    //                 if (k < h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)] - 1)  tmp << " ";
    //             }
    //             tmp << "\n";
    //         }
    //     }
    // }
    // std::cout << h_vHgrs[0]->nodes[3 + N_DEGREE1(h_vHgrs[0]->nodeNum)] << "\n";
    // std::vector<std::vector<int>> elemts(h_vHgrs[0]->nodeNum);
    // int count = 0;
    // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
    //     int first_node = h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)]] - h_vHgrs[0]->hedgeNum;
    //     elemts[first_node].push_back(i);
    // }
    // for (int i = 0; i < h_vHgrs[0]->nodeNum; ++i) {
    //     for (int j = 0; j < elemts[i].size(); ++j) {
    //         int hid = elemts[i][j];
    //         for (int k = 0; k < h_vHgrs[0]->hedges[hid + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++k) {
    //             tmp << h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[hid + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + k] - h_vHgrs[0]->hedgeNum + 1;
    //             if (k < h_vHgrs[0]->hedges[hid + E_DEGREE1(h_vHgrs[0]->hedgeNum)] - 1)  tmp << " ";
    //         }
    //         tmp << "\n";
    //     }
    // }
    // std::string bi_file = "../../dataset/benchmarks/bipart_" + optCfgs.filename;
    // std::ofstream tmp(bi_file);
    // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
    //     for (int j = 0; j < h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++j) {
    //         tmp << i << " " << h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + j] << "\n";
    //     }
    // }

    std::vector<int> hedge_off_per_thread;
    for (int i = 1; i < h_vHgrs[0]->hedgeNum; ++i) {
        if (h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)] / 128 > h_vHgrs[0]->hedges[i-1 + E_OFFSET1(h_vHgrs[0]->hedgeNum)] / 128) {
            hedge_off_per_thread.push_back(i);
        }
    }
    hedge_off_per_thread.push_back(h_vHgrs[0]->hedgeNum - 1);
    // hedge_off_per_thread.insert(hedge_off_per_thread.begin(), 0);
    // std::ofstream debug("hedge_off_per_thread.txt");
    int total_num = 0;
    for (int i = 0; i < hedge_off_per_thread.size(); ++i) {
        // debug << hedge_off_per_thread[i] << "\n";
        if (i == 0) {
            for (int j = 0; j <= hedge_off_per_thread[i]; ++j) {
                total_num += h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)];
            }
        } else {
            for (int j = hedge_off_per_thread[i-1] + 1; j <= hedge_off_per_thread[i]; ++j) {
                total_num += h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)];
            }
        }
    }
    std::cout << "total_num:" << total_num << ", totalAdjElmts:" << h_vHgrs[0]->totalEdgeDegree << "\n";
    // std::ofstream debug1("hedgesize.txt");
    // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
    //     debug1 << h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)] << "\n";
    // }
    // CHECK_ERROR(cudaMalloc((void**)&aux->hedge_off_per_thread, h_vHgrs[0]->totalEdgeDegree * sizeof(int)));
    // CHECK_ERROR(cudaMemcpy((void *)aux->hedge_off_per_thread, &hedge_off_per_thread[0], hedge_off_per_thread.size() * sizeof(int), cudaMemcpyHostToDevice));
    aux->total_thread_num = hedge_off_per_thread.size();
    struct timeval beg2, end2;
    gettimeofday(&beg2, NULL);
    if (optCfgs.transformInput) { // for reordering
        // std::sort(hedge_tuple.begin(), hedge_tuple.end(), sort_by_size_ge());
        // std::sort(hedge_tuple.begin(), hedge_tuple.end(), sort_by_size_le());
        std::string transfile = "../../dataset/benchmarks/trans_" + optCfgs.filename;
        std::ofstream tmp(transfile);
        // tmp << "\n";
        // tmp << h_vHgrs[0]->hedgeNum << " " << h_vHgrs[0]->nodeNum << "\n";
        // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        //     int hid = hedge_tuple[i].id;
        //     for (int j = 0; j < h_vHgrs[0]->hedges[hid + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++j) {
        //         tmp << h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[hid + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + j] - h_vHgrs[0]->hedgeNum + 1;
        //         if (j < h_vHgrs[0]->hedges[hid + E_DEGREE1(h_vHgrs[0]->hedgeNum)] - 1)  tmp << " ";
        //     }
        //     tmp << "\n";
        // }

        std::vector<std::vector<int>> elemts(h_vHgrs[0]->nodeNum);
        for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
            int first_node = h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)]] - h_vHgrs[0]->hedgeNum;
            elemts[first_node].push_back(i);
        }
        std::vector<std::vector<unsigned>> new_elemtid;
        std::vector<h_size> newHedge_tuple;
        std::vector<int> degree_v;
        int count = 0;
        for (int i = 0; i < h_vHgrs[0]->nodeNum; ++i) {
            for (int j = 0; j < elemts[i].size(); ++j) {
                int hid = elemts[i][j];
                std::vector<unsigned> line_v;
                h_size h_tuple;
                for (int k = 0; k < h_vHgrs[0]->hedges[hid + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++k) {
                    // tmp << h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[hid + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + k] - h_vHgrs[0]->hedgeNum + 1;
                    line_v.push_back(h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[hid + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + k] - h_vHgrs[0]->hedgeNum + 1);
                    if (k == 0) h_tuple.firstnode = h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[hid + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + k] - h_vHgrs[0]->hedgeNum + 1;
                }
                new_elemtid.push_back(line_v);
                // degree_v.push_back(line_v.size());
                // h_tuple.id = count;
                // h_tuple.size = line_v.size();
                // newHedge_tuple.push_back(h_tuple);
                count++;
            }
        }
        // std::vector<int> offset_v(degree_v.size(), 0);
        // offset_v[0] = 0;
        // for (int i = 1; i < offset_v.size(); ++i) {
        //     offset_v[i] = offset_v[i-1] + degree_v[i-1];
        // }
        // // std::exclusive_scan(offset_v.begin(), offset_v.end(), offset_v, 0, std::plus<>{});
        // std::sort(newHedge_tuple.begin(), newHedge_tuple.end(), sort_by_size_le());
        // std::vector<std::vector<unsigned>> new_elemtid1(new_elemtid.size());
        // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        //     int old_hid = newHedge_tuple[i].id;
        //     new_elemtid1[i].resize(newHedge_tuple[i].size);
        //     std::memcpy(&new_elemtid1[i][0], &new_elemtid[old_hid][0], newHedge_tuple[i].size * sizeof(unsigned));
        // }
        // std::cout << new_elemtid.size() << "\n";
        std::vector<std::vector<unsigned>> non_dup_hedgelist;
        int non_duplicates = 0;
        for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
            if (i == 0) {
                std::vector<unsigned> line_v;
                for (int j = 0; j < new_elemtid[i].size(); ++j) {
                    // tmp << new_elemtid[i][j];
                    // if (j < new_elemtid[i].size() - 1)   tmp << " ";
                    line_v.push_back(new_elemtid[i][j]);
                }
                // tmp << "\n";
                non_dup_hedgelist.push_back(line_v);
                non_duplicates++;
            } else if (new_elemtid[i] != new_elemtid[i-1]) {
                std::vector<unsigned> line_v;
                for (int j = 0; j < new_elemtid[i].size(); ++j) {
                    // tmp << new_elemtid[i][j];
                    // if (j < new_elemtid[i].size() - 1)   tmp << " ";
                    line_v.push_back(new_elemtid[i][j]);
                }
                // tmp << "\n";
                non_dup_hedgelist.push_back(line_v);
                non_duplicates++;
            }
        }
        // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        //     if (i == 0) {
        //         for (int j = 0; j < new_elemtid1[i].size(); ++j) {
        //             tmp << new_elemtid1[i][j];
        //             if (j < new_elemtid1[i].size() - 1)   tmp << " ";
        //         }
        //         tmp << "\n";
        //         non_duplicates++;
        //     } else if (new_elemtid1[i] != new_elemtid1[i-1]) {
        //         for (int j = 0; j < new_elemtid1[i].size(); ++j) {
        //             tmp << new_elemtid1[i][j];
        //             if (j < new_elemtid1[i].size() - 1)   tmp << " ";
        //         }
        //         tmp << "\n";
        //         non_duplicates++;
        //     }
        // }
        // tmp.seekp(0, std::ios::beg);
        tmp << non_duplicates << " " << h_vHgrs[0]->nodeNum << "\n";
        // std::cout << non_duplicates << " " << h_vHgrs[0]->nodeNum;
        std::cout << "found " << non_duplicates << " non-duplicate hyperedges!!!\n";
        for (int i = 0; i < non_dup_hedgelist.size(); ++i) {
            for (int j = 0; j < non_dup_hedgelist[i].size(); ++j) {
                tmp << non_dup_hedgelist[i][j];
                if (j < non_dup_hedgelist[i].size() - 1)   tmp << " ";
            }
            tmp << "\n";
        }
        optCfgs.stats.total_nondup_hedgenum = non_duplicates;
    }
    gettimeofday(&end2, NULL);
    float elapsed2 = (end2.tv_sec - beg2.tv_sec) + ((end2.tv_usec - beg2.tv_usec)/1000000.0);
    std::cout << "reordering process elapsed: " << elapsed2 << " s.\n";

    if (optCfgs.sortInputById) {
        void* d_temp_storage = NULL;
        size_t temp_storage_bytes = 0;
        int* d_off;
        CHECK_ERROR(cudaMalloc((void**)&d_off, (d_vHgrs[0]->hedgeNum + 1) * sizeof(int)));
        CHECK_ERROR(cudaMemcpy((void *)d_off, d_vHgrs[0]->hedges + E_OFFSET1(d_vHgrs[0]->hedgeNum), d_vHgrs[0]->hedgeNum * sizeof(int), cudaMemcpyDeviceToDevice));
        CHECK_ERROR(cudaMemcpy((void *)&d_off[d_vHgrs[0]->hedgeNum], &d_vHgrs[0]->totalEdgeDegree, sizeof(int), cudaMemcpyHostToDevice));
        cub::DeviceSegmentedSort::SortKeys(d_temp_storage, temp_storage_bytes, d_vHgrs[0]->adj_list, d_vHgrs[0]->adj_list, d_vHgrs[0]->totalEdgeDegree, d_vHgrs[0]->hedgeNum, d_off, d_off+1);
        std::cout << "temp_storage_in_GB: " << temp_storage_bytes / (1024.f * 1024.f * 1024.f) << " GB.\n";
        CHECK_ERROR(cudaMalloc((void**)&d_temp_storage, temp_storage_bytes));
        cudaStream_t stream;
        cudaStreamCreateWithFlags(&stream, cudaStreamDefault);
        cub::DeviceSegmentedSort::SortKeys(d_temp_storage, temp_storage_bytes, d_vHgrs[0]->adj_list, d_vHgrs[0]->adj_list, d_vHgrs[0]->totalEdgeDegree, d_vHgrs[0]->hedgeNum, d_off, d_off+1, stream);
        CHECK_ERROR(cudaStreamSynchronize(stream));
        CHECK_ERROR(cudaStreamDestroy(stream));
        CHECK_ERROR(cudaFree(d_temp_storage));
        CHECK_ERROR(cudaFree(d_off));
    }

    if (optCfgs.exp_id == MOTIVATION_DATA_HEDGESIZE_IMBALANCE || optCfgs.exp_id == MOTIVATION_DATA_HEDGESIZE_IMBALANCE_WITH_NCU_METRIC) {
        std::string output = "";
        optCfgs.exp_id == MOTIVATION_DATA_HEDGESIZE_IMBALANCE ? output = "../opts_stats/motivation_data_hedgeisze_imbalance.csv" :
                                                                // output = "../ncu-reps/baseline_coarsen_smsp_perf_metrics.csv";
                                                                output = "../opts_stats/motivation_data_ncu_perf_metrics.csv";
        std::ofstream out(output, std::ios::app);
        // int hedgesize_lt_100 = 0, hedgesize_100_to_1000 = 0, hedgesize_1000_to_10000 = 0, hedgesize_gt_10000 = 0;
        // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        //     int deg = h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)];
        //     if (deg < 100) {
        //         hedgesize_lt_100++;
        //     } else if (deg >= 100 && deg < 1000) {
        //         hedgesize_100_to_1000++;
        //     } else if (deg >= 1000 && deg < 10000) {
        //         hedgesize_1000_to_10000++;
        //     } else {
        //         hedgesize_gt_10000++;
        //     }
        // }
        // out << hedgesize_lt_100 << "," << hedgesize_100_to_1000 << "," << hedgesize_1000_to_10000 << "," << hedgesize_gt_10000 << "\n";

        // std::vector<int> offset(5);
        // std::vector<int> segAvgHedgesize(5,0);
        // offset[0] = (int)(h_vHgrs[0]->hedgeNum * 0.2); offset[1] = (int)(h_vHgrs[0]->hedgeNum * 0.4); offset[2] = (int)(h_vHgrs[0]->hedgeNum * 0.6);
        // offset[3] = (int)(h_vHgrs[0]->hedgeNum * 0.8); offset[4] = h_vHgrs[0]->hedgeNum;
        // for (int i = 0; i < offset.size(); ++i) {
        //     int j = i == 0 ? 0 : offset[i-1];
        //     int seglen = i == 0 ? offset[i] : offset[i] - offset[i-1];
        //     for (; j < offset[i]; ++j) {
        //         segAvgHedgesize[i] += h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)];
        //     }
        //     segAvgHedgesize[i] /= seglen;
        //     out << segAvgHedgesize[i] << ", ";
        // }

        out << (double)d_vHgrs[0]->maxDegree / d_vHgrs[0]->avgHedgeSize << ",";
    }

    if (optCfgs.exp_id == MOTIVATION_DATA_THREAD_UTILIZATION || optCfgs.exp_id == MOTIVATION_DATA_THREAD_UTILIZATION_WITH_NCU_METRIC) {
        // std::string output = "../results/figure4.csv";
        // std::string output = "../results/overP2/thread_utilization.csv";
        std::string output = "../results/overP2/benchmarks_all_thread_utilization.csv";
        std::ofstream out(output, std::ios::app);
        // int blocksize = 128;
        // double avgWorkPerThread = 0;
        // double geom = 0, avgm = 0;
        // for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
        //     int deg = h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)];
        //     avgWorkPerThread += (double)deg / blocksize;
        //     avgm += (double)deg / blocksize;
        //     geom += log((double)deg / blocksize);
        // }
        // avgm /= h_vHgrs[0]->hedgeNum;
        // geom = exp(geom / h_vHgrs[0]->hedgeNum);
        // out << avgm << ", " << geom << ",";

        std::vector<double> thread_utilization(h_vHgrs[0]->hedgeNum, 0);
        double geom = 0, avgm = 0;
        for (int i = 0; i < UP_DIV(h_vHgrs[0]->hedgeNum, 32); i++) {
            int max_work_load = 0;
            for (int j = i * 32; j < (i+1) * 32 && j < h_vHgrs[0]->hedgeNum; j++) {
                max_work_load = max(max_work_load, h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)]);
            }
            for (int j = i * 32; j < (i+1) * 32 && j < h_vHgrs[0]->hedgeNum; j++) {
                thread_utilization[j] = (double)h_vHgrs[0]->hedges[j + E_DEGREE1(h_vHgrs[0]->hedgeNum)] / max_work_load;
                // out << j << ": " << thread_utilization[j] << "\n";
            }
        }
        for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
            geom += log(thread_utilization[i]);
            avgm += thread_utilization[i];
        }
        geom = exp(geom / h_vHgrs[0]->hedgeNum);
        avgm /= h_vHgrs[0]->hedgeNum;
        out << avgm << "," << geom << "\n";
    }

    if (optCfgs.exp_id == MOTIVATION_DATA_IRREGULAR_ACCESS || optCfgs.exp_id == MOTIVATION_DATA_IRREGULAR_ACCESS_WITH_NCU_METRIC) {
        std::string output = "../opts_stats/motivation_data_irregular_access.csv";
        std::ofstream out(output, std::ios::app);
        std::vector<int> nodeid_gap_per_hedge(h_vHgrs[0]->hedgeNum, 0);
        for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
            int min_node = INT_MAX, max_node = 0;
            for (int j = 0; j < h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)]; ++j) {
                int nodeid = h_vHgrs[0]->adj_list[h_vHgrs[0]->hedges[i + E_OFFSET1(h_vHgrs[0]->hedgeNum)] + j] - h_vHgrs[0]->hedgeNum + 1;
                min_node = min(min_node, nodeid);
                max_node = max(max_node, nodeid);
            }
            if (h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)] == 1) {
                nodeid_gap_per_hedge[i] = 1;
            } else {
                nodeid_gap_per_hedge[i] = (max_node - min_node) / (h_vHgrs[0]->hedges[i + E_DEGREE1(h_vHgrs[0]->hedgeNum)] - 1);
            }
            // out << i << ": " << max_node << ", " << min_node << ", " << nodeid_gap_per_hedge[i] << "\n";
        }
        double geom = 0, avgm = 0;
        for (int i = 0; i < h_vHgrs[0]->hedgeNum; ++i) {
            geom += log(nodeid_gap_per_hedge[i]);
            avgm += nodeid_gap_per_hedge[i];
        }
        geom = exp(geom / h_vHgrs[0]->hedgeNum);
        avgm /= h_vHgrs[0]->hedgeNum;
        out << avgm << ", " << geom << ",";
    }

    if (optCfgs.exp_id == MOTIVATION_DATA_WORK_COMPLEXITY || optCfgs.exp_id == MOTIVATION_DATA_WORK_COMPLEXITY_WITH_NCU_METRIC) {
        std::string output = "k12_work_complexity_measurements.csv";
        std::ofstream out(output, std::ios::app);
        out << (double)d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << "," << d_vHgrs[0]->totalEdgeDegree << ",";
    }

    // if (optCfgs.enableSelection) {
    //     optCfgs.useNewKernel1_2_3 = true;
    //     if (d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize > 5) {
    //         optCfgs.optForKernel4 = true;
    //         optCfgs.optForKernel6 = true;
    //     } else if (d_vHgrs[0]->avgHedgeSize > 75) {
    //         optCfgs.optForKernel4 = true;
    //         optCfgs.optForKernel6 = true;
    //     }

    //     if (d_vHgrs[0]->avgHedgeSize >= 75) {
    //         optCfgs.useNewKernel12 = true;
    //         optCfgs.useNewParalOnBaseK12 = 0;
    //         optCfgs.sortHedgeLists = true;
    //         optCfgs.useNewKernel14 = true;
    //         optCfgs.useNewParalOnBaseK12 = 0;
    //     } else {
    //         optCfgs.useNewKernel12 = false;
    //         optCfgs.useNewParalOnBaseK12 = 2;
    //         optCfgs.sortHedgeLists = true;
    //         optCfgs.useNewKernel14 = true;
    //         optCfgs.useNewParalOnBaseK14 = 2;
    //     }
    //     optCfgs.useNewKernel5 = true;
    // }

    std::cout << d_vHgrs[0]->sdHedgeSize /  d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", "
              << optCfgs.useNewKernel1_2_3 << ", " << optCfgs.useNewKernel5 << ", "
              << optCfgs.optForKernel4 << ", " << optCfgs.optForKernel6 << ", "
              << optCfgs.useNewKernel12 << ", " << optCfgs.useNewParalOnBaseK12 << ", " << optCfgs.sortHedgeLists << ", "
              << optCfgs.useNewKernel14 << ", " << optCfgs.useNewParalOnBaseK14 << "\n";

    float imbalance = optCfgs.stats.imbalance_ratio;
    float ratio  = (50.0 + imbalance) / (50.0 - imbalance);
    float tol    = std::max(ratio, 1 - ratio) - 1;
    int hi       = (1 + tol) * h_vHgrs[0]->nodeNum / (2 + tol);
    int LIMIT          = hi / 4;
    std::cout << "BiPart's LIMIT weight: " << LIMIT << "\n";
    if (optCfgs.runBipartWeightConfig || optCfgs.runBaseline) {
        optCfgs.coarseI_weight_limit = LIMIT;
        optCfgs.coarseMore_weight_limit = INT_MAX;
    }
    std::cout << "optionconfigs: " << optCfgs.coarseI_weight_limit << ", " << optCfgs.coarseMore_weight_limit << "\n";
    std::cout << "matching policy: " << optCfgs.matching_policy << "\n";
    printf("optCfgs.runBaseline: %d, optCfgs.runBipartWeightConfig: %d\n", optCfgs.runBaseline, optCfgs.runBipartWeightConfig);

    int iterNum = 0;
    int coarsenTo = 25;
    unsigned size = h_vHgrs[0]->nodeNum;
    unsigned newsize = size;
    unsigned hedgesize = 0;
    Hypergraph* coarsenHgr = d_vHgrs[0];
    // Hypergraph1* coarsenHgr = d_vHgrs[0];
    float coarsen_time = 0.f;
    float other_time = 0.f;
    float alloc_time = 0.f;
    unsigned long memBytes = E_LENGTH1(h_vHgrs[0]->hedgeNum) * sizeof(int) + N_LENGTH1(h_vHgrs[0]->nodeNum) * sizeof(int) + 1 * h_vHgrs[0]->totalEdgeDegree * sizeof(unsigned);
    std::vector<float> coarsen_perf_collector(20, 0.0);
    std::vector<std::pair<std::string, float>> coarsen_perf_collectors(20);
    std::vector<std::vector<std::pair<std::string, float>>> iterate_kernel_breakdown;
    std::cout << "\n============================= start coarsen =============================\n";
    float selectionOverhead = 0.f;
    // bool expression = optCfgs.testFirstIter ? iterNum < 1 : newsize > coarsenTo;
    // while (newsize > coarsenTo) {
    while (optCfgs.testFirstIter ? iterNum < 1 : newsize > coarsenTo) {
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
        // size = coarsenHgr->nodeNum[0];
        // if (optCfgs.testDeterminism) {
        //     d_vHgrs.emplace_back(non_det_coarsen_no_uvm(coarsenHgr, iterNum, LIMIT, coarsen_time, other_time, optCfgs, memBytes, coarsen_perf_collectors, aux));
        // } 
        if (optCfgs.runBruteForce) {
            // k123 k5 k4 k6 k12 k12pattern sort k14 k14pattern memopt
            std::vector<std::tuple<bool, bool, bool, bool, bool, int, bool, bool, int, bool>> configs;
            configs.push_back(std::make_tuple(false, false, false, false, false, 1, false, false, 0, false)); // baseline
            configs.push_back(std::make_tuple(true, true, false, false, false, 1, false, false, 0, true)); // p3_k123_k5
            configs.push_back(std::make_tuple(true, true, true, true, false, 1, false, false, 0, true)); // p3_k4_split_k6
            configs.push_back(std::make_tuple(true, true, false, false, false, 2, true, true, 2, true)); // p3_k12
            configs.push_back(std::make_tuple(true, true, true, true, false, 2, true, true, 2, true)); // p3_k12_p3_k4_split_k6
            configs.push_back(std::make_tuple(true, true, false, false, true, 1, true, true, 0, true)); // p2_k12
            configs.push_back(std::make_tuple(true, true, true, true, true, 1, true, true, 0, true)); // p2_k12_p3_k4_split_k6
            unsigned size = configs.size();
            std::vector<float> time(size, 0.0);
            for (int i = 0; i < configs.size(); ++i) {
            d_vHgrs.emplace_back(coarsen_no_uvm_brute_force(coarsenHgr, iterNum, LIMIT, coarsen_time, other_time, optCfgs, 
                                memBytes, coarsen_perf_collectors, aux, iterate_kernel_breakdown));
            }
        }
        else {
            d_vHgrs.emplace_back(coarsen_no_uvm(coarsenHgr, iterNum, LIMIT, coarsen_time, other_time, optCfgs, memBytes, 
                                coarsen_perf_collectors, aux, iterate_kernel_breakdown, selectionOverhead, alloc_time));
        }
        coarsenHgr = d_vHgrs.back();
        newsize = coarsenHgr->nodeNum;
        hedgesize = coarsenHgr->hedgeNum;
        // newsize = coarsenHgr->nodeNum[0];
        // hedgesize = coarsenHgr->hedgeNum[0];

        if (hedgesize < 1000) {
            std::cout << __LINE__ << "here~~\n";
            break;
        }
        ++iterNum;
        std::cout << "===============================\n\n";
        std::cout << "current kernel 6 time: " << coarsen_perf_collectors[6].second << " ms.\n";
    }
    float total = coarsen_time;
    std::cout << "current allocatd gpu memory size: " << memBytes << " bytes.\n";
    std::cout << "coarsen execution time: " << coarsen_time << " s.\n";
    std::cout << "other parts time: " << other_time << " s.\n";
    std::cout << "finish coarsen.\n";
    
    std::string deviceName = deviceProp.name;
    std::string suffix = "";
    if (deviceName.find("3060 Ti") != std::string::npos) {
        suffix = "_3060Ti";
    } else if (deviceName.find("3090") != std::string::npos) {
        suffix = "_3090";
    }
    // optCfgs.coarsen_kernel_breakdown = coarsen_perf_collector;
    // std::ofstream breakdown1("../opts_stats/coarsen_kernel_breakdown.csv");
    // for (int i = 0; i < coarsen_perf_collectors.size(); ++i) {
    //     // breakdown1 << "kernel" << i << "," << coarsen_perf_collector[i] << "\n";
    //     breakdown1 << "kernel" << i << "," << coarsen_perf_collectors[i].first << "," << coarsen_perf_collectors[i].second << "\n";
    // }
    if (optCfgs.exp_id == COMPARE_BITSET_KERNEL_BREAKDOWN) {
        // std::string output = "../opts_stats/duplica_mark_kernel_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/duplica_mark_kernel_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[12].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_FILLIN_ADJLIST_KERNEL_BREAKDOWN) {
        // std::string output = "../opts_stats/write_adjlist_kernel_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/write_adjlist_kernel_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[14].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_NODE_PRIOR_ASSIGN_KERNEL_PERF) {
        // std::string output = "../opts_stats/kernel1_2_3_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/kernel1_2_3_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_RESET_NODE_PRIOR_KERNEL_PERF) {
        // std::string output = "../opts_stats/reset_nodeprior_kernel_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/reset_nodeprior_kernel_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[5].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_FIRST_MERGING_NODE_KERNEL_BREAKDOWN) {
        // std::string output = "../opts_stats/reset_nodeprior_kernel_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/first_merging_node_kernel_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[4].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_SECOND_MERGING_NODE_KERNEL_BREAKDOWN) {
        // std::string output = "../opts_stats/reset_nodeprior_kernel_breakdown" + suffix + ".csv";
        std::string output = "../opts_stats/second_merging_node_kernel_breakdown.csv";
        std::cout << "dump obtained stats to csv for " << "\n";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[6].second << ",";
        // if (optCfgs.optForKernel6) {
        //     out << "[usenewTest4:" << optCfgs.useNewTest4 << ",usenewTest5:" << optCfgs.useNewTest5 << ",usenewTest6:" << optCfgs.useNewTest6 << "]";
        // }
    }
    if (optCfgs.exp_id == SHOW_SORTING_PERCENTAGE_IN_CONTRACTION) {
        // std::string output = "../opts_stats/sorting_percentage" + suffix + ".csv";
        std::string output = "../opts_stats/sorting_percentage.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_time << "," << coarsen_perf_collectors[16].second / 1000.f << "\n";
    }
    if (optCfgs.exp_id == TEST_DETERMINISTIC_IMPACT_ITER_I_MATCHING_POLICY_KERNEL) {
        std::string output = "../opts_stats/deterministic_impact_on_K123_iter1.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second << ",";
    }
    if (optCfgs.exp_id == PROFILE_ITERATION_WISE_KERNEL_BREAKDOWN) {
        std::string middle = "";
        if (!optCfgs.optForKernel6) middle = "_baseline_kernel6";
        else if (!optCfgs.useTWCoptForKernel6)   middle = "_split_kernel6_wo_TWC";
        else if (!optCfgs.useMarkListForK6) middle = "_split_kernel6_w_TWC";
        else    middle = "_split_kernel6_w_TWC_and_mark";
        std::string output = optCfgs.filename + middle + "_breakdown.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        for (int i = 0; i < iterate_kernel_breakdown.size(); ++i) {
            out << i << ",";
            for (int j = 0; j < iterate_kernel_breakdown[i].size(); ++j) {
                out << iterate_kernel_breakdown[i][j].first << ",";
            }
            out << "\n";
            out << i << ",";
            for (int j = 0; j < iterate_kernel_breakdown[i].size(); ++j) {
                out << iterate_kernel_breakdown[i][j].second << ",";
            }
            out << "\n";
        }
    }
    if (optCfgs.exp_id == VALIDATE_COARSENING_RESULT) {
        coarsening_validation(d_vHgrs.back(), optCfgs.useCUDAUVM);
    }
    optCfgs.coarsen_kernel_breakdown = coarsen_perf_collectors;
    if (optCfgs.exp_id == PROFILE_EACH_ITER_K12_BREAKDOWN) {
        for (int i = 0; i < iterNum; ++i) {
            std::string output = "K12_comparison_each_iteration1.csv";//optCfgs.filename + "_K12_comparison_each_iteration.csv";
            std::ofstream out(output, std::ios::app);
            out << i << "," << optCfgs.iterative_hedgenum[i] << "," << optCfgs.iterative_nodenum[i] << "," 
                << optCfgs.iterative_maxhedgesize[i] << "," << optCfgs.iterative_maxhedgesize[i] / optCfgs.iterative_avghedgesize[i] << "," 
                << optCfgs.iterative_K12[i] << "\n";// << optCfgs.iterative_K12_num_checks[i] << "\n";
        }
    }
    if (optCfgs.exp_id == PROFILE_EACH_ITER_SPLIT_K4_BREAKDOWN) {
        for (int i = 0; i < iterNum; ++i) {
            std::string output = "K4_split_comparison_each_iteration.csv";
            std::ofstream out(output, std::ios::app);
            out << i << ",";
            out << optCfgs.iterative_K4[i] << ",";
            if (optCfgs.optForKernel4) {
                for (int j = 0; j < optCfgs.iterative_split_K4[i].size(); ++j) {
                    out << optCfgs.iterative_split_K4[i][j] << ",";
                }
                out << "\n";
            }
        }
    }
    if (optCfgs.exp_id == PROFILE_FIRST_ITER_K12_BREAKDOWN) {
        std::ofstream out("K12_breakdown_first_iteration.csv", std::ios::app);
        out << optCfgs.filename << "," << optCfgs.iterative_K12[0] << "," << optCfgs.iterative_time[0] << "," << d_vHgrs[0]->maxDegree << "," << d_vHgrs[0]->maxDegree / d_vHgrs[0]->avgHedgeSize << "\n";
    }
    if (optCfgs.exp_id == PROFILE_K1K2K3_BREAKDOWN_COMPARISON) {
        std::ofstream out("../opts_stats/K1K2K3_breakdown_comparison.csv", std::ios::app);
        out << coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_K12_MEMOPT_BREAKDOWN) {
        std::ofstream out("../opts_stats/K12_memopt_breakdown_comparison.csv", std::ios::app);
        out << coarsen_perf_collectors[12].second << ",";
    }
    if (optCfgs.exp_id == COMPARE_K12_BREAKDOWN_WITH_MODELING_METRICS) {
        std::string output = "../modeling_results/K12/" + optCfgs.filename + "_K12_each_iteration_modeling_test.csv";
        std::ofstream out(output, std::ios::app);
        out << "sortInput: " << optCfgs.sortInputById << ", usenewkernel12: " << optCfgs.useNewKernel12 << ", newParBaseK12: " << optCfgs.useNewParalOnBaseK12 
            << ", usenewkernel14: " << optCfgs.useNewKernel14 << ", newParBaseK14: " << optCfgs.useNewParalOnBaseK14 << "\n";
        out << "iterNum,hedgeNum,nodeNum,maxhedgesize,max/avg,avghedgesize,sdhedgesize,sd/avg,K12_total_time,K14_total_time,K12_total_insts,K12_avginsts_perthread,\n";
        for (int i = 0; i < iterNum; ++i) {
            out << i << "," << optCfgs.iterative_hedgenum[i] << "," << optCfgs.iterative_nodenum[i] << "," 
                << optCfgs.iterative_maxhedgesize[i] << "," << optCfgs.iterative_maxhedgesize[i] / optCfgs.iterative_avghedgesize[i] << "," 
                << optCfgs.iterative_avghedgesize[i] << ", " << optCfgs.iterative_sdhedgesize[i] << "," << (double)optCfgs.iterative_sdhedgesize[i] / optCfgs.iterative_avghedgesize[i] << ", "
                << optCfgs.iterative_K12[i] << ",  " << optCfgs.iterative_K14[i] << ", " << optCfgs.iterative_K12_num_opcost[i] << ", " << optCfgs.iter_perthread_K12_numopcost[i] << "\n";
            // out << i << "," << optCfgs.iterative_hedgenum[i] << "," << optCfgs.iterative_nodenum[i] << "," 
            //     << optCfgs.iterative_maxhedgesize[i] << "," << optCfgs.iterative_maxhedgesize[i] / optCfgs.iterative_avghedgesize[i] << "," 
            //     << optCfgs.iterative_K12[i] << ",  " << "\n";
        }
    }
    if (optCfgs.exp_id == COMPARE_K4_BREAKDOWN_WITH_MODELING_METRICS) {
        std::string output = "../modeling_results/K4/" + optCfgs.filename + "_K4_each_iteration_modeling_test.csv";
        std::ofstream out(output, std::ios::app);
        out << "sortInput: " << optCfgs.sortInputById << ", usesplitopt: " << optCfgs.optForKernel4 << ", pureSplitK4:" << optCfgs.pureSplitK4 << "\n";
        if (!optCfgs.optForKernel4) {
            out << "iterNum,hedgeNum,nodeNum,maxhedgesize,max/avg,avghedgesize,sdhedgesize,sd/avg,total_time,total_clocks,avgclock_unitwork,\n";
        } else {
            out << "iterNum,hedgeNum,nodeNum,maxhedgesize,max/avg,avghedgesize,sdhedgesize,sd/avg,total_time,k1_time,k2_time,k3_time,k4_time,"
                << "total_clocks,avgclock_unitwork,k1_clocks,k3_clocks,k4_clocks,k1_avgclocks,k3_avgclocks,k4_avgclocks\n";
        }
        for (int i = 0; i < iterNum; ++i) {
            out << i << "," << optCfgs.iterative_hedgenum[i] << "," << optCfgs.iterative_nodenum[i] << "," 
                << optCfgs.iterative_maxhedgesize[i] << "," << (double)optCfgs.iterative_maxhedgesize[i] / optCfgs.iterative_avghedgesize[i] << ", "
                << optCfgs.iterative_avghedgesize[i] << ", " << optCfgs.iterative_sdhedgesize[i] << "," << (double)optCfgs.iterative_sdhedgesize[i] / optCfgs.iterative_avghedgesize[i] << ", " 
                << optCfgs.iterative_K4[i] << ",";
            if (optCfgs.optForKernel4) {
                // out << ",  " << optCfgs.iterative_K4_num_opcost[i] << ", " << optCfgs.iter_perthread_K4_numopcost[i] << ", || (K4 split_times), ";
                out << "|| (K4 split_times), ";
                for (int j = 0; j < optCfgs.iterative_split_K4[i].size(); ++j) {
                    out << optCfgs.iterative_split_K4[i][j] << ", ";
                }
                out << "|| (split_clocks), ";
                for (int j = 0; j < optCfgs.iterative_split_K4_in_kernel[i].size(); ++j) {
                    out << optCfgs.iterative_split_K4_in_kernel[i][j] << ", ";
                }
                // out << optCfgs.iterative_split_K4[i][0] << ", " << optCfgs.iterative_split_K4[i][1] << ", " << optCfgs.iterative_split_K4[i][2] << optCfgs.iterative_split_K4[i][3] << ",";
                // out << optCfgs.iterative_split_K4_in_kernel[i][0] << "," << optCfgs.iterative_split_K4_in_kernel[i][1] << ",";
                // out << optCfgs.iterative_split_K4_in_kernel[i][2] << "," << optCfgs.iterative_split_K4_in_kernel[i][3] << "," << optCfgs.iterative_split_K4_in_kernel[i][4] << ",";
                // out << optCfgs.iterative_split_K4_in_kernel[i][5] << "," << optCfgs.iterative_split_K4_in_kernel[i][6] << "," << optCfgs.iterative_split_K4_in_kernel[i][7] << ",";
                out << "\n";
            } else {
                // out << ",  " << optCfgs.iterative_K4_num_opcost[i] << ", " << optCfgs.iter_perthread_K4_numopcost[i] << ", || ";
                out << "|| (K4 single_elaps), ";
                for (int j = 0; j < optCfgs.iterative_split_K4_in_kernel[i].size(); ++j) {
                    out << optCfgs.iterative_split_K4_in_kernel[i][j] << ", ";
                }
                out << "\n";
            }
        }
    }
    if (optCfgs.exp_id == COMPARE_K6_BREAKDOWN_WITH_MODELING_METRICS) {
        std::string output = "../modeling_results/K6/" + optCfgs.filename + "_K6_each_iteration_modeling_test.csv";
        std::ofstream out(output, std::ios::app);
        out << "sortInput: " << optCfgs.sortInputById << ", usesplitopt: " << optCfgs.optForKernel6 << ", useTWCopt:" << optCfgs.useTWCoptForKernel6 << ", useMarkList: " << optCfgs.useMarkListForK6 <<  "\n";
        out << "iterNum,hedgeNum,nodeNum,maxhedgesize,max/avg,avghedgesize,sdhedgesize,sd/avg,total_time,\n";
        for (int i = 0; i < iterNum; ++i) {
            out << i << "," << optCfgs.iterative_hedgenum[i] << "," << optCfgs.iterative_nodenum[i] << "," 
                << optCfgs.iterative_maxhedgesize[i] << "," << (double)optCfgs.iterative_maxhedgesize[i] / optCfgs.iterative_avghedgesize[i] << ", "
                << optCfgs.iterative_avghedgesize[i] << ", " << optCfgs.iterative_sdhedgesize[i] << "," << (double)optCfgs.iterative_sdhedgesize[i] / optCfgs.iterative_avghedgesize[i] << ", "
                << optCfgs.iterative_K6[i] << ",";
            if (optCfgs.optForKernel6) {
                // TODO.
                out << "\n";
            } else {
                out << "\n";
            }
        }
    }
    if (optCfgs.exp_id == COARSENING_STAGE_BREAKDOWN) { // baseline
        std::string output = "../opts_stats/coarsening_each_stage_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[0].second + coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second << ","
            << coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second + coarsen_perf_collectors[7].second + coarsen_perf_collectors[8].second << ","
            << coarsen_perf_collectors[9].second + coarsen_perf_collectors[10].second + coarsen_perf_collectors[11].second << ","
            << coarsen_perf_collectors[12].second + coarsen_perf_collectors[13].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[15].second << ",";
    }
    if (optCfgs.exp_id == PROFILE_AVG_HEDGE_NUM_PROCESSED_PER_SECOND) {
        std::string output = "../opts_stats/avg_hedge_num_kernel_processed_per_second.csv";
        std::ofstream out(output, std::ios::app);
        out << iterate_kernel_breakdown[0][1].second << "," << iterate_kernel_breakdown[0][4].second << "," << iterate_kernel_breakdown[0][6].second << ","
            << iterate_kernel_breakdown[0][12].second << "," << iterate_kernel_breakdown[0][14].second << ","
            << optCfgs.iterative_hedgenum[0] << "," << optCfgs.iterative_adjlist_size[0] << ","
            << (double)optCfgs.iterative_hedgenum[0] / iterate_kernel_breakdown[0][1].second << "," << (double)optCfgs.iterative_hedgenum[0] / iterate_kernel_breakdown[0][4].second << ","
            << (double)optCfgs.iterative_hedgenum[0] / iterate_kernel_breakdown[0][6].second << "," << (double)optCfgs.iterative_hedgenum[0] / iterate_kernel_breakdown[0][12].second << ","
            << (double)optCfgs.iterative_hedgenum[0] / iterate_kernel_breakdown[0][14].second;
    }
    if (optCfgs.exp_id == MOTIVATION_DATA_FOR_KERNEL_SELECTION) {
        std::string output = "../opts_stats/motivation_data_k12_dram_utilization.csv";
        std::ofstream out(output, std::ios::app);
        out << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K12[0] << ", ";

        // std::string output1 = "../opts_stats/motivation_data_k4_dram_utilization.csv";
        // std::ofstream out1(output1, std::ios::app);
        // out1 << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K4[0] << ", ";

        // std::string output2 = "../opts_stats/motivation_data_k6_dram_utilization.csv";
        // std::ofstream out2(output2, std::ios::app);
        // out2 << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K6[0] << ", ";
    }
    if (optCfgs.exp_id == MOTIVATION_DATA_FOR_KERNEL4_SELECTION) {
        // std::string output = "../opts_stats/motivation_data_k12_dram_utilization.csv";
        // std::ofstream out(output, std::ios::app);
        // out << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K12[0] << ", ";

        std::string output = "../opts_stats/motivation_data_k4_dram_utilization.csv";
        std::ofstream out1(output, std::ios::app);
        out1 << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K4[0] << ", ";
    }
    if (optCfgs.exp_id == MOTIVATION_DATA_FOR_KERNEL6_SELECTION) {
        // std::string output = "../opts_stats/motivation_data_k12_dram_utilization.csv";
        // std::ofstream out(output, std::ios::app);
        // out << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K12[0] << ", ";

        std::string output = "../opts_stats/motivation_data_k6_dram_utilization.csv";
        std::ofstream out1(output, std::ios::app);
        out1 << d_vHgrs[0]->sdHedgeSize / d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->sdHedgeSize << ", " << d_vHgrs[0]->avgHedgeSize << ", " << d_vHgrs[0]->hedgeNum << ", " << optCfgs.iterative_K6[0] << ", ";
    }

    if (optCfgs.exp_id == SLOWEST_THREAD_IMPACT_ON_DUPLICATE_REMOVAL_KERNEL) {
        std::string output = "../opts_stats/slowest_thread_impact_on_duplicate_removal_kernel.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[12].second << ", ";
    }
#if 0
    unsigned* h_nets = (unsigned*)malloc(d_vHgrs.back()->totalNodeDegree * sizeof(unsigned));
    CHECK_ERROR(cudaMemcpy((void *)h_nets, d_vHgrs.back()->incident_nets, d_vHgrs.back()->totalNodeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
    unsigned* h_nodes = (unsigned*)malloc(N_LENGTH1(d_vHgrs.back()->nodeNum) * sizeof(int));
    CHECK_ERROR(cudaMemcpy((void *)h_nodes, d_vHgrs.back()->nodes, N_LENGTH1(d_vHgrs.back()->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
    std::ofstream outnets("gpu_nouvm_incident_netlists.txt");
    for (int i = 0; i < d_vHgrs.back()->nodeNum; ++i) {
        std::sort(h_nets + h_nodes[N_OFFSET1(d_vHgrs.back()->nodeNum) + i], 
                  h_nets + h_nodes[N_OFFSET1(d_vHgrs.back()->nodeNum) + i] + h_nodes[N_DEGREE1(d_vHgrs.back()->nodeNum) + i]);
        outnets << "node " << i << "'s incident netid: ";
        for (int j = 0; j < h_nodes[N_DEGREE1(d_vHgrs.back()->nodeNum) + i]; ++j) {
            outnets << h_nets[h_nodes[N_OFFSET1(d_vHgrs.back()->nodeNum) + i] + j] << " ";
        }
        outnets << "\n";
    }
    free(h_nets);
#endif
    
    std::cout << "\n============================= start initial partition =============================\n";
    float partition_time = 0.f;
    unsigned int numPartitions = optCfgs.numPartitions;//2;
    bool use_curr_precision = true;
    float malloc_copy_time = other_time;
    other_time = 0.f;
    if (optCfgs.filename == "ecology1.mtx.hgr") {
        use_curr_precision = false;
    }
    if (optCfgs.useCoarseningOpts <= 2 && !optCfgs.useInitPartitionOpts && !optCfgs.useRefinementOpts) {
        optCfgs.useFirstTwoOptsOnly = true;
    }
    if (!optCfgs.testFirstIter) {
#if 1
    if (optCfgs.runBaseline || optCfgs.useInitPartitionOpts != FIX_HEAVIEST_NODE) {
        init_partition_no_uvm(d_vHgrs.back(), numPartitions, use_curr_precision, partition_time, other_time, optCfgs);
    } else {
        init_partition_fix_heaviest_node(d_vHgrs.back(), numPartitions, use_curr_precision, partition_time, other_time, optCfgs);
    }
    std::cout << "finish initial partition.\n";
    std::cout << "initial partition time: " << partition_time << " s.\n";
    total += partition_time;
    if (optCfgs.exp_id == VALIDATE_INITIAL_PARTITION_RESULT) {
        initial_partitioning_validation(d_vHgrs.back(), optCfgs.useCUDAUVM);
    }
#endif
    }

    std::cout << "\n============================= start refinement =============================\n";
    float Refine_time = 0.f;
    float refine_time = 0.f;
    float balance_time = 0.f;
    float project_time = 0.f;
    int rebalance = 0;
    int curr_idx = d_vHgrs.size()-1;
    int hyperedge_cut = 0;
    int comb_len = 8;
    other_time = 0.f;
    if (optCfgs.useRefinementOpts == MERGING_MOVE) {
        optCfgs.switchToMergeMoveLevel = iterNum + 1;
    }
    if (optCfgs.useRefinementOpts == GAIN_RECALCULATION) {
        optCfgs.comb_len = 8;
    }
    unsigned refineTo = optCfgs.refineIterPerLevel;//2;
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
    // if (!optCfgs.testFirstIter) {
    if (optCfgs.runRefine) {
#if 1
    if (!optCfgs.runReverseRefine) {
        do {
            float cur_ref = 0.f;
            float cur_bal = 0.f;
            float cur_pro = 0.f;
            if (optCfgs.runBaseline || optCfgs.useFirstTwoOptsOnly == true) {
                refine_no_uvm(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, curr_idx, optCfgs);
                // rebalance_no_uvm(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                rebalance_no_uvm_without_multiple_sort(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                // break;
            } else {
                if (optCfgs.useRefinementOpts == ADAPTIVE_MOVING || optCfgs.useRefinementOpts == MERGING_MOVE) {
                    refine_no_uvm_with_hybrid_move(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, curr_idx, optCfgs);
                    rebalance_no_uvm_without_multiple_sort(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                }
                if (optCfgs.useRefinementOpts == GAIN_RECALCULATION) {
                    refine_no_uvm_with_movegain_verify(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, numPartitions, comb_len, ratio, imbalance, curr_idx, optCfgs);
                    rebalance_no_uvm_without_multiple_sort(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                }
                if (optCfgs.useRefinementOpts == FIX_HEAVIEST_NODE) {
                    refine_no_uvm_fix_heaviest_node(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, curr_idx, optCfgs);
                    rebalance_no_uvm_single_sort_fix_heaviest_node(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                }
                if (optCfgs.useRefinementOpts == FIX_NODE_ADAP_MOVE) {
                    refine_no_uvm_fix_node_hybrid_move(d_vHgrs[curr_idx], refineTo, refine_time, cur_ref, other_time, curr_idx, optCfgs);
                    rebalance_no_uvm_single_sort_fix_heaviest_node(d_vHgrs[curr_idx], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
                }
            }
            if (curr_idx > 0) {
                project_no_uvm(d_vHgrs[curr_idx], d_vHgrs[curr_idx-1], project_time, other_time, cur_pro, curr_idx);
            }
            // std::cout << "curr_iter:" << curr_idx << ", edgecut:" << computeHyperedgeCut(d_vHgrs[curr_idx], optCfgs.useCUDAUVM) << "\n";
            std::cout << "cur_ref:" << cur_ref << ", cur_bal:" << cur_bal << ", cur_pro:" << cur_pro << "\n";
            curr_idx--;
            std::cout << "===============================\n\n";
        } while (curr_idx >= 0);
    } else {
        do {
            float cur_ref = 0.f;
            float cur_bal = 0.f;
            float cur_pro = 0.f;
            if (curr_idx > 0) {
                project_no_uvm(d_vHgrs[curr_idx], d_vHgrs[curr_idx-1], project_time, other_time, cur_pro, curr_idx);
            }
            if (optCfgs.runBaseline || optCfgs.useFirstTwoOptsOnly == true) {
                refine_no_uvm(d_vHgrs[curr_idx-1], refineTo, refine_time, cur_ref, other_time, curr_idx, optCfgs);
                rebalance_no_uvm_without_multiple_sort(d_vHgrs[curr_idx-1], ratio, numPartitions, imbalance, balance_time, cur_bal, other_time, rebalance, curr_idx, optCfgs, memBytes);
            }
            std::cout << "cur_ref:" << cur_ref << ", cur_bal:" << cur_bal << ", cur_pro:" << cur_pro << "\n";
            curr_idx--;
            std::cout << "===============================\n\n";
        } while (curr_idx >= 1);
    }
#endif
    }

    hyperedge_cut = computeHyperedgeCut(d_vHgrs[0], optCfgs.useCUDAUVM);
    optCfgs.stats.hyperedge_cut_num = hyperedge_cut;
    std::cout << "finish calculating edge cut..\n";
    if (optCfgs.exp_id == VALIDATE_FINAL_PARTITION_RESULT) {
        final_partitioning_validation(d_vHgrs[0], optCfgs.stats, optCfgs.useCUDAUVM);
    }
    std::cout << "finish final result validation..\n";
    computeBalanceResult(d_vHgrs[0], numPartitions, imbalance, optCfgs.stats.parts, optCfgs.useCUDAUVM);
    std::cout << "finish calculating balance result..\n";

    if (optCfgs.start) 
    {
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
    std::cout << "init_partition imbalance " << optCfgs.stats.init_partition_imbalance << "\n";
    std::cout << "Balance results:[epsilon = " << imbalance / 100.0f << "]:\n";
    // printBalanceResult(d_vHgrs[0], numPartitions, imbalance, optCfgs.useCUDAUVM);
    for (int i = 0; i < numPartitions; ++i) {
        std::cout << "|Partition " << i << "| = " << optCfgs.stats.parts[i] << ", |V|/" << numPartitions << " = " << d_vHgrs[0]->nodeNum / numPartitions
                << ", final ratio: " << fabs(optCfgs.stats.parts[i] - d_vHgrs[0]->nodeNum / numPartitions) / (float)(d_vHgrs[0]->nodeNum / numPartitions) << "\n";
    }
    std::cout << "===============================================================================================\n";
    
    if (optCfgs.exp_id == COMPARE_KERNEL_TIME_WITH_OTHER_TIME) {
        // std::string output = "../opts_stats/kernel_time_vs_memcopy_time_breakdown.csv";
        std::string output = "../results/overP2/kernel_time_vs_memcopy_time_baseline.csv";
        std::ofstream out(output, std::ios::app);
        // out << total << "," << malloc_copy_time << "," << elapsed << ", " << elapsed1 << ", " << elapsed2 << "\n";
        out << total << "," << malloc_copy_time << "," << malloc_copy_time / (malloc_copy_time + total) << ","
            << alloc_time / (alloc_time + malloc_copy_time + total) << ","
            << (alloc_time + malloc_copy_time) / (alloc_time + malloc_copy_time + total) << "\n";
    }

    if (optCfgs.exp_id == COARSENING_STAGE1_SPEEDUP_OVER_BASELINE) {
        std::string output = "../opts_stats/coarsen_stage1_speedup_over_gpu_baseline.csv";
        std::ofstream out(output, std::ios::app);
        out << (coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second)/1000.f << "," << coarsen_time << "," << total << ",|,";
    }

    if (optCfgs.exp_id == COARSENING_STAGE2_SPEEDUP_OVER_BASELINE) {
        std::string output = "../opts_stats/coarsen_stage2_speedup_over_gpu_baseline.csv";
        std::ofstream out(output, std::ios::app);
        // if (optCfgs.testOptPerf) {
        //     coarsen_perf_collectors[5].second *= 0.9;
        // }
        // out << (coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second)/1000.f << "," << coarsen_time << "," << total << ",";
        out << coarsen_perf_collectors[4].second/1000.f << ", " << coarsen_perf_collectors[6].second/1000.f << ", " << coarsen_perf_collectors[5].second/1000.f << ", "
            << (coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second)/1000.f << "," << coarsen_time << "," << total << ",|,";
    }

    if (optCfgs.exp_id == COARSENING_STAGE4_SPEEDUP_OVER_BASELINE) {
        std::string output = "../opts_stats/coarsen_stage4_speedup_over_gpu_baseline.csv";
        std::ofstream out(output, std::ios::app);
        if (!optCfgs.sortHedgeLists) {
            out << (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[13].second + coarsen_perf_collectors[15].second)/1000.f << "," << coarsen_time << "," << total << ",|,";
        } else {
            out << (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[13].second +  + coarsen_perf_collectors[15].second + 
                    coarsen_perf_collectors[16].second)/1000.f << "," << coarsen_time << "," << total << ",|,";
        }
    }

    if (optCfgs.exp_id == NODE_MERGING_AND_CONSTRUCTION_PERCENTAGE) {
        std::string output = "../results/overP2/kernel_percentage_all_overP2_warmup.csv";
        std::ofstream out(output, std::ios::app);
        float matching_time = (coarsen_perf_collectors[0].second + coarsen_perf_collectors[1].second + coarsen_perf_collectors[2].second + coarsen_perf_collectors[3].second) / 1000.f;
        // float node_merging_time = (coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second) / 1000.f;
        float node_merging_time = (coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second + 
                                   coarsen_perf_collectors[7].second + coarsen_perf_collectors[8].second) / 1000.f;
        // float node_merging_time = (coarsen_perf_collectors[4].second + coarsen_perf_collectors[5].second + coarsen_perf_collectors[6].second + 
        //                            coarsen_perf_collectors[7].second + coarsen_perf_collectors[8].second +
        //                            coarsen_perf_collectors[9].second + coarsen_perf_collectors[10].second + coarsen_perf_collectors[11].second) / 1000.f;
        float construction_time = (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[13].second + coarsen_perf_collectors[15].second) / 1000.f;
        
        float matching_perc = matching_time / total;
        float node_merging_perc = node_merging_time / total;
        float construction_perc = construction_time / total;
        float node_merging_perc_in_remaining = node_merging_time / (total - construction_time);
        float matching_perc_in_remaining = matching_time / (total - construction_time);
        float node_merging_perc_in_remain_coarsen = node_merging_time / (coarsen_time - construction_time);
        float coarsen_perc = coarsen_time / total;
        float Refine_perc = Refine_time / total;
        float partition_perc = 1 - (coarsen_perc + Refine_perc);
        float refine_perc = refine_time / total;
        float balance_perc = balance_time / total;
        float project_perc = project_time / total;
        out << matching_time << "," << node_merging_time << "," << construction_time << "," << total << "," 
            << matching_perc << "," << node_merging_perc << "," << construction_perc << "," << 1 - node_merging_perc - construction_perc - matching_perc << ","
            << d_vHgrs[0]->hedgeNum << "," << d_vHgrs[0]->totalEdgeDegree << "," << d_vHgrs[0]->avgHedgeSize << "," 
            << node_merging_perc_in_remaining << "," << node_merging_perc_in_remain_coarsen << "," << matching_perc_in_remaining << ","
            << coarsen_perc << "," << Refine_perc << "," << partition_perc << ","
            << refine_perc << "," << balance_perc << "," << project_perc << ",edgecut:"
            << hyperedge_cut << "\n";
        std::cout << matching_time << "," << node_merging_time << "," << construction_time << "," << total << "," 
            << matching_perc << "," << node_merging_perc << "," << construction_perc << "," << 1 - node_merging_perc - construction_perc << ","
            << d_vHgrs[0]->hedgeNum << "," << d_vHgrs[0]->totalEdgeDegree << "," << d_vHgrs[0]->avgHedgeSize << "," 
            << node_merging_perc_in_remaining << "," << node_merging_perc_in_remain_coarsen << "," << matching_perc_in_remaining << ","
            << coarsen_perc << "," << Refine_perc << "," << partition_perc << ","
            << refine_perc << "," << balance_perc << "," << project_perc << ",edgecut:"
            << hyperedge_cut << "\n";
    }

    if (optCfgs.exp_id == DIFFERENT_PATTERNS_ON_NODE_MERGING_PERF) {
        // std::string output = "../opts_stats/pattern_impact_on_nodemerging_perf.csv";
        // std::string output = "../results/figure11.csv";
        std::string output = "../results/overP2/benchmarks_all_nodemerging_procedure_overP2_240104.csv";
        std::ofstream out(output, std::ios::app);
        // if (optCfgs.testOptPerf) {
        //     total *= 0.95;
        // }
        float node_merging_time = (coarsen_perf_collectors[4].second + coarsen_perf_collectors[6].second) / 1000.f;
        // out << node_merging_time << ", " << total << ", ";
        std::cout << "node_merging_time: " << node_merging_time << ", ";
    }

    if (optCfgs.exp_id == DIFFERENT_PATTERNS_ON_CONSTRUCTION_PERF) {
        // std::string output = "../opts_stats/pattern_impact_on_construction_perf.csv";
        // std::string output = "../results/figure12.csv";
        std::string output = "../results/overP2/benchmarks_all_construction_procedure_overP2_240104.csv";
        std::ofstream out(output, std::ios::app);
        // float construction_time = (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[13].second + coarsen_perf_collectors[15].second) / 1000.f;
        float construction_time = (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second) / 1000.f;
        if (optCfgs.testOptPerf) {
            // total *= 0.95;
            // coarsen_perf_collectors[16].second *= 0.95;
            construction_time = (coarsen_perf_collectors[12].second + coarsen_perf_collectors[14].second + coarsen_perf_collectors[16].second) / 1000.f;
        }
        // out << construction_time << ", " << total << ", ";
        std::cout << "construction_time: " << construction_time << ", ";
    }

    if (optCfgs.exp_id == PROFILE_DETERMINISTIC_OVERHEAD) {
        std::string output = "../results/overP2/benchmarks_all_sorting_overhead.csv";
        std::ofstream out(output, std::ios::app);
        out << coarsen_perf_collectors[16].second / 1000.f << "," << total << "," << coarsen_perf_collectors[16].second / 1000.f / total << "\n";
    }

    if (optCfgs.exp_id == EDGE_CUT_QUALITY_COMPARISON) {
        std::string output = "../results/figure14.csv";
        std::ofstream out(output, std::ios::app);
        out << optCfgs.stats.hyperedge_cut_num << ",\n";
    }

    optCfgs.stats.Refine_time = Refine_time;
    optCfgs.stats.refine_time = refine_time;
    optCfgs.stats.balance_time = balance_time;
    optCfgs.stats.project_time = project_time;
    optCfgs.stats.rebalance = rebalance;
    optCfgs.stats.total_time = total;
    optCfgs.stats.coarsen_time = coarsen_time;
    optCfgs.stats.coarsen_iterations = iterNum;
    optCfgs.stats.memBytes = memBytes;
    optCfgs.stats.coarsen_cuda_memcpy_time = other_time;
    optCfgs.stats.memcpy_time = malloc_copy_time;
    optCfgs.stats.partition_time = partition_time;
    optCfgs.stats.suffix = suffix;
    
    optCfgs.statistics2csv();
    }

    for (int i = 1; i < d_vHgrs.size(); ++i) {
        Hypergraph* d_hgr = d_vHgrs[i];
        CHECK_ERROR(cudaFree(d_hgr->adj_list));
        CHECK_ERROR(cudaFree(d_hgr->nodes));
        CHECK_ERROR(cudaFree(d_hgr->hedges));
    }

    // perform kway partition
    if (numPartitions > 2) {
        optCfgs.stats.parts.clear();
        kway_partition_no_uvm(d_vHgrs[0], numPartitions, total, malloc_copy_time, optCfgs);
    }
    optCfgs.stats.parts.clear();
    hyperedge_cut = computeHyperedgeCut(d_vHgrs[0], optCfgs.useCUDAUVM);
    optCfgs.stats.hyperedge_cut_num = hyperedge_cut;
    std::cout << "# of Hyperedge cut: " << hyperedge_cut << "\n";
    computeBalanceResult(d_vHgrs[0], numPartitions, imbalance, optCfgs.stats.parts, optCfgs.useCUDAUVM);
    for (int i = 0; i < numPartitions; ++i) {
        int gap = optCfgs.stats.parts[i] < d_vHgrs[0]->nodeNum / numPartitions ? 
                    d_vHgrs[0]->nodeNum / numPartitions - optCfgs.stats.parts[i] : 
                    optCfgs.stats.parts[i] - d_vHgrs[0]->nodeNum / numPartitions;
        std::cout << "|Partition " << i << "| = " << optCfgs.stats.parts[i] << ", |V|/" << numPartitions << " = " << d_vHgrs[0]->nodeNum / numPartitions
                  << ", final ratio: " << fabs(gap) / (float)(d_vHgrs[0]->nodeNum / numPartitions) << "\n";
    }

    if (!optCfgs.start) return;

    std::cout << "Total k-way partition time (s): " << total << "\n";
    std::cout << "Total cuda malloc && memcpy time (s): " << malloc_copy_time << "\n";
    
    // while (!d_vHgrs.empty()) {
    //     Hypergraph* d_hgr = d_vHgrs.back();
    //     d_vHgrs.pop_back();
    //     CHECK_ERROR(cudaFree(d_hgr->incident_nets));
    //     CHECK_ERROR(cudaFree(d_hgr->par_list));
    //     CHECK_ERROR(cudaFree(d_hgr->adj_list));
    //     CHECK_ERROR(cudaFree(d_hgr->nodes));
    //     CHECK_ERROR(cudaFree(d_hgr->hedges));
    //     // CHECK_ERROR(cudaFree(d_hgr));
    //     free(d_hgr);
    // }
    // while (!h_vHgrs.empty()) {
    //     Hypergraph* h_hgr = h_vHgrs.back();
    //     h_vHgrs.pop_back();
    //     free(h_hgr->incident_nets);
    //     free(h_hgr->adj_list);
    //     free(h_hgr->par_list);
    //     free(h_hgr->nodes);
    //     free(h_hgr->hedges);
    //     free(h_hgr);
    // }
}

