#include "validation.cuh"

void coarsening_validation(Hypergraph* hgr, bool useUVM) {
    if (useUVM) {
        std::ofstream debug("../debug/coarsen_final_results1.txt");
        for (int i = 0; i < E_LENGTH(hgr); ++i) {
            debug << hgr->hedges[i] << "\n";
        }
        debug << "================\n";
        for (int i = 0; i < N_LENGTH(hgr); ++i) {
            debug << hgr->nodes[i] << "\n";
        }
        debug << "================\n";
        for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
            debug << hgr->adj_list[i] << "\n";
        }
    } else {
        std::ofstream debug("../debug/coarsen_final_results.txt");
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        int* hedge = (int*)malloc(E_LENGTH1(hgr->hedgeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)hedge, hgr->hedges, E_LENGTH1(hgr->hedgeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        unsigned* adj_list = (unsigned*)malloc(hgr->totalEdgeDegree * sizeof(unsigned));
        CHECK_ERROR(cudaMemcpy((void *)adj_list, hgr->adj_list, hgr->totalEdgeDegree * sizeof(unsigned), cudaMemcpyDeviceToHost));
        for (int i = 0; i < E_LENGTH1(hgr->hedgeNum); ++i) {
            debug << hedge[i] << "\n";
        }
        debug << "================\n";
        for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
            debug << nodes[i] << "\n";
        }
        debug << "================\n";
        for (int i = 0; i < hgr->totalEdgeDegree; ++i) {
            debug << adj_list[i] << "\n";
        }
        free(adj_list);
        free(hedge);
        free(nodes);
    }
    std::cout << "finish " << __FUNCTION__ << ", useUVM:" << useUVM << "\n";
}

void initial_partitioning_validation(Hypergraph* hgr, bool useUVM) {
    if (useUVM) {
        std::ofstream debug("../debug/initial_partition_results1.txt");
        for (int i = 0; i < N_LENGTH(hgr); ++i) {
            debug << hgr->nodes[i] << "\n";
        }
    } else {
        std::ofstream debug("../debug/initial_partition_results.txt");
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
            debug << nodes[i] << "\n";
        }
        free(nodes);
    }
    std::cout << "finish " << __FUNCTION__ << ", useUVM:" << useUVM << "\n";
}

void final_partitioning_validation(Hypergraph* hgr, Stats stats, bool useUVM) {
    if (useUVM) {
        std::ofstream debug("../debug/final_partition_results1.txt");
        for (int i = 0; i < N_LENGTH(hgr); ++i) {
            debug << hgr->nodes[i] << "\n";
        }
        debug << "=====================\n";
        debug << "Final solution quality: " << stats.hyperedge_cut_num << "\n";
    } else {
        std::ofstream debug("../debug/final_partition_results.txt");
        int* nodes = (int*)malloc(N_LENGTH1(hgr->nodeNum) * sizeof(int));
        CHECK_ERROR(cudaMemcpy((void *)nodes, hgr->nodes, N_LENGTH1(hgr->nodeNum) * sizeof(int), cudaMemcpyDeviceToHost));
        for (int i = 0; i < N_LENGTH1(hgr->nodeNum); ++i) {
            debug << nodes[i] << "\n";
        }
        debug << "=====================\n";
        debug << "Final solution quality: " << stats.hyperedge_cut_num << "\n";
        free(nodes);
    }
}

