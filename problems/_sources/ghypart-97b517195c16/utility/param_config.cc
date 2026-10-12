#include "param_config.h"
#include <iostream>
#include <limits.h>
#include <sys/time.h>
#include <getopt.h>
#include <fstream>
#include <string>
#include <experimental/filesystem>

void OptionConfigs::parse_cmd(int argc, char** argv) {
    std::cout << "argc: " << argc << "\n";
    if (argc == 2) {
        run_without_params = true;
    }
    filepath = argv[1];
    filename = std::experimental::filesystem::path(filepath).filename();
    for (int i = 2; i < argc; ++i) {
        std::string opt = std::string(argv[i]);
        if (opt == "-wc" || opt == "--wc") { // weight constraint
            if (atoi(argv[i+1]) == 0) {
                runBipartWeightConfig = true;
            } else if (atoi(argv[i+1]) == 1) {
                runBipartWeightConfig = false;
                coarseI_weight_limit = atoi(argv[i+2]);
                coarseMore_weight_limit = coarseI_weight_limit;//INT_MAX;//atoi(argv[i+3]);//
                if (std::string(argv[i+3]) == "-cwflag") {
                    coarseMoreFlag = atoi(argv[i+4]);
                    coarseMore_weight_limit = coarseMoreFlag == 1 ? INT_MAX : coarseMore_weight_limit;
                }
            }
        }
        if (opt == "-exp") {
            exp_id = atoi(argv[++i]);
        }
        if (opt == "-bal" || opt == "--bal") {
            stats.imbalance_ratio = std::stof(argv[++i]);
        }
        if (opt == "-RAND") { // matching_policy
            matching_policy = RAND;//0;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-HDH") {
            matching_policy = 1;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-LDH") {
            matching_policy = 2;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-LSNWH") {
            matching_policy = 3;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-HSNWH") {
            matching_policy = 4;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-LRH") {
            matching_policy = 5;
            if (argc == 3)  runBipartBestPolicy = true;
        } else if (opt == "-HRH") {
            matching_policy = 6;
            if (argc == 3)  runBipartBestPolicy = true;
        }
        if (opt == "-r") {
            refineIterPerLevel = atoi(argv[++i]);
        }
        if (opt == "-debug" || "-d") {
            runDebugMode = true;
        }
        if (opt == "-brc") {
            useBipartRatioComputation = atoi(argv[i+1]) == 1 ? true : false;
        }

        if (opt == "-bp") { // indicate best policy
            runBipartBestPolicy = true;
            useCoarseningOpts += BEST_POLICY;
            select_best_policy(filename);
        }
        if (opt == "-bwt") { // indicate best weight threshold
            useCoarseningOpts += BEST_WEIGHT_THRESHOLD;
            select_best_weight_threshold(filename);
        }
        if (opt == "-rbf") { // rebalance at finest level
            makeBalanceExceptFinestLevel = true;
        }
        if (opt == "-rbase") {
            runBaseline = true;
        }
        if (opt == "-init_opt") {
            useInitPartitionOpts = atoi(argv[++i]);
        }
        if (opt == "-ref_opt") {
            useRefinementOpts = atoi(argv[++i]);
        }
        if (opt == "-m") { // indicate #levels using merge_nodelist_moving
            switchToMergeMoveLevel = atoi(argv[++i]);
        }
        if (opt == "-coar_opt") {
            useCoarseningOpts = atoi(argv[++i]);
        }
        if (opt == "-balance_relax") {
            atoi(argv[i+1]) == 0 ? useBalanceRelax = false : useBalanceRelax = true;
        }
        if (opt == "-adjust_refineTo") {
            changeRefToParamLevel = atoi(argv[++i]);
        }
        if (opt == "-useuvm") {
            useCUDAUVM = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-usenewkernel12") {
            useNewKernel12 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-sort") {
            sortHedgeLists = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-usenewkernel14") {
            useNewKernel14 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-usenewkernel5") {
            useNewKernel5 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-usenewkernel1_2_3") {
            useNewKernel1_2_3 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-runbug") {
            run_bug = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-reverseRef") {
            runReverseRefine = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useKernel4Opt") {
            optForKernel4 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useKernel6Opt") {
            optForKernel6 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useNewTest4") {
            useNewTest4 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useNewTest5") {
            useNewTest5 = atoi(argv[i+1]) == 0 ? 0 : 1;
            // useNewTest5 = atoi(argv[i+1]);
        }
        if (opt == "-useNewTest6") {
            useNewTest6 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useTWCKernel6") {
            useTWCoptForKernel6 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useReduceOpt") {
            useReduceOptForKernel6 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt.find("-blocksize") != std::string::npos) {
            std::stringstream ss(opt.substr(11));
            int count = 0;
            while (!ss.eof()) {
                std::string word;
                std::getline(ss, word, ',');
                blocksize[count] = stoi(word);
                std::cout << blocksize[count] << ",";
                count++;
            }
            std::cout <<"\n";
        }
        if (opt.find("-twcThreshold") != std::string::npos) {
            std::stringstream ss(opt.substr(14));
            int count = 0;
            while (!ss.eof()) {
                std::string word;
                std::getline(ss, word, ',');
                twc_threshod[count] = stoi(word);
                std::cout << twc_threshod[count] << ",";
                count++;
            }
            std::cout <<"\n";
        }
        if (opt == "-useTWCThr") {
            useTWCThreshold = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-tuneTWCThr") {
            tuneTWCThreshold = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useWarp") {
            useWarpBased = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useMarkForK6") {
            useMarkListForK6 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-testDet") {
            testDeterminism = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-cpct_method") {
            cpct_method = atoi(argv[i+1]);
        }
        if (opt == "-useRemove") {
            useThrustRemove = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-newParBaseK12") {
            useNewParalOnBaseK12 = atoi(argv[i+1]);
        }
        if (opt == "-useMemOpt") {
            useMemOpt = atoi(argv[i+1]);
        }
        if (opt == "-newParBaseK14") {
            useNewParalOnBaseK14 = atoi(argv[i+1]);
        }
        if (opt == "-transInput") {
            transformInput = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useTransInput") {
            useTransInput = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-testSpGEMM") {
            testSpGEMM = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-pureSplitK4") {
            pureSplitK4 = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-ref_perfopt") {
            perfOptForRefine = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-sort_input") {
            sortInputById = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-kernel_adapt") {
            useKernelSelection = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-test_opt_perf") {
            testOptPerf = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-test_first_iter") {
            testFirstIter = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-test_no_scan") {
            testK12IdealWork = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-test_no_longest_hedge") {
            testK12NoLongestHedge = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useSelection") {
            enableSelection = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-useOracular") {
            runBruteForce = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-testCPU") {
            testCPUImp = atoi(argv[i+1]) == 0 ? false : true;
        }
        if (opt == "-input_avgsize_thres") {
            input_avgsize_thres = atoi(argv[i+1]);
        }
        if (opt == "-input_skewness_thres") {
            input_skewness_thres = atoi(argv[i+1]);
        }
        if (opt == "-useP2ForK4") {
            useP2ForNodeMergingK4 = atoi(argv[i+1]);
        }
        if (opt == "-useP2ForK6") {
            useP2ForNodeMergingK6 = atoi(argv[i+1]);
        }
        if (opt == "-useP2ForK1") {
            useP2ForMatching = atoi(argv[i+1]);
        }
        if (opt == "-randomSelect") {
            randomSelection = atoi(argv[i+1]);
        }
        if (opt == "-sortOverhead") {
            sortingOverhead = atoi(argv[i+1]);
        }
        if (opt == "-numPartitions") {
            numPartitions = atoi(argv[i+1]);
        }
        if (opt == "-runRefine") {
            runRefine = atoi(argv[i+1]);
        }
    }
}

