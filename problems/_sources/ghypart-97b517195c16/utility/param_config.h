#pragma once
#include <iostream>
#include <limits.h>
#include <sys/time.h>
#include <getopt.h>
#include <fstream>
#include <string>
#include <unordered_set>
#include <experimental/filesystem>
#include <vector>
#include "../include/graph.h"

class Stats {
public:
    float coarsen_time = 0.f;
    float partition_time = 0.f;
    float Refine_time = 0.f;
    float refine_time = 0.f;
    float balance_time = 0.f;
    float project_time = 0.f;
    float total_time = 0.f;
    float memcpy_time = 0.f;
    int rebalance = 0;
    int coarsen_iterations = 0;
    int hyperedge_cut = 0;
    float imbalance_ratio = 5.0;
    float init_partition_imbalance = 0.0;
    int maxNodeWeight = 0;
    unsigned memBytes = 0;
    int total_hedge_num = 0;
    int total_node_num = 0;
    int total_nondup_hedgenum = 0;
    float coarsen_cuda_memcpy_time = 0.f;
    int hyperedge_cut_num = 0;
    std::vector<int> parts;
    std::string suffix = "";
};

class ModelingMetrics {
public:
    int k12_mem_access_num = 0;
    
};

enum EXPERIMENT_ID {
    PROFILE_WEIGHT_CONSTRAIT_CONFIGS = 1,
    COMPARE_BASE_WITH_WEIGHT_LIMIT_OPT = 2,
    COMPARE_BASE_WITH_NODE_FIXING_OPT = 3,
    COMPARE_BASE_WITH_GAIN_RECALCULATION_OPT = 4,
    COMPARE_BASE_WITH_MERGING_MOVE_OPT = 5,
    COMPARE_BASE_WITH_BEST_QUALITY_RESULTS = 6,
    COMPARE_PERF_WITH_NON_UVM_IMPL = 7,
    PRINT_ALLOCATE_MEM_SPACE = 8,
    VALIDATE_COARSENING_RESULT = 9,
    VALIDATE_INITIAL_PARTITION_RESULT = 10,
    VALIDATE_FINAL_PARTITION_RESULT = 11,
    COMPARE_PERF_WITH_SINGLE_REBALANCE_SORT = 12,
    
    COMPARE_BITSET_KERNEL_BREAKDOWN = 13,
    SHOW_SORTING_PERCENTAGE_IN_CONTRACTION = 14,
    COMPARE_E2E_PERF_WITH_BITSET_MARKING_OPT = 15,
    COMPARE_QUALITY_WITH_ADDING_SORTING = 16,
    COMPARE_FILLIN_ADJLIST_KERNEL_BREAKDOWN = 17,
    COMPARE_E2E_PERF_WITH_ATOMIC_WRITE_ADJLIST = 18,
    
    COMPARE_NODE_PRIOR_ASSIGN_KERNEL_PERF = 19,
    COMPARE_E2E_PERF_WITH_KERNEL1_2_3_OPT = 20,
    COMPARE_RESET_NODE_PRIOR_KERNEL_PERF = 21,
    COMPARE_E2E_PERF_WITH_KERNEL5_OPT = 22,
    PROFILE_OVERALL_COARSEN_SPEEDUP_OVER_BASEIMPL = 23,
    COMPARE_REVERSE_REFINE_IMPACT_ON_QUALITY = 24,

    COMPARE_FIRST_MERGING_NODE_KERNEL_BREAKDOWN = 25,
    COMPARE_SECOND_MERGING_NODE_KERNEL_BREAKDOWN = 26,

    PROFILE_EACH_PHASE_BREAKDOWN = 27,
    PROFILE_EACH_KERNEL_BREAKDOWN = 28,

    TEST_ALL_OPT_COMBINATIONS_FOR_EACH_WORKLOAD = 29,

    TEST_DETERMINISTIC_IMPACT_ITER_I_MATCHING_POLICY_KERNEL = 30,

    PROFILE_ITERATION_WISE_KERNEL_BREAKDOWN = 31,

    COMPARE_BEST_QUALITY_BEST_PERF_WITH_BASELINE = 32,

    PROFILE_FIRST_ITER_K12_BREAKDOWN = 33,

    PROFILE_K1K2K3_BREAKDOWN_COMPARISON = 34,

    PROFILE_EACH_ITER_K12_BREAKDOWN = 35,

    PROFILE_EACH_ITER_SPLIT_K4_BREAKDOWN = 36,

    PROFILE_EACH_ITER_SPLIT_K6_BREAKDOWN = 37,

    COMPARE_K12_MEMOPT_BREAKDOWN = 38,

    COMPARE_K12_BREAKDOWN_WITH_MODELING_METRICS = 39,

    COMPARE_K4_BREAKDOWN_WITH_MODELING_METRICS = 40,

    COMPARE_K6_BREAKDOWN_WITH_MODELING_METRICS = 41,

    RECORD_PERFORMANCE_USING_GRAPH_REORDERING = 42,

    COMPARE_BASELINE_WITH_BEST_PERFORMANCE = 43,

    COMPARE_KERNEL_TIME_WITH_MEMCOPY_TIME = 44,

    COARSENING_STAGE_BREAKDOWN = 45,

    MOTIVATION_DATA_HEDGESIZE_IMBALANCE = 46,

    MOTIVATION_DATA_WORK_COMPLEXITY = 47,

    MOTIVATION_DATA_IRREGULAR_ACCESS = 48,

    MOTIVATION_DATA_THREAD_UTILIZATION = 49,

    MOTIVATION_DATA_HEDGESIZE_IMBALANCE_WITH_NCU_METRIC = 50,

    MOTIVATION_DATA_THREAD_UTILIZATION_WITH_NCU_METRIC = 51,

    MOTIVATION_DATA_IRREGULAR_ACCESS_WITH_NCU_METRIC = 52,

    NCU_METRIC_DATA_FOR_KERNEL_SELECTION_METRIC = 51,

    PROFILE_AVG_HEDGE_NUM_PROCESSED_PER_SECOND = 52,

    COARSENING_STAGE1_SPEEDUP_OVER_BASELINE = 53,

    COARSENING_STAGE2_SPEEDUP_OVER_BASELINE = 54,

    COARSENING_STAGE4_SPEEDUP_OVER_BASELINE = 55,

    REORDERING_SPEEDUP_OVER_BASELINE = 56,

    MOTIVATION_DATA_FOR_KERNEL_SELECTION = 57,

    COMPARE_KERNEL_TIME_WITH_OTHER_TIME = 58,

    MOTIVATION_DATA_WORK_COMPLEXITY_WITH_NCU_METRIC = 59,

    SLOWEST_THREAD_IMPACT_ON_DUPLICATE_REMOVAL_KERNEL = 60,

    MOTIVATION_DATA_FOR_KERNEL4_SELECTION = 61,

    MOTIVATION_DATA_FOR_KERNEL6_SELECTION = 62,

    NODE_MERGING_AND_CONSTRUCTION_PERCENTAGE = 63,

    DIFFERENT_PATTERNS_ON_CONSTRUCTION_PERF = 64,

    DIFFERENT_PATTERNS_ON_NODE_MERGING_PERF = 65,

    EDGE_CUT_QUALITY_COMPARISON = 66,

    PROFILE_DETERMINISTIC_OVERHEAD = 67,
};

enum MATCHING_POLICY {
    RAND = 0,
    HDH = 1,
    LDH = 2,
    LSNWH = 3, // LOW_SUM_NODE_WEIGHT_HIGH_PRIORITY
    HSNWH = 4, // HIGH_SUM_NODE_WEIGHT_HIGH_PRIORITY
    LRH = 5, // LOW_SUM_NODE_WEIGH_BY_DEGREE_HIGH_PRIORITY
    HRH = 6, // HIGH_SUM_NODE_WEIGH_BY_DEGREE_HIGH_PRIORITY
};

enum OPTIMIZATIONS {
    BEST_POLICY = 0,
    BEST_WEIGHT_THRESHOLD = 1,
    BEST_POLICY_BEST_LIMIT = 2,
    FIX_HEAVIEST_NODE = 3,
    GAIN_RECALCULATION = 4,
    BALANCE_RELAXATION = 5,
    ADAPTIVE_MOVING = 6,
    MERGING_MOVE = 7,
    FIX_NODE_ADAP_MOVE = 8,
};