void OptionConfigs::select_best_policy(std::string filename) {
#if 0
    if (filename.find("wb-edu") != std::string::npos) {
        matching_policy = 0;
    }
    if (filename.find("webbase-1M") != std::string::npos) {
        matching_policy = 0;
    }
    if (filename.find("ISPD98_ibm17") != std::string::npos) {
        matching_policy = 0;
    }

    if (filename.find("sat14_series_bug7_dual") != std::string::npos) {
        matching_policy = 1;
    }
    if (filename.find("ISPD98_ibm18") != std::string::npos) {
        matching_policy = 1;
    }
    
    if (filename.find("human_gene2") != std::string::npos) { // best quality
        matching_policy = 2;
    }
    if (filename.find("G67") != std::string::npos) {
        matching_policy = 2;
    }
    if (filename.find("ecology1") != std::string::npos) {
        matching_policy = 2;
    }
    if (filename.find("nlpkkt120") != std::string::npos) {
        matching_policy = 2;
    }

    if (filename.find("af_4_k101") != std::string::npos) {
        matching_policy = 3;
    }

    if (filename.find("sat14_series_bug7_primal") != std::string::npos) { // best quality
        matching_policy = 4;
    }

    if (filename.find("Stanford") != std::string::npos) {
        matching_policy = 5;
    }

    if (filename.find("gupta3") != std::string::npos) {
        matching_policy = 5;
    }

    if (filename.find("Chebyshev4") != std::string::npos) {
        matching_policy = 1;//3;//
    }

    if (filename.find("Hamrle3") != std::string::npos) {
        matching_policy = 2;
    }

    if (filename.find("StocF-1465") != std::string::npos) {
        matching_policy = 0;
    }

    if (filename.find("sls") != std::string::npos) {
        matching_policy = 4;
    }

    if (filename.find("trans4") != std::string::npos) {
        matching_policy = 4;
    }

    if (filename.find("circuit5M") != std::string::npos) {
        matching_policy = 0;
    }

    if (filename.find("dac2012_superblue19") != std::string::npos) {
        matching_policy = 2;
    }

    if (filename.find("dac2012_superblue12") != std::string::npos) {
        matching_policy = 1;//2;
    }

    if (filename.find("dac2012_superblue9") != std::string::npos) {
        matching_policy = 6;
    }

    if (filename.find("language") != std::string::npos) {
        matching_policy = 4;
    }

    if (filename.find("kron_g500-logn16") != std::string::npos) {
        matching_policy = 5;
    }

    if (filename.find("case39") != std::string::npos) {
        matching_policy = 1;//3;
    }

    if (filename.find("us04") != std::string::npos) {
        matching_policy = 1;
    }
#endif
    if (filename.find("RM07R") != std::string::npos) {
        // matching_policy = 6;
    }

    if (filename.find("FullChip") != std::string::npos) {
        matching_policy = 1;
    }
}