class OptionConfigs {
public:
    std::string filepath = "";
    std::string filename = "";
    bool runBipartWeightConfig = false;
    unsigned coarseI_weight_limit = INT_MAX;
    unsigned coarseMore_weight_limit = INT_MAX;
    unsigned exp_id = 0;
    bool run_without_params = false;
    unsigned matching_policy = 0;
    bool runBipartBestPolicy = false;
    unsigned refineIterPerLevel = 2;
    bool runDebugMode = false;
    bool useBipartRatioComputation = true;
    bool makeBalanceExceptFinestLevel = false;
    bool runBaseline = false;
    int useInitPartitionOpts = 0;
    int useRefinementOpts = 0;
    int useCoarseningOpts = 0;
    int switchToMergeMoveLevel = INT_MAX;//0;
    bool useBalanceRelax = false;
    bool useFirstTwoOptsOnly = false;
    int changeRefToParamLevel = 0;
    int coarseMoreFlag = 0;
    bool useCUDAUVM = true;
    std::unordered_set<OPTIMIZATIONS> optsets;
    std::vector<std::pair<std::string, float>> coarsen_kernel_breakdown;
    std::vector<std::vector<std::pair<std::string, float>>> iterate_kernel_breakdown;
    bool useNewKernel12 = false;
    bool sortHedgeLists = false;
    bool useNewKernel14 = false;
    bool useNewKernel5 = false;
    bool useNewKernel1_2_3 = false;
    bool run_bug = false;
    bool runReverseRefine = false;
    bool optForKernel4 = false;
    bool optForKernel6 = false;
    bool useNewTest4 = false;
    bool useNewTest5 = false;
    bool useNewTest6 = false;
    int splitK6ForFindCands = 0; // 0 for hedge wise, 1 for adjlist wise
    int splitK6ForFindRep = 0;
    int splitK6ForMerging = 0;
    bool useTWCoptForKernel6 = false;
    bool useReduceOptForKernel6 = false;
    bool useTWCThreshold = false;
    bool tuneTWCThreshold = false;
    int blocksize[4] = {128, 128, 128, 1024};
    int twc_threshod[2] = {50, 5000};
    bool useWarpBased = false;
    bool useMarkListForK6 = false;
    bool testDeterminism = false;
    bool useThrustRemove = false;
    int cpct_method = 0;
    bool useCommonDefRatio = false;
    int comb_len = 8;
    std::vector<float> iterative_K12;
    std::vector<int> iterative_K12_num_checks;
    std::vector<unsigned long> iterative_K12_num_opcost;
    std::vector<unsigned long> iterative_K12_num_memops;
    std::vector<unsigned long> iterative_K12_num_cptops;
    std::vector<unsigned long> iter_perthread_K12_numopcost;
    std::vector<float> iter_partial_K12;
    std::vector<int> iterative_hedgenum;
    std::vector<int> iterative_nodenum;
    std::vector<int> iterative_adjlist_size;
    std::vector<int> iterative_maxhedgesize;
    std::vector<long double> iterative_avghedgesize;
    std::vector<long double> iterative_sdhedgesize;
    std::vector<float> iterative_time;
    std::vector<float> iterative_K4;
    std::vector<float> iterative_K6;
    std::vector<std::vector<float>> iterative_split_K4;
    std::vector<std::vector<float>> iterative_split_K6;
    std::vector<unsigned long> iterative_K4_num_opcost;
    std::vector<unsigned long> iter_perthread_K4_numopcost;
    std::vector<std::vector<long double>> iterative_split_K4_in_kernel;
    std::vector<unsigned long> iterative_K6_num_opcost;
    std::vector<float> iterative_K14;
    int useNewParalOnBaseK12 = 0;
    int useMemOpt = 0; // 1 for useTempAdjParList
    int useNewParalOnBaseK14 = 0;
    bool transformInput = false;
    bool useTransInput = false;
    bool testSpGEMM = false;
    bool pureSplitK4 = false;
    bool perfOptForRefine = false;
    bool sortInputById = false;
    bool useKernelSelection = false;
    bool testOptPerf = false;
    bool testFirstIter = false;
    bool testK12IdealWork = false;
    bool testK12NoLongestHedge = false;
    bool enableSelection = false;
    bool runBruteForce = false;
    bool testCPUImp = false;
    int input_avgsize_thres = 25;
    int input_skewness_thres = 3;
    bool useP2ForNodeMergingK4 = false;
    bool useP2ForNodeMergingK6 = false;
    bool useP2ForMatching = false;
    bool start = false;
    bool randomSelection = false;
    bool sortingOverhead = false;
    int numPartitions = 2;
    int blockdim = 128;
    int runRefine = 1;

    void parse_cmd(int argc, char** argv);
    
    void select_best_policy(std::string filename);

    void select_best_weight_threshold(std::string filename);

    void statistics2csv();

    void printBanner() {
        std::cout << "(+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++)\n";
        std::cout << "(+                            _    _       _____                               +)\n";
        std::cout << "(+                           | |  | |     |  __ \\                              +)\n";
        std::cout << "(+               __          | |  | |     | |  \\ |                             +)\n";
        std::cout << "(+              |__|   ____  | |__| |_   _| |__/ |___  _ __                    +)\n";
        std::cout << "(+                 |  |____| |  __  | | | |  ___/  _ `| '__|                   +)\n";
        std::cout << "(+              \\__/         | |  | | | | | |   | (_| | |                      +)\n";
        std::cout << "(+                           | |  | | |_| | |    \\___/|_|                      +)\n";
        std::cout << "(+                           |_|  |_|   |_|_|                                  +)\n";
        std::cout << "(+                                   ___/ |                                    +)\n";
        std::cout << "(+                                  |___ /                                     +)\n";
        std::cout << "(+                                                                             +)\n";
        std::cout << "(+          GPU-based Multilevel Hypergraph Partitioning System                +)\n";
        std::cout << "(+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++)\n";
    }

    Stats stats;
};