void OptionConfigs::select_best_weight_threshold(std::string filename) {
    if (filename.find("wb-edu") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 3100;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("webbase-1M") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 70000;//56000;//
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("ISPD98_ibm17") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 40000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("sat14_series_bug7_dual") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 57000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("ISPD98_ibm18") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 43000;//68000;//
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    
    if (filename.find("human_gene2") != std::string::npos) { // best quality
        runBipartWeightConfig = false;
        coarseI_weight_limit = 8000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("G67") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 1600;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("ecology1") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 17500;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("RM07R") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 23000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
    if (filename.find("nlpkkt120") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 500000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("af_4_k101") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 49000;//62000;//
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("sat14_series_bug7_primal") != std::string::npos) { // best quality
        runBipartWeightConfig = false;
        coarseI_weight_limit = 30000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("Stanford") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 32000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("gupta") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 2200; // 900 -> 9413
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("Cheb") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 16000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("trans4") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 18000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("Hamrle3") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 165000; // -> 2181
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("StocF-1465") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 63000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("language") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 60000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("kron") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 3100; // 3100 -> 15712
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("case39") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 2000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("dac2012_superblue9") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 45000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("dac2012_superblue12") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 58000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }

    if (filename.find("dac2012_superblue19") != std::string::npos) {
        runBipartWeightConfig = false;
        coarseI_weight_limit = 95000;
        coarseMore_weight_limit = coarseI_weight_limit;
    }
}

void OptionConfigs::statistics2csv() {
    // std::cout << __FUNCTION__ << "\n";
    if (exp_id == PROFILE_WEIGHT_CONSTRAIT_CONFIGS) {
        // std::string output = "../debug/" + filename + "_profile_weight_constraint_impact_results.csv";
        std::string output = filename + "_profile_weight_constraint_impact_results.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        // out << coarseI_weight_limit << "," << coarseMore_weight_limit << "," << stats.total_time << "," << stats.hyperedge_cut << "\n";
        out << coarseI_weight_limit << "," << coarseMore_weight_limit << "," << stats.total_time << "," << stats.hyperedge_cut_num << ", " 
            << stats.maxNodeWeight << ", " << stats.total_node_num << ", " << (double)coarseI_weight_limit / stats.total_node_num << "\n";
        out.close();
    }

    if (exp_id == COMPARE_BASE_WITH_WEIGHT_LIMIT_OPT) {
        std::string output = "../opts_stats/weight_limit_opt_quality_improvement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.hyperedge_cut << "\n";
        out.close();
    }

    if (exp_id == COMPARE_BASE_WITH_NODE_FIXING_OPT) {
        std::string output = "../opts_stats/larget_node_fixing_opt_quality_improvement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.hyperedge_cut << "\n";
        out.close();
    }

    if (exp_id == COMPARE_BASE_WITH_GAIN_RECALCULATION_OPT) {
        std::string output = "../opts_stats/gain_recalculation_opt_quality_improvement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.hyperedge_cut << "\n";
        out.close();
    }

    if (exp_id == COMPARE_BASE_WITH_MERGING_MOVE_OPT) {
        std::string output = "../opts_stats/merging_move_opt_quality_improvement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.hyperedge_cut << "\n";
        out.close();
    }

    if (exp_id == COMPARE_BASE_WITH_BEST_QUALITY_RESULTS) {
        std::string output = "../opts_stats/best_quality_improvement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.hyperedge_cut << "\n";
        out.close();
    }

    if (exp_id == COMPARE_PERF_WITH_NON_UVM_IMPL) {
        std::string output = "../opts_stats/no_uvm_base_perf_comparison_with_uvm_baseline.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        if (useCUDAUVM == true) {
            out << "using uvm and cudamemprefetching, \n";
            // out << filename << ", coarsen kernel time: " << stats.coarsen_time << "\n";
            // out << filename << ", partition kernel time: " << stats.partition_time << "\n";
            out << filename << "," << stats.total_time << "," << stats.coarsen_time << "," << stats.partition_time << "," << stats.Refine_time << "\n";
        } else {
            out << "using cudamalloc and cudamemcpy, \n";
            // out << filename << ", coarsen kernel time: " << stats.coarsen_time << ", cudamalloc+cudamemcpy time: " << stats.coarsen_cuda_memcpy_time << "\n";
            // out << filename << ", partition kernel time: " << stats.partition_time << "\n";
            out << filename << "," << stats.total_time << "," << stats.coarsen_time << "," << stats.partition_time << "," << stats.Refine_time << "\n";
        }
        out.close();
    }

    if (exp_id == PRINT_ALLOCATE_MEM_SPACE) {
        std::string output = "../opts_stats/allocated_gpu_memory_size.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << filename << "," << stats.memBytes / (1024.f * 1024.f * 1024.f) << ",GB\n";
        out.close();
    }

    if (exp_id == COMPARE_PERF_WITH_SINGLE_REBALANCE_SORT) {
        std::string output = "../opts_stats/single_rebalance_sort_perf_comparison_with_uvm_baseline.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        if (useCUDAUVM == true) {
            out << "using uvm and cudamemprefetching, \n";
            // out << filename << ", coarsen kernel time: " << stats.coarsen_time << "\n";
            // out << filename << ", partition kernel time: " << stats.partition_time << "\n";
            out << filename << "," << stats.total_time << "," << stats.coarsen_time << "," << stats.partition_time << "," << stats.Refine_time << "\n";
        } else {
            out << "using cudamalloc and cudamemcpy, \n";
            // out << filename << ", coarsen kernel time: " << stats.coarsen_time << ", cudamalloc+cudamemcpy time: " << stats.coarsen_cuda_memcpy_time << "\n";
            // out << filename << ", partition kernel time: " << stats.partition_time << "\n";
            out << filename << "," << stats.total_time << "," << stats.coarsen_time << "," << stats.partition_time << "," << stats.Refine_time << "\n";
        }
        out.close();
    }
    
    if (exp_id == COMPARE_E2E_PERF_WITH_BITSET_MARKING_OPT) {
        std::string output = "../opts_stats/perf_impact_with_using_bitset_opt" + stats.suffix + ".csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << ",";
        out.close();
    }
    if (exp_id == COMPARE_QUALITY_WITH_ADDING_SORTING) {
        std::string output = "../opts_stats/quality_impact_with_using_cubsort_opt.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.hyperedge_cut_num << ",";
        out.close();
    }
    if (exp_id == COMPARE_E2E_PERF_WITH_ATOMIC_WRITE_ADJLIST) {
        std::string output = "../opts_stats/perf_impact_with_atomic_write_adjlist_opt.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.hyperedge_cut_num << ",";
        out.close();
    }
    if (exp_id == COMPARE_E2E_PERF_WITH_KERNEL1_2_3_OPT) {
        // std::string output = "../opts_stats/perf_comparison_with_using_new_kernel123" + stats.suffix + ".csv";
        std::string output = "../opts_stats/perf_comparison_with_using_new_kernel123.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << ",";
        out.close();
    }
    if (exp_id == COMPARE_E2E_PERF_WITH_KERNEL5_OPT) {
        // std::string output = "../opts_stats/perf_comparison_with_using_new_kernel5" + stats.suffix + ".csv";
        std::string output = "../opts_stats/perf_comparison_with_using_new_kernel5.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << ",";
        out.close();
    }
    if (exp_id == PROFILE_OVERALL_COARSEN_SPEEDUP_OVER_BASEIMPL) {
        // std::string output = "../opts_stats/perf_comparison_with_using_new_coarsening_opts" + stats.suffix + ".csv";
        std::string output = "../opts_stats/perf_comparison_with_using_new_coarsening_opts.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << ",";
        out.close();
    }
    if (exp_id == COMPARE_REVERSE_REFINE_IMPACT_ON_QUALITY) {
        std::string output = "../opts_stats/quality_impact_with_reverse_refinement.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.hyperedge_cut_num << ",";
        out.close();
    }
    if (exp_id == PROFILE_EACH_PHASE_BREAKDOWN) {
        std::string output = "../opts_stats/profile_each_phase_breakdown.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.coarsen_time << "," << stats.partition_time << "," << stats.Refine_time << "\n";
        out.close();
    }
    if (exp_id == PROFILE_EACH_KERNEL_BREAKDOWN) {
        std::string output = "../opts_stats/profile_each_kernel_breakdown.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        for (int i = 0; i < coarsen_kernel_breakdown.size(); ++i) {
            out << coarsen_kernel_breakdown[i].second << ",";
        }
        out << "\n";
        out.close();
    }
    if (exp_id == TEST_ALL_OPT_COMBINATIONS_FOR_EACH_WORKLOAD) {
        std::string output = "../opts_stats/" + filename + "_performance.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << "usenewkernel12 = " << useNewKernel12 << "\n";
        out << "sort = " << sortHedgeLists << "\n";
        out << "usenewkernel14 = " << useNewKernel14 << "\n";
        out << "usenewkernel1_2_3 = " << useNewKernel1_2_3 << "\n";
        out << "useKernel4Opt = " << optForKernel4 << "\n";
        out << "usenewkernel5 = " << useNewKernel5 << "\n";
        out << "useKernel6Opt = " << optForKernel6 << "\n";
        out << "useTWCKernel6 = " << useTWCoptForKernel6 << "\n";
        out << "useWarp = " << useWarpBased << "\n";
        out << "useMarkForK6 = " << useMarkListForK6 << "\n";
        out << "coarsen_time:" << stats.coarsen_time << "\n";
        out << "partition_time:" << stats.partition_time << "\n";
        out << "refine_time:" << stats.Refine_time << "\n";
        out << "total_time:" << stats.total_time << "\n";
        out << "#edge_cut:" << stats.hyperedge_cut_num << "\n";
        out << "\n";
        out.close();
    }
    if (exp_id == COMPARE_BEST_QUALITY_BEST_PERF_WITH_BASELINE) {
        std::string output = "../opts_stats/compare_bestquality_bestperf_with_baseline.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << "," << stats.hyperedge_cut_num << ",";
        out.close();
    }
    
    if (exp_id == RECORD_PERFORMANCE_USING_GRAPH_REORDERING) {
        // std::string output = "hyperedge_reordering_impact.csv";
        std::string output = useTransInput ? "../reordering_results/" + filename + "_hyperedge_reordering_results.csv" : 
                        "../reordering_results/trans_" + filename + "_hyperedge_reordering_results.csv";
        std::cout << "dump obtained stats to csv for " << output << "\n";
        std::ofstream out(output, std::ios::app);
        if (!useTransInput) {
            out << "original baseline: containing " << stats.total_hedge_num << " hyperedges.\n";
            out << "only contains " << stats.total_nondup_hedgenum << " non-duplicate hyperedges!!!\n";
        } else {
            out << "transformed input:\n";
        }
        out << "policy:";
        if (matching_policy == RAND) {
            out << "RAND\n";
        } else if (matching_policy == HDH) {
            out << "HDH\n";
        } else if (matching_policy == LDH) {
            out << "LDH\n";
        } else if (matching_policy == LSNWH) {
            out << "LSNWH\n";
        } else if (matching_policy == HSNWH) {
            out << "HSNWH\n";
        } else if (matching_policy == LRH) {
            out << "LRH\n";
        } else if (matching_policy == HRH) {
            out << "HRH\n";
        }
        out << "coarsening time:" << stats.coarsen_time << "\n";
        out << "total time:" << stats.total_time << "\n";
        out << "edge cut:" << stats.hyperedge_cut_num << "\n";
    }

    if (exp_id == REORDERING_SPEEDUP_OVER_BASELINE) {
        std::string output = "../opts_stats/performance_comparison_with_reordering.csv";
        std::ofstream out(output, std::ios::app);
        out << stats.coarsen_time << ", " << stats.total_time << ", " << stats.hyperedge_cut_num << ", ";
    }

    if (exp_id == COMPARE_BASELINE_WITH_BEST_PERFORMANCE) {
        std::string output = "../opts_stats/performance_comparison_with_best.csv";
        std::ofstream out(output, std::ios::app);
        // out << "useNewK123:" << optCfgs.useNewKernel1_2_3 << ", useSplitK4:" << optCfgs.optForKernel4 << ", use";
        // out << stats.total_time << "," << stats.hyperedge_cut_num << ",";
        out << stats.total_time << ",";
    }

    if (exp_id == COMPARE_KERNEL_TIME_WITH_MEMCOPY_TIME) {
        std::string output = "../opts_stats/kernel_time_vs_memcopy_time_breakdown.csv";
        std::ofstream out(output, std::ios::app);
        out << stats.total_time << "," << stats.memcpy_time << ",";
    }
}

